# Architecture Reference

**Date**: 15 OCT 2025 (Updated with Job Declaration Pattern)
**Purpose**: Deep technical specifications for the Azure Geospatial ETL Pipeline

## Table of Contents
1. [Job Declaration Pattern (Pattern B)](#job-declaration-pattern-pattern-b)
2. [Database Schema Architecture](#database-schema-architecture)
3. [Data Models](#data-models)
4. [Queue Message Schemas](#queue-message-schemas)
5. [PostgreSQL Functions](#postgresql-functions)
6. [Workflow Definitions](#workflow-definitions)
7. [Factory Patterns](#factory-patterns)
8. [State Transitions](#state-transitions)
9. [Inter-Stage Communication](#inter-stage-communication)
10. [Storage Architecture](#storage-architecture)
11. [Error Handling Strategy](#error-handling-strategy)
12. [Scalability Targets](#scalability-targets)

---

## Job Declaration Pattern (Pattern B)

**Updated**: 15 OCT 2025
**Status**: Official standard - used by all 10 production jobs

### Overview

All jobs in this system use **Pattern B** - simple job classes with declarative blueprints. CoreMachine handles all orchestration machinery.

**Key Principle:** Jobs define WHAT to do (stages, tasks). CoreMachine handles HOW (queuing, execution, completion).

### Job Structure

**Updated 15 OCT 2025**: All jobs now inherit from `JobBase` ABC for interface enforcement.

```python
from jobs.base import JobBase

class YourJobClass(JobBase):  # ← Inherits from JobBase ABC
    """
    Job declaration - pure data + task creation logic.

    This is a blueprint, not a controller. CoreMachine orchestrates everything.

    Inherits from JobBase ABC which enforces the 5 required methods at class
    definition time (Python's ABC mechanism).
    """

    # Job metadata
    job_type: str = "your_job"
    description: str = "What this job does"

    # Stage definitions (plain dicts - NOT Pydantic Stage objects)
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "stage_name",
            "task_type": "handler_name",
            "parallelism": "fixed",  # or "dynamic", "match_previous"
            "count": 1  # if fixed parallelism
        }
    ]

    # Parameter schema (optional but recommended)
    parameters_schema: Dict[str, Any]] = {
        "param1": {"type": "str", "required": True},
        "param2": {"type": "int", "default": 10}
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for a stage.

        This is the ONLY job-specific logic needed.
        Returns plain dicts - CoreMachine converts to TaskDefinition.

        Args:
            stage: Stage number (1-based)
            job_params: Job parameters from submission
            job_id: Unique job identifier
            previous_results: Results from previous stage (for fan-out patterns)

        Returns:
            List of plain dicts with task_id, task_type, parameters
        """
        return [
            {
                "task_id": f"{job_id[:8]}-task-{i}",
                "task_type": "handler_name",
                "parameters": {"param": value}
            }
            for i in range(count)
        ]

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate and normalize parameters.

        REQUIRED by JobBase ABC - must be implemented.

        Args:
            params: Raw parameters from job submission

        Returns:
            Validated parameters with defaults applied

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}
        # Add validation logic
        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID for idempotency.

        REQUIRED by JobBase ABC - must be implemented.

        Args:
            params: Job parameters

        Returns:
            Deterministic job ID string (typically SHA256 hash)
        """
        import hashlib
        import json
        return hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record for database storage.

        REQUIRED by JobBase ABC - must be implemented.

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job record dict (typically {"job_id": ..., "status": ...})
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        job_record = JobRecord(
            job_id=job_id,
            job_type="your_job",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=len(YourJobClass.stages),
            stage_results={},
            metadata={"description": YourJobClass.description}
        )

        repos = RepositoryFactory.create_repositories()
        repos['job_repo'].create_job(job_record)

        return {"job_id": job_id, "status": "queued"}

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue job for processing using Service Bus.

        REQUIRED by JobBase ABC - must be implemented.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        config = get_config()
        service_bus = ServiceBusRepository(
            connection_string=config.get_service_bus_connection(),
            queue_name=config.jobs_queue_name
        )

        message = JobQueueMessage(
            job_id=job_id,
            job_type="your_job",
            stage=1,
            parameters=params,
            message_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4())
        )

        result = service_bus.send_message(message.model_dump_json())

        return {
            "queued": True,
            "queue_type": "service_bus",
            "message_id": message.message_id
        }
```

### JobBase ABC Interface

**File**: `jobs/base.py`
**Purpose**: Enforces the 5 required methods that all jobs must implement

The `JobBase` abstract base class uses Python's ABC mechanism to enforce interface compliance at class definition time (not runtime). This provides:

1. **Earlier error detection**: Missing methods cause `TypeError` when class is defined, not when method is called
2. **IDE support**: Autocomplete, type hints, jump to definition
3. **Official contract**: Python's standard way to define interfaces
4. **Better error messages**: Clear indication of missing abstract methods

**Required Methods (All @staticmethod + @abstractmethod):**

```python
from abc import ABC, abstractmethod

class JobBase(ABC):
    """Abstract base class defining the interface contract for all jobs."""

    @staticmethod
    @abstractmethod
    def validate_job_parameters(params: dict) -> dict:
        """Validate and normalize job parameters."""
        pass

    @staticmethod
    @abstractmethod
    def generate_job_id(params: dict) -> str:
        """Generate deterministic job ID for idempotency."""
        pass

    @staticmethod
    @abstractmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """Create job record for database storage."""
        pass

    @staticmethod
    @abstractmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue job for processing."""
        pass

    @staticmethod
    @abstractmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """Generate task parameters for a stage."""
        pass
```

**Why ABC + @staticmethod?**
- **ABC enforcement**: Python checks methods exist at class definition time
- **@staticmethod**: No `self` needed - jobs are stateless blueprints
- **Decorator order matters**: `@staticmethod` MUST come before `@abstractmethod`

**Error Example (Missing Method):**
```python
class BadJob(JobBase):  # Missing validate_job_parameters
    pass

# TypeError: Can't instantiate abstract class BadJob with abstract methods validate_job_parameters
```

**Migration Notes:**
- Phase 0: Runtime validation via `hasattr()` checks in `jobs/__init__.py`
- Phase 2: Compile-time validation via ABC (completed 15 OCT 2025)
- All 10 production jobs migrated successfully (2-line change per job)

### Registration (Explicit, No Decorators)

```python
# jobs/__init__.py
from .your_job import YourJobClass

ALL_JOBS = {
    "your_job": YourJobClass,
    # ... other jobs ...
}

# function_app.py - Initialization
from jobs import ALL_JOBS
from services import ALL_HANDLERS
from core.machine import CoreMachine

core_machine = CoreMachine(
    all_jobs=ALL_JOBS,  # Explicit registry
    all_handlers=ALL_HANDLERS
)
```

### How CoreMachine Uses Jobs

```python
# Process job message
job_class = ALL_JOBS[job_type]  # Get class from dict
tasks = job_class.create_tasks_for_stage(...)  # Returns plain dicts
task_defs = [TaskDefinition(**t) for t in tasks]  # CoreMachine converts to Pydantic
```

### Task Dictionary Contract (Required by CoreMachine)

When `create_tasks_for_stage()` returns task definitions, **each dict must contain these keys**:

**Required Keys:**
```python
{
    "task_id": str,        # Unique identifier (format: "{job_id[:8]}-s{stage}-{index}")
    "task_type": str,      # Handler function name registered in services/__init__.py
    "parameters": dict     # Task-specific parameters passed to handler
}
```

**Optional Keys:**
```python
{
    "metadata": dict       # Additional task metadata (default: empty dict)
}
```

**Example:**
```python
@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    n = job_params.get('n', 3)
    return [
        {
            "task_id": f"{job_id[:8]}-s{stage}-{i}",  # Required
            "task_type": "hello_world_greeting",       # Required
            "parameters": {                            # Required
                "index": i,
                "message": job_params.get('message')
            },
            "metadata": {"batch": "morning"}           # Optional
        }
        for i in range(n)
    ]
```

**What CoreMachine Does:**
1. Receives plain dicts from `job_class.create_tasks_for_stage()`
2. Validates required keys (raises `KeyError` if missing)
3. Converts to `TaskDefinition` Pydantic objects (type validation)
4. Adds context fields: `parent_job_id`, `job_type`, `stage`, `task_index`
5. Persists to database (`app.tasks` table)
6. Queues to Service Bus (`tasks` queue)

**Contract Enforcement:**
- Missing `task_id`, `task_type`, or `parameters` → `KeyError` at line 268-280 in `core/machine.py`
- Invalid types → Pydantic `ValidationError`
- Caught at job processing time, before tasks are queued

### Pydantic Type Safety (At Boundaries)

Jobs work with **plain dicts**. CoreMachine handles **Pydantic conversion at boundaries**:

1. **Job → CoreMachine:** Plain dict → `TaskDefinition` (Pydantic)
2. **Handler execution:** Plain dict → `TaskResult` (Pydantic)
3. **Database:** `JobRecord`, `TaskRecord` (Pydantic models)
4. **Service Bus:** Pydantic models serialize/deserialize automatically

**Boundary Conversion Pattern:**
- **Jobs**: Simple (plain dicts)
- **CoreMachine**: Type-safe (Pydantic at boundaries)
- **Database/Queue**: Validated (Pydantic models)

### Creating a New Job Type - Complete Checklist

**Prerequisites:**
- [ ] Understand Job→Stage→Task pattern (see above)
- [ ] Have handler implementations ready (in `services/`)
- [ ] Know which Service Bus queue to use (`jobs` queue for all jobs)

**Step-by-Step Process:**

**1. Create Job Class**
- [ ] Create `jobs/your_job.py` with class `YourJobClass`
- [ ] Define class attributes:
  - [ ] `job_type: str` - Unique identifier for this job
  - [ ] `description: str` - Human-readable description
  - [ ] `stages: List[Dict[str, Any]]` - Stage definitions (plain dicts)
  - [ ] `parameters_schema: Dict[str, Any]` - (Optional) Parameter schema

**2. Implement Required Methods** (ALL 5 REQUIRED - validated at import!)
- [ ] `validate_job_parameters(params: dict) -> dict`
  - Validate and normalize parameters
  - Called by: `triggers/submit_job.py` line 171
  - Must return validated dict

- [ ] `generate_job_id(params: dict) -> str`
  - Generate deterministic job ID (SHA256 recommended)
  - Called by: `triggers/submit_job.py` line 175
  - Must return hex string

- [ ] `create_job_record(job_id: str, params: dict) -> dict`
  - Create JobRecord and persist to database
  - Called by: `triggers/submit_job.py` line 220
  - Must use `RepositoryFactory.create_repositories()`

- [ ] `queue_job(job_id: str, params: dict) -> dict`
  - Queue JobQueueMessage to Service Bus
  - Called by: `triggers/submit_job.py` line 226
  - Must create message and send to `jobs` queue

- [ ] `create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> List[dict]`
  - Generate task parameter dicts for each stage
  - Called by: `core/machine.py` line 248
  - Must return list of dicts with `task_id`, `task_type`, `parameters`

**3. Register Job**
- [ ] Import class in `jobs/__init__.py`: `from .your_job import YourJobClass`
- [ ] Add to `ALL_JOBS` dict: `"your_job": YourJobClass`
- [ ] Verify import-time validation passes (catches missing methods!)

**4. Register Handlers**
- [ ] Create handler functions in `services/service_your_domain.py`
- [ ] Import in `services/__init__.py`
- [ ] Add to `ALL_HANDLERS` dict: `"task_type": handler_function`

**5. Local Testing**
```bash
# Validate job structure (runs at import)
python3 -c "from jobs import validate_job_registry; validate_job_registry()"

# Test compilation
python3 -m py_compile jobs/your_job.py

# Check handler registry
python3 -c "from services import ALL_HANDLERS; print(list(ALL_HANDLERS.keys()))"
```

**6. Deploy and Test**
```bash
# Deploy to Azure
func azure functionapp publish rmhgeoapibeta --python --build remote

# Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/your_job \
  -H "Content-Type: application/json" \
  -d '{"param1": "value1"}'

# Check job status (use job_id from response)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**Reference Implementations:**
- **Simple single-stage:** [jobs/create_h3_base.py](../jobs/create_h3_base.py) - Minimal working example
- **Multi-stage workflow:** [jobs/hello_world.py](../jobs/hello_world.py) - Two stages with task lineage
- **Complex pipeline:** [jobs/process_raster_v2.py](../jobs/process_raster_v2.py) - Dynamic fan-out pattern with JobBaseMixin

**Common Pitfalls:**
- ❌ Forgetting `@staticmethod` decorator on methods
- ❌ Missing required keys in task dicts (`task_id`, `task_type`, `parameters`)
- ❌ Not registering handler in `services/__init__.py`
- ❌ Using `job_type` string that doesn't match registry key
- ❌ Forgetting to add job to `ALL_JOBS` dict

**Validation Catches:**
- ✅ Missing required methods (caught at import)
- ✅ Missing `stages` attribute (caught at import)
- ✅ Empty `stages` list (caught at import)
- ✅ Missing task dict keys (caught when job processes)
- ✅ Invalid handler names (caught when task executes)

### Why NOT Workflow ABC?

The system has **unused reference files** that define an ABC-based pattern:
- `jobs/workflow.py` - Workflow ABC (unused)
- `jobs/registry.py` - Decorator registration (unused)
- `core/models/stage.py` - Stage Pydantic model (unused by jobs)

These were **planned but never implemented**. Pattern B was chosen because:

1. **Simpler** - No abstract methods or inheritance
2. **Jobs are blueprints** - They define WHAT, CoreMachine handles HOW
3. **Pydantic at boundaries** - Type safety where it matters (SQL ↔ Python ↔ Service Bus)
4. **Proven** - All 10 production jobs use Pattern B successfully

**NOTE:** ABC-based enforcement is planned for future implementation (see ARCHITECTURE_REVIEW.md Phase 2)
5. **Less over-engineering** - Most jobs don't need heavy Pydantic throughout

### Production Job Examples

**Simple single-stage:** `jobs/create_h3_base.py`
```python
class CreateH3BaseJob:
    job_type = "create_h3_base"
    stages = [{"number": 1, "name": "generate", "task_type": "h3_base_generate"}]
```

**Multi-stage greeting:** `jobs/hello_world.py`
```python
class HelloWorldJob:
    job_type = "hello_world"
    stages = [
        {"number": 1, "name": "greeting", "task_type": "hello_world_greeting"},
        {"number": 2, "name": "reply", "task_type": "hello_world_reply"}
    ]
```

**Complex raster pipeline:** `jobs/process_raster_v2.py` (v2 mixin pattern, 04 DEC 2025)
```python
class ProcessRasterV2Job(RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase):
    job_type = "process_raster_v2"
    stages = [
        {"number": 1, "name": "validate", "task_type": "validate_raster", "parallelism": "single"},
        {"number": 2, "name": "create_cog", "task_type": "create_cog", "parallelism": "single"},
        {"number": 3, "name": "create_stac", "task_type": "create_stac_raster", "parallelism": "single"}
    ]
```

All follow Pattern B with plain dicts and static methods.

---

## Database Schema Architecture

### Three-Schema Design Philosophy (14 SEP 2025)

The database uses a **three-schema architecture** for clear separation of concerns and production stability:

#### 1. `app` Schema - Workflow Orchestration (STABLE)
**Purpose**: Core job orchestration engine
**Stability**: Fixed in production - schema changes rare
**Contents**:
- `jobs` table - Job records and state management
- `tasks` table - Task execution and results
- PostgreSQL functions for atomic state transitions
- Advisory locks for concurrency control

**Design Principle**: This schema represents the stable orchestration engine. Once deployed to production, changes should be minimal to ensure workflow reliability.

#### 2. `pgstac` Schema - STAC Catalog (STABLE)
**Purpose**: SpatioTemporal Asset Catalog metadata
**Stability**: Managed by pypgstac migrations - version controlled
**Contents**:
- `collections` - STAC collections (datasets)
- `items` - STAC items (individual assets)
- `search()` function - CQL2 spatial/temporal queries
- Partitioned tables for scale
- Extensive indexing for performance

**Design Principle**: Schema evolution managed by PgSTAC project. Updates only through official pypgstac migrations to maintain STAC API compliance.

#### 3. `geo` Schema - Spatial Data Library (FLEXIBLE)
**Purpose**: Growing library of curated vector and raster data
**Stability**: Designed for continuous growth
**Contents**:
- Vector layers (PostGIS geometries)
- Raster catalogs (PostGIS raster)
- Derived products and analysis results
- Project-specific spatial tables
- Custom spatial functions

**Design Principle**: This is the **living schema** that grows with your geospatial data library. New tables can be added without affecting core orchestration (`app`) or catalog metadata (`pgstac`).

### Schema Interaction Patterns

```sql
-- Example: Job in app schema creates spatial data in geo schema
-- and registers metadata in pgstac schema

-- 1. Job orchestration (app schema)
INSERT INTO app.jobs (job_id, job_type, parameters) VALUES (...);

-- 2. Spatial processing (geo schema)
CREATE TABLE geo.project_boundaries AS
SELECT ST_Transform(geom, 4326) FROM source_data;

-- 3. Catalog registration (pgstac schema)
SELECT pgstac.create_item('{
  "collection": "processed-vectors",
  "id": "project-boundaries-v1",
  "geometry": {...}
}'::jsonb);
```

### Benefits of Three-Schema Architecture

1. **Production Stability**: Core orchestration (`app`) remains stable
2. **Standards Compliance**: STAC catalog (`pgstac`) follows specifications
3. **Data Flexibility**: Spatial library (`geo`) grows organically
4. **Clear Boundaries**: Each schema has distinct responsibilities
5. **Migration Safety**: Schema changes isolated by purpose
6. **Performance**: Optimized indexing strategies per schema
7. **Security**: Role-based access control per schema

### Future-Proofing Considerations

- **app schema**: Versioned migrations for any orchestration changes
- **pgstac schema**: Automatic migrations via pypgstac upgrades
- **geo schema**: Project-based prefixes for table organization (e.g., `geo.project1_*`, `geo.project2_*`)

---

## Data Models

### JobRecord (app.jobs table)
```python
class JobRecord(BaseModel):
    job_id: str           # SHA256 hash for idempotency
    job_type: str         # Maps to controller (e.g., "hello_world", "process_raster")
    status: JobStatus     # QUEUED → PROCESSING → COMPLETED/FAILED
    stage: int            # Current stage (1 to N)
    total_stages: int     # Defined by workflow
    parameters: Dict      # Original input parameters
    stage_results: Dict   # Aggregated results per stage
    result_data: Dict     # Final aggregated results
    error_details: str    # Failure information
    created_at: datetime
    updated_at: datetime
```

### TaskRecord (app.tasks table)
```python
class TaskRecord(BaseModel):
    task_id: str              # Format: {job_id[:8]}-{stage}-{index}
    parent_job_id: str        # Link to parent job
    task_type: str            # Maps to service handler
    status: TaskStatus        # QUEUED → PROCESSING → COMPLETED/FAILED
    stage: int                # Stage number
    task_index: str           # Can be semantic (e.g., "tile-x5-y10")
    parameters: Dict          # Task-specific params
    result_data: Dict         # Task output
    next_stage_params: Dict   # Explicit handoff to next stage
    error_details: str        # Failure information
    heartbeat: datetime       # For long-running tasks
    retry_count: int          # Attempt counter
    created_at: datetime
    updated_at: datetime
```

---

## Queue Message Schemas

### JobQueueMessage
```python
class JobQueueMessage(BaseModel):
    job_id: str
    job_type: str
    stage: int              # 1 for new job, >1 for continuation
    parameters: Dict        # Original parameters
    stage_results: Dict     # Results from completed stages
    timestamp: datetime
```

### TaskQueueMessage
```python
class TaskQueueMessage(BaseModel):
    task_id: str
    parent_job_id: str
    task_type: str
    stage: int
    task_index: str
    parameters: Dict         # Task-specific parameters
    parent_task_id: Optional[str]  # For explicit handoff
    timestamp: datetime
```

---

## PostgreSQL Functions

### Core Atomic Operations
```sql
-- Complete task and check if stage is done (atomic)
CREATE FUNCTION complete_task_and_check_stage(
    p_task_id TEXT,
    p_stage_number INT
) RETURNS BOOLEAN AS $$
BEGIN
    -- Update task to completed
    UPDATE app.tasks 
    SET status = 'COMPLETED', updated_at = NOW()
    WHERE task_id = p_task_id;
    
    -- Check if all tasks in stage are complete
    RETURN NOT EXISTS (
        SELECT 1 FROM app.tasks
        WHERE parent_job_id = (
            SELECT parent_job_id FROM app.tasks 
            WHERE task_id = p_task_id
        )
        AND stage = p_stage_number
        AND status != 'COMPLETED'
    );
END;
$$ LANGUAGE plpgsql;

-- Advance job to next stage
CREATE FUNCTION advance_job_stage(
    p_job_id TEXT,
    p_next_stage INT,
    p_stage_results JSONB
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE app.jobs
    SET 
        stage = p_next_stage,
        stage_results = stage_results || p_stage_results,
        updated_at = NOW()
    WHERE job_id = p_job_id;
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Check if job is complete
CREATE FUNCTION check_job_completion(
    p_job_id TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_stage INT;
    v_total_stages INT;
BEGIN
    SELECT stage, total_stages 
    INTO v_current_stage, v_total_stages
    FROM app.jobs 
    WHERE job_id = p_job_id;
    
    RETURN v_current_stage >= v_total_stages;
END;
$$ LANGUAGE plpgsql;
```

---

## Workflow Definitions

### WorkflowDefinition Schema
```python
class StageDefinition(BaseModel):
    stage_number: int
    stage_name: str
    task_type: str
    max_parallel_tasks: int
    timeout_minutes: int = 30
    depends_on_stage: Optional[int]

class WorkflowDefinition(BaseModel):
    job_type: str
    description: str
    total_stages: int
    stages: List[StageDefinition]
```

### Example: Process Raster Workflow
```python
class ProcessRasterWorkflow(WorkflowDefinition):
    job_type: str = "process_raster"
    total_stages: int = 4
    stages: List[StageDefinition] = [
        StageDefinition(
            stage_number=1,
            stage_name="validate",
            task_type="validate_raster",
            max_parallel_tasks=1
        ),
        StageDefinition(
            stage_number=2,
            stage_name="chunk",
            task_type="calculate_tiles",
            max_parallel_tasks=1
        ),
        StageDefinition(
            stage_number=3,
            stage_name="process",
            task_type="create_cog_tile",
            max_parallel_tasks=100,
            depends_on_stage=2
        ),
        StageDefinition(
            stage_number=4,
            stage_name="catalog",
            task_type="create_stac_record",
            max_parallel_tasks=1,
            depends_on_stage=3
        )
    ]
```

---

## Factory Patterns

### Repository Factory
```python
class RepositoryFactory:
    @staticmethod
    def create_repositories() -> Dict[str, Any]:
        """Create all repository instances"""
        base_repo = PostgreSQLBaseRepository()
        
        return {
            'job_repo': JobRepository(base_repo),
            'task_repo': TaskRepository(base_repo),
            'completion_detector': CompletionDetector(base_repo)
        }
```

### Job Factory with Registry
```python
class JobRegistry:
    """Singleton registry for job type registration"""
    _instance = None
    _controllers: Dict[str, Type[BaseController]] = {}
    
    @classmethod
    def register(cls, job_type: str, workflow: WorkflowDefinition):
        """Decorator for controller registration"""
        def decorator(controller_class):
            cls._controllers[job_type] = controller_class
            return controller_class
        return decorator

class JobFactory:
    @staticmethod
    def create_controller(job_type: str) -> BaseController:
        """Factory method to create controllers"""
        if job_type not in JobRegistry._controllers:
            raise ValueError(f"Unknown job type: {job_type}")
        return JobRegistry._controllers[job_type]()
```

### Task Factory for Bulk Creation
```python
class TaskFactory:
    @staticmethod
    def create_tasks(
        job_id: str,
        stage: StageDefinition,
        task_params: List[Dict]
    ) -> Tuple[List[TaskRecord], List[TaskQueueMessage]]:
        """Bulk create tasks and queue messages"""
        task_records = []
        queue_messages = []
        
        for index, params in enumerate(task_params):
            task_id = f"{job_id[:8]}-{stage.stage_number}-{index}"
            
            record = TaskRecord(
                task_id=task_id,
                parent_job_id=job_id,
                task_type=stage.task_type,
                stage=stage.stage_number,
                task_index=str(index),
                parameters=params,
                status=TaskStatus.QUEUED
            )
            
            message = TaskQueueMessage(
                task_id=task_id,
                parent_job_id=job_id,
                task_type=stage.task_type,
                stage=stage.stage_number,
                task_index=str(index),
                parameters=params
            )
            
            task_records.append(record)
            queue_messages.append(message)
        
        return task_records, queue_messages
```

---

## State Transitions

### Job State Machine
```
        ┌─────────┐
        │ QUEUED  │
        └────┬────┘
             ↓
        ┌─────────────┐
        │ PROCESSING  │
        └─────┬───────┘
              ↓
    ┌─────────┴─────────┐
    ↓                   ↓
┌────────┐        ┌──────────┐
│ FAILED │        │COMPLETED │
└────────┘        └──────────┘
```

### Task State Machine
```
QUEUED → PROCESSING → COMPLETED
            ↓
         FAILED
```

### Stage Advancement Logic
1. **Last Task Detection**: Atomic PostgreSQL operation determines last completing task
2. **Result Aggregation**: Controller aggregates all task results for the stage
3. **Job Record Update**: Stage results stored, stage number incremented
4. **Next Stage Queuing**: New Jobs Queue message created with next stage number

---

## Parallelism Patterns

**Updated**: 16 OCT 2025 - Clarified naming and added fan-in pattern

### Overview

Three parallelism patterns control how tasks are created and orchestrated:

| Pattern | When N is Known | Who Creates Tasks | Example |
|---------|----------------|-------------------|---------|
| **"single"** | Orchestration-time | Job | N from params OR hardcoded |
| **"fan_out"** | Runtime (after previous stage) | Job | N from previous_results |
| **"fan_in"** | Always 1 | CoreMachine (auto) | Aggregate all previous |

**Key Insight**: The distinction is NOT about what N equals, but WHEN N is determined.

---

### Pattern 1: "single" - Orchestration-Time Parallelism

**When to Use**: N is known before any tasks execute (from params or hardcoded)

**Job Behavior**: Job's `create_tasks_for_stage()` creates N tasks at orchestration time

**Examples**:

```python
# Example A: N from job parameters
stages = [
    {"number": 1, "task_type": "process_item", "parallelism": "single"}
]

@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        n = job_params.get('n', 10)  # ← N from request parameters
        return [
            {"task_id": f"{job_id[:8]}-s1-{i}", ...}
            for i in range(n)  # Create N tasks (N = 10)
        ]

# Example B: Hardcoded (always 1 task)
@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        return [{  # ← Always create exactly 1 task
            "task_id": f"{job_id[:8]}-s1-analyze",
            "task_type": "analyze_raster",
            "parameters": {"raster": job_params["raster"]}
        }]
```

**Tiling Example**:
```python
# Stage 1: Calculate tile grid from bounding box
stages = [
    {"number": 1, "task_type": "generate_tiles", "parallelism": "single"}
]

@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        # Calculate tile grid at orchestration time (BEFORE execution)
        bbox = job_params["bounding_box"]
        tile_size = job_params.get("tile_size_km", 10)

        # Determine N tiles from bbox geometry
        tiles = calculate_tile_grid(bbox, tile_size)  # Returns 100 tiles

        # Create 100 tasks immediately (orchestration-time)
        return [
            {
                "task_id": f"{job_id[:8]}-s1-tile-{tile.x}-{tile.y}",
                "task_type": "process_tile",
                "parameters": {"tile": tile.coords}
            }
            for tile in tiles
        ]
```

---

### Pattern 2: "fan_out" - Result-Driven Parallelism

**When to Use**: N is discovered by executing previous stage (file lists, dynamic analysis)

**Job Behavior**: Job's `create_tasks_for_stage()` creates N tasks FROM `previous_results` data

**Example**:

```python
stages = [
    {"number": 1, "task_type": "list_files", "parallelism": "single"},
    {"number": 2, "task_type": "process_file", "parallelism": "fan_out"}  # ← Fan-out
]

@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        # Stage 1: Create 1 task to LIST files (don't know N yet)
        return [{
            "task_id": f"{job_id[:8]}-s1-list",
            "task_type": "list_container_files",
            "parameters": {"container": job_params["container"]}
        }]

    elif stage == 2:
        # Stage 2: Fan-out - Create tasks FROM Stage 1 execution results
        if not previous_results:
            raise ValueError("Stage 2 requires Stage 1 results")

        # Extract file list from Stage 1 task result (runtime discovery!)
        file_list = previous_results[0]['result']['files']  # ← N discovered HERE

        # Create one task per file (N = len(file_list))
        return [
            {
                "task_id": f"{job_id[:8]}-s2-{file_name}",
                "task_type": "process_file",
                "parameters": {"file_name": file_name}
            }
            for file_name in file_list
        ]
```

**Raster Tiling Example (Dynamic N)**:
```python
# Stage 1: Analyze raster → determine if tiling needed
# Stage 2: Process tiles (N determined by Stage 1 analysis)

stages = [
    {"number": 1, "task_type": "analyze_raster", "parallelism": "single"},
    {"number": 2, "task_type": "process_tile", "parallelism": "fan_out"}
]

@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        # Stage 1: One task analyzes raster and determines tiling strategy
        return [{
            "task_id": f"{job_id[:8]}-s1-analyze",
            "task_type": "analyze_raster_size",
            "parameters": {"raster_path": job_params["raster"]}
        }]
        # Task execution outputs: {"tiles": [{"x": 0, "y": 0}, ...]}  ← 100 tiles

    elif stage == 2:
        # Stage 2: Fan-out based on Stage 1 analysis results
        tile_plan = previous_results[0]['result']['tiles']  # ← N = 100 discovered

        return [
            {
                "task_id": f"{job_id[:8]}-s2-tile-{tile['x']}-{tile['y']}",
                "task_type": "process_tile",
                "parameters": {"tile": tile, "raster": job_params["raster"]}
            }
            for tile in tile_plan
        ]
```

---

### Pattern 3: "fan_in" - Auto-Aggregation

**When to Use**: Need to aggregate results in the MIDDLE of a workflow (not just at end)

**Job Behavior**: Job does NOTHING - CoreMachine auto-creates 1 aggregation task

**CoreMachine Logic**:
```python
# In core/machine.py:process_job_message()
if stage_definition.get("parallelism") == "fan_in":
    # CoreMachine creates aggregation task automatically
    tasks = self._create_fan_in_task(...)  # Always returns [1 task]
else:
    # Delegate to job
    tasks = job_class.create_tasks_for_stage(...)
```

**Example - Complete Diamond Pattern**:

```python
stages = [
    {"number": 1, "task_type": "list_files", "parallelism": "single"},
    {"number": 2, "task_type": "process_file", "parallelism": "fan_out"},
    {"number": 3, "task_type": "aggregate_results", "parallelism": "fan_in"},  # ← AUTO
    {"number": 4, "task_type": "update_catalog", "parallelism": "single"}
]

@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    if stage == 1:
        return [{"task_id": ..., "task_type": "list_files", ...}]

    elif stage == 2:
        files = previous_results[0]['result']['files']
        return [{"task_id": ..., "task_type": "process_file", ...} for f in files]

    elif stage == 3:
        # FAN-IN: Job does NOTHING - CoreMachine handles it
        # DO NOT implement this case - return [] or raise NotImplementedError
        return []  # CoreMachine creates aggregation task automatically

    elif stage == 4:
        # Stage 4 receives aggregated result from Stage 3
        summary = previous_results[0]['result']['summary']
        return [{"task_id": ..., "parameters": {"summary": summary}}]
```

**Task Handler for Fan-In Stage**:
```python
# services/aggregate_results.py
class AggregateResultsHandler:
    def execute(self, params: dict) -> dict:
        # Receive ALL Stage 2 results (automatically provided by CoreMachine)
        previous_results = params["previous_results"]  # List of N results

        # Aggregate
        total_files = len(previous_results)
        total_size = sum(r['result']['file_size'] for r in previous_results)

        return {
            "success": True,
            "result": {
                "summary": {
                    "total_files": total_files,
                    "total_size_mb": total_size / 1024 / 1024
                }
            }
        }
```

**Flow Diagram**:
```
Stage 1 (single):     [List Files]
                           ↓
                    (returns 100 files)
                           ↓
Stage 2 (fan_out):   [Process 1] [Process 2] ... [Process 100]
                           ↓         ↓              ↓
                    (all 100 results collected)
                           ↓
Stage 3 (fan_in):    [Aggregate] ← CoreMachine auto-creates this
                           ↓
                    (summary: 100 files processed)
                           ↓
Stage 4 (single):    [Update Catalog]
```

---

## Inter-Stage Communication

### Current Pattern: Explicit Handoff
```python
# Stage 1, Task 5 creates results needed by Stage 2, Task 5
task_1_5.next_stage_params = {
    "tile_boundaries": [100, 200, 300, 400],
    "projection": "EPSG:3857"
}

# Stage 2, Task 5 retrieves handoff data
handoff = get_task_record(f"{job_id}-1-5").next_stage_params
```

### Future Pattern: Automatic Lineage (Planned)
```python
# Tasks with same semantic ID automatically access predecessor
# Stage 2: task "abc123-s2-tile-x5-y10" auto-loads from "abc123-s1-tile-x5-y10"
if context.has_predecessor():
    predecessor_data = context.get_predecessor_result()
```

---

## Storage Architecture

### Data Tiers
```
Bronze Tier (Raw Input)
├── Container: rmhazuregeobronze
├── Purpose: User-uploaded raw data
└── Format: Original formats (GeoTIFF, Shapefile, etc.)

Silver Tier (Processed)
├── Vectors: PostGIS database (geo schema)
├── Rasters: rmhazuregeosilver container
├── Purpose: Analysis-ready data
└── Format: COGs, standardized projections

Gold Tier (Exports) - Future
├── Container: rmhazuregeogold
├── Purpose: Published datasets
└── Format: GeoParquet, STAC catalogs
```

### Large Metadata Handling
```python
class TaskResult(BaseModel):
    result_data: Dict           # Inline results (<1MB)
    large_metadata_path: Optional[str]  # Blob path for large results
    
    def store_large_result(self, data: Dict, blob_client):
        """Store large results in blob storage"""
        if len(json.dumps(data)) > 1_000_000:  # 1MB threshold
            blob_path = f"results/{self.task_id}.json"
            blob_client.upload_blob(blob_path, json.dumps(data))
            self.large_metadata_path = blob_path
            self.result_data = {"status": "stored_externally"}
        else:
            self.result_data = data
```

---

## Error Handling Strategy

### Contract Violations vs Business Errors

**CRITICAL DISTINCTION** (26 SEP 2025)

#### Contract Violations (Programming Bugs)
- **Type**: `ContractViolationError` (inherits from `TypeError`)
- **When**: Wrong types passed, missing required fields, interface violations
- **Handling**: NEVER catch these - let them bubble up to crash the function
- **Purpose**: Find bugs during development, not runtime failures

**Examples**:
```python
# Contract violation - wrong type passed
if not isinstance(job_id, str):
    raise ContractViolationError(
        f"job_id must be str, got {type(job_id).__name__}"
    )

# Contract violation - wrong return type from method
if not isinstance(result, (dict, TaskResult)):
    raise ContractViolationError(
        f"Handler returned {type(result).__name__} instead of TaskResult"
    )
```

#### Business Logic Errors (Expected Runtime Failures)
- **Type**: `BusinessLogicError` and subclasses
- **When**: Normal failures during operation (network issues, missing resources)
- **Handling**: Catch and handle gracefully
- **Purpose**: Keep system running despite expected issues

**Subclasses**:
- `ServiceBusError` - Service Bus communication failures
- `DatabaseError` - Database operation failures
- `TaskExecutionError` - Task failed during execution
- `ResourceNotFoundError` - Resource doesn't exist
- `ValidationError` - Business validation failed

**Examples**:
```python
# Business error - Service Bus unavailable
except ServiceBusError as e:
    logger.warning(f"Service Bus temporarily unavailable: {e}")
    return {"success": False, "retry": True}

# Business error - File not found in blob storage
except ResourceNotFoundError as e:
    logger.info(f"Expected resource not found: {e}")
    return {"success": False, "error": str(e)}
```

### Implementation Pattern

```python
try:
    # Validate contracts first
    if not isinstance(param, expected_type):
        raise ContractViolationError("...")

    # Execute business logic
    result = do_work(param)

except ContractViolationError:
    # Let contract violations bubble up (bugs)
    raise

except BusinessLogicError as e:
    # Handle expected business failures gracefully
    logger.warning(f"Business failure: {e}")
    return handle_business_failure(e)

except Exception as e:
    # Log unexpected errors with full details
    logger.error(f"Unexpected: {e}\n{traceback.format_exc()}")
    return handle_unexpected_error(e)
```

### Current Development Mode
- **Fail-Fast**: Any task failure immediately fails entire job
- **No Retries**: `maxDequeueCount: 1` in host.json
- **Clear Errors**: Detailed error messages in job and task records

### Future Production Mode
```python
class ErrorCategory(Enum):
    TRANSIENT = "transient"      # Network issues, temporary unavailability
    PERMANENT = "permanent"      # Invalid data, logic errors
    THROTTLING = "throttling"    # Rate limits, quota exceeded

class ErrorHandler:
    @staticmethod
    def categorize_error(exception: Exception) -> ErrorCategory:
        if isinstance(exception, (TimeoutError, ConnectionError)):
            return ErrorCategory.TRANSIENT
        elif "rate limit" in str(exception).lower():
            return ErrorCategory.THROTTLING
        else:
            return ErrorCategory.PERMANENT

    @staticmethod
    def should_retry(category: ErrorCategory, retry_count: int) -> bool:
        if category == ErrorCategory.PERMANENT:
            return False
        if category == ErrorCategory.TRANSIENT:
            return retry_count < 3
        if category == ErrorCategory.THROTTLING:
            return retry_count < 5
```

---

## Scalability Targets

### Current Design
- **Parallel Tasks**: 10-50 (tested), expandable to 100-1000
- **Task Duration**: 10-15 minutes typical, 30 minutes maximum
- **Queue Processing**: Azure Functions Premium plan
- **Database**: Simple psycopg connections per task

### Future Scaling
```
Scale Level     | Parallel Tasks | Storage        | Database
----------------|----------------|----------------|------------------
Current (Dev)   | 10-50          | Azure Storage  | PostgreSQL Direct
Near-term       | 100-500        | Azure Storage  | PostgreSQL (memory-first pattern)
Long-term       | 1,000+         | Blob + Cosmos  | PostgreSQL + Cosmos hybrid
```

**Note (23 DEC 2025):** PgBouncer was previously recommended but is NOT suitable for serverless.
See "Serverless Database Connection Pattern" section below for correct approach.

### Performance Optimizations
- **Queue Batching**: Process multiple messages per function invocation
- **Result Streaming**: Direct blob writes for large outputs
- **Caching Layer**: Redis for frequently accessed metadata

---

## ⚠️ CRITICAL: Serverless Database Connection Pattern (23 DEC 2025)

**THIS SECTION DOCUMENTS A HARD-LEARNED LESSON THAT KILLED A DATABASE.**

### The Problem

In serverless architectures with parallel workers, traditional database patterns fail catastrophically:

| Pattern | What Happens | Result |
|---------|--------------|--------|
| Connection pooling | Each worker instance creates its own pool | N workers × M pool size = connection explosion |
| Incremental writes | Keep connection open, write as you go | Long-held connections × parallel workers = exhaustion |
| Per-operation connections | Open/close per DB call | Connection churn overwhelms database |

**Real incident (23 DEC 2025):** 8 function instances × 2 workers × 8 concurrent calls = 128 parallel operations. Each H3 cascade task opened ~15 connections (one per resolution insert). Result: 1,920 connections churning against a 200-connection database. Database became unresponsive and had to be replaced.

### The Correct Pattern: Memory-First, Single-Connection Burst

```python
# ✅ CORRECT: Batch in memory, single connection burst
def process_task(params):
    # PHASE 1: CPU/Memory work (no database connection)
    all_results = []
    for item in items:
        result = expensive_computation(item)  # Use RAM freely
        all_results.append(result)

    # PHASE 2: Single connection, batch insert
    with get_connection() as conn:
        bulk_insert(conn, all_results)  # One connection, fast
        conn.commit()
    # Connection released immediately
```

```python
# ❌ WRONG: Connection open during computation
def process_task(params):
    with get_connection() as conn:  # Connection held for entire task!
        for item in items:
            result = expensive_computation(item)  # Connection idle during CPU work
            conn.execute(insert, result)          # Many small writes
        conn.commit()
```

### Design Principles

1. **RAM is cheap, connections are precious**
   - B3 App Service: 7GB RAM, can hold millions of records
   - PostgreSQL B2s: 429 max connections shared across ALL clients

2. **Minimize connection duration**
   - Generate all data in memory first
   - Open connection only for the INSERT
   - Close immediately after commit

3. **Minimize connection frequency**
   - Batch ALL inserts into ONE connection
   - Use COPY protocol for bulk inserts (faster than individual INSERTs)
   - One connection per task, not per operation

4. **NO connection pooling in serverless**
   - Pools don't persist across function invocations
   - Each worker process creates its own pool
   - Pools hold connections even when idle
   - Use simple open-use-close pattern instead

### Connection Budget Calculation

```
Max safe concurrent connections = max_connections × 0.5 (leave headroom)

Example: PostgreSQL B2s with 429 max_connections
- Safe limit: ~200 concurrent connections
- With 4 workers × 4 concurrent calls = 16 parallel tasks
- Each task can safely use: 200 / 16 = 12 connections max
- Target: 1-3 connections per task for safety margin
```

### Implementation Reference

See `services/handler_cascade_h3_descendants.py` for the canonical implementation:
- `_generate_descendants()`: Pure CPU, no DB connections
- `_insert_all_cells()`: Single connection for all inserts via COPY

---

## Example Workflow: Process Raster

### Stage Flow
```
Stage 1: Validation (1 task)
├── Validate raster format
├── Extract metadata
└── Output: Metadata, tile scheme

Stage 2: Chunking (1 task)
├── Calculate tile boundaries
├── Create task parameters for Stage 3
└── Output: List of tile definitions

Stage 3: Processing (N parallel tasks)
├── Each task processes one tile
├── Reproject and convert to COG
└── Output: COG tile paths

Stage 4: Aggregation (1 task)
├── Create STAC catalog entry
├── Update metadata
└── Output: Complete dataset record
```

### Task ID Examples
```
Job: abc12345... (SHA256 hash)
├── Stage 1: abc12345-1-0 (validation)
├── Stage 2: abc12345-2-0 (chunking)
├── Stage 3: abc12345-3-0 through abc12345-3-99 (100 tiles)
└── Stage 4: abc12345-4-0 (catalog)
```

---

## Implementation Status

### Repository Layer Status
- ✅ Interface/Implementation separation (interface_repository.py)
- ✅ PostgreSQL atomic operations
- ✅ Factory pattern (repository_factory.py)
- ✅ Business repositories (repository_jobs_tasks.py)
- ⚠️ Key Vault integration disabled (repository_vault.py)

### Controller Layer Status
- ✅ Base controller with abstract methods
- ✅ Factory with decorator registration
- ✅ Hello World implementation
- 🔧 Stage 2 task creation issue (active debugging)

### Service Layer Status
- ✅ Task handler registry pattern
- ✅ Hello World service implementation
- ⚠️ Manual import required (no auto-discovery yet)

---

## Future Enhancement: Webhook Integration

### Overview
Upon job completion, the system will support outbound HTTP POST notifications to external applications, enabling real-time integration with client systems.

### Implementation Design
```python
# In job parameters during submission
{
    "webhook_url": "https://client.example.com/api/job-complete",
    "webhook_secret": "shared-hmac-secret",
    "webhook_retry_count": 3,
    "webhook_timeout_seconds": 30
}
```

### Features
- **Automatic Notifications**: Send HTTP POST on job completion/failure
- **Security**: HMAC-SHA256 signature verification
- **Retry Logic**: Exponential backoff for failed deliveries
- **Async Delivery**: Non-blocking webhook calls
- **Batch Support**: Multiple webhook URLs per job

### Webhook Payload Format
```json
{
    "job_id": "abc123...",
    "job_type": "process_raster",
    "status": "completed",
    "stage_results": {...},
    "final_results": {...},
    "timestamp": "2025-09-12T22:00:00Z",
    "signature": "hmac-sha256-signature"
}
```

### Use Cases
1. **Client Notifications**: Alert external systems when processing completes
2. **Workflow Integration**: Trigger downstream processes in other systems
3. **Monitoring**: Send metrics to observability platforms
4. **Data Pipelines**: Chain multiple processing systems together

### Security Considerations
- HMAC signatures prevent webhook spoofing
- URL allowlisting to prevent SSRF attacks
- Timeout limits to prevent hanging connections
- Circuit breaker pattern for failing endpoints

---

*For current issues and tasks, see TODO_ACTIVE.md. For deployment procedures, see DEPLOYMENT_GUIDE.md.*