# Raster ETL Core Machine Compliance - COMPLETE ✅

**Date**: 9 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Summary

**ALL raster ETL jobs now comply with core/machine.py contract.**

- ✅ NO old patterns remaining
- ✅ NO fallback logic for deprecated parameters
- ✅ Binary execution path: correct signature OR loud failure
- ✅ All local import tests passing

---

## Changes Made

### ProcessRasterWorkflow (jobs/process_raster.py)

**COMPLETE REWRITE - Old patterns ELIMINATED**

#### ✅ Added Required Methods

1. **`create_tasks_for_stage(stage, job_params, job_id, previous_results)`** - Line 310
   - Replaces old `create_stage_1_tasks(context)` and `create_stage_2_tasks(context)`
   - Uses `if stage == 1:` / `elif stage == 2:` logic
   - Takes raw primitives (int, dict, str, list) - NO context object
   - Uses `previous_results` list instead of `context.stage_results`
   - Generates deterministic task IDs using `job_id`
   - Returns list of task dicts with `task_id`, `task_type`, `parameters`

2. **`generate_job_id(params)`** - Line 203
   - SHA256 hash for idempotency

3. **`create_job_record(job_id, params)`** - Line 215
   - Creates JobRecord and persists to database

4. **`queue_job(job_id, params)`** - Line 256
   - Sends JobQueueMessage to Service Bus

5. **`validate_job_parameters(params)`** - Line 97
   - Validates all job parameters with explicit error messages

#### ❌ Removed Deprecated Methods

- **DELETED**: `create_stage_1_tasks(context)`
- **DELETED**: `create_stage_2_tasks(context)`

**No fallback logic** - attempting to call these methods will raise **AttributeError** immediately.

#### ✅ Parameter Standardization

**ALL instances of `"container"` replaced with `"container_name"`:**
- Line 80: `parameters_schema` uses `container_name`
- Line 340: Stage 1 task uses `container_name`
- Line 359: Stage 1 task params use `container_name`
- Line 387: Stage 2 task uses `container_name`
- Line 414: Stage 2 task params use `container_name`
- Line 478: aggregate_job_results uses `container_name`

**No fallback support** - passing `"container"` will result in **None** value and likely failure.

---

### ValidateRasterJob (jobs/validate_raster_job.py)

#### ✅ Parameter Standardization

**ALL instances of `"container"` replaced with `"container_name"`:**
- Line 66: `parameters_schema` uses `container_name`
- Line 112-117: Validation logic uses `container_name`
- Line 177: create_tasks_for_stage uses `container_name`
- Line 194: Task parameters use `container_name`
- Line 336, 346: aggregate_job_results uses `container_name`

**No fallback support** - passing `"container"` will fail validation with clear error.

---

## Contract Compliance Verification

### CoreMachine Requirements ✅

#### ProcessRasterWorkflow
- ✅ `create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]`
- ✅ `aggregate_job_results(context: JobExecutionContext) -> dict`
- ✅ `stages: List[Dict[str, Any]]` attribute
- ✅ All trigger methods (generate_job_id, create_job_record, queue_job, validate_job_parameters)

#### ValidateRasterJob
- ✅ `create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]`
- ✅ `aggregate_job_results(context: JobExecutionContext) -> dict`
- ✅ `stages: List[Dict[str, Any]]` attribute
- ✅ All trigger methods (generate_job_id, create_job_record, queue_job, validate_job_parameters)

---

## Validation Results

```bash
$ python3 -c "from jobs import ALL_JOBS; ..."

Testing syntax...
✅ process_raster.py syntax valid
✅ validate_raster_job.py syntax valid

Testing imports...
✅ Registered jobs: 8 jobs
✅ Total jobs: 8

Verifying ProcessRasterWorkflow...
✅ ProcessRasterWorkflow has all required methods

Verifying ValidateRasterJob...
✅ ValidateRasterJob has all required methods

✅ ALL COMPLIANCE CHECKS PASSED
```

---

## Migration Notes

### What Changed

**OLD PATTERN** (ProcessRasterWorkflow before):
```python
@staticmethod
def create_stage_1_tasks(context) -> List[Dict[str, Any]]:
    params = context.parameters
    # ... logic ...
    return [{"task_type": "...", "parameters": {...}}]
```

