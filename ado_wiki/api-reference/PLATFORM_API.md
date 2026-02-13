# Platform API Guide

> **Navigation**: [Quick Start](../getting-started/QUICK_START.md) | **Platform API** | [Errors](ERRORS.md) | [Glossary](../getting-started/GLOSSARY.md)

**Last Updated**: 12 FEB 2026
**Purpose**: B2B integration API for geospatial data processing
**Audience**: DDH developers, external application integrators
**API Version**: 1.5.0 (V0.8.6.2 - Version Lineage + dry_run)

---

## Overview

The Platform API provides a complete lifecycle for geospatial data:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PLATFORM API WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   0. VALIDATE        1. SUBMIT          2. POLL           3. APPROVE       │
│   ────────────       ────────────       ────────────      ────────────     │
│   POST /validate →   POST /submit   →   GET /status   →   POST /approve    │
│   (or ?dry_run)                                           POST /reject     │
│                                                                             │
│   Returns:           Returns:           Returns:          Triggers:         │
│   • lineage_state    • request_id       • job_status      • Publication     │
│   • valid: t/f       • polling URL      • progress        • Service Layer   │
│   • suggested_params                    • preview URLs                      │
│                                                                             │
│   4. UNPUBLISH                     RESUBMIT (retry failed jobs)             │
│   ────────────                     ────────────────────────────             │
│   POST /unpublish                  POST /resubmit → Cleanup → New job       │
│   Removes: STAC, COGs, Tables                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Endpoint Summary

| Category | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| **Submit** | `/api/platform/submit` | POST | Submit raster/vector for processing |
| **Status** | `/api/platform/status/{id}` | GET | Check job/request status |
| **Status** | `/api/platform/status` | GET | List all platform requests |
| **Validate** | `/api/platform/validate` | POST | Pre-flight validation (dry run) |
| **Approve** | `/api/platform/approve` | POST | Approve dataset for publication |
| **Reject** | `/api/platform/reject` | POST | Reject pending dataset |
| **Revoke** | `/api/platform/revoke` | POST | Revoke approved dataset |
| **Approvals** | `/api/platform/approvals` | GET | List approvals with filters |
| **Approvals** | `/api/platform/approvals/{id}` | GET | Get approval details |
| **Approvals** | `/api/platform/approvals/status` | GET | Batch approval status lookup |
| **Unpublish** | `/api/platform/unpublish` | POST | Remove published data |
| **Resubmit** | `/api/platform/resubmit` | POST | Retry failed job with cleanup |
| **Health** | `/api/platform/health` | GET | System readiness check |
| **Failures** | `/api/platform/failures` | GET | Recent failures with patterns |
| **Lineage** | `/api/platform/lineage/{id}` | GET | Data lineage trace |
| **Catalog** | `/api/platform/catalog/lookup` | GET | STAC lookup by DDH IDs |
| **Catalog** | `/api/platform/catalog/item/{col}/{item}` | GET | Get STAC item |
| **Catalog** | `/api/platform/catalog/assets/{col}/{item}` | GET | Get asset URLs |
| **Catalog** | `/api/platform/catalog/dataset/{id}` | GET | List items for dataset |
| **Platforms** | `/api/platforms` | GET | List supported B2B platforms |
| **Platforms** | `/api/platforms/{id}` | GET | Get platform details |

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
| `{STORAGE_URL}` | Blob Storage URL |
| `{BRONZE_CONTAINER}` | Input data container name |

---

## 1. Submit Data for Processing

### Endpoint
```
POST /api/platform/submit
```

### Purpose
Generic submission endpoint that auto-detects data type from file extension or explicit parameter.

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

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `dataset_id` | string | DDH dataset identifier |
| `resource_id` | string | DDH resource identifier |
| `version_id` | string | DDH version identifier |
| `container_name` | string | Source container name |
| `file_name` | string or array | Source file(s) - array for collections |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_type` | string | auto | `raster` or `vector` (auto-detected from extension) |
| `operation` | string | `CREATE` | `CREATE` or `UPDATE` |
| `service_name` | string | - | Human-readable dataset name |
| `access_level` | string | `OUO` | `OUO` (internal) or `PUBLIC` (external delivery) |
| `processing_options` | object | - | Type-specific processing options |
| `previous_version_id` | string | - | **Required for version advances** - must match current latest version |

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | `false` | Validate without creating job (returns lineage state) |

### Supported Operations

| Operation | Description |
|-----------|-------------|
| `CREATE` | Create new dataset (default) |
| `UPDATE` | Overwrite existing dataset - use `overwrite: true` in processing_options |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec...",
    "job_type": "process_raster_v2",
    "message": "Platform request submitted",
    "monitor_url": "/api/platform/status/791147831f11d833c779f8288d34fa5a"
}
```

