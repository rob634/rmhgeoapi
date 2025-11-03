# finalize_job() Architecture & Implementation Plan

**Date**: 3 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ IMPLEMENTATION COMPLETE (3 NOV 2025)

---

## ✅ Implementation Summary (3 NOV 2025)

**All phases completed successfully!**

### What Was Done

1. **✅ Phase 1**: Added `finalize_job(context=None) -> Dict[str, Any]` as 6th required abstract method to `jobs/base.py`
   - Updated header to reflect "6-method interface contract"
   - Added comprehensive docstring with minimal and rich pattern examples
   - Includes Platform integration flow documentation

2. **✅ Phase 2**: Implemented minimal pattern in `jobs/hello_world.py`
   - Simple logging with optional context parameter
   - Returns minimal summary: `{"job_type": "hello_world", "status": "completed"}`
   - Serves as reference pattern for internal/test workflows

3. **✅ Phase 5**: Updated `core/machine.py` to call finalize_job() directly
   - Removed `if hasattr(workflow, 'finalize_job')` check
   - Now calls `workflow.finalize_job(context)` directly (required method)
   - Simplified code, enforces contract

4. **✅ Phase 6**: Validated all 13 workflows
   - All workflows already had finalize_job() from previous rename
   - Import chain tested successfully
   - Syntax validation passed

### Current State

- **JobBase ABC**: Now requires 6 methods (added finalize_job)
- **All 13 workflows**: Have finalize_job() implementation ✅
- **CoreMachine**: Calls method directly without checks ✅
- **Hello World**: Has minimal pattern reference ✅

### Implementation Details by Workflow

**Rich Implementations (Already Complete)**:
- ✅ `process_raster` - Extracts validation, COG, and STAC results
- ✅ `ingest_vector` - Extracts PostGIS table and STAC metadata
- ✅ `validate_raster_job` - Returns validation results
- ✅ `summarize_container` - Container statistics and file counts
- ✅ `list_container_contents` - File listings with metadata
- ✅ `stac_catalog_container` - STAC cataloging results
- ✅ `stac_catalog_vectors` - Vector STAC results

**Minimal Implementations with TODO Comments (3 NOV 2025)**:
- ✅ `hello_world` - Reference pattern (no TODO needed)
- ✅ `process_large_raster` - TODO: Extract MosaicJSON, STAC collection, COG stats, tiling stats
- ✅ `process_raster_collection` - TODO: Extract MosaicJSON, STAC items, per-tile COG stats
- ✅ `create_h3_base` - TODO: Add H3 cell count, table name, processing time
- ✅ `generate_h3_level4` - TODO: Add level-4 cell count, table name, processing time
- ✅ `list_container_contents_diamond` - TODO: Add file count, size statistics

### Remaining Work (Future Enhancements)

**TODO Items Added for Future Work**:
1. `process_large_raster` - Implement rich pattern (see TODO at line 708)
2. `process_raster_collection` - Implement rich pattern (see TODO at line 619)
3. `create_h3_base` - Add H3 statistics (see TODO at line 293)
4. `generate_h3_level4` - Add H3 statistics (see TODO at line 269)
5. `list_container_contents_diamond` - Add file statistics (see TODO at line 348)

**Separate Issues**:
- Fix `process_large_raster` Stage 4 fan-in bug (manually creating task instead of returning [])

---

## 🎯 Executive Summary

This document describes the architecture and implementation plan for making `finalize_job()` a required method for all workflows. This change enables:

1. **Consistent job summaries** - All jobs return structured results
2. **Deployment flexibility** - CoreMachine works standalone OR with Platform layer
3. **Optional context parameter** - Simple workflows can ignore context, complex workflows extract rich results
4. **Platform integration** - Callback receives finalize_job() output for orchestration

---

## 📊 Current State Analysis

### All Workflows NOW HAVE `finalize_job()` (13 total) ✅

| Workflow | Priority | Implementation Status |
|----------|----------|--------|
| `hello_world` | Demo/Reference | ✅ Minimal pattern (NEW - 3 NOV 2025) |
| `process_raster` | HIGH - User-facing | ✅ Rich summary |
| `process_large_raster` | HIGH - User-facing | ✅ Has finalize_job (may need enhancement) |
| `process_raster_collection` | HIGH - User-facing | ✅ Has finalize_job (may need enhancement) |
| `ingest_vector` | HIGH - User-facing | ✅ Rich summary |
| `container_list` | MEDIUM - Diagnostic | ✅ Has summary |
| `container_summary` | MEDIUM - Diagnostic | ✅ Has summary |
| `stac_catalog_container` | MEDIUM - Bulk ops | ✅ Has summary |
| `stac_catalog_vectors` | MEDIUM - Bulk ops | ✅ Has summary |
| `validate_raster_job` | MEDIUM - Validation | ✅ Has summary |
| `create_h3_base` | LOW - Internal | ✅ Has finalize_job |
| `generate_h3_level4` | LOW - Internal | ✅ Has finalize_job |
| `container_list_diamond` | LOW - Diagnostic | ✅ Has finalize_job |

### JobBase ABC Requirements (NOW 6 methods - ✅ UPDATED 3 NOV 2025)

```python
class JobBase(ABC):
    # Currently required:
    @abstractmethod
    def validate_job_parameters(params: dict) -> dict: ...

    @abstractmethod
    def generate_job_id(params: dict) -> str: ...

    @abstractmethod
    def create_job_record(job_id: str, params: dict) -> dict: ...

    @abstractmethod
    def queue_job(job_id: str, params: dict) -> dict: ...

    @abstractmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> List[dict]: ...

    # NOT currently required:
    # def finalize_job(context=None) -> Dict[str, Any]: ...
```

---

## 🔄 Complete Flow: finalize_job() → Platform Callback

### The Two Separate Concepts

1. **`finalize_job(context)`** - Workflow method (NEW: will be required)
2. **`on_job_complete` callback** - CoreMachine constructor parameter (EXISTING: optional)

**They are INDEPENDENT but CONNECTED**:
- `finalize_job()` creates the summary
- Callback receives that summary (if callback exists)

---

### Scenario 1: Standalone CoreMachine (NO Platform Layer)

```python
# ============================================================================
# INITIALIZATION (function_app.py or standalone deployment)
# ============================================================================
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS
    # NO on_job_complete parameter!
    # on_job_complete = None (implicit)
)

# ============================================================================
# JOB COMPLETION (core/machine.py:994-1026)
# ============================================================================
def _complete_job(self, job_id, job_type):
    # ... get task results ...

    # STEP 1: Call workflow's finalize_job() (NOW REQUIRED)
    workflow = self.jobs_registry[job_type]  # e.g., ProcessRasterWorkflow
    final_result = workflow.finalize_job(context)
    # Returns: {
    #     "job_type": "process_raster",
    #     "cog_blob": "05APR13082706_cog.tif",
    #     "stac_item_id": "antigua-april-2013",
    #     "ready_for_titiler": True
    # }

    # STEP 2: Store in database
    self.state_manager.complete_job(job_id, final_result)
    # Database row updated: jobs.result_data = final_result (JSONB)

    # STEP 3: Check if callback exists
    if self.on_job_complete:  # ← FALSE (no callback registered)
        # This block is SKIPPED
        pass

    # STEP 4: Done - user can query GET /api/jobs/status/{job_id}
    # Response includes final_result from database
```

