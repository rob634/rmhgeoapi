# AGENT M -- MEDIATOR RESOLUTION REPORT

**Date**: 27 FEB 2026
**Subsystem**: Version-ID Conflict Guard & Atomic Rollback for Release Approval
**Status**: Final spec for Builder handoff

---

## CONFLICTS FOUND

### CONFLICT 1: NOT EXISTS scope vs. partial unique index scope (Agent A vs. Agent C -- AMB-2)

Agent A's `approve_release_atomic()` uses a NOT EXISTS subquery that checks ALL sibling releases regardless of approval_state, while the partial unique index only constrains APPROVED releases with non-null version_id. Agent C correctly identified this mismatch: a REJECTED release holding version_id "v1" would cause the NOT EXISTS code guard to block a new "v1" approval, even though the index would allow it.

**Resolution**: The NOT EXISTS guard must scope to `approval_state = 'approved'` only, matching the index semantics. Rationale: a rejected release's version_id is stale metadata -- it should not block future approvals. The index is the authoritative constraint. The code guard exists as a fast-path check to return a readable error rather than catching a UniqueViolation, so its scope must match the index precisely.

**Tradeoff**: If a rejected release holds a version_id and someone re-approves a different release with the same version_id, the rejected release's stale version_id will coexist. This is acceptable because rejected releases are not served and version_id on a rejected release is meaningless.

---

### CONFLICT 2: UniqueViolation exception vs. False return value (Agent C OQ-1 vs. Agent A's contract)

Agent A's contract says `approve_release_atomic()` returns False on conflict. Agent C correctly identified that under READ COMMITTED isolation, two concurrent approvals can both pass the NOT EXISTS check before either commits, and the partial unique index then raises `UniqueViolation` on the second commit. The spec promises a return value but gets an exception.

**Resolution**: Catch `psycopg.errors.UniqueViolation` inside `approve_release_atomic()` and return False. This satisfies the contract. The code guard is a best-effort fast path; the index is the actual enforcer. When the index fires, we catch the exception, rollback, and return False. The service layer then probes `get_approved_by_version()` to provide the caller with a diagnostic VersionConflict response.

**Tradeoff**: The caller sees the same False return whether the code guard caught it or the index caught it. The service layer differentiates by probing `get_approved_by_version()` after a False return.

---

### CONFLICT 3: stac_item_id update commits independently (Agent C EDGE-7 vs. Agent A's rollback design)

Agent C identified that `update_physical_outputs()` (which updates stac_item_id to its versioned form) runs in its own connection/transaction and commits independently. If STAC materialization then fails and `rollback_approval_atomic()` reverts the approval, the stac_item_id retains the versioned form (e.g., "floods_jakarta_v1") while version_id is nullified back to None.

**Resolution**: Do NOT move stac_item_id update into the atomic approval transaction. Reason: stac_item_id is already set correctly at draft creation time via ordinal-based naming (see `triggers/platform/submit.py` lines 342-370). The existing `approve_release()` in AssetApprovalService only regenerates stac_item_id if it differs from the current value, which handles the edge case of version_id-based vs ordinal-based naming. On rollback, the stac_item_id remains in its ordinal form (e.g., "floods_jakarta_ord1"), which is a valid identifier. The rollback does NOT need to revert stac_item_id because the ordinal-based ID is stable and does not change between draft and approval.

However, `rollback_approval_atomic()` MUST clear version_id (set to None), set approval_state back to PENDING_REVIEW, and clear is_latest. It should NOT clear stac_item_id, stac_collection_id, or blob_path, as those are physical outputs from processing, not approval artifacts.

**Tradeoff**: After rollback, stac_item_id may contain the version-id form if the stac_item_id update succeeded before STAC materialization failed. This is cosmetically inconsistent but functionally harmless -- the release is back in PENDING_REVIEW and the stac_item_id will be recalculated on re-approval.

---

### CONFLICT 4: ADF pipeline already triggered before rollback (Agent C EDGE-1 vs. Agent O)

Agent C identified that if clearance_state is PUBLIC, the ADF pipeline might be triggered before rollback occurs. But in the current code flow (`AssetApprovalService.approve_release()` in `/Users/robertharrison/python_builds/rmhgeoapi/services/asset_approval_service.py`), ADF is triggered AFTER STAC materialization (line 229), not before. So if STAC fails, ADF is never reached.

**Resolution**: This is a non-conflict on closer inspection of the actual code. The current flow is:

```
atomic approval commit -> stac_item_id update -> STAC materialization -> ADF trigger (only if PUBLIC)
```

If STAC materialization fails, ADF is never reached, so no rollback is needed for ADF. The rollback scope is: revert approval state + restore is_latest. ADF is not in the blast radius.

**Tradeoff**: None. The existing code ordering already prevents this scenario.

---

### CONFLICT 5: First-version rollback leaves no is_latest sibling (Agent C EDGE-2 vs. Agent A's invariant)

Agent A's invariant says "exactly one sibling holds is_latest=true" after rollback. Agent C correctly identified that if the only release is rolled back, there are no other approved siblings to receive is_latest. Agent O noted the same: "the is_latest restoration via subquery handles 'no other approved siblings' correctly (0 rows updated)."

**Resolution**: Weaken the invariant. The correct statement is: **"After rollback, AT MOST one sibling holds is_latest=true. If no other approved siblings exist, zero siblings hold is_latest."** The rollback SQL's is_latest restoration subquery naturally handles this: it finds the most recently approved sibling by ordinal DESC, and if none exists, updates 0 rows. This is correct behavior -- an asset with zero approved releases has zero is_latest releases.

**Tradeoff**: The invariant as stated by the spec is overly strict. The weakened invariant is correct and matches the existing `flip_is_latest()` behavior in `release_repository.py` (lines 1089-1151) which already handles the "no target found" case by rolling back.

---

### CONFLICT 6: Agent A's approved_only parameter vs. No Backward Compatibility constraint

