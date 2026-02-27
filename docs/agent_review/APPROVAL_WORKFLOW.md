# Adversarial Analysis: Platform Approval Workflow

**Date**: 27 FEB 2026
**Pipeline**: Omega → Alpha + Beta (parallel) → Gamma → Delta
**Target**: Approve / Reject / Revoke lifecycle across 3 trigger layers, 1 service, 1 materialization engine, 1 repository, 1 model
**Files Reviewed**: 7 files, ~5,500 LOC
**Result**: 5 of 5 TOP FIXES RESOLVED — commit `088aca9`. 362 tests passing. See `COMPLETED_FIXES.md` for details.

---

## Scope

| # | File | LOC | Role |
|---|------|-----|------|
| 1 | `triggers/trigger_approvals.py` | 1,171 | Platform approval triggers (primary) |
| 2 | `triggers/assets/asset_approvals_bp.py` | 838 | Asset-centric approval endpoints (gateway) |
| 3 | `triggers/admin/admin_approvals.py` | 537 | Admin/QA approval endpoints |
| 4 | `services/asset_approval_service.py` | 635 | V0.9 release-based approval service |
| 5 | `services/stac_materialization.py` | 762 | pgSTAC materialization engine |
| 6 | `infrastructure/release_repository.py` | 1,408 | Release state persistence + atomic ops |
| 7 | `core/models/asset.py` | ~720 | ApprovalState/ClearanceState enums, AssetRelease model |

**Scope Split**: B — Internal vs External (chosen because the approval workflow IS the boundary between internal state machine logic and external side effects to pgSTAC, ADF, and TiTiler)

---

## Delta: Final Actionable Report

### EXECUTIVE SUMMARY

