# Platform API Guide

**Date**: 14 DEC 2025
**Purpose**: External application integration via Anti-Corruption Layer (ACL)
**Audience**: DDH developers, external application integrators

---

## Overview

The Platform API is an **Anti-Corruption Layer (ACL)** that shields external applications from CoreMachine (ETL engine) internals. External apps use high-level DDH identifiers; Platform translates them to CoreMachine job parameters automatically.

### Why Use Platform API Instead of CoreMachine API?

| Aspect | Platform API | CoreMachine API |
|--------|--------------|-----------------|
| **Audience** | External applications (DDH) | Internal tools, power users |
| **Identifiers** | `dataset_id`, `resource_id`, `version_id` | `blob_name`, `table_name`, `collection_id` |
| **Output naming** | Auto-generated from DDH IDs | You specify everything |
| **Status tracking** | `request_id` (DDH-friendly) | `job_id` (internal hash) |
| **Isolation** | DDH API changes absorbed here | Direct ETL access |

**Key Benefit**: If DDH changes their API contract, only Platform layer changes - CoreMachine jobs remain untouched.

---

## Base URL

```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

---

## Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/platform/raster` | POST | Single raster file processing |
| `/api/platform/raster-collection` | POST | Multiple raster files (2-20 files) |
| `/api/platform/submit` | POST | Generic submission (auto-detects data type) |
| `/api/platform/status/{request_id}` | GET | Check request/job status |

---

## Authentication

Currently using Azure AD authentication (when enabled). Contact platform admin for access credentials.

---

## 1. Single Raster Processing

### Endpoint
```
POST /api/platform/raster
```

### Purpose
Process a single raster file (GeoTIFF) into a Cloud-Optimized GeoTIFF (COG) with STAC metadata.

### Request Body

```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "container_name": "rmhazuregeobronze",
    "file_name": "aerial-alpha.tif",
    "service_name": "Aerial Imagery Site Alpha",
    "access_level": "OUO",
    "description": "High-resolution aerial imagery for Site Alpha",
    "tags": ["aerial", "rgb", "2024"]
}
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dataset_id` | string | **Yes** | DDH dataset identifier (e.g., "aerial-imagery-2024") |
| `resource_id` | string | **Yes** | DDH resource identifier (e.g., "site-alpha") |
| `version_id` | string | **Yes** | DDH version identifier (e.g., "v1.0") |
| `container_name` | string | **Yes** | Azure Blob container with source file |
| `file_name` | string | **Yes** | Source raster filename (must be string, not list) |
| `service_name` | string | No | Human-readable service name |
| `access_level` | string | No | Access classification ("OUO", "PUBLIC", etc.) |
| `description` | string | No | Dataset description for STAC metadata |
| `tags` | list | No | Tags for searchability |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ecbf12cfe5298f0b23797e7eda6ab1aed9",
    "job_type": "process_raster_v2",
    "message": "Single raster request submitted.",
    "monitor_url": "/api/platform/status/791147831f11d833c779f8288d34fa5a"
}
```

### Example (curl)

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/raster" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "container_name": "rmhazuregeobronze",
    "file_name": "aerial-alpha.tif",
    "service_name": "Aerial Imagery Site Alpha",
    "access_level": "OUO"
  }'
```

### Size Limits

| Limit | Value | Behavior |
|-------|-------|----------|
| Max file size | 800 MB | Auto-fallback to `process_large_raster_v2` for larger files |
| Min file size | None | Any size accepted |

**Note**: Files exceeding 800 MB are automatically routed to the large raster tiling workflow - no action required from the caller.

---

## 2. Raster Collection Processing

### Endpoint
```
POST /api/platform/raster-collection
```

### Purpose
Process multiple raster files into a unified STAC collection with MosaicJSON for seamless tile serving.

### Request Body

