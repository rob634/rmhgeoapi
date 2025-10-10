# Raster ETL Core Machine Compliance Issues

**Date**: 9 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Executive Summary

The raster ETL implementation has **critical compliance issues** that prevent it from working with `core/machine.py`:

1. **ProcessRasterWorkflow** is missing required methods
2. **ProcessRasterWorkflow** uses old method signatures (create_stage_X_tasks instead of create_tasks_for_stage)
3. **Parameter naming** inconsistent: uses `container` instead of `container_name`
4. **ValidateRasterJob** is compliant but has one validation check mismatch (already fixed)

---

## Core Machine Contract (from core/machine.py)

### Required Job Class Methods

#### 1. create_tasks_for_stage() - **CRITICAL**
```python
@staticmethod
def create_tasks_for_stage(
    stage: int,
    job_params: dict,
    job_id: str,
    previous_results: list = None
) -> list[dict]:
    """
    Called by CoreMachine line 248.

    Args:
        stage: Stage number (1-based)
        job_params: Job parameters from database
        job_id: Job ID for generating deterministic task IDs
        previous_results: Results from previous stage (for fan-out)

    Returns:
        List of task dicts with keys: task_id, task_type, parameters
    """
```

**Used by**: `core/machine.py:248`

#### 2. aggregate_job_results() - Optional
```python
@staticmethod
def aggregate_job_results(context: JobExecutionContext) -> dict:
    """
    Called by CoreMachine line 906 (optional - has default fallback).

    Args:
        context: JobExecutionContext with task_results

    Returns:
        Final job result dict
    """
```

**Used by**: `core/machine.py:906`

### Required Job Class Attributes

```python
stages: List[Dict[str, Any]]  # Used at core/machine.py:814
```

### Optional Job Class Methods (for HTTP trigger)

These are called by `triggers/submit_job.py`, not by CoreMachine:

```python
generate_job_id(params: dict) -> str
create_job_record(job_id: str, params: dict) -> dict
queue_job(job_id: str, params: dict) -> dict
validate_job_parameters(params: dict) -> dict
```

### Required Handler Signature

```python
def handler_name(parameters: dict) -> dict | TaskResult:
    """
    Args:
        parameters: task_message.parameters (dict)

    Returns:
        dict with 'success' bool key OR TaskResult object
        If dict with success=False, should have 'error' str key
    """
```

**Called at**: `core/machine.py:397` - `raw_result = handler(task_message.parameters)`

---

## Compliance Status

### ✅ ValidateRasterJob (jobs/validate_raster_job.py)

**Status**: **COMPLIANT** (after fix)

**Methods Present**:
- ✅ `create_tasks_for_stage(stage, job_params, job_id, previous_results)` - Line 147
- ✅ `aggregate_job_results(context)` - Line 313
- ✅ `generate_job_id(params)` - Line 206
- ✅ `create_job_record(job_id, params)` - Line 218
- ✅ `queue_job(job_id, params)` - Line 259
- ✅ `validate_job_parameters(params)` - Line 77

**Class Attributes**:
- ✅ `stages: List[Dict[str, Any]]` - Line 52

**Task Creation Signature**: ✅ CORRECT
```python
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None)
```

**Issues Fixed**:
1. ✅ aggregate_job_results now checks `result.get("valid")` instead of `result.get("validation_passed")`

**Remaining Issues**:
1. ⚠️ Uses `"container"` in task parameters (line 194) - should be `"container_name"`

---

### ❌ ProcessRasterWorkflow (jobs/process_raster.py)

**Status**: **NON-COMPLIANT** - Will fail in CoreMachine

**Critical Missing Method**:
- ❌ `create_tasks_for_stage(stage, job_params, job_id, previous_results)` - **MISSING**

**Wrong Method Signatures** (old pattern):
- ❌ `create_stage_1_tasks(context)` - Line 91 (WRONG SIGNATURE)
- ❌ `create_stage_2_tasks(context)` - Line 128 (WRONG SIGNATURE)

**Missing Optional Methods** (needed by HTTP trigger):
- ❌ `generate_job_id(params)` - MISSING
- ❌ `create_job_record(job_id, params)` - MISSING
- ❌ `queue_job(job_id, params)` - MISSING
- ❌ `validate_job_parameters(params)` - MISSING

**Class Attributes**:
- ✅ `stages: List[Dict[str, Any]]` - Line 55 (PRESENT)

**Why This Fails**:

When CoreMachine processes a job message at line 248:
```python
tasks = job_class.create_tasks_for_stage(
    job_message.stage,
    job_record.parameters,
    job_message.job_id,
    previous_results=previous_results
)
```

This will raise **AttributeError** because `ProcessRasterWorkflow` doesn't have `create_tasks_for_stage`.

