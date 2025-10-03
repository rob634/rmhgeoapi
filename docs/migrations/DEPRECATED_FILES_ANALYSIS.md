# Deprecated Files Analysis - Archival Readiness

**Date**: 1 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Summary

**Status**: ❌ **CANNOT ARCHIVE YET**

Epoch 3 deprecated files are still required by **Azure Storage Queue triggers** in function_app.py.

## Deprecated Files (8 total)

1. ✅ `controller_base.py` (2,290 lines) - God Class
2. ✅ `controller_hello_world.py` - HelloWorld controller
3. ✅ `controller_container.py` - Container controllers
4. ✅ `controller_service_bus.py` - Service Bus base
5. ✅ `controller_service_bus_hello.py` - Service Bus HelloWorld
6. ✅ `controller_service_bus_container.py` - Service Bus Container
7. ✅ `controller_stac_setup.py` - STAC setup controller
8. ✅ `update_epoch_headers.py` - Utility script (safe to archive)

## Dependency Analysis

### Active Files Importing Deprecated Code:

#### 1. `function_app.py` (PRIMARY BLOCKER)

**Lines 200-203**: Controller registration for Storage Queue
```python
from controller_hello_world import HelloWorldController
from controller_container import SummarizeContainerController, ListContainerController
from controller_stac_setup import STACSetupController
from controller_service_bus_hello import ServiceBusHelloWorldController
```

**Lines 665-920**: Storage Queue triggers
```python
@app.queue_trigger(queue_name="geospatial-jobs", ...)
def process_job_queue(msg: func.QueueMessage):
    # Uses Epoch 3 controllers via JobFactory
    controller = JobFactory.create_controller(job_type)

@app.queue_trigger(queue_name="geospatial-tasks", ...)
def process_task_queue(msg: func.QueueMessage):
    # Uses Epoch 3 controllers via JobFactory
```

#### 2. `triggers/submit_job.py` (SECONDARY BLOCKER)

**Lines 225-227**: Import for registration
```python
import controller_hello_world  # Import to trigger registration
import controller_container  # Import to trigger registration
import controller_stac_setup  # Import to trigger registration
```

**Why needed**: HTTP trigger uses JobFactory which requires controllers registered

#### 3. `core/schema/workflow.py` (WORKFLOW DEFINITION)

**Lines 486-490**: Direct workflow import
```python
if job_type in ["summarize_container", "list_container"]:
    from controller_container import summarize_container_workflow, list_container_workflow
```

**Why needed**: Container workflows still defined in Epoch 3 controller

## Why These Files Are Still Needed

### Azure Storage Queue Pipeline (Epoch 3)

**Active Triggers**:
- `@app.queue_trigger(queue_name="geospatial-jobs")` - Line 665
- `@app.queue_trigger(queue_name="geospatial-tasks")` - Line 883

**Flow**:
```
Storage Queue Message
    ↓
function_app.py::process_job_queue()
    ↓
JobFactory.create_controller(job_type)
    ↓
Epoch 3 Controller (controller_hello_world, controller_container, etc.)
    ↓
BaseController orchestration
```

### Azure Service Bus Pipeline (Epoch 4)

**Active Triggers**:
- `@app.service_bus_queue_trigger(queue_name="geospatial-jobs")` - Line 1112
- `@app.service_bus_queue_trigger(queue_name="geospatial-tasks")` - Line 1164

**Flow**:
```
Service Bus Message
    ↓
function_app.py::process_service_bus_job()
    ↓
CoreMachine.process_job_message()
    ↓
Epoch 4 Workflow (jobs/hello_world.py)
    ↓
Epoch 4 TaskExecutor (services/hello_world.py)
```

