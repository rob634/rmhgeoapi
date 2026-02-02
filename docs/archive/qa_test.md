## Base URL

```bash
# Set your environment's base URL
export BASE_URL="https://YOUR-FUNCTION-APP.azurewebsites.net"
```

All endpoints below are relative to this base URL.

---

## Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        DDH → GEOSPATIAL PLATFORM                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   (Optional)            User clicks              User clicks            │
│   Pre-flight            "Generate Services"      "Activate"             │
│         │                      │                      │                 │
│         ▼                      ▼                      ▼                 │
│   GET /health            POST /submit            POST /approve          │
│   POST /validate               │                (+ clearance_level)     │
│         │                      ▼                      │                 │
│         │               GET /status/{id}              │                 │
│         │               (poll until complete)         │                 │
│         │                      │                      │                 │
│         ▼                      ▼                      ▼                 │
│   System ready?          Preview available       Services live          │
│                                                                         │
│                                                  User clicks            │
│                                                  "Withdraw"             │
│                                                       │                 │
│                                                       ▼                 │
│                                                 POST /unpublish         │
│                                                       │                 │
│                                                       ▼                 │
│                                                 Services deleted        │
└─────────────────────────────────────────────────────────────────────────┘
```

| User Action | API Endpoint | Result |
|-------------|--------------|--------|
| Check system (optional) | `GET /api/platform/health` | Verify system is ready |
| Validate file (optional) | `POST /api/platform/validate` | Check file exists, get estimates |
| Generate Services | `POST /api/platform/submit` → `GET /api/platform/status/{id}` | Services created, preview available |
| Activate | `POST /api/platform/approve` (requires `clearance_level`) | Services published |
| Withdraw | `POST /api/platform/unpublish` | All services deleted |
| Update (versionless) | `POST /api/platform/submit` with `overwrite: true` | Services rebuilt, URL stable |

---

## Endpoints

### 1. Submit Data for Processing

Initiates geospatial processing. Returns immediately with a job ID for polling.

```
POST /api/platform/submit
```

**Request Body:**

```json
{
    "dataset_id": "boundaries-2024",
    "resource_id": "admin-regions",
    "version_id": "v1.0",
    "data_type": "vector",
    "container_name": "bronze-landing",
    "file_name": "boundaries.geojson",
    "service_name": "Administrative Boundaries",
    "access_level": "OUO",
    "processing_options": {
        "overwrite": false
    }
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| dataset_id | string | Yes | DDH dataset identifier |
| resource_id | string | Yes | DDH resource identifier |
| version_id | string | Yes | DDH version identifier |
| data_type | string | Yes | `vector` or `raster` |
| container_name | string | Yes | Azure blob container with source file |
| file_name | string | Yes | Source file name |
| service_name | string | Yes | Display name for service |
| access_level | string | Yes | `OUO` or `PUBLIC` |
| processing_options.overwrite | boolean | No | Set `true` for versionless updates |

**Response (202 Accepted):**

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "monitor_url": "/api/platform/status/791147831f11d833c779f8288d34fa5a"
}
```

**Note:** Save `request_id` or `job_id` - these are used for all subsequent operations (approve, unpublish).

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "my-dataset",
    "resource_id": "my-resource",
    "version_id": "v1.0",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "path/to/file.geojson",
    "access_level": "ouo"
  }'
```

---

### 2. Poll Job Status

Check processing status. Poll until `job_status` is `completed` or `failed`.

```
GET /api/platform/status/{request_id}
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `queued` | Job created, waiting to process |
| `processing` | Job actively processing |
| `completed` | Success - preview URLs available |
| `failed` | Failed - check error details |

**Response (processing):**

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_status": "processing",
    "job_stage": 2
}
```

**Response (completed):**

```json
{
    "success": true,
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "job_status": "completed",
    "job_result": {
        "share_url": "https://titiler.example.com/cog/map?url=...",
        "stac": {
            "item_id": "boundaries-2024-admin-regions-v1-0",
            "collection_id": "boundaries-2024"
        }
    }
}
```

**Polling Recommendation:** Poll every 30 seconds. Typical processing time is 1-15 minutes depending on file size.

**Example curl command:**

```bash
# Using request_id from submit response
curl "$BASE_URL/api/platform/status/791147831f11d833c779f8288d34fa5a"

# You can also use job_id
curl "$BASE_URL/api/platform/status/5a5f62fd4e0526a30d8aa6fa11fac9ec"
```

