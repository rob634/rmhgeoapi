# Raster Collection Workflow - Pattern Compliance Review

**Date**: 20 OCT 2025
**Reviewer**: Geospatial Claude Legion
**Files Reviewed**:
- `jobs/process_raster_collection.py`
- `services/raster_mosaicjson.py`
- `services/stac_collection.py`

---

## 🔴 CRITICAL ISSUES - Must Fix Before Testing

### Issue 1: Incorrect Parallelism Values in Stage Definitions

**Location**: `jobs/process_raster_collection.py:85, 92, 99, 106`

**Current (WRONG)**:
```python
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "validate_tiles",
        "task_type": "validate_raster",
        "parallelism": "multiple"  # ❌ WRONG - not a valid value
    },
    {
        "number": 2,
        "name": "create_cogs",
        "task_type": "create_cog",
        "parallelism": "multiple"  # ❌ WRONG - not a valid value
    },
    ...
]
```

**Should Be**:
```python
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "validate_tiles",
        "task_type": "validate_raster",
        "parallelism": "single"  # ✅ CORRECT - orchestration-time parallelism
    },
    {
        "number": 2,
        "name": "create_cogs",
        "task_type": "create_cog",
        "parallelism": "fan_out"  # ✅ CORRECT - result-driven parallelism
    },
    {
        "number": 3,
        "name": "create_mosaicjson",
        "task_type": "create_mosaicjson",
        "parallelism": "fan_in"  # ✅ CORRECT - already correct!
    },
    {
        "number": 4,
        "name": "create_stac_collection",
        "task_type": "create_stac_collection",
        "parallelism": "fan_in"  # ✅ CORRECT - already correct!
    }
]
```

**Explanation**:
From `jobs/base.py:37`:
- `"single"` - Orchestration-time parallelism (N from params or hardcoded)
- `"fan_out"` - Result-driven parallelism (N from previous_results)
- `"fan_in"` - Auto-aggregation (CoreMachine creates 1 task)

**Stage 1 Analysis**:
- Creates N tasks from `job_params["blob_list"]` (known at job submission)
- N is determined BEFORE any execution
- Pattern: **"single"** (orchestration-time)

**Stage 2 Analysis**:
- Creates N tasks FROM Stage 1 validation results
- N discovered at runtime (only create COGs for validated tiles)
- Pattern: **"fan_out"** (result-driven)

**Comparison to Vector ETL**:
```python
# jobs/ingest_vector.py - CORRECT pattern
{
    "number": 1,
    "name": "prepare_chunks",
    "task_type": "prepare_vector_chunks",
    "parallelism": "single"  # Creates tasks from job params
},
{
    "number": 2,
    "name": "upload_chunks",
    "task_type": "upload_pickled_chunk",
    "parallelism": "fan_out"  # Creates tasks from Stage 1 results
},
{
    "number": 3,
    "name": "create_stac_record",
    "task_type": "create_vector_stac",
    "parallelism": "single"  # Single task, no fan-in
}
```

---

### Issue 2: Method Signature Mismatch - create_tasks_for_stage

**Location**: `jobs/process_raster_collection.py:402`

**Current (WRONG)**:
```python
@staticmethod
def create_tasks_for_stage(
    stage_number: int,  # ❌ WRONG parameter name
    job_id: str,        # ❌ WRONG parameter order
    job_params: Dict[str, Any],
    previous_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
```

**Should Be** (per `jobs/base.py:274-279`):
```python
@staticmethod
def create_tasks_for_stage(
    stage: int,  # ✅ CORRECT parameter name
    job_params: dict,  # ✅ CORRECT parameter order
    job_id: str,
    previous_results: list = None
) -> List[dict]:
```

**Impact**:
- CoreMachine calls this method with specific parameter order
- Signature mismatch will cause runtime errors
- This is part of the ABC contract

**Examples from existing jobs**:
```python
# jobs/ingest_vector.py:290 - CORRECT
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:

# jobs/process_raster.py:349 - CORRECT
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
```

