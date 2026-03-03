# COMPETE Constitution Re-Runs: Approval Workflow + CoreMachine

**Date**: 02 MAR 2026
**Pipeline**: COMPETE (Adversarial Review) with Constitution Enforcement
**Runs**: 28 (Approval Workflow) + 29 (CoreMachine Orchestration)
**Total Tokens**: ~731,565 (349K + 382K)

---

## Run 28: Approval Workflow

**Scope**: approve/reject/revoke lifecycle (7 files, ~7,000 lines)
**Split**: B (Internal vs External)
- Alpha: Internal Logic — asset_approval_service.py, release_repository.py, asset.py, stac_materialization.py
- Beta: External Interfaces — trigger_approvals.py, platform.py, pgstac_repository.py, release_repository.py

### EXECUTIVE SUMMARY

The Approval Workflow subsystem is architecturally sound in its core design: the release-centric model, atomic SQL with NOT EXISTS conflict guard, and DB-first-then-STAC ordering are all correct patterns. However, it has one genuine data integrity gap (approving stale/failed releases) that has been a known open issue since SIEGE Run 25 and remains unguarded. The pgSTAC repository exhibits a systematic error-swallowing pattern across 11 methods that returns falsy sentinels on database errors, cascading into incorrect downstream decisions. The vector detection heuristic fallback in `_is_vector_release` is the third significant issue: on any DB error, it silently classifies a release as vector and skips STAC materialization entirely.

### TOP 5 FIXES

#### Fix 1: Block approval of non-COMPLETED releases (CRITICAL)

| Field | Detail |
|-------|--------|
| **WHAT** | Add a hard guard that rejects approval when `processing_status != COMPLETED` |
| **WHY** | An operator can approve a release that is still processing, has failed, or was never started. The broken dataset gets published to pgSTAC. Known open bug SG5-1/LA-1. |
| **WHERE** | `services/asset_approval_service.py`, `approve_release()`, lines 154-159. Also `infrastructure/release_repository.py`, `approve_release_atomic()`, lines 1255-1256 and 1300-1301 |
| **HOW** | Replace warning with hard rejection return. Add `AND processing_status = 'completed'` to both UPDATE WHERE clauses in the atomic SQL. Defense-in-depth. |
| **EFFORT** | Small |
| **RISK** | Low |

#### Fix 2: Eliminate error swallowing in PgStacRepository (HIGH)

| Field | Detail |
|-------|--------|
| **WHAT** | Make 11 pgSTAC query methods propagate exceptions instead of returning falsy sentinels |
| **WHY** | `collection_exists` returns False on error → unnecessary recreation. `delete_item` returns False → skips extent recalc. `get_collection_item_count` returns 0 → incorrect collection deletion. Section 3.3 violation. |
| **WHERE** | `infrastructure/pgstac_repository.py`, methods at lines: 232-234, 347-349, 398-400, 455-456, 491, 533-534, 569, 766, 805-806, 858-859 |
| **HOW** | Remove `except Exception` blocks from query methods, let exceptions propagate. Callers in stac_materialization.py already have try/except blocks. |
| **EFFORT** | Medium (1-4 hours) |
| **RISK** | Medium — callers assume falsy = "not found", need to verify each call site |

#### Fix 3: Remove heuristic fallback in `_is_vector_release` (HIGH)

| Field | Detail |
|-------|--------|
| **WHAT** | Remove fallback that classifies a release as vector when DB lookup fails |
| **WHY** | On transient DB error, a raster release with empty blob_path gets misclassified as vector, STAC materialization is silently skipped, approved raster never appears in catalog. Section 1.1 violation. |
| **WHERE** | `services/stac_materialization.py`, `_is_vector_release()`, lines 739-745 |
| **HOW** | Replace fallback with `raise RuntimeError(f"Cannot determine data_type for release...")`. Caller at line 158 is already inside try/except that triggers rollback. |
| **EFFORT** | Small |
| **RISK** | Low |

#### Fix 4: Clear version_ordinal in rollback + fix offset passthrough (MEDIUM)

