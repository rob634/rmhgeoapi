# Queue-Based Orchestration Architecture

**Date: September 7, 2025**

## Executive Summary

This document defines the core idempotent, queue-based orchestration architecture for the Azure Geospatial ETL Pipeline. The system implements a Job→Stage→Task hierarchy with parallel task execution, atomic state transitions, and deterministic job identification through SHA256 hashing.

## Core Design Principles

**A MAJESTIC PYRAMID OF STRONG TYPES AND ABSTRACT STRUCTURES ENFORCED THROUGH OBJECT ORIENTED INHERITANCE HEIRARCHY!** (According to Robert...)

### 1. Idempotency Through Deterministic IDs
- **Job IDs**: SHA256 hash of (job_type + parameters) ensures identical requests produce identical IDs
- **Task IDs**: Embed job ID, stage number, and task index for complete context recovery
- **Benefit**: Natural deduplication and resubmission safety

### 2. Queue-Driven State Machine
- **Separation of Concerns**: Jobs Queue for orchestration, Tasks Queue for execution
- **Asynchronous Processing**: HTTP endpoints return immediately after queuing
- **Reliability**: Azure Queue Storage provides automatic retry and poison queue handling

### 3. "Last Task Turns Out the Lights"
- **Distributed Coordination**: Tasks self-organize without central orchestrator
- **Atomic Detection**: PostgreSQL functions prevent race conditions
- **Stage Advancement**: Last completing task triggers next stage or job completion

### 4. Fail-Fast Philosophy
- **No Partial Success**: Any task failure immediately fails the entire job
- **Clear Error Propagation**: Failures bubble up through stage → job hierarchy
- **Rationale**: Partially completed geospatial transformations are useless

## Architectural Pyramid - Serverless State Management

### The Pyramid Structure - Why It Matters

```
        ┌─────────────┐
        │   Schemas   │  Foundation: Core architecture definition
        └──────┬──────┘  (Everything builds on these definitions)
        ┌──────┴──────┐
        │ Controllers │  Orchestration: Workflow coordination (stateless)
        └──────┬──────┘  (Coordinates but never stores)
        ┌──────┴──────┐
        │ Repositories│  State Management: ACID operations & persistence
        └──────┬──────┘  (THE CRITICAL LAYER - All state lives here)
        ┌──────┴──────┐
        │  Services   │  Business Logic: Domain operations (stateless)
        └──────┬──────┘  (Pure computation, no state)
        ┌──────┴──────┐
        │  Triggers   │  Entry Points: HTTP/Timer/Queue handlers
        └──────┬──────┘  (Stateless event routing)
        ┌──────┴──────┐
        │  Utilities  │  Cross-Cutting: Logging, helpers
        └─────────────┘  (Shared tools)
```

**Why This Pyramid Architecture is Magnificent:**

1. **Foundation First (Schemas)**: Everything is built on well-defined data structures
2. **Clear Dependencies**: Each layer only depends on layers below it
3. **State Isolation**: ALL state management happens in ONE layer (Repositories)
4. **Serverless Ready**: Stateless layers (Controllers, Services) scale infinitely
5. **Race Condition Prevention**: Repository layer ensures atomic operations
6. **Testability**: Each layer can be tested independently
7. **Maintainability**: Single responsibility per layer

### Layer Responsibilities in Serverless Context

#### Schemas Layer (Foundation)
**Purpose**: Define the core structure of the entire application
- **schema_base.py**: Core data models (JobRecord, TaskRecord), enums, base controller
- **schema_workflow.py**: Workflow definitions, stage patterns, orchestration contracts
- **schema_sql_generator.py**: Converts Pydantic models to PostgreSQL DDL
- **schema_manager.py**: Deploys and validates database schemas

#### Controllers Layer (Stateless Orchestration)
**Purpose**: Orchestrate workflows without maintaining state
- Coordinate job stages sequentially
- Fan-out parallel tasks within stages
- Delegate state changes to repository layer
- Implement "last task turns out lights" via repository calls

#### Repositories Layer (State Management)
**Purpose**: Manage ALL application state with ACID guarantees
- **Critical Role**: Serverless functions are stateless - repositories own ALL state
- PostgreSQL stored procedures ensure atomic state transitions
- Prevent race conditions in distributed execution
- Examples: `complete_task_and_check_stage()`, `update_job_status()`

