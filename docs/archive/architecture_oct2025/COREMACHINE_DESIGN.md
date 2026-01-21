# CoreMachine Design - Avoiding the God Class

**Date**: 30 SEP 2025
**Purpose**: Design document for CoreMachine orchestrator
**Key Goal**: Universal orchestration WITHOUT becoming a God Class

---

## 🎯 The Problem: God Class (Epoch 3)

### What We Had: BaseController (2,290 lines, 34 methods)

```python
class BaseController:  # THE GOD CLASS
    def __init__(self):
        # Creates EVERYTHING internally (tight coupling)
        self.db_repo = PostgreSQLRepository()
        self.queue_repo = QueueRepository()
        self.service_bus = ServiceBusRepository()
        self.blob_repo = BlobRepository()
        # ... and more

    # Database operations (should be in StateManager)
    def create_job(self, ...): ...
    def update_job_status(self, ...): ...
    def create_task(self, ...): ...
    def get_job(self, ...): ...
    def get_tasks(self, ...): ...

    # State management (should be in StateManager)
    def check_stage_completion(self, ...): ...
    def advance_stage(self, ...): ...
    def complete_job(self, ...): ...

    # Task orchestration (should be in OrchestrationManager)
    def create_stage_tasks(self, ...): ...
    def determine_task_count(self, ...): ...
    def create_task_definitions(self, ...): ...

    # Queue operations (should be abstracted)
    def queue_job_message(self, ...): ...
    def queue_task_message(self, ...): ...
    def batch_queue_tasks(self, ...): ...

    # Business logic (should be in job-specific controllers!)
    def validate_parameters(self, ...): ...
    def aggregate_stage_results(self, ...): ...
    def should_advance_stage(self, ...): ...

    # ... 20 MORE METHODS
```

**Problems**:
1. **2,290 lines** - Too big to understand
2. **34 methods** - Does everything
3. **Tight coupling** - Creates all dependencies internally
4. **Hard to test** - Can't mock dependencies
5. **Not reusable** - Job-specific code mixed with generic
6. **Not swappable** - Can't change Queue → Service Bus easily

---

## ✅ The Solution: CoreMachine + Composition

### CoreMachine is NOT a God Class Because:

## 1. **Composition Over Inheritance**

**God Class Pattern** (BAD):
```python
class BaseController:  # Inherits nothing, creates everything
    def __init__(self):
        self.state_manager = StateManager()  # Created internally!
        self.queue = QueueRepository()       # Locked in!
```

**CoreMachine Pattern** (GOOD):
```python
class CoreMachine:  # Inherits nothing, receives everything
    def __init__(self,
                 state_manager: StateManager,           # Injected!
                 orchestration_manager: OrchestrationManager,  # Injected!
                 queue_repo: QueueRepository,           # Injected! (swappable)
                 service_bus_repo: ServiceBusRepository):  # Injected! (swappable)
        self.state = state_manager
        self.orchestration = orchestration_manager
        self.queue = queue_repo
        self.service_bus = service_bus_repo
```

**Result**: CoreMachine has ZERO hard dependencies!

---

## 2. **Single Responsibility: Orchestration ONLY**

CoreMachine does ONE thing: **Coordinate the workflow**

### What CoreMachine DOES:
- ✅ Process job messages (coordinate workflow start)
- ✅ Process task messages (coordinate task execution)
- ✅ Coordinate stage advancement (when to move forward)
- ✅ Coordinate completion (when to finish)
- ✅ Choose queue strategy (batch vs individual)

### What CoreMachine DOES NOT DO:
- ❌ Database operations → **StateManager** does this
- ❌ Task creation → **OrchestrationManager** does this
- ❌ Parameter validation → **Workflow** does this
- ❌ Business logic → **Task handlers** do this
- ❌ Queue communication → **Repository** does this

**Analogy**: CoreMachine is the **conductor** of an orchestra, not the entire orchestra!