Agent A proposed adding `approved_only: bool = False` to the existing `get_by_version()` method for backward compatibility. The Tier 2 constraint says "No Backward Compatibility Fallbacks."

**Resolution**: Do not add the parameter. The existing `get_by_version()` (lines 309-333 of `release_repository.py`) already queries without filtering on approval_state. Instead, create a new method `get_approved_by_version(asset_id, version_id)` that filters explicitly with `AND approval_state = 'approved'`. This follows the explicit-is-better-than-implicit principle and avoids boolean parameters that obscure behavior.

**Tradeoff**: Two methods instead of one, but each has a clear contract. The service layer calls the explicit one it needs.

---

### CONFLICT 7: Full field reset on rollback (Agent A) vs. minimal reset (audit preservation)

Agent A proposed that `rollback_approval_atomic()` should nullify ALL approval/clearance fields (reviewer, reviewed_at, clearance_state, cleared_at, cleared_by, made_public_at, made_public_by, approval_notes). This is aggressive -- it destroys the audit trail of who attempted the approval.

**Resolution**: Preserve audit fields. Rollback should set:
- `approval_state = PENDING_REVIEW`
- `version_id = NULL`
- `is_latest = false`
- `clearance_state = 'uncleared'`
- `last_error = 'ROLLBACK: {reason}'`

It should NOT clear:
- `reviewer` (who tried to approve)
- `reviewed_at` (when they tried)
- `approval_notes` (what they said)
- `cleared_at`, `cleared_by` (clearance attempt audit)
- `made_public_at`, `made_public_by` (public attempt audit)

The audit trail of the failed approval attempt is valuable for debugging.

**Tradeoff**: After rollback, `reviewer` and `reviewed_at` contain data from the reverted approval. This is intentional -- it answers "who tried to approve this and when?" which is useful diagnostic information. The `last_error` field containing "ROLLBACK: ..." makes the state unambiguous.

---

### CONFLICT 8: Connection count per approval (Agent O) vs. Agent A's design

Agent O noted each approval uses 2-4 database connections. The current code already creates separate connections for: (1) approve_release_atomic, (2) re-read release, (3) stac_item_id update, (4) STAC materialization, (5) update_last_error on failure, (6) rollback. On Consumption Plan, there is no connection pooling.

**Resolution**: Accept the connection count. The approval path is low-volume (manual reviewer action, not batch processing). Connection pooling exists for Docker mode via `ConnectionPoolManager`. For Function App (Consumption Plan), each approval is a separate invocation so connections are isolated. The rollback adds at most 1 additional connection to the existing 4-5.

**Tradeoff**: Under concurrent approval load (unlikely for manual reviewer workflow), connection exhaustion is possible. Agent O's observation is valid but the risk is low given the manual nature of approvals.

---

## DESIGN TENSIONS

### TENSION 1: Agent A's NOT EXISTS subquery vs. Tier 2 SQL Composition constraint

Agent A's NOT EXISTS subquery uses complex SQL with multiple bind parameters. The Tier 2 constraint requires `sql.SQL + sql.Identifier for schema/table names, %s for values`. The existing `approve_release_atomic()` already follows this pattern (lines 1199-1282 of `release_repository.py`). The NOT EXISTS addition follows the same pattern -- it uses `sql.SQL()` with `sql.Identifier()` for schema.table and `%s` for bind values.

**Resolution**: No tension in practice; the constraint is satisfied. The NOT EXISTS subquery uses parameterized `%s` placeholders for all values and `sql.Identifier()` for the schema/table reference in the subquery.

---

### TENSION 2: Agent A's backward-compatible approved_only parameter vs. Tier 2 No Backward Compatibility

Agent A proposed `approved_only: bool = False` as a backward-compatible parameter on `get_by_version()`. Tier 2 says: "Fail explicitly, never create fallbacks."

**Resolution**: Already resolved in Conflict 6. The constraint wins: create a new explicit method `get_approved_by_version()` rather than adding a backward-compatible parameter with a default value.

---

### TENSION 3: Agent A's ERROR_STATUS_MAP dict vs. existing trigger error handling pattern

The existing trigger layer (`trigger_approvals.py`) uses inline if/else for error handling (lines 312-321). Agent A proposed a declarative ERROR_STATUS_MAP dict. The Tier 2 constraints do not prohibit this pattern, and the existing codebase uses inline logic. However, the ERROR_STATUS_MAP is a strict improvement (declarative, extensible, no control flow changes).

**Resolution**: Use the ERROR_STATUS_MAP pattern in the trigger layer. It is consistent with the Tier 2 service layer pattern (services return dicts with `success` + `error_type` fields) and makes the trigger layer a thin mapping. The existing trigger already returns error_type in some paths -- the MAP makes this consistent.

---

## RESOLVED SPEC

### Component 1: Partial Unique Index on `app.asset_releases`

**Responsibility**: Database-level enforcement that no two APPROVED releases of the same asset share a version_id.

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/core/models/asset.py`

**Index Definition (SQL)**:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_releases_version_conflict
ON app.asset_releases (asset_id, version_id)
WHERE approval_state = 'approved' AND version_id IS NOT NULL;
```

**Integration with existing code**: Add to `AssetRelease.__sql_indexes` ClassVar list (currently at line 362 of `asset.py`):
```python
{
    "columns": ["asset_id", "version_id"],
    "name": "idx_releases_version_conflict",
    "unique": True,
    "partial_where": "approval_state = 'approved' AND version_id IS NOT NULL"
},
```

This follows the exact same pattern as the existing `idx_releases_latest` index (lines 371-375):
```python
{
    "columns": ["asset_id"],
    "name": "idx_releases_latest",
    "unique": True,
    "partial_where": "is_latest = true AND approval_state = 'approved'"
},
```

**Deployment**: Deployed via `action=ensure` endpoint (CREATE INDEX IF NOT EXISTS). Safe, no data loss, idempotent. Run the pre-deployment check query first:
```sql
SELECT asset_id, version_id, COUNT(*)
FROM app.asset_releases
WHERE approval_state = 'approved' AND version_id IS NOT NULL
GROUP BY asset_id, version_id
HAVING COUNT(*) > 1;
```
If this returns rows, resolve duplicates manually before deploying.

