# Zarr Service Layer — Native Zarr Ingest + Service URLs

**Date**: 02 MAR 2026
**Feature**: Zarr Service Layer (SAFe Feature under Data Access Epic)
**Stories**: S1 Native Zarr Ingest, S2 Zarr/NetCDF Service URLs
**Status**: APPROVED

---

## Problem Statement

1. **Native Zarr stores cannot be ingested.** The `DataType.ZARR` enum exists but routes 100% to the VirtualiZarr pipeline (NetCDF → kerchunk). Submitting a `.zarr` store fails at extension detection or at the scan stage looking for `*.nc` files.

2. **Zarr releases have no service URLs.** When a VirtualiZarr or (future) native Zarr release is approved, the catalog returns a generic response with no TiTiler xarray endpoints. STAC materialization explicitly skips URL injection (`# NO TiTiler URL injection for zarr (V1)`).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data type grouping | Both NetCDF and Zarr stay `DataType.ZARR` | Mirrors vector grouping (GeoJSON/KML/SHP all `DataType.VECTOR`) |
| Pipeline routing | `ZarrProcessingOptions.pipeline` field: `"virtualzarr"` or `"ingest_zarr"` | Clean separation, shared catalog/STAC code |
| Submit API for native Zarr | Accept both `container_name+file_name` and `source_url` | Flexible — normalize internally |
| Copy strategy | Bronze → silver-zarr (new container) | Maintains bronze/silver tier separation |
| Variable handling | TiTiler xarray URLs use `{variable}` template param | All variables available at query time, no ingest-time selection |
| Service URLs scope | Shared by both VirtualiZarr output and native Zarr | One `_build_zarr_response()` serves both pipeline outputs |

---

## Architecture

### Pipeline Routing

```
DataType.ZARR
├── pipeline="virtualzarr" (default)
│   → VirtualZarrJob (existing, 5-stage)
│   → NetCDF files → kerchunk reference JSON in silver-netcdf
│
└── pipeline="ingest_zarr"
    → IngestZarrJob (new, 3-stage)
    → Native Zarr store → copied to silver-zarr
```

### Data Flow — Native Zarr (Story 1)

```
Submit (container_name + file_name OR source_url)
  → PlatformRequest.data_type == ZARR
  → ZarrProcessingOptions.pipeline == "ingest_zarr"
  → translate_to_coremachine() → job_type="ingest_zarr"

Stage 1: validate_zarr (single task)
  → Open store with xarray.open_zarr()
  → Confirm .zmetadata or .zattrs exists
  → Extract: variables, dimensions, bbox, time range
  → Return metadata in task result

Stage 2: copy_zarr (parallel tasks)
  → List all blobs under source prefix
  → Split into N chunks for parallel copy
  → Copy bronze → silver-zarr, preserve structure

Stage 3: register_zarr (single task)
  → Build STAC item JSON (variables, dims, time extent, bbox)
  → Set geoetl:data_type = "zarr"
  → Set geoetl:zarr_store_path = silver-zarr prefix
  → Cache on Release.stac_item_json
  → Update processing_status = COMPLETED
```

### Service URL Pattern (Story 2)

TiTiler xarray endpoints accept `variable` as a query parameter — all variables in the store are available without pre-selection.

```
# Discovery
GET /xarray/variables?url={zarr_url}
→ ["temperature", "precipitation", "elevation"]

# Tiling (consumer picks variable)
GET /xarray/tiles/{z}/{x}/{y}?url={zarr_url}&variable=temperature
GET /xarray/tilejson.json?url={zarr_url}&variable=temperature

# Analysis
GET /xarray/info?url={zarr_url}&variable=temperature
GET /xarray/preview.png?url={zarr_url}&variable=temperature
GET /xarray/point/{lon},{lat}?url={zarr_url}&variable=temperature
```

### Zarr Store URL Construction

Two source types produce different silver paths:

| Pipeline | Silver Container | Store URL for TiTiler |
|----------|-----------------|----------------------|
| `virtualzarr` | `silver-netcdf` | HTTPS URL to kerchunk reference JSON |
| `ingest_zarr` | `silver-zarr` | HTTPS URL to Zarr store prefix |

