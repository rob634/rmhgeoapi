# Admin0 Setup Workflow - Handoff Document

**Created**: 23 DEC 2025
**Purpose**: Step-by-step instructions for Workflow Claude to set up admin0 boundaries
**Context**: Fresh database needs admin0 PostGIS table for H3 and other system workflows

---

## TL;DR - The Complete Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: Verify World Bank Admin0 in Bronze Storage                         │
│  ───────────────────────────────────────────────────────────────────────────│
│  Container: rmhazuregeobronze                                                │
│  Blob: World_Bank_Global_Administrative_Divisions.geojson                   │
│  (Already uploaded - just verify exists)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: Submit process_vector Job                                           │
│  ───────────────────────────────────────────────────────────────────────────│
│  POST /api/jobs/submit/process_vector                                        │
│  Creates: geo.curated_admin0 table + STAC item in system-vectors            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: Promote as System-Reserved                                          │
│  ───────────────────────────────────────────────────────────────────────────│
│  POST /api/promote                                                           │
│  {is_system_reserved: true, system_role: "admin0_boundaries"}               │
│  Makes admin0 discoverable by H3 and other workflows                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: Verify                                                              │
│  ───────────────────────────────────────────────────────────────────────────│
│  GET /api/promote/system?role=admin0_boundaries                             │
│  GET /api/health (check system_datasets section)                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### 1. Database Schemas Must Exist

```bash
# Rebuild database schemas first (on fresh database)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=full-rebuild&confirm=yes"
```

**Expected schemas after rebuild:**
- `app` - Application metadata (jobs, promoted_datasets, etc.)
- `geo` - PostGIS vector tables + table_metadata registry
- `pgstac` - STAC collections and items
- `h3` - H3 grid tables (if deployed)

### 2. Admin0 Data Source

**Source**: World Bank Global Administrative Divisions
**Location**: Already in Azure Bronze storage

**File details**:
- Container: `rmhazuregeobronze`
- Blob: `World_Bank_Global_Administrative_Divisions.geojson`

**Required columns** (the process_vector job handles geometry automatically):
- ISO3 country code column (e.g., `iso_a3`, `ISO3`, `WB_A3`)
- Country name column (e.g., `name`, `NAME`, `ADMIN`)
- Geometry column (auto-detected)

---

## Step 1: Verify Admin0 Data in Bronze Storage

**Data already exists** - no upload needed.

```bash
# Verify the file exists
az storage blob show \
  --account-name rmhazuregeo \
  --container-name rmhazuregeobronze \
  --name World_Bank_Global_Administrative_Divisions.geojson \
  --auth-mode login
```

**File location**:
- Storage account: `rmhazuregeo` (configured in app settings)
- Container: `rmhazuregeobronze`
- Blob: `World_Bank_Global_Administrative_Divisions.geojson`

---

## Step 2: Submit process_vector Job

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector" \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "blob_name": "World_Bank_Global_Administrative_Divisions.geojson",
    "table_name": "curated_admin0",
    "title": "Admin0 Country Boundaries",
    "description": "World Bank Global Administrative Divisions - System reference for H3 land filtering and ISO3 attribution",
    "attribution": "World Bank",
    "license": "CC-BY-4.0"
  }'
```

### Expected Response

```json
{
  "success": true,
  "job_id": "abc12345-...",
  "job_type": "process_vector",
  "status": "pending",
  "message": "Job submitted successfully"
}
```

### Monitor Job Progress

```bash
# Poll job status (replace JOB_ID)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}"
```

**Expected stages:**
1. `prepare_chunks` - Download, validate, create table, chunk data
2. `upload_chunks` - Parallel upload of chunks to PostGIS
3. `create_stac` - Create STAC item in `system-vectors` collection

### Verify Table Created

```bash
# Check table exists in geo schema
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/curated_admin0"
```

---

## Step 3: Promote as System-Reserved

**CRITICAL**: This step makes admin0 discoverable by H3 and ISO3 attribution services.

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/promote" \
  -H "Content-Type: application/json" \
  -d '{
    "promoted_id": "system-admin0",
    "stac_item_id": "curated_admin0",
    "title": "Admin0 Country Boundaries (System)",
    "description": "World Bank Admin0 boundaries for H3 land filtering and ISO3 attribution",
    "is_system_reserved": true,
    "system_role": "admin0_boundaries",
    "classification": "public",
    "in_gallery": false
  }'
```

### Expected Response

```json
{
  "success": true,
  "promoted_id": "system-admin0",
  "stac_item_id": "curated_admin0",
  "is_system_reserved": true,
  "system_role": "admin0_boundaries",
  "warnings": []
}
```