The platform approval workflow is architecturally sound — the V0.9 Asset/Release entity split is well-designed, the atomic approval transaction in `approve_release_atomic()` is correct and handles concurrency, and the service layer cleanly separates concerns. However, there are two genuinely dangerous bugs: tiled revocation deletes ALL items in a pgSTAC collection (not just the revoked release's items), and all approval endpoints are anonymous with caller-supplied reviewer/revoker strings that are persisted to the audit trail without any authentication. The post-atomic STAC materialization and stac_item_id update (lines 179-199 of `asset_approval_service.py`) represent a real consistency gap, though it fails toward the less-harmful direction (approved in DB, STAC lagging). Error handlers across all three trigger layers leak internal exception class names and messages to unauthenticated callers. These top issues are all fixable with targeted changes and do not require architectural rework.

---

### TOP 5 FIXES — ALL RESOLVED (commit `088aca9`)

| # | Sev | Fix | Resolution |
|---|------|-----|------------|
| 1 | CRITICAL | Tiled revocation deletes ALL collection items | Items tagged `ddh:release_id` at materialization; deletion filtered to matching items; legacy fail-safe skip |
| 2 | HIGH | Exception handlers leak `str(e)` to callers | `safe_error_response()` helper in `http_base.py`; 18 catch blocks sanitized across 3 trigger layers |
| 3 | LOW | `reject_release()` uses `can_approve()` guard | Changed to `can_reject()` |
| 4 | MEDIUM | `approve_release_atomic()` doesn't clear `rejection_reason` | Added `rejection_reason = NULL` to both SQL branches |
| 5 | HIGH | Post-atomic STAC failure undetected | try/except wrapper, CRITICAL log, `last_error` field persistence via `update_last_error()` |

---

### ACCEPTED RISKS

| ID | Sev | Finding | Rationale |
|----|-----|---------|-----------|
| A1 | CRITICAL | All approval endpoints ANONYMOUS, no auth | Dev/internal environment (v0.9.x). Not internet-facing. APIM will handle auth in production. Revisit when exposed externally. |
| A2 | MEDIUM | TOCTOU race in revoke `is_latest` flip (asset_approval_service.py lines 400-418) | Revocation is rare, human-initiated. Worst outcome is temporarily incorrect `is_latest`, fixable manually. Revisit for concurrent reviewers. |
| A3 | MEDIUM | `_materialize_tiled_from_cog_metadata` uses first item's bbox (stac_materialization.py line 321) | Fallback path only. `materialize_collection()` recalculates extent immediately after. Overwritten in same request. |
| A4 | MEDIUM | `stac_item_json` JSONB exposed in `to_dict()` responses (asset.py line 683) | Admin API responses only, not public STAC catalog. Requires `to_api_dict()` split. Revisit when approval API exposed to non-admins. |
| A5 | MEDIUM | No upper bound on `limit` in `platform_approvals_list` (trigger_approvals.py line 710) | Admin tool, not internet-facing. Add `min(limit, 1000)` when exposed via APIM. |
| A6 | MEDIUM | Dual ordinal computation strategies (release_repository.py lines 510-537 vs platform_validation.py lines 167-172) | Different purposes: authoritative vs UI suggestion. Unique index prevents actual collisions. |
| A7 | MEDIUM | ADF pipeline trigger failure swallowed (asset_approval_service.py lines 218-222) | Action set to `approved_public_adf_failed` in response. Log warning written. No persistent state or retry. Revisit when ADF pipeline is production-critical. |
| A8 | MEDIUM | `update_overwrite()` does not reset 17+ stale fields (release_repository.py lines 927-942) | Processing typically overwrites these. Risk is stale data from prior submission surviving into new approval. Revisit when overwrite flow is production-critical. |
| A9 | MEDIUM | Inconsistent response shapes across 3 trigger layers | Platform returns structured fields, asset/admin return raw service result. Revisit during API standardization. |
| A10 | MEDIUM | No timeout/circuit-breaker on pgSTAC operations during materialization | Tiled loop over hundreds of items has no timeout. Revisit when tiled datasets reach production scale. |
| A11 | MEDIUM | `_lookup_releases_by_table_names` executes 2N queries (trigger_approvals.py lines 1104-1133) | Batch query optimization. Revisit if table_names lookups become frequent. |
| A12 | LOW | `_resolve_release()` paths 1-3 bypass operation-aware filtering (trigger_approvals.py lines 85-115) | State guard in service layer catches it. Low risk. |
| A13 | LOW | `version_ordinal=0` sentinel fragile (release_repository.py line 1358) | `or 0` converts NULL and 0 identically. Consistent but fragile. |
| A14 | LOW | Admin blueprint swallows JSON parse failures (admin_approvals.py lines 251-253) | Field validation catches missing fields. Confusing error message, not a bug. |
| A15 | LOW | `_materialize_tiled_from_cog_metadata` inserts potentially stale data (stac_materialization.py lines 308-351) | Fallback path. No staleness check. Low likelihood of firing. |
| A16 | LOW | Admin approve/reject fallback resolves to already-approved release | Fails safely via `can_approve()` guard. Returns clean error, not a crash. |

---

### ARCHITECTURE WINS

1. **Atomic approval transaction**: `approve_release_atomic()` (release_repository.py, lines 1140-1283) correctly combines `flip_is_latest`, version assignment, approval state, and clearance into a single DB transaction with a `WHERE approval_state = 'pending_review'` guard. Textbook optimistic concurrency control. Two concurrent approvals fail cleanly. Preserve this pattern.

2. **DB-first, STAC-second ordering in revoke**: `revoke_release()` (asset_approval_service.py, lines 381-384) deliberately updates the DB before attempting STAC deletion. Orphaned STAC item is the less-harmful failure mode because `rebuild_all_from_db()` can reconcile it.

3. **Clean service layer separation**: Three-layer architecture (trigger → service → repository) consistently applied. No layer reaches into another's concerns. Triggers handle HTTP, service handles business logic, repository handles SQL.

4. **`_resolve_release()` unified resolution**: Single resolution function (trigger_approvals.py, lines 47-159) handles five identifier types with operation-aware behavior. Replaces fragile 3-tier fallback. Each path is a direct indexed lookup.

5. **Explicit state machine guards**: `can_approve()`, `can_reject()`, `can_revoke()`, `can_overwrite()` on AssetRelease (lines 631-649) with defense-in-depth via SQL WHERE guards in atomic operations. Two-layer validation prevents state corruption.

6. **B2C sanitization as first-class concern**: `sanitize_item_properties()` strips all `geoetl:*` internal properties before any pgSTAC write, in both happy path and fallback path. `rebuild_collection_from_db()` also applies sanitization.

---

---

## Alpha: Architecture & Internal Logic Review

### STRENGTHS

1. Well-defined state machine guards on model layer (`core/models/asset.py` lines 631-649).
2. Atomic approval transaction with WHERE guard and rollback (`release_repository.py` lines 1140-1283).
3. DB-first ordering on revocation (`asset_approval_service.py` lines 327-453).
4. `update_revocation()` has concurrent-access WHERE guard (`release_repository.py` lines 752-773).
5. `flip_is_latest()` rolls back on target not found (`release_repository.py` lines 1124-1136).
6. `update_overwrite()` resets approval fields (`release_repository.py` lines 909-953).
7. Consistent resolution for revoke across all 3 trigger layers (all use `get_latest()`).

### CONCERNS

| ID | Sev | File | Lines | Impact |
|----|-----|------|-------|--------|
| H1 | HIGH | `asset_approval_service.py` | 287 | `reject_release()` uses `can_approve()` instead of `can_reject()` — semantic bug, fragile if rules diverge |
| H2 | HIGH | `asset_approvals_bp.py` | 180-182, 336-338 | approve/reject fallback to `get_latest()` resolves to APPROVED release — guaranteed state guard failure, misleading error |
| H3 | HIGH | `asset_approval_service.py` | 179-196 | Non-atomic `stac_item_id` update after atomic approval — inconsistency window |
| M1 | MED | `release_repository.py` | 927-942 | `update_overwrite()` does not reset `stac_item_json`, `blob_path`, hash fields — stale data survives |
| M2 | MED | `asset_approval_service.py` | 400-424 | Revoke `is_latest` flip not atomic with revocation — TOCTOU race |
| M3 | MED | `release_repository.py` | 1201-1266 | `approve_release_atomic()` doesn't clear `rejection_reason=NULL` — defense-in-depth gap |
| M4 | MED | `release_repository.py` | 510-537 | `get_next_version_ordinal()` counts only versioned releases — ordinal collision with drafts |
| M5 | MED | `asset_approval_service.py` | 544-553 | Tiled `_delete_stac` deletes ALL items in collection, not just this release's |
| L1 | LOW | `asset.py` / `release_repository.py` | 412-416 / 1358 | `version_ordinal=0` sentinel fragile |
| L2 | LOW | `admin_approvals.py` | 252-253 | Admin blueprint silently swallows JSON parse failures |
| L3 | LOW | `stac_materialization.py` | 319-321 | `_materialize_tiled_from_cog_metadata` uses first item's bbox, not union |

### ASSUMPTIONS

1. Single-writer assumption for `is_latest` (no advisory lock).
2. Ordinals reserved at draft creation, not approval.
3. Each tiled output maps 1:1 to STAC collection.
4. `stac_item_json` always populated before approval for raster releases.
5. `update_clearance()` called separately only for PUBLIC+ADF — timestamps set twice.

---

## Beta: External Interfaces & Boundaries Review

### VERIFIED SAFE

1. Parameterized SQL everywhere in repository layer.
2. Atomic approval with concurrent-access guard.
3. Revocation updates DB before STAC.
4. `update_revocation` concurrency guard.
5. `flip_is_latest` rollback on target miss.
6. B2C sanitization strips `geoetl:*` properties.
7. `json.dumps` with `default=str` for datetime serialization.

### FINDINGS

| ID | Sev | Description | Confidence |
|----|-----|-------------|------------|
| C1 | CRITICAL | All approval endpoints ANONYMOUS with zero auth. `reviewer`/`revoker` caller-supplied free text. No APIM or middleware. | CONFIRMED |
| H1 | HIGH | Exception catch-all handlers leak `str(e)` + `type(e).__name__` across all 3 trigger layers | CONFIRMED |
| H2 | HIGH | `_materialize_tiled_from_cog_metadata` fallback inserts potentially stale data without validation | CONFIRMED |
| H3 | HIGH | Tiled revocation deletes ALL items in collection, not just revoked release's | CONFIRMED |
| M1 | MED | ADF pipeline trigger failure swallowed — no retry, no persistent error state | CONFIRMED |
| M2 | MED | Inconsistent response shapes across 3 trigger layers | PROBABLE |
| M3 | MED | `stac_item_json` JSONB blob exposed in all `to_dict()` responses — leaks internal metadata | CONFIRMED |
| M4 | MED | `limit` parameter has no validation for non-numeric input | CONFIRMED |
| M5 | MED | No timeout/circuit-breaker on pgSTAC operations during materialization | PROBABLE |

### RISKS

| ID | Likelihood | Description |
|----|-----------|-------------|
| R1 | Medium | Approval-then-STAC non-atomicity — DB approved but STAC not materialized, no retry |
| R2 | Low-Med | `_lookup_releases_by_table_names` executes 2N queries per table name |
| R3 | Low | Race condition in `revoke_release` when checking and flipping `is_latest` |

### EDGE CASES

| ID | Scenario | Likelihood | Severity |
|----|----------|-----------|----------|
| E1 | Tiled materialization with empty `item_ids` AND empty `cog_records` returns success with 0 items | Low | Medium |
| E2 | `get_latest` returns None for non-latest approved release in revoke path | Medium | Low |
| E3 | Admin approve endpoint silently accepts empty JSON body | Medium | Low |
| E4 | `dataset_id` without `resource_id` falls through to unclear error | Medium | Low |
| E5 | TiTiler URL injection failure swallowed silently | Low-Med | Medium |

---

## Gamma: Adversarial Contradiction Analysis

### CONTRADICTIONS

**C1: Alpha H2 overstated — fallback is semantically wrong but fails safely.** Alpha claimed the `get_draft() -> get_latest()` fallback is a "guaranteed failure." Gamma confirmed: the resolved APPROVED release hits the `can_approve()` guard which returns `False`, producing a clean error response — not a crash. Severity demoted from Alpha's HIGH to LOW.

**C2: Alpha M2 vs Beta R3 — severity agreement.** Both flagged the revoke TOCTOU race. Gamma confirmed MEDIUM: the guard at line 411 partially mitigates, and revocation is a rare admin operation.

### AGREEMENT REINFORCEMENT (Highest Confidence)

| Finding | Alpha | Beta | Gamma Verdict |
|---------|-------|------|---------------|
| Tiled revocation deletes ALL items | M5 (Medium) | H3 (High) | **CRITICAL** — silent data loss |
| Exception handlers leak internals | Implicit | H1 (High) | **HIGH** — confirmed across all triggers |
| Non-atomic stac_item_id + STAC materialization | H3 (High) | R1 (Risk) | **HIGH** — three separate transactions |

### BLIND SPOTS

| ID | Sev | Finding | Why Both Missed |
|----|-----|---------|-----------------|
| BS-1 | LOW | `_resolve_release()` paths 1-3 bypass operation-aware filtering | Alpha focused on fallback, Beta on auth |
| BS-2 | HIGH | Dual ordinal computation strategies (`get_next_version_ordinal` vs `platform_validation.py`) | Alpha misdiagnosed the SQL filter. Neither traced both paths. |
| BS-3 | MEDIUM | `platform_approvals_list` has no upper bound on `limit` (line 710) | Both focused on action endpoints, not query endpoints |
| BS-4 | MEDIUM | `_lookup_releases_by_table_names` executes 2N queries (not N+1) | Beta identified pattern but didn't verify actual query count |
| BS-5 | HIGH | `update_overwrite()` doesn't reset 17+ fields (Alpha reported only a few) | Alpha identified but underscoped the field list |
| BS-6 | LOW | `version_ordinal=0` sentinel — `or 0` conflates NULL and 0 | Both noted fragility but didn't trace through both code paths |
| BS-7 | SAFE | `approve_release_atomic()` intermediate `is_latest=false` state | Both verified rollback exists but neither confirmed PostgreSQL READ COMMITTED prevents visibility. **Gamma confirmed safe.** |

### SEVERITY RECALIBRATION

| Rank | ID | Severity | Finding | Confidence |
|------|-----|----------|---------|------------|
| 1 | Beta C1 | **CRITICAL** | All endpoints ANONYMOUS, no auth | CONFIRMED |
| 2 | Alpha M5 + Beta H3 | **CRITICAL** | Tiled revocation deletes ALL collection items | CONFIRMED |
| 3 | Alpha H3 + Beta R1 | **HIGH** | Non-atomic stac_item_id + STAC materialization | CONFIRMED |
| 4 | Beta H1 | **HIGH** | Exception handlers leak internal details | CONFIRMED |
| 5 | Beta M1 | **HIGH** | ADF trigger failure swallowed | CONFIRMED |
| 6 | Alpha M1 + BS-5 | **HIGH** | `update_overwrite()` doesn't reset 17+ stale fields | CONFIRMED |
| 7 | Alpha M4 + BS-2 | **HIGH** | Dual ordinal computation strategies | CONFIRMED |
| 8 | Alpha M2 + Beta R3 | **MEDIUM** | TOCTOU race in revoke `is_latest` flip | CONFIRMED |
| 9 | Alpha M3 | **MEDIUM** | `approve_release_atomic()` doesn't clear `rejection_reason` | CONFIRMED |
| 10 | Alpha L3 | **MEDIUM** | Fallback bbox uses first item, not union | CONFIRMED |
| 11 | Beta M3 | **MEDIUM** | `stac_item_json` exposed in `to_dict()` | CONFIRMED |
| 12 | BS-3 | **MEDIUM** | Platform list has no `limit` cap | CONFIRMED |
| 13 | BS-4 | **MEDIUM** | `_lookup_releases_by_table_names` 2N queries | CONFIRMED |
| 14 | Beta M2 | **MEDIUM** | Inconsistent response shapes | PROBABLE |
| 15 | Beta M5 | **MEDIUM** | No timeout on pgSTAC operations | PROBABLE |
| 16 | Alpha H1 | **LOW** | `reject_release()` uses `can_approve()` | CONFIRMED |
| 17 | BS-1 | **LOW** | `_resolve_release()` paths bypass operation filter | CONFIRMED |
| 18 | Alpha L1 + BS-6 | **LOW** | `version_ordinal=0` sentinel fragile | CONFIRMED |
| 19 | Alpha L2 | **LOW** | Admin swallows JSON parse failures | CONFIRMED |
| 20 | Beta H2 | **LOW** | Fallback inserts potentially stale data | CONFIRMED |
| 21 | Alpha H2 | **LOW** | Fallback resolves to approved release (fails safely) | CONFIRMED |

---

## Review Methodology

| Agent | Role |
|-------|------|
| **Omega** | Split: B (Internal vs External) — approval workflow is boundary between state machine and pgSTAC/ADF |
| **Alpha** | Internal logic: state machine, validation, concurrency, data consistency |
| **Beta** | External interfaces: HTTP contracts, service resilience, auth, observability |
| **Gamma** | Contradictions, blind spots, severity recalibration |
| **Delta** | Final prioritized report with TOP 5 FIXES |
