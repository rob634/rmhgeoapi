# H3 Bootstrap Cascade Optimization - Deployment Guide

**Date**: 15 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Ready for Albania Test Deployment

---

## Overview

Redesigned H3 bootstrap job from **7-stage sequential** workflow to **3-stage cascade** architecture with batched parallelism.

**Performance Improvement**:
- OLD: 30+ minutes (timeout failure)
- NEW: <15 minutes (estimated, Albania test will validate)

---

## Architecture Changes

### OLD Architecture (7 Stages - FAILED)
```
Stage 1: Generate res 2 base (~2K cells, 15 min timeout)
Stage 2: Generate res 3 from res 2 (sequential, slow)
Stage 3: Generate res 4 from res 3 (sequential, slow)
Stage 4: Generate res 5 from res 4 (sequential, slow)
Stage 5: Generate res 6 from res 5 (sequential, slow)
Stage 6: Generate res 7 from res 6 (sequential, slow)
Stage 7: Finalize
RESULT: Stage 1 timed out at 30 minutes (Azure Functions limit)
```

### NEW Architecture (3 Stages - OPTIMIZED)
```
Stage 1: Generate filtered res 2 base
  - 1 task
  - ~2K cells for land (10-20 cells for Albania)
  - Estimated: <1 minute (Albania), 5-10 minutes (global land)

Stage 2: Cascade res 2 → res 3,4,5,6,7 (ALL at once!)
  - N parallel tasks (batched fan-out)
  - Each task: cascade_batch_size parent cells
  - Example: 10 parents → 168,070 descendants to res 7
  - Estimated: 5-10 minutes (parallel execution)

Stage 3: Finalize pyramid
  - 1 task
  - Verify cell counts, update metadata
  - Estimated: <1 minute

RESULT: <15 minutes total (within Azure Functions 30min limit)
```

---

## Files Modified

### 1. New Handler: `services/handler_cascade_h3_descendants.py`
**Purpose**: Multi-level cascade (res 2 → res 3,4,5,6,7 in one operation)

**Key Features**:
- Uses H3's `cell_to_children(parent, target_resolution)` for multi-level jumps
- No spatial filtering needed (children inherit parent land membership)
- Batch processing support (LIMIT/OFFSET for parallel tasks)
- Idempotent inserts (ON CONFLICT DO NOTHING)

### 2. Modified Repository: `infrastructure/h3_repository.py`
**Added Method**: `get_parent_cells(parent_grid_id, batch_start, batch_size)`

**Purpose**: Load parent cells with batching for parallel processing

### 3. Modified Job: `jobs/bootstrap_h3_land_grid_pyramid.py`
**Changes**:
- Reduced from 5 stages → 3 stages
- Added parameters: `country_filter`, `bbox_filter`, `cascade_batch_size`, `target_resolutions`
- Stage 2 creates N parallel tasks based on parent count

### 4. Modified Registry: `services/__init__.py`
**Added**: `cascade_h3_descendants` handler registration

---

## New Parameters

### `country_filter` (Optional - For Testing)
- **Type**: String (ISO3 country code)
- **Example**: `"ALB"` (Albania)
- **Purpose**: Filter res 2 base to specific country for testing
- **Default**: `None` (all land)

### `bbox_filter` (Optional - For Testing)
- **Type**: List of floats `[minx, miny, maxx, maxy]`
- **Example**: `[19.3, 39.6, 21.1, 42.7]` (Albania bounding box)
- **Purpose**: Spatial filter for res 2 base generation
- **Default**: `None`

### `cascade_batch_size` (Performance Tuning)
- **Type**: Integer (1-100)
- **Default**: `10`
- **Purpose**: Number of parent cells per cascade task
- **Example**: `10` parents = ~168K descendants to res 7 per task
- **Recommendation**:
  - Testing (Albania): 5-10
  - Production (global land): 10-20

### `target_resolutions` (Customizable Output)
- **Type**: List of integers
- **Default**: `[3, 4, 5, 6, 7]`
- **Purpose**: Which resolutions to generate from res 2 parents
- **Example**: `[3, 4, 5]` for faster testing

