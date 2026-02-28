# Adversarial Review B: B2B API Surface & Lifecycle Integration

**Date**: 27 FEB 2026
**Status**: COMPLETE
**Pipeline**: Adversarial Review (Omega -> Alpha + Beta parallel -> Gamma -> Delta)
**Scope Split**: B (Internal vs External)

---

## Scope

**Question**: Does the API surface correctly expose the domain? Are the three approval layers consistent? Does the full lifecycle (submit → status → approve → catalog → unpublish) work as a coherent workflow?

### Files Reviewed (12 files, ~8,500 lines)

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
| `services/platform_translation.py` | 600 | DDH → CoreMachine anti-corruption layer |
| `services/platform_validation.py` | 312 | Pre-flight validation for submit |
| `services/platform_catalog_service.py` | 960 | B2B STAC lookup (never previously reviewed) |
| `services/stac_materialization.py` | 818 | Internal DB → pgSTAC materialization engine |

---

## Pipeline Execution

### Omega (Scope Split Selection)

Selected **Split B: Internal vs External**.

- **Alpha** reviews internal business logic — lifecycle gaps, data flow correctness, missing handlers
- **Beta** reviews external API surface — response shapes, HTTP contracts, naming consistency

This split creates productive tension between "does the internal logic handle all cases?" and "does the API surface honor its contracts?"

### Alpha (Internal Business Logic)

Key findings from the internal correctness review (12 findings):

1. **HIGH: Resubmit doesn't reset Release processing state** — `link_job()` in resubmit only resets `job_id` on the release; `last_error`, `processing_state`, etc. persist from prior failed run. Downstream consumers see stale error state on a fresh job.
2. **HIGH: Unpublish doesn't handle zarr data type** — `_resolve_unpublish_data_type()` only routes to vector and raster handlers. Zarr releases have no unpublish path despite having a submit path via `platform_translation.py`.
3. **MEDIUM: `_resolve_release` for revoke via `asset_id` has TOCTOU race** — fetches latest release, but by the time revocation executes in `update_revocation()`, a newer release may have been submitted and flipped `is_latest`.
4. **MEDIUM: Unpublish revokes release BEFORE submitting cleanup job** — if `create_and_submit_job()` fails after revocation, release is revoked but physical artifacts remain. No rollback mechanism.
5. **MEDIUM: Resubmit DDH lookup requires `version_id`** — falsy check at resubmit.py:310, but submit stores empty string for drafts. DDH identifier lookup is impossible for draft resubmissions.
6. **MEDIUM: Raster unpublish reconstructs `stac_item_id` from DDH IDs** — ignores V0.9 ordinal-based naming convention. A release with `stac_item_id = "dataset-resource-ord1"` gets targeted as `"dataset-resource-v10"`.
7. **MEDIUM: Catalog `lookup_unified` passes DDH `version_id` to `get_by_version()`** — internal `version_id` (set at approval) differs from DDH `version_id`. Lookups silently return no results.
8. **LOW: `_is_zarr_release()` depends on `geoetl:` property** — rebuild paths don't check this flag, so rebuilt items may get wrong output mode.
9. **MEDIUM: Three approval families have inconsistent reject resolution** — platform uses `rejection_reason`, asset layer uses `reason`, admin uses `rejection_reason`. Response shapes differ.
10. **HIGH: Collection-level unpublish doesn't revoke individual releases** — removes STAC collection but leaves all item-level releases in "approved" state in the database.
11. **LOW: Resubmit release linkage fails silently for pre-V0.9 jobs** — old jobs have no `release_id`, so `get_by_job_id()` returns None and release linkage is silently skipped.
12. **LOW: Catalog service exposes internal lineage flags** — `is_latest`, `is_served`, `lineage` dict visible in B2C-facing responses.

### Beta (External API Surface)

Key findings from the API contract review (15 findings):