| Field | Detail |
|-------|--------|
| **WHAT** | (a) Add `version_ordinal = NULL` to rollback SQL. (b) Pass offset to query in approvals list endpoint. |
| **WHY** | (a) After rollback, release retains ordinal slot while having no version_id — stale ordinal. (b) Pagination is broken: `?offset=20` returns same results as `?offset=0`. |
| **WHERE** | (a) `infrastructure/release_repository.py`, `rollback_approval_atomic()`, line 1395. (b) `triggers/trigger_approvals.py`, `platform_approvals_list()`, lines 739-745 |
| **HOW** | (a) Add `version_ordinal = NULL` to SET clause. (b) Pass offset to `list_by_approval_state()` and `list_pending_review()`. |
| **EFFORT** | Small |
| **RISK** | Low |

#### Fix 5: Validate int() conversions + add bulk status input limit (MEDIUM)

| Field | Detail |
|-------|--------|
| **WHAT** | (a) Wrap int() conversions in try/except. (b) Cap bulk status IDs at 100. |
| **WHY** | (a) `?limit=abc` raises unhandled ValueError → raw 500. (b) Unbounded IDs → massive IN clause, DB degradation. |
| **WHERE** | `triggers/trigger_approvals.py`, lines 693-694 and 888-890 |
| **HOW** | (a) try/except ValueError returning 400. (b) Check `len(all_ids) > 100` before processing. |
| **EFFORT** | Small |
| **RISK** | Low |

### ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| TOCTOU gap in revocation (M4) | SQL WHERE clause is the real guard, in-memory check is UX sugar | Adding non-SQL side effects between read and write |
| Tiled bbox uses first record (B-3) | Fallback path only; `materialize_collection()` corrects extent | Fallback becomes primary path |
| No auth at endpoints (F-5) | Pre-production, APIM/network auth may exist | Moving to production |
| Hardcoded `geo.table_catalog` (B-6) | Single schema, standalone function without schema attr | Multi-tenant deployments |
| `_build_insert_sql` f-string (H3/F-1) | Column names from constant tuple, no injection risk | Adding dynamic column sources |

### ARCHITECTURE WINS

1. **Atomic SQL with NOT EXISTS version conflict guard** — `approve_release_atomic` prevents double-approval in a single statement
2. **DB-first-then-STAC ordering with rollback** — Correct compensating transaction pattern
3. **Release-centric approval model** — Asset (identity) vs AssetRelease (mutable) separation prevents race conditions
4. **Revocation WHERE clause as invariant enforcer** — SQL-level `AND approval_state = 'approved'` makes revocation inherently idempotent
5. **Vector skip in STAC materialization** — Clean early return with structured response for design decision

### CONSTITUTION VIOLATIONS FOUND

| Section | Rule | Violation | Severity |
|---------|------|-----------|----------|
| 1.1 | No fallbacks | `_is_vector_release` heuristic fallback | HIGH |
| 1.1 | No fallbacks | `data_type or 'raster'` in `_create_routes` | LOW |
| 1.2 | SQL composition | `_build_insert_sql` f-string columns | LOW (constant data) |
| 1.2 | SQL composition | Hardcoded `geo.table_catalog` | MEDIUM |
| 3.3 | No exception swallowing | pgSTAC repository 11 methods | HIGH |

---

## Run 29: CoreMachine Orchestration

**Scope**: Job→Stage→Task pattern, state management (8 files, ~5,600 lines)
**Split**: A (Design vs Runtime)
- Alpha: Architecture/Design — machine.py, state_manager.py, base.py (jobs), mixins.py, services/__init__.py
- Beta: Correctness/Runtime — machine.py, state_manager.py, transitions.py, task_handler.py, job_handler.py

### EXECUTIVE SUMMARY

The CoreMachine orchestration subsystem is structurally sound. The composition-based architecture, explicit registries, and "last task turns out the lights" pattern are well-implemented and demonstrate mature design thinking. However, the subsystem has a systemic exception-swallowing pattern across both Service Bus handlers and the StateManager that prevents Service Bus retry delivery and silently drops database lookup failures. The most impactful fix — re-raising exceptions in the Service Bus handlers — is also the highest-risk, because Azure Functions will retry aggressively without careful dead-letter configuration. The finalize_job fallback creates a backward-compatibility path that directly violates the project constitution.

### TOP 5 FIXES

#### Fix 1: Re-raise transient exceptions in job/task handlers (CRITICAL)