**Error handling**: If the index already exists, CREATE IF NOT EXISTS is a no-op. If existing data violates uniqueness, the deployment fails with a clear PostgreSQL error. This is by design (fail explicitly, per Tier 2).

**Operational requirements**: No ongoing monitoring needed. The index is passive infrastructure. Verify creation after `action=ensure` by checking deployment logs.

---

### Component 2: Enhanced `approve_release_atomic()` on `ReleaseRepository`

**Responsibility**: Atomically approve a release with a NOT EXISTS guard against sibling version_id conflicts. Returns False on conflict (whether caught by code guard or by index UniqueViolation).

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/infrastructure/release_repository.py`

**Interface** (signature unchanged from existing):
```python
def approve_release_atomic(
    self,
    release_id: str,
    asset_id: str,
    version_id: str,
    version_ordinal: int,
    approval_state: ApprovalState,
    reviewer: str,
    reviewed_at: datetime,
    clearance_state: ClearanceState,
    approval_notes: str = None
) -> bool:
    """
    Atomically approve a release: flip is_latest + assign version +
    set approval state + set clearance in a single transaction.

    NOW ALSO: Guards against sibling version_id conflicts via NOT EXISTS
    subquery scoped to APPROVED releases. Catches UniqueViolation from
    the partial unique index as a fallback for concurrent race conditions.

    Args:
        release_id: Release to approve
        asset_id: Parent asset (for flip_is_latest across siblings)
        version_id: Version to assign (e.g., "v1")
        version_ordinal: Numeric ordering (1, 2, 3...)
        approval_state: Must be APPROVED
        reviewer: Who approved
        reviewed_at: When approved
        clearance_state: OUO or PUBLIC
        approval_notes: Optional reviewer notes

    Returns:
        True if approved, False if:
        - release not found
        - release not in pending_review state (concurrent approval)
        - sibling already holds this version_id (conflict)
    """
```

**SQL change**: Both SQL branches (PUBLIC and OUO) in Step 2 get the same NOT EXISTS addition to their WHERE clause. The existing WHERE clause is:
```sql
WHERE release_id = %s AND approval_state = %s
```

Changed to:
```sql
WHERE release_id = %s
  AND approval_state = %s
  AND NOT EXISTS (
      SELECT 1 FROM {schema}.{table}
      WHERE asset_id = %s
        AND version_id = %s
        AND approval_state = %s
        AND release_id != %s
  )
```

New bind parameters for the NOT EXISTS (4 additional per branch):
```python
(asset_id, version_id, ApprovalState.APPROVED, release_id)
```

The NOT EXISTS scopes to `approval_state = 'approved'` only, matching the partial unique index. It excludes the current release_id via `release_id != %s` to avoid self-conflict.

**UniqueViolation handling**: Wrap the entire connection block:
```python
from psycopg.errors import UniqueViolation

try:
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            # Step 1: Clear is_latest for all releases of this asset
            cur.execute(
                sql.SQL("""
                    UPDATE {}.{}
                    SET is_latest = false, updated_at = %s
                    WHERE asset_id = %s AND is_latest = true
                """).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table)
                ),
                (reviewed_at, asset_id)
            )

            # Step 2: Approve + version + is_latest + clearance + NOT EXISTS guard
            # (PUBLIC branch shown; OUO branch is identical except without
            #  made_public_at and made_public_by columns)
            if is_public:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET version_id = %s,
                            version_ordinal = %s,
                            is_latest = true,
                            approval_state = %s,
                            reviewer = %s,
                            reviewed_at = %s,
                            approval_notes = %s,
                            rejection_reason = NULL,
                            clearance_state = %s,
                            cleared_at = %s,
                            cleared_by = %s,
                            made_public_at = %s,
                            made_public_by = %s,
                            updated_at = %s
                        WHERE release_id = %s
                          AND approval_state = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM {}.{}
                              WHERE asset_id = %s
                                AND version_id = %s
                                AND approval_state = %s
                                AND release_id != %s
                          )
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        version_id, version_ordinal,
                        approval_state, reviewer, reviewed_at,
                        approval_notes,
                        clearance_state, reviewed_at, reviewer,
                        reviewed_at, reviewer,
                        reviewed_at,
                        release_id,
                        ApprovalState.PENDING_REVIEW,
                        # NOT EXISTS params
                        asset_id, version_id,
                        ApprovalState.APPROVED, release_id
                    )
                )
            else:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET version_id = %s,
                            version_ordinal = %s,
                            is_latest = true,
                            approval_state = %s,
                            reviewer = %s,
                            reviewed_at = %s,
                            approval_notes = %s,
                            rejection_reason = NULL,
                            clearance_state = %s,
                            cleared_at = %s,
                            cleared_by = %s,
                            updated_at = %s
                        WHERE release_id = %s
                          AND approval_state = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM {}.{}
                              WHERE asset_id = %s
                                AND version_id = %s
                                AND approval_state = %s
                                AND release_id != %s
                          )
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        version_id, version_ordinal,
                        approval_state, reviewer, reviewed_at,
                        approval_notes,
                        clearance_state, reviewed_at, reviewer,
                        reviewed_at,
                        release_id,
                        ApprovalState.PENDING_REVIEW,
                        # NOT EXISTS params
                        asset_id, version_id,
                        ApprovalState.APPROVED, release_id
                    )
                )

            approved = cur.rowcount > 0

            if approved:
                conn.commit()
                logger.info(
                    f"Atomic approve committed: {release_id[:16]}... "
                    f"-> {version_id} (ordinal={version_ordinal})"
                )
            else:
                conn.rollback()
                logger.warning(
                    f"Atomic approve failed: {release_id[:16]}... "
                    f"not found, not in pending_review state, or version "
                    f"conflict (version_id={version_id})"
                )

            return approved