1. **CRITICAL: `revoker` vs `reviewer` field naming divergence** — platform approve uses `reviewer`, revoke uses `revoker`, asset layer uses `reviewer` for both operations. B2B callers must know which field to send per endpoint per operation.
2. **CRITICAL: `version_id` required in platform approve but optional in asset/admin** — platform approve returns 400 if `version_id` is missing (line 272 of trigger_approvals.py). Asset layer auto-generates from ordinal. Admin doesn't require it. Three layers, three contracts.
3. **HIGH: Admin error responses missing `success` and `error_type` keys** — returns bare `{"error": "message"}` instead of standard `{"success": false, "error": "...", "error_type": "..."}`.
4. **HIGH: Admin success responses missing `success: true`** — all other layers include it, admin omits it.
5. **MEDIUM: Mixed `mimetype` vs `headers` for Content-Type** — admin uses `mimetype='application/json'`, asset layer uses `headers={"Content-Type": "application/json"}`. Both work but indicate inconsistent conventions.
6. **HIGH: Catalog lookup returns HTTP 200 for not-found** — `platform_catalog_lookup` returns 200 with `{"found": false}` instead of 404, breaking standard HTTP semantics.
7. **HIGH: Catalog uses different error schema** — `{"error": "error_code"}` vs standard `{"error": "human message", "error_type": "category"}`.
8. **HIGH: Legacy backward-compat shims violate project rules** — `approval_id` accepted as alias for `asset_id` (trigger_approvals.py:178-179), `clearance_level`/`access_level` aliases in submit. Project rule: "No backward compatibility — fail explicitly."
9. **MEDIUM: Deprecated endpoint returns incompatible response shape** — `platform_job_status` uses camelCase (`jobId`, `jobType`) while current `platform_request_status` uses snake_case.
10. **MEDIUM: HTTP 200 for potentially long-running approve** — `approve_release_atomic()` triggers STAC materialization and ADF pipeline, but returns 200 instead of 202 Accepted.
11. **MEDIUM: `dry_run` uses `valid` instead of `success`** — validation response uses `{"valid": true}` while all other endpoints use `{"success": true}`.
12. **HIGH: Admin swallows invalid JSON** — `body = {}` on parse failure (lines 241-242, 359-360, 454-455 of admin_approvals.py) instead of returning 400 Bad Request.
13. **LOW: Async functions without `await`** — status and catalog handlers declared `async def` but contain no `await` calls.
14. **MEDIUM: Unpublish leaks internal error details** — exception messages and type names in 500 responses.
15. **LOW: Inconsistent default limits** — list endpoints use different defaults (50 vs 100 vs unlimited).

### Gamma (Blind Spot Analysis)

Gamma identified 20 findings, 16 unique to Gamma (not caught by Alpha or Beta):

1. **MEDIUM: Submit parses `clearance_level` but never uses it** — dead code at submit.py:157-165. The parsed `clearance_level` variable is never passed to any downstream function. Callers who provide `clearance_state` at submit believe it's recorded.
2. **MEDIUM: Vector unpublish has no retry support for failed jobs** — raster unpublish checks if prior job failed and allows retry; vector unpublish returns idempotent "success" for any existing request, even if the prior job failed.
3. **HIGH: Unpublish DDH identifier path fails for drafts** — `version_id` falsy check at unpublish.py:263; submit stores empty string for drafts. DDH identifier resolution is impossible for draft unpublish.
4. **MEDIUM: Resubmit + unpublish use incompatible release resolution after job re-link** — resubmit updates release's `job_id`, but if unpublish later uses the old `job_id` from the platform request, `get_by_job_id()` returns None and release revocation is silently skipped.
5. **MEDIUM: Approve via `asset_id` resolves to wrong release after revocation** — `get_draft()` excludes revoked releases, `get_latest()` returns old approved release. User thinks they're acting on newest release.
6. **MEDIUM: Singleton `PlatformResubmitHandler` caches stale DB connections** — module-level singleton at resubmit.py:380-389 caches repository instances; in long-lived Azure Functions processes, connections may go stale.
7. **HIGH: Catalog DDH/internal version_id mismatch confirmed** — confirms Alpha-7 with specific code path at platform_catalog_service.py:542-543.
8. **HIGH: Collection-level unpublish skips release revocation entirely** — extends Alpha-10; code branches to `_handle_collection_unpublish()` at line 187 before the revocation block at line 148-174. Individual item releases are NOT revoked.
9. **MEDIUM: Raster unpublish reconstructs stac_item_id from DDH IDs** — confirms Alpha-6 with specific code at platform_translation.py:153-156.
10. **MEDIUM: Catalog 500 handlers leak exception details** — `str(e)` and `type(e).__name__` in all 5 catalog handlers. Extends Beta-14 to catalog endpoints.
11. **LOW: Asset approval resolution doesn't verify `release.asset_id` matches** — no defense-in-depth check after resolution.
12. **MEDIUM: Status 500 handler exposes raw exceptions** — same pattern as Gamma-10, at trigger_platform_status.py:243-253.
13. **LOW: `_build_approval_block` crashes if `platform_url` is None** — `config.platform_url.rstrip('/')` raises AttributeError.
14. **MEDIUM: STAC rebuild loses `ddh:approved_by` and `ddh:approved_at`** — normal `materialize_item()` adds both; rebuild paths omit them. Post-rebuild items have no approval audit trail.
15. **LOW: Offset pagination parameter parsed but never applied** — `platform_approvals_list` accepts `offset` and includes it in response, but never passes it to repository queries. Pagination is decorative.
16. **HIGH: All approval endpoints use `AuthLevel.ANONYMOUS`** — `reviewer` and `revoker` are self-reported strings, not derived from authenticated identity. Orchestrator is directly accessible via public URL.
17. **LOW: Catalog service hardcodes `"schema": "geo"`** — not read from config, divergence risk.
18. **LOW: Validation service creates duplicate repository instances** — fresh repos per call, not shared with caller.
19. **LOW: Status builder creates 4+ repository instances per call** — cumulative connection overhead.
20. **LOW: Submit lacks transactional consistency between Release and PlatformRequest** — separate operations, partial state possible on failure.