#### Services Layer (Stateless Business Logic)
**Purpose**: Execute business logic without state persistence
- Process geospatial data transformations
- Implement domain rules and calculations
- Call repositories for any state changes
- Return results for repository persistence

#### Triggers Layer (Entry Points)
**Purpose**: Handle external events and route to controllers
- HTTP triggers for REST API endpoints
- Queue triggers for async processing
- Timer triggers for scheduled operations
- All triggers are stateless event handlers

#### Utilities Layer (Cross-Cutting Concerns)
**Purpose**: Provide shared functionality across all layers
- Logging and monitoring
- Error handling patterns
- Common helper functions

### Serverless State Management Principle
```
Python Functions (Stateless)  →  Repository Layer  →  PostgreSQL (Stateful)
     - Business Logic              - State Interface     - ACID Guarantees
     - Orchestration              - Atomic Operations    - Race Prevention
     - Computation                - Transaction Safety    - Persistent State
```

**Why This Architecture Works:**
1. **Clear Separation**: Logic (Python) vs State (PostgreSQL)
2. **Scalability**: Stateless functions scale horizontally
3. **Reliability**: ACID transactions prevent distributed system issues
4. **Maintainability**: Each layer has a single, clear responsibility

## Architecture Components

### Job Submission Flow (Through the Pyramid)

```
[Trigger Layer]    [Controller Layer]    [Repository Layer]    [Storage]
HTTP Request  →    Job Controller    →   JobRepository     →   PostgreSQL
     ↓                   ↓                     ↓                   ↓
 Parse request      Validate params       Create job record    app.jobs
 Route to           Generate Job ID       Queue message        status: QUEUED
 controller         Return Job ID          Atomic insert       Jobs Queue
```

### Job Processing Flow (Orchestration Without State)

```
[Queue]        [Trigger]       [Controller]        [Repository]       [Storage]
Jobs Queue →   Queue       →   Controller     →   TaskRepository  →  PostgreSQL
Message        Trigger          Factory            .create_tasks()    app.tasks
(job_id,          ↓                ↓                    ↓               ↓
 stage)       Route to         Load workflow      Bulk insert      Tasks Queue
              controller        Create tasks       Atomic ops       messages
```

### Task Execution Flow (State Management in Action)

```
[Queue]        [Trigger]       [Service]          [Repository]        [PostgreSQL]
Tasks Queue →  Queue       →   Service        →   Repository     →   Stored Proc
Message        Trigger          Layer              Layer             complete_task()
(task_id)         ↓                ↓                  ↓                   ↓
              Load task       Business logic     Update state      Atomic check:
              parameters      Transform data     Check stage       Last task?
              Route to        Return results     completion        Advance stage?
              service                                              Create tasks?
```

## Data Model

### Job Record (app.jobs)
```python
class JobRecord(BaseModel):
    job_id: str           # SHA256 hash for idempotency
    job_type: str         # Maps to controller
    status: JobStatus     # QUEUED → PROCESSING → COMPLETED/FAILED
    stage: int            # Current stage (1 to N)
    total_stages: int     # Defined by workflow
    parameters: Dict      # Input parameters
    stage_results: Dict   # Aggregated results per stage
    result_data: Dict     # Final aggregated results
    error_details: str    # Failure information
    created_at: datetime
    updated_at: datetime
```

### Task Record (app.tasks)
```python
class TaskRecord(BaseModel):
    task_id: str              # Embeds job_id-stage-index
    parent_job_id: str        # Link to job
    task_type: str            # Maps to service
    status: TaskStatus        # QUEUED → PROCESSING → COMPLETED/FAILED
    stage: int                # Stage number
    task_index: str           # Can be semantic (e.g., "tile_x5_y10")
    parameters: Dict          # Task-specific params
    result_data: Dict         # Task output
    next_stage_params: Dict   # Explicit handoff to next stage task
    error_details: str        # Failure information
    heartbeat: datetime       # For long-running tasks
    created_at: datetime
    updated_at: datetime
```

## Workflow Definition

### Pydantic-Based Workflow Schema
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
    