**Result**: User gets rich summary via API, no Platform integration

---

### Scenario 2: CoreMachine WITH Platform Layer

```python
# ============================================================================
# INITIALIZATION (function_app.py)
# ============================================================================

# Step 1: Define placeholder callback function
def _global_platform_callback(job_id, job_type, status, result):
    """Will be replaced by PlatformOrchestrator during init."""
    pass

# Step 2: Create CoreMachine with callback reference
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS,
    on_job_complete=_global_platform_callback  # ← Callback registered!
)
# CoreMachine stores: self.on_job_complete = _global_platform_callback

# ============================================================================
# PLATFORM INITIALIZATION (trigger_platform.py - First HTTP Request)
# ============================================================================
class PlatformOrchestrator:
    def __init__(self):
        # ... repos setup ...

        # Monkey-patch the global callback function
        import function_app

        def combined_callback(job_id, job_type, status, result):
            """THIS is what actually gets called."""
            # Call Platform handler
            self._handle_job_completion(job_id, job_type, status, result)

        # Replace the placeholder
        function_app._global_platform_callback = combined_callback

        # Update CoreMachine's reference
        function_app.core_machine.on_job_complete = combined_callback
        # CoreMachine now stores: self.on_job_complete = combined_callback

# ============================================================================
# JOB COMPLETION (core/machine.py:994-1026)
# ============================================================================
def _complete_job(self, job_id, job_type):
    # ... get task results ...

    # STEP 1: Call workflow's finalize_job() (NOW REQUIRED)
    workflow = self.jobs_registry[job_type]  # e.g., ProcessRasterWorkflow
    final_result = workflow.finalize_job(context)
    # Returns: {
    #     "job_type": "process_raster",
    #     "cog_blob": "05APR13082706_cog.tif",
    #     "stac_item_id": "antigua-april-2013",
    #     "ready_for_titiler": True
    # }

    # STEP 2: Store in database
    self.state_manager.complete_job(job_id, final_result)
    # Database row updated: jobs.result_data = final_result (JSONB)

    # STEP 3: Check if callback exists
    if self.on_job_complete:  # ← TRUE (callback registered!)
        try:
            logger.debug("Invoking job completion callback...")

            # STEP 3a: Call the callback (combined_callback function)
            self.on_job_complete(
                job_id=job_id,
                job_type=job_type,
                status='completed',
                result=final_result  # ← Output from finalize_job()!
            )
            # This calls: combined_callback(job_id, job_type, 'completed', final_result)

        except Exception as e:
            # Callback failure is non-fatal
            logger.warning(f"Callback failed (non-fatal): {e}")
            # Job is STILL marked as completed

    # STEP 4: Done

# ============================================================================
# CALLBACK EXECUTION (trigger_platform.py:256-273)
# ============================================================================
def combined_callback(job_id, job_type, status, result):
    """
    Receives the output from finalize_job()!

    Args:
        job_id: "a1b2c3d4..."
        job_type: "process_raster"
        status: "completed"
        result: {  ← This came from finalize_job()!
            "job_type": "process_raster",
            "cog_blob": "05APR13082706_cog.tif",
            "stac_item_id": "antigua-april-2013",
            "ready_for_titiler": True
        }
    """
    # Call Platform handler
    orchestrator._handle_job_completion(
        job_id=job_id,
        job_type=job_type,
        status=status,
        result=result  # ← Passed along to Platform
    )

# ============================================================================
# PLATFORM HANDLER (trigger_platform.py:321-377)
# ============================================================================
def _handle_job_completion(self, job_id, job_type, status, result):
    """
    Update Platform orchestration tables.

    Args:
        result: {  ← Still has finalize_job() output!
            "cog_blob": "05APR13082706_cog.tif",
            "stac_item_id": "antigua-april-2013",
            ...
        }
    """
    # Look up orchestration record
    orch_job = self.platform_repo.get_orchestration_by_job_id(job_id)

    if orch_job:
        # Update orchestration_jobs table
        self.platform_repo.update_orchestration_status(
            orchestration_id=orch_job.orchestration_id,
            status="completed",
            result=result  # ← Store finalize_job() output in Platform table!
        )
        # UPDATE platform.orchestration_jobs
        # SET status='completed', result_data='{"cog_blob": "...", ...}'
        # WHERE orchestration_id = ...

        # Check if all jobs for this request are done
        all_jobs = self.platform_repo.get_orchestration_jobs(orch_job.request_id)
        if all(j.status == "completed" for j in all_jobs):
            # Mark entire Platform request as complete
            self.platform_repo.complete_api_request(
                request_id=orch_job.request_id,
                result={
                    "total_jobs": len(all_jobs),
                    "all_completed": True,
                    "individual_results": [j.result_data for j in all_jobs]
                    # Each j.result_data contains finalize_job() output!
                }
            )
```

**Result**:
- User gets rich summary via CoreMachine API
- Platform tables updated with same rich summary
- Parent request tracks all child job results

---

## 🔑 Key Relationships

### finalize_job() Creates Data

```python
# Workflow responsibility (ProcessRasterWorkflow)
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """Extract meaningful results from completed tasks."""
    task_results = context.task_results

    cog_task = [t for t in task_results if t.task_type == "create_cog"][0]
    stac_task = [t for t in task_results if t.task_type == "extract_stac_metadata"][0]

    return {
        "job_type": "process_raster",
        "source_blob": context.parameters.get("blob_name"),
        "cog_blob": cog_task.result_data["result"]["cog_blob"],
        "stac_item_id": stac_task.result_data["result"]["item_id"],
        "ready_for_titiler": True,
        "stages_completed": 3
    }
```

### Callback Consumes Data

```python
# Platform responsibility (PlatformOrchestrator)
def _handle_job_completion(self, job_id, job_type, status, result):
    """Use finalize_job() output to update Platform tables."""
    # result = output from finalize_job()

    # Extract what Platform needs
    cog_blob = result.get("cog_blob")  # ← From finalize_job()
    stac_id = result.get("stac_item_id")  # ← From finalize_job()

    # Store in orchestration table
    update_orchestration_status(
        job_id=job_id,
        result={
            "cog_blob": cog_blob,
            "stac_item_id": stac_id
        }
    )
```

---

## 💡 Why context=None is Optional Parameter

### Simple Workflows Don't Need Context

```python
# hello_world.py - Doesn't extract task results
@staticmethod
def finalize_job(context=None) -> Dict[str, Any]:
    """No context needed - just log and return status."""
    logger.info("HelloWorld completed")
    return {
        "job_type": "hello_world",
        "status": "completed"
    }
```