except UniqueViolation:
    logger.warning(
        f"Version conflict (UniqueViolation): release {release_id[:16]}... "
        f"version_id={version_id} already held by approved sibling of "
        f"asset {asset_id[:16]}..."
    )
    return False
```

**Error handling strategy**:
- `UniqueViolation`: caught inside `approve_release_atomic()`, translated to `return False`. Logged at WARNING. The psycopg driver automatically rolls back the transaction on exception, so no explicit `conn.rollback()` is needed in the except block.
- `rowcount == 0`: returns False (existing behavior for stale or concurrent approval, now also for NOT EXISTS conflict).
- Other psycopg exceptions: NOT caught here. They bubble up as infrastructure errors to the service layer's outer try/except.

**Operational requirements**:
- Log `release_id[:16]`, `asset_id[:16]`, `version_id` on every call.
- INFO for successful approval commit.
- WARNING for conflict (both NOT EXISTS and UniqueViolation paths).

---

### Component 3: `rollback_approval_atomic()` on `ReleaseRepository`

**Responsibility**: Revert a committed approval back to PENDING_REVIEW state and restore is_latest to the most recently approved sibling, all in a single transaction.

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/infrastructure/release_repository.py`

**Interface**:
```python
def rollback_approval_atomic(
    self,
    release_id: str,
    asset_id: str,
    reason: str = "STAC materialization failed"
) -> bool:
    """
    Revert a committed approval to PENDING_REVIEW state.

    Called when a post-approval operation (STAC materialization, stac_item_id
    update) fails after the atomic approval has already committed. This method
    undoes the approval so the release does not remain in an "approved-but-broken"
    state.

    Single transaction:
    1. Reset target release: version_id=NULL, approval_state=PENDING_REVIEW,
       is_latest=false, clearance_state='uncleared', last_error=reason.
       Preserves: reviewer, reviewed_at, approval_notes, stac_item_id,
       stac_collection_id, blob_path (audit trail + physical outputs).
    2. Restore is_latest on most recently approved sibling
       (ORDER BY version_ordinal DESC, reviewed_at DESC LIMIT 1).
       If no approved siblings exist, 0 rows updated (correct -- weakened
       invariant allows zero is_latest when no approved siblings remain).

    Args:
        release_id: Release to rollback (must currently be APPROVED)
        asset_id: Parent asset (for sibling is_latest restoration)
        reason: Why the rollback is happening (stored in last_error
                as "ROLLBACK: {reason}")

    Returns:
        True if rollback succeeded (release was APPROVED and is now PENDING_REVIEW).
        False if release not found or not in APPROVED state (already rolled back
        or concurrent modification).
    """
```

**Full implementation**:
```python
def rollback_approval_atomic(
    self,
    release_id: str,
    asset_id: str,
    reason: str = "STAC materialization failed"
) -> bool:
    logger.warning(
        f"Rolling back approval: release {release_id[:16]}... "
        f"asset {asset_id[:16]}... reason: {reason}"
    )

    now = datetime.now(timezone.utc)

    with self._get_connection() as conn:
        with conn.cursor() as cur:
            # Step 1: Reset target release to PENDING_REVIEW
            # Preserves reviewer, reviewed_at, approval_notes for audit trail.
            # Preserves stac_item_id, stac_collection_id, blob_path (physical outputs).
            # Clears version_id (approval artifact), clearance_state, is_latest.
            cur.execute(
                sql.SQL("""
                    UPDATE {}.{}
                    SET approval_state = %s,
                        version_id = NULL,
                        is_latest = false,
                        clearance_state = %s,
                        last_error = %s,
                        updated_at = %s
                    WHERE release_id = %s
                      AND approval_state = %s
                """).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table)
                ),
                (
                    ApprovalState.PENDING_REVIEW,
                    ClearanceState.UNCLEARED,
                    f"ROLLBACK: {reason}",
                    now,
                    release_id,
                    ApprovalState.APPROVED
                )
            )

            rolled_back = cur.rowcount > 0

            if rolled_back:
                # Step 2: Restore is_latest on most recently approved sibling.
                # Uses subquery to find the best candidate in a single statement
                # (no round-trips). If no approved siblings exist, the UPDATE
                # matches 0 rows -- this is correct behavior.
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET is_latest = true, updated_at = %s
                        WHERE release_id = (
                            SELECT release_id FROM {}.{}
                            WHERE asset_id = %s
                              AND approval_state = %s
                              AND release_id != %s
                            ORDER BY version_ordinal DESC, reviewed_at DESC
                            LIMIT 1
                        )
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        now,
                        asset_id,
                        ApprovalState.APPROVED,
                        release_id
                    )
                )
                sibling_restored = cur.rowcount > 0

                conn.commit()

                if sibling_restored:
                    logger.warning(
                        f"ROLLBACK committed: release {release_id[:16]}... "
                        f"reverted to PENDING_REVIEW. is_latest restored to sibling."
                    )
                else:
                    logger.warning(
                        f"ROLLBACK committed: release {release_id[:16]}... "
                        f"reverted to PENDING_REVIEW. No approved siblings "
                        f"to restore is_latest."
                    )
            else:
                conn.rollback()
                logger.warning(
                    f"ROLLBACK skipped: release {release_id[:16]}... "
                    f"not found or not in APPROVED state"
                )

            return rolled_back
```

**Error handling**:
- `approval_state = %s` (APPROVED) in WHERE clause ensures idempotent safety: if already rolled back, returns False without modifying anything.
- Step 2 subquery returns 0 rows if no approved siblings exist; 0 rows updated is correct (weakened invariant).
- Any psycopg exception bubbles up; the `_get_connection()` context manager auto-rolls back on exception, so the transaction guarantees no partial state.
- The caller (service layer) catches exceptions from this method and handles the double-failure case.

**Operational requirements**:
- Log at WARNING level (rollback is an abnormal event worth attention).
- Include `release_id[:16]`, `asset_id[:16]`, and `reason` in all log messages.
- Log whether a sibling was restored to is_latest or not.

---

### Component 4: `get_approved_by_version()` on `ReleaseRepository`