---

## Deployment Steps

### 1. Stage Changes and Commit

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi

# Stage all changes
git add services/handler_cascade_h3_descendants.py
git add infrastructure/h3_repository.py
git add jobs/bootstrap_h3_land_grid_pyramid.py
git add services/__init__.py
git add H3_CASCADE_OPTIMIZATION_README.md

# Commit with detailed message
git commit -m "Optimize H3 bootstrap: 7-stage sequential → 3-stage cascade architecture

🏗️ Architecture Changes:
- NEW: 3-stage cascade workflow (base + batched descendants + finalize)
- OLD: 7-stage sequential workflow (TIMEOUT at 30 minutes)
- Performance: <15 minutes (estimated) vs 30+ minutes (failed)

📦 New Files:
- services/handler_cascade_h3_descendants.py (multi-level cascade handler)

🔧 Modified Files:
- jobs/bootstrap_h3_land_grid_pyramid.py (3-stage architecture, Albania test support)
- infrastructure/h3_repository.py (add get_parent_cells with batching)
- services/__init__.py (register cascade_h3_descendants handler)

✨ New Features:
- country_filter parameter (ISO3 code for testing, e.g., \"ALB\")
- bbox_filter parameter (bounding box for spatial filtering)
- cascade_batch_size parameter (tunable parallelism, default: 10)
- target_resolutions parameter (customizable output, default: [3,4,5,6,7])

🔬 Cascade Mathematics:
- 1 res 2 cell → 16,807 descendants to res 7 (7^5)
- 10 res 2 cells → 168,070 descendants to res 7
- 2,000 res 2 cells → 33.6M descendants to res 7

📊 Albania Test Criteria:
- ~10-20 res 2 cells → ~168K res 7 cells
- Success: Complete in <15 minutes with correct parent relationships

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### 2. Push to Git

```bash
# Push to dev branch
git push origin dev
```

### 3. Deploy to Azure Functions

```bash
# Deploy with remote build
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### 4. Redeploy Database Schema (if needed)

```bash
# Redeploy schema to ensure h3.grids table is ready
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"
```

---

## Testing: Albania Test Job

### Step 1: Submit Albania Test Job

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "grid_id_prefix": "test_albania",
    "bbox_filter": [19.3, 39.6, 21.1, 42.7],
    "cascade_batch_size": 5,
    "target_resolutions": [3, 4, 5, 6, 7]
  }'
```

**Expected Response**:
```json
{
  "job_id": "abc123...",
  "status": "queued",
  "job_type": "bootstrap_h3_land_grid_pyramid",
  "parameters": {
    "grid_id_prefix": "test_albania",
    "bbox_filter": [19.3, 39.6, 21.1, 42.7],
    "cascade_batch_size": 5
  }
}
```

### Step 2: Monitor Job Progress

```bash
# Check job status (replace JOB_ID)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}"
```

**Expected Progression**:
1. Stage 1: `processing` → `completed` (<1 minute)
2. Stage 2: `processing` with 2-4 parallel tasks → `completed` (5-10 minutes)
3. Stage 3: `processing` → `completed` (<1 minute)

### Step 3: Validate Results

```sql
-- Connect to PostgreSQL
PGPASSWORD='{db_password}' psql -h rmhpgflex.postgres.database.azure.com -U {db_superuser} -d geopgflex

-- Check res 2 base (should be ~10-20 cells for Albania)
SELECT COUNT(*) FROM h3.grids WHERE grid_id = 'test_albania_res2';

-- Check all resolutions
SELECT resolution, COUNT(*) as cell_count
FROM h3.grids
WHERE grid_id LIKE 'test_albania%'
GROUP BY resolution
ORDER BY resolution;

-- Expected output:
-- resolution | cell_count
-- -----------+-----------
--      2     |     ~15     (Albania res 2 cells)
--      3     |     ~105    (15 × 7)
--      4     |     ~735    (15 × 7²)
--      5     |     ~5,145  (15 × 7³)
--      6     |     ~36,015 (15 × 7⁴)
--      7     |    ~252,105 (15 × 7⁵)

-- Verify parent relationships (CRITICAL - all children must have parents)
SELECT COUNT(*) FROM h3.grids
WHERE grid_id = 'test_albania_res7' AND parent_res2 IS NULL;
-- Expected: 0 (all res 7 cells should have parent_res2 set)

-- Check spatial coverage (should only cover Albania)
SELECT ST_AsText(ST_Envelope(ST_Collect(geom)))
FROM h3.grids
WHERE grid_id = 'test_albania_res2';
-- Expected: Bounding box roughly [19.3, 39.6, 21.1, 42.7]
```

---

## Success Criteria

### ✅ Albania Test PASSES If:

1. **Job Completes Successfully**
   - All 3 stages complete
   - Status: `completed`
   - Total time: <15 minutes

2. **Correct Cell Counts**
   - Res 2: 10-20 cells (Albania base)
   - Res 7: ~168K cells (15 parents × 16,807 descendants)
   - All resolutions present (2, 3, 4, 5, 6, 7)

3. **Parent Relationships Preserved**
   - All res 7 cells have `parent_res2` set
   - No orphan cells (parent_res2 IS NULL count = 0)

4. **Spatial Accuracy**
   - All cells within Albania bounding box
   - No cells outside [19.3, 39.6, 21.1, 42.7]

### ❌ Albania Test FAILS If:

1. **Timeout** (>30 minutes)
2. **Missing resolutions** (e.g., res 7 not generated)
3. **Orphan cells** (parent_res2 IS NULL)
4. **Spatial leakage** (cells outside Albania)
5. **Stage failures** (any stage status = `failed`)

---

## After Albania Success → Production Deployment

### Global Land Grid Job (2,000 parents → 33.6M descendants)

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "grid_id_prefix": "land",
    "spatial_filter_table": "system_admin0",
    "cascade_batch_size": 10,
    "target_resolutions": [3, 4, 5, 6, 7]
  }'
