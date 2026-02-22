# Design: Asset/Release Entity Split

**Date**: 21 FEB 2026
**Status**: APPROVED
**SAFe Type**: Epic
**Related**: V0.9_ASSET_MODEL.md (specification), V0.9_REVIEW.md (justification)

---

## Problem

GeospatialAsset (~40 columns) conflates stable identity with mutable version lifecycle. This caused identity mutation at approval, PK collisions between drafts and approved versions, and a revoke-first workflow that leaks infrastructure constraints into user experience.

## Solution

Split into two entities:

### app.assets (stable container)

```sql
asset_id        VARCHAR(64) PK   -- SHA256(platform_id|dataset_id|resource_id)[:32]
platform_id     VARCHAR(50)      -- "ddh"
dataset_id      VARCHAR(200)     -- promoted from JSONB
resource_id     VARCHAR(200)     -- promoted from JSONB
platform_refs   JSONB            -- optional, for non-DDH platforms
data_type       VARCHAR(10)      -- "raster" | "vector"
release_count   INT DEFAULT 0
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
deleted_at      TIMESTAMPTZ      -- soft delete
deleted_by      VARCHAR(200)
```

### app.asset_releases (versioned artifact)

```sql
release_id              VARCHAR(64) PK    -- SHA256(asset_id|submission_key)[:32]
asset_id                VARCHAR(64) FK    -- → app.assets
version_id              VARCHAR(100)      -- NULL=draft, "v1"/"v2" assigned at approval
suggested_version_id    VARCHAR(100)      -- submitter's suggestion (metadata only)
version_ordinal         INT               -- 1, 2, 3... assigned at approval
revision                INT DEFAULT 1     -- overwrite counter within this release
previous_release_id     VARCHAR(64)       -- FK → self
is_latest               BOOL DEFAULT false
is_served               BOOL DEFAULT true
request_id              VARCHAR(64)       -- links to api_requests

-- Physical outputs
blob_path               VARCHAR(500)      -- rasters
table_name              VARCHAR(63)       -- vectors
stac_item_id            VARCHAR(200)
stac_collection_id      VARCHAR(200)
stac_item_json          JSONB             -- cached STAC dict for materialization
content_hash            VARCHAR(128)
source_file_hash        VARCHAR(64)
output_file_hash        VARCHAR(64)

-- Processing lifecycle
job_id                  VARCHAR(64) FK    -- → app.jobs
processing_status       VARCHAR(20)       -- pending|processing|completed|failed
processing_started_at   TIMESTAMPTZ
processing_completed_at TIMESTAMPTZ
last_error              VARCHAR(2000)
workflow_id             VARCHAR(64)
node_summary            JSONB

-- Approval lifecycle
approval_state          VARCHAR(20)       -- pending_review|approved|rejected|revoked
reviewer                VARCHAR(200)
reviewed_at             TIMESTAMPTZ
rejection_reason        TEXT
approval_notes          TEXT
clearance_state         VARCHAR(20)       -- uncleared|ouo|public
adf_run_id              VARCHAR(100)
cleared_at              TIMESTAMPTZ
cleared_by              VARCHAR(200)
made_public_at          TIMESTAMPTZ
made_public_by          VARCHAR(200)

-- Revocation audit
revoked_at              TIMESTAMPTZ
revoked_by              VARCHAR(200)
revocation_reason       TEXT

-- Timestamps
created_at              TIMESTAMPTZ
updated_at              TIMESTAMPTZ
```

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| version_id assigned at approval | Suggestion at submit, confirmed by human reviewer |
| overwrite=true flag kept | Explicit user intent; overwrite = same release, new revision |
| Multiple releases active simultaneously | v1+v2 both APPROVED; is_latest controls /latest |
| lineage_id eliminated | Asset IS the lineage |
| AssetRevision table eliminated | Release IS the revision history |
| Approved releases immutable | Cannot overwrite APPROVED; must create new release |
| Clean-slate rebuild | Wipe all data/jobs; rebuild creates new tables |

## Eliminated Concepts

- `lineage_id` (asset IS the lineage)
- `AssetRevision` table (release IS the revision)
- `assign_version()` identity mutation (version on release, not asset)
- Revoke-first workflow (drafts coexist with approved)
- 3-tier asset_id fallback (job FK → release_id directly)

## Impact

- **5 files rewrite**: asset.py, asset_repository.py, asset_service.py, asset_approval_service.py, revision_repository.py
- **15 files moderate change**: triggers, handlers, validation, catalog
- **10 files minor update**: web interfaces, package exports
- **3 files no change**: job model, platform model, platform registry

## URL Resolution

```
/floods/jakarta              → Asset lookup
/floods/jakarta/latest       → Release WHERE is_latest AND approved
/floods/jakarta/v1           → Release WHERE version_id='v1'
/floods/jakarta/versions     → All releases ORDER BY ordinal
/floods/jakarta/drafts       → Release WHERE version_id IS NULL
```
