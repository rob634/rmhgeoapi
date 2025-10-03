# Epoch 4 Job Orchestration Implementation Plan

**Date**: 1 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Ready for Implementation

---

## 🎯 Executive Summary

**Goal**: Replace Epoch 3 controller pattern with Epoch 4 declarative job orchestration using **explicit registration** (no decorators, no import magic).

**Key Principle**: "If it's in the dict, it exists. If it's not, it doesn't."

**Why Explicit Registration?**
- ✅ No decorator timing issues (previous attempt failed)
- ✅ No import order dependencies
- ✅ Crystal clear what's registered (look at the dict!)
- ✅ Azure Functions cold start safe
- ✅ Easy to debug ("is it in the dict?")
- ✅ Only 5-10 job types (not 100)

**If job count grows:** We can refactor to auto-discovery later when we have 50+ jobs. For now, simplicity wins.

---

## 📋 Implementation Tasks

### **Phase 1: Job Registry (Tasks 1-2)**

#### Task 1: Create `jobs/__init__.py`
**Purpose**: Explicit job registry - single source of truth

```python
"""
Job Registry - Explicit Registration

All jobs are registered here explicitly. No decorators, no auto-discovery.
If you don't see it in ALL_JOBS, it's not registered.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from .hello_world import HelloWorldJob

# ============================================================================
# EXPLICIT JOB REGISTRY
# ============================================================================
# To add a new job:
# 1. Create jobs/your_job.py with YourJobClass
# 2. Import it above
# 3. Add entry to ALL_JOBS dict below
# ============================================================================

ALL_JOBS = {
    "hello_world": HelloWorldJob,
    # Add new jobs here explicitly
    # "container_list": ContainerListJob,
    # "process_raster": ProcessRasterJob,
}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_job_registry():
    """Validate all jobs in registry on startup"""
    for job_type, job_class in ALL_JOBS.items():
        if not hasattr(job_class, 'stages'):
            raise ValueError(f"Job {job_type} missing 'stages' attribute")
    return True

# Validate on import
validate_job_registry()
```

**File Size**: ~40 lines
**Dependencies**: None (job classes are just data)
**Testing**: Print ALL_JOBS dict, verify hello_world is present

---

#### Task 2: Create `jobs/hello_world.py`
**Purpose**: HelloWorld job declaration as pure data

```python
"""
HelloWorld Job Declaration - Pure Data

This file declares WHAT the HelloWorld job is, not HOW it executes.
Execution logic lives in services/service_hello_world.py.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field

class HelloWorldJob(BaseModel):
    """
    HelloWorld job declaration - two stages of greetings and replies.

    This is PURE DATA - no execution logic here!
    """

    # Job metadata
    job_type: str = "hello_world"
    description: str = "Simple two-stage greeting workflow for testing"

    # Stage definitions
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",  # Creates n tasks based on params
            "count_param": "n"         # Which parameter controls count
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",  # Same count as stage 1
            "depends_on": 1,
            "uses_lineage": True  # Can access stage 1 results
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "n": {"type": "int", "min": 1, "max": 1000, "default": 3},
        "message": {"type": "str", "default": "Hello World"}
    }

    # Task creation logic (only job-specific code!)
    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str) -> List[dict]:
        """
        Generate task parameters for a stage.

        This is the ONLY job-specific logic - creating task parameters.
        Everything else (queuing, status updates, completion) is handled by CoreMachine.
        """
        n = job_params.get('n', 3)
        message = job_params.get('message', 'Hello World')

        if stage == 1:
            # Stage 1: Create greeting tasks
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-{i}",
                    "task_type": "hello_world_greeting",
                    "parameters": {"index": i, "message": message}
                }
                for i in range(n)
            ]
        elif stage == 2:
            # Stage 2: Create reply tasks (matches stage 1 count)
            return [
                {
                    "task_id": f"{job_id[:8]}-s2-{i}",
                    "task_type": "hello_world_reply",
                    "parameters": {"index": i}
                }
                for i in range(n)
            ]
        else:
            return []
```

