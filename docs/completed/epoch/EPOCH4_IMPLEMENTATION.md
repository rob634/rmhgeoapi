# EPOCH 4 IMPLEMENTATION - Detailed Task List

**Date**: 30 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Step-by-step implementation plan for Epoch 4 rebuild
**Salvage Rate**: ~65-70% of Epoch 3 code reusable

---

## 🎯 Implementation Strategy

**Approach**: Incremental migration in same workspace, not "big bang" rewrite

**Key Principle**: Keep all working infrastructure, extract orchestration into CoreMachine, create declarative job system

---

## 📋 PHASE 1: Foundation Assessment & Preparation

### ✅ Task 1.1: Inventory Current Working Components
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: CRITICAL

- [ ] Document all files in `core/` folder
- [ ] Document all files in `repositories/` folder
- [ ] Document all Pydantic models in `core/models/`
- [ ] List all PostgreSQL functions in schema files
- [ ] Verify which controllers are actually working
- [ ] Identify all database endpoints (health, debug, query)

**Deliverable**: `EPOCH3_INVENTORY.md` - Complete file catalog with working status

---

### ✅ Task 1.2: Test Current Database Functions
**Status**: PENDING
**Estimated Time**: 20 minutes
**Priority**: CRITICAL

```bash
# Verify PostgreSQL functions are deployed
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/functions/test

# Verify schema health
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Test advisory lock implementation
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/enums/diagnostic
```

**Success Criteria**:
- All PostgreSQL functions respond successfully
- Advisory locks working correctly
- Schema matches expected structure

**Deliverable**: Confirmation that database layer is production-ready

---

### ✅ Task 1.3: Create Backup Branch
**Status**: PENDING
**Estimated Time**: 5 minutes
**Priority**: HIGH

```bash
git checkout -b epoch3-backup
git push origin epoch3-backup

git checkout master
git checkout -b epoch4-implementation
```

**Deliverable**: Safe backup of all Epoch 3 work

---

### ✅ Task 1.4: Create New Folder Structure (Empty)
**Status**: PENDING
**Estimated Time**: 10 minutes
**Priority**: HIGH

Create empty folders for new architecture:

```bash
mkdir -p jobs
mkdir -p services
mkdir -p infra
mkdir -p pipeline/orchestration
mkdir -p pipeline/execution
mkdir -p pipeline/state
mkdir -p pipeline/messaging
```

Add `__init__.py` to each:

```bash
touch jobs/__init__.py
touch services/__init__.py
touch infra/__init__.py
touch pipeline/__init__.py
touch pipeline/orchestration/__init__.py
touch pipeline/execution/__init__.py
touch pipeline/state/__init__.py
touch pipeline/messaging/__init__.py
```

**Deliverable**: Empty folder structure ready for new code

---

## 📋 PHASE 2: Core Infrastructure Migration (Rename & Reuse)

### ✅ Task 2.1: Migrate Repositories to infra/
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: HIGH

**Files to migrate** (these are ALL working correctly):

```bash
# Copy (don't move yet - keep backups)
cp repositories/interface_repository.py infra/interfaces.py
cp repositories/postgresql.py infra/postgresql.py
cp repositories/blob.py infra/blob.py
cp repositories/queue.py infra/queue.py
cp repositories/service_bus.py infra/service_bus.py
cp repositories/vault.py infra/vault.py
cp repositories/__init__.py infra/__init__.py
```

**Updates needed**:
- [ ] Update import statements in each file
- [ ] Update `infra/__init__.py` exports
- [ ] Update `config.py` if it references repositories
- [ ] Create `infra/factory.py` for repository creation

**Success Criteria**: All infra files import cleanly with no errors

**Deliverable**: Working `infra/` folder with all repository code

---

### ✅ Task 2.2: Test Infra Layer Independently
**Status**: PENDING
**Estimated Time**: 20 minutes
**Priority**: HIGH

Create test script:

