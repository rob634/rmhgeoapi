# Active Tasks - process_raster_collection Implementation

**Last Updated**: 26 NOV 2025 (UTC)
**Author**: Robert and Geospatial Claude Legion

---

## 🚨 HIGH PRIORITY: Idempotency Fixes for ETL Workflows (25 NOV 2025)

**Status**: 🔴 **PLANNING COMPLETE** - Ready for implementation
**Priority**: **HIGH** - Critical for production reliability
**Impact**: Prevents duplicate data on retry, enables safe job recovery

### Background

Analysis revealed idempotency gaps in three workflows:
- **ingest_vector**: Stage 2 INSERT creates duplicates, Stage 3 STAC items can duplicate
- **process_raster_collection**: Stage 4 pgstac search registration (already has workaround)
- **All workflows**: No failed job recovery mechanism

### 1. FIX: ingest_vector Stage 2 - PostGIS INSERT Idempotency

**Problem**: `upload_pickled_chunk` uses plain INSERT, creating duplicate rows if task retries.

**Location**: `services/vector/postgis_handler.py` lines 707-758

**Current Code** (non-idempotent):
```python
def _insert_features(self, cur, chunk, table_name, schema):
    insert_stmt = sql.SQL("""
        INSERT INTO {schema}.{table} (geom, {cols})
        VALUES (ST_GeomFromText(%s, 4326), {placeholders})
    """)
    for idx, row in chunk.iterrows():
        cur.execute(insert_stmt, values)
```

**Solution Options**:

#### Option A: TRUNCATE + INSERT (Recommended for ingest_vector)
**Rationale**: Stage 2 tasks process distinct chunks; each chunk owns specific rows.

**Implementation**:
```python
def _insert_features_idempotent(
    self,
    cur: psycopg.Cursor,
    chunk: gpd.GeoDataFrame,
    table_name: str,
    schema: str,
    chunk_index: int,
    job_id: str
):
    """
    Idempotent insert: Delete existing rows for this chunk, then INSERT.

    Uses etl_batch_id column (added in GeoTableBuilder) to identify chunk rows.
    Format: {job_id[:8]}-chunk-{chunk_index}
    """
    batch_id = f"{job_id[:8]}-chunk-{chunk_index}"

    # Step 1: Delete any existing rows from this chunk (idempotent cleanup)
    delete_stmt = sql.SQL("""
        DELETE FROM {schema}.{table}
        WHERE etl_batch_id = %s
    """).format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name)
    )
    cur.execute(delete_stmt, (batch_id,))
    deleted_count = cur.rowcount
    if deleted_count > 0:
        logger.info(f"♻️ Idempotency: Deleted {deleted_count} existing rows for batch {batch_id}")

    # Step 2: INSERT new rows with batch_id for tracking
    for idx, row in chunk.iterrows():
        values = [geom_wkt, batch_id] + [row[col] for col in attr_cols]
        cur.execute(insert_stmt, values)
```

**Required Schema Change** (already in GeoTableBuilder):
```sql
-- etl_batch_id column for chunk tracking
ALTER TABLE geo.{table} ADD COLUMN IF NOT EXISTS etl_batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_{table}_etl_batch_id ON geo.{table}(etl_batch_id);
```

#### Option B: UPSERT with Unique Constraint
**For tables with natural keys** (e.g., country codes, admin boundaries):
```python
# Add unique constraint during table creation
ALTER TABLE geo.{table} ADD CONSTRAINT uq_{table}_natural_key UNIQUE (iso3, admin_level);

# Use UPSERT
INSERT INTO geo.{table} (geom, iso3, admin_level, ...)
VALUES (...)
ON CONFLICT (iso3, admin_level) DO UPDATE SET
    geom = EXCLUDED.geom,
    updated_at = NOW();
```

**Task Checklist - ingest_vector Stage 2**:
- [ ] **Step 1**: Add `etl_batch_id` column to `_create_table_if_not_exists()` in `postgis_handler.py`
- [ ] **Step 2**: Modify `_insert_features()` to accept `chunk_index` and `job_id` parameters
- [ ] **Step 3**: Add DELETE before INSERT pattern (DELETE WHERE etl_batch_id = ...)
- [ ] **Step 4**: Update `insert_features_only()` to pass chunk metadata
- [ ] **Step 5**: Update `upload_pickled_chunk()` in `services/vector/tasks.py` to pass chunk_index and job_id
- [ ] **Step 6**: Test with duplicate task execution
- [ ] **Commit**: "Fix: ingest_vector Stage 2 idempotency via DELETE+INSERT pattern"

**Files to Modify**:
| File | Changes |
|------|---------|
| `services/vector/postgis_handler.py` | Add etl_batch_id to schema, DELETE+INSERT pattern |
| `services/vector/tasks.py` | Pass job_id and chunk_index to handler |
| `jobs/ingest_vector.py` | Ensure job_id in Stage 2 task parameters |

---

### 2. FIX: ingest_vector Stage 3 - STAC Item Idempotency

**Problem**: `create_vector_stac` may create duplicate STAC items if retried.

**Location**: `services/stac_vector_catalog.py` lines 111-128

**Current Code** (already has partial fix):
```python
# Check if item already exists (idempotency)
if stac_infra.item_exists(item.id, collection_id):
    logger.info(f"⏭️ STEP 2: Item {item.id} already exists...")
    insert_result = {'success': True, 'skipped': True}
else:
    insert_result = stac_infra.insert_item(item, collection_id)
```

**Status**: ✅ **ALREADY IMPLEMENTED** - Code review confirms idempotency check exists.

**Verification**:
- [ ] Confirm `item_exists()` uses correct collection_id
- [ ] Confirm item_id generation is deterministic (table name based)
- [ ] Test by running Stage 3 twice with same parameters

---

### 3. FIX: process_raster_collection Stage 4 - pgstac Search Registration

**Problem**: Search registration may create duplicates on retry.

**Location**: `services/pgstac_search_registration.py` lines 214-239

**Current Code** (already has workaround):
```python
# Step 1: Check if search already exists using Python-computed hash
cur.execute("SELECT hash FROM pgstac.searches WHERE hash = %s", (search_hash,))
existing = cur.fetchone()

if existing:
    # UPDATE existing (idempotent)
    cur.execute("UPDATE pgstac.searches SET lastused = NOW() WHERE hash = %s", (search_hash,))
else:
    # INSERT new
    cur.execute("INSERT INTO pgstac.searches ...")
```

**Status**: ✅ **ALREADY IMPLEMENTED** - SELECT-then-INSERT/UPDATE pattern is idempotent.

**Verification**:
- [ ] Confirm search_hash computation is deterministic
- [ ] Test by calling `register_search()` twice with same parameters

---

### 4. NEW: Failed Job Recovery & Cleanup Workflow

**Problem**: Failed jobs cannot be retried; intermediate artifacts persist.

**Current Behavior**:
```
Submit job → job_id = ABC, status = QUEUED
Processing fails → status = FAILED
Resubmit identical params → Returns {"status": "failed", "idempotent": true}
                          → NO retry, NO cleanup
```

**Solution**: Two-part system:
1. **Retry endpoint**: Force retry of failed jobs
2. **Cleanup handler**: Remove intermediate artifacts from failed jobs

#### 4.1 Retry Failed Job Endpoint

**New Endpoint**: `POST /api/jobs/retry/{job_id}?confirm=yes`

**File**: `triggers/job_retry.py` (NEW FILE)

```python
"""
Job Retry Trigger

Allows retrying failed jobs by:
1. Cleaning up intermediate artifacts
2. Resetting job status to QUEUED
3. Re-queueing to Service Bus

Endpoint: POST /api/jobs/retry/{job_id}?confirm=yes
"""

class JobRetryTrigger:
    """Handle retry requests for failed jobs."""

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Retry a failed job.

        1. Validate job exists and is in FAILED status
        2. Call cleanup handler for job type
        3. Reset job status to QUEUED, clear error fields
        4. Reset all tasks to PENDING
        5. Queue job to Service Bus
        """
        job_id = req.route_params.get('job_id')
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return error_response("Retry requires ?confirm=yes")

        # Get job from database
        job = self.job_repo.get_job(job_id)
        if not job:
            return error_response(f"Job {job_id} not found", 404)

        if job.status.value != 'failed':
            return error_response(f"Job {job_id} is {job.status.value}, not failed", 400)

        # Execute cleanup for this job type
        cleanup_result = self._cleanup_job_artifacts(job)

        # Reset job status
        self.job_repo.update_job_status(
            job_id=job_id,
            status='queued',
            stage=1,
            metadata={'retry_count': (job.metadata.get('retry_count', 0) + 1)}
        )

        # Reset all tasks to pending
        self.job_repo.reset_tasks_for_job(job_id)

        # Queue to Service Bus
        from core.machine import CoreMachine
        core_machine = CoreMachine.instance()
        core_machine.queue_job(job_id, job.job_type, job.parameters)

        return success_response({
            "job_id": job_id,
            "status": "queued",
            "retry_count": job.metadata.get('retry_count', 0) + 1,
            "cleanup_result": cleanup_result,
            "message": f"Job {job_id} has been reset and re-queued"
        })
```

