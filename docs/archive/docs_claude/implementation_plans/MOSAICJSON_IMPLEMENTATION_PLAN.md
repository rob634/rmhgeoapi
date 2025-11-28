# MosaicJSON Workflow - Implementation Plan

**Date**: 20 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Ready for Implementation

---

## 🎯 Goal

Create a workflow that:
1. Takes a list of raster tiles (e.g., R1C1.tif, R1C2.tif, ...)
2. Converts each tile to COG in parallel
3. Generates a single MosaicJSON file that references all COGs
4. Creates a STAC Collection with linked items

---

## 📋 Architecture Overview

```
INPUT: List of raster tiles
  ↓
STAGE 1: Validate All Tiles (Parallel)
  ├─ Task: validate_raster (tile R1C1)
  ├─ Task: validate_raster (tile R1C2)
  └─ Task: validate_raster (tile R1C3)
       ↓ Aggregate: Verify all same CRS, band count, dtype
       ↓
STAGE 2: Convert All to COGs (Parallel)
  ├─ Task: create_cog (tile R1C1) → cogs/R1C1_cog.tif
  ├─ Task: create_cog (tile R1C2) → cogs/R1C2_cog.tif
  └─ Task: create_cog (tile R1C3) → cogs/R1C3_cog.tif
       ↓ Aggregate: Collect all COG URLs
       ↓
STAGE 3: Create MosaicJSON (Single Task)
  └─ Task: create_mosaicjson
       ↓ Input: List of COG URLs from Stage 2
       ↓ Output: collection_name.json (MosaicJSON file)
       ↓
STAGE 4: Create STAC Collection (Single Task)
  └─ Task: create_stac_collection
       ↓ Create collection-level STAC item
       ↓ Link MosaicJSON as primary asset
       ↓ Link individual COG STAC items as members
```

---

## 🔄 Reusable Components (Already Exist)

### **Stage 1: Validation** ✅ 100% Reusable

**What We Already Have**:
- ✅ **Task Handler**: `validate_raster` in `services/raster_validation.py`
- ✅ **Registration**: Already registered in `services/__init__.py`
- ✅ **Capabilities**:
  - Band count detection
  - Data type detection (uint8, uint16, float32, etc.)
  - CRS extraction
  - Raster type detection (RGB, DEM, multispectral)
  - COG tier compatibility detection
  - Geometry validation

**No changes needed!** This service is already designed to be called in parallel.

---

### **Stage 2: COG Conversion** ✅ 100% Reusable

**What We Already Have**:
- ✅ **Task Handler**: `create_cog` in `services/raster_cog.py`
- ✅ **Registration**: Already registered in `services/__init__.py`
- ✅ **Capabilities**:
  - Multi-tier support (visualization, analysis, archive)
  - Automatic compression selection (JPEG, DEFLATE, LZW)
  - Custom output folder support (20 OCT 2025)
  - Reprojection (if needed)
  - Overview generation
  - Storage tier assignment (hot vs cool)

**No changes needed!** The service already supports everything we need.

---

### **Orchestration Framework** ✅ 100% Reusable

**What We Already Have**:
- ✅ **CoreMachine**: Universal job orchestrator
- ✅ **JobBase ABC**: Abstract base class with stage management
- ✅ **Stage Advancement**: Automatic "last task turns out lights" pattern
- ✅ **Task Creation**: `create_tasks_for_stage()` method
- ✅ **Result Aggregation**: `aggregate_stage_results()` method
- ✅ **Parallelism Support**: `"parallelism": "fan_out"` for dynamic task counts

**Pattern Already Proven**:
- ✅ `process_raster` - 2 stages (validate → create_cog)
- ✅ `ingest_vector` - 2 stages (pickle chunks → upload)
- ✅ `list_container_contents` - 3 stages (fan-out → process → fan-in)

---

## 🆕 New Components to Build

### **Component Reuse Summary**

| Component | Reuse % | Status | Effort |
|-----------|---------|--------|--------|
| **Stage 1: Validation** | 100% | ✅ Exists | 0 hours |
| **Stage 2: COG Conversion** | 100% | ✅ Exists | 0 hours |
| **Orchestration (JobBase)** | 100% | ✅ Exists | 0 hours |
| **Database/Queue Infra** | 100% | ✅ Exists | 0 hours |
| **STAC Foundation** | 60% | ✅ Exists | 1 hour |
| **MosaicJSON Service** | 0% | 🆕 New | 2 hours |
| **Collection Job Class** | 70% | 🆕 New | 2 hours |
| **Task Registration** | 0% | 🆕 New | 0.5 hours |
| **Testing** | 50% | 🆕 New | 2 hours |
| **Total New Work** | | | **~7.5 hours** |

