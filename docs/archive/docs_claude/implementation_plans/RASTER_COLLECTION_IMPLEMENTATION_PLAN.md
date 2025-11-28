# Raster Collection Workflow - Implementation Plan

**Date**: 22 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Implementation Ready - Fixes Required
**Priority**: HIGH - Foundation for Large Raster Tiling

---

## 🎯 Executive Summary

**Goal**: Complete the `process_raster_collection` 4-stage workflow following CoreMachine patterns validated on 21-22 OCT 2025.

**Current Status**:
- ✅ **Job class exists**: `jobs/process_raster_collection.py`
- ✅ **Services exist**: `services/raster_mosaicjson.py`, `services/stac_collection.py`
- ✅ **Stages 1-2 services validated**: `validate_raster`, `create_cog` (100% reusable)
- ❌ **Pattern compliance issues**: Parallelism values, signatures, fan_in implementation
- ✅ **CoreMachine framework validated**: Status transitions fixed, task IDs fixed

**Estimated Fix Time**: 2-3 hours
**Estimated Test Time**: 1-2 hours

---

## 📊 Architecture: 4-Stage Diamond Pattern

```
INPUT: List of raster tiles (blob_list)
  ↓
STAGE 1: Validate All Tiles (PARALLEL - "single")
  ├─ Task: validate_raster (tile 0) ✅ Existing handler
  ├─ Task: validate_raster (tile 1) ✅ Existing handler
  └─ Task: validate_raster (tile N) ✅ Existing handler
       ↓ Fan-out: N tasks determined from job_params["blob_list"]
       ↓ Aggregate: Verify all same CRS, band count, dtype
       ↓
STAGE 2: Convert All to COGs (PARALLEL - "fan_out")
  ├─ Task: create_cog (tile 0) ✅ Existing handler
  ├─ Task: create_cog (tile 1) ✅ Existing handler
  └─ Task: create_cog (tile N) ✅ Existing handler
       ↓ Fan-out: N tasks from Stage 1 validation results
       ↓ Aggregate: Collect all COG URLs
       ↓
STAGE 3: Create MosaicJSON (SINGLE - "fan_in")
  └─ Task: create_mosaicjson (auto-created by CoreMachine)
       ↓ Input: params["previous_results"] = Stage 2 COG results
       ↓ Output: mosaicjson_blob, bounds, zoom levels
       ↓
STAGE 4: Create STAC Collection (SINGLE - "fan_in")
  └─ Task: create_stac_collection (auto-created by CoreMachine)
       ↓ Input: params["previous_results"] = Stage 3 MosaicJSON result
       ↓ Output: STAC collection with MosaicJSON asset
```

**Key Pattern**: This follows the **Diamond Pattern** (fan-out → fan-in)
- Start: 1 job message
- Stage 1: Fan-out to N validation tasks
- Stage 2: Fan-out to N COG tasks
- Stage 3: Fan-in to 1 MosaicJSON task
- Stage 4: Fan-in to 1 STAC task
- End: 1 completed job

---

## 🔴 CRITICAL FIXES REQUIRED

### Fix 1: Parallelism Values (BREAKING)

**File**: `jobs/process_raster_collection.py`
**Lines**: 36-51

**Current (WRONG)**:
```python
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "validate_tiles",
        "task_type": "validate_raster",
        "parallelism": "multiple"  # ❌ Invalid value
    },
    {
        "number": 2,
        "name": "create_cogs",
        "task_type": "create_cog",
        "parallelism": "multiple"  # ❌ Invalid value
    },
    ...
]
```

**Must Be**:
```python
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "validate_tiles",
        "task_type": "validate_raster",
        "description": "Validate raster tiles in parallel",
        "parallelism": "single"  # ✅ Orchestration-time (N from blob_list)
    },
    {
        "number": 2,
        "name": "create_cogs",
        "task_type": "create_cog",
        "description": "Convert validated tiles to COGs",
        "parallelism": "fan_out"  # ✅ Result-driven (N from Stage 1)
    },
    {
        "number": 3,
        "name": "create_mosaicjson",
        "task_type": "create_mosaicjson",
        "description": "Generate MosaicJSON from COG collection",
        "parallelism": "fan_in"  # ✅ Already correct
    },
    {
        "number": 4,
        "name": "create_stac_collection",
        "task_type": "create_stac_collection",
        "description": "Create STAC collection metadata",
        "parallelism": "fan_in"  # ✅ Already correct
    }
]
```