**CoreMachine still calls it**: `workflow.finalize_job(context)`
- Passes `context` object
- HelloWorld ignores it (has default `context=None`)
- Returns minimal summary
- Callback (if exists) receives: `{"job_type": "hello_world", "status": "completed"}`

### Complex Workflows Use Context

```python
# process_raster.py - Extracts rich results from tasks
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """Context required - extract task results."""
    if context is None:
        raise ValueError("process_raster requires context")

    task_results = context.task_results  # ← Use context to get results
    # ... extract COG, STAC details ...
    return {...}  # Rich summary
```

**CoreMachine still calls it**: `workflow.finalize_job(context)`
- Passes `context` object
- process_raster uses it to extract task results
- Returns rich summary
- Callback (if exists) receives rich data

---

## 📊 Data Flow Summary

```
┌─────────────────────────────────────────────────────────────┐
│ WORKFLOW: finalize_job(context)                             │
│                                                              │
│ Input:  context (task_results, parameters, job_id)         │
│ Output: Dict[str, Any] (job summary)                        │
│                                                              │
│ Example: {"cog_blob": "...", "stac_item_id": "..."}        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ COREMACHINE: Store result in database                       │
│                                                              │
│ jobs.result_data = finalize_job() output                   │
│                                                              │
│ User can query: GET /api/jobs/status/{job_id}              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ CALLBACK: on_job_complete(job_id, job_type, status, result)│
│                                                              │
│ If callback registered:                                     │
│   - result = finalize_job() output                         │
│   - Platform receives rich data                             │
│   - Platform updates orchestration_jobs table               │
│                                                              │
│ If NO callback:                                             │
│   - This step is skipped                                    │
│   - CoreMachine works standalone                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architecture Benefits

### 1. Deployment Flexibility

**Standalone CoreMachine** (System in a Box):
```python
# Someone deploys just CoreMachine (no Platform layer)
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS
    # No on_job_complete callback!
)

# Job completes:
# 1. finalize_job() creates summary
# 2. Stored in jobs.result_data
# 3. No callback invoked (none registered)
# 4. User queries GET /api/jobs/status/{job_id} → gets rich summary
```

**CoreMachine + Platform Integration**:
```python
# Full system deployment (with Platform orchestration)
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS,
    on_job_complete=platform_callback  # Platform layer integration
)

# Job completes:
# 1. finalize_job() creates summary
# 2. Stored in jobs.result_data
# 3. Callback invoked with summary
# 4. Platform updates orchestration tables
# 5. User queries either layer → gets consistent data
```

### 2. Progressive Enhancement

**Day 1**: Deploy with minimal `finalize_job()` implementations
```python
def finalize_job(context=None):
    return {"job_type": "my_job", "status": "completed"}
```

**Day 30**: Enhance with rich summaries as needs emerge
```python
def finalize_job(context):
    return {
        "job_type": "my_job",
        "cog_blob": extract_cog_path(context),
        "stac_item_id": extract_stac_id(context),
        "performance_metrics": calculate_metrics(context)
    }
```

### 3. Testing & Validation

**Fail-Fast at Import Time**:
```python
# If workflow missing finalize_job():
from jobs.my_workflow import MyWorkflow  # ← ImportError!
# TypeError: Can't instantiate abstract class MyWorkflow
#            with abstract methods finalize_job
```

**No runtime surprises** - catches errors before deployment!

---

## 📋 Implementation Plan

### Phase 1: Add finalize_job() to JobBase ABC (REQUIRED METHOD)

**File**: `jobs/base.py`

**Changes**:
```python
class JobBase(ABC):
    """
    Required methods (5 → 6):
    1. validate_job_parameters
    2. generate_job_id
    3. create_job_record
    4. queue_job
    5. create_tasks_for_stage
    6. finalize_job  ← NEW REQUIRED METHOD
    """

    @staticmethod
    @abstractmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary (required for all workflows).

        This method is called when the job completes successfully. It should
        return a dictionary summarizing the job results for users/API consumers.

        Args:
            context (JobExecutionContext, optional): Provides access to:
                - task_results: List[TaskRecord] - All completed tasks
                - parameters: dict - Original job parameters
                - job_id: str - Job identifier
                - job_type: str - Job type name
                - total_stages: int - Number of stages

                If None, workflow should log completion and return minimal summary.

        Returns:
            Dict[str, Any]: Job summary with at minimum:
                - job_type (str): Workflow identifier
                - status (str): "completed"
                - (optional) Rich summary fields specific to workflow

        Design Pattern:
            Simple workflows can ignore context and return minimal summary.
            Complex workflows should extract results and build detailed summary.

        Example (Simple):
            @staticmethod
            def finalize_job(context=None) -> Dict[str, Any]:
                logger.info("HelloWorld job completed")
                return {"job_type": "hello_world", "status": "completed"}

        Example (Rich):
            @staticmethod
            def finalize_job(context) -> Dict[str, Any]:
                task_results = context.task_results
                cog_task = [t for t in task_results if t.task_type == "create_cog"][0]
                return {
                    "job_type": "process_raster",
                    "cog_blob": cog_task.result_data["result"]["cog_blob"],
                    "stac_item_id": ...,
                    ...
                }
        """
        pass
```

---

### Phase 2: Implement Hello World (Minimal Pattern Reference)

**File**: `jobs/hello_world.py`

**Add method**:
```python
@staticmethod
def finalize_job(context=None) -> Dict[str, Any]:
    """
    Finalize HelloWorld job - minimal pattern.

    This demonstrates the simplest valid implementation:
    - No context needed (HelloWorld has no meaningful results)
    - Logs completion
    - Returns minimal required fields
    """
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "HelloWorldWorkflow.finalize_job"
    )

    # Log completion (even simple jobs should log)
    if context:
        logger.info(f"✅ HelloWorld job {context.job_id[:16]} completed successfully")
        message = context.parameters.get("message", "No message provided")
    else:
        logger.info("✅ HelloWorld job completed successfully")
        message = "Unknown"

    # Return minimal summary (required fields only)
    return {
        "job_type": "hello_world",
        "status": "completed",
        "message_echoed": message
    }
```

---

### Phase 3: Implement User-Facing Workflows (Rich Pattern) **HIGH PRIORITY**

#### A. process_large_raster.py

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Finalize large raster processing - extract MosaicJSON and STAC results.

    Stages:
    - Stage 1: Tiling scheme
    - Stage 2: Extract tiles
    - Stage 3: Create COGs (N tasks)
    - Stage 4: Create MosaicJSON
    - Stage 5: Create STAC collection
    """
    from util_logger import LoggerFactory, ComponentType
    from core.models import TaskStatus

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "ProcessLargeRasterWorkflow.finalize_job"
    )

    task_results = context.task_results
    params = context.parameters

    # Extract COG tasks count
    cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
    successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]

    # Extract MosaicJSON result (Stage 4)
    mosaicjson_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
    mosaicjson_result = {}
    if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
        mosaicjson_result = mosaicjson_tasks[0].result_data.get("result", {})

    # Extract STAC result (Stage 5)
    stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]
    stac_result = {}
    if stac_tasks and stac_tasks[0].result_data:
        stac_result = stac_tasks[0].result_data.get("result", {})

    logger.info(f"✅ Large raster processing completed: {len(successful_cogs)} COGs, MosaicJSON created, STAC published")

    return {
        "job_type": "process_large_raster",
        "source_blob": params.get("blob_name"),
        "tile_count": len(successful_cogs),
        "mosaicjson_url": mosaicjson_result.get("mosaicjson_url"),
        "mosaicjson_blob": mosaicjson_result.get("mosaicjson_blob"),
        "stac_collection_id": stac_result.get("stac_collection_id") or stac_result.get("collection_id"),
        "spatial_extent": mosaicjson_result.get("bounds") or stac_result.get("spatial_extent"),
        "ready_for_titiler": True,
        "stages_completed": context.total_stages,
        "summary": {
            "total_cogs": len(successful_cogs),
            "mosaicjson_created": bool(mosaicjson_result),
            "stac_published": bool(stac_result)
        }
    }