**Responsibility**: Query for the APPROVED release holding a specific version_id for an asset. Used for conflict diagnostics after `approve_release_atomic()` returns False.

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/infrastructure/release_repository.py`

**Interface**:
```python
def get_approved_by_version(
    self,
    asset_id: str,
    version_id: str
) -> Optional[AssetRelease]:
    """
    Get the APPROVED release holding a specific version_id for an asset.

    Used by the service layer after approve_release_atomic() returns False
    to distinguish between:
    - VersionConflict: an approved sibling holds this version_id
    - ApprovalFailed: the release was not in pending_review state

    This is a separate method from get_by_version() (which does not filter
    by approval_state) per the No Backward Compatibility constraint.

    Args:
        asset_id: Parent asset identifier
        version_id: Version identifier (e.g., "v1", "v2")

    Returns:
        AssetRelease if an APPROVED release holds this version_id, None otherwise.
    """
```

**Full implementation**:
```python
def get_approved_by_version(
    self,
    asset_id: str,
    version_id: str
) -> Optional[AssetRelease]:
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    SELECT * FROM {}.{}
                    WHERE asset_id = %s
                      AND version_id = %s
                      AND approval_state = %s
                """).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table)
                ),
                (asset_id, version_id, ApprovalState.APPROVED)
            )
            row = cur.fetchone()
            return self._row_to_model(row) if row else None
```

**Error handling**: No special handling. Returns None if not found. Psycopg exceptions bubble up to caller.

**Operational requirements**: No logging needed. This is a read-only diagnostic query called only when an approval fails.

**Integration notes**: Place this method near the existing `get_by_version()` method (line 309 of `release_repository.py`) for logical grouping.

---

### Component 5: Enhanced `approve_release()` on `AssetApprovalService`

**Responsibility**: Orchestrate approval with conflict detection and automatic rollback on STAC failure. Return structured error dicts with error_type for the trigger layer to map to HTTP status codes.

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/asset_approval_service.py`

**Interface** (signature unchanged, return dict enhanced):
```python
def approve_release(
    self,
    release_id: str,
    reviewer: str,
    clearance_state: ClearanceState,
    version_id: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Approve a release for publication with conflict detection and auto-rollback.

    Steps:
    1. Validate release exists and is PENDING_REVIEW
    2. Warn (don't block) if processing_status != COMPLETED
    3. Call approve_release_atomic() (with NOT EXISTS guard)
    4. If atomic approval returns False:
       a. Probe get_approved_by_version() to determine cause
       b. Return VersionConflict or ApprovalFailed error dict
    5. If atomic approval succeeds:
       a. Update stac_item_id to final versioned form
       b. Materialize STAC from cached stac_item_json
       c. On STAC failure: call rollback_approval_atomic()
          - If rollback succeeds: return StacMaterializationError
          - If rollback fails: return StacRollbackFailed (CRITICAL)
       d. On STAC success: trigger ADF if PUBLIC

    Returns:
        Dict with fields:
            success: bool

            # On failure:
            error: str -- human-readable error message
            error_type: str -- one of:
                'VersionConflict' -- sibling already holds version_id
                'ApprovalFailed' -- release not in pending_review
                'StacMaterializationError' -- STAC failed, rollback succeeded
                'StacRollbackFailed' -- STAC failed AND rollback failed
            remediation: str -- human-readable fix instructions
            conflicting_release_id: str -- (only for VersionConflict)

            # On success:
            release: dict -- updated AssetRelease.to_dict()
            action: str -- 'approved_ouo' or 'approved_public_adf_triggered'
            stac_updated: bool
            adf_run_id: str -- (only if PUBLIC and ADF triggered)
            mosaic_viewer_url: str -- (only for tiled outputs)
    """