---

## Step 4: Verify Setup

### 4a. Check System Datasets Endpoint

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/promote/system?role=admin0_boundaries"
```

**Expected Response:**
```json
{
  "success": true,
  "dataset": {
    "promoted_id": "system-admin0",
    "stac_item_id": "curated_admin0",
    "system_role": "admin0_boundaries",
    "is_system_reserved": true,
    ...
  }
}
```

### 4b. Check Health Endpoint

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health" | jq '.system_datasets'
```

**Expected in health response:**
```json
{
  "system_datasets": {
    "admin0_boundaries": {
      "status": "healthy",
      "promoted_id": "system-admin0",
      "table_name": "geo.curated_admin0",
      "row_count": 177
    }
  }
}
```

### 4c. Test OGC Features Query

```bash
# Query admin0 with bbox (should return countries)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/curated_admin0/items?bbox=-10,35,5,45&limit=5"
```

---

## Troubleshooting

### Problem: Job fails at Stage 1 (prepare_chunks)

**Possible causes:**
1. Blob doesn't exist → Check `az storage blob list --account-name rmhazuregeo --container-name rmhazuregeobronze`
2. Invalid geometry → Check Application Insights logs
3. Schema not created → Run `full-rebuild` maintenance action

### Problem: STAC item not created (Stage 3)

**Possible causes:**
1. pgSTAC schema missing → Run `full-rebuild`
2. Collection doesn't exist → Check `curl /api/stac/collections`

**Recovery**: Job is idempotent - resubmit if needed.

### Problem: Promote fails with "STAC item not found"

**Fix**: Verify STAC item exists first:
```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/collections/system-vectors/items/curated_admin0"
```

If missing, re-run process_vector job.

### Problem: "System role already assigned"

**Fix**: Another dataset has `admin0_boundaries` role. Either:
1. Demote existing: `DELETE /api/promote/{old_promoted_id}?confirm_system=true`
2. Or use different promoted_id

---

## Architecture Notes

### Data Flow

```
Bronze Storage          PostGIS               STAC Catalog          Promote Registry
┌─────────────┐        ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
│ World_Bank_ │        │geo.curated_ │        │pgstac.items │        │app.promoted_│
│ Global_Admin│──S1──▶│admin0       │──S3───▶│(system-vecs)│──POST─▶│datasets     │
│ .geojson    │        │             │        │             │        │             │
└─────────────┘        └─────────────┘        └─────────────┘        └─────────────┘
                              │                      │                      │
                              │                      │                      │
                              ▼                      ▼                      ▼
                       geo.table_metadata     STAC item props      system_role lookup
                       (source of truth)      (postgis:table)      (H3, ISO3 services)
```

### How H3 Discovers Admin0

```python
# In bootstrap_h3_land_grid_pyramid.py and iso3_attribution.py:
from services.promote_service import PromoteService

service = PromoteService()
table = service.get_system_table_name('admin0_boundaries')
# Returns: "geo.curated_admin0"
```

**No fallback** - if admin0 not promoted with correct system_role, H3 jobs will fail explicitly.

### Required Table Columns for H3/ISO3

The admin0 table MUST have:
- `iso3` or `iso_a3` or `WB_A3` column (ISO3 country code)
- `name` or `NAME` or `ADMIN` column (country name)
- `geometry` or `geom` column (PostGIS geometry)

World Bank data should have these columns - verify after ingestion.

---

## Quick Reference

| Endpoint | Purpose |
|----------|---------|
| `POST /api/jobs/submit/process_vector` | Create PostGIS table + STAC item |
| `GET /api/jobs/status/{id}` | Monitor job progress |
| `POST /api/promote` | Register promoted dataset |
| `GET /api/promote/system?role=admin0_boundaries` | Verify system role |
| `GET /api/health` | Check system_datasets status |
| `GET /api/features/collections/{table}/items` | Query OGC Features |

---

## Summary for Workflow Claude

**Your mission**: Execute Steps 1-4 above to create and register admin0.

**Data source**: World Bank Global Administrative Divisions (already in `rmhazuregeobronze` container)

**Success criteria**:
1. ✅ `geo.curated_admin0` table exists with country records
2. ✅ STAC item `curated_admin0` in `system-vectors` collection
3. ✅ `GET /api/promote/system?role=admin0_boundaries` returns the dataset
4. ✅ `GET /api/health` shows `admin0_boundaries: healthy`

**After completion**: H3 bootstrap jobs and ISO3 attribution will work correctly.
