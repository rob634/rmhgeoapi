# REFLEXION Run 28 — ADV-2 Approval Guard Analysis

**Date**: 04 MAR 2026
**Pipeline**: REFLEXION (R → F → P → J)
**Scope**: Approval workflow — 3 files
**Target**: ADV-2 (approval allows failed/processing releases)
**Version**: v0.9.12.1

---

## Scope Files

| File | LOC | Layer |
|------|-----|-------|
| `services/asset_approval_service.py` | 1031 | Service |
| `triggers/trigger_approvals.py` | 1128 | Trigger |
| `infrastructure/release_repository.py` | 1727 | Repository |

---

## ADV-2 Verdict

**The approval guard CANNOT be bypassed.**

1. **Python guard (line 155)**: `if release.processing_status != ProcessingStatus.COMPLETED` — checks in-memory snapshot
2. **SQL guard (approve_release_atomic)**: `WHERE ... AND processing_status = 'completed'` — database-level defense
3. Both guards agree. The SQL WHERE clause is the ultimate defense — it operates on the live row at UPDATE time.

The live test observation (approval succeeding despite /status showing `processing`) was explained by the Docker worker completing processing between the status check and approval call. This is **correct behavior** — the guard evaluated after processing completed.

---

## Critical Discovery: Stale-Ordinal Guard Inoperative (P0)

`has_newer_active_ordinal()` used positional row indexing (`row[0]`-`row[3]`) on dict_row cursors. This caused `KeyError` on every invocation, silently caught upstream, allowing all approvals to bypass the SG5-1/LA-1 stale-ordinal guard.

**Fixed in PATCH 1.**

---

## Fault Summary (Agent F)

| ID | Fault | Severity | Likelihood | Status |
|----|-------|----------|------------|--------|
| F-01 | Approve+Revoke race corrupts is_latest | CRITICAL | LOW | RESIDUAL — needs advisory locks |
| F-02 | Positional row indexing in has_newer_active_ordinal | HIGH | MEDIUM | **FIXED (P1)** |
| F-03 | STAC partial failure leaves orphaned artifacts | HIGH | MEDIUM | RESIDUAL — needs compensating txn |
| F-06 | version_ordinal coercion to 0 | HIGH | MEDIUM | DEFERRED — by design |
| F-07 | No DB retry/circuit breaker | HIGH | MEDIUM | RESIDUAL — infra-level change |
| F-08 | Approval commits but response says failure | HIGH | LOW | **FIXED (P4)** |
| F-04 | Rollback does not clear is_served | HIGH | LOW | **FIXED (P5)** |
| F-16 | Hardcoded 'completed' in SQL | MEDIUM | LOW | **FIXED (P3)** |
| F-05 | Rejection error message confusing | MEDIUM | LOW | **FIXED (P6)** |

---

## Patches Applied

### PATCH 1 (P0): Fix positional row indexing — `has_newer_active_ordinal()`
- **File**: `infrastructure/release_repository.py:1591-1596`
- **Change**: `row[0]`→`row['release_id']`, `row[1]`→`row['version_ordinal']`, etc.
- **Verdict**: APPROVE — Constitution Rule 6.1 violation, P0 fix

### PATCH 3: Parameterize `'completed'` string in SQL
- **File**: `infrastructure/release_repository.py:1324,1370`
- **Change**: `processing_status = 'completed'` → `processing_status = %s` with `ProcessingStatus.COMPLETED` parameter
- **Verdict**: APPROVE WITH MODIFICATIONS

### PATCH 4: Null guard after atomic commit re-read
- **File**: `services/asset_approval_service.py:239-240`
- **Change**: Add `if not release:` guard with `PostAtomicReadFailure` error type
- **Verdict**: APPROVE

### PATCH 5 (modified): Add `is_served = false` to rollback
- **File**: `infrastructure/release_repository.py:1461-1468`
- **Change**: Add `is_served = false` to rollback SET clause (version_ordinal NOT cleared per Judge)
- **Verdict**: APPROVE WITH MODIFICATIONS

### PATCH 6: Improve rejection error message
- **File**: `services/asset_approval_service.py:505-509`
- **Change**: Add concurrent modification hint and `error_type: 'RejectionFailed'`
- **Verdict**: APPROVE

### PATCH 2 (REJECTED): version_ordinal coercion
- **Reason**: `or 0` sentinel is intentional design. 3-file change too risky. Deferred to architectural discussion.

---

## Residual Risks

| Risk | Mitigation |
|------|------------|
| F-01: Approve+Revoke is_latest race | Add periodic consistency check for assets with ≠1 is_latest |
| F-03: STAC partial failure orphans | Add reconciliation job comparing releases vs pgSTAC items |
| F-07: No DB retry | Azure PG Flex built-in retry + connection pool recycling |

---

## Key Insight

The stale-ordinal guard (SG5-1/LA-1) — specifically designed to prevent approval of obsolete data when a newer version exists — has been completely inoperative since implementation due to positional row indexing that crashes with `KeyError`. This was invisible because the exception was caught silently upstream. A codebase-wide audit of `row[N]` patterns in the infrastructure layer would be a high-value preventive measure.

---

## Token Usage

| Agent | Est. Tokens |
|-------|-------------|
| R (Reverse Engineer) | ~85K |
| F (Fault Injector) | ~91K |
| P (Patch Author) | ~85K |
| J (Judge) | ~82K |
| **Total** | **~343K** |
