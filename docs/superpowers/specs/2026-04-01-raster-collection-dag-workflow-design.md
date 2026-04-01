# Raster Collection DAG Workflow Design

**Date**: 01 APR 2026
**Status**: Approved
**Version**: v0.10.10
**Author**: Claude + Robert

---

## Summary

New DAG workflow (`process_raster_collection`) that processes N raster files into N COGs registered under a single STAC collection with a pgSTAC mosaic search URL. Replaces the Epoch 4 monolithic `raster_collection_complete` handler with fully decomposed atomic handlers connected by fan-out/fan-in nodes.

## Motivation

- Epoch 4 collection handler (`raster_collection_complete`) is a 400+ line monolith with checkpoint-based resume — not composable, not testable per phase
- DAG engine provides fan-out/fan-in, approval gates, and per-task error reporting natively
- This workflow is also a precursor to future directory-scanning workflows that will auto-create collections from blob storage directories
- The workflow must be a clean, self-contained unit callable standalone via `platform/submit` or composable into larger orchestrations

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Per-file output | 1:1 (single COG per file) | Phase A — no tiling. Phase B adds per-file tiling later |
| Per-file size cap | 2GB (env var) | OOM guard; matches tiling threshold in single-raster workflow |
| Homogeneity validation | Post-download, per-file validate then cross-check | Can't assume COG inputs; all files go to mount first |
| Handler reuse | Reuse all 6 existing atomics, 2 new handlers | Prove the DAG architecture handles this complexity |
| Fan-out decomposition | Fully decomposed — 4 fan-out/fan-in cycles | Use the DAG as designed; no composite shortcuts |
| Persist strategy | Single task writes N rows | Needs correlated data from multiple prior fan-outs |
| Cross-fan-out correlation | Deterministic mount paths keyed by `blob_stem` | Mount is a real filesystem; handlers derive paths by convention, not parameter threading |

## Intermediate Data Doctrine

DAG workflows use two channels for data flow between handlers:

### Channel 1: ETL Mount (Azure Files) — File Data

The ETL mount (`/mnt/etl/{run_id}/`) is a real filesystem. Handlers use **deterministic path conventions** to locate files without needing explicit paths passed through DAG parameters.

**Raster collection mount layout:**

```
/mnt/etl/{run_id}/
  source/
    {blob_stem_0}.tif          ← download handler writes here
    {blob_stem_1}.tif
    ...
  cogs/
    {blob_stem_0}.tif          ← COG handler writes here
    {blob_stem_1}.tif
    ...
```

**Convention**: The `blob_stem` (filename without extension from the original blob path) is the correlation key across all fan-out phases. Any handler can reconstruct the path it needs from `(run_id, blob_stem, phase)` without receiving it from a predecessor.

**Scope**: This convention applies to raster workflows that use the ETL mount. Zarr/NetCDF workflows do NOT use the mount for intermediate data — native zarr is cloud-native and reads/writes directly to blob storage via `abfs://` URLs.

### Channel 2: DAG Parameters — Metadata

Structured metadata (CRS, band count, validation results, bounds, raster_type) flows through DAG `receives` mappings and fan-out template syntax. This is data that cannot be derived from the filesystem.

### Channel 3: Blob Storage — Computed Keys (Not Discovery)

Silver blob paths (e.g. `silver-cogs/{collection_id}/{blob_stem}.tif`) are **computed strings** passed as parameters. Blob storage has no real directories — never list or glob to discover intermediates. All blob paths are constructed deterministically by the handler that writes them.

### Why Two Channels?

| Problem | Mount Convention Solves | DAG Parameters Solve |
|---------|----------------------|---------------------|
| "Where is file N?" | `{run_id}/source/{blob_stem}.tif` — derivable | N/A |
| "What CRS is file N?" | N/A | `validation_results[N].source_crs` |
| "Where did the COG go on mount?" | `{run_id}/cogs/{blob_stem}.tif` — derivable | N/A |
| "Where is the COG in silver?" | N/A | Computed key: `silver-cogs/{collection_id}/{blob_stem}.tif` |

This eliminates fragile cross-fan-out index correlation for file locations while keeping structured metadata in the DAG where it belongs.

## Parameters

```yaml
parameters:
  blob_list: {type: list, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  processing_options:
    type: dict
    default: {}
    # Supports: input_crs, target_crs, raster_type, strict_mode
  # Platform metadata passthrough
  dataset_id: {type: str, required: false}
  resource_id: {type: str, required: false}
  version_id: {type: str, required: false}
  access_level: {type: str, required: false}
  title: {type: str, required: false}
  tags: {type: list, required: false}
  release_id: {type: str, required: false}
  asset_id: {type: str, required: false}
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RASTER_COLLECTION_MAX_FILE_SIZE_MB` | `2048` | Per-file size cap (hard limit, OOM guard) |
| `RASTER_COLLECTION_MAX_FILES` | `20` | Max files per collection submission |

