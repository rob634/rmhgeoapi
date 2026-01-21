# Platform API Guide

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Last Updated**: 21 JAN 2026
**Purpose**: B2B integration API for geospatial data processing
**Audience**: DDH developers, external application integrators
**OpenAPI Spec**: `openapi/platform-api-v1.json` (v1.3.0)

---

## Overview

The Platform API provides a complete lifecycle for geospatial data:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PLATFORM API WORKFLOW                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   1. SUBMIT          2. POLL              3. APPROVE      4. UNPUBLISH  │
│   ────────────       ────────────         ────────────    ────────────  │
│   POST /submit   →   GET /status/{id} →   POST /approve → POST /unpublish│
│                                                                         │
│   Returns:           Returns:             Triggers:       Removes:      │
│   • request_id       • job_status         • Finalization  • STAC items  │
│   • polling URL      • progress           • Service Layer • COG blobs   │
│                      • preview URLs         availability  • Tables      │
│                        (on complete)                                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Four Key Workflows

| Workflow | Endpoint | Purpose |
|----------|----------|---------|
| **1. Submit** | `POST /api/platform/submit` | Submit raster or vector for processing → returns polling URL |
| **2. Poll** | `GET /api/platform/status/{request_id}` | Check job status → returns preview URLs on completion |
| **3. Approve** | `POST /api/platform/approve` | Triggers finalization and Service Layer availability |
| **4. Unpublish** | `POST /api/platform/unpublish/{type}` | Undo everything - delete outputs, STAC items, tables |

---

## Base URL

All endpoints use `{BASE_URL}` as the base. Replace with the environment-specific URL provided by your platform administrator.

**Placeholders used in this document:**

| Placeholder | Description |
|-------------|-------------|
| `{BASE_URL}` | Platform API base URL |
| `{TITILER_URL}` | TiTiler raster tile service URL |
| `{STAC_URL}` | STAC catalog API URL |
| `{WEB_MAP_URL}` | Interactive web map viewer URL |
| `{STORAGE_URL}` | Azure Blob Storage URL |
| `{BRONZE_CONTAINER}` | Input data container name |

---

## Authentication

Currently using Azure AD authentication (when enabled). Contact platform admin for access credentials.

---

## 1. Submit Data for Processing

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
    "container_name": "{BRONZE_CONTAINER}",
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

| Operation | Status | Notes |
|-----------|--------|-------|
| `CREATE` | Production | Via `/api/platform/submit` |
| `UPDATE` | Production | Re-submit with same identifiers (idempotent overwrite) |
| `DELETE` | Production | Via `/api/jobs/submit/unpublish_vector` or `unpublish_raster` |

---

## 2. Check Request Status

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
        "share_url": "{TITILER_URL}/cog/WebMercatorQuad/map.html?url=..."
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
curl "{BASE_URL}/api/platform/status/791147831f11d833c779f8288d34fa5a"
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
    "error": "Missing required parameter: dataset_id",
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
    "error": "Pre-flight validation failed: Blob 'missing.tif' does not exist in container '{BRONZE_CONTAINER}'",
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

### 1. Submit Data

```bash
curl -X POST \
  "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "project-alpha",
    "resource_id": "satellite-image",
    "version_id": "v1.0",
    "data_type": "raster",
    "container_name": "{BRONZE_CONTAINER}",
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
curl "{BASE_URL}/api/platform/status/abc123..."
```

### 3. Access Results (when completed)

**Interactive Map Viewer:**
```
{TITILER_URL}/cog/WebMercatorQuad/map.html?url=...
```

**STAC Item:**
```
{STAC_URL}/api/stac/collections/project-alpha/items/project-alpha-satellite-image-v1.0
```

**Tile Endpoint (for web maps):**
```
{TITILER_URL}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=...
```

---

## 3. Unpublish Vector Data

### Endpoint
```
POST /api/platform/unpublish/vector
```

### Purpose
Remove a vector dataset from the platform via the Platform ACL layer. Accepts DDH identifiers, request_id, or direct table_name (cleanup mode). Drops PostGIS table, deletes metadata, and optionally removes STAC item.

### Request Body Options

**Option 1: By DDH Identifiers (Preferred)**
```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": true
}
```

**Option 2: By Request ID** (from original submission)
```json
{
    "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
    "dry_run": true
}
```