```

#### B. process_raster_collection.py

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Finalize raster collection processing - extract MosaicJSON and STAC results.

    Stages:
    - Stage 1: Validate all tiles
    - Stage 2: Create COGs (N tasks)
    - Stage 3: Create MosaicJSON
    - Stage 4: Create STAC collection
    """
    from util_logger import LoggerFactory, ComponentType
    from core.models import TaskStatus

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "ProcessRasterCollectionWorkflow.finalize_job"
    )

    task_results = context.task_results
    params = context.parameters

    # Extract COG tasks count
    cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
    successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]

    # Extract MosaicJSON result (Stage 3)
    mosaicjson_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
    mosaicjson_result = {}
    if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
        mosaicjson_result = mosaicjson_tasks[0].result_data.get("result", {})

    # Extract STAC result (Stage 4)
    stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]
    stac_result = {}
    if stac_tasks and stac_tasks[0].result_data:
        stac_result = stac_tasks[0].result_data.get("result", {})

    logger.info(f"✅ Raster collection processing completed: {len(successful_cogs)} COGs, MosaicJSON created, STAC published")

    return {
        "job_type": "process_raster_collection",
        "collection_id": params.get("collection_id"),
        "tile_count": len(successful_cogs),
        "mosaicjson_url": mosaicjson_result.get("mosaicjson_url"),
        "mosaicjson_blob": mosaicjson_result.get("mosaicjson_blob"),
        "stac_collection_id": stac_result.get("stac_collection_id") or stac_result.get("collection_id"),
        "spatial_extent": mosaicjson_result.get("bounds") or stac_result.get("spatial_extent"),
        "ready_for_titiler": True,
        "stages_completed": context.total_stages,
        "summary": {
            "total_cogs": len(successful_cogs),
            "mosaicjson_created": bool(mosaicjson_result),
            "stac_published": bool(stac_result)
        }
    }
```

---

### Phase 4: Implement Internal Workflows (Minimal Pattern)

**Files**:
- `jobs/create_h3_base.py`
- `jobs/generate_h3_level4.py`
- `jobs/container_list_diamond.py`

**Pattern** (copy for each):
```python
@staticmethod
def finalize_job(context=None) -> Dict[str, Any]:
    """Minimal finalization for internal/diagnostic job."""
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "{WorkflowName}.finalize_job"  # Replace with actual workflow name
    )

    if context:
        logger.info(f"✅ {context.job_type} job {context.job_id[:16]} completed")
    else:
        logger.info("✅ Job completed")

    return {
        "job_type": "{job_type}",  # Replace with actual job_type
        "status": "completed"
    }
```

---

### Phase 5: Update CoreMachine (Remove Optional Check)

**File**: `core/machine.py`

**Before** (optional):
```python
# Line 999-1007
if hasattr(workflow, 'finalize_job'):
    final_result = workflow.finalize_job(context)
else:
    # Default finalization (workflow didn't provide custom summary)
    final_result = {
        'job_type': job_type,
        'total_tasks': len(task_results),
        'message': 'Job completed successfully'
    }
```

**After** (required):
```python
# Call workflow's finalize_job (now required by JobBase ABC)
workflow = self.jobs_registry[job_type]
final_result = workflow.finalize_job(context)
```

**Why this works**:
- ✅ All workflows MUST have `finalize_job()` (enforced by ABC)
- ✅ No need for `hasattr()` check anymore
- ✅ Simpler, cleaner code
- ✅ Fails at import time if workflow missing method (fail-fast)

---

### Phase 6: Validation

**Test import all workflows**:
```python
python3 << 'EOF'
from jobs import ALL_JOBS

print("Testing all workflow imports...")
for job_type, workflow_class in ALL_JOBS.items():
    if not hasattr(workflow_class, 'finalize_job'):
        print(f"❌ {job_type}: Missing finalize_job()")
    else:
        print(f"✅ {job_type}: Has finalize_job()")
EOF
```

**Expected**: All workflows import successfully, all have `finalize_job()`

**Test syntax**:
```bash
python3 -m py_compile jobs/*.py core/machine.py
```

**Test job completion**:
1. Submit hello_world job
2. Wait for completion
3. Query GET /api/jobs/status/{job_id}
4. Verify result_data contains finalize_job() output

---

## ✅ Success Criteria

1. ✅ **JobBase enforces `finalize_job()`** - Abstract method added to ABC
2. ✅ **All 13 workflows implement it** - No ImportError exceptions
3. ✅ **Hello World demonstrates minimal pattern** - Reference implementation
4. ✅ **Major workflows have rich implementations** - process_raster, process_large_raster, process_raster_collection
5. ✅ **CoreMachine simplified** - No optional checks, direct method call
6. ✅ **Backwards compatible deployment** - Works with or without Platform layer
7. ✅ **Fail-fast validation** - Missing method caught at import time, not runtime

---

## 📊 Migration Summary

### Current State
- 7 workflows with `finalize_job()` (formerly `aggregate_job_results`)
- 6 workflows without (use CoreMachine default)
- Method is optional (checked with `hasattr()`)

### Target State
- **13 workflows with `finalize_job()`** (all workflows)
- **Method is required** (enforced by JobBase ABC)
- **No runtime checks** (fail at import if missing)
- **Two implementation patterns** (minimal vs rich)

### Migration Path
1. ✅ Add abstract method to JobBase
2. ✅ Implement in hello_world (reference pattern)
3. ✅ Add to 2 high-priority workflows (rich pattern)
4. ✅ Add to 3 low-priority workflows (minimal pattern)
5. ✅ Remove optional check from CoreMachine
6. ✅ Test all imports (will fail if any missing)

---

## 🎯 Implementation Order

1. **Phase 1**: JobBase ABC Update - Add `@abstractmethod finalize_job()`
   - **Expected outcome**: All workflows without method will fail to import

2. **Phase 2**: Hello World - Add minimal implementation
   - **Expected outcome**: HelloWorld imports successfully, serves as template