#### 4.2 Cleanup Handlers by Job Type

**File**: `services/job_cleanup.py` (NEW FILE)

```python
"""
Job Cleanup Service

Handles cleanup of intermediate artifacts when jobs fail or are retried.
Each job type registers its own cleanup handler.

Cleanup Operations by Job Type:
- ingest_vector: Delete pickle files, optionally drop PostGIS table
- process_raster: Delete intermediate COG files (if partial)
- process_raster_collection: Delete partial MosaicJSON, partial COGs
"""

from typing import Dict, Any, Callable
from config import get_config
from infrastructure.blob import BlobRepository

# Registry of cleanup handlers
CLEANUP_HANDLERS: Dict[str, Callable[[str, dict], dict]] = {}


def register_cleanup(job_type: str):
    """Decorator to register cleanup handler for job type."""
    def decorator(func):
        CLEANUP_HANDLERS[job_type] = func
        return func
    return decorator


@register_cleanup("ingest_vector")
def cleanup_ingest_vector(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed ingest_vector jobs.

    Artifacts to clean:
    1. Pickle files in blob storage ({container}/{prefix}/{job_id}/*.pkl)
    2. Optionally: PostGIS table (if partially created)
    3. Optionally: STAC item (if Stage 3 partially ran)

    Args:
        job_id: Job ID
        job_params: Original job parameters

    Returns:
        {
            "pickles_deleted": int,
            "table_action": "dropped" | "preserved" | "not_found",
            "stac_item_action": "deleted" | "preserved" | "not_found"
        }
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    # 1. Delete pickle files
    pickle_prefix = f"{config.vector_pickle_prefix}/{job_id}/"
    try:
        deleted = blob_repo.delete_blobs_by_prefix(
            container=config.vector_pickle_container,
            prefix=pickle_prefix
        )
        result["pickles_deleted"] = deleted
        logger.info(f"🗑️ Deleted {deleted} pickle files for job {job_id}")
    except Exception as e:
        result["pickles_deleted"] = 0
        result["pickle_error"] = str(e)

    # 2. Optionally drop PostGIS table
    # Only drop if explicitly requested (default: preserve data for debugging)
    table_name = job_params.get("table_name")
    schema = job_params.get("schema", "geo")
    drop_table = job_params.get("cleanup_drop_table", False)

    if drop_table and table_name:
        try:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(schema),
                            sql.Identifier(table_name)
                        )
                    )
                    conn.commit()
            result["table_action"] = "dropped"
            logger.info(f"🗑️ Dropped table {schema}.{table_name}")
        except Exception as e:
            result["table_action"] = "error"
            result["table_error"] = str(e)
    else:
        result["table_action"] = "preserved"

    # 3. Delete STAC item if exists
    try:
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        stac = PgStacBootstrap()
        item_id = f"{schema}-{table_name}"  # Standard item_id format
        collection_id = job_params.get("collection_id", "system-vectors")

        if stac.item_exists(item_id, collection_id):
            stac.delete_item(item_id, collection_id)
            result["stac_item_action"] = "deleted"
        else:
            result["stac_item_action"] = "not_found"
    except Exception as e:
        result["stac_item_action"] = "error"
        result["stac_error"] = str(e)

    return result


@register_cleanup("process_raster")
def cleanup_process_raster(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed process_raster jobs.

    Artifacts to clean:
    1. Intermediate COG in silver container (if Stage 2 failed mid-upload)
    2. STAC item (if Stage 3 partially ran)
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    # 1. Delete COG blob (if exists)
    blob_name = job_params.get("blob_name", "")
    output_tier = job_params.get("output_tier", "analysis")
    # Derive output blob name (same logic as raster_cog.py)
    base_name = blob_name.rsplit('.', 1)[0]
    cog_blob_name = f"{base_name}_cog_{output_tier}.tif"

    try:
        silver_container = config.storage.silver_cog_container
        if blob_repo.blob_exists(silver_container, cog_blob_name):
            blob_repo.delete_blob(silver_container, cog_blob_name)
            result["cog_action"] = "deleted"
        else:
            result["cog_action"] = "not_found"
    except Exception as e:
        result["cog_action"] = "error"
        result["cog_error"] = str(e)

    # 2. Delete STAC item if exists
    try:
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        stac = PgStacBootstrap()
        collection_id = job_params.get("collection_id")
        item_id = f"{collection_id}-{cog_blob_name.replace('/', '-')}"

        if collection_id and stac.item_exists(item_id, collection_id):
            stac.delete_item(item_id, collection_id)
            result["stac_item_action"] = "deleted"
        else:
            result["stac_item_action"] = "not_found"
    except Exception as e:
        result["stac_item_action"] = "error"

    return result


@register_cleanup("process_raster_collection")
def cleanup_process_raster_collection(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed process_raster_collection jobs.

    Artifacts to clean:
    1. Partial COGs in silver container
    2. MosaicJSON file
    3. STAC collection
    4. pgstac search registration
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    collection_id = job_params.get("collection_id")

    # 1. Delete COGs by prefix
    cog_prefix = f"collections/{collection_id}/"
    try:
        deleted = blob_repo.delete_blobs_by_prefix(
            container=config.storage.silver_cog_container,
            prefix=cog_prefix
        )
        result["cogs_deleted"] = deleted
    except Exception as e:
        result["cogs_deleted"] = 0
        result["cog_error"] = str(e)

    # 2. Delete MosaicJSON
    mosaic_blob = f"mosaics/{collection_id}/mosaic.json"
    try:
        if blob_repo.blob_exists(config.storage.mosaicjson_container, mosaic_blob):
            blob_repo.delete_blob(config.storage.mosaicjson_container, mosaic_blob)
            result["mosaicjson_action"] = "deleted"
        else:
            result["mosaicjson_action"] = "not_found"
    except Exception as e:
        result["mosaicjson_action"] = "error"

    # 3. Delete STAC collection
    try:
        from infrastructure.pgstac_repository import PgStacRepository
        pgstac_repo = PgStacRepository()
        if pgstac_repo.collection_exists(collection_id):
            pgstac_repo.delete_collection(collection_id)  # Cascades to items
            result["stac_collection_action"] = "deleted"
        else:
            result["stac_collection_action"] = "not_found"
    except Exception as e:
        result["stac_collection_action"] = "error"

    # 4. Delete pgstac search registration
    try:
        from services.pgstac_search_registration import PgSTACSearchRegistration
        search_reg = PgSTACSearchRegistration()
        search_reg.delete_search_by_collection(collection_id)
        result["search_registration_action"] = "deleted"
    except Exception as e:
        result["search_registration_action"] = "error"

    return result


def cleanup_job(job_id: str, job_type: str, job_params: dict) -> dict:
    """
    Execute cleanup for a job based on its type.

    Args:
        job_id: Job ID
        job_type: Job type (ingest_vector, process_raster, etc.)
        job_params: Original job parameters

    Returns:
        Cleanup result dict
    """
    handler = CLEANUP_HANDLERS.get(job_type)
    if handler:
        return handler(job_id, job_params)
    else:
        return {
            "job_id": job_id,
            "job_type": job_type,
            "cleanup_action": "no_handler",
            "message": f"No cleanup handler registered for job type: {job_type}"
        }
```

#### 4.3 Cleanup Endpoint (Standalone)

**New Endpoint**: `POST /api/jobs/cleanup/{job_id}?confirm=yes`

For cleaning up artifacts without retrying:

```python
def handle_cleanup_request(self, req: func.HttpRequest) -> func.HttpResponse:
    """
    Cleanup artifacts from a failed job WITHOUT retrying.

    Use cases:
    - Job failed due to bad input data (no point retrying)
    - Manual cleanup before data correction
    - Freeing up storage from abandoned jobs
    """
    job_id = req.route_params.get('job_id')
    confirm = req.params.get('confirm')

    if confirm != 'yes':
        return error_response("Cleanup requires ?confirm=yes")

    job = self.job_repo.get_job(job_id)
    if not job:
        return error_response(f"Job {job_id} not found", 404)

    # Execute cleanup
    cleanup_result = cleanup_job(job_id, job.job_type, job.parameters)

    # Mark job as cleaned (optional metadata field)
    self.job_repo.update_job_metadata(job_id, {
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
        "cleanup_result": cleanup_result
    })

    return success_response({
        "job_id": job_id,
        "job_type": job.job_type,
        "job_status": job.status.value,
        "cleanup_result": cleanup_result,
        "message": f"Cleanup completed for job {job_id}"
    })
```

