# Adversarial Review Plan: B2B Asset/Release Domain

**Date**: 27 FEB 2026
**Status**: PLANNED
**Pipeline**: Adversarial Review (Omega → Alpha + Beta parallel → Gamma → Delta)

---

## Objective

Review the **Asset/Release first-class entities** and their implementation across the submit → approve workflow as a **coherent domain** — not as isolated subsystems.

**Assumption**: ETL works. ETL orchestration works. This review treats everything downstream of job submission and upstream of job completion as a black box. The focus is the B2B domain model: entity design, lifecycle state management, API surface, and the contracts that tie them together.

---

## Why This Review

Four adversarial reviews have been completed (25/25 findings resolved):

| Prior Review | Focus | What It Asked |
|-------------|-------|---------------|
| CoreMachine | ETL orchestration internals | "Does the job engine work?" |
| Vector Workflow | Vector ETL pipeline | "Does vector processing work?" |
| Tiled Raster | COG tiling + pgSTAC | "Does raster tiling work?" |
| Approval Workflow | Approve/reject/revoke mechanics | "Do approval state transitions work?" |
| Submission | Submit entry point | "Does the submit endpoint work?" |

All five asked **"does this subsystem work?"** — none asked **"does this domain make sense as a whole?"**

Specific gaps:
- No review has looked at the Asset/Release entity split as a domain design decision
- No review has traced the full lifecycle: submit → process → approve → publish → catalog → unpublish
- No review has assessed whether the three approval trigger layers (platform, asset, admin) are consistent
- Several files (~4,000 lines) have never been reviewed at all

---

## Scope: The Full B2B Domain

**23 files, ~19,000 lines** across four layers:

### Domain Models (6 files, ~2,500 lines)

| File | Lines | Role |
|------|-------|------|
| `core/models/asset.py` | 721 | Asset (stable identity) + AssetRelease (versioned content) + enums |
| `core/models/platform.py` | 670 | PlatformRequest DTO, ApiRequest thin tracking, enums |
| `core/models/platform_registry.py` | 232 | Platform entity for multi-platform B2B support |
| `core/models/release_table.py` | 82 | Release-to-PostGIS-table junction model |
| `core/models/stac.py` | 388 | STAC data models, AccessLevel enum |
| `core/models/processing_options.py` | 312 | Vector/Raster/Zarr processing option models |

### Repositories (5 files, ~3,300 lines)

| File | Lines | Role |
|------|-------|------|
| `infrastructure/asset_repository.py` | 447 | Asset CRUD + advisory locks for concurrent find_or_create |
| `infrastructure/release_repository.py` | 1,446 | Release lifecycle persistence, atomic approval, version assignment |
| `infrastructure/pgstac_repository.py` | 838 | pgSTAC materialization writes (B2C clean view) |
| `infrastructure/platform_registry_repository.py` | 323 | Platform registry CRUD |
| `infrastructure/release_table_repository.py` | 277 | Release-to-table junction CRUD |

### Services (8 files, ~5,100 lines)

| File | Lines | Role |
|------|-------|------|
| `services/asset_service.py` | 585 | Asset/Release lifecycle orchestration |
| `services/asset_approval_service.py` | 680 | Approval state transitions on AssetRelease |
| `services/platform_translation.py` | 600 | DDH → CoreMachine anti-corruption layer |
| `services/platform_validation.py` | 312 | Pre-flight validation for submit operations |
| `services/platform_catalog_service.py` | 960 | B2B STAC lookup by DDH identifiers |
| `services/platform_job_submit.py` | 245 | Job creation + Service Bus submission |
| `services/stac_materialization.py` | 818 | Internal DB → pgSTAC materialization engine |
| `services/unpublish_handlers.py` | 884 | Revocation + data removal coordination |

### HTTP Triggers (10 files, ~8,100 lines)

| File | Lines | Role |
|------|-------|------|
| `triggers/platform/submit.py` | 453 | POST /api/platform/submit |
| `triggers/platform/resubmit.py` | 451 | POST /api/platform/resubmit |
| `triggers/platform/unpublish.py` | 616 | POST /api/platform/unpublish |
| `triggers/trigger_platform_status.py` | 1,801 | GET /api/platform/status (consolidated) |
| `triggers/trigger_approvals.py` | 1,117 | Platform approval endpoints |
| `triggers/assets/asset_approvals_bp.py` | 775 | Asset-centric approval endpoints |
| `triggers/admin/admin_approvals.py` | 512 | Admin/QA approval endpoints |
| `triggers/trigger_platform_catalog.py` | 573 | B2B STAC catalog lookup |
| `triggers/platform/platform_bp.py` | 808 | Blueprint registration + routing |
| `triggers/trigger_platform.py` | 53 | Facade re-exports (backward compat) |