## Current State: Dual Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    function_app.py                          │
│                                                             │
│  Epoch 3 Pipeline (Storage Queue)                          │
│  ├─ @app.queue_trigger("geospatial-jobs")                  │
│  │   └─ JobFactory → controller_hello_world (Epoch 3)      │
│  └─ @app.queue_trigger("geospatial-tasks")                 │
│      └─ JobFactory → controller_container (Epoch 3)        │
│                                                             │
│  Epoch 4 Pipeline (Service Bus) ✅                          │
│  ├─ @app.service_bus_queue_trigger("geospatial-jobs")      │
│  │   └─ CoreMachine → jobs/hello_world.py (Epoch 4)        │
│  └─ @app.service_bus_queue_trigger("geospatial-tasks")     │
│      └─ CoreMachine → services/hello_world.py (Epoch 4)    │
└─────────────────────────────────────────────────────────────┘
```

## Migration Path to Archive Deprecated Files

### Phase 1: Migrate Storage Queue Triggers to CoreMachine ⏳

**Goal**: Make Storage Queue triggers use CoreMachine instead of Epoch 3 controllers

**Changes Needed**:

1. **Update `function_app.py` lines 665-920**:
   ```python
   # Before (Epoch 3)
   @app.queue_trigger(queue_name="geospatial-jobs", ...)
   def process_job_queue(msg: func.QueueMessage):
       controller = JobFactory.create_controller(job_type)
       controller.process_job_message(message)

   # After (Epoch 4)
   @app.queue_trigger(queue_name="geospatial-jobs", ...)
   def process_job_queue(msg: func.QueueMessage):
       job_message = JobQueueMessage.model_validate_json(msg.get_body())
       result = core_machine.process_job_message(job_message)
   ```

2. **Update `triggers/submit_job.py`**:
   - Remove imports of Epoch 3 controllers
   - Use CoreMachine for job submission

3. **Migrate container workflows**:
   - Move `summarize_container_workflow` and `list_container_workflow` from `controller_container.py`
   - To new files: `jobs/container_summarize.py`, `jobs/container_list.py`
   - Register with `@register_job` decorator

### Phase 2: Remove Epoch 3 Imports ⏳

**After Phase 1 complete**, remove these imports from `function_app.py`:

```python
# REMOVE THESE:
from controller_hello_world import HelloWorldController
from controller_container import SummarizeContainerController, ListContainerController
from controller_stac_setup import STACSetupController
from controller_service_bus_hello import ServiceBusHelloWorldController
from controller_service_bus_container import ServiceBusContainerController
```

### Phase 3: Archive Deprecated Files ✅

**Only after Phases 1-2 complete**, move to archive:

```bash
mkdir -p archive/epoch3_controllers
mv controller_*.py archive/epoch3_controllers/
mv update_epoch_headers.py archive/epoch3_controllers/
```

## Files Safe to Archive NOW

### ✅ Can Archive Immediately:

**`update_epoch_headers.py`** - Utility script, not imported by any active code

```bash
mkdir -p archive/utilities
mv update_epoch_headers.py archive/utilities/
```

## Timeline Estimate

### Phase 1: Migrate Storage Queue Triggers (4-6 hours)
- [ ] Update `function_app.py` Storage Queue triggers to use CoreMachine
- [ ] Migrate container workflows to Epoch 4 pattern
- [ ] Update `triggers/submit_job.py` to remove Epoch 3 dependencies
- [ ] Test Storage Queue end-to-end

### Phase 2: Remove Imports (30 minutes)
- [ ] Remove Epoch 3 controller imports from `function_app.py`
- [ ] Remove Epoch 3 controller imports from `triggers/submit_job.py`
- [ ] Update `core/schema/workflow.py` to use Epoch 4 workflows
- [ ] Test that no import errors occur

### Phase 3: Archive (15 minutes)
- [ ] Create archive folder structure
- [ ] Move deprecated files to archive
- [ ] Update documentation
- [ ] Final verification tests

**Total Estimated Time**: 5-7 hours

## Decision Point

### Option 1: Keep Dual Pipeline (Current State)
**Pros**:
- No migration work required
- Storage Queue still works
- Gradual migration possible

**Cons**:
- Maintaining two systems
- Code duplication
- Confusion about which pipeline to use

### Option 2: Migrate to Single Pipeline (Recommended)
**Pros**:
- Single source of truth (CoreMachine)
- Can archive deprecated code
- Cleaner architecture

**Cons**:
- Requires migration work (5-7 hours)
- Need to test Storage Queue thoroughly

### Option 3: Deprecate Storage Queue Entirely
**Pros**:
- Only use Service Bus (simpler)
- Can archive deprecated code immediately

**Cons**:
- Loses Storage Queue capability
- May need Storage Queue for specific use cases

## Recommendation

**Proceed with Option 2: Migrate to Single Pipeline**

**Rationale**:
1. Service Bus is the future (better for batch processing)
2. CoreMachine is cleaner architecture
3. But keep Storage Queue capability (useful for small jobs)
4. 5-7 hours of work to remove 8 deprecated files (2,500+ lines)

**Next Step**: Create detailed migration plan for Phase 1

## Current Status

❌ **Cannot archive yet** - 3 active files still depend on Epoch 3 controllers:
- `function_app.py` - Storage Queue triggers
- `triggers/submit_job.py` - HTTP job submission
- `core/schema/workflow.py` - Container workflow definitions

**Blocker**: Storage Queue triggers still use Epoch 3 controllers via JobFactory

**Resolution**: Migrate Storage Queue triggers to use CoreMachine (Phase 1)

---

**Last Updated**: 1 OCT 2025