**File Size**: ~70 lines
**Dependencies**: Pydantic only
**Testing**: Instantiate HelloWorldJob(), verify stages list

---

### **Phase 2: Handler Registry (Tasks 3-4)**

#### Task 3: Create `services/__init__.py`
**Purpose**: Explicit handler registry - single source of truth

```python
"""
Service Handler Registry - Explicit Registration

All task handlers are registered here explicitly. No decorators, no auto-discovery.
If you don't see it in ALL_HANDLERS, it's not registered.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from .service_hello_world import handle_greeting, handle_reply

# ============================================================================
# EXPLICIT HANDLER REGISTRY
# ============================================================================
# To add a new handler:
# 1. Create function in services/service_*.py
# 2. Import it above
# 3. Add entry to ALL_HANDLERS dict below
# ============================================================================

ALL_HANDLERS = {
    "hello_world_greeting": handle_greeting,
    "hello_world_reply": handle_reply,
    # Add new handlers here explicitly
    # "process_tile": handle_tile_processing,
    # "validate_geotiff": handle_geotiff_validation,
}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_handler_registry():
    """Validate all handlers in registry on startup"""
    for task_type, handler in ALL_HANDLERS.items():
        if not callable(handler):
            raise ValueError(f"Handler {task_type} is not callable")
    return True

# Validate on import
validate_handler_registry()
```

**File Size**: ~45 lines
**Dependencies**: service_hello_world
**Testing**: Print ALL_HANDLERS dict, verify both handlers present

---

#### Task 4: Update `services/service_hello_world.py`
**Purpose**: Pure handler functions - no decorators, no magic

```python
"""
HelloWorld Service Handlers - Pure Business Logic

These are pure functions that execute task logic. No decorators, no registration magic.
Registration happens explicitly in services/__init__.py.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

def handle_greeting(task_params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle greeting task - pure business logic.

    Args:
        task_params: Task parameters (index, message)
        context: Optional context (not used in stage 1)

    Returns:
        Task result data
    """
    index = task_params.get('index', 0)
    message = task_params.get('message', 'Hello World')

    return {
        "success": True,
        "greeting": f"{message} from task {index}!",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_index": index
    }


def handle_reply(task_params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle reply task - uses lineage to access predecessor.

    Args:
        task_params: Task parameters (index)
        context: Context with predecessor results

    Returns:
        Task result data
    """
    index = task_params.get('index', 0)

    # Access predecessor result if context provided
    predecessor_greeting = "unknown"
    if context and 'predecessor_result' in context:
        predecessor_greeting = context['predecessor_result'].get('greeting', 'unknown')

    return {
        "success": True,
        "reply": f"Replying to: {predecessor_greeting}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_index": index
    }
```

**File Size**: ~60 lines
**Dependencies**: None (pure Python)
**Testing**: Call functions directly, verify return structure

---

### **Phase 3: CoreMachine (Task 5)**

#### Task 5: Update `core/machine.py`
**Purpose**: Universal orchestrator with explicit registry lookups

**Key Changes:**
```python
class CoreMachine:
    """
    Universal job orchestration engine.
    Works with explicit registries - no decorator magic.
    """

    def __init__(self, all_jobs: Dict[str, Any], all_handlers: Dict[str, callable]):
        """
        Initialize with EXPLICIT registries.

        Args:
            all_jobs: ALL_JOBS dict from jobs/__init__.py
            all_handlers: ALL_HANDLERS dict from services/__init__.py
        """
        self.jobs_registry = all_jobs
        self.handlers_registry = all_handlers
        self.state_manager = StateManager()
        self.orchestrator = OrchestrationManager()

    def process_job_message(self, message: JobQueueMessage):
        """Generic job processing using explicit job registry"""
        job_type = message.job_type

        # EXPLICIT lookup - crystal clear!
        if job_type not in self.jobs_registry:
            available = list(self.jobs_registry.keys())
            raise ValueError(f"Unknown job type: {job_type}. Available: {available}")

        job_class = self.jobs_registry[job_type]
        # Continue processing...

    def process_task_message(self, message: TaskQueueMessage):
        """Generic task processing using explicit handler registry"""
        task_type = message.task_type

        # EXPLICIT lookup - no mystery!
        if task_type not in self.handlers_registry:
            available = list(self.handlers_registry.keys())
            raise ValueError(f"Unknown task type: {task_type}. Available: {available}")

        handler = self.handlers_registry[task_type]
        # Execute handler...
```

