# Zarr Service Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add native Zarr store ingestion (validate → copy → register) and xarray TiTiler service URLs for all zarr releases (both VirtualiZarr and native Zarr).

**Architecture:** Two stories sharing `DataType.ZARR`. Story 1 adds an `ingest_zarr` pipeline (3 stages) alongside existing `virtualzarr` (5 stages), routed by `ZarrProcessingOptions.pipeline`. Story 2 adds `_build_zarr_response()` in catalog service and `_inject_xarray_urls()` in STAC materialization, serving both pipeline outputs.

**Tech Stack:** xarray, fsspec/adlfs, Azure Blob Storage, TiTiler xarray endpoints, pgSTAC, CoreMachine job orchestration.

**Design doc:** `docs/plans/2026-03-02-zarr-service-layer-design.md`

---

## Task 1: Storage and Config Foundation

**Files:**
- Modify: `config/defaults.py:297` (add SILVER_ZARR constant)
- Modify: `config/defaults.py:418-459` (add ingest_zarr handlers to DOCKER_TASKS)
- Modify: `config/storage_config.py:415` (add zarr field to StorageAccountConfig)
- Modify: `config/storage_config.py:522-582` (wire zarr into MultiAccountStorageConfig zones)

**Step 1: Add SILVER_ZARR constant**

In `config/defaults.py`, after line 297 (`SILVER_NETCDF = "silver-netcdf"`):

```python
SILVER_ZARR = "silver-zarr"        # Zarr stores for IngestZarr pipeline
```

**Step 2: Add ingest_zarr handlers to DOCKER_TASKS**

In `config/defaults.py`, after line 459 (`"virtualzarr_register"`), add:

```python

        # =====================================================================
        # INGEST ZARR HANDLERS (native Zarr store pipeline)
        # =====================================================================
        "ingest_zarr_validate",
        "ingest_zarr_copy",
        "ingest_zarr_register",
```

**Step 3: Add zarr field to StorageAccountConfig**

In `config/storage_config.py`, after line 415 (`netcdf: str = Field(...)`):

```python
    zarr: str = Field(default="notused", description="Zarr stores (IngestZarr pipeline)")
```

Update the error message in `get_container()` (line ~438) to include `zarr`:
```python
f"Valid options: vectors, rasters, cogs, tiles, mosaicjson, "
f"stac_assets, misc, temp, netcdf, zarr"
```

**Step 4: Wire zarr into MultiAccountStorageConfig zones**

In the `_build_default_config()` method:
- Bronze zone (~line 522): add `zarr=StorageDefaults.NOT_USED,`
- Silver zone (~line 542): add `zarr=os.getenv("SILVER_ZARR_CONTAINER", StorageDefaults.SILVER_ZARR),`
- SilverExt zone (~line 562): add `zarr=StorageDefaults.NOT_USED,`
- Gold zone (~line 582): add `zarr=StorageDefaults.NOT_USED,`

**Step 5: Run existing tests to verify no breakage**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/job_system/ -v --tb=short 2>&1 | tail -30`
Expected: All existing tests PASS (registry validation may fail until Task 3 completes — that's OK, note it and proceed).

**Step 6: Commit**

```bash
git add config/defaults.py config/storage_config.py
git commit -m "Add silver-zarr storage config and ingest_zarr DOCKER_TASKS routing"
```

---

## Task 2: Processing Options and Data Type Detection

**Files:**
- Modify: `core/models/processing_options.py:289-313` (expand ZarrProcessingOptions)
- Modify: `core/models/platform.py:440-463` (add .zarr extension detection)

**Step 1: Expand ZarrProcessingOptions pipeline literal**

In `core/models/processing_options.py`, replace the `pipeline` field (line ~303):

```python
    pipeline: Literal["virtualzarr", "ingest_zarr"] = Field(
        default="virtualzarr",
        description="Pipeline selector: 'virtualzarr' for NetCDF, 'ingest_zarr' for native Zarr stores"
    )
```

**Step 2: Add .zarr extension detection**

In `core/models/platform.py`, in the `data_type` property, after line 449 (`elif ext == 'nc': return DataType.ZARR`), add:

```python
        elif ext == 'zarr':
            return DataType.ZARR
```

**Step 3: Add auto-detection of pipeline from extension**

In `core/models/platform.py`, in the `model_post_init_processing_options` validator (the method that dispatches to `ZarrProcessingOptions`), after creating the options object, add auto-detection logic. If `file_name` ends with `.zarr` and no explicit `pipeline` was set, default to `"ingest_zarr"`.

Find the section in the validator where `ZarrProcessingOptions` is constructed (around line 390-395). After the options object is created:

```python
        if model_cls is ZarrProcessingOptions:
            opts_instance = model_cls(**raw_dict)
            # Auto-detect pipeline from file extension
            file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name
            if file_name and file_name.lower().endswith('.zarr') and 'pipeline' not in raw_dict:
                opts_instance.pipeline = "ingest_zarr"
            self.processing_options = opts_instance
            return self
