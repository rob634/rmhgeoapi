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

### Download Fan-Out

- **Source**: `blob_list` (workflow parameter — list of blob path strings)
- **Per-task params**: `{{ item }}` = blob path string, `{{ inputs.container_name }}`
- **Output per task**: `{source_path, file_size_bytes, blob_name}`
- **Fan-in result**: `agg_downloads.items` = list of download results

### Validate Fan-Out

- **Source**: `agg_downloads.items`
- **Per-task params**: `{{ item.source_path }}` as source_path, `{{ item.blob_name }}` as blob_name, `{{ inputs.container_name }}`
- **Output per task**: Full validation result (source_crs, target_crs, needs_reprojection, raster_type, nodata, band_count, dtype, bounds, file_size_bytes)
- **Fan-in result**: `agg_validations.items` = list of validation results

### Homogeneity Check (Single Task)

- **Inputs**: `agg_validations.items` (all validation results), `agg_downloads.items` (for source_path correlation)
- **Logic**: Compare band_count, dtype, CRS, resolution (within tolerance), raster_type across all files against file[0] as reference
- **Output (success)**: `{homogeneous: true, reference: {...}, file_specs: [...]}`
  - Each `file_spec` bundles: source_path, source_crs, target_crs, needs_reprojection, raster_type, nodata, output_blob_name, blob_name
  - `output_blob_name` computed as `{collection_id}/{original_filename_stem}.tif`
- **Output (failure)**: `{success: false, error: "...", mismatches: [...]}`
  - Mismatches include type (BAND_COUNT, DTYPE, CRS, RESOLUTION, RASTER_TYPE), expected vs found, file name

### COG Creation Fan-Out

- **Source**: `check_homogeneity.result.file_specs`
- **Per-task params**: `{{ item.source_path }}`, `{{ item.output_blob_name }}`, `{{ item.source_crs }}`, `{{ item.target_crs }}`, `{{ item.needs_reprojection }}`, `{{ item.raster_type }}`, `{{ item.nodata }}`
- **Output per task**: `{cog_path, cog_blob, bounds_4326, shape, raster_bands, rescale_range, transform, resolution, crs, compression, tile_size, overview_levels}`
- **Fan-in result**: `agg_cogs.items`

### Upload Fan-Out

- **Source**: `agg_cogs.items`
- **Per-task params**: `{{ item.cog_path }}`, `{{ item.cog_blob }}`, `{{ inputs.collection_id }}`
- **Note**: `raster_create_cog_atomic` must pass through `blob_name` in its result dict so the upload handler can access it. If the existing handler does not include `blob_name` in its output, the homogeneity `file_specs` array can be accessed by index via `{{ nodes.check_homogeneity.result.file_specs[index].blob_name }}` — verify template engine supports index access during implementation. Alternatively, the COG fan-out task params can include `blob_name: "{{ item.blob_name }}"` which would flow through naturally.
- **Output per task**: `{stac_item_id, silver_container, silver_blob_path, cog_url, cog_size_bytes, etag}`
- **Fan-in result**: `agg_uploads.items`

### Persist Collection (Single Task)

- **Inputs**: `agg_uploads.items`, `agg_cogs.items`, `check_homogeneity.result.file_specs`, platform metadata
- **Logic**: Iterate over correlated results (same index), build stac_item_json per file via `build_stac_item()`, upsert N `cog_metadata` rows
- **Output**: `{cog_ids: [stac_item_id_1, ...], collection_id, item_count}`

### STAC Materialize Fan-Out

- **Source**: `persist_collection.result.cog_ids`
- **Per-task params**: `{{ item }}` as cog_id, `{{ inputs.collection_id }}`
- **Handler**: Existing `stac_materialize_item` — reads stac_item_json from cog_metadata, sanitizes, injects TiTiler URLs, upserts to pgSTAC

### Collection Materialize (Single Task)

- **Handler**: Existing `stac_materialize_collection`
- **Logic**:
  1. Compute union bbox + temporal extent from all items in pgSTAC
  2. Upsert STAC collection record
  3. Register pgSTAC search (item_count > 1 triggers mosaic registration)
- **Output**: `{collection_id, bbox, item_count, search_id}`
- **Critical**: The `search_id` enables TiTiler to serve all N tiles as a single mosaic layer

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
        validation_results (list): Fan-in collected validation results
        download_results (list): Fan-in collected download results (for source_path)
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
                        "source_path": "/mnt/etl/.../file1.tif",
                        "blob_name": "path/to/file1.tif",
                        "output_blob_name": "collection_id/file1.tif",
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
- Iterate over upload_results (indexed), correlate with cog_results and file_specs by position
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