### Files Never Previously Reviewed

| File | Lines | Note |
|------|-------|------|
| `services/platform_catalog_service.py` | 960 | B2B STAC lookup — never reviewed |
| `triggers/trigger_platform_status.py` | 1,801 | Status/diagnostics — never reviewed |
| `triggers/platform/resubmit.py` | 451 | Resubmit flow — never reviewed |
| `triggers/platform/platform_bp.py` | 808 | Blueprint routing — never reviewed |
| `infrastructure/platform_registry_repository.py` | 323 | Platform registry — never reviewed |
| `core/models/platform_registry.py` | 232 | Platform registry model — never reviewed |
| `core/models/processing_options.py` | 312 | Processing options — never reviewed |

---

## Execution Plan: Two Reviews

19,000 lines is too large for a single adversarial review pass (pipeline is most effective at 5-20 files). Split into two reviews that together cover the full domain.

### Review A — Domain Model & Lifecycle Coherence

**Question**: Does the Asset/Release entity split hold up? Are the state machines complete? Do the repositories honor the domain model's invariants?

**Likely scope split**: Split A (Design vs Runtime) — creates tension between "is the entity design clean?" and "do the state transitions actually work at runtime?"

**~10 files, ~6,500 lines:**

| File | Lines | Why Included |
|------|-------|--------------|
| `core/models/asset.py` | 721 | The entity design itself |
| `core/models/platform.py` | 670 | The request/tracking model |
| `core/models/release_table.py` | 82 | Junction model |
| `core/models/platform_registry.py` | 232 | Multi-platform support model |
| `infrastructure/asset_repository.py` | 447 | Asset persistence contracts |
| `infrastructure/release_repository.py` | 1,446 | Release lifecycle persistence (largest file) |
| `infrastructure/release_table_repository.py` | 277 | Junction persistence |
| `infrastructure/platform_registry_repository.py` | 323 | Platform registry persistence |
| `services/asset_service.py` | 585 | Asset/Release lifecycle orchestration |
| `services/asset_approval_service.py` | 680 | Approval state machine implementation |

**Key questions for Alpha/Beta**:
- Is the Asset (identity) / AssetRelease (content) split the right domain decomposition?
- Are there state transitions missing from the approval/processing state machines?
- Does `release_repository.py` (1,446 lines) have too many responsibilities?
- Do the repository contracts match the domain model invariants?
- Are advisory locks used correctly for concurrent access?

---

### Review B — B2B API Surface & Lifecycle Integration

**Question**: Does the API surface correctly expose the domain? Are the three approval layers consistent? Does the full lifecycle (submit → status → approve → catalog → unpublish) work as a coherent workflow?

**Likely scope split**: Split B (Internal vs External) — creates tension between "does the internal business logic handle all cases?" and "does the external API surface honor its contracts?"

**~12 files, ~8,500 lines:**

| File | Lines | Why Included |
|------|-------|--------------|
| `triggers/platform/submit.py` | 453 | Submit entry point |
| `triggers/platform/resubmit.py` | 451 | Resubmit flow (never reviewed) |
| `triggers/platform/unpublish.py` | 616 | Unpublish entry point |
| `triggers/trigger_platform_status.py` | 1,801 | Status/diagnostics (never reviewed) |
| `triggers/trigger_approvals.py` | 1,117 | Platform approval layer |
| `triggers/assets/asset_approvals_bp.py` | 775 | Asset-centric approval layer |
| `triggers/admin/admin_approvals.py` | 512 | Admin approval layer |
| `triggers/trigger_platform_catalog.py` | 573 | B2B catalog lookup |
| `services/platform_translation.py` | 600 | DDH → CoreMachine translation |
| `services/platform_validation.py` | 312 | Submit pre-flight validation |
| `services/platform_catalog_service.py` | 960 | Catalog service (never reviewed) |
| `services/stac_materialization.py` | 818 | STAC materialization engine |

**Key questions for Alpha/Beta**:
- Are the three approval trigger layers (platform, asset, admin) consistent with each other?
- Does the status endpoint correctly reflect all lifecycle states?
- Is the catalog service returning clean B2C data?
- Does the resubmit flow correctly handle all the states the original submit created?
- Does unpublish properly reverse everything that submit + approve created?
- Are response shapes consistent across all endpoints?

---

## Execution Notes

- Run Review A first — domain model findings may inform Review B's scope
- Review B can reference Review A's findings for context
- Both reviews should reference the accepted risks from prior reviews (see `REMAINING_ISSUES.md`) to avoid re-finding known issues
- After both reviews complete, update `COMPLETED_FIXES.md` with any new findings resolved
