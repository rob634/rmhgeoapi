# Data-Behavior Separation Architecture

**Date**: 1 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Core Principle: Composition over Inheritance

The "Task" and "Job" conceptual entities are **NOT represented by single classes**.
Instead, they emerge from the **collaboration between DATA and BEHAVIOR components**.

## Two Orthogonal Concerns

### 1. DATA (What entities ARE)
- **Pydantic Models** - Define structure, validation, serialization
- **Base Contracts** - TaskData, JobData (core/contracts/)
- **Boundary Specializations** - Add boundary-specific fields
  - Database: TaskRecord, JobRecord (core/models/)
  - Queue: TaskQueueMessage, JobQueueMessage (core/schema/)

### 2. BEHAVIOR (What entities DO)
- **Abstract Base Classes** - Define execution contracts
- **TaskExecutor** (services/task.py) - Task business logic
- **Workflow** (services/workflow.py) - Job orchestration logic

## Why Keep Them Separate?

✅ **Flexibility**: Swap data format without touching business logic
✅ **Testability**: Test behavior without database/queue infrastructure
✅ **Single Responsibility**: Data structure changes don't affect behavior
✅ **Boundary Crossing**: Data models cross boundaries, behavior stays internal

❌ **Anti-pattern**: `class Task(BaseModel, ABC)` - Mixing concerns creates tight coupling

## The Complete Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      CONCEPTUAL ENTITIES                             │
│                                                                      │
│  "Task" Entity = TaskData + TaskExecutor (Composition)              │
│  "Job" Entity  = JobData  + Workflow     (Composition)              │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────┐         ┌─────────────────────────────────┐
│   DATA (Pydantic)       │         │   BEHAVIOR (ABC)                │
│                         │         │                                 │
│   TaskData              │         │   TaskExecutor                  │
│   (core/contracts)      │         │   (services/task.py)            │
│   ├─ task_id            │         │   └─ execute(params) -> result  │
│   ├─ parent_job_id      │         │                                 │
│   ├─ job_type           │         │   Workflow                      │
│   ├─ task_type ←────────┼─────────┼─→ (services/workflow.py)        │
│   ├─ stage              │  LINK   │   └─ define_stages() -> [Stage] │
│   ├─ task_index         │         │                                 │
│   └─ parameters         │         │                                 │
│        ↓                │         │                                 │
│   ┌──────────────┐      │         │                                 │
│   │ Boundaries:  │      │         │                                 │
│   ├─ TaskRecord  │      │         │                                 │
│   │   (Database) │      │         │                                 │
│   │   +status    │      │         │                                 │
│   │   +result    │      │         │                                 │
│   │   +timestamps│      │         │                                 │
│   │              │      │         │                                 │
│   └─ TaskQueue   │      │         │                                 │
│      Message     │      │         │                                 │
│      (Queue)     │      │         │                                 │
│      +retry_count│      │         │                                 │
│      +timestamp  │      │         │                                 │
└─────────────────────────┘         └─────────────────────────────────┘
         ↓                                      ↓
         └──────────────┬───────────────────────┘
                        ↓
            ┌───────────────────────┐
            │   COMPOSITION LAYER   │
            │   (Brings them together) │
            │                       │
            │   CoreMachine         │
            │   TaskExecutionService│
            └───────────────────────┘
```

## The Link: task_type Field

The `task_type` field in TaskData is the **bridge** connecting data to behavior:

```python
# 1. Data knows WHAT task to execute
task_record = TaskRecord(
    task_type="validate_raster",  # ← The link
    parameters={"file": "raster.tif"}
)

# 2. Registry maps task_type to behavior
TASK_REGISTRY = {
    "validate_raster": ValidateRasterTaskExecutor,
    "generate_tiles": GenerateTilesTaskExecutor,
}

# 3. Composition brings them together
executor_class = TASK_REGISTRY[task_record.task_type]
executor = executor_class()
result = executor.execute(task_record.parameters)
```

## Hierarchy Details

### Task Hierarchy

```
TaskData (BaseModel)
  ├─ task_id: str
  ├─ parent_job_id: str
  ├─ job_type: str
  ├─ task_type: str
  ├─ stage: int
  ├─ task_index: str
  └─ parameters: dict
       ↓ inherits
  ┌────┴─────┐
  │          │
TaskRecord  TaskQueueMessage
(Database)  (Queue)
  │          │
  +status    +retry_count
  +result    +timestamp
  +metadata  +parent_task_id
  +error
  +heartbeat
  +timestamps
```

### Job Hierarchy

```
JobData (BaseModel)
  ├─ job_id: str (SHA256)
  ├─ job_type: str
  └─ parameters: dict
       ↓ inherits
  ┌────┴─────┐
  │          │
JobRecord   JobQueueMessage
(Database)  (Queue)
  │          │
  +status    +stage
  +stage     +stage_results
  +total_stages +retry_count
  +stage_results +timestamp
  +metadata
  +result
  +error
  +timestamps