---

### Issue 3: Stage 3 and 4 Task Creation Logic (fan_in pattern)

**Location**: `jobs/process_raster_collection.py:550-670`

**Current Implementation**:
- Stage 3: `_create_stage_3_tasks()` manually creates 1 task
- Stage 4: `_create_stage_4_tasks()` manually creates 1 task

**Expected for fan_in**:
According to `jobs/base.py:46-49`:
```
"fan_in": Auto-aggregation (CoreMachine handles)
    - CoreMachine auto-creates 1 task (job does nothing)
    - Task receives ALL previous results via params["previous_results"]
```

**Should Be**:
```python
@staticmethod
def create_tasks_for_stage(
    stage: int,
    job_params: dict,
    job_id: str,
    previous_results: list = None
) -> List[dict]:
    if stage == 1:
        return ProcessRasterCollectionWorkflow._create_stage_1_tasks(job_id, job_params)
    elif stage == 2:
        return ProcessRasterCollectionWorkflow._create_stage_2_tasks(job_id, job_params, previous_results)
    elif stage == 3:
        # fan_in - CoreMachine auto-creates task, job returns empty list
        return []
    elif stage == 4:
        # fan_in - CoreMachine auto-creates task, job returns empty list
        return []
    else:
        raise ValueError(f"Invalid stage number: {stage}")
```

**Task Handler Changes Required**:

`services/raster_mosaicjson.py` must expect `previous_results` in parameters:
```python
def create_mosaicjson(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Task handler signature - receives previous_results from CoreMachine.

    Args:
        params: Task parameters containing:
            - previous_results: List of Stage 2 COG creation results
            - collection_name: Collection identifier
            - output_folder: Output folder path
        context: Optional context
    """
    # Extract COG blobs from previous_results
    previous_results = params.get("previous_results", [])
    cog_blobs = [
        r.get("result_data", {}).get("cog_blob_name")
        for r in previous_results
        if r.get("result_data", {}).get("cog_blob_name")
    ]

    collection_name = params.get("collection_name")
    output_folder = params.get("output_folder", "mosaics")
    container = params.get("container", "rmhazuregeosilver")

    # ... rest of logic
```

`services/stac_collection.py` must expect Stage 3 result:
```python
def create_stac_collection(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Task handler signature - receives previous_results from CoreMachine.

    Args:
        params: Task parameters containing:
            - previous_results: List with single Stage 3 MosaicJSON result
            - collection_id: Collection identifier
            - description: Collection description
        context: Optional context
    """
    # Extract MosaicJSON result from previous_results
    previous_results = params.get("previous_results", [])
    if not previous_results:
        raise ValueError("No MosaicJSON result from Stage 3")

    mosaic_result = previous_results[0].get("result_data", {})
    mosaicjson_blob = mosaic_result.get("mosaicjson_blob")

    # ... rest of logic
```

**Comparison to Vector ETL**:
Vector ETL uses **"single"** for Stage 3, not "fan_in":
```python
# jobs/ingest_vector.py - Stage 3 is "single", not "fan_in"
{
    "number": 3,
    "name": "create_stac_record",
    "task_type": "create_vector_stac",
    "parallelism": "single"  # Manually creates 1 task
}

# create_tasks_for_stage:
elif stage == 3:
    return ProcessRasterCollectionWorkflow._create_stage_3_tasks(...)
```

**Decision Required**:
Should Stages 3 and 4 use:
- **"fan_in"** - CoreMachine auto-creates task (simpler, less code)
- **"single"** - Job manually creates 1 task (more explicit control)

**Recommendation**: Use **"fan_in"** for both Stages 3 and 4:
- Simpler job code (no manual task creation)
- Handler receives all previous results automatically
- Follows documented pattern in base.py

---

## 🟡 MODERATE ISSUES - Should Fix

### Issue 4: Task Handler Function Signatures

**Location**: `services/raster_mosaicjson.py:50`, `services/stac_collection.py:50`

