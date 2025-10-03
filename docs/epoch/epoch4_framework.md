# Geospatial ETL Pipeline Architecture Guide

## Overview

This is a **serverless, multi-stage ETL pipeline** for geospatial data processing built on Azure Functions. The architecture separates the orchestration framework (domain-agnostic) from geospatial operations (domain-specific), enabling Python developers to work on the pipeline without geospatial knowledge.

## Core Architecture Principles

### 1. Framework vs Domain Separation

**The Key Insight:** Orchestration logic is completely separate from geospatial operations.

```
pipeline/     ← Framework: HOW we orchestrate (no geospatial knowledge)
workflows/    ← Definitions: WHAT stages exist (minimal geospatial)
tasks/        ← Bridge: Connects framework to domain
domain/       ← Geospatial: WHERE all the geo complexity lives
```

**Result:** A Python developer can work on `pipeline/`, `workflows/`, and `tasks/` without understanding coordinate systems, projections, or GDAL.

### 2. Composition Over Inheritance

**One class uses inheritance:** `Orchestrator` (the state machine skeleton)

**Everything else is composition:** Dependencies injected as parameters

```python
# ❌ BAD: Hardcoded dependency
class Orchestrator:
    def __init__(self):
        self.queue = ServiceBusQueue()  # Locked in!

# ✅ GOOD: Injected dependency
class Orchestrator:
    def __init__(self, queue: MessageQueue):  # Swappable!
        self.queue = queue
```

**Why this matters:** Swapping Service Bus ↔ Storage Queue requires changing ONE line in composition, not rewriting the entire class.

### 3. Contracts Everywhere (ABC + Pydantic)

**ABC (Abstract Base Classes):** Define interfaces
```python
class Task(ABC):
    @abstractmethod
    def execute(self, params: dict) -> dict: ...
```

**Pydantic Models:** Enforce data shapes
```python
class Job(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    current_stage: int
```

**Result:** Consistent signatures, type safety, validation everywhere

### 4. Single Source of Truth

The same Pydantic models flow through the entire system:

```
SQL → Pydantic → Python ✅
Queue Message → Pydantic → Python ✅
HTTP Request → Pydantic → Python ✅
```

No manual serialization/deserialization. Validation happens once.

### 5. Fan-Out/Fan-In Pattern

Core orchestration pattern for parallelization:

```
Stage 1: Determination (1 task)
    ↓ outputs n
Stage 2: Processing (n parallel tasks)
    ↓ "last one out" advances
Stage 3: Finalization (1 task)
```

**Example:** Upload a 10GB file
- Stage 1: Determine → split into 100 chunks
- Stage 2: Upload → 100 parallel uploads
- Stage 3: Finalize → mark complete when last chunk finishes

### 6. State Management

**Database is the single source of truth** for job state.

- Jobs have stages
- Stages have tasks
- Tasks update atomic counters
- "Last one out" uses advisory locks to prevent race conditions

---

## Architecture Evolution: The Story

### Epoch 3: The God Class (What We Had)

**The Problem:** 3,000 lines, 34 methods, ONE class that did EVERYTHING

```python
class JobManager:  # The Monolith
    def create_job(self, ...): ...
    def execute_validate_raster_task(self, ...): ...
    def execute_generate_tiles_task(self, ...): ...
    def increment_task_counter(self, ...): ...
    def check_stage_completion(self, ...): ...
    def advance_stage(self, ...): ...
    def send_to_service_bus(self, ...): ...
    # ... 28 more methods
```

**Why it broke:** When we swapped Storage Queue → Service Bus, everything broke because:
- Tight coupling hid dependencies
- No clear component boundaries  
- Assumptions baked into the monolith

### Epoch 4: Proper Separation (What We're Building)

**The Solution:** One core class + composition

```python
# ONE class with inheritance (the state machine)
class Orchestrator:
    def __init__(self, state_manager, message_queue, executor):
        self.state = state_manager      # Injected!
        self.queue = message_queue      # Injected! (Swappable!)
        self.executor = executor        # Injected!

# Everything else is composed
state_manager = StateManager(db_connection)
message_queue = ServiceBusQueue(connection_string)  # Or StorageQueue!
executor = TaskExecutor(task_registry)

orchestrator = Orchestrator(state_manager, message_queue, executor)
```