```json
{
    "dataset_id": "satellite-tiles-2024",
    "resource_id": "region-alpha",
    "version_id": "v1.0",
    "container_name": "rmhazuregeobronze",
    "file_name": [
        "tiles/tile_R1C1.tif",
        "tiles/tile_R1C2.tif",
        "tiles/tile_R2C1.tif",
        "tiles/tile_R2C2.tif"
    ],
    "service_name": "Satellite Tiles Region Alpha",
    "access_level": "OUO",
    "description": "Multi-tile satellite imagery mosaic"
}
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dataset_id` | string | **Yes** | DDH dataset identifier |
| `resource_id` | string | **Yes** | DDH resource identifier |
| `version_id` | string | **Yes** | DDH version identifier |
| `container_name` | string | **Yes** | Azure Blob container with source files |
| `file_name` | list | **Yes** | List of raster filenames (must be list, not string) |
| `service_name` | string | No | Human-readable service name |
| `access_level` | string | No | Access classification |
| `description` | string | No | Collection description |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "a1b2c3d4e5f6...",
    "job_id": "def456abc789...",
    "job_type": "process_raster_collection_v2",
    "file_count": 4,
    "message": "Raster collection request submitted (4 files).",
    "monitor_url": "/api/platform/status/a1b2c3d4e5f6..."
}
```

### Example (curl)

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/raster-collection" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "namangan-imagery",
    "resource_id": "aug2019",
    "version_id": "v1.0",
    "container_name": "rmhazuregeobronze",
    "file_name": [
      "namangan/namangan14aug2019_R1C1cog.tif",
      "namangan/namangan14aug2019_R1C2cog.tif",
      "namangan/namangan14aug2019_R2C1cog.tif",
      "namangan/namangan14aug2019_R2C2cog.tif"
    ],
    "service_name": "Namangan Satellite Imagery",
    "access_level": "OUO"
  }'
```

### Size and Count Limits

| Limit | Value | Behavior |
|-------|-------|----------|
| Min files | 2 | Use `/api/platform/raster` for single files |
| Max files | 20 | Submit in smaller batches for larger collections |
| Max individual file | 800 MB | Rejected if ANY file exceeds this (Docker worker coming soon) |

---

## 3. Generic Submit (Auto-Detection)

### Endpoint
```
POST /api/platform/submit
```

### Purpose
Generic submission endpoint that auto-detects data type from parameters.

### Request Body

```json
{
    "dataset_id": "boundaries-2024",
    "resource_id": "admin-regions",
    "version_id": "v1.0",
    "data_type": "vector",
    "operation": "CREATE",
    "container_name": "rmhazuregeobronze",
    "file_name": "boundaries.geojson",
    "service_name": "Administrative Boundaries",
    "access_level": "PUBLIC"
}
```

### Supported Data Types

| Data Type | Job Created | Status |
|-----------|-------------|--------|
| `vector` | `process_vector` | Production |
| `raster` | `process_raster_v2` or `process_raster_collection_v2` | Production |
| `pointcloud` | - | Phase 2 |
| `mesh_3d` | - | Phase 2 |
| `tabular` | - | Phase 2 |

### Supported Operations

| Operation | Status |
|-----------|--------|
| `CREATE` | Production |
| `UPDATE` | Phase 2 |
| `DELETE` | Phase 2 |

---

## 4. Check Request Status

### Endpoint
```
GET /api/platform/status/{request_id}
```

### Purpose
Check the status of a submitted request, including underlying job progress.

### Response

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "dataset_id": "test-raster-14dec",
    "resource_id": "dctest",
    "version_id": "v1",
    "data_type": "raster",
    "created_at": "2025-12-14T03:52:23.002245",
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ecbf12cfe5298f0b23797e7eda6ab1aed9",
    "job_type": "process_raster_v2",
    "job_status": "completed",
    "job_stage": 3,
    "job_result": {
        "cog": {
            "size_mb": 127.07,
            "cog_blob": "test-raster-14dec/dctest/v1/dctest_cog_analysis.tif",
            "compression": "deflate"
        },
        "stac": {
            "item_id": "test-raster-14dec-dctest-v1",
            "collection_id": "test-raster-14dec",
            "inserted_to_pgstac": true
        },
        "share_url": "https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=..."
    },
    "task_summary": {
        "total": 3,
        "completed": 3,
        "failed": 0,
        "processing": 0,
        "by_stage": {
            "1": {"total": 1, "completed": 1, "task_types": ["validate_raster"]},
            "2": {"total": 1, "completed": 1, "task_types": ["create_cog"]},
            "3": {"total": 1, "completed": 1, "task_types": ["extract_stac_metadata"]}
        }
    }
}
```

### Example (curl)

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/status/791147831f11d833c779f8288d34fa5a"
```

### Job Status Values

| Status | Description |
|--------|-------------|
| `queued` | Job created, waiting to be processed |
| `processing` | Job is actively being processed |
| `completed` | Job finished successfully |
| `failed` | Job failed (check `error_details`) |
| `completed_with_errors` | Job finished but some tasks failed |

---

## Output Naming Convention

Platform auto-generates all output paths from DDH identifiers:

### From These Inputs:
```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0"
}
```

### These Outputs Are Generated:

| Output Type | Generated Value |
|-------------|-----------------|
| **Output folder** | `aerial-imagery-2024/site-alpha/v1.0/` |
| **STAC collection ID** | `aerial-imagery-2024` |
| **STAC item ID** | `aerial-imagery-2024-site-alpha-v1.0` |
| **COG path** | `silver-cogs/aerial-imagery-2024/site-alpha/v1.0/{filename}_cog_analysis.tif` |
| **Vector table** | `geo.aerial_imagery_2024_site_alpha_v1_0` |

### Naming Rules

- Hyphens preserved in IDs
- Dots replaced with underscores for PostgreSQL table names
- Paths use forward slashes
- All lowercase

---

## Idempotency

Platform API is fully idempotent based on DDH identifiers:

```
request_id = SHA256(dataset_id + resource_id + version_id)
```

### Behavior

| Scenario | Response |
|----------|----------|
| First submission | 202 Accepted, job created |
| Duplicate submission (same IDs) | 200 OK, returns existing request |
| Same file, different version_id | 202 Accepted, new job created |

### Example: Idempotent Response

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_id": "5a5f62fd...",
    "message": "Request already submitted (idempotent)",
    "monitor_url": "/api/platform/status/791147831f11d833c779f8288d34fa5a"
}
```

---

## Error Handling

### Validation Error (400)

```json
{
    "success": false,
    "error": "file_name must be a string for single raster endpoint. Use /api/platform/raster-collection for multiple files.",
    "error_type": "ValidationError"
}
```

### Not Implemented (501)

```json
{
    "success": false,
    "error": "UPDATE operation coming in Phase 2",
    "error_type": "NotImplemented"
}
```

### Pre-flight Validation Failure (400)

```json
{
    "success": false,
    "error": "Pre-flight validation failed: Blob 'missing.tif' does not exist in container 'rmhazuregeobronze'",
    "error_type": "ValidationError"
}
```

### Server Error (500)

```json
{
    "success": false,
    "error": "Internal server error",
    "error_type": "RuntimeError"
}
```

---

## Processing Options

Optional processing parameters can be included in the request:

### Raster Options

```json
{
    "dataset_id": "...",
    "resource_id": "...",
    "version_id": "...",
    "container_name": "...",
    "file_name": "image.tif",
    "processing_options": {
        "output_tier": "analysis",
        "crs": "EPSG:4326",
        "raster_type": "auto"
    }
}
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `output_tier` | `analysis`, `visualization`, `archive` | `analysis` | COG compression profile |
| `crs` | EPSG code | `EPSG:4326` | Target coordinate system |
| `raster_type` | `auto`, `rgb`, `dem`, `categorical` | `auto` | Raster type hint |

### Vector Options

```json
{
    "processing_options": {
        "lon_column": "longitude",
        "lat_column": "latitude",
        "overwrite": false
    }
}
```

| Option | Description |
|--------|-------------|
| `lon_column` | Longitude column name (for CSV) |
| `lat_column` | Latitude column name (for CSV) |
| `wkt_column` | WKT geometry column name (for CSV) |
| `overwrite` | Replace existing data |

---

## Complete Workflow Example

### 1. Submit Raster

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/raster" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "project-alpha",
    "resource_id": "satellite-image",
    "version_id": "v1.0",
    "container_name": "rmhazuregeobronze",
    "file_name": "satellite.tif",
    "service_name": "Project Alpha Satellite",
    "access_level": "OUO"
  }'
```

**Response:**
```json
{
    "success": true,
    "request_id": "abc123...",
    "job_id": "def456...",
    "monitor_url": "/api/platform/status/abc123..."
}
```

### 2. Poll Status

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/status/abc123..."
```

### 3. Access Results (when completed)

**Interactive Map Viewer:**
```
https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=...
```

**STAC Item:**
```
https://rmhogcstac-.../api/stac/collections/project-alpha/items/project-alpha-satellite-image-v1.0
```

**Tile Endpoint (for web maps):**
```
https://rmhtitiler-.../cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=...
```

---

## Related Documentation

- **CoreMachine API**: See `WIKI_API_JOB_SUBMISSION.md` for direct ETL access
- **STAC API**: See `/api/stac` endpoints for metadata queries
- **OGC Features API**: See `/api/features` for vector data access
- **Architecture**: See `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md`

---

**Last Updated**: 14 DEC 2025
**Function App**: rmhazuregeoapi
**Region**: East US