### Raster Collection (Multiple Files)

Submit multiple rasters as a collection by passing an array:

```json
{
    "dataset_id": "satellite-imagery",
    "resource_id": "region-tiles",
    "version_id": "v1.0",
    "container_name": "{BRONZE_CONTAINER}",
    "file_name": ["tile_001.tif", "tile_002.tif", "tile_003.tif"]
}
```

---

## 2. Check Request Status

### Get Status by ID

```
GET /api/platform/status/{request_id}
GET /api/platform/status/{job_id}
```

The endpoint auto-detects whether the ID is a request_id or job_id.

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
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec...",
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
        "by_stage": {
            "1": {"total": 1, "completed": 1, "task_types": ["validate_raster"]},
            "2": {"total": 1, "completed": 1, "task_types": ["create_cog"]},
            "3": {"total": 1, "completed": 1, "task_types": ["extract_stac_metadata"]}
        }
    }
}
```

### List All Requests

```
GET /api/platform/status?limit=100&status=pending
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum results |
| `status` | string | - | Filter: `pending`, `processing`, `completed`, `failed` |
| `offset` | integer | 0 | Pagination offset |

### Job Status Values

| Status | Description |
|--------|-------------|
| `queued` | Job created, waiting to be processed |
| `processing` | Job is actively being processed |
| `completed` | Job finished successfully |
| `failed` | Job failed (check `error_details`) |
| `completed_with_errors` | Job finished but some tasks failed |

---

## 3. Pre-flight Validation & Version Lineage

### Overview

The Platform API tracks **version lineage** for datasets. When submitting a new version (e.g., v2.0 after v1.0), you must specify `previous_version_id` to prevent race conditions where two clients submit the same version simultaneously.

**Two equivalent validation workflows:**
- `POST /api/platform/validate` - Standalone validation endpoint
- `POST /api/platform/submit?dry_run=true` - Submit with dry_run parameter

Both return identical responses and use the same validation logic.

### Validation Endpoint

```
POST /api/platform/validate
POST /api/platform/submit?dry_run=true
```

### Request Body
Same format as `/api/platform/submit`.

### Response Structure

```json
{
    "valid": true,
    "dry_run": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "would_create_job_type": "vector_docker_etl",
    "lineage_state": {
        "lineage_id": "c391b297bdf4a51cc23f0dd1af9d37d1",
        "lineage_exists": true,
        "current_latest": {
            "version_id": "v1.0",
            "version_ordinal": 1,
            "asset_id": "d386f436d2219eb2...",
            "is_served": true,
            "created_at": "2026-02-01T21:41:41.039810"
        }
    },
    "validation": {
        "data_type_detected": "vector",
        "previous_version_valid": true
    },
    "warnings": [],
    "suggested_params": {
        "version_ordinal": 2,
        "previous_version_id": "v1.0"
    }
}
```

### Version Validation Matrix

| `previous_version_id` | Lineage State | Result |
|-----------------------|---------------|--------|
| `null` | Empty (first version) | ✅ **valid: true** |
| `null` | Has versions (v1.0 exists) | ❌ **valid: false** - "Specify previous_version_id='v1.0'" |
| `"v1.0"` | Empty lineage | ❌ **valid: false** - "v1.0 doesn't exist" |
| `"v1.0"` | Latest is v1.0 | ✅ **valid: true** |
| `"v1.0"` | Latest is v2.0 | ❌ **valid: false** - "v1.0 is not latest, current is v2.0" |

### Recommended Workflow

**Step 1: Validate before submitting**
```bash
curl -X POST "{BASE_URL}/api/platform/submit?dry_run=true" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "floods",
    "resource_id": "jakarta",
    "version_id": "v2.0",
    "data_type": "vector",
    "container_name": "bronze-vectors",
    "file_name": "jakarta_v2.gpkg"
  }'
```