**Option 3: Cleanup Mode** (direct table_name - for orphaned data)
```json
{
    "table_name": "city_parcels_v1_0",
    "schema_name": "geo",
    "dry_run": true
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset_id` | string | Option 1 | - | DDH dataset identifier |
| `resource_id` | string | Option 1 | - | DDH resource identifier |
| `version_id` | string | Option 1 | - | DDH version identifier |
| `request_id` | string | Option 2 | - | Original platform request ID |
| `table_name` | string | Option 3 | - | Direct PostGIS table name (cleanup mode) |
| `schema_name` | string | No | `geo` | PostgreSQL schema containing the table |
| `dry_run` | boolean | No | `true` | Preview mode - shows what would be deleted without executing |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "unpublish-abc123...",
    "job_id": "def456...",
    "job_type": "unpublish_vector",
    "mode": "platform",
    "dry_run": true,
    "table_name": "aerial_imagery_2024_site_alpha_v1_0",
    "message": "Vector unpublish job submitted (dry_run=true)",
    "monitor_url": "/api/platform/status/unpublish-abc123..."
}
```

### Example (curl)

```bash
# Option 1: By DDH identifiers (preferred)
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/vector" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": true
  }'

# Option 2: By request_id
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/vector" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
    "dry_run": false
  }'

# Option 3: Cleanup mode (direct table_name)
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/vector" \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "city_parcels_v1_0",
    "dry_run": false
  }'