**Current Implementation**:
```python
# services/raster_mosaicjson.py
def create_mosaicjson(
    cog_blobs: List[str],  # ❌ Not following handler contract
    collection_name: str,
    container: str = "rmhazuregeosilver",
    output_folder: str = "mosaics"
) -> Dict[str, Any]:
```

**Expected Handler Contract**:
```python
def create_mosaicjson(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Standard task handler signature.

    Args:
        params: Task parameters (dict)
        context: Optional context (dict or None)

    Returns:
        {"success": bool, ...}
    """
```

**From `services/__init__.py:32-69`**:
```python
Handler Function Contract (ENFORCED BY CoreMachine):
    def handler(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        '''
        Returns:
            Dict with REQUIRED 'success' field (bool) and additional data:

            SUCCESS FORMAT:
                {
                    "success": True,        # REQUIRED
                    "result": {...}         # Optional
                }

            FAILURE FORMAT:
                {
                    "success": False,       # REQUIRED
                    "error": "error message",  # REQUIRED
                    "error_type": "ValueError" # Optional
                }
        '''
```

**Impact**:
- Handlers won't be callable by CoreMachine
- Will fail at runtime when tasks execute

---

### Issue 5: Missing Success Field in Return Values

**Location**: `services/raster_mosaicjson.py:148`, `services/stac_collection.py:138`

**Current**:
```python
# services/raster_mosaicjson.py - Missing "success" field
return {
    "mosaicjson_blob": mosaicjson_blob,
    "mosaicjson_url": mosaicjson_url,
    # ... other fields
    # ❌ Missing "success": True
}
```

**Should Be**:
```python
return {
    "success": True,  # ✅ REQUIRED by handler contract
    "mosaicjson_blob": mosaicjson_blob,
    "mosaicjson_url": mosaicjson_url,
    # ... other fields
}
```

**Same Issue in** `services/stac_collection.py:138`

---

## 🟢 MINOR ISSUES - Nice to Have

### Issue 6: Type Hint Consistency

**Location**: Multiple files

**Pattern in Codebase**:
- Use lowercase `dict`, `list` for Python 3.9+ compatibility
- Not `Dict`, `List` from typing module

**Example from existing code**:
```python
# jobs/ingest_vector.py:290 - Uses lowercase
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
```

**Current Code** uses `Dict`, `List` - works but inconsistent

---

## 📋 SUMMARY OF REQUIRED CHANGES

### High Priority (Breaks Functionality):

1. **Fix parallelism values**:
   - Stage 1: `"multiple"` → `"single"`
   - Stage 2: `"multiple"` → `"fan_out"`
   - Stages 3-4: Already correct (`"fan_in"`)

2. **Fix create_tasks_for_stage signature**:
   - Change `stage_number: int` → `stage: int`
   - Change order: `(stage, job_params, job_id, previous_results=None)`

3. **Implement fan_in pattern correctly**:
   - Stages 3-4: Return empty list `[]`
   - CoreMachine auto-creates tasks
   - Handlers receive `params["previous_results"]`

4. **Fix handler signatures**:
   - Change to: `def handler(params: dict, context: dict = None) -> dict:`
   - Extract parameters from `params` dict inside handler
   - Return dict with `"success": True/False`

### Medium Priority (Best Practices):

5. **Add "success" field** to all handler return values
6. **Update type hints** to use lowercase `dict`, `list`

---

## 🔄 RECOMMENDED REFACTORING APPROACH

### Step 1: Fix Job Class (process_raster_collection.py)

```python
# 1. Fix stage definitions
stages: List[Dict[str, Any]] = [
    {"number": 1, "parallelism": "single", ...},
    {"number": 2, "parallelism": "fan_out", ...},
    {"number": 3, "parallelism": "fan_in", ...},
    {"number": 4, "parallelism": "fan_in", ...},
]

# 2. Fix method signature
@staticmethod
def create_tasks_for_stage(
    stage: int,
    job_params: dict,
    job_id: str,
    previous_results: list = None
) -> list[dict]:

# 3. Simplify fan_in stages
if stage == 3 or stage == 4:
    return []  # CoreMachine handles fan_in
```