**Response (lineage exists, missing previous_version_id):**
```json
{
    "valid": false,
    "warnings": [
        "Version 'v1.0' already exists for this dataset/resource. Specify previous_version_id='v1.0' to submit a new version."
    ],
    "suggested_params": {
        "previous_version_id": "v1.0",
        "version_ordinal": 2
    }
}
```

**Step 2: Submit with previous_version_id**
```bash
curl -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "floods",
    "resource_id": "jakarta",
    "version_id": "v2.0",
    "previous_version_id": "v1.0",
    "data_type": "vector",
    "container_name": "bronze-vectors",
    "file_name": "jakarta_v2.gpkg"
  }'
```

### Validation Errors (Submit without dry_run)

If you submit without `dry_run=true` and validation fails, you get a **400 Bad Request**:

```json
{
    "success": false,
    "error": "Version 'v1.0' already exists for this dataset/resource. Specify previous_version_id='v1.0' to submit a new version.",
    "error_type": "ValidationError"
}
```

### First Version (No Lineage)

For the first version of a dataset/resource, `previous_version_id` is not required:

```bash
curl -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "floods",
    "resource_id": "jakarta",
    "version_id": "v1.0",
    "data_type": "vector",
    "container_name": "bronze-vectors",
    "file_name": "jakarta_v1.gpkg"
  }'
```

---

## 4. Approval Workflow

### Approve Dataset

```
POST /api/platform/approve
```

Approves a pending dataset for publication.

