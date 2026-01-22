# Artifact Registry - Internal Asset Tracking

**Created**: 22 JAN 2026
**Status**: Complete
**Epic**: E10 - Data Lineage & Provenance

---

## Overview

The Artifact Registry tracks all data pipeline outputs (COGs, PostGIS tables) with revision history and supersession chains. This enables:

- **Revision History**: Track all versions of an asset over time
- **Lineage Tracking**: Know which job/task created each artifact
- **Duplicate Detection**: Content hash prevents redundant processing
- **Audit Trail**: Soft deletes preserve records for compliance

**Important**: Artifact tracking is **internal only**. The `artifact_id` is never exposed to external clients (DDH, platform consumers). External systems continue using their own identifiers (dataset_id, resource_id, version_id).

---

## Architecture

```
Platform Layer (DDH, Data360)
     │
     │  client_refs: {dataset_id, resource_id, version_id}
     ▼
Orchestrator Layer (CoreMachine)
     │
     │  job_id, task_id
     ▼
Artifact Layer (this system)
     │
     │  artifact_id (internal UUID)
     ▼
Storage Layer (Blob Storage, PostGIS)
```

### Key Design Decisions (20 JAN 2026)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| STAC Item Handling | Delete old, create new with same ID | Keeps STAC catalog consistent |
| COG Blob Handling | Overwrite blob in place | No orphan blobs, same URL |
| Revision Numbering | Global monotonic (never resets) | Clear ordering across all versions |
| Content Hash | Hash output COG after creation | Enables duplicate detection |
| Cleanup Timing | Synchronous | Simpler error handling |
| API Response | artifact_id is INTERNAL ONLY | Clients use their own IDs |

---

## Data Model

### Artifact Table

```sql
CREATE TABLE app.artifacts (
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash VARCHAR(128),           -- SHA256 multihash
    storage_account VARCHAR(64) NOT NULL,
    container VARCHAR(64) NOT NULL,
    blob_path TEXT NOT NULL,
    size_bytes BIGINT,
    content_type VARCHAR(100),
    blob_version_id VARCHAR(64),         -- Azure Blob versioning
    stac_collection_id VARCHAR(255),
    stac_item_id VARCHAR(255),
    client_type VARCHAR(50) NOT NULL,    -- 'ddh', 'data360', etc.
    client_refs JSONB NOT NULL,          -- Client's identifiers
    source_job_id VARCHAR(64),
    source_task_id VARCHAR(100),
    supersedes UUID REFERENCES app.artifacts(artifact_id),
    superseded_by UUID REFERENCES app.artifacts(artifact_id),
    revision INTEGER NOT NULL DEFAULT 1,
    status app.artifact_status NOT NULL DEFAULT 'active',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
```

### Status Lifecycle

```
PENDING ──────► ACTIVE ──────► SUPERSEDED ──────► DELETED
    │              │                                  ▲
    │              │                                  │
    │              └──────────► ARCHIVED ─────────────┘
    │              │
    │              └──────────► DELETED ──────────────
    │                           (via unpublish)
    └──────────────────────────────────────────────────
              (creation failed)
```

| Status | Meaning |
|--------|---------|
| `PENDING` | Being created (not yet complete) |
| `ACTIVE` | Current version (one per client_refs) |
| `SUPERSEDED` | Replaced by newer version |
| `ARCHIVED` | Moved to archive storage tier |
| `DELETED` | Soft deleted (record preserved) |

---

## Supersession Chain

When `overwrite=true`, the system creates a linked list of revisions:

```
┌─────────────────┐    supersedes    ┌─────────────────┐    supersedes    ┌─────────────────┐
│  Artifact v1    │◄─────────────────│  Artifact v2    │◄─────────────────│  Artifact v3    │
│  revision: 1    │                  │  revision: 2    │                  │  revision: 3    │
│  status: SUPER  │──────────────────►  status: SUPER  │──────────────────►  status: ACTIVE │
│  SEDED          │  superseded_by   │  SEDED          │  superseded_by   │                 │
└─────────────────┘                  └─────────────────┘                  └─────────────────┘
```

### Traversal Directions

- **backward**: Follow `supersedes` links (what did this replace?)
- **forward**: Follow `superseded_by` links (what replaced this?)
- **both**: Full chain from oldest to newest

---

## Client Reference Mapping

The `client_refs` JSONB field stores client-specific identifiers:

### DDH (Data Delivery Hub)

```json
{
    "dataset_id": "flood-risk-2024",
    "resource_id": "site-alpha",
    "version_id": "v2.1"
}
```

### Future Clients

```json
// Data360 example
{
    "project_id": "PRJ-123",
    "asset_id": "AST-456"
}

// Manual upload example
{
    "upload_batch": "2024-01-15",
    "filename": "survey_results.tif"
}
```

---

## Storage Types

### Raster Artifacts (COGs)

```python
artifact = service.create_artifact(
    storage_account="rmhazuregeosilver",
    container="silver-cogs",
    blob_path="flood-2024/site-a.tif",
    client_type="ddh",
    client_refs={"dataset_id": "flood-2024", "resource_id": "site-a"},
    stac_collection_id="silver-cogs",
    stac_item_id="flood-2024-site-a",
    content_type="image/tiff",
    size_bytes=52428800,
    ...
)
```

### Vector Artifacts (PostGIS Tables)

