# B2B Domain Review: Consolidated Implementation Plan

**Date**: 27 FEB 2026
**Status**: ALL 10 FIXES IMPLEMENTED (27 FEB 2026) — pending action=rebuild
**Coverage**: 23 files, ~19,000 lines across the full B2B Asset/Release domain
**Source**: Review A (Domain Model) + Review B (API Surface)

---

## Executive Summary

Two adversarial reviews examined the B2B domain end-to-end:

| Review | Scope | Files | Lines | Unique Findings |
|--------|-------|-------|-------|-----------------|
| A — Domain Model & Lifecycle | Entity design, state machines, repositories | 10 | ~6,500 | 13 |
| B — API Surface & Integration | HTTP contracts, lifecycle integration, 3 approval layers | 12 | ~8,500 | 37 |
| **Combined** | **Full B2B domain** | **22** (1 overlap) | **~15,000** | **50 unique** |

**10 fixes** total — 3 CRITICAL, 7 HIGH. No overlap between the two reviews.

---

## Consolidated Top 10 Fixes

Ranked by severity, then by blast radius within severity tier.

| # | Fix | Severity | Effort | Risk | Source |
|---|-----|----------|--------|------|--------|
| 1 | WHERE guard on `update_approval_state()` | CRITICAL | Small | Low | Review A |
| 2 | Unique constraint on `(asset_id, version_ordinal)` + ordinal query fix | CRITICAL | Medium | Medium | Review A |
| 3 | Normalize approval contracts across all 3 layers | CRITICAL | Medium | Medium | Review B |
| 4 | Re-read release after atomic approval | HIGH | Small | Low | Review A |
| 5 | Extract shared 44-column INSERT in release_repository | HIGH | Small | Low | Review A |
| 6 | Raster unpublish must use Release's authoritative `stac_item_id` | HIGH | Small | Low | Review B |
| 7 | Collection-level unpublish must revoke individual releases | HIGH | Medium | Medium | Review B |
| 8 | Catalog HTTP status codes, error schema, exception sanitization | HIGH | Medium | Low | Review B |
| 9 | Fix DDH `version_id` resolution across catalog/unpublish/resubmit | HIGH | Medium | Medium | Review B |
| 10 | Persist versioning fields in PlatformRegistryRepository | HIGH | Medium | Low | Review A |

---

## Implementation Batches

Grouped by file overlap and dependency order. Each batch can be committed independently.

### Batch 1: Release Repository Hardening