---

## 3. **Delegated Responsibilities**

```
┌─────────────────────────────────────────────────────────────┐
│                       CoreMachine                            │
│                 (Orchestration Coordinator)                  │
│                                                              │
│  def process_job_message(msg):                              │
│      workflow = get_workflow(msg.job_type)  ← Registry      │
│      self.state.create_job(...)             ← StateManager  │
│      tasks = self.orchestration.create_tasks(...)           │
│      self.queue_tasks(tasks)                ← Smart routing │
│                                                              │
│  def process_task_message(msg):                             │
│      handler = get_task(msg.task_type)      ← Registry      │
│      result = handler(msg.params)           ← Business logic│
│      is_done = self.state.complete_task_and_check_stage()   │
│      if is_done: self.advance_stage(...)    ← Coordination  │
│                                                              │
│  def queue_tasks(tasks):                                    │
│      if len(tasks) >= threshold:                            │
│          self.service_bus.batch_send(tasks) ← Delegation    │
│      else:                                                  │
│          self.queue.send_messages(tasks)    ← Delegation    │
└─────────────────────────────────────────────────────────────┘
           │              │              │              │
           ▼              ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  State   │  │Orchestr. │  │  Queue   │  │ Service  │
    │ Manager  │  │ Manager  │  │   Repo   │  │   Bus    │
    └──────────┘  └──────────┘  └──────────┘  └──────────┘
```

**CoreMachine coordinates, others execute!**

---

## 4. **Major Components Breakdown**

### Component 1: StateManager (Already Exists!)

**Location**: `core/state_manager.py` (~540 lines)

**Responsibility**: All database operations

**Methods CoreMachine Calls**:
```python
state.create_job(job_id, job_type, params)
state.create_tasks(task_definitions)
state.complete_task_and_check_stage(task_id, job_id, stage)  # ← Advisory locks!
state.advance_job_stage(job_id, next_stage, results)
state.complete_job(job_id, final_results)
state.get_job(job_id)
state.get_tasks_for_stage(job_id, stage)
```

**Key Feature**: Uses PostgreSQL advisory locks for atomic "last task turns out lights" logic.

**CoreMachine doesn't need to know HOW the database works!**

---

### Component 2: OrchestrationManager (Already Exists!)

**Location**: `core/orchestration_manager.py` (~400 lines)

**Responsibility**: Dynamic task creation and batching

**Methods CoreMachine Calls**:
```python
orchestration.create_tasks_for_stage(
    job_id=job_id,
    stage_num=stage,
    workflow=workflow,
    params=params
)
# Returns: List[TaskDefinition]

orchestration.prepare_batch_tasks(tasks)
# Returns: Batches ready for Service Bus
```

**Key Feature**: Handles the "fan-out" pattern where 1 task creates N tasks.

**CoreMachine doesn't need to know HOW tasks are created!**

---

### Component 3: MessageQueue Abstraction

**Location**: `infrastructure/queue.py`, `infrastructure/service_bus.py`

**Responsibility**: Queue/Service Bus communication

**Interface CoreMachine Uses**:
```python
# Queue Storage (for small jobs)
queue_repo.send_message(message_dict)

# Service Bus (for large jobs)
service_bus_repo.batch_send(messages_list)
```

**Key Feature**: CoreMachine doesn't care WHICH queue - it's injected!

**Swap queues by changing ONE line in composition!**

---

### Component 4: Job Registry (Just Created!)

**Location**: `jobs/registry.py`

**Responsibility**: Job type → Workflow class mapping

**Methods CoreMachine Calls**:
```python
workflow = get_workflow(job_type)  # Returns Workflow instance
stages = workflow.define_stages()   # Get stage definitions
params = workflow.validate_parameters(params)  # Validate
threshold = workflow.get_batch_threshold()  # Get threshold
```

**CoreMachine doesn't need to know WHAT jobs exist!**

---

### Component 5: Task Registry (Just Created!)

