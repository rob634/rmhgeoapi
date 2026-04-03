# Feature F4: Asset Lifecycle Management — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Asset Lifecycle Management is the governance layer that tracks every dataset from submission through approval to potential revocation. It answers the data owner's questions: "What happened to my data after I submitted it?", "Who approved it and when?", "Can I unpublish it?", and "What version is live?"

The system is built on an Asset/Release entity model inspired by software release management. An **Asset** is a stable identity container (SHA256 of platform_id, dataset_id, resource_id) that never changes. A **Release** is a versioned submission attached to an Asset, carrying its own approval state machine, version ordinal, and cached STAC metadata. Multiple releases can coexist under one Asset — `is_latest` is always computed dynamically, never stored.

STAC metadata is built during ETL processing but only published to pgSTAC at approval time. This deferred materialization pattern keeps the STAC catalog clean — only approved data is discoverable by consumers. Symmetric unpublish pipelines exist for all three data types (raster, vector, Zarr), each performing inventory, data deletion, and audit trail recording.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S4.1 | Asset/Release entity model | Done | v0.9.0.0 | Stable identity + versioned releases with ordinals |
| S4.2 | Approval workflow | Done | v0.9.0.0 | draft to approved to revoked state machine |
| S4.3 | STAC materialization at approval | Done | v0.9.0.0 | Cached dict on Release, written to pgSTAC when approved |
| S4.4 | Release audit trail | Done | v0.9.12.1 | Append-only lifecycle logging (APPROVED, REVOKED, OVERWRITTEN) |
| S4.5 | Unpublish orchestration | Done | v0.10.9 | Symmetric teardown for raster, vector, Zarr |
| S4.6 | Version ordinal management | Done | v0.9.0.0 | Reserved at submit, version_id assigned at approval |
| S4.7 | Services block gating | Done | v0.10.9.14 | services=null until release is approved |
| S4.8 | Approval guard | Done | v0.10.9 | DAG-aware: accepts processing status for DAG runs at gate |

---

## Story Detail

### S4.1: Asset/Release Entity Model
**Status**: Done (v0.9.0.0, 23 FEB 2026)

The monolithic GeospatialAsset entity was split into two entities:

**Asset** (stable identity container):
- `asset_id` = SHA256(platform_id | dataset_id | resource_id) — never changes
- `data_type` (raster, vector, zarr)
- `created_at`

**AssetRelease** (versioned submission):
- `release_id` = SHA256(asset_id | submission_key)
- `version_ordinal` (1, 2, 3... reserved at creation)
- `version_id` (assigned at approval, not submission)
- `approval_state` (draft, approved, revoked)
- `processing_status` (pending, processing, completed, failed)
- `stac_item_json` (cached STAC dict)
- `result_data` (ETL handler outputs)

**Key design decisions**:
- `is_latest` is computed, never stored: `ORDER BY version_ordinal DESC LIMIT 1`
- Multiple drafts can coexist under one Asset
- Ordinal naming: tables use `ord1`, `ord2` (not "draft")
- Vector data excluded from STAC — vector discovery via PostGIS/OGC Features only

**Key files**: `core/models/entities.py`, `infrastructure/postgresql.py`

### S4.2: Approval Workflow
**Status**: Done (v0.9.0.0, 23 FEB 2026)

Three-state approval lifecycle:

```
DRAFT ──> APPROVED ──> REVOKED
  │                       
  └──> REJECTED (terminal, no state change on Release)
```

- **Draft**: Created at job submission. ETL processing runs. Multiple drafts coexist.
- **Approved**: Approver assigns version_id. STAC item published to pgSTAC. Data discoverable.
- **Revoked**: Approver-triggered. STAC item deleted. Data hidden but not destroyed.

**Endpoints**: `POST /api/platform/approve`, `POST /api/platform/reject`, `POST /api/platform/revoke`
**Admin UI**: Approve/Reject/Revoke modals in DAG Brain Assets page

**Key files**: `services/asset_approval_service.py`, `triggers/platform/platform_bp.py`

### S4.3: STAC Materialization at Approval
**Status**: Done (v0.9.0.0)

Deferred materialization pattern:
1. ETL handler builds STAC item dict during processing
2. Dict cached on `release.stac_item_json` — NOT published
3. On approval: cached dict sanitized (remove `geoetl:*` and `processing:*` prefixes), TiTiler URLs injected, upserted to pgSTAC
4. On revocation: STAC item deleted from pgSTAC

**Why defer?** ETL may be re-run (overwrite). Approval may change version_id. Separation of concerns: ETL builds data, approval publishes metadata.

**Key files**: `services/stac_materialization.py`, `services/stac/handler_materialize_item.py`

### S4.4: Release Audit Trail
**Status**: Done (v0.9.12.1, 4 MAR 2026)

Append-only lifecycle logging capturing every approval state transition. Events: APPROVED, REVOKED, OVERWRITTEN. Each event records: actor, timestamp, previous state, new state, and full context (release_id, asset_id, version_ordinal). Inline single-transaction audit — no phantom events possible.

**Key files**: `core/models/events.py` (ReleaseAuditEvent), `infrastructure/audit_repository.py`

### S4.5: Unpublish Orchestration
**Status**: Done (v0.10.9)

Three symmetric unpublish workflows, one per data type:

| Workflow | Nodes | What It Deletes |
|----------|:-----:|----------------|
| `unpublish_raster.yaml` | 3 | COG blobs from silver, STAC item, audit record |
| `unpublish_vector.yaml` | 3 | PostGIS table, geo.table_catalog entry, release revocation |
| `unpublish_zarr.yaml` | 3 | Zarr chunks from silver-zarr, STAC item, audit record |

All unpublish handlers are idempotent — re-running on already-deleted data is a no-op.

**Key files**: `workflows/unpublish_*.yaml`, `services/unpublish_handlers.py`

### S4.6: Version Ordinal Management
**Status**: Done (v0.9.0.0)

Version ordinals are reserved at submission time (monotonically increasing integer per Asset). The human-readable `version_id` is assigned by the approver at approval time — not at submission. This ensures the version_id reflects the approval decision, not just the order of submission.

Table naming convention: `geo.{dataset}_{resource}_ord{N}` (e.g., `geo.acled_events_ord1`).

**Key files**: `services/asset_approval_service.py`, `core/models/entities.py`

### S4.7: Services Block Gating
**Status**: Done (v0.10.9.14, 2 APR 2026)

Service URLs (TiTiler visualization, OGC Features links) are only populated on a Release after approval. Before approval, `services = null`. This prevents consumers from accessing pre-approval data through service URLs — they can only browse raw tables via TiPG's two-phase discovery (which is intentional for approver preview).

**Key files**: `triggers/platform/trigger_platform_status.py`

### S4.8: Approval Guard
**Status**: Done (v0.10.9, 29 MAR 2026)

The approval endpoint validates that a release is ready for approval. Epoch 4 releases require `processing_status == 'completed'` (all tasks finished). DAG releases reach the approval gate mid-workflow (`processing_status == 'processing'`) — the guard accepts `processing` when the release has a `workflow_id` (DAG runs set `workflow_id = run_id`). The approval gate task must be in `waiting` status for STAC materialization to proceed.

**Key files**: `services/asset_approval_service.py:154-164`