**Request Body:**
```json
{
    "stac_item_id": "flood-data-res-001-v1-0",
    "reviewer": "user@example.com",
    "notes": "QA review passed"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `approval_id` | string | Option 1 | Approval record ID |
| `stac_item_id` | string | Option 2 | STAC item ID |
| `job_id` | string | Option 3 | Job ID |
| `request_id` | string | Option 4 | Platform request ID |
| `reviewer` | string | **Yes** | Reviewer email |
| `notes` | string | No | Review notes |

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

### Reject Dataset

```
POST /api/platform/reject
```

Rejects a pending dataset that fails review (different from revoke which is for already-approved datasets).

**Request Body:**
```json
{
    "stac_item_id": "flood-data-res-001-v1-0",
    "reviewer": "user@example.com",
    "reason": "Data quality issue found"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `approval_id` | string | Option 1 | Approval record ID |
| `stac_item_id` | string | Option 2 | STAC item ID |
| `job_id` | string | Option 3 | Job ID |
| `request_id` | string | Option 4 | Platform request ID |
| `reviewer` | string | **Yes** | Reviewer email |
| `reason` | string | **Yes** | Rejection reason (audit trail) |

**Response:**
```json
{
    "success": true,
    "approval_id": "apr-abc123...",
    "status": "rejected",
    "asset_id": "...",
    "asset_updated": true,
    "message": "Dataset rejected"
}
```

### Revoke Approval

```
POST /api/platform/revoke
```

Revokes an already-approved dataset (unpublishes it). This is an audit-logged operation.

**Request Body:**
```json
{
    "stac_item_id": "flood-data-res-001-v1-0",
    "revoker": "admin@example.com",
    "reason": "Data quality issue discovered"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `approval_id` | string | Option 1 | Approval record ID |
| `stac_item_id` | string | Option 2 | STAC item ID |
| `job_id` | string | Option 3 | Job ID |
| `revoker` | string | **Yes** | Revoker email |
| `reason` | string | **Yes** | Revocation reason (audit trail) |

**Response:**
```json
{
    "success": true,
    "approval_id": "apr-abc123...",
    "status": "revoked",
    "asset_id": "...",
    "asset_deleted": true,
    "warning": "Approved dataset has been revoked",
    "message": "Approval revoked successfully"
}
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

**Response:**
```json
{
    "success": true,
    "approvals": [...],
    "count": 25,
    "status_counts": {"pending": 5, "approved": 15, "rejected": 3, "revoked": 2}
}
```

### Get Approval Details

```
GET /api/platform/approvals/{approval_id}
```

### Batch Approval Status

```
GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
```

Returns approval status for multiple items (useful for UI dashboards).

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

## 5. Unpublish Data

### Endpoint
```
POST /api/platform/unpublish
```

### Purpose
Remove a dataset from the platform. Auto-detects data type and removes all outputs.

### Request Body Options

**Option 1 - By DDH Identifiers (Preferred):**
```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": true
}
```

**Option 2 - By Request ID:**
```json
{
    "request_id": "a3f2c1b8e9d7f6a5...",
    "dry_run": true
}
```

**Option 3 - By Job ID:**
```json
{
    "job_id": "abc123...",
    "dry_run": true
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | `true` | Preview mode - shows what would be deleted |

### Response (202 Accepted)

```json
{
    "success": true,
    "request_id": "unpublish-abc123...",
    "job_id": "def456...",
    "data_type": "raster",
    "dry_run": true,
    "message": "Unpublish job submitted (dry_run=true)",
    "monitor_url": "/api/platform/status/unpublish-abc123..."
}
```

### What Gets Deleted

| Data Type | Outputs Removed |
|-----------|-----------------|
| **Vector** | PostGIS table, `geo.table_catalog` metadata, STAC item |
| **Raster** | COG blob(s), MosaicJSON (if collection), STAC item |

---

## 6. Resubmit Failed Job

### Endpoint
```
POST /api/platform/resubmit
```

### Purpose
Retry a failed job with automatic cleanup of partial artifacts.

### Request Body Options

**Option 1 - By DDH Identifiers (Preferred):**
```json
{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "dry_run": false,
    "delete_blobs": false
}
```

**Option 2 - By Request ID:**
```json
{
    "request_id": "a3f2c1b8e9d7f6a5...",
    "dry_run": false
}
```

**Option 3 - By Job ID:**
```json
{
    "job_id": "abc123...",
    "dry_run": false
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | `false` | Preview cleanup without executing |
| `delete_blobs` | boolean | `false` | Also delete COG files from storage |
| `force` | boolean | `false` | Resubmit even if job is currently processing |

### Response

```json
{
    "success": true,
    "original_job_id": "abc123...",
    "new_job_id": "def456...",
    "job_type": "process_raster_v2",
    "platform_refs": {
        "request_id": "...",
        "dataset_id": "...",
        "resource_id": "...",
        "version_id": "..."
    },
    "cleanup_summary": {
        "tasks_deleted": 5,
        "job_deleted": true,
        "tables_dropped": [],
        "stac_items_deleted": ["item-123"],
        "blobs_deleted": []
    },
    "message": "Job resubmitted successfully",
    "monitor_url": "/api/platform/status/def456..."
}
```

---

## 7. System Health and Monitoring

### Platform Health

```
GET /api/platform/health
```

Simplified system readiness check for external apps.

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

```
GET /api/platform/failures?hours=24&limit=20
```

Recent failures with sanitized error summaries (no internal paths or secrets).

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

```
GET /api/platform/lineage/{request_id}
```

Trace data lineage (source → processing → outputs).

**Response:**
```json
{
    "success": true,
    "request_id": "...",
    "lineage": {
        "source": {
            "container": "bronze-rasters",
            "blob": "image.tif",
            "size_mb": 250.5
        },
        "processing": {
            "job_id": "...",
            "job_type": "process_raster_v2",
            "started_at": "...",
            "completed_at": "..."
        },
        "outputs": {
            "cog_blob": "silver-cogs/.../image_cog.tif",
            "stac_item": "dataset-resource-v1",
            "stac_collection": "dataset"
        }
    }
}
```

---

## 8. Catalog API (STAC Access)

The Catalog API allows B2B apps to verify processed data in the STAC catalog.

### Catalog Lookup

```
GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z
```

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
    }
}
```

**Response (not found - job processing):**
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

```
GET /api/platform/catalog/item/{collection_id}/{item_id}
```

Returns the full STAC item (GeoJSON Feature).

### Get Asset URLs with TiTiler

```
GET /api/platform/catalog/assets/{collection_id}/{item_id}?include_titiler=true
```

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
    }
}
```

### List Items for Dataset