```python
artifact = service.create_artifact(
    storage_account="postgis",           # Indicates PostGIS storage
    container="app",                      # Schema name
    blob_path="parcels_v2",              # Table name
    client_type="ddh",
    client_refs={"dataset_id": "parcels", "resource_id": "city-data"},
    stac_collection_id="vectors",
    stac_item_id="parcels-city-data",
    content_type="application/x-postgis-table",
    size_bytes=150000,                   # Row count as size metric
    ...
)
```

---

## Integration Points

### Raster Processing (handler_process_raster_complete.py)

Artifact creation happens in STEP 5 after STAC item creation:

```python
# STEP 5: ARTIFACT REGISTRY
artifact_id = None
if client_refs:
    artifact_service = ArtifactService()
    artifact = artifact_service.create_artifact(
        storage_account=storage_account,
        container=container,
        blob_path=blob_path,
        client_type='ddh',
        client_refs=client_refs,
        stac_collection_id=collection_id,
        stac_item_id=item_id,
        source_job_id=job_id,
        source_task_id=task_id,
        content_hash=cog_hash,
        size_bytes=cog_size,
        content_type='image/tiff',
        overwrite=True  # Platform jobs always overwrite
    )
    artifact_id = str(artifact.artifact_id)
```

### Vector Processing (stac_vector_catalog.py)

Same pattern - STEP 5 after DDH refs upsert:

```python
# STEP 5: ARTIFACT REGISTRY
artifact_service = ArtifactService()
artifact = artifact_service.create_artifact(
    storage_account='postgis',
    container=schema,
    blob_path=table_name,
    client_type='ddh',
    client_refs=client_refs,
    stac_collection_id=collection_id,
    stac_item_id=item.id,
    source_job_id=job_id,
    content_type='application/x-postgis-table',
    size_bytes=row_count,
    overwrite=True
)
```

### Unpublish Workflow

When a dataset is unpublished, the artifact is **NOT deleted**. Instead:

```python
# Mark as DELETED (soft delete - preserves audit trail)
artifact_service.mark_deleted(artifact_id)
```

This preserves the revision history for audit/compliance purposes.

---

## Admin Endpoints

Internal endpoints for artifact inspection (not exposed to external clients):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/artifacts/{artifact_id}` | GET | Get artifact by UUID |
| `/api/admin/artifacts/stac` | GET | Lookup by STAC collection/item |
| `/api/admin/artifacts/job/{job_id}` | GET | Get all artifacts from a job |
| `/api/admin/artifacts/history` | GET | Full revision history |
| `/api/admin/artifacts/{artifact_id}/chain` | GET | Supersession chain traversal |
| `/api/admin/artifacts/{artifact_id}` | DELETE | Soft delete (requires confirm=yes) |
| `/api/admin/artifacts/stats` | GET | Statistics by client type |

### Example: Get Revision History

```bash
curl "https://rmhazuregeoapi.../api/admin/artifacts/history?\
client_type=ddh&\
dataset_id=flood-2024&\
resource_id=site-a"
```

Response:
```json
{
    "client_type": "ddh",
    "client_refs": {"dataset_id": "flood-2024", "resource_id": "site-a"},
    "revision_count": 3,
    "history": [
        {"artifact_id": "...", "revision": 3, "status": "active", ...},
        {"artifact_id": "...", "revision": 2, "status": "superseded", ...},
        {"artifact_id": "...", "revision": 1, "status": "superseded", ...}
    ]
}
```

### Example: Get Supersession Chain

```bash
curl "https://rmhazuregeoapi.../api/admin/artifacts/{artifact_id}/chain?direction=both"
```

---

## Service API

```python
from services.artifact_service import ArtifactService

service = ArtifactService()

# Create artifact (with automatic supersession if overwrite=True)
artifact = service.create_artifact(...)

# Lookups
artifact = service.get_by_id(artifact_id)
artifact = service.get_by_client_refs("ddh", {"dataset_id": "...", "resource_id": "..."})
artifact = service.get_by_stac("collection-id", "item-id")
artifacts = service.get_by_job("job-123")

# History & Lineage
history = service.get_history("ddh", {"dataset_id": "...", "resource_id": "..."})
chain = service.get_supersession_chain(artifact_id, direction="both")

# Status Management
service.mark_deleted(artifact_id)
service.mark_archived(artifact_id)

# Duplicate Detection
existing = service.check_duplicate_content("ddh", client_refs, content_hash)
duplicates = service.find_duplicates(content_hash)

# Statistics
stats = service.get_stats(client_type="ddh")
```

---

## Error Handling

Artifact creation is **non-fatal** - failures log warnings but don't fail the job:

```python
try:
    artifact = artifact_service.create_artifact(...)
    artifact_id = str(artifact.artifact_id)
    logger.info(f"Artifact created: {artifact_id}")
except Exception as artifact_error:
    # Non-fatal - log warning but continue
    logger.warning(f"Artifact creation failed (non-fatal): {artifact_error}")
```

This ensures that artifact tracking issues don't break the data pipeline.

---

## File Locations

| Component | Path |
|-----------|------|
| Model | `core/models/artifact.py` |
| Repository | `infrastructure/artifact_repository.py` |
| Service | `services/artifact_service.py` |
| Admin Endpoints | `triggers/admin/admin_artifacts.py` |
| Raster Integration | `services/handler_process_raster_complete.py` (STEP 5) |
| Vector Integration | `services/stac_vector_catalog.py` (STEP 5) |

---

## Future Enhancements

1. **Content-Based Deduplication**: Skip processing if content hash matches existing artifact
2. **Archive Policy**: Automatic archival of old superseded versions
3. **Retention Policy**: Configurable retention period for deleted artifacts
4. **Cross-Client Linking**: Track same physical asset used by multiple clients