---

## Delta Final Verdict: TOP 5 FIXES

### Fix 1: Normalize approval response contracts across all three layers

**Severity**: CRITICAL
**Effort**: Medium | **Risk**: Medium
**Locations**: `triggers/trigger_approvals.py`, `triggers/assets/asset_approvals_bp.py`, `triggers/admin/admin_approvals.py`
**Covers findings**: Beta-1, Beta-2, Beta-3, Beta-4, Beta-12, Alpha-9

**Problem**: The three approval layers (platform, asset, admin) have divergent contracts that make the B2B API unreliable for callers:

| Aspect | Platform Layer | Asset Layer | Admin Layer |
|--------|---------------|-------------|-------------|
| `version_id` | Required | Auto-generated from ordinal | Not required |
| Actor field (approve) | `reviewer` | `reviewer` | `reviewer` |
| Actor field (revoke) | `revoker` | `reviewer` | N/A |
| Success key in response | `success: true` | `success: true` | Missing |
| Error shape | `{success, error, error_type}` | `{success, error, error_type}` | `{error}` only |
| Invalid JSON handling | Returns 400 | Returns 400 | Silently uses `{}` |
| Reject field | `rejection_reason` | `reason` | `rejection_reason` |

**Fix** (three parts):

1. **Standardize actor field to `reviewer` everywhere** — revoke should accept `reviewer` (the person authorizing revocation), not `revoker`. Update `trigger_approvals.py` revoke handler to read `reviewer` from body.

2. **Add standard response envelope to admin layer** — all responses must include `"success": true/false`. Error responses must include `"error_type"`. Add JSON validation with 400 response on parse failure:
```python
try:
    req_body = req.get_json()
except ValueError:
    return func.HttpResponse(
        json.dumps({"success": False, "error": "Invalid JSON", "error_type": "validation_error"}),
        status_code=400, mimetype='application/json'
    )
```

3. **Make `version_id` consistently optional** — platform layer should auto-generate from ordinal like asset layer does, or all layers should require it. Pick one contract.

---

### Fix 2: Collection-level unpublish must revoke individual releases

**Severity**: HIGH
**Effort**: Medium | **Risk**: Medium
**Locations**: `triggers/platform/unpublish.py` lines 187-193, 469-616
**Covers findings**: Alpha-10, Gamma-8

**Problem**: Collection-level unpublish branches directly to `_handle_collection_unpublish()` at line 187, BEFORE the release revocation block at lines 148-174. The function submits `unpublish_raster` jobs for each STAC item in the collection, but never revokes any of the individual releases in the app database. After collection unpublish completes:
- STAC items are removed from pgSTAC (B2C view is clean)
- Release records remain `approval_state = 'approved'` in the app database
- Status queries show releases as "approved" with no physical data behind them
- A subsequent `action=ensure` schema sync could attempt to re-materialize these ghost releases

**Fix**: Add release revocation loop inside `_handle_collection_unpublish()`:

```python
# After fetching STAC items and before submitting unpublish jobs:
from infrastructure import ReleaseRepository
release_repo = ReleaseRepository()

for item in stac_items:
    stac_item_id = item.get('id')
    release = release_repo.get_by_stac_item_id(stac_item_id)
    if release and release.approval_state == ApprovalState.APPROVED:
        release_repo.update_revocation(
            release_id=release.release_id,
            current_state='approved',
            revoker='system:collection_unpublish',
            reason=f'Collection-level unpublish of {collection_id}'
        )
```

Also add `get_by_stac_item_id()` to `ReleaseRepository` if it doesn't exist, or resolve via `stac_item_id` → `release_id` mapping.

---

### Fix 3: Fix raster unpublish stac_item_id to use Release's authoritative ID