```

## Real-World Example: Task Execution

```python
# ============================================================================
# STEP 1: Queue message arrives (DATA in motion)
# ============================================================================
queue_message = TaskQueueMessage(
    task_id="abc123-s2-tile_5_10",
    parent_job_id="def456...",
    job_type="stage_raster",
    task_type="generate_cog",  # ← Links to behavior
    stage=2,
    task_index="tile_5_10",
    parameters={
        "input_tile": "/bronze/chunk_5_10.tif",
        "output_cog": "/silver/cog_5_10.tif"
    }
)

# ============================================================================
# STEP 2: Create database record (DATA at rest)
# ============================================================================
task_record = TaskRecord(
    **queue_message.model_dump(exclude={'retry_count', 'timestamp'}),
    status=TaskStatus.PROCESSING,
    created_at=datetime.now()
)
await db.upsert_task(task_record)

# ============================================================================
# STEP 3: Look up behavior from registry
# ============================================================================
executor_class = TASK_REGISTRY["generate_cog"]  # GenerateCOGTaskExecutor
executor = executor_class()

# ============================================================================
# STEP 4: Execute behavior with data
# ============================================================================
result = executor.execute(task_record.parameters)
# result = {"status": "completed", "cog_size_mb": 45.2, "epsg": 4326}

# ============================================================================
# STEP 5: Update data with results
# ============================================================================
task_record.status = TaskStatus.COMPLETED
task_record.result_data = result
task_record.updated_at = datetime.now()
await db.update_task(task_record)
```

## Benefits of This Architecture

### 1. Independent Evolution
```python
# Change data structure without touching business logic
class TaskRecord(TaskData):
    # Add new field
    gpu_used: Optional[str] = None  # TaskExecutor doesn't care!
```

### 2. Easy Testing
```python
# Test behavior without database
def test_generate_cog_executor():
    executor = GenerateCOGTaskExecutor()
    result = executor.execute({"input_tile": "test.tif"})
    assert result["status"] == "completed"
```

### 3. Boundary Flexibility
```python
# Same TaskData base, different boundaries
class TaskKafkaMessage(TaskData):  # New boundary!
    partition: int
    offset: int
```

### 4. Clear Responsibilities
- **TaskData**: Validation, serialization, boundary contracts
- **TaskExecutor**: Business logic, domain operations
- **TaskExecutionService**: Coordination, composition

## Comparison: Before vs After

### ❌ Before (Pyramid/God Class)

```python
class Task(BaseModel, ABC):
    # Data fields
    task_id: str
    status: str
    parameters: dict

    # Behavior
    @abstractmethod
    def execute(self):
        pass

# Problems:
# - Can't serialize behavior to database
# - Can't have different data formats
# - Can't test behavior independently
# - Tight coupling everywhere
```

### ✅ After (Composition)

```python
# Data (can evolve independently)
class TaskData(BaseModel):
    task_id: str
    task_type: str
    parameters: dict

class TaskRecord(TaskData):
    status: TaskStatus
    result: dict

# Behavior (can evolve independently)
class TaskExecutor(ABC):
    @abstractmethod
    def execute(self, params: dict) -> dict:
        pass

class GenerateCOGTaskExecutor(TaskExecutor):
    def execute(self, params):
        # Business logic here
        pass

# Composition (brings them together)
class TaskExecutionService:
    def execute_task(self, task_record: TaskRecord):
        executor = TASK_REGISTRY[task_record.task_type]()
        result = executor.execute(task_record.parameters)
        return result
```

## Key Files

### Data Contracts
- **core/contracts/__init__.py** - TaskData, JobData base classes
- **core/models/task.py** - TaskRecord (database boundary)
- **core/models/job.py** - JobRecord (database boundary)
- **core/schema/queue.py** - TaskQueueMessage, JobQueueMessage (queue boundary)

### Behavior Contracts
- **services/task.py** - TaskExecutor (ABC)
- **services/workflow.py** - Workflow (ABC)

### Composition Layer
- **core/machine.py** - CoreMachine (coordinates Job workflows)
- **services/** (future) - TaskExecutionService (coordinates Task execution)

## Mental Model

Think of a real-world task like "paint a room":

**Work Order (TaskRecord)** - The DATA
- Task ID: #12345
- Type: "paint_room"
- Status: "in_progress"
- Params: `{room: "bedroom", color: "blue"}`

**Painter (TaskExecutor)** - The BEHAVIOR
- Knows HOW to paint
- Has the technique
- Can execute the work

**Foreman (TaskExecutionService)** - The COMPOSITION
- Reads the work order (data)
- Assigns to someone who knows how to do it (behavior)
- Records the results (updates data)

Neither alone is complete! The "task" entity emerges from their collaboration.

## Summary

**The "Task" and "Job" entities are NOT single classes.**

They are **conceptual entities** that emerge from the **collaboration** between:
1. **Data components** (TaskData/JobData + boundary specializations)
2. **Behavior components** (TaskExecutor/Workflow)
3. **Composition layer** (CoreMachine, TaskExecutionService)

This separation provides:
- ✅ Flexibility to evolve data and behavior independently
- ✅ Testability without infrastructure dependencies
- ✅ Clear separation of concerns
- ✅ Boundary flexibility (database, queue, etc.)

**Principle**: "Favor composition over inheritance"

The conceptual entity is expressed through **collaboration**, not **inheritance**.