The `_build_zarr_response()` reads `blob_path` from the Release to determine which, then constructs the full HTTPS URL for TiTiler.

---

## Story 1: Native Zarr Ingest Pipeline

### New Files

**`jobs/ingest_zarr.py`** — Job definition

```python
class IngestZarrJob(JobBaseMixin, JobBase):
    job_type = "ingest_zarr"
    description = "Ingest native Zarr store: validate, copy to silver, register"

    stages = [
        {"number": 1, "name": "validate",  "task_type": "validate_zarr",  "parallelism": "single"},
        {"number": 2, "name": "copy",      "task_type": "copy_zarr",      "parallelism": "parallel"},
        {"number": 3, "name": "register",  "task_type": "register_zarr",  "parallelism": "single"},
    ]

    parameters_schema = {
        'source_url':       {'type': 'str', 'required': True},
        'source_account':   {'type': 'str', 'required': True},
        'stac_item_id':     {'type': 'str', 'required': True},
        'collection_id':    {'type': 'str', 'required': True},
        'dataset_id':       {'type': 'str', 'required': True},
        'resource_id':      {'type': 'str', 'required': True},
        'version_id':       {'type': 'str', 'required': True},
        'title':            {'type': 'str', 'required': False},
        'description':      {'type': 'str', 'required': False},
        'tags':             {'type': 'list', 'required': False},
        'access_level':     {'type': 'str', 'required': True},
    }
```

**`services/handler_ingest_zarr.py`** — Three handlers

- `validate_zarr(params)`: Opens store via `xr.open_zarr()` with fsspec/adlfs credentials from `BlobRepository.for_zone()`. Validates `.zmetadata` exists. Extracts variable names, dimensions, spatial bounds (if lat/lon coords exist), time range. Returns metadata dict.
- `copy_zarr(params)`: Lists blobs under source prefix, copies chunk to `silver-zarr/{dataset_id}/{resource_id}/{store_name}/`. Uses `BlobRepository` for both source (bronze) and target (silver) zones.
- `register_zarr(params)`: Builds STAC item JSON from validate metadata. Sets `geoetl:data_type=zarr`, `geoetl:zarr_store_path`. Caches on Release. Sets `processing_status=COMPLETED`.

### Modified Files

**`core/models/platform.py`** — `data_type` property:
- Add `.zarr` extension → `DataType.ZARR`

**`core/models/processing_options.py`** — `ZarrProcessingOptions`:
- Expand `pipeline: Literal["virtualzarr"]` → `Literal["virtualzarr", "ingest_zarr"]`
- Auto-detect: if `file_name` ends with `.zarr`, default pipeline to `"ingest_zarr"`

**`services/platform_translation.py`** — `translate_to_coremachine()`:
- Branch zarr routing on `opts.pipeline`:
  - `"virtualzarr"` → existing path (unchanged)
  - `"ingest_zarr"` → new `ingest_zarr` job with appropriate params
- Normalize `container_name + file_name` to `source_url` when pipeline is `ingest_zarr`

**`jobs/__init__.py`** — Register `IngestZarrJob`

**`services/__init__.py`** — Register `validate_zarr`, `copy_zarr`, `register_zarr` handlers

**`config/defaults.py`** — Add `SILVER_ZARR = "silver-zarr"` constant

**`config/storage_config.py`** — Add `zarr` field to silver storage config

---

## Story 2: Zarr/NetCDF Service URLs

### Modified Files

**`services/platform_catalog_service.py`**:

Add `_build_zarr_response(asset_dict, release_dict)`:
```python
def _build_zarr_response(self, asset, release):
    # Determine store URL from blob_path + container
    blob_path = release.get('blob_path')
    # Detect source: silver-zarr (native) or silver-netcdf (virtualzarr)
    container = release.get('output_container', 'silver-zarr')
    storage_account = self._config.storage.silver.account_name
    zarr_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"
    encoded_url = quote_plus(zarr_url)

    titiler_base = self._config.titiler_base_url

    return {
        "found": True,
        "asset_id": asset.get('asset_id'),
        "data_type": "zarr",
        "status": { ... },
        "service_urls": {
            "variables":  f"{titiler_base}/xarray/variables?url={encoded_url}",
            "tiles":      f"{titiler_base}/xarray/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={encoded_url}&variable={{variable}}",
            "tilejson":   f"{titiler_base}/xarray/tilejson.json?url={encoded_url}&variable={{variable}}",
            "preview":    f"{titiler_base}/xarray/preview.png?url={encoded_url}&variable={{variable}}",
            "info":       f"{titiler_base}/xarray/info?url={encoded_url}&variable={{variable}}",
            "point":      f"{titiler_base}/xarray/point/{{lon}},{{lat}}?url={encoded_url}&variable={{variable}}",
        },
        "metadata": { "bbox": ..., "variables": [...], ... },
        "ddh_refs": { ... },
        "lineage": { ... },
    }
```