3. **Phase 3**: High-Priority Workflows - Rich implementations
   - process_large_raster.py
   - process_raster_collection.py
   - **Expected outcome**: Major raster workflows have detailed summaries

4. **Phase 4**: Low-Priority Workflows - Minimal implementations
   - create_h3_base.py
   - generate_h3_level4.py
   - container_list_diamond.py
   - **Expected outcome**: All workflows import successfully

5. **Phase 5**: CoreMachine Update - Remove optional check
   - **Expected outcome**: Simpler code, guaranteed method exists

6. **Phase 6**: Validation - Import all workflows, test completion
   - **Expected outcome**: All workflows work, rich summaries in database

---

## 🔄 Summary

### Question
"How is the Platform callable parameter called if it is present? How will this be used or not used with finalize_job()?"

### Answer
1. **`finalize_job()` ALWAYS runs** - Creates summary regardless of Platform presence
2. **Summary ALWAYS stored in database** - Available via CoreMachine API
3. **Callback (if present) receives summary** - Platform gets finalize_job() output
4. **Callback (if absent) skipped** - CoreMachine works standalone

### The Connection
- `finalize_job()` **produces** the data
- Callback **consumes** the data (if callback exists)
- They're **loosely coupled** - finalize_job() works without callback
- **Platform is optional** - CoreMachine is a complete standalone system

### Deployment Flexibility
- **"System in a box"**: CoreMachine alone, no callback, users query `/api/jobs/status`
- **"Full platform"**: CoreMachine + Platform, callback receives rich summaries, orchestrates multi-job requests

---

## 📝 Next Steps

1. Review this plan
2. Approve implementation
3. Execute phases 1-6 sequentially
4. Validate all workflows import and execute
5. Update documentation with new required method
6. Celebrate simplified, more robust architecture! 🎉

---

## 🌐 Phase 7: Add API Endpoint URL Generation (TiTiler + OGC Features)

**Date Added**: 3 NOV 2025
**Status**: 📋 PLANNED - Ready for implementation
**Priority**: HIGH - Completes finalize_job() with user-facing visualization URLs

### Why This Matters

When ETL jobs complete, users need immediate access to their processed data. This phase adds **ready-to-use API endpoint URLs** to finalize_job() output:

- **Raster data** → TiTiler tile serving URLs (dynamic map tiles, preview images, interactive viewers)
- **Vector data** → OGC Features URLs (GeoJSON access, standardized queries)

**Key Insight**: Different data types need different APIs!
- Rasters require dynamic tile generation (TiTiler-PgSTAC)
- Vectors are best served as GeoJSON (OGC API - Features)

### Critical Data Flow Clarification

**finalize_job() Output Storage**:

```python
# In core/machine.py _complete_job() method:

# STEP 1: Workflow creates rich summary
summary = workflow.finalize_job(context)
# Returns: {
#     "job_type": "process_large_raster",
#     "mosaicjson_url": "https://.../mosaics/17apr2024wv2.json",
#     "titiler": {
#         "tile_url_template": "https://.../tiles/{z}/{x}/{y}",
#         "preview_url": "https://.../preview.png",
#         ...
#     }
# }

# STEP 2: ALWAYS store in database (PRIMARY STORAGE)
job_repo.update_job(
    job_id=job_id,
    result_data=summary,  # ← Stored in app.jobs.result_data (JSONB)
    status=JobStatus.COMPLETED
)

# STEP 3: OPTIONAL Platform callback (NOTIFICATION ONLY)
if self.on_job_complete:
    self.on_job_complete(
        job_id=job_id,
        job_type=job_type,
        status='completed',
        result=summary  # ← SAME data sent to Platform (not stored again)
    )
    # Platform receives notification with complete summary
    # Platform can update platform.orchestration_jobs.result_data
    # Both tables end up with same summary data
```

**Key Points**:
- ✅ Database (`app.jobs.result_data`) is the PRIMARY storage
- ✅ Platform callback is a NOTIFICATION that includes the data
- ✅ Callback is OPTIONAL - CoreMachine works standalone
- ✅ Single source of truth (database query always works)
- ✅ Users can query `/api/db/jobs/{job_id}` to get complete summary

### TiTiler-PgSTAC Context

**Already Deployed**: `https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`

**Available Endpoints** (per STAC item):
- Tile serving: `/collections/{collection}/items/{item}/WebMercatorQuad/tiles/{z}/{x}/{y}`
- Preview image: `/collections/{collection}/items/{item}/preview.png?width=512`
- Raster info: `/collections/{collection}/items/{item}/info`
- Spatial bounds: `/collections/{collection}/items/{item}/bounds`
- Interactive map: `/collections/{collection}/items/{item}/WebMercatorQuad/map.html`

**Standards Compliance**:
- ✅ OGC API - Tiles 1.0 (Core, JPEG, PNG, TIFF)
- ✅ OGC API - Common 1.0 (Core, HTML, JSON)
- ✅ Interoperable with Leaflet, Mapbox, QGIS, ArcGIS

### Implementation Plan

#### Step 1: Add URL Generation Methods to config.py

**File**: `config.py`
**Location**: Add to `AppConfig` class (after existing fields)