## Pre-Flight Validators

```yaml
validators:
  - type: blob_list_exists_with_max_size
    container_param: container_name
    blob_list_param: blob_list
    zone: bronze
    max_size_mb: env:RASTER_COLLECTION_MAX_FILE_SIZE_MB
    max_count: env:RASTER_COLLECTION_MAX_FILES
    error_too_large: "Individual file exceeds per-file size limit. Use tiled collection workflow for files over 2 GB."
    error_too_many: "Collection exceeds maximum file count."
```

Note: The `blob_list_exists_with_max_size` validator already exists in `/infrastructure/validators.py`. Env var resolution in validators may require a small extension if not already supported — verify during implementation.

## DAG Shape

```
                    +-----------------+
                    |   blob_list     |  (workflow parameter)
                    +--------+--------+
                             |
                    +--------v--------+
                    | download_files  |  fan-out per blob
                    | (N tasks)       |  handler: raster_download_source
                    +--------+--------+
                             |
                    +--------v--------+
                    | agg_downloads   |  fan-in collect
                    +--------+--------+
                             |
                    +--------v--------+
                    | validate_files  |  fan-out per downloaded file
                    | (N tasks)       |  handler: raster_validate
                    +--------+--------+
                             |
                    +--------v--------+
                    | agg_validations |  fan-in collect
                    +--------+--------+
                             |
                    +--------v--------+
                    |check_homogeneity|  single task (NEW handler)
                    | cross-compare   |  outputs: file_specs[]
                    +--------+--------+
                             |
                    +--------v--------+
                    | create_cogs     |  fan-out per file_spec
                    | (N tasks)       |  handler: raster_create_cog_atomic
                    +--------+--------+
                             |
                    +--------v--------+
                    | agg_cogs        |  fan-in collect
                    +--------+--------+
                             |
                    +--------v--------+
                    | upload_cogs     |  fan-out per COG result
                    | (N tasks)       |  handler: raster_upload_cog
                    +--------+--------+
                             |
                    +--------v--------+
                    | agg_uploads     |  fan-in collect
                    +--------+--------+
                             |
                    +--------v--------+
                    |persist_collection| single task (NEW handler)
                    | writes N rows   |  outputs: cog_ids[]
                    +--------+--------+
                             |
                    +--------v--------+
                    | approval_gate   |  gate: approval
                    +--------+--------+
                             |
                    +--------v--------+
                    |materialize_items|  fan-out per cog_id
                    | (N tasks)       |  handler: stac_materialize_item
                    +--------+--------+
                             |
                    +--------v--------+
                    |agg_materializes |  fan-in collect
                    +--------+--------+
                             |
                    +--------v--------+
                    |materialize_coll |  single task
                    |extent + search  |  handler: stac_materialize_collection
                    +--------+--------+
                             |
                    +--------v--------+
                    |    finalize     |  handler: raster_finalize
                    +--------+--------+
```

## Data Flow Between Fan-Outs

The mount path convention eliminates most cross-fan-out parameter threading for file locations. Each fan-out below shows what flows through DAG parameters (metadata) vs what is derived from mount convention (file paths).

### Download Fan-Out

- **Source**: `blob_list` (workflow parameter — list of blob path strings)
- **Per-task params**: `{{ item }}` = blob path string, `{{ inputs.container_name }}`
- **Mount write**: `{run_id}/source/{blob_stem}.tif`
- **DAG output**: `{blob_stem, file_size_bytes, blob_name}` — the `blob_stem` is the correlation key for all downstream phases
- **Fan-in result**: `agg_downloads.items` = list of `{blob_stem, file_size_bytes, blob_name}`

### Validate Fan-Out

- **Source**: `agg_downloads.items`
- **Per-task params**: `{{ item.blob_stem }}` (handler derives mount path: `{run_id}/source/{blob_stem}.tif`), `{{ item.blob_name }}`, `{{ inputs.container_name }}`
- **Mount read**: `{run_id}/source/{blob_stem}.tif` — derived, not passed
- **DAG output**: Full validation metadata (source_crs, target_crs, needs_reprojection, raster_type, nodata, band_count, dtype, bounds) plus `blob_stem` forwarded
- **Fan-in result**: `agg_validations.items` = list of validation results keyed by `blob_stem`

### Homogeneity Check (Single Task)