**Location**: `services/registry.py`

**Responsibility**: Task type → Handler function mapping

**Methods CoreMachine Calls**:
```python
handler = get_task(task_type)  # Returns callable
result = handler(params)        # Execute task
```

**CoreMachine doesn't need to know WHAT tasks exist!**

---

## 5. **CoreMachine Methods (Only ~5-6 methods!)**

### Method 1: `process_job_message(message: JobQueueMessage)`

**Responsibility**: Start a job workflow

**Steps**:
1. Get workflow from registry
2. Validate parameters
3. Create job record (via StateManager)
4. Create Stage 1 tasks (via OrchestrationManager)
5. Queue Stage 1 tasks (smart routing)

**Lines**: ~50-80 lines

---

### Method 2: `process_task_message(message: TaskQueueMessage)`

**Responsibility**: Execute a single task

**Steps**:
1. Get task handler from registry
2. Execute handler
3. Save task result (via StateManager)
4. Check stage completion (via StateManager - advisory locks!)
5. If last task: advance stage OR complete job

**Lines**: ~60-100 lines

---

### Method 3: `advance_stage(job_id: str, current_stage: int)`

**Responsibility**: Move job to next stage

**Steps**:
1. Get workflow definition
2. Check if more stages exist
3. If yes: Create tasks for next stage, queue them
4. If no: Complete job

**Lines**: ~40-60 lines

---

### Method 4: `complete_job(job_id: str)`

**Responsibility**: Finalize job

**Steps**:
1. Aggregate final results
2. Mark job complete (via StateManager)

**Lines**: ~20-30 lines

---

### Method 5: `queue_tasks(tasks: List[TaskDefinition], workflow: Workflow)`

**Responsibility**: Smart queue routing

**Steps**:
1. Check task count vs threshold
2. If >= threshold: Service Bus batch
3. If < threshold: Queue Storage individual

**Lines**: ~30-40 lines

---

### Method 6 (Optional): `handle_task_failure(task_id: str, error: Exception)`

**Responsibility**: Error handling

**Steps**:
1. Log error
2. Update task status to FAILED
3. Determine if job should fail or retry

**Lines**: ~20-30 lines

---

## 6. **Total CoreMachine Size Estimate**

```
Class definition & __init__:        ~30 lines
process_job_message():              ~70 lines
process_task_message():             ~90 lines
advance_stage():                    ~50 lines
complete_job():                     ~25 lines
queue_tasks():                      ~35 lines
handle_task_failure():              ~25 lines
Helper methods & error handling:    ~75 lines
Documentation & imports:            ~50 lines
─────────────────────────────────────────────
TOTAL:                             ~450 lines
```

**Compare**:
- God Class (BaseController): 2,290 lines
- CoreMachine: ~450 lines (80% smaller!)

**And CoreMachine handles ALL jobs, not just one!**

---

## 7. **Why CoreMachine Avoids God Class**

### ✅ Single Responsibility
Does ONE thing: coordinate workflow execution

### ✅ Composition
All dependencies injected, zero hard coupling

### ✅ Delegation
Delegates to:
- StateManager (database)
- OrchestrationManager (task creation)
- Repositories (queues)
- Registries (lookup)
- Workflows (job definition)
- Handlers (business logic)

### ✅ Small Interface
Only 5-6 public methods

### ✅ Stateless
No job-specific state stored in CoreMachine

### ✅ Testable
All dependencies can be mocked

### ✅ Swappable
Change Queue → Service Bus: change 1 line in composition

---

## 8. **The Key Design Pattern**