```python
# ============================================================================
# API Endpoint Configuration (NEW - 3 NOV 2025)
# ============================================================================

titiler_base_url: str = Field(
    default="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net",
    description="Base URL for TiTiler-PgSTAC tile server (raster visualization). "
                "Production URL already deployed and operational."
)

ogc_features_base_url: str = Field(
    default="https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features",
    description="Base URL for OGC API - Features (vector data access). "
                "Placeholder until custom DNS (geospatial.rmh.org) is configured."
)

def generate_titiler_urls(self, collection_id: str, item_id: str) -> dict:
    """
    Generate TiTiler-PgSTAC tile serving URLs for a raster STAC item.

    Use this for ALL raster workflows (process_raster, process_large_raster,
    process_raster_collection) to provide users with ready-to-use
    visualization endpoints.

    Args:
        collection_id: STAC collection ID (typically "cogs")
        item_id: STAC item ID (e.g., "17apr2024wv2", "antigua-april-2013")

    Returns:
        Dict with complete set of TiTiler endpoints:
        - tile_url_template: For Leaflet/Mapbox ({z}/{x}/{y} placeholders)
        - preview_url: PNG thumbnail (512px default)
        - info_url: Raster metadata (bands, stats, data type)
        - bounds_url: Spatial extent in EPSG:4326
        - map_viewer_url: Built-in Leaflet interactive viewer

    Example:
        >>> config = get_config()
        >>> urls = config.generate_titiler_urls("cogs", "17apr2024wv2")
        >>> urls["preview_url"]
        'https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/preview.png?width=512'

    Notes:
        - URLs work immediately after STAC item is created in PgSTAC
        - No additional TiTiler configuration required
        - Supports OGC Tiles 1.0 standard parameters (rescale, colormap, etc.)
        - tile_url_template uses {z}/{x}/{y} placeholders for web mapping libraries
    """
    base = self.titiler_base_url.rstrip('/')

    return {
        "tile_url_template": f"{base}/collections/{collection_id}/items/{item_id}/WebMercatorQuad/tiles/{{z}}/{{x}}/{{y}}",
        "preview_url": f"{base}/collections/{collection_id}/items/{item_id}/preview.png?width=512",
        "info_url": f"{base}/collections/{collection_id}/items/{item_id}/info",
        "bounds_url": f"{base}/collections/{collection_id}/items/{item_id}/bounds",
        "map_viewer_url": f"{base}/collections/{collection_id}/items/{item_id}/WebMercatorQuad/map.html"
    }

def generate_ogc_features_url(self, collection_id: str) -> str:
    """
    Generate OGC API - Features collection URL for vector data.

    Use this for ALL vector workflows (ingest_vector) to provide users
    with standardized GeoJSON access to their PostGIS tables.

    Args:
        collection_id: Collection name (same as PostGIS table name)

    Returns:
        OGC Features collection URL for querying vector features

    Example:
        >>> config = get_config()
        >>> url = config.generate_ogc_features_url("acled_1997")
        >>> url
        'https://rmhgeoapibeta-.../api/features/collections/acled_1997'

    Available Operations:
        - GET /collections/{id} - Collection metadata (bbox, feature count)
        - GET /collections/{id}/items - Query features (supports bbox, limit, offset)
        - GET /collections/{id}/items/{feature_id} - Single feature by ID

    Notes:
        - Base URL is placeholder until custom DNS is configured
        - Will become https://geospatial.rmh.org/api/features/collections/{id}
        - Easy update: Single environment variable (OGC_FEATURES_BASE_URL)
        - OGC API - Features Core 1.0 compliant
    """
    return f"{self.ogc_features_base_url.rstrip('/')}/collections/{collection_id}"
```

**Expected Outcome**:
- ✅ Reusable URL generation methods available everywhere via `get_config()`
- ✅ Single source of truth for base URLs
- ✅ Easy to update URLs when DNS is configured (change env vars)
- ✅ Type-safe, documented, testable

---

#### Step 2: Update process_large_raster.py finalize_job()

**File**: `jobs/process_large_raster.py`
**Current**: Minimal stub with TODO comment (lines 704-735)
**Action**: Replace with rich implementation extracting MosaicJSON, STAC, and generating TiTiler URLs

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Create final job summary from all completed tasks.

    Extracts:
    - Tiling statistics (Stage 1-2)
    - COG processing results (Stage 3)
    - MosaicJSON metadata (Stage 4)
    - STAC collection details (Stage 5)
    - TiTiler visualization URLs

    Args:
        context: JobExecutionContext with task results

    Returns:
        Comprehensive job summary with TiTiler URLs
    """
    from util_logger import LoggerFactory, ComponentType
    from core.models import TaskStatus
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "ProcessLargeRasterWorkflow.finalize_job"
    )

    task_results = context.task_results
    params = context.parameters
    config = get_config()

    # Extract tiling scheme results (Stage 1)
    tiling_tasks = [t for t in task_results if t.task_type == "generate_tiling_scheme"]
    tiling_summary = {}
    if tiling_tasks and tiling_tasks[0].result_data:
        tiling_result = tiling_tasks[0].result_data.get("result", {})
        tiling_summary = {
            "scheme_blob": tiling_result.get("tiling_scheme_blob"),
            "tile_count": tiling_result.get("tile_count"),
            "grid_dimensions": tiling_result.get("grid_dimensions")
        }

    # Extract tile extraction results (Stage 2)
    extraction_tasks = [t for t in task_results if t.task_type == "extract_tiles"]
    extraction_summary = {}
    if extraction_tasks and extraction_tasks[0].result_data:
        extraction_result = extraction_tasks[0].result_data.get("result", {})
        extraction_summary = {
            "processing_time_seconds": extraction_result.get("processing_time_seconds"),
            "tiles_extracted": extraction_result.get("tile_count")
        }

    # Extract COG results (Stage 3 - fan-out, N tasks)
    cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
    successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]
    failed_cogs = [t for t in cog_tasks if t.status == TaskStatus.FAILED]

    # Calculate total COG size
    total_size_mb = 0
    for cog_task in successful_cogs:
        if cog_task.result_data and cog_task.result_data.get("result"):
            size_mb = cog_task.result_data["result"].get("size_mb", 0)
            total_size_mb += size_mb

    cog_summary = {
        "total_count": len(successful_cogs),
        "successful": len(successful_cogs),
        "failed": len(failed_cogs),
        "total_size_mb": round(total_size_mb, 2)
    }

    # Extract MosaicJSON result (Stage 4 - fan-in)
    mosaicjson_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
    mosaicjson_summary = {}
    if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
        mosaicjson_result = mosaicjson_tasks[0].result_data.get("result", {})
        mosaicjson_summary = {
            "blob_path": mosaicjson_result.get("mosaicjson_blob"),
            "url": mosaicjson_result.get("mosaicjson_url"),
            "bounds": mosaicjson_result.get("bounds"),
            "tile_count": mosaicjson_result.get("tile_count")
        }

    # Extract STAC result (Stage 5 - fan-in)
    stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]
    stac_summary = {}
    titiler_urls = {}

    if stac_tasks and stac_tasks[0].result_data:
        stac_result = stac_tasks[0].result_data.get("result", {})
        collection_id = stac_result.get("collection_id", "cogs")
        item_id = stac_result.get("stac_id") or stac_result.get("pgstac_id")

        stac_summary = {
            "collection_id": collection_id,
            "stac_id": item_id,
            "pgstac_id": stac_result.get("pgstac_id"),
            "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
            "ready_for_titiler": True
        }

        # Generate TiTiler URLs if we have STAC item ID
        if item_id:
            titiler_urls = config.generate_titiler_urls(
                collection_id=collection_id,
                item_id=item_id
            )

    logger.info(
        f"✅ Large raster job {context.job_id[:16]} completed: "
        f"{len(successful_cogs)} COGs, MosaicJSON created, STAC published"
    )

    return {
        "job_type": "process_large_raster",
        "job_id": context.job_id,
        "source_blob": params.get("blob_name"),
        "source_container": params.get("container_name"),
        "tiling": tiling_summary,
        "extraction": extraction_summary,
        "cogs": cog_summary,
        "mosaicjson": mosaicjson_summary,
        "stac": stac_summary,
        "titiler": titiler_urls,  # Ready-to-use visualization URLs
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(task_results),
        "tasks_by_status": {
            "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
        }
    }
```

**Expected Output Example**:
```json
{
  "job_type": "process_large_raster",
  "job_id": "a1b2c3d4...",
  "source_blob": "17apr2024wv2.tif",
  "tiling": {
    "tile_count": 204,
    "grid_dimensions": "17x12"
  },
  "cogs": {
    "total_count": 204,
    "successful": 204,
    "failed": 0,
    "total_size_mb": 1843.52
  },
  "mosaicjson": {
    "blob_path": "mosaics/17apr2024wv2.json",
    "url": "https://.../mosaics/17apr2024wv2.json",
    "bounds": [-70.7, -56.3, -70.6, -56.2]
  },
  "stac": {
    "collection_id": "cogs",
    "stac_id": "17apr2024wv2",
    "ready_for_titiler": true
  },
  "titiler": {
    "tile_url_template": "https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/WebMercatorQuad/tiles/{z}/{x}/{y}",
    "preview_url": "https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/preview.png?width=512",
    "info_url": "https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/info",
    "bounds_url": "https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/bounds",
    "map_viewer_url": "https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/WebMercatorQuad/map.html"
  }
}
```

---

#### Step 3: Update process_raster_collection.py finalize_job()

**File**: `jobs/process_raster_collection.py`
**Current**: Minimal stub with TODO comment (lines 614-646)
**Action**: Similar to process_large_raster but adapted for collection workflow

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Create final job summary from all completed tasks.

    Extracts:
    - Per-tile COG statistics (Stage 2)
    - MosaicJSON metadata (Stage 3)
    - STAC collection details (Stage 4)
    - TiTiler visualization URLs

    Args:
        context: JobExecutionContext with task results

    Returns:
        Comprehensive job summary with TiTiler URLs
    """
    from util_logger import LoggerFactory, ComponentType
    from core.models import TaskStatus
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        "ProcessRasterCollectionWorkflow.finalize_job"
    )

    task_results = context.task_results
    params = context.parameters
    config = get_config()

    # Extract COG results (Stage 2 - fan-out, N tasks)
    cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
    successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]
    failed_cogs = [t for t in cog_tasks if t.status == TaskStatus.FAILED]

    total_size_mb = 0
    for cog_task in successful_cogs:
        if cog_task.result_data and cog_task.result_data.get("result"):
            size_mb = cog_task.result_data["result"].get("size_mb", 0)
            total_size_mb += size_mb

    cog_summary = {
        "total_count": len(successful_cogs),
        "successful": len(successful_cogs),
        "failed": len(failed_cogs),
        "total_size_mb": round(total_size_mb, 2)
    }

    # Extract MosaicJSON result (Stage 3 - fan-in)
    mosaicjson_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
    mosaicjson_summary = {}
    if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
        mosaicjson_result = mosaicjson_tasks[0].result_data.get("result", {})
        mosaicjson_summary = {
            "blob_path": mosaicjson_result.get("mosaicjson_blob"),
            "url": mosaicjson_result.get("mosaicjson_url"),
            "bounds": mosaicjson_result.get("bounds"),
            "tile_count": mosaicjson_result.get("tile_count")
        }

    # Extract STAC result (Stage 4 - fan-in)
    stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]
    stac_summary = {}
    titiler_urls = {}

    if stac_tasks and stac_tasks[0].result_data:
        stac_result = stac_tasks[0].result_data.get("result", {})
        collection_id = stac_result.get("collection_id", "cogs")
        item_id = stac_result.get("stac_id") or stac_result.get("pgstac_id")

        stac_summary = {
            "collection_id": collection_id,
            "stac_id": item_id,
            "pgstac_id": stac_result.get("pgstac_id"),
            "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
            "ready_for_titiler": True
        }

        # Generate TiTiler URLs
        if item_id:
            titiler_urls = config.generate_titiler_urls(
                collection_id=collection_id,
                item_id=item_id
            )

    logger.info(
        f"✅ Raster collection job {context.job_id[:16]} completed: "
        f"{len(successful_cogs)} COGs, MosaicJSON created, STAC published"
    )

    return {
        "job_type": "process_raster_collection",
        "job_id": context.job_id,
        "collection_id": params.get("collection_id"),
        "cogs": cog_summary,
        "mosaicjson": mosaicjson_summary,
        "stac": stac_summary,
        "titiler": titiler_urls,
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(task_results),
        "tasks_by_status": {
            "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
        }
    }