```

### Mode Behavior

| Mode | Description |
|------|-------------|
| `platform` | Original request found - uses DDH identifiers to generate table name |
| `cleanup` | No request found - uses provided identifiers directly (logs warning) |

### Workflow Stages

| Stage | Task | Description |
|-------|------|-------------|
| 1 | `inventory_vector` | Query `geo.table_metadata` for ETL/STAC linkage |
| 2 | `drop_vector_table` | DROP PostGIS table + DELETE metadata row |
| 3 | `cleanup_vector` | Delete STAC item if linked + create audit record |

### Job Result (when completed)

```json
{
    "job_result": {
        "table_dropped": "geo.city_parcels_v1_0",
        "metadata_deleted": true,
        "stac_item_deleted": "city-parcels-v1-0",
        "audit_record_id": "unpublish_abc123"
    }
}
```

---

## 4. Unpublish Raster Data

### Endpoint
```
POST /api/platform/unpublish/raster
```

### Purpose
Remove a raster dataset from the platform via the Platform ACL layer. Accepts DDH identifiers, request_id, or direct STAC identifiers (cleanup mode). Deletes STAC item and associated COG/MosaicJSON blobs from storage.

### Request Body Options

**Option 1: By DDH Identifiers (Preferred)**
```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": true
}
```

**Option 2: By Request ID** (from original submission)
```json
{
    "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
    "dry_run": true
}
```

**Option 3: Cleanup Mode** (direct STAC identifiers - for orphaned data)
```json
{
    "stac_item_id": "aerial-imagery-2024-site-alpha-v1-0",
    "collection_id": "aerial-imagery-2024",
    "dry_run": true
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset_id` | string | Option 1 | - | DDH dataset identifier |
| `resource_id` | string | Option 1 | - | DDH resource identifier |
| `version_id` | string | Option 1 | - | DDH version identifier |
| `request_id` | string | Option 2 | - | Original platform request ID |
| `stac_item_id` | string | Option 3 | - | Direct STAC item ID (cleanup mode) |
| `collection_id` | string | Option 3 | - | Direct STAC collection ID (cleanup mode) |
| `dry_run` | boolean | No | `true` | Preview mode - shows what would be deleted without executing |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "unpublish-def456...",
    "job_id": "ghi789...",
    "job_type": "unpublish_raster",
    "mode": "platform",
    "dry_run": true,
    "stac_item_id": "aerial-imagery-2024-site-alpha-v1-0",
    "collection_id": "aerial-imagery-2024",
    "message": "Raster unpublish job submitted (dry_run=true)",
    "monitor_url": "/api/platform/status/unpublish-def456..."
}
```

### Example (curl)

```bash
# Option 1: By DDH identifiers (preferred)
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/raster" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": true
  }'

# Option 2: By request_id
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/raster" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
    "dry_run": false
  }'

# Option 3: Cleanup mode (direct STAC identifiers)
curl -X POST \
  "{BASE_URL}/api/platform/unpublish/raster" \
  -H "Content-Type: application/json" \
  -d '{
    "stac_item_id": "aerial-imagery-2024-site-alpha-v1-0",
    "collection_id": "aerial-imagery-2024",
    "dry_run": false
  }'
```

### Mode Behavior

| Mode | Description |
|------|-------------|
| `platform` | Original request found - uses DDH identifiers to generate STAC IDs |
| `cleanup` | No request found - uses provided identifiers directly (logs warning) |

### Workflow Stages

| Stage | Task | Description |
|-------|------|-------------|
| 1 | `inventory_raster` | Query STAC item, extract asset hrefs for deletion |
| 2 | `delete_raster_blobs` | Fan-out deletion of COG/MosaicJSON blobs |
| 3 | `cleanup_raster` | Delete STAC item + create audit record |

### Job Result (when completed)

```json
{
    "job_result": {
        "stac_item_deleted": "aerial-imagery-2024-site-alpha-v1-0",
        "blobs_deleted": [
            "silver-cogs/aerial-imagery-2024/site-alpha/v1.0/site-alpha_cog_analysis.tif"
        ],
        "collection_cleanup": false,
        "audit_record_id": "unpublish_def456"
    }
}
```

---

## 5. System Health and Monitoring

### Platform Health (Simplified)

The `/api/platform/health` endpoint provides a simplified system readiness check designed for external apps:

```bash
curl "{BASE_URL}/api/platform/health"
```

**Response:**
```json
{
    "status": "healthy",
    "ready_for_jobs": true,
    "summary": {
        "database": "healthy",
        "storage": "healthy",
        "service_bus": "healthy"
    },
    "jobs": {
        "queue_backlog": 5,
        "processing": 2,
        "failed_last_24h": 1,
        "avg_completion_minutes": 15.3
    },
    "timestamp": "2026-01-16T10:00:00Z"
}
```

### Platform Failures

Get recent failures with sanitized error summaries (no internal paths or secrets):

```bash
curl "{BASE_URL}/api/platform/failures?hours=24&limit=20"
```

**Response:**
```json
{
    "period_hours": 24,
    "total_failures": 5,
    "failure_rate": "3.2%",
    "common_patterns": [
        {"pattern": "File not found", "count": 3},
        {"pattern": "Invalid CRS", "count": 2}
    ],
    "recent_failures": [
        {
            "job_id": "abc123...",
            "job_type": "process_raster_v2",
            "failed_at": "2026-01-16T10:00:00Z",
            "error_category": "file_not_found",
            "error_summary": "Source file not accessible",
            "request_id": "req-456..."
        }
    ]
}
```

### Platform Lineage

Trace data lineage for a Platform request (source → processing → outputs):

```bash
curl "{BASE_URL}/api/platform/lineage/{request_id}"
```

### Pre-flight Validation

Validate a file before submitting a job:

```bash
curl -X POST "{BASE_URL}/api/platform/validate" \
  -H "Content-Type: application/json" \
  -d '{"data_type": "raster", "container_name": "bronze-rasters", "blob_name": "imagery.tif"}'
```

**Response:**
```json
{
    "valid": true,
    "file_exists": true,
    "file_size_mb": 250.5,
    "recommended_job_type": "process_raster_v2",
    "processing_mode": "function",
    "estimated_minutes": 15,
    "warnings": []
}
```

### Failed Jobs Query

Use the dbadmin endpoint to query failed jobs with full details:

```bash
curl "{BASE_URL}/api/dbadmin/jobs?status=failed&hours=24&limit=10"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | - | Filter by status (failed, completed, processing) |
| `hours` | integer | 24 | Time window to search |
| `limit` | integer | 50 | Maximum jobs to return |

---

## 6. Data Access URLs

After successful processing, jobs return access URLs for the published data.

### Vector Data Access

When a vector job completes, the result includes:

```json
{
    "job_result": {
        "data_access": {
            "postgis": {
                "schema": "geo",
                "table": "city_parcels_v1_0",
                "connection": "See platform admin for credentials"
            },
            "ogc_features": {
                "collection": "/api/features/collections/city_parcels_v1_0",
                "items": "/api/features/collections/city_parcels_v1_0/items",
                "bbox_query": "/api/features/collections/city_parcels_v1_0/items?bbox=-122.5,37.7,-122.4,37.8"
            },
            "web_map": "{WEB_MAP_URL}/?collection=city_parcels_v1_0"
        }
    }
}
```

**Access Methods:**

| Method | URL Pattern | Description |
|--------|-------------|-------------|
| **OGC Features API** | `/api/features/collections/{table}/items` | Standards-compliant GeoJSON API |
| **Interactive Map** | `{WEB_MAP_URL}/` | Web map viewer |
| **Direct PostGIS** | Connect to `{POSTGRES_HOST}` | SQL access |

### Raster Data Access

When a raster job completes, the result includes:

```json
{
    "job_result": {
        "cog": {
            "blob_path": "silver-cogs/aerial-imagery-2024/site-alpha/v1.0/site-alpha_cog_analysis.tif",
            "size_mb": 127.07
        },
        "stac": {
            "collection_id": "aerial-imagery-2024",
            "item_id": "aerial-imagery-2024-site-alpha-v1.0"
        },
        "share_url": "{TITILER_URL}/cog/map?url=...",
        "data_access": {
            "stac_item": "/api/stac/collections/aerial-imagery-2024/items/aerial-imagery-2024-site-alpha-v1.0",
            "stac_search": "/api/stac/search",
            "tile_endpoint": "{TITILER_URL}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=...",
            "preview": "{TITILER_URL}/cog/preview?url=..."
        }
    }
}
```

**Access Methods:**

| Method | URL Pattern | Description |
|--------|-------------|-------------|
| **STAC Item** | `/api/stac/collections/{collection}/items/{item}` | Metadata + asset links |
| **STAC Search** | `/api/stac/search?bbox=...&datetime=...` | Spatial/temporal search |
| **XYZ Tiles** | `{TITILER_URL}/cog/tiles/{z}/{x}/{y}.png?url=...` | For web maps (Leaflet, MapLibre) |
| **Preview Image** | `{TITILER_URL}/cog/preview?url=...` | Quick thumbnail |
| **Interactive Map** | `share_url` from job result | Full-screen map viewer |

---

## 7. Catalog API - STAC Verification

The Catalog API allows DDH to verify that processed data exists in the STAC catalog and retrieve asset URLs for visualization. This is the B2B interface for STAC access.

### Catalog Lookup

Verify a STAC item exists using DDH identifiers:

```bash
curl "{BASE_URL}/api/platform/catalog/lookup?dataset_id=flood-data&resource_id=res-001&version_id=v1.0"
```

**Query Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `dataset_id` | Yes | DDH dataset identifier |
| `resource_id` | Yes | DDH resource identifier |
| `version_id` | Yes | DDH version identifier |

**Response (found):**
```json
{
    "found": true,
    "stac": {
        "collection_id": "flood-data",
        "item_id": "flood-data-res-001-v1-0",
        "item_url": "/api/platform/catalog/item/flood-data/flood-data-res-001-v1-0",
        "assets_url": "/api/platform/catalog/assets/flood-data/flood-data-res-001-v1-0"
    },
    "processing": {
        "request_id": "a3f2c1b8...",
        "job_id": "abc123...",
        "completed_at": "2026-01-15T10:00:00Z"
    },
    "metadata": {
        "bbox": [-75.5, -56.5, -66.5, -49.0],
        "datetime": "2026-01-15T00:00:00Z"
    },
    "ddh_refs": {
        "dataset_id": "flood-data",
        "resource_id": "res-001",
        "version_id": "v1.0"
    }
}
```

**Response (not found - job still processing):**
```json
{
    "found": false,
    "reason": "job_not_completed",
    "message": "Job is processing. STAC item will be available when job completes.",
    "job_status": "processing",
    "status_url": "/api/platform/status/a3f2c1b8..."
}
```

### Get STAC Item

Retrieve the full STAC item (GeoJSON Feature) with all metadata:

```bash
curl "{BASE_URL}/api/platform/catalog/item/{collection_id}/{item_id}"
```

Returns standard STAC Item format (GeoJSON Feature) with geometry, properties, and assets.

### Get Asset URLs with TiTiler

Retrieve asset URLs with pre-built TiTiler visualization URLs:

```bash
curl "{BASE_URL}/api/platform/catalog/assets/{collection_id}/{item_id}"
```

**Query Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_titiler` | `true` | Include TiTiler URLs |

**Response:**
```json
{
    "item_id": "flood-data-res-001-v1-0",
    "collection_id": "flood-data",
    "bbox": [-75.5, -56.5, -66.5, -49.0],
    "assets": {
        "data": {
            "href": "{STORAGE_URL}/silver-cogs/flood.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "size_mb": 125.5
        }
    },
    "titiler": {
        "preview": "{TITILER_URL}/cog/preview?url=...",
        "tiles": "{TITILER_URL}/cog/tiles/{z}/{x}/{y}?url=...",
        "info": "{TITILER_URL}/cog/info?url=...",
        "tilejson": "{TITILER_URL}/cog/tilejson.json?url=...",
        "wmts": "{TITILER_URL}/cog/WMTSCapabilities.xml?url=..."
    },
    "platform_refs": {
        "dataset_id": "flood-data",
        "resource_id": "res-001",
        "version_id": "v1.0"
    }
}
```

### List Items for Dataset

List all STAC items for a DDH dataset:

```bash
curl "{BASE_URL}/api/platform/catalog/dataset/{dataset_id}?limit=50"
```

**Response:**
```json
{
    "dataset_id": "flood-data",
    "count": 3,
    "items": [
        {
            "item_id": "flood-data-res-001-v1-0",
            "collection_id": "flood-data",
            "bbox": [-75.5, -56.5, -66.5, -49.0],
            "datetime": "2026-01-15T00:00:00Z",
            "resource_id": "res-001",
            "version_id": "v1.0"
        }
    ]
}
```

---

## 8. Approvals API - QA Workflow

The Approvals API manages dataset approval before publication. Approving a dataset marks it as published in the STAC catalog.

### Approve Dataset

```
POST /api/platform/approve
```

**Request Body** - identify dataset by ONE of:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `approval_id` | string | Option 1 | Approval record ID (e.g., `apr-abc123...`) |
| `stac_item_id` | string | Option 2 | STAC item ID for the dataset |
| `job_id` | string | Option 3 | Job ID that processed the dataset |
| `reviewer` | string | **Yes** | Email of person approving |
| `notes` | string | No | Review notes |

**Example:**
```bash
curl -X POST "{BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "stac_item_id": "flood-data-res-001-v1-0",
    "reviewer": "user@example.com",
    "notes": "QA review passed"
  }'
```

**Response:**
```json
{
    "success": true,
    "approval_id": "apr-abc123...",
    "status": "approved",
    "action": "stac_updated",
    "message": "Dataset approved successfully"
}
```

### Revoke Approval

```
POST /api/platform/revoke
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `approval_id` | string | Option 1 | Approval record ID |
| `stac_item_id` | string | Option 2 | STAC item ID |
| `job_id` | string | Option 3 | Job ID |
| `revoker` | string | **Yes** | Email of person revoking |
| `reason` | string | **Yes** | Reason for revocation (audit trail) |

**Example:**
```bash
curl -X POST "{BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "stac_item_id": "flood-data-res-001-v1-0",
    "revoker": "admin@example.com",
    "reason": "Data quality issue discovered"
  }'