### Step 2: Fix MosaicJSON Handler (raster_mosaicjson.py)

```python
def create_mosaicjson(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create MosaicJSON from COG collection (fan_in aggregation).

    Receives previous_results from CoreMachine containing all Stage 2 COG creation results.
    """
    # Extract from params (fan_in pattern)
    previous_results = params.get("previous_results", [])
    collection_name = params.get("collection_name")
    output_folder = params.get("output_folder", "mosaics")
    container = params.get("container", "rmhazuregeosilver")

    # Extract COG blobs from previous results
    cog_blobs = [
        r.get("result_data", {}).get("cog_blob_name")
        for r in previous_results
        if r.get("result_data", {}).get("cog_blob_name")
    ]

    if not cog_blobs:
        return {
            "success": False,
            "error": "No COG blobs found in previous results"
        }

    try:
        # ... existing MosaicJSON creation logic

        return {
            "success": True,  # ✅ Required field
            "mosaicjson_blob": mosaicjson_blob,
            "mosaicjson_url": mosaicjson_url,
            "tile_count": len(cog_blobs),
            "bounds": bounds,
            "minzoom": minzoom,
            "maxzoom": maxzoom
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
```

### Step 3: Fix STAC Collection Handler (stac_collection.py)

```python
def create_stac_collection(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create STAC collection (fan_in aggregation).

    Receives previous_results from CoreMachine containing Stage 3 MosaicJSON result.
    """
    # Extract from params (fan_in pattern)
    previous_results = params.get("previous_results", [])
    collection_id = params.get("collection_id")
    description = params.get("description")

    # Get MosaicJSON result from Stage 3
    if not previous_results:
        return {
            "success": False,
            "error": "No MosaicJSON result from Stage 3"
        }

    mosaic_result = previous_results[0].get("result_data", {})
    mosaicjson_blob = mosaic_result.get("mosaicjson_blob")
    spatial_extent = mosaic_result.get("bounds")
    tile_count = mosaic_result.get("tile_count", 0)

    try:
        # ... existing STAC collection creation logic

        return {
            "success": True,  # ✅ Required field
            "collection_id": collection_id,
            "stac_id": collection.id,
            "pgstac_id": pgstac_id,
            "tile_count": tile_count,
            "spatial_extent": spatial_extent,
            "mosaicjson_url": mosaicjson_url
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
```

---

## ✅ VALIDATION CHECKLIST

Before deployment:

- [ ] Stage 1 parallelism: `"single"` ✅
- [ ] Stage 2 parallelism: `"fan_out"` ✅
- [ ] Stage 3 parallelism: `"fan_in"` ✅
- [ ] Stage 4 parallelism: `"fan_in"` ✅
- [ ] `create_tasks_for_stage` signature matches base class ✅
- [ ] Stages 3-4 return empty list `[]` ✅
- [ ] `create_mosaicjson` uses handler contract signature ✅
- [ ] `create_stac_collection` uses handler contract signature ✅
- [ ] Both handlers return `{"success": bool, ...}` ✅
- [ ] Both handlers extract params from `params["previous_results"]` ✅

---

## 📚 REFERENCE IMPLEMENTATIONS

**Correct fan_out + fan_in pattern**: `jobs/ingest_vector.py`
- Stage 1: "single" (hardcoded 1 task)
- Stage 2: "fan_out" (N tasks from Stage 1 results)
- Stage 3: "single" (manually creates 1 task)

**Correct handler contract**: `services/vector/tasks.py`
```python
def prepare_vector_chunks(params: dict, context: dict = None) -> dict:
    return {"success": True, "chunk_count": N, ...}

def upload_pickled_chunk(params: dict, context: dict = None) -> dict:
    return {"success": True, "rows_inserted": N, ...}
```

---

**Author**: Robert and Geospatial Claude Legion
**Next Steps**: Apply fixes and redeploy for testing