**Result:** 
- Swap queues in one line
- Test components in isolation
- Clear boundaries and responsibilities
- Hand off pieces to specialists

---

## Complete Folder Structure

```
project/
├── pipeline/                      # Core Framework (domain-agnostic)
│   ├── orchestration/
│   │   ├── orchestrator.py        # Orchestrator class
│   │   ├── stage_manager.py       # Stage advancement logic
│   │   └── reconciler.py          # Timer trigger recovery
│   ├── execution/
│   │   ├── executor.py            # TaskExecutor class
│   │   └── task_registry.py       # TASK_REGISTRY: task_type → Task class
│   ├── state/
│   │   ├── state_manager.py       # StateManager (atomic operations)
│   │   ├── models.py              # Pydantic: Job, Task, Stage, StageStatus
│   │   ├── repository.py          # JobRepository, TaskRepository (CRUD)
│   │   └── migrations/            # Database schema migrations
│   └── messaging/
│       ├── message_queue.py       # ABC: MessageQueue
│       ├── service_bus.py         # ServiceBusQueue(MessageQueue)
│       └── storage_queue.py       # StorageQueue(MessageQueue)
│
├── workflows/                     # Job Definitions
│   ├── workflow.py                # ABC: Workflow
│   ├── job_registry.py            # JOB_REGISTRY: job_type → Workflow class
│   ├── hello_world.py             # ⭐ HelloWorldWorkflow (tests framework)
│   ├── raster_ingest.py           # RasterIngestWorkflow
│   └── vector_ingest.py           # VectorIngestWorkflow
│
├── tasks/                         # Task Implementations (bridge layer)
│   ├── task.py                    # ABC: Task
│   ├── hello/                     # ⭐ Hello World tasks
│   │   ├── greet.py               # GreetTask (Stage 1: fan-out test)
│   │   ├── process.py             # ProcessGreetingTask (Stage 2: progression)
│   │   └── finalize.py            # FinalizeHelloTask (Stage 3: completion)
│   ├── validation/
│   │   ├── validate_raster.py     # ValidateRasterTask(Task)
│   │   └── validate_vector.py     # ValidateVectorTask(Task)
│   ├── processing/
│   │   ├── generate_tiles.py      # GenerateTilesTask(Task)
│   │   ├── reproject.py           # ReprojectTask(Task)
│   │   └── chunk_features.py      # ChunkFeaturesTask(Task)
│   └── finalization/
│       └── create_metadata.py     # CreateMetadataTask(Task)
│
├── domain/                        # Geospatial Operations (⚠️ learning curve)
│   ├── raster/
│   │   ├── operations.py          # reproject_raster(), create_cog()
│   │   ├── tiling.py              # generate_tile(), calculate_tiles()
│   │   └── validation.py          # validate_crs(), check_raster()
│   ├── vector/
│   │   ├── operations.py          # buffer(), simplify(), chunk_features()
│   │   ├── loading.py             # load_to_postgis()
│   │   └── validation.py          # validate_geometry(), check_crs()
│   └── README.md                  # ⚠️ Geospatial primer for new devs
│
├── infrastructure/                # Cross-cutting concerns
│   ├── logging.py                 # Logging configuration
│   ├── config.py                  # Configuration (env vars, Azure config)
│   └── exceptions.py              # JobError, TaskError, ValidationError
│
├── functions/                     # Azure Function entry points
│   ├── http_triggers/
│   │   └── create_job.py          # HTTP: POST /jobs {job_type, params}
│   ├── queue_triggers/
│   │   └── execute_task.py        # Queue: executes Task from message
│   └── timer_triggers/
│       └── reconcile_jobs.py      # Timer: recovers stalled jobs
│
└── tests/                         # Testing
    ├── integration/
    │   └── test_hello_world.py    # End-to-end: validates framework
    └── unit/
        ├── test_orchestrator.py
        ├── test_executor.py
        └── test_state_manager.py
```

---

## Naming Conventions

### Pythonic ABC Pattern

**Abstract classes:** Simple, clean noun
```python
class Task(ABC): ...           # Not BaseTask or ITask
class Workflow(ABC): ...       # Not BaseWorkflow or IWorkflow
class MessageQueue(ABC): ...   # Not IMessageQueue or BaseMessageQueue
```

