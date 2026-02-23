# Platform API Endpoint Responses

**Captured**: 23 FEB 2026 | **Version**: v0.8.24.0
**Architecture**: V0.9 Asset/Release two-entity model, V0.9.1 clean B2B status response

---

## Endpoint Index

| # | Endpoint | Lookup | Status |
|---|----------|--------|--------|
| 1 | `GET /api/platform/status` | List all requests | WORKS |
| 2 | `GET /api/platform/status/{request_id}` | By request_id | WORKS |
| 3 | `GET /api/platform/status/{asset_id}` | By asset_id (auto-detect) | WORKS (fixed v0.8.24.0) |
| 4 | `GET /api/platform/status/{release_id}` | By release_id (auto-detect) | WORKS (fixed v0.8.24.0) |
| 5 | `GET /api/platform/status/{job_id}` | By job_id (auto-detect) | WORKS (current job_id only) |
| 6 | `GET /api/platform/status?dataset_id=X&resource_id=Y` | By DDH refs | WORKS |
| 7 | `GET /api/platform/status/{id}?detail=full` | Any ID + operational detail | WORKS (added v0.8.24.0) |
| 8 | `GET /api/platform/catalog/asset/{asset_id}` | Catalog view | WORKS |
| 9 | `GET /api/platform/approvals?status=approved` | List approvals | WORKS |
| 10 | `GET /api/platform/approvals/{release_id}` | Single release detail | WORKS |

---

## Standard B2B Response Shape (Endpoints 2-7)

All `/api/platform/status/{id}` lookups return the same clean response:

```json
{
    "success": true,
    "request_id": "5af1552b2ae9d82e3efbb879079584f3",

    "asset": {
        "asset_id": "05cb99e14cffa92e31f5b3fd1944e1cf",
        "dataset_id": "v09-raster-test",
        "resource_id": "dctest",
        "data_type": "raster",
        "release_count": 3
    },

    "release": {
        "release_id": "2c4d935a59dfa9af190d3cc4aeeaad19",
        "version_id": null,
        "version_ordinal": 3,
        "revision": 1,
        "is_latest": false,
        "processing_status": "completed",
        "approval_state": "pending_review",
        "clearance_state": "uncleared"
    },

    "job_status": "completed",

    "outputs": {
        "stac_item_id": "v09-raster-test-dctest-ord3",
        "stac_collection_id": "v09-raster-test",
        "blob_path": "v09-raster-test/dctest/3/dctest_cog_analysis.tif",
        "container": "silver-cogs"
    },

    "services": {
        "preview": "https://rmhtitiler-.../cog/preview.png?url=...",
        "tiles": "https://rmhtitiler-.../cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=...",
        "viewer": "https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=...",
        "stac_collection": "https://rmhazuregeoapi-.../api/collections/v09-raster-test",
        "stac_item": "https://rmhazuregeoapi-.../api/collections/v09-raster-test/items/v09-raster-test-dctest-ord3"
    },

    "approval": {
        "approve_url": "https://rmhazuregeoapi-.../api/platform/approve",
        "asset_id": "05cb99e14cffa92e31f5b3fd1944e1cf",
        "viewer_url": "https://rmhazuregeoapi-.../api/interface/raster-viewer?item_id=...",
        "embed_url": "https://rmhazuregeoapi-.../api/interface/raster-viewer?item_id=...&embed=true"
    },

    "versions": [
        {
            "release_id": "2c4d935a...",
            "version_id": null,
            "approval_state": "pending_review",
            "clearance_state": "uncleared",
            "processing_status": "completed",
            "is_latest": false,
            "version_ordinal": 3,
            "revision": 1,
            "created_at": "2026-02-23T05:50:13.310673"
        },
        {
            "release_id": "bb2ea0fc...",
            "version_id": "v2",
            "approval_state": "approved",
            "clearance_state": "ouo",
            "processing_status": "completed",
            "is_latest": true,
            "version_ordinal": 2,
            "revision": 1,
            "created_at": "2026-02-23T05:43:50.148221"
        },
        {
            "release_id": "a8b1da7b...",
            "version_id": "v1",
            "approval_state": "approved",
            "clearance_state": "ouo",
            "processing_status": "completed",
            "is_latest": false,
            "version_ordinal": 1,
            "revision": 1,
            "created_at": "2026-02-23T05:42:14.319581"
        }
    ]
}
```

### Response Block Summary

| Block | Contents | When Present |
|-------|----------|-------------|
| `asset` | Stable identity: asset_id, dataset_id, resource_id, data_type, release_count | Always (null if not found) |
| `release` | Lifecycle state: release_id, version_id, ordinal, approval/clearance/processing | Always (null if not found) |
| `job_status` | Single status string: `pending`, `processing`, `completed`, `failed` | Always |
| `outputs` | Physical artifacts: blob_path, table_name, stac_item_id, stac_collection_id | When processing completed |
| `services` | Access URLs: preview, tiles, viewer (raster); collection, items (vector); STAC | When processing completed |
| `approval` | Workflow URLs: approve_url, viewer_url, embed_url | Only when `pending_review` + `completed` |
| `versions` | All releases for this asset, sorted newest first | Always (null if no asset) |