**Task Checklist - Job Retry & Cleanup**:
- [ ] **Step 1**: Create `services/job_cleanup.py` with cleanup handlers registry
- [ ] **Step 2**: Implement `cleanup_ingest_vector()` handler
- [ ] **Step 3**: Implement `cleanup_process_raster()` handler
- [ ] **Step 4**: Implement `cleanup_process_raster_collection()` handler
- [ ] **Step 5**: Create `triggers/job_retry.py` with retry endpoint
- [ ] **Step 6**: Add `POST /api/jobs/retry/{job_id}` route to `function_app.py`
- [ ] **Step 7**: Add `POST /api/jobs/cleanup/{job_id}` route to `function_app.py`
- [ ] **Step 8**: Add `reset_tasks_for_job()` method to PostgreSQLRepository
- [ ] **Step 9**: Add `delete_blobs_by_prefix()` method to BlobRepository
- [ ] **Step 10**: Add `delete_item()` and `delete_collection()` to PgStacBootstrap
- [ ] **Step 11**: Add `delete_search_by_collection()` to PgSTACSearchRegistration
- [ ] **Step 12**: Test retry flow end-to-end
- [ ] **Step 13**: Test cleanup flow end-to-end
- [ ] **Commit**: "Add job retry and cleanup workflow for failed jobs"

**New Files**:
| File | Purpose |
|------|---------|
| `services/job_cleanup.py` | Cleanup handlers registry and implementations |
| `triggers/job_retry.py` | HTTP trigger for retry endpoint |

**Files to Modify**:
| File | Changes |
|------|---------|
| `function_app.py` | Add routes for /api/jobs/retry and /api/jobs/cleanup |
| `infrastructure/postgresql.py` | Add `reset_tasks_for_job()` method |
| `infrastructure/blob.py` | Add `delete_blobs_by_prefix()` method |
| `infrastructure/pgstac_bootstrap.py` | Add `delete_item()`, `delete_collection()` methods |
| `services/pgstac_search_registration.py` | Add `delete_search_by_collection()` method |

---

### Summary: Implementation Order

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| 1 | ingest_vector Stage 2 DELETE+INSERT | 2 hours | Prevents duplicate rows |
| 2 | Job cleanup handlers | 3 hours | Enables artifact cleanup |
| 3 | Job retry endpoint | 2 hours | Enables failed job recovery |
| 4 | Verification of existing idempotency | 1 hour | Confirms STAC handlers work |

**Total Estimated Effort**: 8 hours

---

## ✅ RESOLVED: Platform Schema Consolidation & DDH Metadata (26 NOV 2025)

**Status**: ✅ **COMPLETED** on 26 NOV 2025
**Impact**: Simplified configuration, verified DDH → STAC metadata flow

### What Was Done

**1. Platform Schema Consolidation**:
- Removed unused `platform_schema` config field from `config/database_config.py`
- Confirmed `api_requests` table was already in `app` schema (no migration needed)
- Updated documentation in `infrastructure/platform.py` and `core/models/platform.py`
- Fixed `triggers/admin/db_data.py` queries to use correct schema and columns
- Deprecated `orchestration_jobs` endpoints (HTTP 410)

**2. Worker Configuration Optimization**:
- Set `FUNCTIONS_WORKER_PROCESS_COUNT=4` via Azure CLI
- Reduced `maxConcurrentCalls` from 8 to 2 in `host.json`
- Result: 4 workers × 2 calls = 8 concurrent DB connections (was 16)

**3. DDH Metadata Passthrough Verification**:
- Tested `process_raster` job with DDH identifiers (dataset_id, resource_id, version_id, access_level)
- Verified STAC items contain `platform:*` properties with DDH values
- Confirms Platform → CoreMachine → STAC metadata pipeline is operational

**Files Modified**:
- `config/database_config.py`
- `infrastructure/platform.py`
- `core/models/platform.py`
- `triggers/admin/db_data.py`
- `host.json`

**See**: HISTORY.md entry for 26 NOV 2025 for full details.

---

## ✅ RESOLVED: SQL Generator Invalid Index Bug (24 NOV 2025)

**Status**: ✅ **FIXED** on 24 NOV 2025
**Fix Location**: `core/schema/sql_generator.py:478-491`

### What Was Fixed

The `generate_indexes_composed()` method was creating an invalid `idx_api_requests_status` index for the `api_requests` table, which does NOT have a `status` column.

**Fix Applied** (sql_generator.py:479-481):
```python
elif table_name == "api_requests":
    # Platform Layer indexes (added 16 NOV 2025, FIXED 24 NOV 2025)
    # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
    # Status is delegated to CoreMachine job_id lookup
```

Now only valid indexes are generated:
- `idx_api_requests_dataset_id`
- `idx_api_requests_created_at`

---

## 🚨 CRITICAL: JPEG COG Compression Failing in Azure Functions (21 NOV 2025)

**Status**: ❌ **BROKEN** - JPEG compression fails, DEFLATE works fine
**Priority**: **CRITICAL** - Blocks visualization tier COG creation
**Impact**: Cannot create web-optimized COGs for TiTiler streaming

### Problem Description

The `process_raster` job fails at Stage 2 (create_cog) when using `output_tier: "visualization"` (JPEG compression), but succeeds with `output_tier: "analysis"` (DEFLATE compression).

**Error**: `COG_TRANSLATE_FAILED` after ~6 seconds of processing
**Error Classification**: The error occurs in `cog_translate()` call (rio-cogeo library)

### Evidence

| Test | Output Tier | Compression | Result | Duration |
|------|-------------|-------------|--------|----------|
| dctest_v3 | visualization | JPEG | ❌ COG_TRANSLATE_FAILED | ~6 sec |
| dctest_deflate | analysis | DEFLATE | ✅ SUCCESS (127.58 MB) | 9.8 sec |

**Same input file**: dctest.tif (27 MB RGB GeoTIFF, 7777x5030 pixels, uint8)
**Same infrastructure**: Azure Functions B3 tier, same runtime, same deployment

### Root Cause Analysis (Suspected)

1. **GDAL JPEG Driver Issue**: The Azure Functions Python runtime may have a broken or missing libjpeg library linkage with GDAL/rasterio
2. **Memory Allocation Pattern**: JPEG compression may have different memory allocation patterns that fail in the constrained Azure Functions environment
3. **rio-cogeo JPEG Profile Bug**: The JPEG COG profile configuration may be incompatible with rasterio version in Azure

### Technical Context

**Code Location**: `services/raster_cog.py` lines 388-401
```python
# This call fails for JPEG, succeeds for DEFLATE
cog_translate(
    src,                        # Input rasterio dataset
    output_memfile.name,        # Output to MemoryFile
    cog_profile,                # JPEG vs DEFLATE profile
    config=config,
    overview_level=None,
    overview_resampling=overview_resampling_name,
    in_memory=in_memory,
    quiet=False,
)
```

**COG Profile Source**: `rio_cogeo.profiles.cog_profiles` dictionary
- DEFLATE profile: Works ✅
- JPEG profile: Fails ❌

### Workaround (Active)

Use `output_tier: "analysis"` (DEFLATE) instead of `output_tier: "visualization"` (JPEG):
```bash
curl -X POST ".../api/jobs/submit/process_raster" \
  -d '{"blob_name": "image.tif", "container_name": "rmhazuregeobronze", "output_tier": "analysis"}'
```

**Trade-offs**:
- ✅ DEFLATE produces larger files (127 MB vs ~5-10 MB with JPEG for RGB imagery)
- ✅ DEFLATE is lossless (better for analysis)
- ❌ DEFLATE is slower to stream via TiTiler (more bytes to transfer)
- ❌ JPEG compression ratio (97% reduction) unavailable

### Investigation Steps Required

- [ ] **Test JPEG locally**: Run rio-cogeo with JPEG profile on local machine to verify it works outside Azure
- [ ] **Check GDAL drivers**: Add diagnostic to log available GDAL drivers in Azure Functions runtime
  ```python
  from osgeo import gdal
  logger.info(f"GDAL drivers: {[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]}")
  ```
- [ ] **Check libjpeg linkage**: Verify JPEG driver is properly linked
  ```python
  import rasterio
  logger.info(f"Rasterio GDAL version: {rasterio.gdal_version()}")
  driver = rasterio.drivers.env.get('JPEG')
  ```
- [ ] **Test explicit JPEG driver**: Try creating JPEG COG with explicit driver specification
- [ ] **Check Azure Functions base image**: Determine if Python 3.12 runtime image has JPEG support
- [ ] **Review rio-cogeo GitHub issues**: Search for known JPEG issues in cloud environments
- [ ] **Add detailed error logging**: Capture the actual exception message from cog_translate()

