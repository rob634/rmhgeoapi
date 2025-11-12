# Platform Layer Pydantic & Enum Pattern Consistency

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document Pydantic and enum usage patterns - ensure Platform mirrors CoreMachine

## Overview

**CRITICAL**: Platform layer must use identical Pydantic/enum patterns as CoreMachine to maintain consistency and type safety throughout the system.

## Core Principle: Enums, Not Strings

```python
# ❌ WRONG - String values
status = 'queued'
data_type = 'raster'

# ✅ CORRECT - Enum values
status = JobStatus.QUEUED
data_type = DataType.RASTER
```

## CoreMachine Enum Patterns

### JobStatus Enum

**File**: `core/models/enums.py`

```python
from enum import Enum

class JobStatus(Enum):
    """Valid status values for jobs"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
```

**Usage in CoreMachine**:

```python
from core.models.enums import JobStatus
from core.models.job import JobRecord

# Creating job record
job = JobRecord(
    job_id="abc123...",
    job_type="hello_world",
    status=JobStatus.QUEUED,  # ✅ Enum value
    parameters={"message": "Hello"}
)

# Status transitions
if job.status == JobStatus.PROCESSING:
    job.status = JobStatus.COMPLETED
```

### TaskStatus Enum

**File**: `core/models/enums.py`

```python
class TaskStatus(Enum):
    """Valid status values for tasks"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    PENDING_RETRY = "pending_retry"
    CANCELLED = "cancelled"
```

**Usage in CoreMachine**:

```python
from core.models.enums import TaskStatus
from core.models.task import TaskRecord

task = TaskRecord(
    task_id="xyz789...",
    job_id="abc123...",
    status=TaskStatus.QUEUED,  # ✅ Enum value
    task_type="greet"
)
```

## Platform Layer Enum Patterns

### PlatformRequestStatus Enum

**File**: `triggers/trigger_platform.py`

```python
from enum import Enum

class PlatformRequestStatus(str, Enum):
    """Platform request status - mirrors JobStatus pattern"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
```

**Note**: Platform uses `PENDING` (not `QUEUED`) because platform requests don't go in queues - they're HTTP requests that immediately spawn CoreMachine jobs.

### DataType Enum

**File**: `triggers/trigger_platform.py`

```python
class DataType(str, Enum):
    """Supported data types for processing"""
    RASTER = "raster"
    VECTOR = "vector"
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"
```

## Platform Request Models

### PlatformRequest (HTTP Request Body)

```python
from pydantic import BaseModel, Field

class PlatformRequest(BaseModel):
    """Platform request from external application (DDH)"""
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: DataType  # ✅ Enum type annotation
    source_location: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    client_id: str
```

**Usage**:

```python
# Pydantic automatically validates and converts
req_body = {
    "dataset_id": "test",
    "data_type": "raster",  # String in JSON
    # ...
}

platform_req = PlatformRequest(**req_body)
print(platform_req.data_type)  # DataType.RASTER (enum)
print(platform_req.data_type.value)  # "raster" (string)
```

### PlatformRecord (Database Model)

```python
class PlatformRecord(BaseModel):
    """Platform request database record"""
    request_id: str
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: str  # Store as string in DB
    status: PlatformRequestStatus = Field(default=PlatformRequestStatus.PENDING)  # ✅ Enum
    job_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            'request_id': self.request_id,
            'dataset_id': self.dataset_id,
            'status': self.status.value if isinstance(self.status, Enum) else self.status,  # ✅ Convert enum to string
            # ...
        }
```

## Platform Creates CoreMachine Jobs - CRITICAL PATTERN

**File**: `triggers/trigger_platform.py:_create_coremachine_job()`

```python
from core.models.job import JobRecord
from core.models.enums import JobStatus  # ✅ Import CoreMachine enum

async def _create_coremachine_job(
    self,
    request: PlatformRecord,
    job_type: str,
    parameters: Dict[str, Any]
) -> Optional[str]:
    """
    Create a CoreMachine job and submit it to jobs queue.

    CRITICAL: Must use CoreMachine enums (JobStatus) not Platform enums!
    """

    # Generate job ID (SHA256 full 64-char hash)
    job_id = self._generate_job_id(job_type, parameters)

    # Create job record using CoreMachine enum
    job_record = JobRecord(
        job_id=job_id,
        job_type=job_type,
        status=JobStatus.QUEUED,  # ✅ CoreMachine enum (NOT PlatformRequestStatus!)
        parameters=parameters,
        metadata={
            'platform_request': request.request_id,
            'created_by': 'platform_orchestrator'
        }
    )

    # Store in database (app.jobs table)
    stored_job = self.job_repo.create_job(job_record)

    # Submit to Service Bus
    await self._submit_to_queue(stored_job)

    return job_id
```

**Key Insight**: Platform uses `PlatformRequestStatus` for platform requests, but when creating CoreMachine jobs, it uses `JobStatus` enum.

## Common Mistakes and Fixes

### Mistake 1: Using String Instead of Enum

```python
# ❌ WRONG
job_record = JobRecord(
    job_id="abc123",
    job_type="hello_world",
    status='queued',  # String - will fail Pydantic validation
    parameters={}
)

# ✅ CORRECT
from core.models.enums import JobStatus

job_record = JobRecord(
    job_id="abc123",
    job_type="hello_world",
    status=JobStatus.QUEUED,  # Enum - type safe
    parameters={}
)
```

### Mistake 2: Using Platform Enum for CoreMachine Job