**Files**: `infrastructure/release_repository.py`
**Fixes**: #1, #2, #5
**Effort**: Medium | **Requires**: `action=ensure` after deployment (for Fix #2)

| Fix | What Changes |
|-----|-------------|
| #1 — WHERE guard | Add `AND approval_state = 'pending_review'` to `update_approval_state()` UPDATE. Return `False` on rowcount 0. (~5 lines changed) |
| #2 — Ordinal uniqueness | Fix `get_next_version_ordinal()` to query `WHERE version_ordinal IS NOT NULL` instead of `WHERE version_id IS NOT NULL`. Add `__sql_unique_constraints` to `core/models/asset.py`. (~10 lines changed) |
| #5 — Shared INSERT | Extract `_INSERT_COLUMNS` tuple and `_build_insert_values()` helper. Refactor `create()` and `create_and_count_atomic()` to use them. (~80 lines refactored, net reduction) |

**Dependency**: Fix #2 requires `action=ensure` schema sync to create the new partial unique index. Deploy code first, then run ensure.

**Testing**:
- Fix #1: Verify rejection returns `False` when release is already rejected
- Fix #2: Verify concurrent ordinal assignments get unique values; verify `action=ensure` creates index
- Fix #5: Verify `create()` and `create_and_count_atomic()` produce identical rows

---

### Batch 2: Approval Service Correctness

**Files**: `services/asset_approval_service.py`
**Fixes**: #4
**Effort**: Small

| Fix | What Changes |
|-----|-------------|
| #4 — Re-read release | After `approve_release_atomic()` succeeds, re-read release from DB before passing to `_materialize_stac()` and `_trigger_adf_pipeline()`. (~3 lines added) |

```python
# After line ~158 (approve_release_atomic succeeds):
if not success:
    return {'success': False, 'error': "Atomic approval failed..."}

# Re-read the approved release for accurate downstream operations
release = self.release_repo.get_by_id(release_id)
```

**Testing**: Verify STAC materialization receives `approval_state='approved'` and `version_id` is populated (not None).

---

### Batch 3: Approval Contract Normalization

**Files**: `triggers/trigger_approvals.py`, `triggers/assets/asset_approvals_bp.py`, `triggers/admin/admin_approvals.py`
**Fixes**: #3
**Effort**: Medium

Three sub-tasks:

**3a. Standardize actor field to `reviewer`**
- `trigger_approvals.py` revoke handler: change `revoker` → `reviewer` in request body parsing
- All response bodies: use `reviewer` consistently

**3b. Add standard response envelope to admin layer**
- All admin success responses: add `"success": true`
- All admin error responses: add `"success": false` and `"error_type"`
- Replace silent `body = {}` on JSON parse failure with 400 response:
```python
try:
    req_body = req.get_json()
except ValueError:
    return func.HttpResponse(
        json.dumps({"success": False, "error": "Invalid JSON body", "error_type": "validation_error"}),
        status_code=400, mimetype='application/json'
    )
```
- Locations: `admin_approvals.py` lines 241-242, 359-360, 454-455

**3c. Make `version_id` consistently optional across all layers**
- Platform layer (`trigger_approvals.py` ~line 272): remove hard requirement, auto-generate from ordinal like asset layer does
- Or: document that platform layer requires it and asset/admin layers auto-resolve

**Testing**: Hit all three approval layers with identical payloads. Verify:
- Same field names accepted (`reviewer`, `rejection_reason`)
- Same response shape returned (`success`, `error`, `error_type`)
- Invalid JSON returns 400 on all three layers

---

### Batch 4: Unpublish Lifecycle Fixes

**Files**: `services/platform_translation.py`, `triggers/platform/unpublish.py`
**Fixes**: #6, #7
**Effort**: Medium

| Fix | What Changes |
|-----|-------------|
| #6 — Raster stac_item_id | In `get_unpublish_params_from_request()`, for raster: read `stac_item_id` from Release record (via `get_by_job_id`), fall back to DDH reconstruction only if no release found. (~15 lines) |
| #7 — Collection revocation | In `_handle_collection_unpublish()`, before submitting cleanup jobs: loop through STAC items, resolve each to a Release, call `update_revocation()` on each. (~20 lines) |

**Fix #6 code**:
```python
elif data_type == "raster":
    if request.job_id:
        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()
        release = release_repo.get_by_job_id(request.job_id)
        if release and release.stac_item_id:
            return {
                'stac_item_id': release.stac_item_id,
                'collection_id': release.collection_id or request.dataset_id
            }
    # Fallback: reconstruct from DDH identifiers (pre-V0.9 releases)
    stac_item_id = generate_stac_item_id(request.dataset_id, request.resource_id, request.version_id)
    return {'stac_item_id': stac_item_id, 'collection_id': request.dataset_id}
```

**Fix #7** may require adding `get_by_stac_item_id()` to `ReleaseRepository` if it doesn't already exist.

**Testing**:
- Fix #6: Unpublish a V0.9 ordinal-named raster release; verify correct `stac_item_id` is targeted
- Fix #7: Collection unpublish; verify all item releases have `approval_state='revoked'` after completion

---

### Batch 5: Catalog Contract Fixes

**Files**: `triggers/trigger_platform_catalog.py`, `services/platform_catalog_service.py`, `infrastructure/release_repository.py`
**Fixes**: #8, #9
**Effort**: Medium

| Fix | What Changes |
|-----|-------------|
| #8 — HTTP status + error schema | Return 404 for not-found (instead of 200). Standardize error schema to `{success, error, error_type}`. Sanitize 500 responses to generic message (log full exception server-side). (~40 lines across 5 handlers) |
| #9 — DDH version_id | In `lookup_unified()`: query `suggested_version_id` first, fall back to `version_id`. In `unpublish.py` and `resubmit.py`: change `and version_id` to `and version_id is not None` for DDH identifier path. Add `get_by_suggested_version()` to `ReleaseRepository`. (~25 lines) |

**Fix #9 — version_id semantic fix across 3 files**:

| File | Line | Change |
|------|------|--------|
| `triggers/platform/unpublish.py` | 263 | `and version_id` → `and version_id is not None` |
| `triggers/platform/resubmit.py` | 310 | `and version_id` → `and version_id is not None` |
| `services/platform_catalog_service.py` | 542 | Query `suggested_version_id` first, fall back to `version_id` |
| `infrastructure/release_repository.py` | (new) | Add `get_by_suggested_version(asset_id, suggested_version_id)` |

**Testing**:
- Fix #8: Catalog lookup for non-existent asset returns 404; 500 errors don't leak exception details
- Fix #9: Catalog lookup by DDH version finds the correct release; unpublish/resubmit work for drafts (empty version_id)

---

### Batch 6: Platform Registry Persistence

**Files**: `infrastructure/platform_registry_repository.py`
**Fixes**: #10
**Effort**: Medium | **Requires**: Verify columns exist in `app.platforms` table (may need `action=ensure`)

| Fix | What Changes |
|-----|-------------|
| #10 — Versioning fields | Add `nominal_refs`, `version_ref`, `uses_versioning` to all SELECT column lists, the INSERT in `create()`, and the `_row_to_platform()` mapper. (~30 lines across 6 locations) |

**Testing**: Create a Platform with versioning fields set; re-read it; verify all fields round-trip correctly.

---

## Implementation Sequence

```
Batch 1 ──→ Batch 2 ──→ Batch 3 ──┐
(release repo)  (approval svc)  (approval API) │
                                                ├──→ Deploy + action=ensure
Batch 4 ──→ Batch 5 ──────────────┘
(unpublish)  (catalog)

Batch 6 ──────────────────────────────────────→ (independent)
(platform registry)
```

**Recommended order**:
1. **Batch 1** first — CRITICAL fixes, all in one file, highest impact
2. **Batch 2** next — small, unlocks correct STAC materialization
3. **Batch 4** next — fixes unpublish data integrity before Batch 5
4. **Batch 5** next — catalog fixes depend on `get_by_suggested_version()` added here
5. **Batch 3** — approval normalization, largest surface area
6. **Batch 6** — independent, lowest urgency

**After all batches**: Run `action=ensure` to create the new unique constraint from Fix #2 and any missing platform registry columns from Fix #10.

---

## Files Modified (Summary)

| File | Batches | Changes |
|------|---------|---------|
| `infrastructure/release_repository.py` | 1, 5 | WHERE guard, ordinal query, shared INSERT, `get_by_suggested_version()` |
| `core/models/asset.py` | 1 | `__sql_unique_constraints` |
| `services/asset_approval_service.py` | 2 | Re-read release after approval |
| `triggers/trigger_approvals.py` | 3 | `reviewer` field, `version_id` requirement |
| `triggers/assets/asset_approvals_bp.py` | 3 | Verify contract consistency |
| `triggers/admin/admin_approvals.py` | 3 | Response envelope, JSON validation |
| `services/platform_translation.py` | 4 | Raster `stac_item_id` from Release |
| `triggers/platform/unpublish.py` | 4, 5 | Collection revocation, `version_id is not None` |
| `triggers/platform/resubmit.py` | 5 | `version_id is not None` |
| `triggers/trigger_platform_catalog.py` | 5 | HTTP status, error schema, exception sanitization |
| `services/platform_catalog_service.py` | 5 | `suggested_version_id` lookup |
| `infrastructure/platform_registry_repository.py` | 6 | Versioning field persistence |

**12 files modified** across 6 batches. No new files created.

---

## Accepted Risks (Consolidated)

These findings were identified across both reviews but accepted as low-priority:

| Finding | Source | Why Accepted |
|---------|--------|-------------|
| All endpoints `AuthLevel.ANONYMOUS` | B-Gamma-16 | Dev environment; Gateway handles auth. Pre-production requirement. |
| Race in `get_or_overwrite_release()` ordinal | A-Beta-4 | Low traffic; Fix #2's unique constraint is the DB safety net |
| God Object (AssetRelease, 45 fields) | A-Alpha-1 | Flat table projection, not behavior-rich |
| `datetime.utcnow()` in ApiRequest | A-Alpha-7 | Isolated to one model, cosmetic |
| `async def` without `await` | B-Beta-13 | Azure Functions handles correctly |
| Singleton caches connections | B-Gamma-6 | Short-lived warm instances in dev |
| Repository instantiation per call | B-Gamma-18/19/20, A-Beta-5 | Known pattern, documented |
| `clearance_level` dead code in submit | B-Gamma-1 | Feature not yet wired; separate story |
| `dry_run` uses `valid` not `success` | B-Beta-11 | Semantic distinction is appropriate |
| Deprecated endpoint camelCase | B-Beta-9 | Has `Sunset` header; migration expected |
| Offset pagination decorative | B-Gamma-15 | Low traffic; implement when needed |
| STAC rebuild loses audit trail | B-Gamma-14 | Admin-only nuclear option |
| Mixed mimetype vs headers | B-Beta-5 | Cosmetic; both work |
| Legacy shims (approval_id, access_level) | B-Beta-8 | Requires DDH coordination; track separately |
| Vector unpublish no retry | B-Gamma-2 | Low volume |
| Non-atomic release + table creation | A-Gamma-2 | Connection-per-op pattern; known |
| Soft-deleted asset accumulation | A | Low volume, query-indexed |
| `_build_approval_block` crashes if platform_url None | B-Gamma-13 | Config always set in deployed environments |

---

## Architecture Wins (Consolidated)

Preserve these patterns — they represent correct engineering:

| Pattern | Location | Review |
|---------|----------|--------|
| Asset/Release entity split | `core/models/asset.py` | A |
| `approve_release_atomic()` single transaction | `release_repository.py` | A, B |
| `update_revocation()` WHERE guard | `release_repository.py` | A |
| `flip_is_latest()` rollback on target miss | `release_repository.py` | A |
| Advisory locks for find_or_create | `asset_repository.py` | A |
| Deterministic ID generation (SHA256) | `core/models/asset.py`, `submit.py` | A, B |
| Explicit enum parsing in `_row_to_model()` | `release_repository.py` | A |
| V0.9 entity flow in submit | `submit.py` | B |
| Vector unpublish reads from release_tables | `platform_translation.py` | B |
| Anti-corruption layer DDH → CoreMachine | `platform_translation.py` | B |
| Consolidated status with auto-detect | `trigger_platform_status.py` | B |
| B2C sanitization stripping `geoetl:*` | `stac_materialization.py` | B |

---

## Metrics

| Metric | Value |
|--------|-------|
| Total files reviewed | 22 (of 23 in scope; 1 shared) |
| Total lines reviewed | ~15,000 |
| Total raw findings | 60 (Review A: 13 + Review B: 47) |
| Unique findings after dedup | 50 |
| Fixes to implement | 10 |
| Files to modify | 12 |
| Estimated total effort | ~200 lines changed across 6 batches |
| Schema sync required | Yes (`action=ensure` after Batch 1 + Batch 6) |
