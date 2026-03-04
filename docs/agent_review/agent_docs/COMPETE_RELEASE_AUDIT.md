# COMPETE Run 33: Release Audit Log & In-Place Ordinal Revision

**Date**: 03 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Scope**: Release audit log subsystem + in-place ordinal revision enablement
**Scope Split**: A (Design vs Runtime) — Architecture/contracts vs correctness/reliability
**Files Reviewed**: 6 primary + 3 priority files (Gamma)

---

## Agent Execution

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Omega | Scope split + file assignment | -- | inline |
| Alpha | Architecture & design review | ~64,903 | 2m 30s |
| Beta | Correctness & reliability review | ~79,871 | 7m 05s |
| Gamma | Contradiction + blind spot analysis | ~83,288 | 3m 20s |
| Delta | Final report synthesis | ~53,305 | 2m 03s |
| **Total** | | **~281,367** | **~14m 58s** |

---

## Files Under Review

**New files:**
1. `core/models/release_audit.py` — ReleaseAuditEvent model + ReleaseAuditEventType enum
2. `infrastructure/release_audit_repository.py` — Append-only audit CRUD

**Modified files:**
3. `core/schema/sql_generator.py` — Registration (4 insertion points)
4. `infrastructure/release_repository.py` — Audit emission in `update_overwrite()`, `update_revocation()`, `approve_release_atomic()`
5. `core/models/asset.py` — `can_overwrite()` accepts REVOKED
6. `services/asset_approval_service.py` — Stale ordinal guard exemption for revision > 1

**Priority files (Gamma):**
7. `services/asset_service.py` — `create_or_get_draft()` caller chain
8. `infrastructure/release_repository.py` — `get_draft()` method
9. `docs/plans/2026-03-03-release-audit-log.md` — Formal spec

---

## EXECUTIVE SUMMARY

This subsystem is **structurally unsound** in its current state. The primary spec feature — overwriting a revoked ordinal for resubmission — is unreachable because `get_draft()` filters out revoked releases by both conditions in its WHERE clause (BS-1). Additionally, every read method in `ReleaseAuditRepository` produces corrupted data because `dict(zip(columns, dict_row))` iterates dict keys rather than values (F-2), and the `record_event()` return path will KeyError on `row[0]` against a `dict_row` result (C-1). The audit trail itself is architecturally compromised by a split-transaction design where audit commits independently before the mutation it records, creating orphaned events on mutation rollback (BS-4). There are 5 confirmed HIGH-severity bugs that must be fixed before this code reaches any endpoint that handles real traffic.

---

## TOP 5 FIXES

### Fix 1: `get_draft()` Cannot Find Revoked Releases for Overwrite (BS-1 — CRITICAL)

- **WHAT**: `get_draft()` excludes REVOKED releases, making the in-place ordinal revision feature dead code.
- **WHY**: The entire "revoke then resubmit at same ordinal" workflow is broken. A user who revokes ordinal 2, then submits with `overwrite=true`, will never find the revoked release. Instead, a new release is created, defeating the ordinal revision intent.
- **WHERE**: `infrastructure/release_repository.py`, function `get_draft()`, lines 361-373.
- **HOW**: The query has `version_id IS NULL AND approval_state != REVOKED`. Revoked releases have `version_id` assigned (set during approval), so they fail BOTH conditions. Create a dedicated `get_overwrite_candidate(asset_id)` method that queries for releases with `approval_state IN ('pending_review', 'rejected', 'revoked') AND processing_status != 'processing'`, ordered by `created_at DESC LIMIT 1`. Call this from `create_or_get_draft()` when `overwrite=True`. Also: `update_overwrite()` must clear `version_id = NULL` so the release re-enters draft state.
- **EFFORT**: Medium (2-3 hours). New query method + update to `create_or_get_draft()` + `version_id` clearing.
- **RISK OF FIX**: Medium. Touches the release lifecycle state machine.

### Fix 2: All Audit Read Methods Produce Garbage Data (F-2 — HIGH)