```
GET /api/platform/catalog/dataset/{dataset_id}?limit=50
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

## 9. Platform Registry

List supported B2B platforms and their identifier requirements.

### List Platforms

```
GET /api/platforms
GET /api/platforms?active_only=false
```

**Response:**
```json
{
    "success": true,
    "platforms": [
        {
            "platform_id": "ddh",
            "display_name": "Data Distribution Hub",
            "description": "Primary B2B platform with dataset/resource/version hierarchy",
            "required_refs": ["dataset_id", "resource_id", "version_id"],
            "optional_refs": ["title", "description", "access_level"],
            "is_active": true
        }
    ],
    "count": 1
}
```

### Get Platform Details

```
GET /api/platforms/{platform_id}
```

**Response:**
```json
{
    "success": true,
    "platform": {
        "platform_id": "ddh",
        "display_name": "Data Distribution Hub",
        "description": "Primary B2B platform...",
        "required_refs": ["dataset_id", "resource_id", "version_id"],
        "optional_refs": ["title", "description"],
        "is_active": true
    }
}
```

---

## 10. Processing Options

### Raster Options

```json
{
    "processing_options": {
        "output_tier": "analysis",
        "crs": "EPSG:4326",
        "raster_type": "auto",
        "default_ramp": null,
        "overwrite": false
    }
}
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `output_tier` | `analysis`, `visualization`, `archive` | `analysis` | COG compression profile |
| `crs` | EPSG code | `EPSG:4326` | Target coordinate system |
| `raster_type` | See table below | `auto` | Raster type hint (physical or domain type) |
| `default_ramp` | See ColorRamp table below | `null` | Override default colormap for visualization |
| `overwrite` | boolean | `false` | Replace existing data |

#### Raster Types (V0.8.17.2)

Raster types are organized into **physical types** (auto-detectable from raster data) and **domain types** (user-specified to refine auto-detection).

**Physical Types** (auto-detectable):

| Value | Description | Auto-Detection |
|-------|-------------|----------------|
| `auto` | Let the system detect type | Default — runs all heuristics |
| `rgb` | 3-band RGB imagery | 3 bands + uint8/16 |
| `rgba` | 4-band RGBA imagery | 4 bands + alpha channel |
| `dem` | Digital Elevation Model | Single-band float, smooth gradients |
| `categorical` | Classified/discrete raster | Single-band, <256 unique integer values |
| `multispectral` | 5+ band satellite imagery | 5+ bands |
| `nir` | Near-infrared composite | 4 bands without alpha |
| `continuous` | Generic single-band continuous | Single-band numeric (catch-all) |
| `vegetation_index` | NDVI, EVI, etc. | Single-band float in [-1, 1] range |

**Domain Types** (user-specified — refine physical detection):

| Value | Description | Default Colormap |
|-------|-------------|-----------------|
| `flood_depth` | Flood depth/extent models | `blues` |
| `flood_probability` | Flood probability surfaces | `blues` |
| `hydrology` | Flow accumulation, drainage, watershed | `ylgnbu` |
| `temporal` | Time-indexed data (deforestation year, etc.) | `spectral` |
| `population` | Population density/count grids | `inferno` |

Domain types are validated using **hierarchical compatibility**: a user-specified domain type is accepted if the physical auto-detection returns a compatible base type (e.g., `flood_depth` is compatible with `dem` or `continuous`). Genuine mismatches (e.g., specifying `dem` for a 3-band RGB) still fail.

#### ColorRamp Values (V0.8.17.2)

The `default_ramp` parameter overrides the type-based default colormap. All values are valid TiTiler `colormap_name` parameters.

| Category | Values |
|----------|--------|
| **Sequential** | `viridis`, `plasma`, `inferno`, `magma`, `cividis` |
| **Terrain** | `terrain`, `gist_earth` |
| **Water** | `blues`, `pubu`, `ylgnbu` |
| **Heat** | `coolwarm`, `rdylbu`, `reds`, `oranges`, `ylorrd` |
| **Vegetation** | `rdylgn`, `piyg`, `brbg`, `prgn` |
| **Classification** | `spectral`, `greys`, `greens`, `purples` |
| **Specialized** | `seismic`, `bwr`, `gnbu`, `orrd`, `ylorbr` |

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

## 11. Output Naming Convention

Platform auto-generates all output paths from identifiers:

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

---

## 12. Idempotency

Platform API is fully idempotent based on identifiers:

```
request_id = SHA256(dataset_id + resource_id + version_id)
```

| Scenario | Response |
|----------|----------|
| First submission | 202 Accepted, job created |
| Duplicate submission (same IDs) | 200 OK, returns existing request |
| Same file, different version_id | 202 Accepted, new job created |

---

## 13. Version Lineage

### Concept