---

## 🏗️ Implementation Steps

### **Phase 1: Core Infrastructure** (~4 hours)

#### Step 1: Add MosaicJSON Dependencies
**File**: `requirements.txt`
**Time**: 5 minutes

```python
# Add cogeo-mosaic library
cogeo-mosaic>=7.0.0
```

---

#### Step 2: Create MosaicJSON Service
**File**: `services/raster_mosaicjson.py` (NEW)
**Time**: 2 hours

**Key Functions**:
- `create_mosaicjson(cog_urls, collection_name, container, output_folder)` → MosaicJSON file

**Dependencies**:
- `cogeo-mosaic` library for MosaicJSON generation
- Azure Blob Storage client for upload
- Tempfile for local processing

**Features**:
- Standards-compliant MosaicJSON creation
- Automatic zoom level calculation
- Quadkey-based tile indexing
- Blob storage upload
- Metadata return (bounds, zoom, tile count)

---

#### Step 3: Create Process Raster Collection Job
**File**: `jobs/process_raster_collection.py` (NEW)
**Time**: 2 hours

**Parameters**:
```python
{
    "blob_list": ["tile1.tif", "tile2.tif", ...],
    "collection_id": "unique_identifier",
    "container_name": "rmhazuregeobronze",
    "output_tier": "analysis",
    "output_folder": "cogs/collection/",
    "create_mosaicjson": true,
    "create_stac_collection": true
}
```

**Stage Breakdown**:
- **Stage 1**: Validate all tiles (parallel, reuse existing handler)
- **Stage 2**: Convert to COGs (parallel, reuse existing handler)
- **Stage 3**: Create MosaicJSON (single task, new handler)
- **Stage 4**: Create STAC collection (single task, new handler)

**Key Methods**:
- `validate_job_parameters()` - Validate blob_list, collection_id
- `create_tasks_for_stage()` - Generate N tasks for Stages 1-2, single tasks for 3-4
- `aggregate_stage_results()` - Collect COG URLs, verify consistency

---

### **Phase 2: Task Handlers** (~2 hours)

#### Step 4: Register MosaicJSON Task Handler
**File**: `services/__init__.py`
**Time**: 30 minutes

```python
@TaskRegistry.register("create_mosaicjson")
def handle_create_mosaicjson(params: dict) -> dict:
    """Create MosaicJSON from COG collection."""
    from services.raster_mosaicjson import create_mosaicjson
    return create_mosaicjson(
        cog_urls=params['cog_blobs'],
        collection_name=params['collection_name'],
        container=params.get('container', 'rmhazuregeosilver'),
        output_folder=params.get('output_folder', 'mosaics')
    )
```

---

#### Step 5: Create STAC Collection Service
**File**: `services/stac_collection.py` (NEW)
**Time**: 1 hour

**Key Function**:
- `create_stac_collection(collection_id, mosaicjson_blob, description)` → STAC Collection

**Features**:
- Uses `pystac.Collection` (similar to existing `pystac.Item`)
- Adds MosaicJSON as asset
- Inserts into PgSTAC collections table
- Links individual items as members

---

#### Step 6: Register STAC Collection Handler
**File**: `services/__init__.py`
**Time**: 30 minutes

```python
@TaskRegistry.register("create_stac_collection")
def handle_create_stac_collection(params: dict) -> dict:
    """Create STAC collection item."""
    from services.stac_collection import create_stac_collection
    return create_stac_collection(
        collection_id=params['collection_id'],
        mosaicjson_blob=params.get('mosaicjson_blob'),
        description=params.get('description')
    )
```

---

### **Phase 3: Registration** (~15 minutes)

#### Step 7: Register Job Type
**File**: `jobs/__init__.py`
**Time**: 5 minutes

```python
from jobs.process_raster_collection import ProcessRasterCollectionWorkflow

# Job will auto-register via @JobRegistry.instance().register() decorator
```

---

#### Step 8: Update Health Checks
**File**: `utils/import_validator.py` (if needed)
**Time**: 10 minutes

Add `cogeo-mosaic` to critical dependencies list.

---

### **Phase 4: Testing** (~2 hours)

#### Step 9: Unit Tests
**Time**: 30 minutes

Test each component in isolation:
- MosaicJSON creation with sample COG URLs
- STAC collection creation
- Task handler registration

---

#### Step 10: Integration Test - Simple Grid
**Time**: 30 minutes