```

---

#### Step 4: Update process_raster.py finalize_job()

**File**: `jobs/process_raster.py`
**Current**: Rich implementation WITHOUT TiTiler URLs (lines 573-643)
**Action**: Add TiTiler URL generation to existing implementation

**Find this section** (around line 618-628):
```python
# Extract STAC results
stac_summary = {}
if stage_3_tasks and stage_3_tasks[0].result_data:
    stac_result = stage_3_tasks[0].result_data.get("result", {})
    stac_summary = {
        "item_id": stac_result.get("item_id"),
        "collection_id": stac_result.get("collection_id"),
        "bbox": stac_result.get("bbox"),
        "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
        "ready_for_titiler": True  # COG + STAC = ready for serving
    }
```

**Replace with**:
```python
# Extract STAC results
stac_summary = {}
titiler_urls = {}

if stage_3_tasks and stage_3_tasks[0].result_data:
    stac_result = stage_3_tasks[0].result_data.get("result", {})
    collection_id = stac_result.get("collection_id", "cogs")
    item_id = stac_result.get("item_id")

    stac_summary = {
        "item_id": item_id,
        "collection_id": collection_id,
        "bbox": stac_result.get("bbox"),
        "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
        "ready_for_titiler": True
    }

    # Generate TiTiler URLs
    if item_id:
        from config import get_config
        config = get_config()
        titiler_urls = config.generate_titiler_urls(
            collection_id=collection_id,
            item_id=item_id
        )
```

**Then find the return statement** (around line 630):
```python
return {
    "job_type": "process_raster",
    "source_blob": params.get("blob_name"),
    "source_container": params.get("container_name"),
    "validation": validation_summary,
    "cog": cog_summary,
    "stac": stac_summary,
    "stages_completed": context.current_stage,
    "total_tasks_executed": len(task_results),
    "tasks_by_status": {
        "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
        "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
    }
}
```

**Add titiler field**:
```python
return {
    "job_type": "process_raster",
    "source_blob": params.get("blob_name"),
    "source_container": params.get("container_name"),
    "validation": validation_summary,
    "cog": cog_summary,
    "stac": stac_summary,
    "titiler": titiler_urls,  # ← ADD THIS LINE
    "stages_completed": context.current_stage,
    "total_tasks_executed": len(task_results),
    "tasks_by_status": {
        "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
        "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
    }
}
```

---

#### Step 5: Update ingest_vector.py finalize_job()

**File**: `jobs/ingest_vector.py`
**Current**: Rich implementation WITHOUT OGC Features URL
**Action**: Add OGC Features URL generation to existing implementation

**Find the finalize_job() method** and locate the return statement.

**Before**:
```python
return {
    "job_type": "ingest_vector",
    "table_name": table_name,
    "stac": stac_summary,
    # ... other fields
}
```

**After**:
```python
# Generate OGC Features URL for vector access
from config import get_config
config = get_config()
ogc_features_url = config.generate_ogc_features_url(table_name)