### Fix Options (Once Root Cause Identified)

1. **If missing driver**: Add GDAL JPEG driver to requirements or use custom Docker image
2. **If memory issue**: Reduce JPEG quality or process smaller tiles
3. **If rio-cogeo bug**: Pin to specific version or patch the library
4. **If unfixable**: Document limitation and recommend DEFLATE for all tiers

### Related Config Issue Fixed (Same Session)

**Root Cause Found**: Missing `raster_cog_in_memory` legacy property in `config/app_config.py`

**Fix Applied**: Added three missing legacy properties:
```python
@property
def raster_cog_in_memory(self) -> bool:
    return self.raster.cog_in_memory

@property
def raster_target_crs(self) -> str:
    return self.raster.target_crs

@property
def raster_mosaicjson_maxzoom(self) -> int:
    return self.raster.mosaicjson_maxzoom
```

This fix was required after the config.py → config/ package migration (20 NOV 2025).

---

## ✅ STAC API Fixed & Validated (19 NOV 2025)

**Status**: **RESOLVED** - STAC API fully operational with live data
**Achievement**: Complete end-to-end validation from raster upload to browser visualization
**Completion**: 20 NOV 2025 00:40 UTC

### What Was Fixed

**Root Cause**: Tuple/dict confusion in pgSTAC query functions
- `infrastructure/pgstac_bootstrap.py:1191` - `get_collection_items()` using `result[0]` instead of `result['jsonb_build_object']`
- `infrastructure/pgstac_bootstrap.py:1291` - `search_items()` using same incorrect pattern

**Fix Applied**: Changed from tuple indexing to dictionary key access with RealDictCursor

**Validation Results**:
- ✅ Deployed to Azure Functions (20 NOV 2025 00:08:28 UTC)
- ✅ Schema redeployment: app + pgSTAC 0.9.8
- ✅ Live test: process_raster job with dctest.tif (27 MB → 127.6 MB COG)
- ✅ STAC API endpoints working: `/api/stac/collections` and `/api/stac/collections/{id}/items`
- ✅ TiTiler URLs present in STAC items using `/vsiaz/silver-cogs/` pattern
- ✅ **USER CONFIRMED**: TiTiler interactive map working in browser

### Database State

**pgSTAC** (pgstac schema):
- Version: 0.9.8 with 22 tables
- Collections: 1 (`dctest_validation_19nov2025`)
- Items: 1 (`dctest_validation_19nov2025-dctest_cog_analysis-tif`)
- Search hash functions: `search_tohash`, `search_hash`, `search_fromhash` all present
- GENERATED hash column: Working correctly

**CoreMachine** (app schema):
- Jobs: process_raster job completed in 25 seconds
- Tasks: All 3 stages completed successfully

---

## ✅ COMPLETED - Refactor config.py God Object (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025
**Restore Point**: Commit `f765f58` (pre-deletion backup)
**Purpose**: Split 1,747-line config.py into domain-specific modules
**Achievement**: 10 clean, focused modules instead of 1 monolithic file

### What Was Done

**Phase 1-3**: Created new `config/` package with domain-specific modules:
- ✅ `config/__init__.py` - Exports and singleton pattern
- ✅ `config/app_config.py` - Main composition class with legacy properties
- ✅ `config/storage_config.py` - COG tiers, multi-account storage
- ✅ `config/database_config.py` - PostgreSQL/PostGIS configuration
- ✅ `config/raster_config.py` - Raster pipeline settings
- ✅ `config/vector_config.py` - Vector pipeline settings
- ✅ `config/queue_config.py` - Service Bus queue configuration
- ✅ `config/h3_config.py` - H3 hexagonal grid configuration
- ✅ `config/stac_config.py` - STAC metadata configuration
- ✅ `config/validation.py` - Configuration validators

**Phase 4**: Deleted old `config.py` (25 NOV 2025)
- All imports now use `config/` package
- Legacy properties in `app_config.py` maintained for backward compatibility
- Production deployment verified: health check passing

### Results

| Metric | Before | After |
|--------|--------|-------|
| **AppConfig size** | 1,090 lines (63+ fields) | 150 lines (5 composed configs) |
| **Find raster setting** | Search 1,747 lines | Look in config/raster_config.py |
| **Test raster code** | Mock all 63+ fields | Only mock RasterConfig |
| **Merge conflicts** | High | Low (different files per domain) |

### Deployment Verified
```bash
# 25 NOV 2025 - Post-deletion verification
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
# ✅ Status: healthy
```

---

## 🎯 CURRENT PRIORITY - process_raster_collection Job

**Status**: Ready to implement
**Purpose**: Multi-raster collection processing with TiTiler search URLs

### Analysis (18 NOV 2025 03:50 UTC)

**The Sequence**:
1. `stac_collection.py:326` → `PgStacRepository().insert_collection()` ✅ Succeeds
2. `stac_collection.py:335` → `PgStacInfrastructure().collection_exists()` ❌ Returns False
3. Code raises: "Collection not found in PgSTAC after insertion"

**The Problem**:
- `PgStacRepository` and `PgStacInfrastructure` both create **separate** `PostgreSQLRepository` instances
- Each instance = separate connection context
- INSERT commits on Connection A, SELECT queries on Connection B
- Possible transaction isolation or connection pooling visibility issue

### Immediate Fix Required

**Quick Fix** (services/stac_collection.py lines 325-341):
```python
# BEFORE (current broken pattern):
pgstac_id = _insert_into_pgstac_collections(collection_dict)  # Creates PgStacRepository
stac_service = StacMetadataService()  # Creates PgStacInfrastructure
if not stac_service.stac.collection_exists(collection_id):  # Different connection!
    raise RuntimeError("Collection not found...")

# AFTER (single repository instance):
repo = PgStacRepository()  # Create ONCE
collection = Collection.from_dict(collection_dict)
pgstac_id = repo.insert_collection(collection)  # Use it for insert
if not repo.collection_exists(collection_id):  # Use SAME instance for verification
    raise RuntimeError("Collection not found...")
```

### Long-Term Architectural Fix - Consolidate PgSTAC Classes

**Current Duplication** (18 NOV 2025 analysis):

| Class | Lines | Purpose | Issues |
|-------|-------|---------|--------|
| **PgStacRepository** | 390 | Collections/Items CRUD | ✅ Clean, focused, newer (12 NOV) |
| **PgStacInfrastructure** | 2,060 | Setup + Operations + Queries | ❌ Bloated, duplicates PgStacRepository methods |

**Duplicate Methods Found**:
- `collection_exists()` - **THREE copies** (PgStacRepository:214, PgStacInfrastructure:802, PgStacInfrastructure:943)
- `insert_item()` - **TWO copies** (PgStacRepository:247, PgStacInfrastructure:880)

**Root Cause**: PgStacInfrastructure was created first (4 OCT), PgStacRepository added later (12 NOV) but old methods never removed

### Refactoring Plan - Rename & Consolidate

**Step 1: Rename PgStacInfrastructure → PgStacBootstrap**
- Clarifies purpose: schema setup, installation, verification
- Filename: `infrastructure/stac.py` → `infrastructure/pgstac_bootstrap.py`
- Class: `PgStacInfrastructure` → `PgStacBootstrap`

**Step 2: Move ALL Data Operations to PgStacRepository**

**PgStacBootstrap** (setup/installation ONLY):
- ✅ Keep: `check_installation()`, `install_pgstac()`, `verify_installation()`, `_drop_pgstac_schema()`, `_run_pypgstac_migrate()`
- ✅ Keep: Standalone query functions for admin/diagnostics (`get_collection()`, `get_collection_items()`, `search_items()`, etc.)
- ❌ Remove: `collection_exists()` (duplicate)
- ❌ Remove: `item_exists()` (duplicate)
- ❌ Remove: `insert_item()` (duplicate)
- ❌ Remove: `create_collection()` (data operation, not setup)

**PgStacRepository** (ALL data operations):
- ✅ Keep: All existing methods (`insert_collection()`, `update_collection_metadata()`, `collection_exists()`, `insert_item()`, `get_collection()`, `list_collections()`)
- ➕ Add: `bulk_insert_items()` (move from PgStacBootstrap)
- ➕ Add: `item_exists()` (if not already present)

**Step 3: Update All Imports**
- Search codebase for `from infrastructure.stac import PgStacInfrastructure`
- Replace with `from infrastructure.pgstac_repository import PgStacRepository` where data operations are used
- Replace with `from infrastructure.pgstac_bootstrap import PgStacBootstrap` where setup/admin functions are used

**Step 4: Fix StacMetadataService**
- Change `self.stac = PgStacInfrastructure()` to `self.stac = PgStacRepository()`
- This ensures single repository pattern throughout

### Task Breakdown