**Severity**: HIGH
**Effort**: Small | **Risk**: Low
**Locations**: `services/platform_translation.py` lines 153-156, `triggers/platform/unpublish.py`
**Covers findings**: Alpha-6, Gamma-9

**Problem**: Raster unpublish reconstructs `stac_item_id` from DDH identifiers via `generate_stac_item_id(dataset_id, resource_id, version_id)`. This ignores V0.9 ordinal-based naming. A release submitted as ordinal 1 gets `stac_item_id = "dataset-resource-ord1"` (set during submit at lines 359-370 of submit.py), but raster unpublish reconstructs `"dataset-resource-v10"` or `"dataset-resource-draft"`. The unpublish job targets a non-existent STAC item.

Vector unpublish correctly reads from the `release_tables` junction table (platform_translation.py:134-152), so the pattern already exists.

**Fix**: Mirror the vector pattern — read `stac_item_id` from the Release record:

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
    # Fallback to reconstruction only if no release found
    stac_item_id = generate_stac_item_id(request.dataset_id, request.resource_id, request.version_id)
    collection_id = request.dataset_id
    return {'stac_item_id': stac_item_id, 'collection_id': collection_id}
```

---

### Fix 4: Catalog HTTP status codes, error schema, and exception sanitization

**Severity**: HIGH
**Effort**: Medium | **Risk**: Low
**Locations**: `triggers/trigger_platform_catalog.py` (all 5 handlers), `services/platform_catalog_service.py`
**Covers findings**: Beta-6, Beta-7, Gamma-10, Gamma-12

**Problem**: The catalog endpoints have three contract violations:

1. **200 for not-found**: `platform_catalog_lookup` returns HTTP 200 with `{"found": false}` instead of 404. B2B callers checking HTTP status codes will think the request succeeded.

2. **Different error schema**: Catalog uses `{"error": "error_code", "message": str(e), "error_type": type(e).__name__}` while all other endpoints use `{"success": false, "error": "human message", "error_type": "category"}`.

3. **Exception detail leaks**: All 5 catalog handlers and both status handlers return `str(e)` and `type(e).__name__` in 500 responses, leaking PostgreSQL error details, table names, and internal module paths to B2B callers.

**Fix** (three parts):

1. Return 404 when release/asset not found:
```python
if not result.get('found'):
    return func.HttpResponse(
        json.dumps({"success": False, "error": "Asset or release not found", "error_type": "not_found"}),
        status_code=404, ...
    )
```

2. Standardize error schema to match `{"success": false, "error": "message", "error_type": "category"}`.

3. Sanitize 500 responses — log the full exception for debugging, return generic message to caller:
```python
except Exception as e:
    logger.error(f"Catalog lookup failed: {e}", exc_info=True)
    return func.HttpResponse(
        json.dumps({"success": False, "error": "Internal server error", "error_type": "server_error"}),
        status_code=500, ...
    )
```

---

### Fix 5: Fix DDH `version_id` resolution across catalog lookup and unpublish

**Severity**: HIGH
**Effort**: Medium | **Risk**: Medium
**Locations**: `services/platform_catalog_service.py` line 542, `triggers/platform/unpublish.py` line 263, `triggers/platform/resubmit.py` line 310
**Covers findings**: Alpha-7, Gamma-3, Gamma-7, Alpha-5

**Problem**: Three endpoints fail when `version_id` is empty (drafts) or when DDH `version_id` differs from internal Release `version_id`:

1. **Catalog**: `lookup_unified()` passes DDH `version_id` to `release_repo.get_by_version(asset_id, version_id)` which queries internal `version_id`. DDH "v1.0" ≠ internal "v1". Lookup silently returns no results.

2. **Unpublish**: DDH identifier path requires `version_id` to be truthy (line 263: `if dataset_id and resource_id and version_id`). Submit stores empty string for drafts. Draft unpublish via DDH identifiers is impossible.

3. **Resubmit**: Same falsy check on `version_id` at line 310. Draft resubmit via DDH identifiers is impossible.

**Fix**: The `version_id` field has two different semantics — DDH version (external) and Release version (internal). Resolution must translate between them:

1. **For catalog**: Look up by `suggested_version_id` first (which stores the DDH-provided version), fall back to `version_id`:
```python
release = self._release_repo.get_by_suggested_version(asset.asset_id, version_id)
if not release:
    release = self._release_repo.get_by_version(asset.asset_id, version_id)