**NEW PATTERN** (ProcessRasterWorkflow after):
```python
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
    if stage == 1:
        task_id = generate_deterministic_task_id(job_id, 1, "validate")
        return [{"task_id": task_id, "task_type": "...", "parameters": {...}}]
```

**Key Differences:**
1. Single method handles all stages via `if stage == X:` logic
2. No `context` object - uses raw primitives
3. Must include `task_id` in returned dicts
4. Uses `previous_results` list instead of `context.stage_results`

### Why No Fallbacks?

**Philosophy: "No Backward Compatibility in Development"**

Per project guidelines (CLAUDE.md):
> When changing core architecture:
> 1. **Remove deprecated patterns completely**
> 2. **Add explicit validation with clear error messages**
> 3. **Update all calling code to use new pattern**
> 4. **Add tests that verify deprecated patterns fail**

**Benefits:**
- ✅ **Binary execution**: Correct signature works, wrong signature fails loudly
- ✅ **No hidden technical debt**: Can't accidentally use old patterns
- ✅ **Fast iteration**: No compatibility shims slowing development
- ✅ **Quality enforcement**: Integration issues caught immediately

---

## Testing Checklist

### ✅ Local Tests (Completed)
- [x] Syntax validation for both job files
- [x] Import validation (all 8 jobs registered)
- [x] Method presence verification
- [x] NO AttributeError for create_tasks_for_stage

### 🔲 Deployment Tests (Next Steps)
- [ ] Deploy to Azure Functions
- [ ] Health check (all imports successful)
- [ ] Test validate_raster_job with container_name parameter
- [ ] Test process_raster job (2-stage workflow)
- [ ] Verify Stage 1 → Stage 2 advancement with previous_results

---

## Expected Behavior

### ✅ Correct Usage
```bash
# ValidateRasterJob
curl -X POST .../api/jobs/submit/validate_raster_job \
  -d '{"blob_name": "test.tif", "container_name": "rmhazuregeobronze"}'
# → SUCCESS

# ProcessRasterWorkflow
curl -X POST .../api/jobs/submit/process_raster \
  -d '{"blob_name": "test.tif", "container_name": "rmhazuregeobronze"}'
# → SUCCESS
```

### ❌ Incorrect Usage (Deprecated Parameter)
```bash
curl -X POST .../api/jobs/submit/process_raster \
  -d '{"blob_name": "test.tif", "container": "rmhazuregeobronze"}'
# → FAILS with validation error: "container_name must be a non-empty string"
# (container parameter ignored, container_name=None fails validation)
```

### ❌ Incorrect Usage (Old Method Call)
```python
# Code attempting to call old method
workflow.create_stage_1_tasks(context)
# → AttributeError: 'ProcessRasterWorkflow' object has no attribute 'create_stage_1_tasks'
```

---

## Files Modified

1. **jobs/process_raster.py** - Complete rewrite, 488 lines
   - Added: create_tasks_for_stage, generate_job_id, create_job_record, queue_job, validate_job_parameters
   - Removed: create_stage_1_tasks, create_stage_2_tasks
   - Changed: All `"container"` → `"container_name"`

2. **jobs/validate_raster_job.py** - Parameter standardization
   - Changed: All `"container"` → `"container_name"` (7 locations)
   - No method changes (already compliant)

---

## Next Steps

1. **Deploy to Azure Functions**
2. **Test validate_raster_job** (already working, verify with new parameter name)
3. **Test process_raster workflow** (Stage 1 → Stage 2)
4. **Verify handlers** (validate_raster, create_cog) work with container_name

---

## Success Criteria ✅

- [x] ProcessRasterWorkflow has `create_tasks_for_stage()` method matching signature
- [x] ProcessRasterWorkflow has all trigger support methods
- [x] All parameter references use `container_name` (not `container`)
- [x] Local imports pass for both job classes
- [x] NO fallback logic for deprecated patterns
- [x] NO old methods remaining (create_stage_X_tasks removed)
- [ ] ValidateRasterJob job completes successfully in Azure
- [ ] ProcessRasterWorkflow job completes successfully (Stage 1 → Stage 2)
- [ ] Health endpoint shows all handlers registered
- [ ] No AttributeError when CoreMachine calls job_class.create_tasks_for_stage()

**Status**: 6/10 complete (local tests passing, deployment tests pending)