```python
# test_infra.py
from infra import postgresql, blob, queue, service_bus, vault

# Test each repository instantiates
db = postgresql.PostgreSQLRepository()
storage = blob.BlobRepository()
q = queue.QueueRepository()
sb = service_bus.ServiceBusRepository()
v = vault.VaultRepository()

print("✅ All infra repositories import successfully")
```

**Success Criteria**: All imports work, no errors

**Deliverable**: Validated infra layer

---

### ✅ Task 2.3: Update Core Models Documentation
**Status**: PENDING
**Estimated Time**: 20 minutes
**Priority**: MEDIUM

- [ ] Document all models in `core/models/enums.py`
- [ ] Document all models in `core/models/job.py`
- [ ] Document all models in `core/models/task.py`
- [ ] Document all models in `core/models/results.py`
- [ ] Document all models in `core/models/context.py`
- [ ] Verify all models have proper type hints
- [ ] Verify all models have docstrings

**Deliverable**: `CORE_MODELS_REFERENCE.md` with all model schemas

---

## 📋 PHASE 3: CoreMachine Creation (The Heart of Epoch 4)

### ✅ Task 3.1: Design CoreMachine Class Interface
**Status**: PENDING
**Estimated Time**: 45 minutes
**Priority**: CRITICAL

Create design document: `COREMACHINE_DESIGN.md`

**What to extract from existing controllers**:

From `core/core_controller.py` (400 lines):
- Generic job creation logic
- Generic stage advancement logic
- Generic completion detection

From `controller_service_bus_hello.py` (1,019 lines):
- Batch task creation pattern
- Service Bus coordination
- Task distribution logic

**CoreMachine interface** (design first, implement later):

```python
class CoreMachine:
    """Universal orchestration engine - works for ALL jobs"""

    def __init__(self,
                 state_manager: StateManager,
                 orchestration_manager: OrchestrationManager,
                 queue_repo: QueueRepository,
                 service_bus_repo: ServiceBusRepository):
        # Composed dependencies
        pass

    # Core methods to design:
    def process_job_message(self, message: JobQueueMessage) -> None:
        """Generic job processing"""
        pass

    def process_task_message(self, message: TaskQueueMessage) -> None:
        """Generic task processing"""
        pass

    def handle_stage_completion(self, job_id: str, stage: int) -> None:
        """Generic stage advancement"""
        pass

    def queue_tasks(self, tasks: List[TaskDefinition], job: JobDeclaration) -> None:
        """Smart queuing (batch vs individual)"""
        pass
```

**Deliverable**: Complete design document with method signatures and responsibilities

---

### ✅ Task 3.2: Create JobDeclaration Abstract Base Class
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: CRITICAL

Create `core/job_declaration.py`:

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pydantic import BaseModel

class StageDefinition(BaseModel):
    """Declarative stage definition"""
    number: int
    name: str
    task_type: str
    parallelism: str  # "static", "dynamic", "match_previous"
    count_param: str | None = None
    uses_lineage: bool = False