class ProcessRasterWorkflow(WorkflowDefinition):
    job_type: str = "process_raster"
    stages: List[StageDefinition] = [
        StageDefinition(
            stage_number=1,
            stage_name="validate",
            task_type="validate_raster",
            max_parallel_tasks=10
        ),
        StageDefinition(
            stage_number=2,
            stage_name="tile",
            task_type="create_cog_tile",
            max_parallel_tasks=100,
            depends_on_stage=1
        )
    ]
```

## Job Type Registry

### Decorator-Based Registration with Factory Pattern
```python
@JobRegistry.instance().register(
    job_type="process_raster",
    workflow=ProcessRasterWorkflow(),
    description="Chunk and process large rasters into COGs",
    max_parallel_tasks=100
)
class ProcessRasterController(BaseController):
    """Controller auto-registered at definition time"""
    
    def create_stage_tasks(self, stage: int, context: JobExecutionContext) -> List[TaskRecord]:
        """Generate tasks based on stage and previous results"""
        pass
    
    def aggregate_stage_results(self, stage: int, task_results: List[TaskResult]) -> Dict:
        """Aggregate task results for stage completion"""
        pass

# Factory usage in submit_job endpoint
controller = JobFactory.create_controller(job_type)
workflow = JobFactory.get_workflow(job_type)
```

## Task Factory

### High-Volume Task Creation
```python
class TaskFactory:
    """Factory for creating potentially thousands of task instances"""
    
    @staticmethod
    def create_tasks(
        job_id: str,
        stage: StageDefinition,
        task_params: List[Dict],
        parent_results: Optional[Dict] = None
    ) -> Tuple[List[TaskRecord], List[TaskQueueMessage]]:
        """
        Bulk create task records and queue messages.
        
        Critical for stages that fan-out to 100-1000 parallel tasks.
        """
        task_records = []
        queue_messages = []
        
        for index, params in enumerate(task_params):
            # Generate deterministic task ID
            task_id = TaskFactory.generate_task_id(job_id, stage.stage_number, index)
            
            # Create task record for database
            record = TaskRecord(
                task_id=task_id,
                parent_job_id=job_id,
                task_type=stage.task_type,
                stage=stage.stage_number,
                task_index=str(index),  # Or semantic like "tile_x5_y10"
                parameters=params,
                status=TaskStatus.QUEUED
            )
            
            # Create corresponding queue message
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
    
    @staticmethod
    def generate_task_id(job_id: str, stage: int, index: Union[int, str]) -> str:
        """Generate deterministic task ID embedding job context"""
        # Option 1: Readable format
        return f"{job_id[:8]}-{stage}-{index}"
        
        # Option 2: Hash-based for true determinism
        # return hashlib.sha256(f"{job_id}-{stage}-{index}".encode()).hexdigest()
```

### Usage in Controller
```python
class ProcessRasterController(BaseController):
    def create_stage_tasks(self, stage: int, context: JobExecutionContext) -> List[TaskRecord]:
        if stage == 2:  # Tiling stage
            # Calculate tile parameters (could be 100-1000 tiles)
            tile_params = self.calculate_tile_boundaries(
                context.stage_results[1]['raster_bounds'],
                max_tiles=1000
            )
            
            # Use TaskFactory for bulk creation
            task_records, queue_messages = TaskFactory.create_tasks(
                job_id=context.job_id,
                stage=self.workflow.stages[1],
                task_params=tile_params
            )
            
            # Bulk insert to database and queue
            self.repository.bulk_insert_tasks(task_records)
            self.queue_service.bulk_send_messages(queue_messages)
            
            return task_records
```
```

## Stage Orchestration

### Stage Advancement Logic
1. **Last Task Detection**: Atomic PostgreSQL operation determines last completing task
2. **Result Aggregation**: Controller aggregates all task results for the stage
3. **Job Record Update**: Stage results stored, stage number incremented
4. **Next Stage Queuing**: New Jobs Queue message created with next stage number

### Inter-Stage Task Communication
```python
# Explicit task handoff pattern
# Stage 1, Task 5 creates results needed by Stage 2, Task 5
task_1_5.next_stage_params = {
    "tile_boundaries": [100, 200, 300, 400],
    "projection": "EPSG:3857"
}

# Stage 2, Task 5 retrieves handoff data
handoff = get_task_record(f"{job_id}-1-5").next_stage_params
```