- **Inputs**: `agg_validations.items` (all validation results — each carries `blob_stem`)
- **Logic**: Compare band_count, dtype, CRS, resolution (within tolerance), raster_type across all files against file[0] as reference
- **Output (success)**:
  ```json
  {
    "homogeneous": true,
    "reference": {"band_count": 1, "dtype": "float32", "crs": "EPSG:32637", ...},
    "file_count": 5,
    "file_specs": [
      {
        "blob_stem": "nairobi_dem",
        "blob_name": "datasets/nairobi_dem.tif",
        "output_blob_name": "my_collection/nairobi_dem.tif",
        "source_crs": "EPSG:32637",
        "target_crs": "EPSG:4326",
        "needs_reprojection": true,
        "raster_type": {"detected_type": "dem", ...},
        "nodata": -9999.0,
        "band_count": 1,
        "dtype": "float32"
      }
    ]
  }
  ```
  - `blob_stem` = mount correlation key (handlers derive paths)
  - `output_blob_name` = silver blob key (computed, not discovered)
- **Output (failure)**: `{success: false, error: "...", mismatches: [...]}`
  - Mismatches include type (BAND_COUNT, DTYPE, CRS, RESOLUTION, RASTER_TYPE), expected vs found, file name

### COG Creation Fan-Out

- **Source**: `check_homogeneity.result.file_specs`
- **Per-task params**: `{{ item.blob_stem }}`, `{{ item.output_blob_name }}`, `{{ item.source_crs }}`, `{{ item.target_crs }}`, `{{ item.needs_reprojection }}`, `{{ item.raster_type }}`, `{{ item.nodata }}`
- **Mount read**: `{run_id}/source/{blob_stem}.tif` — derived from `blob_stem`
- **Mount write**: `{run_id}/cogs/{blob_stem}.tif` — derived from `blob_stem`
- **DAG output**: `{blob_stem, cog_blob, bounds_4326, shape, raster_bands, rescale_range, transform, resolution, crs, compression, tile_size, overview_levels}`
- **Fan-in result**: `agg_cogs.items`

### Upload Fan-Out

- **Source**: `agg_cogs.items`
- **Per-task params**: `{{ item.blob_stem }}`, `{{ item.cog_blob }}`, `{{ inputs.collection_id }}`
- **Mount read**: `{run_id}/cogs/{blob_stem}.tif` — derived from `blob_stem`
- **Blob write**: `silver-cogs/{collection_id}/{blob_stem}.tif` — computed key
- **DAG output**: `{blob_stem, stac_item_id, silver_container, silver_blob_path, cog_url, cog_size_bytes, etag}`
- **Fan-in result**: `agg_uploads.items`

### Persist Collection (Single Task)

- **Inputs**: `agg_uploads.items`, `agg_cogs.items`, `check_homogeneity.result.file_specs`, platform metadata
- **Correlation**: All three lists are correlated by `blob_stem` (not index position)
- **Logic**: For each `blob_stem`, join upload result + COG result + file_spec, build `stac_item_json` via `build_stac_item()`, upsert `cog_metadata` row
- **DAG output**: `{cog_ids: [stac_item_id_1, ...], collection_id, item_count}`

### STAC Materialize Fan-Out

- **Source**: `persist_collection.result.cog_ids`
- **Per-task params**: `{{ item }}` as cog_id, `{{ inputs.collection_id }}`
- **Handler**: Existing `stac_materialize_item` — reads stac_item_json from cog_metadata, sanitizes, injects TiTiler URLs, upserts to pgSTAC
- **No mount access** — reads from DB, writes to pgSTAC

### Collection Materialize (Single Task)

- **Handler**: Existing `stac_materialize_collection`
- **Logic**:
  1. Compute union bbox + temporal extent from all items in pgSTAC
  2. Upsert STAC collection record
  3. Register pgSTAC search (item_count > 1 triggers mosaic registration)
- **DAG output**: `{collection_id, bbox, item_count, search_id}`
- **Critical**: The `search_id` enables TiTiler to serve all N tiles as a single mosaic layer via a single viewer/tilejson/tiles URL

## New Handlers

### 1. `raster_check_homogeneity`

**File**: `services/raster/handler_check_homogeneity.py`
**Registered as**: `raster_check_homogeneity` in ALL_HANDLERS