**Important:** The `job_id` can also be used in the status endpoint, not just `request_id`.

---

### 3. Approve (Activate Services)

Called when user clicks "Activate" after previewing. Marks services as published and sets sharing.

```
POST /api/platform/approve
```

**Request Body (use any identifier):**

```json
{
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "reviewer": "user@worldbank.org",
    "clearance_level": "ouo",
    "notes": "Reviewed and approved for publication"
}
```

or

```json
{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "reviewer": "user@worldbank.org",
    "clearance_level": "public"
}
```

or

```json
{
    "approval_id": "apr-abc123",
    "reviewer": "user@worldbank.org",
    "clearance_level": "ouo"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| request_id | string | Option 1 | Request ID from submit response |
| job_id | string | Option 2 | Job ID from submit response |
| approval_id | string | Option 3 | Approval ID from list approvals |
| reviewer | string | **Yes** | Email of approving user |
| clearance_level | string | **Yes** | `ouo` (internal only) or `public` (triggers ADF export) |
| notes | string | No | Optional review notes |

**Clearance Levels (V0.8):**

| Level | Description | Action on Approval |
|-------|-------------|-------------------|
| `ouo` | Official Use Only | Updates STAC metadata with `app:published=true`. Data stays internal. |
| `public` | Public access | Triggers ADF pipeline to copy data to external zone, then updates STAC. Returns `adf_run_id`. |

**Response:**

```json
{
    "success": true,
    "approval_id": "apr-abc123",
    "status": "approved",
    "action": "stac_updated",
    "adf_run_id": null,
    "stac_updated": true,
    "classification": "ouo",
    "clearance_level": "ouo",
    "asset_id": "ast-def456",
    "asset_updated": true,
    "message": "Dataset approved successfully"
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `approval_id` | Unique approval record ID |
| `status` | `approved` on success |
| `action` | `stac_updated` (OUO) or `adf_triggered` (PUBLIC) |
| `adf_run_id` | Azure Data Factory run ID (PUBLIC only, null for OUO) |
| `stac_updated` | Whether STAC metadata was updated |
| `classification` | `ouo` or `public` (legacy field) |
| `clearance_level` | `ouo` or `public` (V0.8 field) |
| `asset_id` | GeospatialAsset ID (V0.8) |
| `asset_updated` | Whether GeospatialAsset was updated (V0.8) |

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "reviewer": "user@example.com",
    "clearance_level": "ouo",
    "notes": "Approved after review"
  }'
```

**Important:**
- `clearance_level` is **mandatory** (V0.8 requirement)
- Approval records are only created AFTER the job completes successfully
- If you try to approve a job that is still `processing`, you will get a "not found" error
- Always poll status until `job_status: "completed"` before approving

---

### 3a. List Approvals

List all approval records with optional filtering.

```
GET /api/platform/approvals
GET /api/platform/approvals?status=pending
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| status | string | Filter by status: `pending`, `approved`, `rejected`, `revoked` |
| limit | int | Max results (default: 100) |
| offset | int | Pagination offset (default: 0) |

**Response:**

```json
{
    "success": true,
    "approvals": [
        {
            "approval_id": "apr-3250e3e1",
            "job_id": "79c3e3eb236911f5fa56fc6a1e3ca3eef1af8d19...",
            "job_type": "vector_docker_etl",
            "classification": "ouo",
            "status": "pending",
            "stac_item_id": "boundaries-admin-v10",
            "stac_collection_id": "system-vectors",
            "reviewer": null,
            "created_at": "2026-01-29T01:40:01.517181",
            "reviewed_at": null
        }
    ],
    "count": 1,
    "limit": 100,
    "offset": 0,
    "status_counts": {
        "pending": 1,
        "approved": 3
    }
}
```

**Example curl command:**

```bash
# List all approvals
curl "$BASE_URL/api/platform/approvals"

# List only pending approvals
curl "$BASE_URL/api/platform/approvals?status=pending"
```

---

### 3b. Get Approval by ID

Get details of a specific approval record.

```
GET /api/platform/approvals/{approval_id}
```

**Response:**

