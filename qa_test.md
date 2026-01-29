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
│   User clicks              User clicks           User clicks            │
│   "Generate Services"      "Activate"            "Withdraw"             │
│         │                      │                      │                 │
│         ▼                      ▼                      ▼                 │
│   POST /submit            POST /approve         POST /unpublish         │
│         │                      │                      │                 │
│         ▼                      │                      │                 │
│   GET /status/{id}             │                      │                 │
│   (poll until complete)        │                      │                 │
│         │                      │                      │                 │
│         ▼                      ▼                      ▼                 │
│   Preview available       Services live         Services deleted        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| User Action | API Endpoint | Result |
|-------------|--------------|--------|
| Generate Services | `POST /api/platform/submit` → `GET /api/platform/status/{id}` | Services created, preview available |
| Activate | `POST /api/platform/approve` | Services published |
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
    "notes": "Reviewed and approved for publication"
}
```

or

```json
{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "reviewer": "user@worldbank.org"
}
```

or

```json
{
    "approval_id": "apr-abc123",
    "reviewer": "user@worldbank.org"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| request_id | string | Option 1 | Request ID from submit response |
| job_id | string | Option 2 | Job ID from submit response |
| approval_id | string | Option 3 | Approval ID from list approvals |
| reviewer | string | Yes | Email of approving user |
| notes | string | No | Optional review notes |

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
    "message": "Dataset approved successfully"
}
```

**Classification Behavior:**

| Classification | Action on Approval |
|----------------|-------------------|
| `OUO` | Updates STAC metadata with `app:published=true`. Data stays internal. |
| `PUBLIC` | Triggers ADF pipeline to copy data to external zone, then updates STAC. Returns `adf_run_id`. |

**Response Fields:**

| Field | Description |
|-------|-------------|
| `approval_id` | Unique approval record ID |
| `status` | `approved` on success |
| `action` | `stac_updated` (OUO) or `adf_triggered` (PUBLIC) |
| `adf_run_id` | Azure Data Factory run ID (PUBLIC only, null for OUO) |
| `stac_updated` | Whether STAC metadata was updated |
| `classification` | `ouo` or `public` |

**Example curl command:**

```bash
curl -X POST "$BASE_URL/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "5a5f62fd4e0526a30d8aa6fa11fac9ec",
    "reviewer": "user@example.com",
    "notes": "Approved after review"
  }'
```

**Important:** Approval records are only created AFTER the job completes successfully. If you try to approve a job that is still `processing`, you will get a "not found" error. Always poll status until `job_status: "completed"` before approving.

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
| Start processing | POST | `/api/platform/submit` | DDH identifiers + file info |
| Check status | GET | `/api/platform/status/{request_id}` | `request_id` from submit |
| List approvals | GET | `/api/platform/approvals` | Optional: `?status=pending` |
| Get approval | GET | `/api/platform/approvals/{approval_id}` | `approval_id` |
| Batch status | GET | `/api/platform/approvals/status` | `?stac_item_ids=a,b,c` |
| Publish services | POST | `/api/platform/approve` | `request_id`, `job_id`, or `approval_id` |
| Delete services | POST | `/api/platform/unpublish` | `request_id` or `job_id` |

---

## Approval Workflow

When a job completes successfully, an approval record is automatically created with status `pending`. The approval is linked to the `job_id` (source of truth).

```
Job Submitted → Job Completes → Approval Created (pending)
                                      ↓
                              User reviews data
                                      ↓
                    ┌─────────────────┴─────────────────┐
                    ↓                                   ↓
            POST /approve                        POST /reject (future)
                    ↓                                   ↓
            status: approved                    status: rejected
                    ↓
        ┌───────────┴───────────┐
        ↓                       ↓
    OUO: Update STAC       PUBLIC: Trigger ADF
    (internal only)        (copy to external zone)
```

---