**Parameter Naming Issues**:
- Line 74: schema uses `"container"` - should be `"container_name"`
- Line 104: uses `params.get('container')` - should be `container_name`
- Line 119: task params use `"container"` - should be `"container_name"`
- Line 155: uses `params.get('container')` - should be `container_name`
- Line 178: task params use `"container"` - should be `"container_name"`

---

### ⚠️ validate_raster Handler (services/raster_validation.py)

**Status**: **MOSTLY COMPLIANT** - needs parameter fix

**Signature**: ✅ CORRECT
```python
def validate_raster(params: dict) -> dict:
```

**Return Structure**: ✅ CORRECT
Returns dict with `"success": bool` key and `"error"` key on failure.

**Parameter Issues**:
1. ⚠️ Accepts both `container_name` and `container` with fallback (line TBD)
   - This is backward compatible but not ideal
   - Should only accept `container_name`

---

### ❓ create_cog Handler (services/raster_cog.py)

**Status**: **NEEDS VERIFICATION** - file not yet reviewed

**Required**:
- Must accept `parameters: dict` argument
- Must return `dict` with `"success": bool` key OR `TaskResult` object
- Should use `container_name` not `container`

---

## Required Fixes

### HIGH PRIORITY - ProcessRasterWorkflow

1. **Add create_tasks_for_stage() method**:
```python
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
    from core.task_id import generate_deterministic_task_id

    if stage == 1:
        # Call existing logic from create_stage_1_tasks
        task_id = generate_deterministic_task_id(job_id, 1, "validate")
        return [{
            "task_id": task_id,
            "task_type": "validate_raster",
            "parameters": { ... }
        }]

    elif stage == 2:
        # Call existing logic from create_stage_2_tasks
        # Use previous_results instead of context.stage_results
        if not previous_results:
            raise ValueError("Stage 2 requires Stage 1 results")

        validation_result = previous_results[0].get('result', {})
        task_id = generate_deterministic_task_id(job_id, 2, "create_cog")
        return [{
            "task_id": task_id,
            "task_type": "create_cog",
            "parameters": { ... }
        }]

    else:
        return []
```

2. **Add trigger support methods** (copy from ValidateRasterJob):
   - `generate_job_id(params)`
   - `create_job_record(job_id, params)`
   - `queue_job(job_id, params)`
   - `validate_job_parameters(params)`

3. **Fix parameter naming**:
   - Replace all `"container"` with `"container_name"`
   - Update `parameters_schema` line 74
   - Update task parameter dicts

4. **Remove old methods** (after migration):
   - `create_stage_1_tasks(context)` - deprecated
   - `create_stage_2_tasks(context)` - deprecated

### MEDIUM PRIORITY - Parameter Standardization

1. **ValidateRasterJob**:
   - Line 194: Change `"container"` to `"container_name"` in task parameters

2. **validate_raster handler**:
   - Remove fallback support for `"container"`
   - Only accept `"container_name"`

3. **create_cog handler**:
   - Verify uses `"container_name"` not `"container"`

---

## Testing Plan

### Phase 1: Validate Local Imports
```bash
python3 -c "from jobs import ALL_JOBS; print(list(ALL_JOBS.keys()))"
```

### Phase 2: Test ValidateRasterJob (Already Working)
```bash
curl -X POST .../api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test/dctest3_R1C2_regular.tif", "container_name": "rmhazuregeobronze", "raster_type": "auto"}'
```

### Phase 3: Test ProcessRasterWorkflow (After Fixes)
```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test/dctest3_R1C2_regular.tif", "container_name": "rmhazuregeobronze", "raster_type": "auto"}'
```

---

## Implementation Priority

1. ❗ **CRITICAL**: Fix ProcessRasterWorkflow - add `create_tasks_for_stage()` method
2. ❗ **CRITICAL**: Add trigger support methods to ProcessRasterWorkflow
3. ⚠️ **HIGH**: Standardize all parameter naming to `container_name`
4. ✅ **MEDIUM**: Test validate_raster handler with standardized parameters
5. ❓ **MEDIUM**: Verify create_cog handler compliance

---

## Success Criteria

- [ ] ProcessRasterWorkflow has `create_tasks_for_stage()` method matching signature
- [ ] ProcessRasterWorkflow has all trigger support methods
- [ ] All parameter references use `container_name` (not `container`)
- [ ] Local imports pass for both job classes
- [ ] ValidateRasterJob job completes successfully (already working)
- [ ] ProcessRasterWorkflow job completes successfully (Stage 1 → Stage 2)
- [ ] Health endpoint shows all handlers registered
- [ ] No AttributeError when CoreMachine calls job_class.create_tasks_for_stage()