| Field | Detail |
|-------|--------|
| **WHAT** | Both Service Bus handlers catch ALL exceptions and return result dicts instead of re-raising, preventing Service Bus retry |
| **WHY** | If DB is also unreachable, both the processing and the mark-as-FAILED call fail. Message is consumed and permanently lost. Silent data loss vector. |
| **WHERE** | `triggers/service_bus/job_handler.py`, `_handle_exception`, lines 236-238. `triggers/service_bus/task_handler.py`, `_handle_exception`, line 259 |
| **HOW** | Classify using existing `RETRYABLE_EXCEPTIONS` tuple from machine.py. For transient errors, re-raise after mark_failed attempt. Keep swallow for permanent errors. Verify dead-letter queue config first. |
| **EFFORT** | Medium (2-3 hours) |
| **RISK** | Medium — needs dead-letter queue config verified |

#### Fix 2: Remove finalize_job fallback (HIGH)

| Field | Detail |
|-------|--------|
| **WHAT** | When `finalize_job()` raises, code catches and creates `completed_with_errors` fallback, marking job COMPLETED |
| **WHY** | Constitution 1.1 violation. Masks finalization bugs. Produces corrupt output that downstream consumers treat as valid. |
| **WHERE** | `core/machine.py`, `_complete_job`, lines 2099-2136 |
| **HOW** | Replace with `self._mark_job_failed()` call and raise `BusinessLogicError`. |
| **EFFORT** | Small |
| **RISK** | Low — any "completed_with_errors" job was already producing bad output |

#### Fix 3: Validate stage_complete message with Pydantic (HIGH)

| Field | Detail |
|-------|--------|
| **WHAT** | `process_stage_complete_message` accepts raw Dict, no validation. StageCompleteMessage Pydantic model exists but unused for inbound. |
| **WHY** | Missing `job_id` or non-integer `completed_stage` causes confusing downstream TypeError instead of validation error. External input boundary. |
| **WHERE** | `core/machine.py`, `process_stage_complete_message`, line 684. Also `triggers/service_bus/job_handler.py` line 154 |
| **HOW** | Use `StageCompleteMessage.model_validate(message_dict)` in job_handler, change machine.py signature to accept `StageCompleteMessage`. |
| **EFFORT** | Small |
| **RISK** | Low |

#### Fix 4: Eliminate duplicate repository creation (HIGH)

| Field | Detail |
|-------|--------|
| **WHAT** | CoreMachine and StateManager independently create separate repository bundles via `RepositoryFactory.create_repositories()` |
| **WHY** | Double connection pools. In Azure Functions with limited PostgreSQL connections, this wastes connections and increases cold-start time. |
| **WHERE** | `core/machine.py`, `repos` property, lines 204-222. `core/state_manager.py`, `repos` property, lines 115-119 |
| **HOW** | Share repos via CoreMachine passing its bundle to StateManager, or make `RepositoryFactory` return a cached singleton. |
| **EFFORT** | Small (1 hour) |
| **RISK** | Low |

#### Fix 5: Stop _confirm_task_queued from swallowing DB failures (MEDIUM)

| Field | Detail |
|-------|--------|
| **WHAT** | `_confirm_task_queued` catches all exceptions and continues. If DB unreachable, task proceeds in PENDING state, then PENDING→PROCESSING transition fails. |
| **WHY** | Combined with Fix 1 not applied, creates double-swallow: transient DB outage → permanent task loss. |
| **WHERE** | `triggers/service_bus/task_handler.py`, `_confirm_task_queued`, lines 208-210 |
| **HOW** | Re-raise for transient DB errors (ConnectionError, TimeoutError, OSError). Swallow only state conflict errors. |
| **EFFORT** | Small |
| **RISK** | Low |

### ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| @staticmethod vs @classmethod mismatch (A-HIGH-1) | Works at runtime, all jobs use mixin | Adding mypy strict mode |
| Lazy repos not thread-safe (B-MED2) | Azure Functions single-threaded per invocation | Multi-threaded execution model |
| Partial task queueing returns "partial" (B-MED5) | Total failure handled; orphans cleaned up; stage completion arithmetic correct | Jobs requiring exact N inputs |
| StateManager methods swallow exceptions (B-MED4) | Read operations; callers check for None | Need to distinguish "not found" from "DB down" |
| fail_tasks_for_job bypasses state machine (G-B5) | Cleanup operation, force-fail is the correct behavior | Adding audit logging for all transitions |

### ARCHITECTURE WINS