- **WHAT**: `dict(zip(columns, row))` in all 4 read methods maps column names to column names (not values), because `row` is already a dict from `dict_row` cursor.
- **WHY**: Every read method crashes with a ValueError (invalid enum) or returns nonsensical data. The audit trail is write-only.
- **WHERE**: `infrastructure/release_audit_repository.py`, lines 122-124, 143-145, 165-167, 187-189.
- **HOW**: Remove `columns` line and `dict(zip(...))` wrapper. Rows are already dicts:
  ```python
  rows = cur.fetchall()
  return [self._row_to_event(row) for row in rows]
  ```
- **EFFORT**: Small (15 minutes). Four identical fixes.
- **RISK OF FIX**: Low.

### Fix 3: `record_event()` Uses `row[0]` on dict_row Result (C-1 — HIGH)

- **WHAT**: `row[0]` at line 102 raises `KeyError(0)` because `fetchone()` returns a dict.
- **WHY**: Return value always lost. Audit row IS inserted (commit at line 100 precedes fetchone), but callers never get the `audit_id`. Swallowed by blanket `except Exception`.
- **WHERE**: `infrastructure/release_audit_repository.py`, line 102.
- **HOW**: `audit_id = row['audit_id'] if row else None`
- **EFFORT**: Small (5 minutes).
- **RISK OF FIX**: Low.

### Fix 4: `update_overwrite()` Has No State Guard in WHERE Clause (AR-3 — HIGH)

- **WHAT**: UPDATE has `WHERE release_id = %s` with no `approval_state` guard. TOCTOU race.
- **WHY**: If release is concurrently approved between `can_overwrite()` check and UPDATE, the unguarded UPDATE resets an APPROVED release to PENDING_REVIEW.
- **WHERE**: `infrastructure/release_repository.py`, `update_overwrite()`, line 1046.
- **HOW**: Add state guards matching `can_overwrite()` logic:
  ```sql
  WHERE release_id = %s
    AND approval_state IN ('pending_review', 'rejected', 'revoked')
    AND processing_status != 'processing'
  ```
- **EFFORT**: Small (30 minutes).
- **RISK OF FIX**: Low. Strictly additive WHERE conditions.

### Fix 5: Audit Commits in Separate Transaction from Mutation (BS-4 — HIGH)

- **WHAT**: Audit `record_event()` commits in its own connection before the mutation executes in a second connection.
- **WHY**: If mutation fails, audit event persists as orphan — records a transition that never happened. Corrupts the audit trail.
- **WHERE**: `infrastructure/release_repository.py`: `update_overwrite()` lines 1007-1058, `update_revocation()` lines 811-854, `approve_release_atomic()` lines 1329-1484.
- **HOW**: Move audit INSERT inside the same transaction as the mutation. Execute both in the same `with self._get_connection()` block, single `conn.commit()`.
- **EFFORT**: Medium (2-3 hours). Three methods to refactor.
- **RISK OF FIX**: Medium. Changes transaction boundaries.

---

## FULL FINDINGS (Recalibrated)