**File Size**: ~300-400 lines (already mostly exists)
**Dependencies**: StateManager, OrchestrationManager (already exist)
**Testing**: Pass test dicts to constructor, verify lookups work

---

### **Phase 4: Function App Integration (Tasks 6-9)**

#### Task 6: Update `function_app.py` - Explicit imports at top
**Purpose**: Single point of truth for all registries

```python
# ============================================================================
# EXPLICIT REGISTRIES - Everything visible here!
# ============================================================================
# All jobs and handlers imported explicitly at module level.
# No decorators, no auto-discovery, no import timing issues.
# ============================================================================

from jobs import ALL_JOBS, validate_job_registry
from services import ALL_HANDLERS, validate_handler_registry
from core.machine import CoreMachine

# Validate registries on startup
validate_job_registry()
validate_handler_registry()

# Create CoreMachine with explicit registries
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS
)

# Log what's registered (for debugging)
logger.info(f"Registered jobs: {list(ALL_JOBS.keys())}")
logger.info(f"Registered handlers: {list(ALL_HANDLERS.keys())}")
```

**Lines Changed**: ~20 lines at top of file
**Benefit**: Everything registered is visible in one place!

---

#### Task 7: Update `triggers/submit_job.py`
**Purpose**: Use ALL_JOBS dict instead of JobFactory

**Before (Epoch 3):**
```python
from controller_factories import JobFactory
controller = JobFactory.create_controller(job_type)
```

**After (Epoch 4):**
```python
from jobs import ALL_JOBS

if job_type not in ALL_JOBS:
    raise ValueError(f"Unknown job: {job_type}. Available: {list(ALL_JOBS.keys())}")

job_class = ALL_JOBS[job_type]
# Create job using CoreMachine
```

**Lines Changed**: ~10 lines
**Benefit**: Direct dict lookup, no factory abstraction

---

#### Task 8: Update `function_app.py` - Job Queue Processor
**Purpose**: Use CoreMachine for job processing

**Before (Epoch 3):**
```python
controller = JobFactory.create_controller(message.job_type)
controller.process_job(message)
```

**After (Epoch 4):**
```python
# CoreMachine already initialized with registries
core_machine.process_job_message(message)
```

**Lines Changed**: ~5 lines in job queue handler
**Benefit**: Single universal orchestrator

---

#### Task 9: Update `function_app.py` - Task Queue Processor
**Purpose**: Use ALL_HANDLERS for task execution

**Before (Epoch 3):**
```python
handler = TaskRegistry.get_handler(message.task_type)
result = handler(message.parameters)
```

**After (Epoch 4):**
```python
# CoreMachine already has ALL_HANDLERS
core_machine.process_task_message(message)
```

**Lines Changed**: ~5 lines in task queue handler
**Benefit**: Consistent with job processing

---

### **Phase 5: Testing (Task 10)**

#### Task 10: Deploy and Test
**Purpose**: Verify end-to-end functionality

**Test Steps:**
```bash
# 1. Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote

# 2. Verify registries loaded
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
# Look for "Registered jobs: ['hello_world']" in logs

# 3. Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "Epoch 4 test", "n": 2}'

# 4. Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# 5. Verify completion
# Should show: 2 tasks in stage 1 (completed), 2 tasks in stage 2 (completed), job status: completed
```

