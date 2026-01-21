# Process Raster V2 - JobBaseMixin Implementation

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 29 DEC 2025
**Status**: Production

---

## Overview

`process_raster_v2` is a clean slate reimplementation of the raster ETL pipeline using the JobBaseMixin pattern. It provides identical functionality to `process_raster` but with:

- **73% less code** (280 lines vs 743 lines)
- **Declarative parameter validation** via `parameters_schema`
- **Pre-flight resource validation** (fails fast if blob doesn't exist)
- **No deprecated parameters** (clean slate design)
- **Config integration** for defaults (env vars → fallback defaults)

---

## Quick Start

### Minimal Request

```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze"
  }'
```

### Full Parameters

```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "satellite/image.tif",
    "container_name": "rmhazuregeobronze",
    "raster_type": "rgb",
    "output_tier": "visualization",
    "target_crs": "EPSG:3857",
    "jpeg_quality": 90,
    "collection_id": "my-satellite-collection",
    "item_id": "custom-item-id",
    "in_memory": false
  }'
```

---

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_name` | string | **Yes** | - | Name of raster file in blob storage |
| `container_name` | string | **Yes** | - | Source blob container |
| `input_crs` | string | No | null | Source CRS (if not in file metadata) |
| `target_crs` | string | No | config | Target CRS for reprojection (default: EPSG:4326) |
| `raster_type` | string | No | "auto" | Raster type: auto, rgb, rgba, dem, categorical, multispectral, nir |
| `output_tier` | string | No | "analysis" | COG compression tier (see below) |
| `jpeg_quality` | int | No | config | JPEG quality 1-100 (default: 85) |
| `output_folder` | string | No | null | Custom output folder in silver container |
| `strict_mode` | bool | No | false | Fail on validation warnings |
| `in_memory` | bool | No | config | Override in-memory processing (true=faster for small files) |
| `collection_id` | string | No | config | STAC collection ID (default: system-rasters) |
| `item_id` | string | No | auto | Custom STAC item ID |

### Size Limits

| Limit | Value | Behavior |
|-------|-------|----------|
| **Max file size** | 800 MB | Files >800 MB rejected at pre-flight validation |

**For files exceeding 800 MB**: Use `process_large_raster_v2` which routes to the Docker worker for long-running processing.

### Platform Passthrough Parameters (DDH Integration)

| Parameter | Type | Description |
|-----------|------|-------------|
| `dataset_id` | string | Platform dataset identifier |
| `resource_id` | string | Platform resource identifier |
| `version_id` | string | Platform version identifier |
| `access_level` | string | Platform access level |
| `stac_item_id` | string | Platform-specified STAC item ID |

### Output Tiers

| Tier | Compression | Use Case |
|------|-------------|----------|
| `visualization` | JPEG (lossy) | Web display, fast loading |
| `analysis` | DEFLATE (lossless) | GIS analysis, data integrity |
| `archive` | LZW (lossless) | Long-term storage |
| `all` | Creates all three | Multiple use cases |

---

## Execution Chain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         JOB SUBMISSION                                       │
│  POST /api/jobs/submit/process_raster_v2                                    │
│  {"blob_name": "dctest.tif", "container_name": "rmhazuregeobronze"}         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    JobBaseMixin (4 methods automatic)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. validate_job_parameters() → Declarative via parameters_schema            │
│ 2. generate_job_id()         → SHA256 hash of params (idempotent)          │
│ 3. create_job_record()       → Insert to app.jobs table                     │
│ 4. queue_job()               → Send to Service Bus jobs queue               │
├─────────────────────────────────────────────────────────────────────────────┤
│ PRE-FLIGHT: resource_validators runs blob_exists check                      │
│             → Fails fast if dctest.tif doesn't exist in rmhazuregeobronze  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 1: VALIDATE                                    │
│                         task_type: validate_raster                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ Handler: services/raster_validation.py (REUSED)                             │
│                                                                              │
│ Input:                                                                       │
│   - blob_url (SAS URL for raster)                                           │
│   - raster_type: "auto"                                                     │
│   - strict_mode: false                                                      │
│                                                                              │
│ Output:                                                                      │
│   - source_crs: "EPSG:32618" (detected)                                     │
│   - raster_type: {detected_type: "rgb", confidence: 0.95}                   │
│   - warnings: []                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 2: CREATE COG                                  │
│                         task_type: create_cog                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ Handler: services/raster_cog.py (REUSED)                                    │
│                                                                              │
│ Input (from Stage 1 + config):                                              │
│   - source_crs: from Stage 1 result                                         │
│   - target_crs: config.raster.target_crs ("EPSG:4326")                      │
│   - output_tier: "analysis" (→ DEFLATE compression)                         │
│   - jpeg_quality: config.raster.cog_jpeg_quality (85)                       │
│   - overview_resampling: config.raster.overview_resampling ("average")      │
│   - reproject_resampling: config.raster.reproject_resampling ("bilinear")   │
│   - in_memory: job param OR config.raster.cog_in_memory                     │
│                                                                              │
│ Output:                                                                      │
│   - cog_blob: "dctest_cog.tif"                                              │
│   - cog_container: "silver-cogs"                                            │
│   - size_mb: 12.5                                                           │
│   - compression: "deflate"                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STAGE 3: CREATE STAC                                 │
│                         task_type: extract_stac_metadata                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Handler: services/stac_catalog.py (REUSED)                                  │
│                                                                              │
│ Input (from Stage 2 + config):                                              │
│   - container_name: cog_container from Stage 2                              │
│   - blob_name: cog_blob from Stage 2                                        │
│   - collection_id: config.raster.stac_default_collection ("system-rasters") │
│   - Platform passthrough: dataset_id, resource_id, version_id, access_level│
│                                                                              │
│ Output:                                                                      │
│   - item_id: "dctest_cog"                                                   │
│   - collection_id: "system-rasters"                                         │
│   - bbox: [-77.1, 38.8, -76.9, 39.0]                                        │
│   - inserted_to_pgstac: true                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FINALIZE JOB                                         │
│                         finalize_job(context)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ Aggregates all stage results into final job response:                       │
│                                                                              │
│ {                                                                            │
│   "job_type": "process_raster_v2",                                          │
│   "source_blob": "dctest.tif",                                              │
│   "validation": {source_crs, raster_type, confidence, warnings},            │
│   "cog": {cog_blob, cog_container, size_mb, compression},                   │
│   "stac": {item_id, collection_id, bbox, inserted_to_pgstac},               │
│   "titiler_urls": {viewer_url, tile_url, preview_url},                      │
│   "share_url": "https://titiler.../viewer?url=...",                         │
│   "stages_completed": 3,                                                    │
│   "tasks_by_status": {completed: 3, failed: 0}                              │
│ }                                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture: What's REUSED vs CREATED

### REUSED (No Changes Needed)

| Component | File | Purpose |
|-----------|------|---------|
| `validate_raster` handler | `services/raster_validation.py` | Stage 1: CRS, bit-depth, type detection |
| `create_cog` handler | `services/raster_cog.py` | Stage 2: Reproject + COG creation |
| `extract_stac_metadata` handler | `services/stac_catalog.py` | Stage 3: STAC metadata + pgstac insert |
| `blob_exists` validator | `infrastructure/validators.py` | Pre-flight blob existence check |
| `BlobRepository` | `infrastructure/blob.py` | Azure Blob Storage operations |
| `JobBaseMixin` | `jobs/mixins.py` | Provides 4 boilerplate methods |
| `JobBase` | `jobs/base.py` | Abstract interface (6 methods) |
| `RasterConfig` | `config/raster_config.py` | All raster processing defaults |
| `generate_deterministic_task_id` | `core/task_id.py` | Task ID generation |

### CREATED (New)

| File | Action | Description |
|------|--------|-------------|
| `jobs/process_raster_v2.py` | CREATE | ~280 lines, new job class |
| `jobs/__init__.py` | EDIT | +2 lines (import + registration) |

---

## Config Integration

Defaults are loaded from `config/raster_config.py` which reads environment variables with fallbacks:

```python
# Environment Variable → Default
RASTER_TARGET_CRS         → "EPSG:4326"
RASTER_COG_COMPRESSION    → "deflate"
RASTER_COG_JPEG_QUALITY   → 85
RASTER_COG_IN_MEMORY      → true
RASTER_OVERVIEW_RESAMPLING → "average"
RASTER_REPROJECT_RESAMPLING → "bilinear"
STAC_DEFAULT_COLLECTION   → "system-rasters"
```

**Pattern**: Job schema declares `'default': None` for config-controlled fields, then resolves from config at task creation time.

---

## Key Design Decisions

1. **`container_name` is REQUIRED** - Explicit is better than implicit
2. **Config-controlled params removed from user-facing schema**: `overview_resampling`, `reproject_resampling` are resolved from `config.raster.*` at task creation (not user-configurable per-job)
3. **`in_memory` KEPT** - Useful for ETL optimization; overrides config default when specified
4. **`compression` REMOVED** - Replaced by `output_tier` (visualization/analysis/archive/all)
5. **Pre-flight validation** - `blob_exists` check fails fast with HTTP 400 before job is queued
6. **Idempotent job IDs** - SHA256 hash of parameters ensures same input = same job ID

---

## Response Examples

### Successful Job Submission

```json
{
  "job_id": "a1b2c3d4e5f6...",
  "job_type": "process_raster_v2",
  "status": "pending",
  "message": "Job queued successfully",
  "parameters": {
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze"
  }
}
```

### Completed Job Status

```json
{
  "job_id": "a1b2c3d4e5f6...",
  "job_type": "process_raster_v2",
  "status": "completed",
  "result_data": {
    "job_type": "process_raster_v2",
    "source_blob": "dctest.tif",
    "source_container": "rmhazuregeobronze",
    "validation": {
      "source_crs": "EPSG:32618",
      "raster_type": "rgb",
      "confidence": 0.95,
      "warnings": []
    },
    "cog": {
      "cog_blob": "dctest_cog.tif",
      "cog_container": "silver-cogs",
      "size_mb": 12.5,
      "compression": "deflate",
      "processing_time_seconds": 8.3
    },
    "stac": {
      "item_id": "dctest_cog",
      "collection_id": "system-rasters",
      "bbox": [-77.1, 38.8, -76.9, 39.0],
      "inserted_to_pgstac": true
    },
    "titiler_urls": {
      "viewer_url": "https://titiler.../viewer?url=...",
      "tile_url": "https://titiler.../tiles/{z}/{x}/{y}...",
      "preview_url": "https://titiler.../preview..."
    },
    "share_url": "https://titiler.../viewer?url=...",
    "stages_completed": 3,
    "total_tasks_executed": 3,
    "tasks_by_status": {
      "completed": 3,
      "failed": 0
    }
  }
}
```

### Pre-flight Validation Failure

```json
{
  "error": "Resource validation failed",
  "message": "Source raster file does not exist. Verify blob_name and container_name.",
  "validator": "blob_exists",
  "parameters": {
    "blob_name": "nonexistent.tif",
    "container_name": "rmhazuregeobronze"
  }
}
```

---

## Comparison: process_raster vs process_raster_v2

| Aspect | process_raster | process_raster_v2 |
|--------|----------------|-------------------|
| Lines of code | 743 | 280 |
| Parameter validation | Imperative code | Declarative schema |
| Pre-flight checks | None | blob_exists validator |
| Config integration | Inline defaults | Config module pattern |
| `compression` param | Yes (deprecated) | No (use `output_tier`) |
| `overview_resampling` | User param | Config-only |
| `reproject_resampling` | User param | Config-only |
| Boilerplate methods | 4 manual | 4 via mixin |

---

## Migration from process_raster

If you're currently using `process_raster`, migration is straightforward:

1. Change job type: `process_raster` → `process_raster_v2`
2. Replace `compression` with `output_tier`:
   - `"deflate"` → `"analysis"`
   - `"jpeg"` → `"visualization"`
   - `"lzw"` → `"archive"`
3. Remove `overview_resampling` and `reproject_resampling` (now config-controlled)
4. All other parameters remain the same

---

## Files

| File | Purpose |
|------|---------|
| `jobs/process_raster_v2.py` | Job implementation |
| `jobs/__init__.py` | Job registration |
| `config/raster_config.py` | Default configuration |
| `services/raster_validation.py` | Stage 1 handler |
| `services/raster_cog.py` | Stage 2 handler |
| `services/stac_catalog.py` | Stage 3 handler |
| `infrastructure/validators.py` | Pre-flight validators |

---

**Last Updated**: 29 DEC 2025