```json
{
    "success": true,
    "approval": {
        "approval_id": "apr-3250e3e1",
        "job_id": "79c3e3eb236911f5fa56fc6a1e3ca3eef1af8d19...",
        "job_type": "vector_docker_etl",
        "classification": "ouo",
        "status": "approved",
        "stac_item_id": "boundaries-admin-v10",
        "stac_collection_id": "system-vectors",
        "reviewer": "user@worldbank.org",
        "notes": "Reviewed and approved",
        "rejection_reason": null,
        "adf_run_id": null,
        "created_at": "2026-01-29T01:40:01.517181",
        "reviewed_at": "2026-01-29T01:45:00.000000"
    }
}
```

---

### 3c. Batch Approval Status Lookup

Check approval status for multiple STAC items at once.

```
GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| stac_item_ids | string | Comma-separated list of STAC item IDs |

**Response:**

```json
{
    "success": true,
    "statuses": {
        "boundaries-admin-v10": "approved",
        "flood-zones-v20": "pending",
        "unknown-item": null
    }
}
```

---

### 3d. Revoke Approval (Reverse Activate)

Revokes a previously approved dataset. This reverses the approval but **preserves the data** (unlike unpublish which deletes everything). Use this when you need to unpublish from view but keep the data for correction or investigation.

```
POST /api/platform/revoke
```

**Request Body (use any identifier):**

```json
{
    "approval_id": "apr-abc123",
    "revoker": "admin@worldbank.org",
    "reason": "Data quality issue found - needs correction"
}
```

or

```json
{
    "stac_item_id": "boundaries-admin-v10",
    "revoker": "admin@worldbank.org",
    "reason": "Incorrect attribution discovered"
}
```

or

```json
{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "revoker": "admin@worldbank.org",
    "reason": "Processing error discovered after approval"
}
```

or

```json
{
    "request_id": "791147831f11d833c779f8288d34fa5a",
    "revoker": "admin@worldbank.org",
    "reason": "Source data was outdated"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| approval_id | string | Option 1 | Approval ID to revoke |
| stac_item_id | string | Option 2 | Find approval by STAC item |
| job_id | string | Option 3 | Find approval by job ID |
| request_id | string | Option 4 | Find approval by Platform request ID |
| revoker | string | **Yes** | Email of person revoking |
| reason | string | **Yes** | Reason for revocation (required for audit trail) |

**Response:**

```json
{
    "success": true,
    "approval_id": "apr-abc123",
    "status": "revoked",
    "stac_updated": true,
    "warning": "Approved dataset has been revoked - this action is logged for audit",
    "message": "Approval revoked successfully"
}
```

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "revoker": "admin@example.com",
    "reason": "Data quality issue found after approval"
  }'
```

**Important:**
- `reason` is **mandatory** for audit trail
- Can only revoke datasets with status `approved`
- Data is **preserved** (PostGIS tables, COG blobs still exist)
- STAC metadata is updated with revocation properties
- To re-publish, submit a new approval with `POST /approve`
- To delete data entirely, use `POST /unpublish` instead

**Revoke vs Unpublish:**

| Aspect | Revoke | Unpublish |
|--------|--------|-----------|
| Purpose | Reverse approval decision | Delete everything |
| Data | Preserved | Deleted |
| STAC | Updated with revocation info | Deleted |
| Reversible | Yes (re-approve) | No (must resubmit job) |
| Audit | Requires reason | No reason required |

---

### 4. Unpublish (Withdraw Services)

Called when user clicks "Withdraw". Deletes all generated services and data.

```
POST /api/platform/unpublish
```

**Request Body (use either identifier):**

```json
{
    "request_id": "791147831f11d833c779f8288d34fa5a"
}
```

or

```json
{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| request_id | string | Option 1 | Request ID from submit response |
| job_id | string | Option 2 | Job ID from submit response |

**Response (202 Accepted):**

```json
{
    "success": true,
    "request_id": "unpublish-abc123",
    "job_type": "unpublish",
    "monitor_url": "/api/platform/status/unpublish-abc123"
}
```

**What gets deleted:**
- PostGIS tables (vector)
- COG blobs (raster)
- STAC catalog items
- All metadata records

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/unpublish" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec"
  }'