| Rank | ID | Severity | Source | Finding | Confidence |
|------|-----|----------|--------|---------|------------|
| 1 | BS-1 | **CRITICAL** | Gamma | `get_draft()` excludes REVOKED releases — in-place revision unreachable | CONFIRMED |
| 2 | F-2 | **HIGH** | Beta | All read methods produce garbage via `dict(zip(columns, dict_row))` | CONFIRMED |
| 3 | BS-4 | **HIGH** | Gamma | Audit and mutation in separate transactions — phantom events | CONFIRMED |
| 4 | AR-3 | **HIGH** | Beta+Alpha | `update_overwrite()` lacks state guard — TOCTOU race | CONFIRMED |
| 5 | F-4 | **HIGH** | Beta | `INTERVAL '%s hours'` broken with psycopg3 — `get_recent_events()` fails | CONFIRMED |
| 6 | AR-1 | **HIGH** | Alpha | `ReleaseAuditRepository` not in `infrastructure/__init__.py` | CONFIRMED |
| 7 | AR-2 | **HIGH** | Alpha+Beta | 3 identical audit blocks violate DRY + overbroad `except Exception` | CONFIRMED |
| 8 | C-1 | **MEDIUM** | Beta | `row[0]` on dict_row — KeyError swallowed, return value lost | CONFIRMED |
| 9 | BS-3 | **MEDIUM** | Gamma | 5 of 8 spec event types not implemented | CONFIRMED |
| 10 | BS-2 | **MEDIUM** | Gamma | `version_ordinal == 0` falsy — stale guard bypassed | PROBABLE |
| 11 | C-3 | **MEDIUM** | Beta+Gamma | `except Exception` catches ContractViolationError (S1.3 violation) | CONFIRMED |
| 12 | BS-5 | **LOW** | Gamma | Error message omits REVOKED from allowed states | CONFIRMED |
| 13 | Alpha MEDIUM-2 | **LOW** | Alpha | `to_dict()` duplicates `model_dump()` | CONFIRMED |
| 14 | Alpha LOW-2 | **LOW** | Alpha | `ConfigDict()` no arguments | CONFIRMED |
| 15 | Beta R-1 | **LOW** | Beta | New `ReleaseAuditRepository()` per call | CONFIRMED |
| 16 | Beta R-2 | **LOW** | Beta | Snapshot includes full `stac_item_json` | PROBABLE |
| 17 | Beta R-3 | **LOW** | Beta | Read methods have no LIMIT | CONFIRMED |

---

## ACCEPTED RISKS

1. **`ReleaseAuditRepository` not in `__init__.py`** (AR-1): Works via direct module import inside function bodies. Acceptable since audit repo is only used from within `ReleaseRepository` methods past cold start. Revisit if used from trigger-level code.

2. **5 of 8 event types not implemented** (BS-3): CREATED, PROCESSING_*, REJECTED are forward-looking placeholders. The 3 critical events (OVERWRITTEN, REVOKED, APPROVED) are implemented. Revisit when building release timeline UI.

3. **`to_dict()` duplicates `model_dump()`** (Alpha MEDIUM-2): Matches codebase-wide pattern. Revisit during Pydantic v2 cleanup sweep.

4. **Snapshot includes full `stac_item_json`** (Beta R-2): Acceptable at dev volume. Revisit if audit table exceeds 10K rows.

5. **Read methods have no LIMIT** (Beta R-3): Releases have at most ~10 lifecycle events. Revisit if exposed through API endpoint.

6. **`ConfigDict()` with no arguments** (Alpha LOW-2): Model populated from DB rows, not user input. Whitespace stripping irrelevant.

---

## ARCHITECTURE WINS

1. **`approve_release_atomic()`** — Gold standard lifecycle method. Single SQL transaction, `NOT EXISTS` guard, `UniqueViolation` catch, `WHERE approval_state = %s AND processing_status = %s` guards. Pattern to follow.

2. **`update_revocation()` WHERE guards** — Correct `AND approval_state = %s` prevents race conditions. Template for `update_overwrite()` fix.

3. **Append-only audit design** — No UPDATE/DELETE methods. Schema well-designed with denormalized identity fields and appropriate indexes.

4. **`can_overwrite()` centralization** — State guard logic in domain model, not scattered across services. Clean predicate.

5. **`ReleaseAuditEventType` enum** — All 8 lifecycle events defined. Prevents future `ALTER TYPE` migrations.

---

## SPEC OPEN QUESTIONS ANSWERED

| # | Question | Answer |
|---|----------|--------|
| 3 | `NOT EXISTS` guard excludes REVOKED from conflict check? | **YES** — guard uses `AND approval_state = APPROVED` (line 1392). REVOKED releases don't trigger conflict. Re-approval of "v2" succeeds. |
| 1 | How does overwrite find REVOKED target? | **UNRESOLVED** — `get_draft()` cannot find REVOKED releases (BS-1). Needs new query method. |
| 2 | Multiple revoked ordinals — which gets overwritten? | **UNRESOLVED** — Depends on Fix 1 implementation. Caller should pass `version_ordinal` explicitly. |