class JobDeclaration(ABC):
    """
    Abstract base for declarative job definitions.
    Jobs ONLY declare WHAT they do, not HOW.
    """

    # Class attributes (required)
    JOB_TYPE: str
    STAGES: List[Dict[str, Any]]
    PARAMETERS: Dict[str, Any]
    BATCH_THRESHOLD: int = 50

    @abstractmethod
    def create_tasks_for_stage(self, stage: int, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        ONLY custom logic needed per job.
        Returns list of task parameter dicts.
        """
        pass

    def validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Optional: Custom parameter validation"""
        return params
```

**Deliverable**: Working abstract base class for job declarations

---

### ✅ Task 3.3: Implement CoreMachine - Job Processing
**Status**: PENDING
**Estimated Time**: 2 hours
**Priority**: CRITICAL

Create `core/machine.py`:

**Step 3.3.1**: Implement `process_job_message()`

```python
def process_job_message(self, message: JobQueueMessage) -> None:
    """
    Generic job processing - works for ALL jobs.

    1. Get job declaration from registry
    2. Create tasks for Stage 1
    3. Decide batch vs individual queuing
    4. Queue tasks
    5. Update job status
    """
    pass
```

**Extract from**:
- `core/core_controller.py` - `_create_stage_tasks()`
- `controller_service_bus_hello.py` - `_handle_stage_1_initial_setup()`

**Success Criteria**: Can process a job message and create Stage 1 tasks

---

### ✅ Task 3.4: Implement CoreMachine - Task Processing
**Status**: PENDING
**Estimated Time**: 2 hours
**Priority**: CRITICAL

**Step 3.4.1**: Implement `process_task_message()`

```python
def process_task_message(self, message: TaskQueueMessage) -> None:
    """
    Generic task processing - works for ALL tasks.

    1. Look up handler from service registry
    2. Build execution context (lineage if needed)
    3. Execute handler
    4. Save task result
    5. Check stage completion (advisory lock!)
    6. If last task: advance stage or complete job
    """
    pass
```

**Extract from**:
- `controller_service_bus_hello.py` - `_execute_task_with_lineage()`
- `controller_service_bus_hello.py` - `_check_and_advance_stage()`
- Uses `state_manager.complete_task_and_check_stage()` (already working!)

**Success Criteria**: Can process a task and detect completion

---

### ✅ Task 3.5: Implement CoreMachine - Stage Advancement
**Status**: PENDING
**Estimated Time**: 1.5 hours
**Priority**: CRITICAL

**Step 3.5.1**: Implement `handle_stage_completion()`

```python
def handle_stage_completion(self, job_id: str, stage: int) -> None:
    """
    Generic stage advancement - works for ALL jobs.

    1. Get job declaration
    2. Check if more stages exist
    3. If yes: create tasks for next stage, queue them
    4. If no: aggregate final results, complete job
    """
    pass
```

**Extract from**:
- `core/core_controller.py` - `_advance_to_next_stage()`
- `controller_service_bus_hello.py` - stage advancement logic

**Success Criteria**: Can advance from Stage 1 → Stage 2 → Completion

---

### ✅ Task 3.6: Implement CoreMachine - Smart Queuing
**Status**: PENDING
**Estimated Time**: 1 hour
**Priority**: HIGH

**Step 3.6.1**: Implement `queue_tasks()`

```python
def queue_tasks(self, tasks: List[TaskDefinition], job: JobDeclaration) -> None:
    """
    Smart queuing based on task count.

    - < BATCH_THRESHOLD: Queue Storage (individual messages)
    - >= BATCH_THRESHOLD: Service Bus (batch messages)
    """
    if len(tasks) >= job.BATCH_THRESHOLD:
        return self._batch_queue_tasks(tasks)
    else:
        return self._individual_queue_tasks(tasks)
```

**Extract from**:
- `controller_service_bus_hello.py` - batch coordination logic
- `core/orchestration_manager.py` - task creation patterns

**Success Criteria**: Correctly routes to Queue Storage or Service Bus based on count

---

### ✅ Task 3.7: Create Job Registry System
**Status**: PENDING
**Estimated Time**: 45 minutes
**Priority**: HIGH

Create `jobs/registry.py`:

```python
# Global job registry
JOB_REGISTRY: Dict[str, Type[JobDeclaration]] = {}

def register_job(cls: Type[JobDeclaration]) -> Type[JobDeclaration]:
    """Decorator to register job declarations"""
    JOB_REGISTRY[cls.JOB_TYPE] = cls
    return cls

def get_job_declaration(job_type: str) -> JobDeclaration:
    """Get job declaration by type"""
    if job_type not in JOB_REGISTRY:
        raise ValueError(f"Unknown job type: {job_type}")
    return JOB_REGISTRY[job_type]()
```

**Deliverable**: Working registry with decorator pattern

---

### ✅ Task 3.8: Create Service Handler Registry
**Status**: PENDING
**Estimated Time**: 45 minutes
**Priority**: HIGH

Create `services/registry.py`:

```python
from typing import Dict, Callable, Any

# Global handler registry
HANDLER_REGISTRY: Dict[str, Callable] = {}

def register_handler(task_type: str):
    """Decorator to register task handlers"""
    def decorator(func: Callable) -> Callable:
        HANDLER_REGISTRY[task_type] = func
        return func
    return decorator

def get_handler(task_type: str) -> Callable:
    """Get handler by task type"""
    if task_type not in HANDLER_REGISTRY:
        raise ValueError(f"Unknown task type: {task_type}")
    return HANDLER_REGISTRY[task_type]
```

**Deliverable**: Working handler registry with decorator pattern

---

## 📋 PHASE 4: HelloWorld Job Migration (Proof of Concept)

### ✅ Task 4.1: Extract HelloWorld Business Logic to services/
**Status**: PENDING
**Estimated Time**: 1 hour
**Priority**: HIGH

Create `services/hello_world.py`:

**Extract from**: `controller_service_bus_hello.py` (lines with actual business logic)

```python
from services.registry import register_handler
from typing import Dict, Any

@register_handler("hello_world_greeting")
def handle_greeting(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    """
    Stage 1: Generate greeting message
    """
    index = params['index']
    message = params.get('message', 'Hello World')

    return {
        'greeting': f"{message} from task {index}",
        'index': index
    }

@register_handler("hello_world_reply")
def handle_reply(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    """
    Stage 2: Reply to greeting (demonstrates lineage)
    """
    index = params['index']

    # Get predecessor result from Stage 1
    if context.has_predecessor():
        predecessor = context.get_predecessor_result()
        greeting = predecessor.get('greeting', 'unknown')
    else:
        greeting = 'no predecessor'

    return {
        'reply': f"Replying to: {greeting}",
        'index': index
    }
```

**Success Criteria**: Pure business logic, no orchestration code

**Deliverable**: Clean service handlers (~50 lines total)

---

### ✅ Task 4.2: Create HelloWorld Job Declaration
**Status**: PENDING
**Estimated Time**: 45 minutes
**Priority**: HIGH

Create `jobs/hello_world.py`:

```python
from core.job_declaration import JobDeclaration, register_job
from typing import List, Dict, Any

@register_job
class HelloWorldJob(JobDeclaration):
    """
    Simple test job for framework validation.

    Stages:
        1. Greeting: Generate n greeting messages (fan-out)
        2. Reply: Reply to each greeting (demonstrates lineage)

    Parameters:
        n (int): Number of parallel tasks (default: 3)
        message (str): Greeting message (default: "Hello World")
    """

    JOB_TYPE = "hello_world"
    BATCH_THRESHOLD = 50  # Use Service Bus if n >= 50

    STAGES = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",
            "count_param": "n"
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",
            "uses_lineage": True
        }
    ]

    PARAMETERS = {
        "n": {"type": "int", "min": 1, "max": 1000, "default": 3},
        "message": {"type": "str", "default": "Hello World"}
    }

    def create_tasks_for_stage(self, stage: int, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """ONLY custom logic - task creation"""
        n = params['n']
        message = params.get('message', 'Hello World')

        if stage == 1:
            # Stage 1: Create n greeting tasks
            return [
                {"index": i, "message": message}
                for i in range(n)
            ]

        elif stage == 2:
            # Stage 2: Create n reply tasks (matches Stage 1 count)
            return [
                {"index": i}
                for i in range(n)
            ]

        else:
            raise ValueError(f"Unknown stage: {stage}")
```

**Success Criteria**:
- Total lines: ~50-60 (vs 1,019 in old controller!)
- Pure declaration, no orchestration
- Clear and readable

**Deliverable**: Declarative HelloWorld job definition

---

### ✅ Task 4.3: Wire HelloWorld to CoreMachine
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: HIGH

Update `function_app.py` to use CoreMachine:

```python
# OLD WAY (don't do this):
# controller = ServiceBusHelloWorldController(...)

# NEW WAY:
from core.machine import CoreMachine
from jobs.registry import get_job_declaration

@app.queue_trigger(queue_name="geospatial-jobs")
def process_job_queue(msg: func.QueueMessage):
    message = JobQueueMessage.parse_raw(msg.get_body())

    # Get job declaration from registry
    job_declaration = get_job_declaration(message.job_type)

    # CoreMachine handles everything
    machine = CoreMachine(state_manager, orchestration_manager, queue_repo, service_bus_repo)
    machine.process_job_message(message)
```

**Deliverable**: HelloWorld wired to CoreMachine

---

### ✅ Task 4.4: Test HelloWorld End-to-End (Local)
**Status**: PENDING
**Estimated Time**: 1 hour
**Priority**: CRITICAL

```bash
# Start function app locally
func start

# Submit test job (n=3 - should use Queue Storage)
curl -X POST http://localhost:7071/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 3, "message": "Test"}'

# Watch logs for:
# - Job created
# - Stage 1: 3 greeting tasks queued
# - Stage 1: 3 greeting tasks completed
# - Stage 2: 3 reply tasks queued (with lineage)
# - Stage 2: 3 reply tasks completed
# - Job completed
```

**Success Criteria**:
- All stages complete successfully
- Lineage works (Stage 2 accesses Stage 1 results)
- No errors in logs

**Deliverable**: Working HelloWorld job with CoreMachine

---

### ✅ Task 4.5: Test HelloWorld with Large n (Service Bus)
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: HIGH

```bash
# Submit test job (n=100 - should use Service Bus batches)
curl -X POST http://localhost:7071/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 100, "message": "Batch Test"}'
```

**Success Criteria**:
- Uses Service Bus (not Queue Storage)
- Batches sent efficiently
- All 100 tasks complete
- No deadlocks

**Deliverable**: Validated batch processing

---

## 📋 PHASE 5: Deployment & Validation

### ✅ Task 5.1: Deploy to Azure (rmhgeoapibeta)
**Status**: PENDING
**Estimated Time**: 20 minutes
**Priority**: HIGH

```bash
# Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote

# Post-deployment checks
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Redeploy schema (if needed)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

**Deliverable**: Epoch 4 deployed to production

---

### ✅ Task 5.2: Test HelloWorld in Production
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: HIGH

```bash
# Test small job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 5, "message": "Production Test"}'

# Get job ID from response, then query status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Check tasks completed
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

**Success Criteria**:
- Job completes successfully
- All tasks complete
- Results accessible

---

### ✅ Task 5.3: Measure Line Count Reduction
**Status**: PENDING
**Estimated Time**: 15 minutes
**Priority**: MEDIUM

```bash
# Old way (Epoch 3)
wc -l controller_service_bus_hello.py
# Expected: ~1,019 lines

# New way (Epoch 4)
wc -l jobs/hello_world.py services/hello_world.py
# Expected: ~100 lines combined (90% reduction!)

# CoreMachine (shared by ALL jobs)
wc -l core/machine.py
# Expected: ~300-400 lines (used by ALL jobs)
```

**Deliverable**: Metrics showing 90% code reduction per job

---

## 📋 PHASE 6: Documentation & Cleanup

### ✅ Task 6.1: Create Developer Guide
**Status**: PENDING
**Estimated Time**: 1 hour
**Priority**: MEDIUM

Create `EPOCH4_DEVELOPER_GUIDE.md`:

- How to add a new job (step-by-step)
- How to add a new task handler
- How CoreMachine works
- Testing guide
- Debugging guide

**Deliverable**: Complete developer documentation

---

### ✅ Task 6.2: Delete Legacy Controllers
**Status**: PENDING
**Estimated Time**: 15 minutes
**Priority**: LOW

**ONLY after validation that everything works!**

```bash
# Move to archive (don't delete permanently yet)
mkdir -p archive/epoch3_controllers
mv controller_base.py archive/epoch3_controllers/
mv controller_hello_world.py archive/epoch3_controllers/
mv controller_container.py archive/epoch3_controllers/
mv controller_service_bus.py archive/epoch3_controllers/
mv controller_service_bus_hello.py archive/epoch3_controllers/
mv controller_service_bus_container.py archive/epoch3_controllers/
```

**Deliverable**: Clean codebase with no legacy controllers

---

### ✅ Task 6.3: Update CLAUDE.md for Epoch 4
**Status**: PENDING
**Estimated Time**: 30 minutes
**Priority**: HIGH

Update project instructions:

- Point to Epoch 4 architecture
- Update folder structure
- Update development philosophy
- Add CoreMachine documentation reference

**Deliverable**: Updated project instructions

---

### ✅ Task 6.4: Git Commit & Tag
**Status**: PENDING
**Estimated Time**: 10 minutes
**Priority**: MEDIUM

```bash
git add .
git commit -m "Epoch 4: CoreMachine implementation complete

- Created CoreMachine universal orchestration engine
- Migrated HelloWorld to declarative job (~50 lines vs 1,019)
- Created jobs/ and services/ folders
- Migrated repositories to infra/
- 90% code reduction per job
- All tests passing

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"

git tag -a epoch4-complete -m "Epoch 4 implementation complete"
git push origin epoch4-implementation
git push origin epoch4-complete
```

**Deliverable**: Version-controlled Epoch 4 implementation

---

## 📋 PHASE 7: Future Jobs Migration

### ✅ Task 7.1: Migrate Container List Job
**Status**: PENDING
**Estimated Time**: 2 hours
**Priority**: MEDIUM

Create:
- `jobs/container_list.py` (~50 lines)
- `services/container_list.py` (business logic)

**Success Criteria**: Works with CoreMachine, no custom orchestration

---

### ✅ Task 7.2: Migrate Raster Processing Job
**Status**: PENDING
**Estimated Time**: 3 hours
**Priority**: MEDIUM

Create:
- `jobs/process_raster.py` (~80 lines)
- `services/raster.py` (GDAL operations)

**Success Criteria**: Multi-stage raster workflow with tiling

---

### ✅ Task 7.3: Create STAC Ingest Job
**Status**: PENDING
**Estimated Time**: 2 hours
**Priority**: LOW

Create:
- `jobs/stac_ingest.py` (~60 lines)
- `services/stac.py` (pgstac operations)

**Success Criteria**: STAC items ingested to pgstac schema

---

## 📊 Success Metrics

### Code Quality Targets
- [ ] HelloWorld job: ≤100 lines (vs 1,019 in Epoch 3) ✅ 90% reduction
- [ ] CoreMachine: ~300-400 lines (shared by ALL jobs)
- [ ] Zero God Classes remaining
- [ ] All jobs use declarative pattern

### Performance Targets
- [ ] 1,000 tasks complete in <5 seconds (Service Bus batches)
- [ ] No deadlocks at any scale
- [ ] Advisory locks working correctly

### Developer Experience Targets
- [ ] New job: <2 hours to implement (was days before)
- [ ] Clear error messages throughout
- [ ] Self-documenting code
- [ ] Easy debugging with database endpoints

---

## 🚨 Blocking Issues & Risks

### Potential Blockers

1. **CoreMachine Complexity**
   - Risk: Harder to implement than expected
   - Mitigation: Start with minimal implementation, iterate

2. **Existing Code Dependencies**
   - Risk: Old controllers have hidden dependencies
   - Mitigation: Thorough testing before deletion

3. **Service Bus Coordination**
   - Risk: Batch processing breaks
   - Mitigation: Keep old controller as reference until validated

4. **Task Lineage Implementation**
   - Risk: Context injection complex
   - Mitigation: HelloWorld Stage 2 validates this pattern

---

## 📝 Notes & Lessons Learned

### Key Insights from Epoch 3
- Advisory locks are CRITICAL - don't skip this
- Database functions ARE the orchestration engine
- Composition > Inheritance (proven)
- Declarative > Imperative (obvious in hindsight)

### Important Reminders
- **NO backward compatibility** - fail fast in development
- **Database schema redeploy** after code changes
- **Test locally first** before deploying to Azure
- **Keep backups** until fully validated

---

## 🎯 Current Status

**Last Updated**: 30 SEP 2025

**Phase**: Planning Complete
**Next Step**: Task 1.1 - Inventory Current Working Components
**Blocking Issues**: None
**Estimated Completion**: 2-3 weeks

---

**Ready to begin? Start with Phase 1, Task 1.1!** 🚀