```

---

### 5. System Health Check

Check if the platform is ready to accept jobs before submitting.

```
GET /api/platform/health
```

**Response:**

```json
{
    "status": "healthy",
    "ready_for_jobs": true,
    "version": "0.8.0",
    "uptime_seconds": 3600,
    "summary": {
        "database": "healthy",
        "storage": "healthy",
        "service_bus": "healthy",
        "docker_worker": "healthy"
    },
    "jobs": {
        "queue_backlog": 5,
        "processing": 2,
        "failed_last_24h": 1,
        "avg_completion_minutes": 15.3
    },
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `healthy` | All systems operational, ready for jobs |
| `degraded` | Some components have issues but jobs may still work |
| `unavailable` | System cannot accept jobs |

**Component Summary:**

| Component | Description |
|-----------|-------------|
| `database` | PostgreSQL connectivity |
| `storage` | Azure Blob Storage connectivity |
| `service_bus` | Azure Service Bus queue connectivity |
| `docker_worker` | Heavy API Docker worker status |

**Example curl command:**

```bash
curl "$BASE_URL/api/platform/health"
```

**Recommended Usage:** Call health check before submitting jobs to verify the system is ready. If `ready_for_jobs` is `false`, do not submit jobs until the issue is resolved.

---

### 6. Pre-flight Validation

Validate a file before submitting a job. Checks file existence, size, and returns recommended job type.

```
POST /api/platform/validate
```

**Request Body:**

```json
{
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "blob_name": "imagery/large_file.tif"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| data_type | string | Yes | `raster` or `vector` |
| container_name | string | Yes | Azure blob container name |
| blob_name | string | Yes | Path to file within container |

**Response (valid file):**

```json
{
    "valid": true,
    "file_exists": true,
    "file_size_mb": 250.5,
    "data_type": "raster",
    "recommended_job_type": "process_raster_docker",
    "processing_mode": "docker",
    "estimated_minutes": 7,
    "etl_mount_enabled": true,
    "output_mode": "single_cog",
    "estimated_tiles": 1,
    "tiling_threshold_mb": 2000,
    "warnings": null,
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Response (large file - will be tiled):**

```json
{
    "valid": true,
    "file_exists": true,
    "file_size_mb": 5500.0,
    "data_type": "raster",
    "recommended_job_type": "process_raster_docker",
    "processing_mode": "docker",
    "estimated_minutes": 112,
    "etl_mount_enabled": true,
    "output_mode": "tiled",
    "estimated_tiles": 11,
    "tiling_threshold_mb": 2000,
    "warnings": ["Large file (5500.0MB) - will produce ~11 tiles"],
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Response (file not found):**

```json
{
    "valid": false,
    "file_exists": false,
    "file_size_mb": null,
    "data_type": "raster",
    "recommended_job_type": "process_raster_docker",
    "processing_mode": "docker",
    "estimated_minutes": null,
    "warnings": null,
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Raster-specific Fields (V0.8):**

| Field | Description |
|-------|-------------|
| `etl_mount_enabled` | Whether ETL mount is available (expected `true` in production) |
| `output_mode` | `single_cog` (file ≤ 2GB) or `tiled` (file > 2GB) |
| `estimated_tiles` | Number of output tiles (1 for single_cog) |
| `tiling_threshold_mb` | Size threshold for tiling (default: 2000 MB) |

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "blob_name": "imagery/my_image.tif"
  }'
```

**Recommended Usage:** Call validate before submit to:
1. Verify the file exists and is accessible
2. Get estimated processing time
3. Understand if large files will be tiled
4. Catch errors before job submission

---

## 7. Catalog Endpoints (B2B STAC Access)

> **⚠️ UNDER REVIEW**: The lookup endpoint signature is changing. This documentation reflects the current implementation but may be updated.

These endpoints provide DDH-facing access to the STAC catalog without requiring knowledge of STAC API conventions.

### 7a. Lookup by DDH Identifiers

Verify that a STAC item exists for given DDH identifiers. This is the primary endpoint for DDH to verify processing completed.

```
GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z
```

> **⚠️ SIGNATURE UNDER REVIEW** - Parameters may change.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| dataset_id | string | Yes | DDH dataset identifier |
| resource_id | string | Yes | DDH resource identifier |
| version_id | string | Yes | DDH version identifier |

**Response (found):**

```json
{
    "found": true,
    "stac": {
        "collection_id": "flood-hazard-2024",
        "item_id": "magallanes-region-flood",
        "item_url": "/api/platform/catalog/item/flood-hazard-2024/magallanes-region-flood",
        "assets_url": "/api/platform/catalog/assets/flood-hazard-2024/magallanes-region-flood"
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
    },
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Response (not found):**

```json
{
    "found": false,
    "reason": "job_not_completed",
    "message": "Job is still processing...",
    "status_url": "/api/platform/status/a3f2c1b8..."
}
```

**Example curl command:**

```bash
curl "$BASE_URL/api/platform/catalog/lookup?dataset_id=flood-data&resource_id=res-001&version_id=v1.0"
```

---

### 7b. Get STAC Item

Get the full STAC item (GeoJSON Feature) with all metadata and assets.

```
GET /api/platform/catalog/item/{collection_id}/{item_id}
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | string | STAC collection ID |
| item_id | string | STAC item ID |

**Response:**

Returns a standard STAC Item (GeoJSON Feature):

```json
{
    "type": "Feature",
    "stac_version": "1.0.0",
    "id": "magallanes-region-flood",
    "collection": "flood-hazard-2024",
    "geometry": {
        "type": "Polygon",
        "coordinates": [...]
    },
    "bbox": [-75.5, -56.5, -66.5, -49.0],
    "properties": {
        "datetime": "2026-01-15T00:00:00Z",
        "platform:dataset_id": "flood-data",
        "platform:resource_id": "res-001",
        "platform:version_id": "v1.0"
    },
    "assets": {
        "data": {
            "href": "https://storage.blob.core.windows.net/.../cog.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized"
        }
    },
    "links": [...]
}
```

**Example curl command:**

```bash
curl "$BASE_URL/api/platform/catalog/item/flood-hazard-2024/magallanes-region-flood"
```

---

### 7c. Get Asset URLs with TiTiler

Get asset URLs and pre-built TiTiler visualization URLs. This is the primary endpoint for DDH to get URLs for embedding maps in their UI.

```
GET /api/platform/catalog/assets/{collection_id}/{item_id}
GET /api/platform/catalog/assets/{collection_id}/{item_id}?include_titiler=false
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| collection_id | string | STAC collection ID |
| item_id | string | STAC item ID |

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| include_titiler | boolean | true | Include pre-built TiTiler URLs |

**Response:**

```json
{
    "item_id": "magallanes-region-flood",
    "collection_id": "flood-hazard-2024",
    "bbox": [-75.5, -56.5, -66.5, -49.0],
    "assets": {
        "data": {
            "href": "https://storage.blob.core.windows.net/.../cog.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "size_mb": 125.5
        }
    },
    "titiler": {
        "preview": "https://titiler.example.com/cog/preview?url=...",
        "tiles": "https://titiler.example.com/cog/tiles/{z}/{x}/{y}?url=...",
        "info": "https://titiler.example.com/cog/info?url=...",
        "tilejson": "https://titiler.example.com/cog/tilejson.json?url=..."
    },
    "temporal": {
        "datetime": "2026-01-15T00:00:00Z"
    },
    "platform_refs": {
        "dataset_id": "flood-data",
        "resource_id": "res-001",
        "version_id": "v1.0"
    },
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Example curl command:**

```bash
curl "$BASE_URL/api/platform/catalog/assets/flood-hazard-2024/magallanes-region-flood"
```

---

### 7d. List Items for Dataset

List all STAC items for a DDH dataset (all versions/resources).

```
GET /api/platform/catalog/dataset/{dataset_id}
GET /api/platform/catalog/dataset/{dataset_id}?limit=50
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| dataset_id | string | DDH dataset identifier |

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 100 | Maximum items to return (max: 1000) |

**Response:**

```json
{
    "dataset_id": "flood-data",
    "count": 3,
    "items": [
        {
            "item_id": "flood-item-v1",
            "collection_id": "flood-collection",
            "bbox": [-75.5, -56.5, -66.5, -49.0],
            "datetime": "2026-01-15T00:00:00Z",
            "resource_id": "res-001",
            "version_id": "v1.0"
        },
        {
            "item_id": "flood-item-v2",
            "collection_id": "flood-collection",
            "bbox": [-75.5, -56.5, -66.5, -49.0],
            "datetime": "2026-01-20T00:00:00Z",
            "resource_id": "res-001",
            "version_id": "v2.0"
        }
    ],
    "timestamp": "2026-01-29T10:00:00Z"
}
```

**Example curl command:**

```bash
curl "$BASE_URL/api/platform/catalog/dataset/flood-data?limit=50"
```

---

## Versionless Updates

To replace existing data without changing the dataset/resource/version identifiers:

```json
{
    "dataset_id": "boundaries-2024",
    "resource_id": "admin-regions",
    "version_id": "v1.0",
    "data_type": "vector",
    "container_name": "bronze-landing",
    "file_name": "boundaries_updated.geojson",
    "service_name": "Administrative Boundaries",
    "access_level": "OUO",
    "processing_options": {
        "overwrite": true
    }
}
```

**Behavior:**
- Service URLs remain stable
- Format changes (GeoJSON → Shapefile) handled automatically
- Schema changes (new/removed attributes) handled automatically
- Services rebuilt in place

---

## Error Handling

**Validation Error (400):**

```json
{
    "success": false,
    "error": "Missing required parameter: dataset_id",
    "error_type": "ValidationError"
}
```

**File Not Found (400):**

```json
{
    "success": false,
    "error": "Pre-flight validation failed: Blob 'missing.tif' does not exist",
    "error_type": "ValidationError"
}
```

**Server Error (500):**

```json
{
    "success": false,
    "error": "Internal server error",
    "error_type": "RuntimeError"
}
```

---

## Quick Reference

| Action | Method | Endpoint | Key Parameter |
|--------|--------|----------|---------------|
| **Diagnostics** | | | |
| System health | GET | `/api/platform/health` | None |
| Pre-flight validation | POST | `/api/platform/validate` | `data_type`, `container_name`, `blob_name` |
| **Core Workflow** | | | |
| Start processing | POST | `/api/platform/submit` | DDH identifiers + file info |
| Check status | GET | `/api/platform/status/{request_id}` | `request_id` from submit |
| Publish services | POST | `/api/platform/approve` | `request_id` + `reviewer` + `clearance_level` |
| Reverse approval | POST | `/api/platform/revoke` | `request_id` + `revoker` + `reason` |
| Delete services | POST | `/api/platform/unpublish` | `request_id` or `job_id` |
| **Approvals Admin** | | | |
| List approvals | GET | `/api/platform/approvals` | Optional: `?status=pending` |
| Get approval | GET | `/api/platform/approvals/{approval_id}` | `approval_id` |
| Batch status | GET | `/api/platform/approvals/status` | `?stac_item_ids=a,b,c` |
| **Catalog (B2B)** | | | ⚠️ Lookup signature under review |
| Lookup by DDH IDs | GET | `/api/platform/catalog/lookup` | `?dataset_id=X&resource_id=Y&version_id=Z` |
| Get STAC item | GET | `/api/platform/catalog/item/{col}/{item}` | `collection_id`, `item_id` |
| Get asset URLs | GET | `/api/platform/catalog/assets/{col}/{item}` | `collection_id`, `item_id` |
| List dataset items | GET | `/api/platform/catalog/dataset/{dataset_id}` | `dataset_id` |

---

## Approval Workflow

When a job completes successfully, an approval record is automatically created with status `pending`. The approval is linked to the `job_id` (source of truth).

```
Job Submitted → Job Completes → Approval Created (pending)
                                      ↓
                              User reviews data
                                      ↓
                              POST /approve
                              (+ clearance_level)
                                      ↓
                              status: approved
                                      ↓
                    ┌─────────────────┴─────────────────┐
                    ↓                                   ↓
            OUO: Update STAC                   PUBLIC: Trigger ADF
            (internal only)                    (copy to external zone)
                    ↓                                   ↓
                    └─────────────┬─────────────────────┘
                                  ↓
                          Services are LIVE
                                  ↓
                    (if issue found later...)
                                  ↓
                          POST /revoke
                          (+ reason)
                                  ↓
                          status: revoked
                          (data preserved)
                                  ↓
                    ┌─────────────┴─────────────────┐
                    ↓                               ↓
            Fix & re-approve                 POST /unpublish
            (POST /approve again)            (delete everything)
```

**Status Transitions:**

| From | Action | To |
|------|--------|-----|
| `pending` | `POST /approve` | `approved` |
| `approved` | `POST /revoke` | `revoked` |
| `revoked` | `POST /approve` | `approved` |
| any | `POST /unpublish` | (deleted) |

---