- [ ] **CRITICAL**: Implement quick fix in stac_collection.py (single repository instance)
- [ ] Test quick fix with new job submission
- [ ] Rename infrastructure/stac.py → infrastructure/pgstac_bootstrap.py
- [ ] Rename class PgStacInfrastructure → PgStacBootstrap
- [ ] Remove duplicate methods from PgStacBootstrap (collection_exists, insert_item, item_exists, create_collection)
- [ ] Add bulk_insert_items to PgStacRepository (if needed)
- [ ] Update all imports (search for PgStacInfrastructure, replace appropriately)
- [ ] Fix StacMetadataService to use PgStacRepository
- [ ] Test end-to-end STAC collection creation
- [ ] Update documentation (FILE_CATALOG.md, ARCHITECTURE_REFERENCE.md)
- [ ] Commit: "Consolidate PgSTAC: Rename to Bootstrap, eliminate duplication"

### Expected Benefits

1. ✅ **Fixes "Collection not found" error** - single repository instance eliminates READ AFTER WRITE issue
2. ✅ **Eliminates duplication** - removes 3 duplicate method implementations
3. ✅ **Clearer architecture** - PgStacBootstrap = setup, PgStacRepository = data operations
4. ✅ **Easier maintenance** - no more confusion about which class to use
5. ✅ **Better testability** - single repository pattern easier to mock

---

## ✅ RESOLVED - STAC Metadata Encapsulation (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025
**Purpose**: Standardized approach for adding custom metadata to STAC collections and items
**Achievement**: Centralized metadata enrichment with ~375 lines of duplicate code eliminated

### What Was Implemented

**Created New Files**:
- `services/iso3_attribution.py` (~300 lines) - Standalone ISO3 country code attribution service
- `services/stac_metadata_helper.py` (~550 lines) - Main helper class with dataclasses

**Key Classes Created**:

```python
# services/iso3_attribution.py
@dataclass
class ISO3Attribution:
    iso3_codes: List[str]
    primary_iso3: Optional[str]
    countries: List[str]
    attribution_method: Optional[str]  # 'centroid' or 'first_intersect'
    available: bool

class ISO3AttributionService:
    def get_attribution_for_bbox(bbox: List[float]) -> ISO3Attribution
    def get_attribution_for_geometry(geometry: Dict) -> ISO3Attribution

# services/stac_metadata_helper.py
@dataclass
class PlatformMetadata:
    dataset_id: Optional[str]
    resource_id: Optional[str]
    version_id: Optional[str]
    request_id: Optional[str]
    access_level: Optional[str]
    client_id: str = 'ddh'

    @classmethod
    def from_job_params(cls, params: Dict) -> Optional['PlatformMetadata']
    def to_stac_properties(self) -> Dict[str, Any]  # Returns platform:* prefixed dict

@dataclass
class AppMetadata:
    job_id: Optional[str]
    job_type: Optional[str]
    created_by: str = 'rmhazuregeoapi'
    processing_timestamp: Optional[str]

    def to_stac_properties(self) -> Dict[str, Any]  # Returns app:* prefixed dict

class STACMetadataHelper:
    def augment_item(item_dict, bbox, container, blob_name, platform, app,
                     include_iso3=True, include_titiler=True) -> Dict
    def augment_collection(collection_dict, bbox, platform, app,
                          include_iso3=True, register_search=True) -> Tuple[Dict, VisualizationMetadata]
```

**Files Modified**:

| File | Changes |
|------|---------|
| `services/__init__.py` | Added exports for new classes |
| `services/service_stac_metadata.py` | Added `platform_meta`, `app_meta` params; replaced inline ISO3 code with helper (~190 lines removed) |
| `services/service_stac_vector.py` | Added `platform_meta`, `app_meta` params; replaced inline ISO3 code with helper (~175 lines removed) |
| `services/stac_collection.py` | Added ISO3 attribution to collection `extra_fields` |

### Property Namespaces Implemented

| Namespace | Purpose | Example Properties |
|-----------|---------|-------------------|
| `platform:*` | DDH platform identifiers | `platform:dataset_id`, `platform:resource_id`, `platform:version_id` |
| `app:*` | Application/job linkage | `app:job_id`, `app:job_type`, `app:created_by` |
| `geo:*` | Geographic attribution | `geo:iso3`, `geo:primary_iso3`, `geo:countries` |
| `azure:*` | Azure storage provenance | `azure:source_container`, `azure:source_blob` (existing) |

### Usage Example

```python
from services import STACMetadataHelper, PlatformMetadata, AppMetadata

# Extract metadata from job parameters
platform_meta = PlatformMetadata.from_job_params(job_params)
app_meta = AppMetadata(job_id=job_id, job_type='process_raster')

# Augment STAC item
helper = STACMetadataHelper()
item_dict = helper.augment_item(
    item_dict=item_dict,
    bbox=bbox,
    container='rmhazuregeobronze',
    blob_name='test.tif',
    platform=platform_meta,
    app=app_meta,
    include_iso3=True,
    include_titiler=True
)
```

### Benefits

1. ✅ **DRY Code**: Eliminated ~375 lines of duplicated ISO3 attribution code
2. ✅ **Type Safety**: Dataclasses with factory methods prevent parameter errors
3. ✅ **Consistent Namespacing**: All metadata uses standardized prefixes
4. ✅ **Job Linkage**: Every STAC item now links back to its creating job via `app:job_id`
5. ✅ **Graceful Degradation**: Non-critical metadata failures don't block STAC creation
6. ✅ **Extensible**: Easy to add new metadata categories

### Related Bug Fix (25 NOV 2025)

**Issue**: TiTiler URLs were missing from STAC API responses at `/api/stac/collections/{id}`
**Root Cause**: `stac_api/service.py` was OVERWRITING `links[]` with standard STAC links
**Fix Applied**: Modified to preserve existing custom links (TiTiler preview/tilejson/tiles) by merging:
```python
# FIX (25 NOV 2025): Preserve TiTiler links stored in pgstac database
existing_links = response.get('links', [])
standard_rels = {'self', 'items', 'parent', 'root'}
custom_links = [link for link in existing_links if link.get('rel') not in standard_rels]
response['links'] = standard_links + custom_links
```

---

## ✅ RESOLVED - pgSTAC search_tohash() Function Failure (25 NOV 2025)

**Status**: ✅ **RESOLVED** - Workaround implemented + full-rebuild available
**Resolution Date**: 25 NOV 2025
**Documentation**: See `services/pgstac_search_registration.py` module docstring for full details

### Problem Summary

**Error**: `function search_tohash(jsonb) does not exist`
**Context**: Occurred when using `ON CONFLICT (hash)` with pgstac.searches GENERATED column

### Root Cause

The pgstac.searches table has a GENERATED column:
```sql
hash TEXT GENERATED ALWAYS AS (search_hash(search, metadata))
```

When using `ON CONFLICT (hash)`, PostgreSQL's query planner "inlines" the GENERATED column
expression during conflict detection. This caused it to look for `search_tohash(jsonb)` with
1 argument, but the function was defined as `search_tohash(jsonb, jsonb)` with 2 arguments.

### Resolution

**Two-Part Fix:**

1. **Workaround Implemented** (`services/pgstac_search_registration.py`):
   - Uses SELECT-then-INSERT/UPDATE pattern instead of UPSERT
   - Avoids `ON CONFLICT (hash)` entirely (the only operation that triggers the bug)
   - Computes hash in Python, uses it for lookup, then INSERT or UPDATE separately

2. **Root Cause Fix Available** (`/api/dbadmin/maintenance/full-rebuild?confirm=yes`):
   - `DROP SCHEMA pgstac CASCADE` + fresh `pypgstac migrate`
   - Creates functions with correct signatures
   - After clean rebuild, workaround is technically unnecessary but kept as defensive programming

### Verification Query

```sql
SELECT p.proname, pg_get_function_arguments(p.oid)
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'pgstac'
AND p.proname IN ('search_tohash', 'search_hash');

-- Expected (correct after full-rebuild):
--   search_hash    | search jsonb, metadata jsonb
--   search_tohash  | search jsonb                   <- 1 argument
```

---

## ✅ RESOLVED - Fix STAC Collection Description Validation Error (25 NOV 2025)

**Status**: ✅ **FIXED** in code
**Fix Location**: `services/stac_collection.py:110-112`
**Resolution**: Default description provided: `f"Raster collection: {collection_id}"`

### Problem Summary

**Error**: `None is not of type 'string'`
**Context**: STAC 1.1.0 collection validation fails on `description` field
**Impact**: `process_large_raster` Stage 5 (STAC creation) fails; Stages 1-4 complete successfully

### Fix Applied

**File**: `services/stac_collection.py:110-112`
```python
# FIX (25 NOV 2025): Provide default description to satisfy STAC 1.1.0 validation
description = job_parameters.get("collection_description") or params.get("description") or f"Raster collection: {collection_id}"
```

