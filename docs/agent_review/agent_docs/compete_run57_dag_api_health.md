# COMPETE Run 57: DAG API Endpoints + Health Monitoring + Scheduler

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DAG API endpoints, health monitoring, scheduler, schedule repository, startup orchestrator |
| **Version** | v0.10.6.3 |
| **Split** | B (Internal vs External) |
| **Files** | 6 target files |
| **Findings** | 17 total: 2 CRITICAL, 4 HIGH, 7 MEDIUM, 4 LOW |
| **Report** | `agent_docs/compete_run57_dag_api_health.md` |

---

## EXECUTIVE SUMMARY

The DAG API, health monitoring, and scheduler subsystem is architecturally sound. The fail-open scheduler design, deterministic schedule IDs, and per-schedule exception isolation are well-executed. The health subsystem provides comprehensive component-level monitoring. However, the trigger layer (`dag_bp.py`) contains multiple raw DB access patterns that bypass the repository layer (Standard 1.4), a broken 409-duplicate detection path in schedule creation, and a latent `AttributeError` in the scheduler's error-logging code path. The startup orchestrator is clean and well-structured. The most urgent fixes are the duplicate schedule detection bug (which returns 500 instead of 409) and the `registry.list_all()` call to a nonexistent method.

---

## TOP 5 FIXES

### Fix 1: Schedule creation duplicate detection returns 500 instead of 409

- **WHAT**: `dag_create_schedule` checks `if created is None` for 409, but `ScheduleRepository.create()` never returns `None` -- it raises `DatabaseError` on unique constraint violation.
- **WHY**: A user creating a duplicate schedule gets a confusing 500 "Internal error" instead of the documented 409 "Schedule already exists". The `None` check on line 690 is dead code.
- **WHERE**: `triggers/dag/dag_bp.py`, `dag_create_schedule()`, lines 682-693 and `infrastructure/schedule_repository.py`, `create()`, lines 108-128.
- **HOW**: Option A (preferred): Catch `psycopg.errors.UniqueViolation` specifically in `ScheduleRepository.create()` and return `None`. Option B: Catch `DatabaseError` in the endpoint and inspect the underlying cause. Option A is cleaner because it keeps the error semantics in the repository.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low -- only changes error handling for a specific exception type.
- **CONFIDENCE**: CONFIRMED -- traced from `dag_create_schedule` line 682 through `ScheduleRepository.create` line 121. A PK collision on `schedule_id` raises `psycopg.Error` (specifically `UniqueViolation`), which is caught at line 121 and wrapped in `DatabaseError`, which propagates to the endpoint's `except Exception` at line 697, returning 500.

### Fix 2: `registry.list_all()` -- nonexistent method in scheduler error path

- **WHAT**: `dag_scheduler.py` line 311 calls `registry.list_all()` but `WorkflowRegistry` only has `list_workflows()`.
- **WHY**: When a scheduled workflow's YAML file is missing or renamed, the error handler itself crashes with `AttributeError`, producing a confusing double error and obscuring the root cause.
- **WHERE**: `core/dag_scheduler.py`, `_fire_schedule()`, line 311.
- **HOW**: Change `list(registry.list_all())` to `registry.list_workflows()`.
- **EFFORT**: Small (< 15 minutes).
- **RISK OF FIX**: Low -- one-line fix in an error-logging path.
- **CONFIDENCE**: CONFIRMED -- `WorkflowRegistry` in `core/workflow_registry.py` defines `list_workflows()` at line 118. No `list_all` method exists.

### Fix 3: Raw DB access in trigger layer bypasses repository pattern (4 endpoints)

- **WHAT**: `dag_list_runs`, `dag_get_run` (task counts + active tasks), `dag_get_run_tasks`, and `dag_get_schedule` (recent runs) all create `ConnectionManager(ManagedIdentityAuth())` directly in the trigger layer and execute raw SQL queries.
- **WHY**: Violates Standard 1.4 (database access only through repository pattern). SQL queries are now properly composed with `sql.SQL()` (fixed from Run 50), but the access pattern still leaks infrastructure concerns into the trigger layer. This makes testing harder, creates connection proliferation, and duplicates auth setup across 4 endpoints.
- **WHERE**: `triggers/dag/dag_bp.py`:
  - `dag_list_runs()`: lines 117-124
  - `dag_get_run()`: lines 176-206 (two separate queries with two separate connections)
  - `dag_get_run_tasks()`: lines 267-293
  - `dag_get_schedule()`: lines 773-789