```

Note: Check the actual validator structure before implementing — it may use a different pattern. The key logic is: `.zarr` extension + no explicit pipeline → default to `ingest_zarr`.

**Step 4: Commit**

```bash
git add core/models/processing_options.py core/models/platform.py
git commit -m "Expand ZarrProcessingOptions for ingest_zarr pipeline, add .zarr detection"
```

---

## Task 3: IngestZarr Job Definition

**Files:**
- Create: `jobs/ingest_zarr.py`
- Modify: `jobs/__init__.py:32-73` (register job)
- Modify: `jobs/unpublish_zarr.py:67` (add ingest_zarr to reverses list)

**Step 1: Create job definition**

Create `jobs/ingest_zarr.py` following the `VirtualZarrJob` pattern (from `jobs/virtualzarr.py:110-163`):

```python
# ============================================================================
# CLAUDE CONTEXT - INGEST ZARR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job definition - Native Zarr store ingest pipeline
# PURPOSE: 3-stage pipeline: validate → copy → register for native Zarr stores
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: IngestZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================

import logging
from typing import Any, Dict, List, Optional

from .base import JobBase
from .mixins import JobBaseMixin

logger = logging.getLogger(__name__)


class IngestZarrJob(JobBaseMixin, JobBase):
    """
    Native Zarr store ingest pipeline.

    3-stage pipeline:
      Stage 1 (validate): Open store with xarray, confirm readable, extract metadata
      Stage 2 (copy):     Copy all blobs from bronze → silver-zarr (parallel fan-out)
      Stage 3 (register): Build STAC item, cache on Release, set COMPLETED

    Routing: DataType.ZARR + ZarrProcessingOptions.pipeline == "ingest_zarr"
    """

    job_type = "ingest_zarr"
    description = "Ingest native Zarr store: validate, copy to silver, register"

    # ETL linkage — unpublish_zarr can reverse this job
    reversed_by = "unpublish_zarr"

    stages = [
        {"number": 1, "name": "validate", "task_type": "ingest_zarr_validate", "parallelism": "single"},
        {"number": 2, "name": "copy",     "task_type": "ingest_zarr_copy",     "parallelism": "fan_out", "depends_on": 1},
        {"number": 3, "name": "register", "task_type": "ingest_zarr_register", "parallelism": "single",  "depends_on": 2},
    ]

    parameters_schema = {
        "source_url":       {"type": "str",  "required": True},
        "source_account":   {"type": "str",  "required": True},
        "stac_item_id":     {"type": "str",  "required": True},
        "collection_id":    {"type": "str",  "required": True},
        "dataset_id":       {"type": "str",  "required": True},
        "resource_id":      {"type": "str",  "required": True},
        "version_id":       {"type": "str",  "required": True},
        "title":            {"type": "str",  "required": False},
        "description":      {"type": "str",  "required": False},
        "tags":             {"type": "list", "required": False},
        "access_level":     {"type": "str",  "required": True},
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Create tasks for each stage of the ingest_zarr pipeline."""

        source_url = job_params.get("source_url", "")
        dataset_id = job_params.get("dataset_id", "unknown")
        resource_id = job_params.get("resource_id", "unknown")

        if stage == 1:
            # Stage 1: Validate — single task
            return [{
                "task_id": f"{job_id[:8]}-validate",
                "task_type": "ingest_zarr_validate",
                "parameters": {
                    "source_url": source_url,
                    "source_account": job_params.get("source_account"),
                    "dataset_id": dataset_id,
                    "resource_id": resource_id,
                },
            }]

        elif stage == 2:
            # Stage 2: Copy — fan out from validate results
            # Previous results contain blob list from validate stage
            validate_result = {}
            if previous_results:
                validate_result = previous_results[0].get("result", {})

            blob_list = validate_result.get("blob_list", [])
            if not blob_list:
                logger.warning(f"[ingest_zarr] Stage 2: No blobs to copy")
                return []

            # Chunk blob list for parallel copy tasks
            chunk_size = max(1, len(blob_list) // 4)  # Up to 4 parallel tasks
            chunks = [blob_list[i:i + chunk_size] for i in range(0, len(blob_list), chunk_size)]

            from config import get_config
            config = get_config()
            silver_container = config.storage.silver.zarr

            tasks = []
            for idx, chunk in enumerate(chunks):
                tasks.append({
                    "task_id": f"{job_id[:8]}-copy-{idx}",
                    "task_type": "ingest_zarr_copy",
                    "parameters": {
                        "source_url": source_url,
                        "source_account": job_params.get("source_account"),
                        "blob_list": chunk,
                        "target_container": silver_container,
                        "target_prefix": f"{dataset_id}/{resource_id}",
                    },
                })
            return tasks

        elif stage == 3:
            # Stage 3: Register — single task
            # Gather metadata from validate (stage 1 results via job_params or previous)
            validate_result = {}
            if previous_results:
                # Stage 3 previous_results are from stage 2 (copy).
                # We need stage 1 results — pass them through job_params or
                # read from the first stage's stored results.
                # CoreMachine passes previous_results from the immediately preceding stage.
                pass

            from config import get_config
            config = get_config()
            silver_container = config.storage.silver.zarr
            silver_account = config.storage.silver.account_name

            store_prefix = f"{dataset_id}/{resource_id}"
            zarr_store_url = f"abfs://{silver_container}/{store_prefix}"

            return [{
                "task_id": f"{job_id[:8]}-register",
                "task_type": "ingest_zarr_register",
                "parameters": {
                    "release_id": job_params.get("release_id"),
                    "source_url": source_url,
                    "zarr_store_url": zarr_store_url,
                    "silver_account": silver_account,
                    "silver_container": silver_container,
                    "store_prefix": store_prefix,
                    "stac_item_id": job_params.get("stac_item_id"),
                    "collection_id": job_params.get("collection_id"),
                    "dataset_id": dataset_id,
                    "resource_id": resource_id,
                    "version_id": job_params.get("version_id"),
                    "title": job_params.get("title"),
                    "description": job_params.get("description"),
                    "tags": job_params.get("tags"),
                    "access_level": job_params.get("access_level"),
                },
            }]

        return []
```

**Note:** The stage 3 handler will need to read validate metadata. Two approaches: (a) the validate handler stores metadata on the Release record, and register reads it back, or (b) the register handler re-opens the silver-zarr store briefly to extract metadata. Approach (a) is cleaner — validate stores metadata as JSON on a release field or in the task result that gets passed through. Check how `virtualzarr` chains results from stage 1 → stage 5 via `create_tasks_for_stage`. The implementer should read `jobs/virtualzarr.py:215-350` to understand the chaining pattern and mirror it.

**Step 2: Register in jobs/__init__.py**

Add import after line ~43:
```python
from .ingest_zarr import IngestZarrJob
```

Add to `ALL_JOBS` dict after the `"virtualzarr"` entry (~line 72):
```python
    "ingest_zarr": IngestZarrJob,
```

**Step 3: Update unpublish_zarr reverses**

In `jobs/unpublish_zarr.py`, line 67, change:
```python
    reverses = ["virtualzarr"]
```
to:
```python
    reverses = ["virtualzarr", "ingest_zarr"]
```

**Step 4: Run registry validation**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from jobs import ALL_JOBS; print(f'Jobs registered: {len(ALL_JOBS)}'); print(list(ALL_JOBS.keys()))"`
Expected: `ingest_zarr` appears in the list. No import errors.

**Step 5: Commit**

```bash
git add jobs/ingest_zarr.py jobs/__init__.py jobs/unpublish_zarr.py
git commit -m "Add IngestZarrJob definition (3-stage native Zarr pipeline)"
```

---

## Task 4: Submit Routing for ingest_zarr

**Files:**
- Modify: `services/platform_translation.py:429-462` (branch zarr routing on pipeline field)

**Step 1: Branch the zarr routing**

In `services/platform_translation.py`, replace the zarr branch (lines 429-462). The existing block unconditionally returns `'virtualzarr'`. Change it to check `opts.pipeline`:

```python
    # ========================================================================
    # ZARR CREATE -> virtualzarr or ingest_zarr
    # ========================================================================
    elif data_type == DataType.ZARR:
        opts = request.processing_options
        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )
        collection_id = request.dataset_id
        source_account = get_config().storage.bronze.account_name

        pipeline = getattr(opts, 'pipeline', 'virtualzarr')

        if pipeline == 'ingest_zarr':
            # Native Zarr store — normalize source_url from container+file if needed
            source_url = request.source_url
            if not source_url and request.container_name and request.file_name:
                file_name = request.file_name[0] if isinstance(request.file_name, list) else request.file_name
                source_url = f"abfs://{request.container_name}/{file_name}"

            if not source_url:
                raise ValueError("ingest_zarr requires source_url or container_name+file_name")

            return 'ingest_zarr', {
                'source_url': source_url,
                'source_account': source_account,
                'stac_item_id': stac_item_id,
                'collection_id': collection_id,
                'title': request.generated_title,
                'description': request.description,
                'tags': request.tags,
                'access_level': request.access_level.value if request.access_level else 'OUO',
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,
            }

        else:
            # VirtualiZarr (NetCDF → kerchunk reference pipeline) — existing path
            return 'virtualzarr', {
                'source_url': request.source_url,
                'source_account': source_account,
                'file_pattern': getattr(opts, 'file_pattern', '*.nc'),
                'concat_dim': getattr(opts, 'concat_dim', 'time'),
                'fail_on_chunking_warnings': getattr(opts, 'fail_on_chunking_warnings', False),
                'max_files': getattr(opts, 'max_files', 500),
                'ref_output_prefix': f"refs/{request.dataset_id}/{request.resource_id}",
                'stac_item_id': stac_item_id,
                'collection_id': collection_id,
                'title': request.generated_title,
                'description': request.description,
                'tags': request.tags,
                'access_level': request.access_level.value if request.access_level else 'OUO',
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,
            }
```

Key detail: The `ingest_zarr` branch normalizes `container_name + file_name` into a `source_url` so both submit patterns work.

**Step 2: Commit**

```bash
git add services/platform_translation.py
git commit -m "Route zarr submissions to ingest_zarr or virtualzarr based on pipeline field"
```

---

## Task 5: IngestZarr Handlers

**Files:**
- Create: `services/handler_ingest_zarr.py`
- Modify: `services/__init__.py:81-158` (register handlers)

**Step 1: Create handler file**

Create `services/handler_ingest_zarr.py` with three handlers. Follow the patterns from `services/handler_virtualzarr.py` (scan at lines 79-283, register at lines 846-1029).

```python
# ============================================================================
# CLAUDE CONTEXT - INGEST ZARR HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler functions - Native Zarr store ingest pipeline
# PURPOSE: validate, copy, register handlers for ingest_zarr job
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: ingest_zarr_validate, ingest_zarr_copy, ingest_zarr_register
# DEPENDENCIES: xarray, fsspec, adlfs, infrastructure.blob_repository
# ============================================================================

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def ingest_zarr_validate(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 1: Validate a native Zarr store.

    - Lists all blobs under the source_url prefix
    - Confirms .zmetadata or .zattrs exists (valid Zarr structure)
    - Opens with xarray.open_zarr() to extract variables, dims, bbox, time range
    - Returns blob list + metadata for downstream stages
    """
    source_url = params.get("source_url")
    source_account = params.get("source_account")

    logger.info(f"[ingest_zarr_validate] Validating Zarr store: {source_url}")

    try:
        from infrastructure import RepositoryFactory
        blob_repo = RepositoryFactory.create_blob_repository(zone="bronze")

        # Parse container and prefix from source_url
        # source_url format: abfs://container/prefix
        url_parts = source_url.replace("abfs://", "").split("/", 1)
        container = url_parts[0]
        prefix = url_parts[1] if len(url_parts) > 1 else ""

        # List all blobs under prefix
        blobs = blob_repo.list_blobs(container, prefix=prefix)
        blob_names = [b.name if hasattr(b, 'name') else str(b) for b in blobs]

        if not blob_names:
            return {
                "success": False,
                "error": "ZARR_EMPTY",
                "message": f"No blobs found under {source_url}",
            }

        # Check for Zarr structure markers
        has_zmetadata = any(b.endswith('.zmetadata') for b in blob_names)
        has_zattrs = any(b.endswith('.zattrs') for b in blob_names)
        has_zarray = any('.zarray' in b for b in blob_names)

        if not (has_zmetadata or has_zattrs or has_zarray):
            return {
                "success": False,
                "error": "ZARR_INVALID_STRUCTURE",
                "message": (
                    f"No .zmetadata, .zattrs, or .zarray found under {source_url}. "
                    "This does not appear to be a valid Zarr store."
                ),
            }

        logger.info(f"[ingest_zarr_validate] Found {len(blob_names)} blobs, "
                     f"zmetadata={has_zmetadata}, zattrs={has_zattrs}")

        # Open with xarray to extract metadata
        import xarray as xr

        credential = blob_repo.get_credential()
        storage_options = {
            "account_name": source_account,
            "credential": credential,
        }

        ds = xr.open_zarr(
            f"az://{container}/{prefix}",
            storage_options=storage_options,
            consolidated=has_zmetadata,
        )

        variables = list(ds.data_vars)
        dimensions = {dim: int(ds.sizes[dim]) for dim in ds.dims}

        # Extract spatial extent if lat/lon coordinates exist
        spatial_extent = None
        lat_names = [n for n in ds.coords if n.lower() in ('lat', 'latitude', 'y')]
        lon_names = [n for n in ds.coords if n.lower() in ('lon', 'longitude', 'x')]
        if lat_names and lon_names:
            lat = ds[lat_names[0]].values
            lon = ds[lon_names[0]].values
            spatial_extent = [
                float(lon.min()), float(lat.min()),
                float(lon.max()), float(lat.max()),
            ]

        # Extract time range if time coordinate exists
        time_range = None
        time_names = [n for n in ds.coords if n.lower() in ('time', 't')]
        if time_names:
            time_coord = ds[time_names[0]]
            try:
                time_range = {
                    "start": str(time_coord.values.min()),
                    "end": str(time_coord.values.max()),
                }
            except Exception:
                pass

        ds.close()

        logger.info(f"[ingest_zarr_validate] Valid store: {len(variables)} variables, "
                     f"{len(dimensions)} dimensions, {len(blob_names)} blobs")

        return {
            "success": True,
            "result": {
                "blob_list": blob_names,
                "blob_count": len(blob_names),
                "variables": variables,
                "dimensions": dimensions,
                "spatial_extent": spatial_extent,
                "time_range": time_range,
                "has_consolidated_metadata": has_zmetadata,
                "source_container": container,
                "source_prefix": prefix,
            },
        }

    except Exception as e:
        logger.error(f"[ingest_zarr_validate] Failed: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "ZARR_VALIDATE_FAILED",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }


def ingest_zarr_copy(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 2: Copy a chunk of Zarr blobs from bronze → silver-zarr.

    Parallel fan-out: each task copies a subset of the blob list.
    Preserves directory structure relative to the source prefix.
    """
    source_url = params.get("source_url")
    source_account = params.get("source_account")
    blob_list = params.get("blob_list", [])
    target_container = params.get("target_container")
    target_prefix = params.get("target_prefix", "")

    logger.info(f"[ingest_zarr_copy] Copying {len(blob_list)} blobs to "
                f"{target_container}/{target_prefix}")

    try:
        from infrastructure import RepositoryFactory
        source_repo = RepositoryFactory.create_blob_repository(zone="bronze")
        target_repo = RepositoryFactory.create_blob_repository(zone="silver")

        # Parse source container and prefix
        url_parts = source_url.replace("abfs://", "").split("/", 1)
        source_container = url_parts[0]
        source_prefix = url_parts[1] if len(url_parts) > 1 else ""

        copied = 0
        failed = 0
        for blob_name in blob_list:
            try:
                # Compute relative path from source prefix
                if source_prefix and blob_name.startswith(source_prefix):
                    relative = blob_name[len(source_prefix):].lstrip("/")
                else:
                    relative = blob_name

                target_path = f"{target_prefix}/{relative}" if target_prefix else relative

                # Copy blob
                source_repo.copy_blob(
                    source_container=source_container,
                    source_blob=blob_name,
                    target_container=target_container,
                    target_blob=target_path,
                    target_repo=target_repo,
                )
                copied += 1

            except Exception as e:
                logger.error(f"[ingest_zarr_copy] Failed to copy {blob_name}: {e}")
                failed += 1

        if failed > 0 and copied == 0:
            return {
                "success": False,
                "error": "ZARR_COPY_FAILED",
                "message": f"All {failed} blob copies failed",
            }

        logger.info(f"[ingest_zarr_copy] Copied {copied}/{len(blob_list)} blobs "
                     f"({failed} failed)")

        return {
            "success": True,
            "result": {
                "copied": copied,
                "failed": failed,
                "target_container": target_container,
                "target_prefix": target_prefix,
            },
        }

    except Exception as e:
        logger.error(f"[ingest_zarr_copy] Failed: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "ZARR_COPY_FAILED",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }


def ingest_zarr_register(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 3: Register the Zarr store as a STAC item on the Release.

    Builds STAC item JSON with zarr metadata (variables, dims, bbox, time).
    Caches on Release.stac_item_json. Sets processing_status = COMPLETED.

    Pattern follows virtualzarr_register (handler_virtualzarr.py:846-1029).
    """
    release_id = params.get("release_id")
    zarr_store_url = params.get("zarr_store_url")
    silver_account = params.get("silver_account")
    silver_container = params.get("silver_container")
    store_prefix = params.get("store_prefix")
    stac_item_id = params.get("stac_item_id")
    collection_id = params.get("collection_id")
    dataset_id = params.get("dataset_id")
    resource_id = params.get("resource_id")
    version_id = params.get("version_id")
    title = params.get("title")
    description = params.get("description")
    tags = params.get("tags", [])
    access_level = params.get("access_level", "OUO")

    logger.info(f"[ingest_zarr_register] Registering {stac_item_id} in {collection_id}")

    try:
        from infrastructure import RepositoryFactory
        release_repo = RepositoryFactory.create_release_repository()

        # Re-open store from silver to extract metadata
        # (validate metadata was in stage 1 results, but CoreMachine only passes
        # previous stage results — we're after stage 2 copy, not stage 1 validate.
        # Re-reading is the simplest reliable approach.)
        import xarray as xr

        silver_repo = RepositoryFactory.create_blob_repository(zone="silver")
        credential = silver_repo.get_credential()
        storage_options = {
            "account_name": silver_account,
            "credential": credential,
        }

        ds = xr.open_zarr(
            f"az://{silver_container}/{store_prefix}",
            storage_options=storage_options,
        )

        variables = list(ds.data_vars)
        dimensions = {dim: int(ds.sizes[dim]) for dim in ds.dims}

        # Spatial extent
        bbox = [-180, -90, 180, 90]  # Default global
        lat_names = [n for n in ds.coords if n.lower() in ('lat', 'latitude', 'y')]
        lon_names = [n for n in ds.coords if n.lower() in ('lon', 'longitude', 'x')]
        if lat_names and lon_names:
            lat = ds[lat_names[0]].values
            lon = ds[lon_names[0]].values
            bbox = [float(lon.min()), float(lat.min()),
                    float(lon.max()), float(lat.max())]

        # Time range
        time_range = None
        time_names = [n for n in ds.coords if n.lower() in ('time', 't')]
        if time_names:
            time_coord = ds[time_names[0]]
            try:
                time_range = {
                    "start": str(time_coord.values.min()),
                    "end": str(time_coord.values.max()),
                }
            except Exception:
                pass

        ds.close()

        # Build STAC item
        now_iso = datetime.now(timezone.utc).isoformat()

        # HTTPS URL for TiTiler xarray access
        zarr_https_url = (
            f"https://{silver_account}.blob.core.windows.net/"
            f"{silver_container}/{store_prefix}"
        )

        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]], [bbox[2], bbox[1]],
                [bbox[2], bbox[3]], [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]],
        }

        temporal_extent = None
        if time_range:
            temporal_extent = [time_range["start"], time_range["end"]]

        properties = {
            "created": now_iso,
            "updated": now_iso,
            "datetime": time_range["start"] if time_range else now_iso,
            "start_datetime": time_range["start"] if time_range else None,
            "end_datetime": time_range["end"] if time_range else None,
            "title": title or stac_item_id,
            "description": description or f"Zarr store: {dataset_id}/{resource_id}",
            # ETL properties (stripped at materialization by sanitize_item_properties)
            "geoetl:data_type": "zarr",
            "geoetl:pipeline": "ingest_zarr",
            "geoetl:dataset_id": dataset_id,
            "geoetl:resource_id": resource_id,
            # Zarr-specific properties
            "zarr:variables": variables,
            "zarr:dimensions": dimensions,
            "xarray:open_kwargs": {
                "engine": "zarr",
                "consolidated": True,
            },
        }

        if tags:
            properties["tags"] = tags

        stac_item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": stac_item_id,
            "collection": collection_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": properties,
            "assets": {
                "zarr": {
                    "href": zarr_https_url,
                    "type": "application/vnd+zarr",
                    "title": "Zarr Store",
                    "roles": ["data"],
                    "xarray:open_kwargs": {
                        "engine": "zarr",
                        "consolidated": True,
                    },
                },
            },
            "links": [],
        }

        # Update Release record
        from core.models.release import ProcessingStatus

        stac_updated = release_repo.update_stac_item_json(release_id, stac_item)
        outputs_updated = release_repo.update_physical_outputs(
            release_id,
            blob_path=store_prefix,
            stac_item_id=stac_item_id,
            output_mode="zarr_store",
        )
        status_updated = release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

        logger.info(f"[ingest_zarr_register] Registered {stac_item_id}: "
                     f"stac={stac_updated}, outputs={outputs_updated}, status={status_updated}")

        return {
            "success": True,
            "result": {
                "stac_item_cached": stac_updated,
                "release_updated": outputs_updated and status_updated,
                "blob_path": store_prefix,
                "variables": variables,
            },
        }

    except Exception as e:
        logger.error(f"[ingest_zarr_register] Failed: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "ZARR_REGISTER_FAILED",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
```

**Important implementation notes for the engineer:**

- The `copy_blob` method on BlobRepository may not exist with this exact signature. Check `infrastructure/blob_repository.py` for the actual copy API. It might be `copy_blob_from_url()` or use `start_copy_from_url()` on the Azure SDK. Adapt accordingly.
- The `list_blobs()` return type varies — check if it returns `BlobProperties` objects or strings.
- Auth pattern: always use `BlobRepository.for_zone()` or `RepositoryFactory.create_blob_repository(zone=...)` — never create `DefaultAzureCredential()` directly.
- The `az://` prefix for fsspec (used in `xr.open_zarr`) may need to be `abfs://` depending on the adlfs version. Check what VirtualiZarr handlers use.

**Step 2: Register handlers in services/__init__.py**

Add import block after line ~87:
```python
# IngestZarr handlers (native Zarr store pipeline)
from .handler_ingest_zarr import (
    ingest_zarr_validate,
    ingest_zarr_copy,
    ingest_zarr_register,
)
```

Add to `ALL_HANDLERS` dict after the virtualzarr entries (~line 157):
```python
    # IngestZarr handlers (native Zarr store pipeline)
    "ingest_zarr_validate": ingest_zarr_validate,
    "ingest_zarr_copy": ingest_zarr_copy,
    "ingest_zarr_register": ingest_zarr_register,
```

**Step 3: Run handler registry validation**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services import ALL_HANDLERS; print(f'Handlers registered: {len(ALL_HANDLERS)}'); [print(k) for k in sorted(ALL_HANDLERS.keys()) if 'zarr' in k]"`
Expected: All three `ingest_zarr_*` handlers plus existing `virtualzarr_*` handlers listed. No import errors.

**Step 4: Commit**

```bash
git add services/handler_ingest_zarr.py services/__init__.py
git commit -m "Add ingest_zarr handlers: validate, copy, register"
```

---

## Task 6: Zarr Service URLs — Config Helper

**Files:**
- Modify: `config/app_config.py:724-760` (add generate_xarray_tile_urls)

**Step 1: Add generate_xarray_tile_urls method**

In `config/app_config.py`, after `generate_vector_tile_urls()` (~line 760), add:

```python
    def generate_xarray_tile_urls(self, zarr_url: str) -> dict:
        """
        Generate TiTiler xarray endpoint URLs for a Zarr store.

        URLs use {variable} as a template parameter — consumers call /variables
        first to discover available variables, then substitute into other URLs.

        Args:
            zarr_url: HTTPS URL to the Zarr store (or kerchunk reference JSON)

        Returns:
            Dict of endpoint URLs with {variable} placeholders
        """
        from urllib.parse import quote_plus
        encoded = quote_plus(zarr_url)
        base = self.titiler_base_url.rstrip('/')

        return {
            "variables":  f"{base}/xarray/variables?url={encoded}",
            "tiles":      f"{base}/xarray/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@1x.png?url={encoded}&variable={{variable}}&decode_times=false",
            "tilejson":   f"{base}/xarray/tilejson.json?url={encoded}&variable={{variable}}&decode_times=false",
            "preview":    f"{base}/xarray/preview.png?url={encoded}&variable={{variable}}&decode_times=false",
            "info":       f"{base}/xarray/info?url={encoded}&variable={{variable}}&decode_times=false",
            "point":      f"{base}/xarray/point/{{lon}},{{lat}}?url={encoded}&variable={{variable}}&decode_times=false",
        }
```

Note: `decode_times=false` is included as default because TiTiler xarray requires it as a lowercase string param. The `@1x.png` suffix sets 1x resolution PNG tiles.

**Step 2: Commit**

```bash
git add config/app_config.py
git commit -m "Add generate_xarray_tile_urls() config helper for zarr service URLs"
```

---

## Task 7: Zarr Service URLs — Catalog Response

**Files:**
- Modify: `services/platform_catalog_service.py:565-579` (add zarr branch in lookup_unified)
- Modify: `services/platform_catalog_service.py:829-834` (add zarr branch in get_unified_urls)
- Modify: `services/platform_catalog_service.py` (add _build_zarr_response method)

**Step 1: Add _build_zarr_response method**

In `services/platform_catalog_service.py`, after `_build_generic_response()` (~line 785), add:

```python
    def _build_zarr_response(self, asset: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
        """Build catalog response for zarr data type with xarray TiTiler URLs."""
        from datetime import datetime, timezone
        from urllib.parse import quote_plus

        blob_path = release.get('blob_path')
        output_mode = release.get('output_mode', '')
        stac_collection_id = release.get('stac_collection_id')
        stac_item_id = release.get('stac_item_id')

        # Build zarr store URL for TiTiler
        xarray_urls = {}
        if blob_path:
            storage_account = self._config.storage.silver.account_name

            # Determine container from output_mode
            if output_mode == 'zarr_store':
                container = self._config.storage.silver.zarr
            else:
                # VirtualiZarr output — kerchunk reference in silver-netcdf
                container = self._config.storage.silver.netcdf

            zarr_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"
            xarray_urls = self._config.generate_xarray_tile_urls(zarr_url)

        # Extract zarr metadata from cached STAC item if available
        zarr_metadata = {}
        stac_json = release.get('stac_item_json')
        if stac_json and isinstance(stac_json, dict):
            props = stac_json.get('properties', {})
            zarr_metadata = {
                "variables": props.get('zarr:variables', []),
                "dimensions": props.get('zarr:dimensions', {}),
                "open_kwargs": props.get('xarray:open_kwargs', {}),
            }

        return {
            "found": True,
            "asset_id": asset.get('asset_id'),
            "data_type": "zarr",

            "status": {
                "processing": release.get('processing_status', 'pending'),
                "approval": release.get('approval_state', 'pending_review'),
                "clearance": release.get('clearance_state', 'uncleared'),
            },

            "xarray_urls": xarray_urls,

            "stac": {
                "collection_id": stac_collection_id,
                "item_id": stac_item_id,
            },

            "zarr_metadata": zarr_metadata,

            "metadata": {
                "bbox": release.get('bbox'),
                "created_at": asset.get('created_at'),
            },

            "ddh_refs": {
                "dataset_id": asset.get('dataset_id'),
                "resource_id": asset.get('resource_id'),
                "version_id": release.get('version_id'),
            },

            "lineage": {
                "asset_id": asset.get('asset_id'),
                "version_id": release.get('version_id'),
                "version_ordinal": release.get('version_ordinal'),
                "is_latest": release.get('is_latest'),
                "is_served": release.get('is_served'),
            },

            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
```

**Step 2: Wire into lookup_unified**

In `lookup_unified()` (~line 575), change the `else` branch:

```python
        if data_type == 'vector':
            response = self._build_vector_response(asset_dict, release_dict)
        elif data_type == 'raster':
            response = self._build_raster_response(asset_dict, release_dict)
        elif data_type == 'zarr':
            response = self._build_zarr_response(asset_dict, release_dict)
        else:
            logger.warning(f"   Unknown data_type: {data_type}")
            response = self._build_generic_response(asset_dict, release_dict)
```

**Step 3: Wire into get_unified_urls**

Same pattern at ~line 829:

```python
        if asset.data_type == 'vector':
            return self._build_vector_response(asset_dict, release_dict)
        elif asset.data_type == 'raster':
            return self._build_raster_response(asset_dict, release_dict)
        elif asset.data_type == 'zarr':
            return self._build_zarr_response(asset_dict, release_dict)
        else:
            return self._build_generic_response(asset_dict, release_dict)
```

**Step 4: Commit**

```bash
git add services/platform_catalog_service.py
git commit -m "Add _build_zarr_response with xarray TiTiler URLs in catalog service"
```

---

## Task 8: Zarr Service URLs — STAC Materialization

**Files:**
- Modify: `services/stac_materialization.py:755-794` (inject xarray URLs in _materialize_zarr_item)

**Step 1: Add _inject_xarray_urls method**

In `services/stac_materialization.py`, after `_inject_titiler_urls()` (~line 851), add:

```python
    def _inject_xarray_urls(self, stac_item_json: dict) -> None:
        """Inject TiTiler xarray URLs into zarr STAC item."""
        try:
            from config import get_config
            config = get_config()

            # Get zarr store URL from assets
            assets = stac_item_json.get('assets', {})
            zarr_asset = assets.get('zarr') or assets.get('reference')
            if not zarr_asset:
                logger.warning("[STAC] No zarr/reference asset found for xarray URL injection")
                return

            zarr_url = zarr_asset.get('href', '')
            if not zarr_url:
                return

            xarray_urls = config.generate_xarray_tile_urls(zarr_url)

            # Add variables discovery link
            links = stac_item_json.setdefault('links', [])
            links.append({
                "rel": "variables",
                "href": xarray_urls["variables"],
                "type": "application/json",
                "title": "Available Variables (TiTiler xarray)",
            })

            # Add tilejson link (with {variable} template)
            links.append({
                "rel": "tilejson",
                "href": xarray_urls["tilejson"],
                "type": "application/json",
                "title": "TileJSON (substitute {variable})",
            })

            logger.info(f"[STAC] Injected xarray URLs for zarr item")

        except Exception as e:
            logger.warning(f"[STAC] Failed to inject xarray URLs: {e}")
```

**Step 2: Call from _materialize_zarr_item**

In `_materialize_zarr_item()`, replace the comment at line ~791:

```python
        # NO TiTiler URL injection for zarr (V1)
```

with:

```python
        # Inject TiTiler xarray URLs
        self._inject_xarray_urls(stac_item_json)
```

**Step 3: Commit**

```bash
git add services/stac_materialization.py
git commit -m "Inject xarray TiTiler URLs into zarr STAC items at materialization"
```

---

## Task 9: Verification and Integration Test

**Step 1: Run full import validation**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda run -n azgeo python -c "
from jobs import ALL_JOBS
from services import ALL_HANDLERS
print(f'Jobs: {len(ALL_JOBS)}')
print(f'Handlers: {len(ALL_HANDLERS)}')
print('ingest_zarr job:', 'ingest_zarr' in ALL_JOBS)
print('ingest_zarr handlers:', all(h in ALL_HANDLERS for h in ['ingest_zarr_validate', 'ingest_zarr_copy', 'ingest_zarr_register']))
"
```

Expected: All True, no import errors.

**Step 2: Run existing test suite**

```bash
conda run -n azgeo python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: All existing tests pass. No regressions.

**Step 3: Verify catalog service imports cleanly**

```bash
conda run -n azgeo python -c "
from services.platform_catalog_service import PlatformCatalogService
print('Catalog service imports OK')
from services.stac_materialization import StacMaterializationService
print('STAC materialization imports OK')
from config.app_config import AppConfig
c = AppConfig()
urls = c.generate_xarray_tile_urls('https://example.com/store.zarr')
print(f'xarray URL keys: {list(urls.keys())}')
"
```

Expected: All imports succeed. URL keys: `['variables', 'tiles', 'tilejson', 'preview', 'info', 'point']`.

**Step 4: Deploy and live-test (when ready)**

After deployment, test with:
```bash
# Submit a native Zarr store
curl -X POST https://rmhazuregeoapi-.../api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-zarr-ingest",
    "resource_id": "store1",
    "container_name": "bronze-data",
    "file_name": "test-data/sample.zarr",
    "processing_options": {"pipeline": "ingest_zarr"}
  }'

# Check catalog for xarray URLs
curl "https://rmhazuregeoapi-.../api/platform/catalog/lookup-unified?dataset_id=test-zarr-ingest&resource_id=store1"
```

**Step 5: Commit any final fixes, then tag**

```bash
git commit -m "Verify zarr service layer integration"
```

---

## Summary: Commit Sequence

| # | Commit | Files |
|---|--------|-------|
| 1 | Storage config + DOCKER_TASKS | `config/defaults.py`, `config/storage_config.py` |
| 2 | Processing options + data type | `core/models/processing_options.py`, `core/models/platform.py` |
| 3 | IngestZarrJob definition | `jobs/ingest_zarr.py`, `jobs/__init__.py`, `jobs/unpublish_zarr.py` |
| 4 | Submit routing | `services/platform_translation.py` |
| 5 | Handler implementations | `services/handler_ingest_zarr.py`, `services/__init__.py` |
| 6 | Config URL helper | `config/app_config.py` |
| 7 | Catalog response | `services/platform_catalog_service.py` |
| 8 | STAC materialization | `services/stac_materialization.py` |
| 9 | Integration verification | (no new files) |