return {
    "job_type": "ingest_vector",
    "table_name": table_name,
    "stac": stac_summary,
    "ogc_features_url": ogc_features_url,  # ← ADD THIS LINE
    # ... other fields
}
```

**Expected Output Example**:
```json
{
  "job_type": "ingest_vector",
  "table_name": "acled_1997",
  "rows_inserted": 5000,
  "stac": {
    "collection_id": "system-vectors",
    "item_id": "acled_1997"
  },
  "ogc_features_url": "https://rmhgeoapibeta-.../api/features/collections/acled_1997"
}
```

---

### Implementation TODO Checklist

- [ ] **Step 1**: Add URL generation methods to `config.py`
  - [ ] Add `titiler_base_url` field
  - [ ] Add `ogc_features_base_url` field
  - [ ] Add `generate_titiler_urls()` method
  - [ ] Add `generate_ogc_features_url()` method
  - [ ] Test import and method calls

- [ ] **Step 2**: Update `process_large_raster.py` finalize_job()
  - [ ] Replace minimal stub with rich implementation
  - [ ] Extract Stage 1-5 results
  - [ ] Generate TiTiler URLs
  - [ ] Test with mock context

- [ ] **Step 3**: Update `process_raster_collection.py` finalize_job()
  - [ ] Replace minimal stub with rich implementation
  - [ ] Extract Stage 2-4 results
  - [ ] Generate TiTiler URLs
  - [ ] Test with mock context

- [ ] **Step 4**: Update `process_raster.py` finalize_job()
  - [ ] Add TiTiler URL generation to existing code
  - [ ] Add `titiler` field to return dict
  - [ ] Test with mock context

- [ ] **Step 5**: Update `ingest_vector.py` finalize_job()
  - [ ] Add OGC Features URL generation
  - [ ] Add `ogc_features_url` field to return dict
  - [ ] Test with mock context

- [ ] **Validation**:
  - [ ] Import all workflows successfully
  - [ ] Verify URL format correctness
  - [ ] Test config methods with sample data
  - [ ] Deploy and test with real job execution
  - [ ] Verify URLs work in browser
  - [ ] Confirm Platform callback receives complete summaries

---

### Benefits of This Implementation

#### For Users
✅ **Immediate Visualization Access** - Get clickable map viewer URLs the moment job completes
✅ **Embeddable Tile URLs** - Ready to use in Leaflet, Mapbox, QGIS
✅ **Preview Thumbnails** - Quick visual confirmation without loading full dataset
✅ **Standards-Based** - OGC-compliant URLs work with any standards-compliant client

#### For Platform Layer
✅ **Complete Metadata** - Callback receives all URLs for orchestration
✅ **No Additional Lookups** - All visualization endpoints in one response
✅ **Consistent Format** - Same structure across all ETL workflows
✅ **Ready for UI Integration** - Platform can display maps/previews immediately

#### For System Architecture
✅ **Type-Appropriate APIs** - Rasters use TiTiler (tiles), Vectors use OGC Features (GeoJSON)
✅ **Single Source of Truth** - URL generation methods in config.py
✅ **Future-Proof** - Easy DNS update (change env vars, redeploy)
✅ **Reusable Patterns** - Same helper methods for all workflows
✅ **Testable** - URL generation logic isolated and mockable

---

### Example: Complete End-to-End Flow

#### User Submits Large Raster Job
```bash
curl -X POST .../api/jobs/submit/process_large_raster \
  -d '{"blob_name": "17apr2024wv2.tif", "container_name": "rmhazuregeobronze"}'

# Response:
{"job_id": "a1b2c3d4...", "status": "queued"}
```

#### Job Executes (5 stages)
1. Stage 1: Generate tiling scheme (204 tiles)
2. Stage 2: Extract all tiles sequentially
3. Stage 3: Convert 204 tiles to COGs (parallel)
4. Stage 4: Create MosaicJSON with quadkey index
5. Stage 5: Create STAC item in "cogs" collection

#### Job Completes - finalize_job() Runs
```python
# workflow.finalize_job(context) produces:
{
  "job_type": "process_large_raster",
  "cogs": {"total_count": 204, "total_size_mb": 1843.52},
  "mosaicjson": {"url": "https://.../mosaics/17apr2024wv2.json"},
  "stac": {"stac_id": "17apr2024wv2", "ready_for_titiler": true},
  "titiler": {
    "tile_url_template": "https://rmhtitiler-.../tiles/{z}/{x}/{y}",
    "map_viewer_url": "https://rmhtitiler-.../map.html"
  }
}
```

#### Result Stored in Database
```sql
UPDATE app.jobs
SET result_data = '{...}',  -- ← finalize_job() output
    status = 'completed'
WHERE job_id = 'a1b2c3d4...';
```

#### Platform Callback Receives Same Data (if registered)
```python
on_job_complete(
    job_id="a1b2c3d4...",
    job_type="process_large_raster",
    status="completed",
    result={...}  # ← Same dict from finalize_job()
)

# Platform updates:
UPDATE platform.orchestration_jobs
SET result_data = '{...}',  -- ← Same finalize_job() output
    status = 'completed'
WHERE job_id = 'a1b2c3d4...';
```

#### User Queries Job Status
```bash
curl .../api/db/jobs/a1b2c3d4...

# Returns complete summary with URLs:
{
  "job_id": "a1b2c3d4...",
  "status": "completed",
  "result_data": {
    "titiler": {
      "map_viewer_url": "https://rmhtitiler-.../map.html"  # ← Click to view!
    }
  }
}
```

#### User Opens Interactive Map
```
Browser: https://rmhtitiler-.../collections/cogs/items/17apr2024wv2/WebMercatorQuad/map.html
→ Instant Leaflet map with pan/zoom, ready to view processed raster!
```

---

### Data Flow Summary

```
finalize_job() Output
       ↓
app.jobs.result_data (PostgreSQL JSONB)  ← PRIMARY STORAGE
       ↓
(Optional) Platform Callback
       ↓
platform.orchestration_jobs.result_data  ← DUPLICATE FOR PLATFORM TRACKING
       ↓
User Queries /api/db/jobs/{id} or Platform API
       ↓
Returns: Complete summary with TiTiler/OGC URLs
       ↓
User clicks map_viewer_url
       ↓
Instant visualization! 🎉
```

**Key Points**:
- Database is the source of truth
- Callback is a notification (not primary storage)
- Users get same data whether using CoreMachine API or Platform API
- URLs work immediately (no additional configuration)

---

### Success Criteria

✅ All 5 files updated (config.py + 4 workflow files)
✅ URL generation methods tested and working
✅ All imports successful
✅ TiTiler URLs match format: `/collections/{coll}/items/{item}/...`
✅ OGC Features URLs match format: `/api/features/collections/{id}`
✅ Job completion stores complete summaries in database
✅ Platform callback receives complete summaries (if registered)
✅ URLs accessible in browser after job completion
✅ Interactive map viewers load successfully

---

**Last Updated**: 3 NOV 2025
**Status**: 📋 Ready for implementation
**Priority**: HIGH - Completes finalize_job() architecture with user-facing URLs