```

2. **For unpublish and resubmit**: Allow empty-string `version_id` for DDH identifier lookup (drafts):
```python
# Change from:
if dataset_id and resource_id and version_id:
# To:
if dataset_id and resource_id and version_id is not None:
```

3. **Add `get_by_suggested_version()` to ReleaseRepository** if it doesn't exist:
```sql
SELECT * FROM app.asset_releases
WHERE asset_id = %s AND suggested_version_id = %s
ORDER BY created_at DESC LIMIT 1
```

---

## Accepted Risks

These findings were identified but accepted as low-priority or context-appropriate:

| Finding | Why Accepted |
|---------|-------------|
| All endpoints use `AuthLevel.ANONYMOUS` (Gamma-16) | Dev environment; Gateway handles auth in production path. Document as pre-production requirement. |
| `async def` without `await` in handlers (Beta-13) | Azure Functions framework handles this correctly; no runtime impact. |
| Singleton caches stale connections (Gamma-6) | Azure Functions warm instances are short-lived in dev; monitor if issues arise. |
| Repository instantiation per call (Gamma-18/19/20) | Known infrastructure pattern (documented in REMAINING_ISSUES.md from Review A). |
| `clearance_level` dead code in submit (Gamma-1) | Feature not yet wired; remove or implement in separate story. |
| `dry_run` uses `valid` instead of `success` (Beta-11) | Semantic distinction is appropriate (validation ≠ operation success). |
| Deprecated endpoint camelCase shape (Beta-9) | Deprecated with `Sunset` header; callers expected to migrate. |
| Offset pagination not applied (Gamma-15) | Low traffic; implement when pagination is needed. |
| STAC rebuild loses approval audit trail (Gamma-14) | Rebuild is admin-only nuclear option; acceptable data loss in dev. |
| Mixed mimetype vs headers (Beta-5) | Cosmetic; both patterns work in Azure Functions. |
| Legacy shims (`approval_id`, `access_level`) (Beta-8) | Track separately; removal requires DDH platform coordination. |
| Vector unpublish no retry (Gamma-2) | Low volume; can resubmit manually. |
| Resubmit + unpublish incompatible resolution (Gamma-4) | Edge case requiring specific sequence of resubmit → unpublish with old request_id. |

---

## Architecture Wins

These design decisions should be **preserved** — they represent deliberate, correct engineering:

| Pattern | Location | Why It's Good |
|---------|----------|---------------|
| Deterministic request_id generation | `submit.py:117-122` | SHA256-based IDs ensure idempotent re-submission |
| V0.9 entity flow in submit | `submit.py:243-403` | Clean find_or_create → get_or_overwrite → submit → link pipeline |
| Vector unpublish reads from release_tables junction | `platform_translation.py:134-152` | Authoritative source, not reconstructed |
| Anti-corruption layer for DDH → CoreMachine | `platform_translation.py` | Clean boundary between external identifiers and internal job params |
| Consolidated status endpoint with auto-detect | `trigger_platform_status.py:110-170` | Single endpoint handles all ID types gracefully |
| Platform validation with version lineage | `platform_validation.py` | Pre-flight validation prevents bad data from entering pipeline |
| B2C sanitization stripping `geoetl:*` properties | `stac_materialization.py:196-198` | Clean separation of internal processing metadata from public catalog |
| `approve_release_atomic()` single transaction | `release_repository.py` (from Review A) | Correct pattern preserved across API layers |

---

## Finding Counts

| Reviewer | Total | CRITICAL | HIGH | MEDIUM | LOW |
|----------|-------|----------|------|--------|-----|
| Alpha | 12 | 0 | 3 | 5 | 4 |
| Beta | 15 | 2 | 6 | 5 | 2 |
| Gamma | 20 | 0 | 4 | 9 | 7 |
| **Unique** | **37** | **2** | **9** | **14** | **12** |

(10 findings confirmed/extended across reviewers, reducing 47 raw to 37 unique)

---

## Cross-Reference with Review A

Review A (Domain Model & Lifecycle Coherence) produced 5 fixes. No overlap with Review B's Top 5. The two reviews are complementary:

| Review A Focus | Review B Focus |
|---------------|---------------|
| Entity design, state machine completeness | API contract consistency |
| Repository-level concurrency guards | Lifecycle integration across endpoints |
| Domain model invariants | B2B caller experience |
| Advisory lock correctness | Response shape normalization |
| Data model persistence fidelity | Cross-layer behavioral divergence |

---

## Next Steps

1. Implement Review B Top 5 Fixes (prioritized by severity)
2. Implement Review A Top 5 Fixes (if not yet done)
3. Update `COMPLETED_FIXES.md` with resolved findings
4. Track accepted risks in `REMAINING_ISSUES.md`
5. Consider a focused follow-up review on the legacy shim removal (Beta-8) after DDH coordination
