# Architecture Reference

**Date**: 11 SEP 2025  
**Author**: Robert and Geospatial Claude Legion  
**Purpose**: Deep technical specifications for the Azure Geospatial ETL Pipeline

## Table of Contents
1. [Database Schema Architecture](#database-schema-architecture)
2. [Data Models](#data-models)
3. [Queue Message Schemas](#queue-message-schemas)
4. [PostgreSQL Functions](#postgresql-functions)
5. [Workflow Definitions](#workflow-definitions)
6. [Factory Patterns](#factory-patterns)
7. [State Transitions](#state-transitions)
8. [Inter-Stage Communication](#inter-stage-communication)
9. [Storage Architecture](#storage-architecture)
10. [Error Handling Strategy](#error-handling-strategy)
11. [Scalability Targets](#scalability-targets)

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
Near-term       | 100-1000       | Azure Storage  | PgBouncer Pool
Long-term       | 10,000+        | Blob + Cosmos  | PostgreSQL + Cosmos
```

### Performance Optimizations
- **Connection Pooling**: PgBouncer for >100 parallel tasks
- **Queue Batching**: Process multiple messages per function invocation
- **Result Streaming**: Direct blob writes for large outputs
- **Caching Layer**: Redis for frequently accessed metadata

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