**Success Criteria:**
- ✅ No import errors on startup
- ✅ Registries show correct job/handler counts in logs
- ✅ HelloWorld job completes both stages
- ✅ All 4 tasks (2 per stage) complete successfully
- ✅ No Epoch 3 controllers used (verified in logs)

---

## 🎯 Benefits of Explicit Registration

### **Simplicity**
- Look at `ALL_JOBS` dict → see all registered jobs
- Look at `ALL_HANDLERS` dict → see all registered handlers
- No hidden registration failures
- No import timing mysteries

### **Reliability**
- Everything imported explicitly in `function_app.py`
- No decorator timing issues
- No auto-discovery race conditions
- Azure Functions cold start safe

### **Debuggability**
- "Why isn't my job registered?" → Look at ALL_JOBS dict
- "Why isn't my handler found?" → Look at ALL_HANDLERS dict
- Can print registries on startup for verification
- Can grep for registration easily

### **Scalability Strategy**
**Current (5-10 jobs):** Explicit registration is perfect
**Future (50+ jobs):** Can refactor to auto-discovery when needed
- Add `_discover_jobs()` function in `jobs/__init__.py`
- Scan `jobs/` directory for `*_job.py` files
- Auto-populate `ALL_JOBS` dict
- But only when we actually have 50+ jobs!

### **No Magic, No Surprises**
- What you see is what you get
- No decorators that silently fail
- No import order dependencies
- Boring, predictable, reliable

---

## 📊 Estimated Implementation Time

| Phase | Tasks | Estimated Time | Complexity |
|-------|-------|----------------|------------|
| Phase 1: Job Registry | 1-2 | 30 minutes | Low |
| Phase 2: Handler Registry | 3-4 | 30 minutes | Low |
| Phase 3: CoreMachine | 5 | 1-2 hours | Medium |
| Phase 4: Integration | 6-9 | 1 hour | Medium |
| Phase 5: Testing | 10 | 30 minutes | Low |
| **Total** | **10 tasks** | **3-4 hours** | **Medium** |

---

## 🚀 Post-Implementation

### **What Gets Removed:**
- ❌ `controller_factories.py` (archive)
- ❌ `registration.py` (archive)
- ❌ `controller_base.py` (archive)
- ❌ `controller_hello_world.py` (archive - replaced by jobs/hello_world.py)
- ❌ All decorator registration code

### **What Stays:**
- ✅ `controller_service_bus_hello.py` (reference for CoreMachine patterns)
- ✅ `core/state_manager.py` (used by CoreMachine)
- ✅ `core/orchestration_manager.py` (used by CoreMachine)
- ✅ `infrastructure/` (repository layer unchanged)

### **Future Jobs:**
Adding a new job is trivial:
1. Create `jobs/your_job.py` with job class
2. Add import to `jobs/__init__.py`
3. Add entry to `ALL_JOBS` dict
4. Create handler functions in `services/service_your_job.py`
5. Add imports to `services/__init__.py`
6. Add entries to `ALL_HANDLERS` dict
7. Done!

**~10 minutes to add a new job** once the infrastructure is in place.

---

## 📝 Success Metrics

### **Code Quality:**
- ✅ No files over 400 lines
- ✅ Clear separation: jobs/ (data) vs services/ (logic) vs core/ (orchestration)
- ✅ No decorator magic
- ✅ All imports explicit and visible

### **Functionality:**
- ✅ HelloWorld completes both stages
- ✅ Tasks execute in correct order
- ✅ Results flow between stages via lineage
- ✅ Job completion detection works

### **Developer Experience:**
- ✅ Adding new job takes ~10 minutes
- ✅ Easy to understand what's registered
- ✅ No mysterious registration failures
- ✅ Clear error messages ("Unknown job: X. Available: [Y, Z]")

---

**Ready for Implementation**: Yes
**Complexity**: Medium (mostly integration work)
**Risk**: Low (explicit approach avoids previous decorator failures)
**Next Step**: Start with Task 1 (jobs/__init__.py)