## Queue Message Schemas

### Jobs Queue Message
```python
class JobQueueMessage(BaseModel):
    job_id: str
    job_type: str
    stage: int              # 1 for new job, >1 for continuation
    parameters: Dict        # Original parameters
    stage_results: Dict     # Results from completed stages
    timestamp: datetime
```

### Tasks Queue Message
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

## State Transitions

### Job State Machine
```
QUEUED → PROCESSING → COMPLETED
            ↓
         FAILED
```

### Critical PostgreSQL Functions
```sql
-- Atomically mark task complete and check stage completion
complete_task_and_check_stage(task_id, stage_number) → is_stage_complete

-- Update job to next stage
advance_job_stage(job_id, next_stage, stage_results) → success

-- Check if all stages complete
check_job_completion(job_id) → is_job_complete
```

## Storage Architecture

### Data Tiers
- **Bronze**: Raw input data (`rmhazuregeobronze` container)
- **Silver**: Processed data
  - **Vectors**: PostGIS database
  - **Rasters**: COGs in `rmhazuregeosilver` container
- **Task Results**: Reference silver tier locations

### Large Metadata Handling
```python
class TaskResult(BaseModel):
    result_data: Dict           # Inline results (<1MB)
    large_metadata_path: Optional[str]  # Blob storage path for large results
```

## Scalability Considerations

### Current Design Targets
- **Parallel Tasks**: 10-50 (expandable to 100-1000)
- **Task Duration**: 10-15 minutes typical, 30 minutes maximum
- **Database Connections**: Simple psycopg per task (no pooling required)
- **Queue Processing**: Azure Functions Premium plan (unlimited scale)

### Future Scaling Path
- **10,000+ parallel tasks**: Migrate to CosmosDB
- **Connection pooling**: PgBouncer when tasks need persistent connections
- **Result streaming**: Direct blob storage writes for large outputs

## Error Handling

### Current Approach (Development)
- **Fail-Fast**: Any task failure immediately fails entire job
- **No Retries**: Failed jobs must be resubmitted
- **Clear Errors**: Detailed error messages in job and task records

### Future Production Enhancements
- **Task-level retries**: Configurable retry count per task type
- **Partial completion**: Save successful stage results
- **Circuit breakers**: Prevent cascading failures
- **Dead letter queues**: Investigate repeatedly failing jobs

## Example: Process Raster Workflow

### Stage 1: Validation
- **Tasks**: 1 task to validate raster format and metadata
- **Output**: Raster metadata, tile scheme definition

### Stage 2: Chunking
- **Tasks**: N tasks based on raster size (e.g., 50GB → 100 tiles)
- **Handoff**: Each task gets tile boundaries from Stage 1
- **Output**: Tile identifiers and boundaries

### Stage 3: Processing
- **Tasks**: N parallel tasks (one per tile)
- **Handoff**: Tile boundaries from corresponding Stage 2 task
- **Output**: Processed COG tiles in silver storage

### Stage 4: Aggregation
- **Tasks**: 1 task to create STAC record
- **Input**: All COG references from Stage 3
- **Output**: Complete STAC catalog entry

## Implementation Status

### Completed
- ✅ PostgreSQL schema with atomic operations
- ✅ Queue message structures
- ✅ Base controller and task classes
- ✅ Pydantic validation models

### In Progress
- 🔧 Job type registry with decorators
- 🔧 Workflow definition schemas
- 🔧 Task ID generation logic

### Future Work
- 📋 Stage advancement implementation
- 📋 Task handoff mechanism
- 📋 Result aggregation logic
- 📋 Job completion webhooks

## Summary

This architecture provides a robust, scalable foundation for geospatial ETL processing with:
- **Idempotent operations** through deterministic hashing
- **Parallel processing** with atomic coordination
- **Clear failure semantics** with fail-fast philosophy
- **Flexible workflows** through Pydantic-based definitions
- **Modern Python patterns** with decorators and type safety

The system is designed to handle massive parallel workloads (50GB+ rasters) while maintaining data consistency and providing clear operational visibility.