Wire into `lookup_unified()`:
```python
elif data_type == 'zarr':
    response = self._build_zarr_response(asset_dict, release_dict)
```

**`config/__init__.py`** (or `config/app_config.py`):

Add `generate_xarray_tile_urls(zarr_url)` helper:
```python
def generate_xarray_tile_urls(self, zarr_url: str) -> dict:
    encoded = quote_plus(zarr_url)
    base = self.titiler_base_url
    return {
        "variables":  f"{base}/xarray/variables?url={encoded}",
        "tiles":      f"{base}/xarray/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={encoded}&variable={{variable}}",
        "tilejson":   f"{base}/xarray/tilejson.json?url={encoded}&variable={{variable}}",
        "preview":    f"{base}/xarray/preview.png?url={encoded}&variable={{variable}}",
        "info":       f"{base}/xarray/info?url={encoded}&variable={{variable}}",
        "point":      f"{base}/xarray/point/{{lon}},{{lat}}?url={encoded}&variable={{variable}}",
    }
```

**`services/stac_materialization.py`**:

Add `_inject_xarray_urls(stac_item_json, zarr_url)`:
- Adds `xarray:variables` link
- Adds `tiles` link (tilejson with `{variable}` template)
- Optionally adds `thumbnail` asset

Call from `_materialize_zarr_item()` — replace the `# NO TiTiler URL injection` comment with the actual call.

---

## Files Summary

| File | Change | Story |
|------|--------|-------|
| `jobs/ingest_zarr.py` | **NEW** — 3-stage job definition | S1 |
| `services/handler_ingest_zarr.py` | **NEW** — validate, copy, register handlers | S1 |
| `jobs/__init__.py` | Register `ingest_zarr` job | S1 |
| `services/__init__.py` | Register 3 new handlers | S1 |
| `core/models/platform.py` | Add `.zarr` extension detection | S1 |
| `core/models/processing_options.py` | Expand `pipeline` literal, auto-detect | S1 |
| `services/platform_translation.py` | Branch zarr routing on pipeline field | S1 |
| `config/defaults.py` | Add `SILVER_ZARR` constant | S1 |
| `config/storage_config.py` | Add `zarr` field to silver storage | S1 |
| `services/platform_catalog_service.py` | Add `_build_zarr_response()`, wire into `lookup_unified()` | S2 |
| `config/__init__.py` or `config/app_config.py` | Add `generate_xarray_tile_urls()` | S2 |
| `services/stac_materialization.py` | Add `_inject_xarray_urls()`, call from `_materialize_zarr_item()` | S2 |

**No changes to**: `core/machine.py`, existing VirtualiZarr handlers/job, unpublish pipeline, web interfaces.

---

## What This Resolves

| Issue | Resolution |
|-------|------------|
| Zarr catalog returns empty generic response | `_build_zarr_response()` returns xarray service URLs |
| `_materialize_zarr_item()` skips TiTiler URLs | `_inject_xarray_urls()` adds them to STAC items |
| Native Zarr submission rejected | `ingest_zarr` pipeline handles `.zarr` stores |
| `ingest_zarr` dashboard placeholder has no backend | Backend now exists |
| VirtualiZarr approved releases have no service URLs | Shared `_build_zarr_response()` serves both pipelines |

## Out of Scope

- SG5-1/SG6-L2 (approval guard for failed releases) — separate fix
- Zarr unpublish pipeline — the existing `unpublish_zarr` job handles both types (inventory by STAC ID)
- Zarr web interface rewiring — the explorer already works for existing stores
- Variable-specific thumbnails at ingest time — consumers select variables at query time