**Test**: 2x2 tile grid
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster_collection \
  -H "Content-Type: application/json" \
  -d '{
    "blob_list": ["test/R1C1.tif", "test/R1C2.tif", "test/R2C1.tif", "test/R2C2.tif"],
    "collection_id": "test_grid_2x2",
    "output_folder": "cogs/test_grid",
    "create_mosaicjson": true
  }'
```

**Expected**:
- 4 validation tasks complete
- 4 COG tasks complete
- 1 MosaicJSON created at `mosaics/test_grid_2x2.json`
- MosaicJSON contains 4 tile references

---

#### Step 11: Integration Test - Real Maxar Data
**Time**: 1 hour

**Test**: Use delivery discovery → collection processing workflow

```bash
# Step 1: Discover delivery structure
curl -X POST https://rmhgeoapibeta.../api/analysis/delivery \
  -d @maxar_folder_blobs.json > discovery_result.json

# Step 2: Extract recommended workflow parameters
cat discovery_result.json | jq '.recommended_workflow.parameters' > job_params.json

# Step 3: Submit collection processing job
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster_collection \
  -d @job_params.json
```

**Expected**:
- All tiles validated (same CRS verification)
- All tiles converted to COGs
- MosaicJSON generated with correct bounds
- STAC collection created

---

### **Phase 5: Integration with Discovery** (~1 hour)

#### Step 12: Update Delivery Discovery
**File**: `services/delivery_discovery.py`
**Time**: 30 minutes

Enhance `analyze_delivery_structure()` to return exact submission-ready parameters.

**Add**:
```python
recommended_workflow["submit_url"] = f"https://rmhgeoapibeta.../api/jobs/submit/{job_type}"
recommended_workflow["ready_to_submit"] = True
```

---

#### Step 13: End-to-End Workflow Test
**Time**: 30 minutes

Test complete workflow:
1. User drops vendor delivery folder
2. Discovery API analyzes structure
3. Returns ready-to-use job parameters
4. User submits collection job
5. All tiles processed to COGs
6. MosaicJSON created
7. STAC collection created

---

## 📊 Success Criteria

✅ **Stage 1**: All tiles validated in parallel (verify same CRS, dtype, band count)
✅ **Stage 2**: All tiles converted to COGs in custom output folder
✅ **Stage 3**: MosaicJSON generated with correct tile count and bounds
✅ **Stage 4**: STAC collection created with MosaicJSON asset
✅ **Integration**: Discovery → Submission works end-to-end
✅ **Testing**: Simple grid + real Maxar data both work

---

## 🎯 Timeline Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| **Phase 1** | Dependencies + MosaicJSON service + Job class | 4 hours |
| **Phase 2** | Task handlers + STAC collection | 2 hours |
| **Phase 3** | Registration | 15 minutes |
| **Phase 4** | Testing (unit + integration) | 2 hours |
| **Phase 5** | Discovery integration | 1 hour |
| **Total** | | **~9 hours** |

**Expected Duration**: 1-2 days with deployment and testing

---

## 📝 Deployment Checklist

- [ ] Add `cogeo-mosaic>=7.0.0` to requirements.txt
- [ ] Create `services/raster_mosaicjson.py`
- [ ] Create `services/stac_collection.py`
- [ ] Create `jobs/process_raster_collection.py`
- [ ] Register task handlers in `services/__init__.py`
- [ ] Register job in `jobs/__init__.py`
- [ ] Deploy to Azure: `func azure functionapp publish rmhgeoapibeta --python --build remote`
- [ ] Test with simple 2x2 grid
- [ ] Test with real Maxar delivery
- [ ] Verify MosaicJSON in blob storage
- [ ] Verify STAC collection in PgSTAC
- [ ] Update `docs_claude/TODO.md` with completion
- [ ] Update `docs_claude/HISTORY.md` with results

---

## 🔗 Related Documentation

- **Vendor Discovery**: `MOSAICJSON_IMPLEMENTATION_PLAN.md` (this file)
- **Multi-Tier COG**: `docs_claude/TODO.md` (Phase 1 complete)
- **STAC Integration**: `docs_claude/ARCHITECTURE_REFERENCE.md`
- **Job Patterns**: `docs_claude/ARCHITECTURE_REFERENCE.md` (Diamond pattern)

---

## 💡 Future Enhancements

**After Initial Implementation**:
- [ ] MosaicJSON visualization endpoint (TiTiler integration)
- [ ] Automatic STAC item linking (individual COGs → collection)
- [ ] Multi-tier MosaicJSON (separate viz/analysis/archive mosaics)
- [ ] MosaicJSON validation endpoint
- [ ] Mosaic statistics (coverage, overlap, gaps)

**Priority**: Low - Core workflow first, enhancements later