1. **Composition over inheritance** — CoreMachine delegates to injected components with zero job-specific logic
2. **Explicit registries over decorator magic** — Comment documents the real lesson learned from decorator failures
3. **"Last task turns out the lights" with atomic SQL** — Advisory-lock-protected stage completion eliminates race conditions
4. **Retryable vs permanent exception classification** — Clean, extensible tuples for error categorization
5. **Consolidated `_mark_job_failed` with platform callback** — Single-path ensures platform callback always invoked on failure
6. **Orphan task cleanup in `_individual_queue_tasks`** — 26 FEB fix prevents stage deadlocks from failed SB sends

### CONSTITUTION VIOLATIONS FOUND

| Section | Rule | Violation | Severity |
|---------|------|-----------|----------|
| 1.1 | No fallbacks | `finalize_job()` fallback masks bugs as completed_with_errors | HIGH |
| 3.3 | No exception swallowing | Job handler swallows all exceptions | CRITICAL |
| 3.3 | No exception swallowing | Task handler swallows all exceptions | CRITICAL |
| 3.3 | No exception swallowing | `_confirm_task_queued` swallows exceptions | MEDIUM |
| 3.3 | No exception swallowing | StateManager methods swallow exceptions | MEDIUM |

### ADDITIONAL FINDING: State Machine Inconsistency

Three locations define the task state machine with conflicting rules:

| Transition | `transitions.py` | `task.py` `can_transition_to()` | `base.py` docstring |
|---|---|---|---|
| QUEUED → FAILED | Not allowed | Not allowed | Allowed |
| QUEUED → CANCELLED | Allowed | Not allowed | Not mentioned |
| PROCESSING → PENDING | Allowed | Not allowed | Not mentioned |

`_validate_status_transition()` in `base.py` delegates to `TaskRecord.can_transition_to()`, making `transitions.py` effectively dead code for validation. The docstring in `base.py` adds a third inconsistent definition.

---

## Cross-Review Synthesis

### Shared Patterns Found

1. **Exception swallowing is the dominant anti-pattern** — pgSTAC repository (Run 28), Service Bus handlers (Run 29), StateManager (Run 29), `_confirm_task_queued` (Run 29). All are Section 3.3 violations. This is the single most important pattern to address systematically.

2. **Constitution enforcement caught real issues** — Section 1.1 (fallbacks) found `_is_vector_release` heuristic and `finalize_job` fallback. Section 1.2 (SQL) found hardcoded schema. Section 3.3 (swallowing) found the systemic pattern. The Constitution added value over the original runs.

3. **Known critical bug reconfirmed** — SG5-1/LA-1 (stale release approval) continues to be the most important unresolved data integrity issue. Both reviews reinforced this from different angles.

### Comparison With Original Runs

| Aspect | Run 1 (Original CoreMachine) | Run 29 (Constitution Rerun) |
|--------|------|------|
| Top finding | Non-atomic task creation | Service Bus handler exception swallowing |
| Constitution violations | Not checked | 5 violations found (2 CRITICAL) |
| Total findings | ~15 | ~24 |
| Blind spots caught | 0 (no Gamma blind spot detection) | 9 (Gamma found job/task handler swallowing) |

| Aspect | Run 4 (Original Approval) | Run 28 (Constitution Rerun) |
|--------|------|------|
| Top finding | Concurrent approval race | Stale release approval (SG5-1) |
| Constitution violations | Not checked | 5 violations found (1 CRITICAL via Section 3.3) |
| Total findings | ~12 | ~22 |
| Blind spots caught | 0 | 8 (Gamma found pgSTAC error swallowing cascade) |

### Token Usage

| Run | Agent | Tokens | Tool Uses | Duration |
|-----|-------|--------|-----------|----------|
| 28 | Alpha | 91,682 | 20 | 163s |
| 28 | Beta | 108,344 | 26 | 159s |
| 28 | Gamma | 96,506 | 20 | 169s |
| 28 | Delta | 52,640 | 30 | 177s |
| **28 Total** | | **349,172** | **96** | **668s** |
| 29 | Alpha | 104,474 | 36 | 191s |
| 29 | Beta | 106,028 | 37 | 446s |
| 29 | Gamma | 114,550 | 32 | 231s |
| 29 | Delta | 57,341 | 29 | 148s |
| **29 Total** | | **382,393** | **134** | **1,016s** |
| **Combined** | | **731,565** | **230** | **1,684s** |