---

## 1. GET /api/platform/status

**Purpose**: List all platform requests (api_requests table)
**Returns**: Thin records — no job details, no release info

```json
{
    "success": true,
    "count": 5,
    "requests": [
        {
            "request_id": "1b0b0c4a5c7c1808234eb76b2e98cec6",
            "dataset_id": "v09-revoke-test",
            "resource_id": "rev-raster",
            "version_id": "",
            "job_id": "0b02095b565f60af...",
            "data_type": "raster",
            "asset_id": "b5354d2eca795ed590fd49a9d6098c97",
            "platform_id": "ddh",
            "retry_count": 0,
            "created_at": "2026-02-23T05:48:39.911409",
            "updated_at": "2026-02-23T05:49:21.739167"
        }
    ]
}
```

---

## 2-5. GET /api/platform/status/{id} — Auto-Detect Lookups

All four ID types return the same B2B response shape (see Standard Response above).

| ID Type | Example | Resolution Path |
|---------|---------|-----------------|
| `request_id` | `5af1552b2ae9d82e3efbb879079584f3` | Direct api_requests lookup |
| `job_id` | `6a161119b6441b9a...` | api_requests.job_id match |
| `release_id` | `a8b1da7b27cdb794...` | Release → job_id → api_requests |
| `asset_id` | `05cb99e14cffa92e...` | Asset → latest release → job_id → api_requests |

**Notes**:
- Resolution tries: request_id → job_id → release_id → asset_id (in order)
- If the release has no matching api_requests row (e.g., release_id or asset_id lookup), the response still works — `request_id` will be `null`
- Stale job_ids (overwritten by UPSERT on resubmit) return 404 — use release_id for historical lookups

---

## 6. GET /api/platform/status?dataset_id=X&resource_id=Y

**Purpose**: Full status + version history for a dataset/resource pair
**Returns**: Same B2B shape, plus `lookup_type: "platform_refs"`

Priority logic for selecting the primary release to display:
1. Release with active processing (`pending` or `processing`)
2. Completed draft (no version_id, processing done)
3. Latest approved release
4. Most recent release overall

---

## 7. GET /api/platform/status/{id}?detail=full

**Purpose**: Append operational detail for debugging/internal use
**Returns**: Standard B2B response PLUS a `detail` block

```json
{
    "success": true,
    "request_id": "...",
    "asset": { "..." },
    "release": { "..." },
    "job_status": "completed",
    "outputs": { "..." },
    "services": { "..." },
    "approval": null,
    "versions": [ "..." ],

    "detail": {
        "job_id": "6a161119b6441b9a45465e2b67fc7fb93a33e215704f4b2056b2f41444c8da92",
        "job_type": "process_raster_docker",
        "job_stage": 1,
        "job_result": {
            "cog": {
                "size_mb": 127.07,
                "cog_blob": "v09-raster-test/dctest/3/dctest_cog_analysis.tif",
                "file_size": 133247181,
                "compression": "deflate",
                "raster_type": { "crs": "EPSG:4326", "dtype": "uint8", "shape": [7777, 5030], "band_count": 3 },
                "cog_container": "silver-cogs",
                "file_checksum": "1220d4a93d1a82cffa2508ff6810f6c9...",
                "processing_time_seconds": 18.57
            },
            "stac": { "cached": true, "item_id": "...", "collection_id": "..." },
            "resources": { "final_rss_mb": 466.2, "peak_memory_cog_mb": 466.5, "peak_memory_overall_mb": 591.3 },
            "titiler_urls": { "preview_url": "...", "tilejson_url": "...", "viewer_url": "..." },
            "validation": { "confidence": "VERY_HIGH", "source_crs": "EPSG:4326", "raster_type": "rgb" }
        },
        "task_summary": {
            "total": 1, "completed": 1, "failed": 0,
            "by_stage": { "1": { "total": 1, "completed": 1, "task_types": ["raster_process_complete"] } }
        },
        "urls": {
            "job_status": "/api/jobs/status/6a161119b644...",
            "job_tasks": "/api/dbadmin/tasks/6a161119b644..."
        },
        "created_at": "2026-02-23T05:42:17.172909"
    }
}
```

---

## 8. GET /api/platform/catalog/asset/{asset_id}

**Purpose**: High-level catalog view of an asset with service URLs
**Returns**: Latest served version only — no version history