**Concrete classes:** Descriptive compound
```python
class ValidateRasterTask(Task): ...
class ServiceBusQueue(MessageQueue): ...
class RasterIngestWorkflow(Workflow): ...
```

### Folders and Files

**Folders:** Plural nouns (what lives there)
- `orchestration/` - orchestrators live here
- `workflows/` - workflow definitions live here
- `tasks/` - task implementations live here

**Files:** Singular nouns (what it defines)
- `orchestrator.py` - defines `Orchestrator` class
- `executor.py` - defines `TaskExecutor` class
- `workflow.py` - defines `Workflow` ABC

**Classes:** Match file names
```python
# orchestrator.py
class Orchestrator: ...

# state_manager.py
class StateManager: ...
```

---

## Hello World Workflow

### Purpose

Tests ALL core framework functionality without geospatial complexity:
- ✅ Job creation
- ✅ Fan-out (1 task → n tasks)
- ✅ Parallel task execution
- ✅ Stage progression ("last one out" logic)
- ✅ Job completion

### The Workflow Definition

**File:** `workflows/hello_world.py`

```python
from workflows.workflow import Workflow
from pipeline.state.models import Stage

class HelloWorldWorkflow(Workflow):
    """
    Simple test workflow for framework validation.
    
    Parameters:
        n (int): Number of parallel greetings to generate
    
    Stages:
        1. Generate: Creates n greeting tasks (tests fan-out)
        2. Process: Processes each greeting in parallel (tests parallelism)
        3. Finalize: Aggregates results (tests fan-in + completion)
    """
    
    def define_stages(self) -> list[Stage]:
        return [
            Stage(
                stage_num=1,
                stage_name="generate_greetings",
                task_types=["greet"],
                determines_task_count=True  # This stage outputs n tasks
            ),
            Stage(
                stage_num=2,
                stage_name="process_greetings",
                task_types=["process_greeting"],
                parallel=True  # n parallel tasks
            ),
            Stage(
                stage_num=3,
                stage_name="finalize",
                task_types=["finalize_hello"],
                parallel=False  # Single finalization task
            )
        ]
```

### Stage 1: Fan-Out (Determination)

**File:** `tasks/hello/greet.py`

```python
from tasks.task import Task

class GreetTask(Task):
    """
    Stage 1: Determination task
    Creates n greeting tasks based on parameter
    
    Tests: Dynamic task count determination (fan-out pattern)
    """
    
    def execute(self, params: dict) -> dict:
        n = params.get('n', 3)
        
        # Return list of tasks to create for next stage
        greeting_tasks = []
        for i in range(n):
            greeting_tasks.append({
                'task_type': 'process_greeting',
                'params': {
                    'greeting_id': i,
                    'message': f"Hello from task {i}!"
                }
            })
        
        return {
            'status': 'completed',
            'task_count': n,
            'next_stage_tasks': greeting_tasks
        }
```

### Stage 2: Parallel Processing

**File:** `tasks/hello/process.py`

```python
from tasks.task import Task
import time

class ProcessGreetingTask(Task):
    """
    Stage 2: Processing task (runs n times in parallel)
    
    Tests: Parallel execution, stage progression when all complete
    """
    
    def execute(self, params: dict) -> dict:
        greeting_id = params['greeting_id']
        message = params['message']
        
        # Simulate some work
        time.sleep(0.5)
        processed = message.upper()
        
        return {
            'status': 'completed',
            'greeting_id': greeting_id,
            'processed_message': processed
        }
```

### Stage 3: Fan-In (Finalization)

**File:** `tasks/hello/finalize.py`

```python
from tasks.task import Task

class FinalizeHelloTask(Task):
    """
    Stage 3: Finalization task
    
    Tests: Fan-in pattern, job completion
    """
    
    def execute(self, params: dict) -> dict:
        job_id = params['job_id']
        
        # Could query database for all processed greetings
        # For now, just mark complete
        
        return {
            'status': 'completed',
            'message': 'Hello World workflow completed successfully!',
            'job_id': job_id
        }
```

### Usage Example

```python
# Create a Hello World job with n=5
POST /jobs
{
    "job_type": "hello_world",
    "params": {
        "n": 5  # Creates 5 parallel greeting tasks
    }
}

# Framework automatically:
# 1. Creates job in database
# 2. Runs GreetTask (determines 5 tasks needed)
# 3. Creates 5 ProcessGreetingTask messages in queue
# 4. Executes all 5 in parallel
# 5. Last one to complete advances to Stage 3
# 6. Runs FinalizeHelloTask
# 7. Marks job complete
```

