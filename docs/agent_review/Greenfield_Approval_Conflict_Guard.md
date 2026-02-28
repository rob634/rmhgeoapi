# Greenfield Report: Approval Conflict Guard & Atomic Rollback

**Date**: 27 FEB 2026
**Pipeline**: Greenfield Agent (S -> A+C+O -> M -> B -> V -> Spec Diff)
**Subsystem**: Version-ID conflict guard + STAC rollback for release approval

---

## Pipeline Summary

| Agent | Role | Key Finding |
|-------|------|-------------|
| S | Spec Writer | 6 contracts, 3 invariants, 2 open questions |
| A | Advocate | 6 components, hybrid guard (index + NOT EXISTS), rollback via SQL subquery |
| C | Critic | 4 ambiguities, 7 edge cases, 7 gaps, 3 contradictions, 6 open questions |
| O | Operator | 6 failure modes, deploy order requirement, connection exhaustion risk |
| M | Mediator | 8 conflicts resolved, 3 tensions noted, 5 deferred decisions, 5 risks |
| B | Builder | 4 files modified, all spec requirements implemented |
| V | Validator | NEEDS MINOR WORK — 1 critical concern (C1: explicit rollback in UniqueViolation) |

---

## Key Resolutions from M

1. **NOT EXISTS scoped to APPROVED only** (matching index) — rejected releases don't block
2. **UniqueViolation caught inside connection block** — explicit conn.rollback() (V's C1 fix applied)
3. **Audit trail preserved on rollback** — reviewer/reviewed_at/notes survive
4. **New `get_approved_by_version()` method** — no backward compat parameter
5. **Weakened is_latest invariant** — "at most one" (zero valid when no approved siblings)
6. **ERROR_STATUS_MAP dict** — declarative, extensible, replaces inline if/else

## V's Spec Diff Verdict

- **MATCHES**: All 9 spec requirements correctly inferred from code
- **GAPS**: None
- **EXTRAS**: 1 critical (C1 — fixed), 5 pre-existing issues (out of scope)
- **Post-fix rating**: PRODUCTION READY for this subsystem

## Files Modified

| File | Changes |
|------|---------|
| `core/models/asset.py` | Added `idx_releases_version_conflict` partial unique index |
| `infrastructure/release_repository.py` | NOT EXISTS guard + UniqueViolation catch + `rollback_approval_atomic()` + `get_approved_by_version()` |
| `services/asset_approval_service.py` | Rewrote `approve_release()` with conflict detection + auto-rollback |
| `triggers/trigger_approvals.py` | Added `ERROR_STATUS_MAP` + typed error propagation |

## Deferred Decisions

- D1: Pre-deployment duplicate data check (one-time manual task)
- D2: statement_timeout (cross-cutting concern for all SQL)
- D3: Connection pooling for Function App mode
- D4: Diagnostic endpoint for sibling state inspection
- D5: ADF pipeline idempotency on re-approval

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| R1: Double failure (STAC + rollback) | Low | High | CRITICAL log + MANUAL_INTERVENTION_REQUIRED tag |
| R2: READ COMMITTED race | Very Low | None (functional) | UniqueViolation caught, translated to VersionConflict |
| R3: Index creation failure (existing duplicates) | Low | Low | Pre-deployment check query |
| R4: Stale stac_item_id after rollback | Very Low | Low | Recalculated on re-approval |
| R5: Audit trail confusion | Informational | Low | last_error contains ROLLBACK prefix |

## Deployment Steps

1. Deploy code via `./deploy.sh orchestrator`
2. Run `POST /api/dbadmin/maintenance?action=ensure&confirm=yes` to create the partial unique index
3. Verify index exists in deployment logs
4. Test: approve a release, verify 200 response
5. Test: approve same version_id for sibling, verify 409 VersionConflict

## Full Agent Reports

- Mediator Resolution: `docs/agent_review/agents/MEDIATOR_RESOLUTION.md`
- Design Doc: `docs/plans/2026-02-27-approval-conflict-guard-design.md`