**Reference**: `jobs/base.py:37-49` defines valid parallelism values:
- `"single"` - Orchestration-time parallelism (N known at job submission)
- `"fan_out"` - Result-driven parallelism (N from previous_results)
- `"fan_in"` - Auto-aggregation (CoreMachine creates 1 task)

---

### Fix 2: Method Signature (BREAKING)

**File**: `jobs/process_raster_collection.py`
**Line**: 402

**Current (WRONG)**:
```python
@staticmethod
def create_tasks_for_stage(
    stage_number: int,  # ❌ Wrong parameter name
    job_id: str,        # ❌ Wrong parameter order
    job_params: Dict[str, Any],
    previous_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
```

**Must Be** (per `jobs/base.py:274-279`):
```python
@staticmethod
def create_tasks_for_stage(
    stage: int,                    # ✅ Correct name
    job_params: dict,               # ✅ Correct order
    job_id: str,
    previous_results: list = None
) -> list[dict]:
```

**Why**: CoreMachine calls this method with specific parameter order. Mismatch causes runtime errors.

---

### Fix 3: Fan-In Pattern Implementation (BREAKING)

**File**: `jobs/process_raster_collection.py`
**Lines**: 598-720

**Current (WRONG)**:
```python
elif stage == 3:
    return ProcessRasterCollectionWorkflow._create_stage_3_tasks(...)
elif stage == 4:
    return ProcessRasterCollectionWorkflow._create_stage_4_tasks(...)
```

**Must Be**:
```python
elif stage == 3:
    return []  # ✅ CoreMachine auto-creates task for fan_in
elif stage == 4:
    return []  # ✅ CoreMachine auto-creates task for fan_in
else:
    raise ValueError(f"Invalid stage: {stage}")
```

**Why**:
- `"fan_in"` parallelism means CoreMachine automatically creates 1 task
- Job class returns empty list
- CoreMachine passes ALL previous results via `params["previous_results"]`

**Reference**: `jobs/base.py:46-49`:
```python
"fan_in": Auto-aggregation (CoreMachine handles)
    - CoreMachine auto-creates 1 task (job does nothing)
    - Task receives ALL previous results via params["previous_results"]
```

---

### Fix 4: Handler Signatures (BREAKING)

**File**: `services/raster_mosaicjson.py`
**Line**: 50

**Current (WRONG)**:
```python
def create_mosaicjson(
    cog_blobs: List[str],  # ❌ Not handler contract
    collection_name: str,
    container: str = "rmhazuregeosilver",
    output_folder: str = "mosaics"
) -> Dict[str, Any]:
```