```python
# ❌ WRONG - Using Platform enum for CoreMachine job
from triggers.trigger_platform import PlatformRequestStatus

job_record = JobRecord(
    status=PlatformRequestStatus.PENDING  # Wrong enum!
)

# ✅ CORRECT - Using CoreMachine enum for CoreMachine job
from core.models.enums import JobStatus

job_record = JobRecord(
    status=JobStatus.QUEUED  # Correct enum
)
```

### Mistake 3: Truncating SHA256 Hash

```python
# ❌ WRONG - Truncated hash (32 chars)
job_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]

# ✅ CORRECT - Full hash (64 chars)
job_id = hashlib.sha256(canonical.encode()).hexdigest()
```

## Enum Serialization for Database/JSON

### Writing to Database

```python
# Pydantic model with enum
platform_record = PlatformRecord(
    request_id="abc123",
    status=PlatformRequestStatus.PROCESSING  # Enum
)

# Convert enum to string for database
db_dict = {
    'request_id': platform_record.request_id,
    'status': platform_record.status.value  # "processing" (string)
}

# Or use model's to_dict() method
db_dict = platform_record.to_dict()
```

### Reading from Database

```python
# Database returns strings
row = cur.fetchone()
status_str = row['status']  # "processing" (string)

# Pydantic automatically converts to enum
platform_record = PlatformRecord(
    request_id=row['request_id'],
    status=status_str  # Pydantic converts "processing" → PlatformRequestStatus.PROCESSING
)

print(platform_record.status)  # PlatformRequestStatus.PROCESSING (enum)
```

### JSON Responses

```python
# HTTP response serialization
return func.HttpResponse(
    json.dumps({
        'request_id': platform_record.request_id,
        'status': platform_record.status.value,  # ✅ Convert to string for JSON
        'jobs_created': job_ids
    }),
    mimetype='application/json'
)
```

## Enum Pattern Checklist

### ✅ Platform Layer Compliance (29 OCT 2025)

- [x] **PlatformRequestStatus enum** - Defined and used correctly
- [x] **DataType enum** - Defined and used correctly
- [x] **PlatformRequest model** - Uses DataType enum type annotation
- [x] **PlatformRecord model** - Uses PlatformRequestStatus enum with proper serialization
- [x] **Creating CoreMachine jobs** - Uses JobStatus enum (NOT PlatformRequestStatus)
- [x] **Job ID generation** - Full 64-char SHA256 hash (not truncated)
- [x] **Status updates** - Uses PlatformRequestStatus enum for platform requests
- [x] **Database serialization** - Converts enums to strings via .value
- [x] **JSON responses** - Converts enums to strings via .value

## Reference Implementations

### CoreMachine: Job Creation

**File**: `jobs/hello_world.py:create_job_record()`

```python
from core.models.enums import JobStatus
from core.models.job import JobRecord

def create_job_record(self, job_id: str, params: dict) -> dict:
    """Create job record for hello_world job"""
    job_record = JobRecord(
        job_id=job_id,
        job_type=self.job_type,
        status=JobStatus.QUEUED,  # ✅ Enum
        parameters=params,
        metadata={
            'job_type': self.job_type,
            'created_by': 'hello_world_controller'
        }
    )
    return job_record.model_dump()
```

### Platform: Job Creation via CoreMachine

**File**: `triggers/trigger_platform.py:_create_coremachine_job()`

```python
from core.models.enums import JobStatus  # ✅ Import CoreMachine enum
from core.models.job import JobRecord

job_record = JobRecord(
    job_id=job_id,
    job_type=job_type,
    status=JobStatus.QUEUED,  # ✅ Use CoreMachine enum
    parameters=job_params,
    metadata={
        'platform_request': request.request_id,
        'created_by': 'platform_orchestrator'
    }
)
```

## Type Safety Benefits

### IDE Autocomplete

```python
# Enum provides autocomplete
job.status = JobStatus.  # IDE shows: QUEUED, PROCESSING, COMPLETED, FAILED, ...

# String provides no help
job.status = 'qu'  # IDE shows: nothing, prone to typos
```

### Compile-Time Validation

```python
# Enum - invalid value caught by IDE/linter
job.status = JobStatus.INVALID  # ❌ AttributeError at import time

# String - invalid value only caught at runtime
job.status = 'invalid'  # ✅ No error until Pydantic validation
```

### Refactoring Safety

```python
# Change enum value
class JobStatus(Enum):
    QUEUED = "queued"
    # PROCESSING = "processing"  # Rename to IN_PROGRESS
    IN_PROGRESS = "in_progress"

# All usages show errors immediately
job.status = JobStatus.PROCESSING  # ❌ AttributeError (caught immediately)

# With strings, silent bugs
job.status = 'processing'  # ✅ No error, but wrong value in DB
```

## Summary: Pattern Consistency

### Platform Layer ✅ COMPLIANT

1. **Platform Request Status**: Uses `PlatformRequestStatus` enum
2. **Data Type**: Uses `DataType` enum
3. **CoreMachine Job Creation**: Uses `JobStatus` enum (NOT platform enum!)
4. **Database Serialization**: Properly converts enums to strings with `.value`
5. **JSON Responses**: Properly converts enums to strings with `.value`

### CoreMachine Layer ✅ REFERENCE

1. **Job Status**: Uses `JobStatus` enum consistently
2. **Task Status**: Uses `TaskStatus` enum consistently
3. **Raster Type**: Uses `RasterType` enum consistently
4. **No string status values**: All status assignments use enums

---

**Key Takeaway**: Platform mirrors CoreMachine enum patterns, ensuring type safety and consistency throughout the entire system. When Platform creates CoreMachine jobs, it uses CoreMachine enums, not Platform enums.