```python
# God Class Pattern (Epoch 3)
class GodClass:
    def __init__(self):
        self.dependency1 = Dependency1()  # Creates it
        self.dependency2 = Dependency2()  # Creates it

    def do_everything(self):
        # Does database work
        # Does queue work
        # Does business logic
        # Does orchestration
        # ... 2,290 lines of EVERYTHING

# CoreMachine Pattern (Epoch 4)
class CoreMachine:
    def __init__(self, dep1, dep2, dep3, dep4):  # Receives them
        self.dep1 = dep1  # Injected
        self.dep2 = dep2  # Injected
        self.dep3 = dep3  # Injected
        self.dep4 = dep4  # Injected

    def coordinate_workflow(self):
        # Delegates to dep1
        # Delegates to dep2
        # Delegates to dep3
        # Delegates to dep4
        # ... ~450 lines of COORDINATION ONLY
```

**God Class**: "I'll do it all myself!"
**CoreMachine**: "I'll coordinate experts!"

---

## 9. **CoreMachine Responsibilities Table**

| Responsibility | CoreMachine | Delegated To |
|----------------|-------------|--------------|
| Start workflow | ✅ Coordinate | StateManager (create job) |
| Validate params | ❌ Delegate | Workflow.validate_parameters() |
| Create tasks | ❌ Delegate | OrchestrationManager |
| Save to database | ❌ Delegate | StateManager |
| Execute business logic | ❌ Delegate | Task handlers (from registry) |
| Check stage completion | ❌ Delegate | StateManager (advisory locks!) |
| Decide next stage | ✅ Coordinate | Workflow.define_stages() |
| Queue messages | ❌ Delegate | Queue/ServiceBus repos |
| Choose queue type | ✅ Coordinate | Based on Workflow.get_batch_threshold() |
| Handle errors | ✅ Coordinate | Log and delegate to StateManager |

**CoreMachine coordinates, others execute!**

---

## 10. **Comparison Summary**

### God Class (BaseController - Epoch 3)
```
Lines: 2,290
Methods: 34
Dependencies: Created internally (7 repositories)
Testability: Hard (can't mock)
Reusability: Low (mixed concerns)
Swappability: None (tight coupling)
Job-specific code: Mixed in (bad!)
```

### CoreMachine (Epoch 4)
```
Lines: ~450
Methods: 5-6
Dependencies: Injected (4 components)
Testability: Easy (all mockable)
Reusability: High (pure coordination)
Swappability: Full (composition)
Job-specific code: Zero (all in Workflows/Tasks!)
```

---

## 🎯 Implementation Strategy

### Phase 1: Create CoreMachine Skeleton
```python
class CoreMachine:
    def __init__(self, state, orchestration, queue, service_bus):
        self.state = state
        self.orchestration = orchestration
        self.queue = queue
        self.service_bus = service_bus
```

### Phase 2: Implement process_job_message()
Extract from `controller_service_bus_hello.py`:
- Job creation logic
- Stage 1 task creation
- Task queuing

### Phase 3: Implement process_task_message()
Extract from `controller_service_bus_hello.py`:
- Task handler execution
- Result saving
- Stage completion check
- Conditional advancement

### Phase 4: Implement advance_stage()
Extract from `controller_service_bus_hello.py`:
- Next stage determination
- Task creation for next stage
- Task queuing

### Phase 5: Implement complete_job()
Extract from `controller_service_bus_hello.py`:
- Result aggregation
- Job completion

### Phase 6: Implement queue_tasks()
- Smart routing logic
- Batch vs individual

---

## ✅ Success Criteria

CoreMachine is successful if:

1. ✅ **Size**: < 500 lines (vs 2,290 for God Class)
2. ✅ **Methods**: < 10 public methods (vs 34 for God Class)
3. ✅ **Dependencies**: All injected (vs created internally)
4. ✅ **Job-specific code**: ZERO (all in Workflows/Tasks)
5. ✅ **Works for ALL jobs**: HelloWorld, Container, Raster, etc.
6. ✅ **Testable**: All dependencies mockable
7. ✅ **Swappable**: Change queues without changing CoreMachine

---

**Created**: 30 SEP 2025
**Status**: Design complete, ready for implementation
**Next**: Implement CoreMachine using this design