**Must Be** (per `services/__init__.py:32-69`):
```python
def create_mosaicjson(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create MosaicJSON from COG collection (fan_in aggregation).

    Handler receives previous_results from CoreMachine containing
    all Stage 2 COG creation results.

    Args:
        params: Task parameters containing:
            - previous_results: List of Stage 2 COG results
            - collection_name: Collection identifier
            - output_folder: Output folder path
            - container: Storage container
        context: Optional execution context

    Returns:
        {
            "success": True/False,
            "mosaicjson_blob": "path/to/mosaic.json",
            "mosaicjson_url": "https://...",
            "tile_count": N,
            "bounds": [...],
            "minzoom": X,
            "maxzoom": Y
        }
    """
    # Extract parameters
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
            "success": True,  # ✅ Required
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

**Same Fix Required**: `services/stac_collection.py` (see RASTER_COLLECTION_REVIEW.md:503-547)

---

### Fix 5: Add Success Field (BREAKING)

**Files**: `services/raster_mosaicjson.py`, `services/stac_collection.py`

**Current (WRONG)**:
```python
return {
    "mosaicjson_blob": mosaicjson_blob,
    # ... other fields
    # ❌ Missing "success" field
}
```

**Must Be**:
```python
return {
    "success": True,  # ✅ Required by handler contract
    "mosaicjson_blob": mosaicjson_blob,
    # ... other fields
}
```

**Why**: CoreMachine requires `"success"` field to determine task status.

**Reference**: `services/__init__.py:40-51` - Handler contract enforced by CoreMachine.

---

## ✅ Components Already Working

### Reusable Services (100% Ready)

**Stage 1: Validation** ✅
- Handler: `validate_raster` in `services/raster_validation.py`
- Features: Band count, dtype, CRS, raster type, tier compatibility
- Registration: Already in `services/__init__.py`
- **No changes needed**

**Stage 2: COG Conversion** ✅
- Handler: `create_cog` in `services/raster_cog.py`
- Features: Multi-tier, compression, reprojection, overviews, custom output folder
- Registration: Already in `services/__init__.py`
- **No changes needed**

**Orchestration Framework** ✅
- CoreMachine: Status transitions validated (21 OCT 2025)
- Task IDs: Fixed semantic naming (22 OCT 2025)
- JobBase ABC: Stage management, fan-out/fan-in patterns
- Database/Queue: PostgreSQL + Service Bus working
- **No changes needed**

---

## 📋 Implementation Checklist

### Phase 1: Fix Job Class (30 minutes)

- [ ] Fix stage parallelism values (Line 36-51)
  - Stage 1: `"multiple"` → `"single"`
  - Stage 2: `"multiple"` → `"fan_out"`
  - Stages 3-4: Already `"fan_in"` ✅

- [ ] Fix `create_tasks_for_stage` signature (Line 402)
  - Parameter name: `stage_number` → `stage`
  - Parameter order: `(stage, job_params, job_id, previous_results=None)`
  - Return type: `list[dict]`

- [ ] Implement fan_in pattern (Lines 598-720)
  - Stage 3: Return `[]` instead of calling `_create_stage_3_tasks()`
  - Stage 4: Return `[]` instead of calling `_create_stage_4_tasks()`
  - Add `else: raise ValueError(f"Invalid stage: {stage}")`

- [ ] Remove unused methods (cleanup)
  - Delete `_create_stage_3_tasks()` (no longer needed)
  - Delete `_create_stage_4_tasks()` (no longer needed)

### Phase 2: Fix Handlers (1 hour)

- [ ] Fix `services/raster_mosaicjson.py`
  - Change signature to `(params: dict, context: dict = None) -> dict`
  - Extract `previous_results` from `params`
  - Extract COG blobs from `previous_results`
  - Add `"success": True` to return dict
  - Add try/except with `"success": False` on error

- [ ] Fix `services/stac_collection.py`
  - Change signature to `(params: dict, context: dict = None) -> dict`
  - Extract `previous_results` from `params`
  - Get MosaicJSON result from `previous_results[0]`
  - Add `"success": True` to return dict
  - Add try/except with `"success": False` on error

### Phase 3: Testing (2 hours)

- [ ] Deploy to Azure
  - `func azure functionapp publish rmhgeoapibeta --python --build remote`

- [ ] Test 2-tile collection
  ```bash
  curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster_collection \
    -H "Content-Type: application/json" \
    -d '{
      "collection_id": "test_2tile",
      "container_name": "rmhazuregeosilver",
      "blob_list": [
        "namangan/namangan14aug2019_R1C1cog_analysis.tif",
        "namangan/namangan14aug2019_R1C2cog_analysis.tif"
      ],
      "output_tier": "visualization",
      "output_folder": "test/collection_validation",
      "create_mosaicjson": true,
      "create_stac_collection": true
    }'
  ```

- [ ] Verify Stage 1: 2 validation tasks completed
- [ ] Verify Stage 2: 2 COG tasks completed with correct task IDs
- [ ] Verify Stage 3: 1 MosaicJSON task completed
  - Check blob storage for `mosaicjson` file
  - Verify quadkey index structure
  - Verify tile references match COG URLs

- [ ] Verify Stage 4: 1 STAC collection task completed
  - Query PgSTAC for collection
  - Verify MosaicJSON URL in assets
  - Verify spatial extent matches union of tiles

- [ ] Check Application Insights logs
  - No "Invalid status transition" errors ✅
  - Clean PROCESSING → QUEUED → PROCESSING transitions ✅
  - All 4 stages advance correctly ✅

### Phase 4: Documentation (30 minutes)

- [ ] Update `docs_claude/TODO.md` with completion
- [ ] Update `docs_claude/HISTORY.md` with results
- [ ] Document test results in this file
- [ ] Commit all changes with detailed message

---

## 🎯 Success Criteria

**Stage Transitions**:
- ✅ QUEUED → PROCESSING (Stage 1)
- ✅ PROCESSING → QUEUED → PROCESSING (Stage 1 → 2)
- ✅ PROCESSING → QUEUED → PROCESSING (Stage 2 → 3)
- ✅ PROCESSING → QUEUED → PROCESSING (Stage 3 → 4)
- ✅ PROCESSING → COMPLETED (Stage 4)

**Task Creation**:
- ✅ Stage 1: N tasks (N = len(blob_list))
- ✅ Stage 2: N tasks (N from Stage 1 results)
- ✅ Stage 3: 1 task (auto-created by CoreMachine)
- ✅ Stage 4: 1 task (auto-created by CoreMachine)

**Task IDs**:
- ✅ Format: `{job_id[:8]}-s{stage}-{semantic_name}-{i}`
- ✅ All IDs < 100 chars
- ✅ Semantic names: `validate-{i}`, `cog-{i}`, `mosaicjson`, `stac`

**Outputs**:
- ✅ MosaicJSON file created in blob storage
- ✅ STAC collection created in PgSTAC
- ✅ MosaicJSON URL in STAC collection assets
- ✅ All COG tiles referenced in MosaicJSON

---

## 📚 Reference Documentation

**CoreMachine Patterns**:
- `jobs/base.py:37-49` - Parallelism definitions
- `jobs/base.py:274-279` - create_tasks_for_stage signature
- `services/__init__.py:32-69` - Handler contract

**Working Examples**:
- `jobs/ingest_vector.py` - Fan-out + fan-in pattern
- `jobs/hello_world.py` - Simple 2-stage pattern
- `jobs/container_list.py` - 2-stage with aggregation

**Recent Validations**:
- `COREMACHINE_STATUS_TRANSITION_FIX.md` - Status transition fixes
- `docs_claude/TODO.md` (22 OCT 2025) - Task ID fixes
- `docs_claude/HISTORY.md` (21-22 OCT 2025) - CoreMachine validation

**Implementation Guides**:
- `docs_claude/MOSAICJSON_IMPLEMENTATION_PLAN.md` - Original plan
- `docs_claude/RASTER_COLLECTION_REVIEW.md` - Pattern compliance issues
- `COG_MOSAIC.md` - MosaicJSON workflow design

---

## 🚀 Next Steps After Completion

**Phase 2: Large Raster Automatic Tiling**:
- Add file size detection in `process_raster` job
- If size > 2GB, create tiling scheme
- Submit `process_raster_collection` job with tile list
- Result: Single large file → Multiple COG tiles → 1 MosaicJSON → 1 STAC collection

**Phase 3: TiTiler Integration**:
- Deploy TiTiler service
- Add tile proxy endpoint: `/api/datasets/{id}/tiles/{z}/{x}/{y}`
- Extract MosaicJSON URL from STAC collection
- Proxy tile requests to TiTiler

**Phase 4: Delivery Discovery Integration**:
- Update `services/delivery_discovery.py`
- Return ready-to-submit parameters for `process_raster_collection`
- End-to-end: Upload vendor delivery → Discovery → Automatic collection processing

---

**Author**: Robert and Geospatial Claude Legion
**Priority**: HIGH - Foundation for large raster processing
**Estimated Total Time**: 4-5 hours (implementation + testing)
**Next Action**: Apply Fix 1 (parallelism values)
