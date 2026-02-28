# Adversarial Review A: Domain Model & Lifecycle Coherence

**Date**: 27 FEB 2026
**Status**: COMPLETE
**Pipeline**: Adversarial Review (Omega -> Alpha + Beta parallel -> Gamma -> Delta)
**Scope Split**: A (Design vs Runtime)

---

## Scope

**Question**: Does the Asset/Release entity split hold up? Are the state machines complete? Do the repositories honor the domain model's invariants?

### Files Reviewed (10 files, ~6,500 lines)

| File | Lines | Role |
|------|-------|------|
| `core/models/asset.py` | 721 | Asset (stable identity) + AssetRelease (versioned content) + enums |
| `core/models/platform.py` | 670 | PlatformRequest DTO, ApiRequest thin tracking, enums |
| `core/models/release_table.py` | 82 | Release-to-PostGIS-table junction model |
| `core/models/platform_registry.py` | 232 | Platform entity for multi-platform B2B support |
| `infrastructure/asset_repository.py` | 447 | Asset CRUD + advisory locks |
| `infrastructure/release_repository.py` | 1,446 | Release lifecycle persistence (largest file) |
| `infrastructure/release_table_repository.py` | 277 | Release-to-table junction CRUD |
| `infrastructure/platform_registry_repository.py` | 323 | Platform registry CRUD |
| `services/asset_service.py` | 585 | Asset/Release lifecycle orchestration |
| `services/asset_approval_service.py` | 680 | Approval state machine implementation |

---

## Pipeline Execution

### Omega (Scope Split Selection)

Selected **Split A: Design vs Runtime**.

- **Alpha** reviews entity design, domain model coherence, schema contracts
- **Beta** reviews runtime correctness, state transitions, concurrency safety

This split creates productive tension between "is the entity design clean?" and "do the state transitions actually work at runtime?"

### Alpha (Design Perspective)

Key findings from the architecture/design review:

1. **Asset/Release entity split is sound** — Asset (~12 fields, stable identity) vs AssetRelease (~45 fields, versioned content) is the right decomposition
2. **`__sql_unique_constraints` is empty** (asset.py:355) — no DB-enforced uniqueness on `(asset_id, version_ordinal)`, relying entirely on application logic
3. **PlatformRegistryRepository drops versioning fields** — `nominal_refs`, `version_ref`, `uses_versioning` columns omitted from all SELECT queries, create(), and `_row_to_platform()`. Data silently lost on round-trip
4. **ReleaseTable missing `to_dict()`** — only model without serialization, will break any caller expecting uniform model interface
5. **DDH_PLATFORM singleton is mutable** — module-level constant at platform_registry.py:211-222 lacks `frozen=True` on model config
6. **Duplicated 44-column INSERT** — `create()` (lines 96-200) and `create_and_count_atomic()` (lines 203-344) share identical column lists, divergence risk on future additions
7. **`datetime.utcnow()` in ApiRequest** (platform.py:621-627) — deprecated pattern, all other models use `datetime.now(timezone.utc)`

### Beta (Runtime Perspective)

Key findings from the correctness/reliability review:

1. **CRITICAL: `update_approval_state()` lacks WHERE guard** (release_repository.py:605-657) — UPDATE matches only on `release_id`, no check on current `approval_state`. Concurrent rejections can clobber each other. Compare with `approve_release_atomic()` (line 1191) and `update_revocation()` (line 747) which both correctly guard on current state
2. **CRITICAL: `get_next_version_ordinal()` ignores in-flight drafts** (release_repository.py:510-537) — queries `WHERE version_id IS NOT NULL` (approved releases only), so two concurrent submits can both get ordinal 1
3. **Stale release object after atomic approval** (asset_approval_service.py:127→204) — release fetched at line 127 is used for STAC materialization at line 204 AFTER `approve_release_atomic()` commits at line 158. The release object still has `approval_state=PENDING_REVIEW` and `version_id=None`
4. **`get_or_overwrite_release()` ordinal assignment outside lock** (asset_service.py:323) — `get_next_version_ordinal()` called without advisory lock, race window for duplicate ordinals
5. **Ad-hoc `AssetRepository()` instantiation** (asset_approval_service.py:186-187) — creates new repo instance inside method instead of using declared dependency injection
6. **`asset_repository._row_to_model()` uses `.get()` with defaults for NOT NULL columns** — e.g., `platform_id` defaults to `'ddh'`, violating project "fail explicitly" rule