### Integration Test

**File:** `tests/integration/test_hello_world.py`

```python
import pytest
from pipeline.orchestration.orchestrator import Orchestrator

def test_hello_world_end_to_end(orchestrator, state_manager):
    """
    Tests complete workflow execution:
    - Job creation
    - Fan-out (1 → n tasks)
    - Parallel execution
    - Stage progression
    - Job completion
    """
    
    # Create job
    result = orchestrator.create_job(
        job_type="hello_world",
        params={"n": 5}
    )
    
    job_id = result['job_id']
    
    # Wait for completion
    wait_for_job_completion(job_id, timeout=30)
    
    # Verify job completed
    job = state_manager.get_job(job_id)
    assert job.status == "completed"
    assert job.current_stage == 3
    
    # Verify all tasks completed
    tasks = state_manager.get_tasks_for_job(job_id)
    assert len(tasks) == 7  # 1 generate + 5 process + 1 finalize
    assert all(t.status == "completed" for t in tasks)
```

---

## Core Components Deep Dive

### Orchestrator (`pipeline/orchestration/orchestrator.py`)

**Responsibility:** Job lifecycle and stage transitions (the state machine)

```python
class Orchestrator:
    """
    Manages job lifecycle and stage transitions.
    This is the state machine that coordinates workflow execution.
    """
    
    def __init__(self, 
                 state_manager: StateManager,
                 message_queue: MessageQueue,
                 executor: TaskExecutor):
        self.state = state_manager
        self.queue = message_queue
        self.executor = executor
    
    def create_job(self, job_type: str, params: dict) -> dict:
        """
        Creates a new job and initializes first stage.
        
        1. Create job record in database
        2. Look up workflow definition
        3. Create tasks for Stage 1
        4. Send task messages to queue
        """
        pass
    
    def advance_stage(self, job_id: str, stage_num: int):
        """
        Advances job to next stage.
        
        Called by "last one out" - the final task in a stage.
        Uses advisory locks to prevent race conditions.
        
        1. Claim advancement (atomic)
        2. Get next stage definition
        3. Create tasks for next stage
        4. Send task messages to queue
        """
        pass
    
    def check_stage_completion(self, job_id: str, stage_num: int):
        """
        Checks if current stage is complete.
        
        Called by each task upon completion.
        If this is the last task, advances to next stage.
        """
        pass
```

### StateManager (`pipeline/state/state_manager.py`)

**Responsibility:** Database operations with atomic guarantees

```python
class StateManager:
    """
    Handles all database operations for job/task state.
    Provides atomic operations to prevent race conditions.
    """
    
    def __init__(self, job_repo: JobRepository, task_repo: TaskRepository):
        self.jobs = job_repo
        self.tasks = task_repo
    
    def increment_succeeded_count(self, job_id: str, stage_num: int) -> dict:
        """
        Atomically increments succeeded task count.
        Returns current stage status.
        
        Uses advisory locks to ensure thread safety.
        """
        pass
    
    def claim_stage_advancement(self, job_id: str, stage_num: int, 
                               task_id: str) -> bool:
        """
        Atomically claims the right to advance stage.
        
        Only ONE task can successfully claim advancement.
        Returns True if this task won the race.
        """
        pass
    
    def get_stage_status(self, job_id: str, stage_num: int) -> dict:
        """
        Returns current stage status:
        {
            'total': 10,
            'succeeded': 8,
            'failed': 1,
            'in_progress': 1
        }
        """
        pass
```

### TaskExecutor (`pipeline/execution/executor.py`)

**Responsibility:** Execute tasks by delegating to task classes

```python
class TaskExecutor:
    """
    Executes tasks by looking up and instantiating task classes.
    """
    
    def __init__(self, task_registry: dict):
        self.registry = task_registry
    
    def execute(self, task_data: dict) -> dict:
        """
        1. Look up task class from registry
        2. Instantiate task with data
        3. Execute task
        4. Return result
        """
        task_type = task_data['task_type']
        task_class = self.registry.get(task_type)
        
        if not task_class:
            raise ValueError(f"Unknown task type: {task_type}")
        
        task = task_class(task_data)
        result = task.execute(task_data['params'])
        
        return result
```