```

**Expected Performance**:
- Stage 1: 5-10 minutes (generate 2K res 2 cells with land filter)
- Stage 2: 10-15 minutes (200 parallel tasks, 10 parents each)
- Stage 3: <1 minute (finalization)
- **Total**: 15-25 minutes (well within 30min limit!)

---

## Rollback Plan (If Test Fails)

### Option 1: Revert to Previous Commit
```bash
git revert HEAD
git push origin dev
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### Option 2: Adjust Batch Size
```bash
# If memory issues, reduce batch size
curl -X POST "..." -d '{"cascade_batch_size": 5, ...}'

# If too slow, increase batch size
curl -X POST "..." -d '{"cascade_batch_size": 20, ...}'
```

### Option 3: Reduce Target Resolutions
```bash
# Test with fewer resolutions first
curl -X POST "..." -d '{"target_resolutions": [3, 4, 5], ...}'
```

---

## Troubleshooting

### Job Stuck at Stage 1 (>5 minutes)
**Possible Cause**: Spatial filtering taking too long
**Solution**: Use bbox_filter instead of spatial_filter_table

### Stage 2 Tasks Failing
**Possible Cause**: Memory limit exceeded
**Solution**: Reduce cascade_batch_size to 5

### Missing Parent Relationships
**Possible Cause**: Cascade handler not setting parent_res2
**Solution**: Check handler_cascade_h3_descendants.py line 237

### Orphan Cells (parent_res2 IS NULL)
**Possible Cause**: ON CONFLICT preventing parent_res2 updates
**Solution**: Check h3_repository.py insert_h3_cells method

---

## Contact

For questions or issues, refer to:
- **Documentation**: `docs_claude/CLAUDE_CONTEXT.md`
- **Job Creation Guide**: `JOB_CREATION_QUICKSTART.md`
- **Architecture**: `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md`

**Author**: Robert and Geospatial Claude Legion
**Date**: 15 NOV 2025