```

**Full implementation flow** (replaces current lines 85-267 of `asset_approval_service.py`):

```python
def approve_release(
    self,
    release_id: str,
    reviewer: str,
    clearance_state: ClearanceState,
    version_id: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    logger.info(
        f"Approving release {release_id[:16]}... by {reviewer} "
        f"(clearance: {clearance_state.value}, version: {version_id})"
    )

    # ── Step 1: Get and validate release ──
    release = self.release_repo.get_by_id(release_id)
    if not release:
        return {
            'success': False,
            'error': f"Release not found: {release_id}",
            'error_type': 'ApprovalFailed',
            'remediation': 'Check the release_id is correct.'
        }

    if not release.can_approve():
        return {
            'success': False,
            'error': (
                f"Cannot approve: approval_state is '{release.approval_state.value}', "
                f"expected 'pending_review'"
            ),
            'error_type': 'ApprovalFailed',
            'remediation': (
                'Check the release\'s current state. It may have been '
                'approved, rejected, or revoked concurrently.'
            )
        }

    # ── Step 2: Warn if processing not complete ──
    if release.processing_status != ProcessingStatus.COMPLETED:
        logger.warning(
            f"Approving release with processing_status="
            f"{release.processing_status.value} "
            f"(expected COMPLETED) - proceeding anyway"
        )

    now = datetime.now(timezone.utc)
    version_ordinal = release.version_ordinal

    # ── Step 3: Atomic approval with NOT EXISTS guard ──
    success = self.release_repo.approve_release_atomic(
        release_id=release_id,
        asset_id=release.asset_id,
        version_id=version_id,
        version_ordinal=version_ordinal,
        approval_state=ApprovalState.APPROVED,
        reviewer=reviewer,
        reviewed_at=now,
        clearance_state=clearance_state,
        approval_notes=notes
    )

    # ── Step 4: Handle atomic approval failure ──
    if not success:
        # Probe to distinguish VersionConflict from ApprovalFailed
        conflicting = self.release_repo.get_approved_by_version(
            release.asset_id, version_id
        )
        if conflicting:
            logger.warning(
                f"Version conflict: version_id '{version_id}' already held "
                f"by release {conflicting.release_id[:16]}... for asset "
                f"{release.asset_id[:16]}..."
            )
            return {
                'success': False,
                'error': (
                    f"Version '{version_id}' is already assigned to approved "
                    f"release {conflicting.release_id}"
                ),
                'error_type': 'VersionConflict',
                'conflicting_release_id': conflicting.release_id,
                'remediation': (
                    'Choose a different version_id, or revoke the conflicting '
                    'release first.'
                )
            }
        else:
            return {
                'success': False,
                'error': (
                    'Atomic approval failed: release not in pending_review '
                    'state (concurrent approval?)'
                ),
                'error_type': 'ApprovalFailed',
                'remediation': (
                    'Check the release\'s current state. It may have been '
                    'approved or rejected concurrently.'
                )
            }

    # ── Step 5: Post-atomic operations ──
    # Re-read approved release for downstream operations
    release = self.release_repo.get_by_id(release_id)

    stac_result = {'success': False, 'error': 'STAC materialization not attempted'}
    try:
        # Update stac_item_id to final versioned form (draft ordinal -> version_id)
        from services.platform_translation import generate_stac_item_id
        from infrastructure import AssetRepository
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(release.asset_id)
        if asset:
            final_stac_item_id = generate_stac_item_id(
                asset.dataset_id, asset.resource_id, version_id
            )
            if final_stac_item_id != release.stac_item_id:
                self.release_repo.update_physical_outputs(
                    release_id=release_id,
                    stac_item_id=final_stac_item_id
                )
                logger.info(
                    f"Updated stac_item_id: {release.stac_item_id} -> "
                    f"{final_stac_item_id}"
                )
                release.stac_item_id = final_stac_item_id

        # Materialize STAC item to pgSTAC from cached stac_item_json
        stac_result = self._materialize_stac(release, reviewer, clearance_state)

    except Exception as e:
        # ── Step 5c: STAC failed -- attempt rollback ──
        logger.critical(
            f"STAC_MATERIALIZATION_FAILED for approved release "
            f"{release_id[:16]}...: {e}",
            exc_info=True
        )

        try:
            rolled_back = self.release_repo.rollback_approval_atomic(
                release_id=release_id,
                asset_id=release.asset_id,
                reason=str(e)
            )
            if rolled_back:
                logger.warning(
                    f"Rollback succeeded for release {release_id[:16]}... "
                    f"after STAC failure"
                )
                return {
                    'success': False,
                    'error': f"STAC materialization failed: {e}",
                    'error_type': 'StacMaterializationError',
                    'remediation': (
                        'The approval has been automatically rolled back to '
                        'PENDING_REVIEW. Investigate the STAC issue and '
                        're-approve when resolved.'
                    )
                }
            else:
                # Rollback returned False -- release was not in APPROVED state
                # (concurrent modification). This is unusual but not catastrophic.
                logger.critical(
                    f"MANUAL_INTERVENTION_REQUIRED: Rollback returned False "
                    f"for release {release_id[:16]}... (not in APPROVED state?)"
                )
                try:
                    self.release_repo.update_last_error(
                        release_id=release_id,
                        last_error=f"STAC_FAILED_ROLLBACK_INCONCLUSIVE: {e}"
                    )
                except Exception:
                    pass
                return {
                    'success': False,
                    'error': (
                        'STAC materialization failed and rollback was '
                        'inconclusive. Release state may be inconsistent.'
                    ),
                    'error_type': 'StacRollbackFailed',
                    'remediation': (
                        'MANUAL INTERVENTION REQUIRED: Check the release state '
                        'in the database. The release may need manual correction '
                        'by an administrator.'
                    )
                }

        except Exception as rollback_err:
            # ── Double failure: STAC failed AND rollback threw ──
            logger.critical(
                f"MANUAL_INTERVENTION_REQUIRED: STAC failed AND rollback "
                f"failed for release {release_id[:16]}... "
                f"STAC error: {e}, Rollback error: {rollback_err}",
                exc_info=True
            )
            try:
                self.release_repo.update_last_error(
                    release_id=release_id,
                    last_error=(
                        f"DOUBLE_FAILURE: STAC={e}, ROLLBACK={rollback_err}"
                    )
                )
            except Exception as persist_err:
                logger.error(
                    f"Failed to persist error to release: {persist_err}"
                )
            return {
                'success': False,
                'error': (
                    'STAC materialization failed AND rollback failed. '
                    'Release is APPROVED in DB but STAC item is missing.'
                ),
                'error_type': 'StacRollbackFailed',
                'remediation': (
                    'MANUAL INTERVENTION REQUIRED: The release is in APPROVED '
                    'state but STAC materialization did not complete. Contact '
                    'an administrator to either manually materialize the STAC '
                    'item or revert the release to PENDING_REVIEW.'
                )
            }

    # Check if STAC materialization returned failure (without exception)
    if not stac_result.get('success'):
        logger.critical(
            f"STAC materialization returned failure for release "
            f"{release_id[:16]}...: {stac_result.get('error')}"
        )
        # Attempt rollback for non-exception STAC failure too
        try:
            stac_error_msg = stac_result.get('error', 'STAC returned failure')
            rolled_back = self.release_repo.rollback_approval_atomic(
                release_id=release_id,
                asset_id=release.asset_id,
                reason=stac_error_msg
            )
            if rolled_back:
                return {
                    'success': False,
                    'error': f"STAC materialization failed: {stac_error_msg}",
                    'error_type': 'StacMaterializationError',
                    'remediation': (
                        'The approval has been automatically rolled back to '
                        'PENDING_REVIEW. Investigate the STAC issue and '
                        're-approve when resolved.'
                    )
                }
            else:
                try:
                    self.release_repo.update_last_error(
                        release_id=release_id,
                        last_error=f"STAC_FAILED_ROLLBACK_FALSE: {stac_error_msg}"
                    )
                except Exception:
                    pass
                return {
                    'success': False,
                    'error': 'STAC failed and rollback was inconclusive.',
                    'error_type': 'StacRollbackFailed',
                    'remediation': (
                        'MANUAL INTERVENTION REQUIRED: Check release state.'
                    )
                }
        except Exception as rollback_err:
            logger.critical(
                f"MANUAL_INTERVENTION_REQUIRED: STAC returned failure AND "
                f"rollback threw for release {release_id[:16]}...: "
                f"{rollback_err}",
                exc_info=True
            )
            try:
                self.release_repo.update_last_error(
                    release_id=release_id,
                    last_error=(
                        f"DOUBLE_FAILURE: STAC={stac_result.get('error')}, "
                        f"ROLLBACK={rollback_err}"
                    )
                )
            except Exception:
                pass
            return {
                'success': False,
                'error': 'STAC failed AND rollback failed.',
                'error_type': 'StacRollbackFailed',
                'remediation': 'MANUAL INTERVENTION REQUIRED.'
            }

    # ── Step 6: ADF trigger if PUBLIC (existing logic, unchanged) ──
    adf_run_id = None
    action = 'approved_ouo'

    if clearance_state == ClearanceState.PUBLIC:
        adf_result = self._trigger_adf_pipeline(release)
        if adf_result.get('success'):
            adf_run_id = adf_result.get('run_id')
            action = 'approved_public_adf_triggered'
            self.release_repo.update_clearance(
                release_id=release_id,
                clearance_state=clearance_state,
                cleared_by=reviewer,
                adf_run_id=adf_run_id
            )
            logger.info(
                f"ADF triggered for {release_id[:16]}...: {adf_run_id}"
            )
        else:
            logger.warning(
                f"ADF trigger failed for {release_id[:16]}...: "
                f"{adf_result.get('error')}"
            )
            action = 'approved_public_adf_failed'

    # ── Step 7: Build success response ──
    updated_release = self.release_repo.get_by_id(release_id)

    logger.info(
        f"Release {release_id[:16]}... approved by {reviewer} "
        f"(clearance: {clearance_state.value}, version: {version_id})"
    )

    response = {
        'success': True,
        'release': updated_release.to_dict() if updated_release else None,
        'action': action,
        'stac_updated': stac_result.get('success', False),
        'adf_run_id': adf_run_id
    }

    if stac_result.get('mosaic_viewer_url'):
        response['mosaic_viewer_url'] = stac_result['mosaic_viewer_url']

    return response
```

**Error handling strategy**:
- `VersionConflict` is a BusinessLogicError (expected, return dict with `error_type`).
- `StacMaterializationError` with successful rollback is a BusinessLogicError (expected failure, clean recovery).
- `StacRollbackFailed` is a double failure requiring manual intervention -- logged at CRITICAL with `MANUAL_INTERVENTION_REQUIRED` tag.
- ContractViolationErrors (programming bugs) bubble up through the outer try/except in the trigger.

**Operational requirements**:
- INFO: Successful approval with `release_id[:16]`, `asset_id[:16]`, `version_id`, `clearance_state`.
- WARNING: Version conflict with conflicting release_id. Rollback success.
- CRITICAL: STAC materialization failure. StacRollbackFailed with `MANUAL_INTERVENTION_REQUIRED` tag.
- All log messages include `release_id[:16]` and `asset_id[:16]`.

**Integration notes**:
- This replaces the existing `approve_release()` method entirely.
- `_materialize_stac()`, `_trigger_adf_pipeline()`, and `_delete_stac()` are unchanged.
- The `reject_release()`, `revoke_release()`, and query methods are unchanged.

---

### Component 6: Enhanced `platform_approve()` trigger with ERROR_STATUS_MAP

**Responsibility**: Map service-layer error_type to HTTP status codes. Thin layer -- no business logic.

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/triggers/trigger_approvals.py`

**Change**: Add ERROR_STATUS_MAP constant and replace inline error handling after the `approve_release()` call.

**ERROR_STATUS_MAP** (add near top of file, after imports):
```python
# Error type -> HTTP status code mapping for approval responses.
# Used by platform_approve() to translate service-layer error dicts.
ERROR_STATUS_MAP = {
    'VersionConflict': 409,      # Conflict: sibling holds version_id
    'ApprovalFailed': 400,       # Bad request: release not in right state
    'StacMaterializationError': 500,  # Server error: STAC failed, rolled back
    'StacRollbackFailed': 500,   # Server error: double failure, manual fix
}
```

**Replace existing error handling** (currently lines 312-321) with:
```python
if not result.get('success'):
    error_type = result.get('error_type', 'ApprovalFailed')
    status_code = ERROR_STATUS_MAP.get(error_type, 400)

    response_body = {
        "success": False,
        "error": result.get('error'),
        "error_type": error_type,
    }

    # Include remediation instructions if present
    if result.get('remediation'):
        response_body['remediation'] = result['remediation']

    # Include conflicting release_id for VersionConflict errors
    if result.get('conflicting_release_id'):
        response_body['conflicting_release_id'] = result['conflicting_release_id']

    return func.HttpResponse(
        json.dumps(response_body),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )
```

**Error handling**: The ERROR_STATUS_MAP is exhaustive for known error_types. Unknown error_types default to 400 via `.get(error_type, 400)`. This is defensive without being a backward-compatibility fallback -- it handles future error_types that may be added to the service layer.

**Operational requirements**: No additional logging in the trigger layer. The service layer already logs all error conditions. The trigger is a thin mapping layer.

**Integration notes**: The rest of `platform_approve()` (validation, _resolve_release, success response building) remains unchanged. Only the error branch after `approval_service.approve_release()` is replaced.

---

## DEFERRED DECISIONS

### D1: Existing data migration for index creation (Agent C GAP-7, Agent O F1)

If the `app.asset_releases` table already contains duplicate (asset_id, version_id) pairs with `approval_state = 'approved'`, the partial unique index creation will fail. This is a deployment concern, not a code concern.

**Why deferred**: The current dataset is small (dev environment). Check for violations before deployment with:
```sql
SELECT asset_id, version_id, COUNT(*)
FROM app.asset_releases
WHERE approval_state = 'approved' AND version_id IS NOT NULL
GROUP BY asset_id, version_id
HAVING COUNT(*) > 1;
```
If violations exist, manually resolve them (revoke duplicates) before deploying the index. This is a one-time deployment task, not a code feature.

---

### D2: statement_timeout on rollback (Agent O)

Agent O noted rollback could hang indefinitely without statement_timeout. This is true for all repository operations in this codebase, not specific to rollback.

**Why deferred**: Adding statement_timeout is a cross-cutting concern for all database operations, not specific to this feature. File a Story for "Add statement_timeout to all long-running SQL operations." The rollback SQL is a simple UPDATE + subquery UPDATE -- it should complete in milliseconds under normal conditions.

---

### D3: Connection pooling concerns (Agent O F6)

Agent O noted connection exhaustion under high approval load. The approval workflow is manual (reviewer-driven), not batch-automated.

**Why deferred**: The existing connection-per-operation pattern works for current scale. Connection pooling is already available in Docker mode via `ConnectionPoolManager`. If approval volume increases, address at the infrastructure level (connection pool for Function App mode).

---

### D4: Diagnostic endpoint for sibling state inspection (Agent O recommendation)

Agent O recommended a diagnostic endpoint to inspect sibling state after a conflict or rollback.

**Why deferred**: The existing endpoints provide sufficient visibility:
- `/api/dbadmin/diagnostics/all` -- general diagnostics
- `/api/platform/approvals/{id}` -- single release state
- `/api/platform/approvals?asset_id=X` -- all releases for an asset

A dedicated sibling-inspection endpoint adds API surface area without immediate operational need. Add as a Story if rollback incidents become frequent.

---

### D5: ADF pipeline idempotency on re-approval after rollback

If a release is approved (ADF triggered for PUBLIC), then STAC fails and rollback occurs, then the release is re-approved (ADF triggered again) -- ADF may run twice. ADF pipeline logic must be idempotent.

**Why deferred**: ADF pipeline idempotency is an existing concern independent of rollback. The `export_to_public` pipeline should already be idempotent (overwrite semantics). Verify separately as part of ADF testing.

---

## RISK REGISTER

### R1: Double-failure state (StacRollbackFailed) -- MEDIUM

**Description**: If STAC materialization fails AND `rollback_approval_atomic()` also fails (throws exception or returns False), the release is in APPROVED state with no STAC item. This is the "approved-but-broken" state the spec aims to prevent.

**Likelihood**: Low. The rollback is a simple SQL UPDATE on a single table. It fails only under connection loss, database crash, or concurrent state modification (another process changed the release's approval_state between the atomic approval and the rollback attempt).

**Impact**: High. Manual intervention required. The release appears approved to the API but has no STAC presence.

**Mitigation**:
1. Log at CRITICAL with `MANUAL_INTERVENTION_REQUIRED` tag.
2. Return `remediation` instructions in the API response.
3. Persist error to `release.last_error` for visibility in admin dashboard.
4. The error message includes the specific STAC error AND the rollback error for diagnostics.

**Residual risk**: Manual intervention is required. No automated recovery is possible for double failures.

---

### R2: READ COMMITTED race window between NOT EXISTS and COMMIT -- LOW

**Description**: Two concurrent approvals for the same version_id can both pass the NOT EXISTS guard before either commits. The partial unique index then catches the second at commit time via UniqueViolation.

**Likelihood**: Very low. Approvals are manual, reviewer-driven actions. Two reviewers simultaneously approving the same version_id for sibling releases of the same asset is unlikely.

**Impact**: None (functional). The second approval fails cleanly with a VersionConflict error. The only cost is wasted work (Step 1 clearing is_latest, then rolling back via UniqueViolation catch).

**Mitigation**: The partial unique index is the authoritative enforcer. UniqueViolation is caught and translated to `return False`. The service layer provides a diagnostic VersionConflict response.

**Residual risk**: None functionally. The invariant is maintained.

---

### R3: Index creation failure on deployment -- LOW

**Description**: If existing data violates the uniqueness constraint, `CREATE UNIQUE INDEX` will fail.

**Likelihood**: Low in dev environment with small dataset. Higher if production data has been accumulating without this constraint.

**Impact**: Deployment fails with a clear PostgreSQL error. The code-level guards (NOT EXISTS) still work without the index. The index adds defense-in-depth but is not the only protection.

**Mitigation**: Run the diagnostic query (D1) before deployment. Resolve violations manually.

**Residual risk**: If the index is not created (query finds violations), the code-level NOT EXISTS guard still provides protection. The system operates safely but without the database-level backstop for concurrent races.

---

### R4: Stale stac_item_id after rollback -- VERY LOW

**Description**: After rollback, stac_item_id may still contain the version-id form (e.g., "floods_jakarta_v1") instead of the ordinal form (e.g., "floods_jakarta_ord1").

**Likelihood**: Only occurs when (a) the stac_item_id update succeeded before (b) STAC materialization failed.

**Impact**: Cosmetic only. The release is in PENDING_REVIEW state, so no STAC operations reference this value. On re-approval, stac_item_id is recalculated.

**Mitigation**: The stac_item_id is recalculated at approval time. The stale value is overwritten on re-approval.

**Residual risk**: If someone queries the release between rollback and re-approval, they see the stale stac_item_id. This is cosmetic, not functional.

---

### R5: Audit trail confusion after rollback -- INFORMATIONAL

**Description**: After rollback, `reviewer` and `reviewed_at` still contain the failed approval attempt's data. The `last_error` field contains "ROLLBACK: {reason}". This combination (PENDING_REVIEW state + reviewer set + last_error set) could confuse operators.

**Likelihood**: Certain (by design -- we chose to preserve audit fields).

**Impact**: Operator confusion. Not a data integrity issue.

**Mitigation**: The `last_error` field containing "ROLLBACK: ..." makes the state unambiguous. The `approval_state = pending_review` + `last_error = ROLLBACK:...` combination is documented as "this release was approved, STAC failed, and it was automatically rolled back."

**Residual risk**: Operators need to understand this state combination. Add a note to operational documentation.