### Gamma (Blind Spot Analysis)

Gamma identified findings that neither Alpha nor Beta caught:

1. **ReleaseTable serialization gap** — junction model lacks `to_dict()` while all sibling models implement it. Any future API that returns release-table associations will fail
2. **Non-atomic release + table creation** — `create()` in release_repository and table link in release_table_repository are separate connections, no transactional guarantee
3. **Mutable DDH_PLATFORM singleton** — module-level `Platform(...)` instance can be mutated at runtime, affecting all callers sharing the import
4. **Ordinal query ignoring in-flight drafts** — `get_next_version_ordinal()` only counts approved releases (WHERE version_id IS NOT NULL), creating a window for duplicate ordinals across concurrent submissions

---

## Delta Final Verdict: TOP 5 FIXES

### Fix 1: Add WHERE guard to `update_approval_state()` for rejection path

**Severity**: CRITICAL
**Effort**: Small | **Risk**: Low
**Location**: `infrastructure/release_repository.py` lines 631-657

**Problem**: `update_approval_state()` uses `WHERE release_id = %s` with no guard on current `approval_state`. Two concurrent reject calls can clobber each other's `rejection_reason`. The approval path uses `approve_release_atomic()` which correctly guards with `AND approval_state = 'pending_review'`, but the rejection path through `update_approval_state()` does not.

**Fix**: Add `AND approval_state = 'pending_review'` to the WHERE clause:

```sql
UPDATE app.asset_releases
SET approval_state = %s, reviewer = %s, reviewed_at = %s,
    rejection_reason = %s, approval_notes = %s, updated_at = NOW()
WHERE release_id = %s
  AND approval_state = 'pending_review'   -- ADD THIS
```

Return `False` if rowcount is 0 (concurrent rejection or already-processed release).

---

### Fix 2: Add unique constraint on `(asset_id, version_ordinal)` and fix ordinal reservation query

**Severity**: CRITICAL
**Effort**: Medium | **Risk**: Medium
**Location**: `core/models/asset.py` line 355, `infrastructure/release_repository.py` lines 510-537

**Problem**: `__sql_unique_constraints` is an empty list — there is no DB-enforced uniqueness on `(asset_id, version_ordinal)`. Combined with `get_next_version_ordinal()` only counting approved releases (`WHERE version_id IS NOT NULL`), two concurrent submissions can both reserve ordinal 1.

**Fix** (two parts):

1. Add unique constraint to `asset.py`:
```python
__sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
    {"columns": ["asset_id", "version_ordinal"], "name": "uq_release_asset_ordinal",
     "partial_where": "version_ordinal IS NOT NULL"}
]
```

2. Fix `get_next_version_ordinal()` to count ALL releases with assigned ordinals, not just approved ones:
```sql
SELECT COALESCE(MAX(version_ordinal), 0) + 1 AS next_ordinal
FROM app.asset_releases
WHERE asset_id = %s
  AND version_ordinal IS NOT NULL   -- Count all ordinals, not just approved
```

**Note**: Requires `action=ensure` schema sync after deployment.

---

### Fix 3: Extract shared column list for duplicated 44-column INSERT

**Severity**: HIGH
**Effort**: Small | **Risk**: Low
**Location**: `infrastructure/release_repository.py` lines 96-200 and 203-344

**Problem**: `create()` and `create_and_count_atomic()` each contain identical 44-column INSERT statements. If a column is added to one and not the other, releases created through different paths will have different data shapes. This is a maintenance time bomb.

**Fix**: Extract a class-level `_INSERT_COLUMNS` tuple and a `_build_insert_values()` helper:

```python
_INSERT_COLUMNS = (
    "release_id", "asset_id", "version_id", "suggested_version_id",
    "version_ordinal", "revision", "previous_release_id",
    # ... all 44 columns
)

def _build_insert_values(self, release: AssetRelease, now: datetime) -> tuple:
    """Extract ordered values from release model to match _INSERT_COLUMNS."""
    return (release.release_id, release.asset_id, ...)
```