### MessageQueue Interface (`pipeline/messaging/message_queue.py`)

**Responsibility:** Abstract interface for message queues (enables swapping)

```python
from abc import ABC, abstractmethod

class MessageQueue(ABC):
    """
    Abstract interface for message queues.
    Implementations: ServiceBusQueue, StorageQueue
    """
    
    @abstractmethod
    def send(self, message: dict) -> None:
        """Send a message to the queue"""
        pass
    
    @abstractmethod
    def receive(self, timeout: int = 30) -> list[dict]:
        """Receive messages from queue"""
        pass
    
    @abstractmethod
    def complete(self, message_id: str) -> None:
        """Mark message as successfully processed"""
        pass
    
    @abstractmethod
    def abandon(self, message_id: str) -> None:
        """Return message to queue for retry"""
        pass
```

---

## Pydantic Models

### Job Model

```python
from pydantic import BaseModel
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class Job(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    current_stage: int
    total_stages: int
    params: dict
    created_at: datetime
    updated_at: datetime
    
    class Config:
        use_enum_values = True
```

### Task Model

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class Task(BaseModel):
    task_id: str
    job_id: str
    stage_num: int
    task_type: str
    status: TaskStatus
    params: dict
    result: dict | None = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        use_enum_values = True
```

### Stage Model

```python
class Stage(BaseModel):
    stage_num: int
    stage_name: str
    task_types: list[str]
    determines_task_count: bool = False  # True if this stage outputs n tasks
    parallel: bool = True
```

---

## Adding a New Workflow

### Step 1: Define the Workflow

**File:** `workflows/my_new_workflow.py`

```python
from workflows.workflow import Workflow
from pipeline.state.models import Stage

class MyNewWorkflow(Workflow):
    """
    Description of what this workflow does.
    
    Parameters:
        param1: Description
        param2: Description
    """
    
    def define_stages(self) -> list[Stage]:
        return [
            Stage(
                stage_num=1,
                stage_name="stage_one",
                task_types=["task_type_one"]
            ),
            Stage(
                stage_num=2,
                stage_name="stage_two",
                task_types=["task_type_two"],
                parallel=True
            ),
            # ... more stages
        ]
```

### Step 2: Implement the Tasks

**File:** `tasks/my_category/my_task.py`

```python
from tasks.task import Task

class MyTaskClass(Task):
    """
    Description of what this task does.
    """
    
    def execute(self, params: dict) -> dict:
        # Your task logic here
        # Can call domain operations if needed
        
        return {
            'status': 'completed',
            # ... other result data
        }
```

### Step 3: Register Everything

**In:** `workflows/job_registry.py`

```python
JOB_REGISTRY = {
    'hello_world': HelloWorldWorkflow,
    'raster_ingest': RasterIngestWorkflow,
    'my_new_workflow': MyNewWorkflow,  # Add here
}
```

**In:** `pipeline/execution/task_registry.py`

```python
TASK_REGISTRY = {
    'greet': GreetTask,
    'process_greeting': ProcessGreetingTask,
    'task_type_one': MyTaskClass,  # Add here
    'task_type_two': MyOtherTaskClass,
}
```

### Step 4: Test It

```python
# Create job via API
POST /jobs
{
    "job_type": "my_new_workflow",
    "params": {
        "param1": "value1",
        "param2": "value2"
    }
}
```

**That's it!** The framework handles everything else:
- Job creation
- Stage transitions
- Task execution
- Parallelization
- Completion detection

---

## For the Python Developer (Handoff Guide)

### What You Need to Know

**Week 1: Understand the Framework**
- Start with `pipeline/` - this is pure Python patterns
- Read `orchestrator.py`, `executor.py`, `state_manager.py`
- You don't need to understand geospatial concepts yet

**Week 2: Understand Workflows**
- Look at `workflows/hello_world.py` as a simple example
- See how stages are defined
- Understand the fan-out/fan-in pattern

**Week 3: Understand Tasks**
- Look at `tasks/hello/` as examples
- See how tasks call domain operations
- Start seeing geospatial terms but don't need deep knowledge

**Week 4+: Learn Geospatial (As Needed)**
- Read `domain/README.md` for primer
- Learn concepts progressively as you need them
- The geospatial specialist handles complex operations

### What You Can Work On Immediately

✅ **Orchestration logic** - state machines, stage transitions
✅ **State management** - database operations, atomic counters
✅ **Messaging** - queue integration, retry logic
✅ **Testing** - unit tests, integration tests
✅ **Framework improvements** - better error handling, logging, monitoring

❌ **Don't worry about:**
- What a CRS is
- How raster reprojection works
- GDAL, rasterio, fiona, shapely
- PostGIS operations

### Key Files to Start With

1. `workflows/hello_world.py` - simplest workflow
2. `tasks/hello/` - simplest tasks
3. `pipeline/orchestration/orchestrator.py` - the state machine
4. `pipeline/execution/executor.py` - task execution
5. `tests/integration/test_hello_world.py` - end-to-end test

### Running Hello World

```bash
# 1. Set up environment
pip install -r requirements.txt