A **lineage** groups all versions of the same dataset/resource combination. The lineage ID is computed from:

```
lineage_id = SHA256(platform_id + dataset_id + resource_id)
```

Note: `version_id` is **excluded** from the lineage hash, so all versions share the same lineage.

### Lineage State

Each lineage tracks:
- **current_latest**: The most recent version (`is_latest=true`)
- **version_ordinal**: Sequential version number (1, 2, 3...)
- **previous_asset_id**: Links to the prior version's asset

### Version Chain Example

```
Lineage: floods/jakarta (lineage_id: c391b297...)
├── v1.0 (ordinal=1, is_latest=false, previous=null)
├── v2.0 (ordinal=2, is_latest=false, previous=v1.0)
└── v3.0 (ordinal=3, is_latest=true,  previous=v2.0)  ← current
```

### Race Condition Prevention

The `previous_version_id` requirement prevents race conditions:

```
┌──────────────┐     ┌──────────────┐
│   Client A   │     │   Client B   │
└──────┬───────┘     └──────┬───────┘
       │                    │
       │  Submit v2.0       │  Submit v2.0
       │  prev=v1.0         │  prev=v1.0
       ▼                    ▼
┌──────────────────────────────────────┐
│           Platform API               │
│  ┌────────────────────────────────┐  │
│  │  DB Constraint:                │  │
│  │  Only ONE is_latest per lineage│  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
       │                    │
       ▼                    ▼
   ✅ Success           ❌ 400 Error
   (v2.0 created)       (v1.0 no longer latest)
```

**Without `previous_version_id`**: Both could succeed, creating corrupt state.

**With `previous_version_id`**: Second client gets clear error message explaining v2.0 is now latest.

### Checking Lineage State

Use dry_run to check lineage before submitting:

```bash
curl -X POST "{BASE_URL}/api/platform/submit?dry_run=true" \
  -d '{"dataset_id": "floods", "resource_id": "jakarta", "version_id": "v3.0", ...}'
```

Response shows current lineage state and suggested parameters:

```json
{
    "lineage_state": {
        "lineage_exists": true,
        "current_latest": {
            "version_id": "v2.0",
            "version_ordinal": 2
        }
    },
    "suggested_params": {
        "previous_version_id": "v2.0",
        "version_ordinal": 3
    }
}
```

---

## 14. Error Handling

### Validation Error (400)

```json
{
    "success": false,
    "error": "Missing required parameter: dataset_id",
    "error_type": "ValidationError"
}
```

### Version Lineage Error (400)

When submitting a new version without the correct `previous_version_id`:

```json
{
    "success": false,
    "error": "Version 'v1.0' already exists for this dataset/resource. Specify previous_version_id='v1.0' to submit a new version.",
    "error_type": "ValidationError"
}
```

When specifying wrong `previous_version_id`:

```json
{
    "success": false,
    "error": "previous_version_id='v0.5' does not match current latest version 'v1.0'",
    "error_type": "ValidationError"
}
```

### Not Found (404)

```json
{
    "success": false,
    "error": "Request not found: abc123...",
    "error_type": "NotFound"
}
```

### Deprecated Endpoint (410)

```json
{
    "success": false,
    "error": "ENDPOINT_DEPRECATED",
    "message": "This endpoint has been removed. Use POST /api/platform/submit instead.",
    "migration": {
        "old_endpoint": "POST /api/platform/raster",
        "new_endpoint": "POST /api/platform/submit"
    }
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

## 15. Deprecated Endpoints

These endpoints return 410 Gone with migration instructions:

| Deprecated | Replacement |
|------------|-------------|
| `POST /api/platform/raster` | `POST /api/platform/submit` |
| `POST /api/platform/raster-collection` | `POST /api/platform/submit` (array file_name) |
| `POST /api/platform/vector` | `POST /api/platform/submit` |

---

## Related Documentation

- **Architecture**: See [TECHNICAL_OVERVIEW.md](../architecture/TECHNICAL_OVERVIEW.md) for system architecture
- **OGC Features API**: See [OGC_FEATURES.md](OGC_FEATURES.md) for vector data access
- **Service Layer**: See [SERVICE_LAYER.md](../architecture/SERVICE_LAYER.md) for TiTiler and data serving
- **Error Reference**: See [ERRORS.md](ERRORS.md) for complete error codes

---

*End of Platform API Guide*