- **HOW**: Add `list_runs(status, workflow, limit)`, `get_task_counts(run_id)`, `get_active_tasks(run_id)`, `list_tasks(run_id, status)`, and `get_recent_runs_for_schedule(schedule_id)` methods to the appropriate repository classes (`WorkflowRunRepository` and `ScheduleRepository`). Replace the raw queries in `dag_bp.py` with repository calls.
- **EFFORT**: Medium (2-3 hours -- 5 new repo methods + endpoint refactoring).
- **RISK OF FIX**: Low -- moves existing working SQL to repository layer without changing behavior.
- **CONFIDENCE**: CONFIRMED -- all 4 endpoints verified by direct code inspection.

### Fix 4: `limit` query parameter not validated for non-numeric input

- **WHAT**: `dag_list_runs` line 85: `int(req.params.get('limit', '50'))` throws `ValueError` on non-numeric input, caught by generic `except Exception` and returned as 500.
- **WHY**: A malformed query parameter (`?limit=abc`) returns 500 "Internal error" instead of 400 "Invalid limit parameter". Poor client experience for a simple input validation gap.
- **WHERE**: `triggers/dag/dag_bp.py`, `dag_list_runs()`, line 85.
- **HOW**: Wrap in try/except: `try: limit = min(int(req.params.get('limit', '50')), 200) except ValueError: return _error_response("limit must be a positive integer")`.
- **EFFORT**: Small (< 15 minutes).
- **RISK OF FIX**: Low.
- **CONFIDENCE**: CONFIRMED -- `int("abc")` raises `ValueError`.

### Fix 5: Health check does not detect stale primary loop (stuck thread)

- **WHAT**: `DAGBrainSubsystem._check_primary_loop()` only checks `thread.is_alive()`. If the thread is alive but stuck (e.g., blocked on a long DB query or deadlock), health reports "healthy" indefinitely.
- **WHY**: A stuck DAG Brain primary loop means no workflows advance, but health checks continue to report all-green. This defeats the purpose of health monitoring for the system's most critical component.
- **WHERE**: `docker_health/dag_brain.py`, `_check_primary_loop()`, lines 116-134.
- **HOW**: Add a staleness check: compare `loop_status["last_scan_at"]` to `datetime.now(timezone.utc)`. If the delta exceeds 2x the expected scan interval (e.g., > 60s for a 30s interval), report "warning" or "unhealthy". Same pattern should be applied to `_check_janitor()` and `_check_scheduler()`.
- **EFFORT**: Small (< 1 hour -- add staleness check to 3 thread monitors).
- **RISK OF FIX**: Low -- additive check, does not change existing healthy/unhealthy logic.
- **CONFIDENCE**: PROBABLE -- the stuck-thread scenario requires external conditions (DB deadlock, network hang), but the health check gap is confirmed by code inspection.

---

## ADDITIONAL FINDINGS

### HIGH

| # | Finding | File | Lines | Confidence |
|---|---------|------|-------|------------|
| 6 | `dag_get_run` opens TWO separate DB connections (task counts + active tasks) in the same request, creating unnecessary connection pressure | `dag_bp.py` | 176-206 | CONFIRMED |
| 7 | No input validation on `status` filter -- any string is passed to SQL WHERE clause. While parameterized (safe from injection), invalid statuses return empty results with no feedback to the caller | `dag_bp.py` | 83, 103-104, 263, 283 | CONFIRMED |

### MEDIUM