---

## 🚨 CRITICAL NEXT WORK - Repository Pattern Enforcement (16 NOV 2025)

**Purpose**: Eliminate all direct database connections, enforce repository pattern
**Status**: 🟡 **IN PROGRESS** - Managed identity operational, service files remain
**Priority**: **HIGH** - Complete repository pattern migration for maintainability
**Root Cause**: 5+ service files bypass PostgreSQLRepository, directly manage connections

**✅ Managed Identity Status**: Operational in production (15 NOV 2025)
**📘 Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for setup guide

### Architecture Violation

**Current Broken Pattern**:
```python
# ❌ VIOLATES REPOSITORY PATTERN
from config import get_postgres_connection_string
conn_str = get_postgres_connection_string()  # Creates repo, throws it away
with psycopg.connect(conn_str) as conn:      # Manages connection directly
    cur.execute("SELECT ...")                 # Bypasses repository
```

**Problems**:
1. PostgreSQLRepository created just to extract connection string
2. Connection management scattered across 10+ files
3. Can't centralize: pooling, retry logic, monitoring, token refresh
4. Violates single responsibility - repository should manage connections
5. Makes testing harder - can't mock repository

**Correct Pattern**:
```python
# ✅ REPOSITORY PATTERN - ONLY ALLOWED PATTERN
from infrastructure.postgresql import PostgreSQLRepository

# Option 1: Use repository methods (PREFERRED)
repo = PostgreSQLRepository()
job = repo.get_job(job_id)  # Repository manages connection internally

# Option 2: Raw SQL via repository connection manager (ALLOWED)
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...")
```

---

## CRITICAL ETL FILES - IMMEDIATE REFACTORING REQUIRED

### Priority 1: Schema Management (BLOCKING SCHEMA REDEPLOY)

**1. triggers/schema_pydantic_deploy.py** (lines 283-287)
- **Current**: `get_postgres_connection_string()` + `psycopg.connect()`
- **Fix**: Use `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema deployment failing (36 statements fail due to "already exists")
- **Blocking**: YES - prevents nuke operation

**2. triggers/db_query.py** (lines 139-141, 1017-1019)
- **Current**: `DatabaseQueryTrigger._get_database_connection()` builds connection directly
- **Fix**: Make `_get_database_connection()` use `PostgreSQLRepository._get_connection()`
- **Impact**: All database query endpoints + nuke operation broken
- **Blocking**: YES - nuke returns 0 objects dropped

**3. core/schema/deployer.py** (lines 102-103)
- **Current**: `SchemaManager._build_connection_string()` returns connection string
- **Fix**: Replace with `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema management utilities broken
- **Blocking**: YES - used by nuke operation

**4. infrastructure/postgis.py** (lines 57-71)
- **Current**: `check_table_exists()` uses `get_postgres_connection_string()`
- **Fix**: Create `PostgreSQLRepository`, use `_get_connection()`
- **Impact**: Table existence checks (used in validation)
- **Blocking**: NO - but needed for production readiness

---

### Priority 2: STAC Metadata Pipeline (CORE ETL)

**5. infrastructure/stac.py** (10+ direct connections)
- **Lines**: 1082-1083, 1140-1141, 1193-1194, 1283-1284, 1498-1499, 1620-1621, 1746-1747, 1816-1817, 1898-1899, 2000-2001
- **Current**: Every function creates connection via `get_postgres_connection_string()`
- **Fix**: Create `PgSTACRepository` class that wraps pgstac operations
- **Impact**: ALL STAC operations (collections, items, search)
- **Blocking**: YES - STAC is core metadata layer