Both `create()` and `create_and_count_atomic()` then reference the shared tuple.

---

### Fix 4: Persist versioning fields in PlatformRegistryRepository

**Severity**: HIGH
**Effort**: Medium | **Risk**: Low
**Location**: `infrastructure/platform_registry_repository.py` (all SELECT queries, `create()`, and `_row_to_platform()`)

**Problem**: Three model fields — `nominal_refs`, `version_ref`, `uses_versioning` — are defined on the `Platform` model but completely absent from the repository. All SELECTs, the INSERT, and the row-to-model mapper omit these columns. Data is silently lost on every round-trip.

**Fix**: Add the three columns to:
- All SELECT column lists (lines 71, 98, 125, 160)
- The INSERT in `create()`
- The `_row_to_platform()` mapper

Requires corresponding columns in the `app.platforms` table (may need `action=ensure` if not already present).

---

### Fix 5: Re-read release after atomic approval before STAC materialization

**Severity**: HIGH
**Effort**: Small | **Risk**: Low
**Location**: `services/asset_approval_service.py` lines 127→204

**Problem**: The release object fetched at line 127 (pre-approval) is passed to `_materialize_stac()` at line 204 (post-approval). Between these, `approve_release_atomic()` commits at line 158, updating `version_id`, `version_ordinal`, `approval_state`, `clearance_state`, and `is_latest` in the DB. But the in-memory `release` object still has the old values (`approval_state=PENDING_REVIEW`, `version_id=None`). Line 201 manually patches `stac_item_id`, but all other fields remain stale.

**Fix**: Re-read the release after atomic approval:

```python
if not success:
    return {'success': False, 'error': "Atomic approval failed..."}

# Re-read the approved release for accurate downstream operations
release = self.release_repo.get_by_id(release_id)
```

This ensures `_materialize_stac()` and `_trigger_adf_pipeline()` receive accurate post-approval state.

---

## Accepted Risks

These findings were identified but accepted as low-priority or context-appropriate:

| Finding | Why Accepted |
|---------|-------------|
| Race in `get_or_overwrite_release()` ordinal assignment | Low traffic volume; Fix 2's unique constraint provides DB-level safety net |
| God Object (AssetRelease has 45 fields) | Acceptable for a persistence model — it's a flat table projection, not a behavior-rich domain object |
| `datetime.utcnow()` in ApiRequest | Isolated to one model, cosmetic divergence from `datetime.now(timezone.utc)` convention |
| Soft-deleted asset accumulation | No purge mechanism, but soft deletes are low volume and query-indexed |
| Multiple drafts possible per asset | By design — overwrite flow handles this, and `is_latest` partial unique index prevents duplicate "latest" |
| Connection-per-operation pattern | Known infrastructure pattern, documented in REMAINING_ISSUES.md |

---

## Architecture Wins

These design decisions should be **preserved** — they represent deliberate, correct engineering:

| Pattern | Location | Why It's Good |
|---------|----------|---------------|
| Asset/Release entity split | `core/models/asset.py` | Clean separation of stable identity vs versioned content |
| `approve_release_atomic()` | `release_repository.py:1171-1316` | Single transaction for flip_is_latest + version + approval + clearance |
| `update_revocation()` WHERE guard | `release_repository.py:729-773` | Correct idempotent pattern for concurrent revocation |
| Explicit enum parsing in `_row_to_model()` | `release_repository.py` | No silent defaults for enum fields — fails on unknown values |
| `flip_is_latest()` rollback on target miss | `release_repository.py:1107-1169` | Prevents orphaned `is_latest=false` if target release not found |
| Advisory locks for find_or_create | `asset_repository.py` | Correct serialization of concurrent asset creation |
| Deterministic ID generation | `core/models/asset.py` | SHA256-based IDs ensure idempotent re-submission |

---

## Next Steps

1. Implement Top 5 Fixes (prioritized by severity)
2. Run `action=ensure` after Fix 2 deployment for schema sync
3. Update `COMPLETED_FIXES.md` with resolved findings
4. Proceed to **Review B** (B2B API Surface & Lifecycle Integration)