# 2. Initialize database
python -m alembic upgrade head

# 3. Start Azure Function locally
func start

# 4. Create a job
curl -X POST http://localhost:7071/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "hello_world", "params": {"n": 5}}'

# 5. Watch the logs - you'll see:
# - Job created
# - GreetTask determines 5 tasks needed
# - 5 ProcessGreetingTask messages sent
# - 5 tasks execute in parallel
# - Last one advances to Stage 3
# - FinalizeHelloTask completes
# - Job marked complete
```

---

## Key Design Patterns Used

### 1. Dependency Injection
Pass dependencies as parameters instead of hardcoding them.

### 2. Registry Pattern
Look up classes dynamically from registries instead of if/else chains.

### 3. Template Method Pattern
Base classes define the flow, subclasses implement specifics.

### 4. Strategy Pattern
Swap implementations (ServiceBus vs StorageQueue) without changing orchestration.

### 5. Repository Pattern
Isolate data access logic from business logic.

### 6. Fan-Out/Fan-In
Parallelize work across multiple tasks, converge at completion.

---

## FAQ

**Q: Why not use Durable Functions?**
A: We need full control over state management, retry logic, and the ability to query "show me all failed tasks from yesterday." Durable Functions is a black box.

**Q: Why not use Airflow/Prefect/Luigi?**
A: We're fully serverless (Azure Functions) with no VM management. These tools require infrastructure.

**Q: Can I add a new job type without touching the framework?**
A: YES! That's the whole point. Define workflow → implement tasks → register both. Done.

**Q: How do I swap Service Bus for Storage Queue?**
A: Change one line in composition: `message_queue = StorageQueue(...)` instead of `ServiceBusQueue(...)`

**Q: What if I need to add geospatial operations?**
A: Add functions to `domain/raster/operations.py` or `domain/vector/operations.py`. Tasks can call them.

**Q: How do I debug a stuck job?**
A: Query the database: `SELECT * FROM tasks WHERE job_id = '...' AND status = 'failed'`

---

## Summary: The Big Picture

```
┌─────────────────────────────────────────────────────────────┐
│                     HTTP Trigger                             │
│                   POST /jobs {job_type, params}              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                              │
│  • Create job in database                                    │
│  • Look up workflow definition from JOB_REGISTRY             │
│  • Create Stage 1 tasks                                      │
│  • Send task messages to queue                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   MESSAGE QUEUE                              │
│              (ServiceBus or StorageQueue)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   QUEUE TRIGGER                              │
│                  (Azure Function)                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   TASK EXECUTOR                              │
│  • Look up task class from TASK_REGISTRY                     │
│  • Instantiate and execute task                              │
│  • Return result                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   STATE MANAGER                              │
│  • Update task status in database                            │
│  • Increment succeeded count (atomic)                        │
│  • Check if stage complete                                   │
│  • If last task out: trigger stage advancement               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼ (if stage complete)
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR                               │
│  • Claim advancement (atomic)                                │
│  • Create next stage tasks                                   │
│  • Send task messages to queue                               │
└─────────────────────────────────────────────────────────────┘

           Cycle repeats until all stages complete
```

**Key Points:**
- Framework is domain-agnostic
- Workflows define stage sequences
- Tasks bridge framework to domain
- Domain operations are pure functions
- Everything is testable in isolation
- Components are swappable via composition

---

*This architecture enables Python developers to work on orchestration without geospatial knowledge, while geospatial specialists focus on domain operations. The Hello World workflow validates the entire framework without any geospatial complexity.*