**6. services/stac_collection.py** (line 617-620)
- **Current**: Uses `get_postgres_connection_string()` for pgstac operations
- **Fix**: Use `PgSTACRepository` (after creating it from #5)
- **Impact**: STAC collection creation
- **Blocking**: YES - needed for dataset ingestion

**7. services/service_stac_vector.py** (lines 181-183)
- **Current**: Direct connection for vector → STAC ingestion
- **Fix**: Use `PgSTACRepository`
- **Impact**: Vector data STAC indexing
- **Blocking**: YES - core ETL pipeline

**8. services/service_stac_setup.py** (lines 56-57)
- **Current**: `get_connection_string()` wrapper around `get_postgres_connection_string()`
- **Fix**: Delete function, use `PgSTACRepository`
- **Impact**: pgstac installation
- **Blocking**: NO - setup only

---

### Priority 3: Vector Ingestion Handlers

**9. services/vector/postgis_handler.py** (lines 55-59)
- **Current**: Stores `self.conn_string` in constructor, creates connections in methods
- **Fix**: Store `self.repo = PostgreSQLRepository()`, use `repo._get_connection()`
- **Impact**: Vector data ingestion to PostGIS
- **Blocking**: YES - primary ingestion path

**10. services/vector/postgis_handler_enhanced.py** (lines 88-92)
- **Current**: Same pattern as postgis_handler.py
- **Fix**: Same fix - use repository
- **Impact**: Enhanced vector ingestion
- **Blocking**: YES - used for complex vector datasets

---

## IMPLEMENTATION STEPS

### Step 1: Fix PostgreSQLRepository (✅ COMPLETED - 16 NOV 2025)
- [x] Remove fallback logic (no password fallback) - DONE
- [x] Use environment variable `MANAGED_IDENTITY_NAME` with fallback to `WEBSITE_SITE_NAME`
- [x] Environment variable set in Azure: `MANAGED_IDENTITY_NAME=rmhazuregeoapi`
- [x] NO fallbacks - fails immediately if token acquisition fails
- [x] **PostgreSQL user `rmhazuregeoapi` created** - Operational in production (15 NOV 2025)

### Step 2: Create PgSTACRepository Class (NEW)
**File**: `infrastructure/pgstac_repository.py` (refactor existing)
```python
class PgSTACRepository:
    """Repository for pgstac operations - wraps all STAC database operations."""

    def __init__(self):
        self.repo = PostgreSQLRepository()  # Delegate to PostgreSQL repo

    def list_collections(self) -> List[Dict]:
        with self.repo._get_connection() as conn:
            # pgstac collection listing logic

    def get_collection(self, collection_id: str) -> Dict:
        with self.repo._get_connection() as conn:
            # pgstac collection retrieval logic

    # ... all other pgstac operations
```

### Step 3: Fix Schema Management Files (COMPLETED - 16 NOV 2025)
1. ✅ **triggers/schema_pydantic_deploy.py**:
   ```python
   # OLD
   from config import get_postgres_connection_string
   conn_string = get_postgres_connection_string()
   conn = psycopg.connect(conn_string)

   # NEW
   from infrastructure.postgresql import PostgreSQLRepository
   repo = PostgreSQLRepository()
   with repo._get_connection() as conn:
       # Execute schema statements
   ```

2. ✅ **triggers/db_query.py**:
   ```python
   # OLD
   def _get_database_connection(self):
       from config import get_postgres_connection_string
       conn_str = get_postgres_connection_string()
       return psycopg.connect(conn_str)

   # NEW
   def _get_database_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()  # Returns context manager
   ```

3. ✅ **core/schema/deployer.py**:
   ```python
   # OLD
   def _build_connection_string(self) -> str:
       from config import get_postgres_connection_string
       return get_postgres_connection_string()

   # NEW
   def _get_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()
   ```

### Step 4: Migrate STAC Files to PgSTACRepository
- Update `infrastructure/stac.py` to use `PgSTACRepository` methods
- Update `services/stac_collection.py`
- Update `services/service_stac_vector.py`

### Step 5: Fix Vector Handlers
- Update `services/vector/postgis_handler.py`
- Update `services/vector/postgis_handler_enhanced.py`

### Step 6: Delete get_postgres_connection_string() Helper
**File**: `config.py` (line 1666-1747)
- **After all files migrated**, delete the helper function
- This enforces repository pattern at compile time

### Step 7: Deploy and Test
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test schema redeploy (should work 100%)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# Test STAC
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections"

# Test OGC Features
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections"
```

---

## NOT TOUCHING (Lower Priority)

### H3 Grid System (not core ETL)
- `services/handler_h3_native_streaming.py` - Can refactor later
- `services/handler_create_h3_stac.py` - Can refactor later

### OGC Features API (separate module)
- `ogc_features/config.py` - Already standalone, can refactor later

---

## ✅ MANAGED IDENTITY - USER-ASSIGNED PATTERN (22 NOV 2025)

**Status**: ✅ Configured with automatic credential detection
**Architecture**: User-assigned identity `rmhpgflexadmin` for read/write/admin database access
**Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for complete setup guide

### Authentication Priority Chain (NEW - 22 NOV 2025)

The system automatically detects and uses credentials in this order:

1. **User-Assigned Managed Identity** - If `MANAGED_IDENTITY_CLIENT_ID` is set
2. **System-Assigned Managed Identity** - If running in Azure (detected via `WEBSITE_SITE_NAME`)
3. **Password Authentication** - If `POSTGIS_PASSWORD` is set
4. **FAIL** - Clear error message with instructions

This allows the same codebase to work in:
- Azure Functions with user-assigned identity (production - recommended)
- Azure Functions with system-assigned identity (simpler setup)
- Local development with password (developer machines)

### Identity Strategy

**User-Assigned (RECOMMENDED)** - Single identity shared across multiple apps:
- `rmhpgflexadmin` - Read/write/admin access (Function App, etc.)
- `rmhpgflexreader` (future) - Read-only access (TiTiler, OGC/STAC apps)

**Benefits**:
- Single identity for multiple apps (easier to manage)
- Identity persists even if app is deleted
- Can grant permissions before app deployment
- Cleaner separation of concerns

### Environment Variables

```bash
# For User-Assigned Identity (production)
MANAGED_IDENTITY_CLIENT_ID=<client-id>        # From Azure Portal → Managed Identities
MANAGED_IDENTITY_NAME=rmhpgflexadmin          # PostgreSQL user name

# For System-Assigned Identity (auto-detected in Azure)
# No env vars needed - WEBSITE_SITE_NAME is set automatically

# For Local Development
POSTGIS_PASSWORD=<password>                   # Password auth fallback
```

### Azure Setup Required

**1. Create PostgreSQL user for managed identity**:
```sql
-- As Entra admin
SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;

-- Grant on existing tables
GRANT ALL ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;

-- Default for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO rmhpgflexadmin;
-- etc.
```

**2. Assign identity to Function App** (Azure Portal or CLI):
```bash
# Assign existing user-assigned identity
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --identities /subscriptions/{sub}/resourcegroups/rmhazure_rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/rmhpgflexadmin
```

**3. Configure environment variables**:
```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhpgflexadmin \
    MANAGED_IDENTITY_CLIENT_ID=<client-id-from-portal>
```

### Files Updated (22 NOV 2025)
- `config/database_config.py` - Added `managed_identity_client_id` field
- `infrastructure/postgresql.py` - Updated to use user-assigned identity by default

### Previous Production Setup (15 NOV 2025)
- ✅ PostgreSQL user `rmhazuregeoapi` created with pgaadauth
- ✅ All schema permissions granted (app, geo, pgstac, h3)
- ✅ Function App managed identity enabled
- ✅ Environment variable `USE_MANAGED_IDENTITY=true` configured
- ✅ PostgreSQLRepository using ManagedIdentityCredential
- ✅ Token refresh working (automatic hourly rotation)

**For New Environments** (QA/Production):

See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) section "Managed Identity for Database Connections" for complete setup instructions including:
- Azure CLI commands to enable managed identity
- PostgreSQL user creation script
- Environment variable configuration
- Verification steps

**Quick Setup** (for reference):
```bash
# 1. Enable managed identity on Function App
az functionapp identity assign --name <app-name> --resource-group <rg>

# 2. Create PostgreSQL user (as Entra admin)
psql "host=<server>.postgres.database.azure.com dbname=<db> sslmode=require"
SELECT pgaadauth_create_principal('<app-name>', false, false);
# ... grant permissions (see QA_DEPLOYMENT.md)

# 3. Configure Function App
az functionapp config appsettings set --name <app-name> \
  --settings USE_MANAGED_IDENTITY=true
```

---

## Current Status (16 NOV 2025 - 22:25 UTC)

### ✅ COMPLETED - Phase 1: Schema Management (Critical Path)
- ✅ Fixed PostgreSQLRepository:
  - Changed from `DefaultAzureCredential` → `ManagedIdentityCredential` (explicit control)
  - Removed ALL fallback logic (no password fallback)
  - Uses `MANAGED_IDENTITY_NAME` env var (value: `rmhazuregeoapi`)
  - Supports user-assigned identities via `MANAGED_IDENTITY_CLIENT_ID`
  - Fails immediately if token acquisition fails
- ✅ Fixed PostgreSQL ownership (all app schema objects owned by `rmhazuregeoapi`)
- ✅ Refactored 4 critical schema management files:
  - triggers/schema_pydantic_deploy.py
  - triggers/db_query.py
  - core/schema/deployer.py
  - infrastructure/postgis.py
- ✅ Deployed to Azure (16 NOV 2025 20:49 UTC)
- ✅ **VERIFIED WORKING**:
  - Schema redeploy: 100% success (38/38 statements)
  - Nuke operation: Works perfectly
  - Hello world job: Completed successfully
  - Managed identity authentication: Operational

### ✅ COMPLETED - Phase 2A: STAC Infrastructure (16 NOV 2025 23:20 UTC)
- ✅ **infrastructure/stac.py**: Refactored all 9 standalone functions (10 occurrences):
  - get_collection() - Added optional repo parameter
  - get_collection_items() - Added optional repo parameter
  - search_items() - Added optional repo parameter
  - get_schema_info() - Added optional repo parameter
  - get_collection_stats() - Added optional repo parameter
  - get_item_by_id() - Added optional repo parameter
  - get_health_metrics() - Added optional repo parameter
  - get_collections_summary() - Added optional repo parameter
  - get_all_collections() - Added optional repo parameter (removed duplicate, kept better implementation)
- ✅ All functions use repository pattern with dependency injection
- ✅ Backward compatible (repo parameter optional)
- ✅ Compiled successfully (python3 -m py_compile)
- ✅ ZERO remaining `get_postgres_connection_string()` calls in infrastructure/stac.py

### 🔴 REMAINING - Phase 2B: STAC Service Files (NEXT)
- ⏳ services/stac_collection.py
- ⏳ services/service_stac_vector.py
- ⏳ services/service_stac_setup.py
- ⏳ services/vector/postgis_handler.py
- ⏳ services/vector/postgis_handler_enhanced.py

### 📋 NEXT STEPS - STAC Infrastructure Refactoring

**Phase 2A: Fix infrastructure/stac.py (10 direct connections - BLOCKING STAC JOBS)**

The file has TWO usage patterns that need different fixes:

**Pattern 1: Class Methods (lines 140-166, already correct)**
- `PgStacInfrastructure.__init__()` already creates `self._pg_repo = PostgreSQLRepository()`
- `check_installation()`, `verify_installation()`, etc. already use `self._pg_repo._get_connection()`
- ✅ NO CHANGES NEEDED - already using repository pattern correctly

**Pattern 2: Standalone Functions (10 violations)**
These are module-level functions that bypass the repository pattern:

1. **get_all_collections()** (lines 1082-1083, 2000-2001) - 2 occurrences
   - Fix: Accept optional `repo` parameter, default to creating new PostgreSQLRepository

2. **get_collection()** (lines 1140-1141)
   - Fix: Same pattern - accept optional `repo` parameter

3. **get_collection_items()** (lines 1193-1194)
   - Fix: Same pattern - accept optional `repo` parameter

4. **search_items()** (lines 1283-1284)
   - Fix: Same pattern - accept optional `repo` parameter

5. **get_schema_info()** (lines 1498-1499)
   - Fix: Same pattern - accept optional `repo` parameter

6. **get_collection_stats()** (lines 1620-1621)
   - Fix: Same pattern - accept optional `repo` parameter

7. **get_item_by_id()** (lines 1746-1747)
   - Fix: Same pattern - accept optional `repo` parameter

8. **get_health_metrics()** (lines 1816-1817)
   - Fix: Same pattern - accept optional `repo` parameter

9. **get_collections_summary()** (lines 1898-1899)
   - Fix: Same pattern - accept optional `repo` parameter

**Refactoring Pattern**:
```python
# OLD
def get_all_collections() -> Dict[str, Any]:
    from config import get_postgres_connection_string
    connection_string = get_postgres_connection_string()
    with psycopg.connect(connection_string) as conn:
        # ... query logic

# NEW
def get_all_collections(repo: Optional[PostgreSQLRepository] = None) -> Dict[str, Any]:
    if repo is None:
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        # ... query logic (unchanged)
```

**Why This Pattern**:
- Allows dependency injection for testing
- Backward compatible (callers can omit repo parameter)
- Repository creates managed identity connection automatically
- No need for PgSTACRepository wrapper - these are already pgstac-schema-aware functions

**Phase 2B: Update STAC service files**
- services/stac_collection.py
- services/service_stac_vector.py
- services/service_stac_setup.py

**Phase 2C: Update vector handlers**
- services/vector/postgis_handler.py
- services/vector/postgis_handler_enhanced.py

**Phase 2D: Final cleanup**
- Delete `get_postgres_connection_string()` helper (after all migrations complete)

---

## ✅ RESOLVED - ISO3 Country Attribution in STAC Items (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025 (as part of STAC Metadata Encapsulation)
**Purpose**: Add ISO3 country codes to STAC item metadata during creation
**Achievement**: Extracted to standalone service with graceful degradation

### What Was Implemented

**File Created**: `services/iso3_attribution.py` (~300 lines)

```python
@dataclass
class ISO3Attribution:
    iso3_codes: List[str]           # All intersecting countries
    primary_iso3: Optional[str]      # Centroid-based primary country
    countries: List[str]             # Country names (if available)
    attribution_method: Optional[str] # 'centroid' or 'first_intersect'
    available: bool                  # True if attribution succeeded

    def to_stac_properties(self, prefix: str = "geo") -> Dict[str, Any]:
        """Convert to STAC properties dict with namespaced keys."""

class ISO3AttributionService:
    def get_attribution_for_bbox(bbox: List[float]) -> ISO3Attribution
    def get_attribution_for_geometry(geometry: Dict) -> ISO3Attribution
```

### Integration Points

| Location | How ISO3 is Added |
|----------|-------------------|
| Raster STAC items | `STACMetadataHelper.augment_item()` calls ISO3AttributionService |
| Vector STAC items | `STACMetadataHelper.augment_item()` with `include_titiler=False` |
| STAC collections | Direct call to `ISO3AttributionService.get_attribution_for_bbox()` |

### Properties Added to STAC Items

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `geo:iso3` | List[str] | ISO 3166-1 alpha-3 codes for all intersecting countries | `["USA", "CAN"]` |
| `geo:primary_iso3` | str | Primary country (centroid-based) | `"USA"` |
| `geo:countries` | List[str] | Country names (if available in admin0 table) | `["United States", "Canada"]` |
| `geo:attribution_method` | str | How primary was determined | `"centroid"` or `"first_intersect"` |

### Configuration

Uses existing H3 config for admin0 table:
```python
from config import get_config
config = get_config()
admin0_table = config.h3.system_admin0_table  # "geo.system_admin0_boundaries"
```

### Graceful Degradation

The service handles failures gracefully:
- Returns `available=False` if admin0 table doesn't exist
- Returns `available=True` with empty lists if geometry is in ocean/international waters
- Non-fatal warnings logged but STAC item creation continues

### Future Enhancements (Unchanged)

1. **H3 Cell Lookup**: Use H3 grid with precomputed country_code for faster lookup
2. **Admin1 Attribution**: Add state/province codes for granular attribution
3. **Batch Processing**: Single query for multiple bboxes in bulk operations

---

## 🎨 MEDIUM-LOW PRIORITY - Multispectral Band Combination URLs in STAC (21 NOV 2025)

**Status**: Planned - Enhancement for satellite imagery visualization
**Purpose**: Auto-generate TiTiler viewer URLs with common band combinations for Landsat/Sentinel-2 imagery
**Priority**: MEDIUM-LOW (nice-to-have for multispectral data users)
**Effort**: 2-3 hours
**Requested By**: Robert (21 NOV 2025)

### Problem Statement

**Current State**: When `process_raster` detects multispectral imagery (11+ bands like Sentinel-2), it creates standard TiTiler URLs that don't specify band combinations. The default TiTiler viewer can't display 11-band data without explicit band selection.

**User Experience Today**:
1. User processes Sentinel-2 GeoTIFF
2. TiTiler preview URL opens blank/error page
3. User must manually craft URL with `&bidx=4&bidx=3&bidx=2&rescale=0,3000` parameters
4. No guidance provided for common visualization patterns

**Desired State**: STAC items for multispectral imagery should include multiple ready-to-use visualization URLs:
```json
{
  "assets": {
    "data": { "href": "..." },
    "visual_truecolor": {
      "href": "https://titiler.../preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../preview?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../preview?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Detection Logic

**When to generate band combination URLs**:
```python
# Criteria for "multispectral satellite imagery"
should_add_band_urls = (
    band_count >= 4 and
    (dtype == 'uint16' or dtype == 'int16') and
    (
        # Sentinel-2 pattern (11-13 bands)
        band_count in [10, 11, 12, 13] or
        # Landsat 8/9 pattern (7-11 bands)
        band_count in [7, 8, 9, 10, 11] or
        # Generic multispectral with band descriptions
        has_band_descriptions_matching(['blue', 'green', 'red', 'nir'])
    )
)
```

### Standard Band Combinations

**Sentinel-2 (10m/20m bands)**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,3000` | Natural appearance |
| False Color NIR | B8, B4, B3 | `bidx=8&bidx=4&bidx=3&rescale=0,3000` | Vegetation health |
| SWIR | B11, B8, B4 | `bidx=11&bidx=8&bidx=4&rescale=0,3000` | Moisture/geology |
| Agriculture | B11, B8, B2 | `bidx=11&bidx=8&bidx=2&rescale=0,3000` | Crop analysis |

**Landsat 8/9**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,10000` | Natural appearance |
| False Color NIR | B5, B4, B3 | `bidx=5&bidx=4&bidx=3&rescale=0,10000` | Vegetation health |
| SWIR | B7, B5, B4 | `bidx=7&bidx=5&bidx=4&rescale=0,10000` | Moisture/geology |

### Implementation Location

**File**: [services/service_stac_metadata.py](../services/service_stac_metadata.py)

**Location**: In `_generate_titiler_urls()` method, after standard URL generation (around line 455)

```python
# After generating standard URLs...

# Check if multispectral imagery
if raster_type == 'multispectral' and band_count >= 10:
    # Determine rescale based on dtype
    rescale = "0,3000" if dtype == 'uint16' else "0,255"

    # Sentinel-2 band combinations (11-13 bands)
    if band_count >= 10:
        band_combinations = {
            'truecolor': {
                'bands': [4, 3, 2],
                'title': 'True Color (RGB)',
                'description': 'Natural color composite (Red, Green, Blue)'
            },
            'falsecolor_nir': {
                'bands': [8, 4, 3],
                'title': 'False Color (NIR)',
                'description': 'Near-infrared composite for vegetation analysis'
            },
            'swir': {
                'bands': [11, 8, 4] if band_count >= 11 else [8, 4, 3],
                'title': 'SWIR Composite',
                'description': 'Short-wave infrared for moisture and geology'
            }
        }

        for combo_name, combo_info in band_combinations.items():
            bidx_params = '&'.join([f'bidx={b}' for b in combo_info['bands']])
            urls[f'preview_{combo_name}'] = f"{titiler_base}/cog/preview?url={encoded_url}&{bidx_params}&rescale={rescale}"

        logger.info(f"Added {len(band_combinations)} band combination URLs for multispectral imagery")
```

### Task Checklist

- [ ] **Step 1**: Add band combination detection logic to `_validate_raster()` or `_detect_raster_type()`
- [ ] **Step 2**: Create band combination profiles (Sentinel-2, Landsat 8/9, generic)
- [ ] **Step 3**: Extend `_generate_titiler_urls()` to add band-specific preview URLs
- [ ] **Step 4**: Update STAC item assets structure to include visual role URLs
- [ ] **Step 5**: Test with Sentinel-2 imagery (bia_glo30dem.tif is actually Sentinel-2)
- [ ] **Step 6**: Test with Landsat imagery (if available)
- [ ] **Step 7**: Document new STAC asset types in API documentation
- [ ] **Commit**: "Add band combination URLs for multispectral STAC items"

### Expected STAC Item Structure

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "sentinel2-scene-001",
  "properties": {
    "datetime": "2025-11-21T00:00:00Z",
    "geo:raster_type": "multispectral",
    "eo:bands": [
      {"name": "B1", "description": "Coastal aerosol"},
      {"name": "B2", "description": "Blue"},
      {"name": "B3", "description": "Green"},
      {"name": "B4", "description": "Red"},
      {"name": "B5", "description": "Vegetation Red Edge"},
      {"name": "B6", "description": "Vegetation Red Edge"},
      {"name": "B7", "description": "Vegetation Red Edge"},
      {"name": "B8", "description": "NIR"},
      {"name": "B8A", "description": "Vegetation Red Edge"},
      {"name": "B11", "description": "SWIR"},
      {"name": "B12", "description": "SWIR"}
    ]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/...",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    },
    "thumbnail": {
      "href": "https://titiler.../cog/preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000&width=256&height=256",
      "type": "image/png",
      "roles": ["thumbnail"]
    },
    "visual_truecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite Viewer",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Notes

- **Rescale values**: Sentinel-2 L2A reflectance is typically 0-10000 but clipped at 3000 for visualization
- **Band indexing**: TiTiler uses 1-based indexing (band 1 = first band)
- **uint16 handling**: Most satellite imagery is uint16, requires rescale parameter
- **Graceful degradation**: If band combination bands don't exist, skip that combination