```json
{
    "found": true,
    "asset_id": "05cb99e14cffa92e31f5b3fd1944e1cf",
    "data_type": "raster",
    "status": {
        "processing": "completed",
        "approval": "approved",
        "clearance": "ouo"
    },
    "metadata": {
        "bbox": null,
        "created_at": "2026-02-23T05:42:13.780368"
    },
    "raster": {
        "blob_path": "v09-raster-test/dctest/2/dctest_cog_analysis.tif",
        "container": "silver-cogs",
        "stac": {
            "collection_id": "v09-raster-test",
            "item_id": "v09-raster-test-dctest-v2"
        },
        "tiles": {
            "xyz": "https://rmhtitiler-.../cog/tiles/{z}/{x}/{y}?url=...",
            "tilejson": "https://rmhtitiler-.../cog/tilejson.json?url=...",
            "preview": "https://rmhtitiler-.../cog/preview?url=...",
            "info": "https://rmhtitiler-.../cog/info?url=...",
            "statistics": "https://rmhtitiler-.../cog/statistics?url=...",
            "viewer": "/api/interface/raster-viewer?url=..."
        }
    },
    "ddh_refs": {
        "dataset_id": "v09-raster-test",
        "resource_id": "dctest",
        "version_id": "v2"
    },
    "lineage": {
        "asset_id": "05cb99e14cffa92e31f5b3fd1944e1cf",
        "version_id": "v2",
        "version_ordinal": 2,
        "is_latest": true,
        "is_served": true
    }
}
```

---

## 9. GET /api/platform/approvals?status=approved

**Purpose**: List releases by approval state
**Returns**: Full release records (all columns including stac_item_json)

```json
{
    "success": true,
    "releases": [
        {
            "release_id": "b3c4d62ca79b8cb9da4fe969763fc7ab",
            "asset_id": "f9a3e3a9939e76e564b4d3308a84808c",
            "version_id": "v2",
            "version_ordinal": 2,
            "revision": 1,
            "is_latest": true,
            "is_served": true,
            "table_name": "v09_vector_test_cutlines_ord2",
            "stac_item_id": "v09-vector-test-cutlines-v2",
            "stac_collection_id": "v09-vector-test",
            "processing_status": "completed",
            "approval_state": "approved",
            "clearance_state": "ouo",
            "reviewer": "claude-qa@example.com",
            "reviewed_at": "2026-02-23T05:45:43.895531"
        }
    ],
    "count": 4,
    "limit": 100,
    "offset": 0,
    "status_counts": {
        "pending_review": 3,
        "approved": 4,
        "rejected": 0,
        "revoked": 1
    }
}
```

---

## 10. GET /api/platform/approvals/{release_id}

**Purpose**: Single release with all columns
**Returns**: Complete release record

```json
{
    "success": true,
    "release": {
        "release_id": "a8b1da7b27cdb794667447ac19ac3113",
        "asset_id": "05cb99e14cffa92e31f5b3fd1944e1cf",
        "version_id": "v1",
        "version_ordinal": 1,
        "revision": 1,
        "is_latest": false,
        "is_served": true,
        "blob_path": "v09-raster-test/dctest/1/dctest_cog_analysis.tif",
        "stac_item_id": "v09-raster-test-dctest-v1",
        "stac_collection_id": "v09-raster-test",
        "stac_item_json": { "...full STAC item..." },
        "processing_status": "completed",
        "approval_state": "approved",
        "clearance_state": "ouo",
        "reviewer": "claude-qa@example.com",
        "reviewed_at": "2026-02-23T05:43:37.754450"
    }
}
```

---

## Vector Response Differences

When the asset is `data_type: "vector"`, the response shape is the same but:

- `outputs` has `table_name` + `schema` instead of `blob_path` + `container`
- `services` has `collection` + `items` (TiPG/OGC Features) instead of `preview` + `tiles` + `viewer` (TiTiler)
- STAC fields are present in both

```json
{
    "outputs": {
        "stac_item_id": "v09-vector-test-cutlines-v1",
        "stac_collection_id": "v09-vector-test",
        "table_name": "v09_vector_test_cutlines_ord1",
        "schema": "geo"
    },
    "services": {
        "collection": "https://tipg-.../collections/geo.v09_vector_test_cutlines_ord1",
        "items": "https://tipg-.../collections/geo.v09_vector_test_cutlines_ord1/items",
        "stac_collection": "https://rmhazuregeoapi-.../api/collections/v09-vector-test",
        "stac_item": "https://rmhazuregeoapi-.../api/collections/v09-vector-test/items/v09-vector-test-cutlines-v1"
    }
}
```

---

## Changes from Pre-v0.8.24.0

| What Changed | Before | After |
|-------------|--------|-------|
| Auto-detect lookups | Only request_id worked; asset_id, release_id, job_id returned 404 | All 4 ID types resolve |
| Response shape | ~140 lines: flat mix of job_result, task_summary, admin URLs, duplicated fields | ~40 lines: separated asset/release/outputs/services/approval/versions |
| `job_result` blob | Always included (80+ lines of raw worker output) | Hidden by default, available via `?detail=full` |
| `task_summary` | Always included | Hidden by default, available via `?detail=full` |
| Admin URLs | Always included (`/api/dbadmin/tasks/...`) | Hidden by default, available via `?detail=full` |
| Version history | Only with `?dataset_id&resource_id` lookup | Always included |
| Outputs source | Parsed from `job_result` (fragile, varies by job type) | Read from Release record (authoritative) |
| Service URLs | 9+ TiTiler URLs + generic STAC search | 3 focused URLs per data type + STAC links |
| Approval block | Mixed into `data_access` section | Separate block, only when `pending_review` |