| # | Finding | File | Lines | Confidence |
|---|---------|------|-------|------------|
| 8 | `os.environ` direct access in `shared.py` for APP_SCHEMA and TITILER_BASE_URL (Standard 2.2 violation) | `shared.py` | 259, 319 | CONFIRMED |
| 9 | `_SELECT_COLS` uses plain string concatenation inside `sql.SQL()` -- inconsistent with Standard 1.2 style (not a security issue since constants, but mixed patterns) | `schedule_repository.py` | 51, 92, 142, 292 | CONFIRMED |
| 10 | `record_run` does not check `cur.rowcount` -- if schedule is deleted between fire and record, UPDATE affects 0 rows silently, orphaning the run | `schedule_repository.py` | 376-415 | CONFIRMED |
| 11 | `dag_create_schedule` re-instantiates `WorkflowRegistry` and calls `load_all()` on every request (lines 654-658). Acceptable at current scale but wasteful | `dag_bp.py` | 654-658 | CONFIRMED |
| 12 | `_fire_schedule` re-instantiates `WorkflowRegistry` and `load_all()` every time a schedule fires (lines 302-304). Same registry-per-call pattern as endpoint | `dag_scheduler.py` | 302-304 | CONFIRMED |
| 13 | Health check `_check_workflow_registry()` also instantiates `WorkflowRegistry` with `handler_names` kwarg (line 234) but `dag_create_schedule` instantiates without it (line 657) -- different validation behavior for same check | `dag_brain.py` vs `dag_bp.py` | 232-234, 654-657 | CONFIRMED |
| 14 | Startup orchestrator still validates Service Bus (Phases 3+4) even though Service Bus is deprecated (Standard 5.4). Wastes startup time and produces confusing warnings when SB is not configured | `orchestrator.py` | 82-102 | PROBABLE |

### LOW

| # | Finding | File | Lines | Confidence |
|---|---------|------|-------|------------|
| 15 | `dag_bp.py` imports `WorkflowRunRepository` at line 79 inside handler but never uses it directly (SQL queries bypass it) -- misleading import | `dag_bp.py` | 79 | CONFIRMED |
| 16 | Deterministic `request_id` in `_fire_schedule` uses minute-level granularity -- two manual triggers within same minute produce identical request_ids | `dag_scheduler.py` | 316-317 | CONFIRMED |
| 17 | `dag_bp.py` file header says `LAST_REVIEWED: 17 MAR 2026` -- stale (schedule endpoints added 20 MAR) | `dag_bp.py` | 9 | CONFIRMED |

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|-------------|
| No per-endpoint auth on DAG routes | Gated at blueprint registration (`has_admin_endpoints`). Function App is not publicly internet-facing without Azure Easy Auth. | B2E/B2C auth layer is implemented |
| Thread-safety of health metric reads | CPython GIL makes simple attribute reads atomic. Scheduler/janitor counters are int/datetime, not compound structures. | Move to multi-process or non-CPython runtime |
| WorkflowRegistry re-instantiated per fire/request | YAML files are small, load_all is fast. Accepted in Run 50 at current scale. | Workflow count > 50 or poll interval < 5s |
| Startup orchestrator validates Service Bus | Phases 3+4 are skipped when prior phases fail. SB validation produces pass/fail results that are informational. No harm beyond minor startup latency. | v0.11.0 removes SB entirely |

---

## ARCHITECTURE WINS

- **Fail-open scheduler loop**: Per-schedule exception isolation (lines 181-276 in `dag_scheduler.py`) ensures one bad cron expression or missing workflow never blocks other schedules. This is textbook resilient design.
- **Deterministic schedule_id**: SHA256-based deduplication (lines 671-677 in `dag_bp.py`) prevents accidental duplicate schedule creation at the data layer.
- **Health subsystem composition**: `DAGBrainSubsystem` extends `WorkerSubsystem` base class cleanly, with each component check isolated. The `compute_status` rollup (worst-component-wins) is correct and simple.
- **Cron validation before persistence**: Both `dag_create_schedule` and `dag_update_schedule` validate cron expressions via `croniter` before writing to the database -- invalid expressions never reach the scheduler.
- **SQL composition discipline in ScheduleRepository**: All queries use `psycopg.sql.SQL()` and `sql.Identifier()`. No f-string SQL. Column list constant approach is safe (hardcoded values only).
- **Concurrency guard**: `get_active_run_count` query correctly checks `pending` and `running` statuses against `workflow_runs.schedule_id`, enforcing `max_concurrent` per schedule. This was fixed since Run 50 (which found the join was broken).
- **Startup orchestrator sequencing**: Phases run in dependency order (env vars -> imports -> SB DNS -> SB queues) with proper skip-on-failure logic. `STARTUP_STATE` singleton is clean and well-documented.