```

### List Approvals

```
GET /api/platform/approvals?status=pending&limit=50
```

| Parameter | Description |
|-----------|-------------|
| `status` | Filter: `pending`, `approved`, `rejected`, `revoked` |
| `classification` | Filter: `ouo`, `public` |
| `limit` | Max results (default: 100) |
| `offset` | Pagination offset |

### Get Approval Details

```
GET /api/platform/approvals/{approval_id}
```

### Batch Approval Status (for UI dashboards)

```
GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
```

**Response:**
```json
{
    "success": true,
    "statuses": {
        "item1": {"has_approval": true, "is_approved": true, "approval_id": "apr-abc123", "reviewer": "user@example.com"},
        "item2": {"has_approval": true, "is_approved": false, "status": "pending"},
        "item3": {"has_approval": false}
    }
}
```

---

## Related Documentation

- **Architecture**: See [WIKI_TECHNICAL_OVERVIEW.md](WIKI_TECHNICAL_OVERVIEW.md) for system architecture and security zones
- **STAC API**: See `/api/stac` endpoints for metadata queries
- **OGC Features API**: See [WIKI_OGC_FEATURES.md](WIKI_OGC_FEATURES.md) for vector data access
- **Service Layer**: See [WIKI_SERVICE_LAYER.md](WIKI_SERVICE_LAYER.md) for TiTiler and data serving
- **OpenAPI Spec**: See `openapi/platform-api-v1.json` for machine-readable API definition

---

**Last Updated**: 21 JAN 2026
**API Version**: 1.3.0