**Contract**:
```python
def raster_check_homogeneity(params, context=None) -> dict:
    """
    Cross-compare validation results for collection homogeneity.

    Params:
        validation_results (list): Fan-in collected validation results.
            Each item carries blob_stem plus metadata (source_crs, band_count,
            dtype, raster_type, nodata, etc.)
        collection_id (str): For output_blob_name generation
        tolerance_percent (float, optional): Resolution tolerance, default 20.0

    Returns (success):
        {
            "success": True,
            "result": {
                "homogeneous": True,
                "reference": {band_count, dtype, crs, resolution, raster_type},
                "file_count": N,
                "file_specs": [
                    {
                        "blob_stem": "nairobi_dem",
                        "blob_name": "datasets/nairobi_dem.tif",
                        "output_blob_name": "my_collection/nairobi_dem.tif",
                        "source_crs": "EPSG:32637",
                        "target_crs": "EPSG:4326",
                        "needs_reprojection": True,
                        "raster_type": {"detected_type": "dem", ...},
                        "nodata": -9999.0,
                        "band_count": 1,
                        "dtype": "float32"
                    },
                    ...
                ]
            }
        }

    Note: file_specs does NOT include source_path or cog_path.
    Downstream handlers derive mount paths from (run_id, blob_stem).
    output_blob_name is a computed silver blob key, not a mount path.

    Returns (failure):
        {
            "success": False,
            "error": "Collection is not homogeneous: BAND_COUNT, DTYPE mismatch",
            "error_type": "HomogeneityError",
            "retryable": False,
            "mismatches": [...]
        }
    """
```

**Checks** (ported from Epoch 4):
- Band count: exact match
- Data type: exact match
- CRS: exact match (same EPSG)
- Resolution: within tolerance (default +/-20%)
- Raster type: same category (no RGB + DEM mixing; unknown passes)

**No I/O**: Pure comparison on in-memory validation results.

### 2. `raster_persist_collection`

**File**: `services/raster/handler_persist_collection.py`
**Registered as**: `raster_persist_collection` in ALL_HANDLERS

**Contract**:
```python
def raster_persist_collection(params, context=None) -> dict:
    """
    Write N cog_metadata rows for a raster collection.

    Params:
        upload_results (list): Fan-in collected upload results
        cog_results (list): Fan-in collected COG creation results
        file_specs (list): From homogeneity check (validation metadata)
        collection_id (str): STAC collection ID
        Platform metadata: dataset_id, resource_id, version_id, stac_item_id,
                          access_level, title, tags, release_id, asset_id

    Returns:
        {
            "success": True,
            "result": {
                "cog_ids": ["item_id_1", "item_id_2", ...],
                "collection_id": "my_collection",
                "item_count": N
            }
        }
    """
```

**Logic**:
- Join upload_results, cog_results, and file_specs by `blob_stem` (not index position)
- Build `stac_item_json` per file via existing `build_stac_item()`
- Upsert N `cog_metadata` rows via `RasterMetadataRepository`
- Pattern follows `raster_persist_tiled` (writes N rows, returns cog_ids list)

## Existing Handler Reuse (6)

| Handler | File | Used In Phase | Changes |
|---------|------|---------------|---------|
| `raster_download_source` | `services/raster/handler_download_source.py` | Download | None |
| `raster_validate` | `services/raster/handler_validate.py` | Validate | None |
| `raster_create_cog_atomic` | `services/raster/handler_create_cog.py` | COG Creation | None |
| `raster_upload_cog` | `services/raster/handler_upload_cog.py` | Upload | None |
| `stac_materialize_item` | `services/stac/handler_materialize_item.py` | STAC Items | None |
| `stac_materialize_collection` | `services/stac/handler_materialize_collection.py` | Collection + Search | None |

## Registration

- **Workflow YAML**: `workflows/process_raster_collection.yaml`
- **Handler registration**: Add 2 new handlers to `ALL_HANDLERS` in `services/__init__.py`
- **Docker task routing**: Add 2 new handlers to `DOCKER_TASKS` in `config/defaults.py`
- **Platform submit**: No changes — existing `platform/submit` resolves workflow by name

## Platform Status Integration

The `platform/status` response for a collection follows the same pattern as tiled rasters:

- **`awaiting_approval`**: `services=null`, `approval={approve_url, asset_id, viewer_url}` where `viewer_url` points to TiTiler `/preview/raster`
- **`approved`**: `services` block includes mosaic URLs derived from the pgSTAC search_id (single viewer URL loads all tiles as one scene)

No changes needed to `triggers/trigger_platform_status.py` — the existing logic already handles collections via search_id-based mosaic URLs.

## Future: Phase B (Per-File Tiling)

When tiling support is needed per file:
1. Replace the COG creation phase with a conditional node (route_by_size per file)
2. Files <= threshold: `raster_create_cog_atomic` (current path)
3. Files > threshold: sub-workflow or nested fan-out for tiling
4. Raise `RASTER_COLLECTION_MAX_FILE_SIZE_MB` accordingly
5. `raster_persist_collection` would need to handle mixed single + tiled outputs

## Future: Directory Scanner Workflow

This collection workflow is designed as a building block. A future directory-scanning workflow would:
1. List blobs in a directory prefix
2. Group by collection logic (TBD — could be by subdirectory, by naming convention, etc.)
3. Invoke `process_raster_collection` per group (as a sub-workflow or via platform/submit)

The clean parameter interface (blob_list + container_name + collection_id) makes this composable.
