# V10 Accepted Risks & Architecture Decisions

**Version**: v0.10.6.5
**Last Updated**: 27 MAR 2026
**Source**: COMPETE adversarial code review pipeline — Runs 1-4, 42, 46-47, 53-57

**Note**: Deferred bug fixes are tracked in `V10_DEFERRED_FIXES.md`. This file is for conscious architecture decisions and accepted risks only.

---

## Connection Infrastructure (Run 1)

### A. `update_task` GET-before-UPDATE for DEBUG logging

Extra DB read per task update for diagnostic logging. Bounded by task count per stage (1-20).

- **Impact**: ~2ms overhead per task update
- **Revisit when**: 100+ task stages become common
- **File**: `infrastructure/postgresql.py`, `update_task()`

### ~~B. God-class `PostgreSQLRepository` (~2600 lines)~~ — RESOLVED 14 MAR 2026

Decomposed via internal composition (V0.10.2.0):
- `db_auth.py` → `ManagedIdentityAuth` (token acquisition, connection strings)
- `db_connections.py` → `ConnectionManager` (pooled/single-use routing, circuit breaker, retry)
- `db_utils.py` → Shared utilities (type adapters, JSONB parsing, redaction)
- `postgresql.py` reduced from ~1,530 to ~820 lines
- COMPETE reviewed (Run 42), SIEGE Run 17 regression-free (93% pass rate)

### ~~C. Duplicate connection string building~~ — RESOLVED 14 MAR 2026

`ManagedIdentityAuth` now owns all connection string building. Pool path delegates to `ManagedIdentityAuth._build_connection_string()`. Single auth chain: override → user-assigned MI → system MI → password (dev-only) → FAIL.

### ~~D. External config MI fallback~~ — RESOLVED 13 MAR 2026

Removed silent fallback to app DB managed identity vars. `EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID` and `EXTERNAL_DB_MANAGED_IDENTITY_NAME` now required when external DB is configured with MI.

### E. `_execute_query` wraps psycopg errors as RuntimeError

Loses structured error type (deadlock vs constraint violation vs timeout). Upstream decorators add context. P3 transient retry operates at connection layer, bypasses this.

- **Impact**: Cannot distinguish retryable from non-retryable query errors
- **Revisit when**: Query-level retry logic is added
- **File**: `infrastructure/postgresql.py:_execute_query()`

---

## State Management (Run 2)

### F. `update_job_status_with_validation` TOCTOU

Read-validate-write across two separate connections. Python validates transition rules, but real concurrency protection comes from SQL CAS guards: `WHERE stage = p_current_stage` in `advance_job_stage`, `WHERE status = 'failed'` in `reset_failed_job`.

- **Impact**: Theoretical invalid transition if two workers race (mitigated by SQL)
- **Revisit when**: New transition path added that bypasses SQL CAS guards
- **File**: `infrastructure/jobs_tasks.py:update_job_status_with_validation()`

### G. Non-atomic task create + Service Bus send

DB insert and Service Bus send are two separate operations. A crash between them creates an orphan PENDING task with no message on the bus. Cleanup code marks failed-to-send tasks FAILED immediately, but process crash (OOM, pod eviction) between the two calls has no inline recovery.

- **Impact**: Orphan PENDING task blocks stage completion until manual intervention
- **Mitigation needed**: Periodic janitor that detects PENDING tasks older than N minutes
- **File**: `core/machine.py:_individual_queue_tasks()`

### H. `_advance_stage` double infrastructure failure

When Service Bus send fails during stage advancement, the code rolls back job status QUEUED→PROCESSING. If the rollback also fails (DB down too), job is stuck in QUEUED with no message and no recovery path.

- **Impact**: Job permanently stuck in QUEUED (only during simultaneous DB + Service Bus outage)
- **Mitigation needed**: Periodic sweep for QUEUED jobs with no activity for >5 minutes
- **File**: `core/machine.py:_advance_stage()`

### I. `store_stage_results` JSONB read-modify-write

Python-level `dict.copy() → update key → write back` has a lost-update window if two callers write different stage keys concurrently. Mitigated by sequential stage execution — only one stage is active at a time. The `advance_job_stage` SQL function does atomic `stage_results || jsonb_build_object()` merge as the primary path.

- **Impact**: Stage results silently overwritten (only if stages run concurrently, which they don't)
- **Revisit when**: Concurrent stage execution is implemented
- **File**: `infrastructure/jobs_tasks.py:update_job_stage_with_validation()`

---

## PostGIS DDL & Vector (Run 3)

### J. No concurrency protection for table name collisions

Two concurrent ETL jobs targeting the same `table_name` with `overwrite=true` can race. Job ID deduplication (SHA256) prevents identical jobs, but different jobs with the same target table could collide silently.

- **Impact**: Data corruption — one job's data silently replaces the other's
- **Revisit when**: Multi-user concurrent vector uploads become common
- **File**: `services/vector/postgis_handler.py`

### K. Ensure mode cannot evolve enum values

`action=ensure` skips all enum statements when the type exists in `pg_type`. Adding a new value to a Python enum requires `action=rebuild`. No `ALTER TYPE ... ADD VALUE` path.

- **Impact**: New enum values fail until destructive rebuild
- **Revisit when**: Enum changes need to be non-destructive (production migrations)
- **File**: `triggers/admin/db_maintenance.py`

### L. Full rebuild non-atomic between DROP and CREATE schemas

Steps 1-2 (DROP app, DROP pgstac) are committed independently from Step 3 (CREATE). If Step 3 fails, both schemas are gone. Re-run rebuild to recover.

- **Impact**: Database completely broken on rebuild failure (dev env acceptable)
- **File**: `triggers/admin/db_maintenance.py`

### M. PL/pgSQL function bodies use str.format(schema=) (LOW)

Schema name comes from config (never user input). Deviates from `sql.Identifier()` pattern used everywhere else.

- **Revisit when**: Multi-tenant schema routing from user input
- **File**: `core/schema/sql_generator.py`

---

## External DB & PgSTAC (Run 4)

### N. `update_collection_metadata` TOCTOU

Read-modify-write across separate connections. Two concurrent approvals into the same collection could race on extent updates. Mitigated by sequential approval flow and extent recomputation on every approval.

- **Impact**: Extent temporarily stale (cosmetic — affects UI zoom, not data correctness)
- **Revisit when**: Concurrent bulk approvals become common
- **File**: `infrastructure/pgstac_repository.py:update_collection_metadata()`

### O. `rebuild_collection_from_db` non-atomic delete-then-reinsert

Items deleted one-by-one, then collection deleted, then reinserted. Collection invisible to consumers during the window. Rebuild is a dev/admin operation, not runtime.

- **Impact**: Collection temporarily invisible during rebuild
- **Revisit when**: Zero-downtime rebuild required for production
- **File**: `services/stac_materialization.py:rebuild_collection_from_db()`

### P. Non-atomic `materialize_release`

Collection create → item insert → extent update are 3 separate connections. ADV-17 cleanup handles collection-created-but-item-failed case. Extent failure is non-fatal — next approval recomputes.

- **Impact**: Extent temporarily stale on failed extent recomputation
- **File**: `services/stac_materialization.py:materialize_release()`

### Q. Search hash Python vs PostgreSQL

Python computes SHA256 of search query for dedup lookup, but PostgreSQL GENERATED column uses `search_tohash(search, metadata)`. Lookup may miss existing rows. Mitigated: code returns `result['hash']` (PostgreSQL-generated) on all paths, so TiTiler always gets the correct hash.

- **Impact**: Extra INSERT on duplicate registration (self-correcting)
- **Revisit when**: Dedup accuracy becomes critical
- **File**: `services/pgstac_search_registration.py:register_search()`

### R. N+1 connections in `_materialize_tiled_items`

Each item fetched and upserted individually — 2N connections for N items. Performance concern, not correctness.

- **Impact**: Slow materialization for large tiled collections
- **Revisit when**: Tiled collections exceed ~500 items
- **File**: `services/stac_materialization.py:_materialize_tiled_items()`

### S. Error-as-default-value in PgStacRepository query methods

`get_collection()`, `get_item()`, `list_collections()`, `get_collection_item_count()` return None/[]/0 on DB errors. The most dangerous instance (`collection_exists()`) was fixed. Remaining methods have lower blast radius.

- **Impact**: Misleading return values on transient DB errors
- **Revisit when**: Any of these methods gains correctness-critical callers
- **File**: `infrastructure/pgstac_repository.py` (multiple methods)

---

## Cross-Cutting Themes (Updated)

### 1. TOCTOU mitigated by SQL CAS (Risks F, N)

Python validates, SQL enforces. Safe as long as every write path has a `WHERE` guard matching expected prior state. Risk N (collection metadata) has no SQL guard but is self-correcting via extent recomputation.

### 2. Distributed systems fundamentals (Risks G, H)

DB and Service Bus aren't transactional together. No inline fix exists. Both risks are addressed by a single **janitor process** that sweeps for stale PENDING and QUEUED jobs/tasks.

### 3. Sequential execution assumptions (Risks A, I)

Safe today because stages are sequential and task counts are small (1-20). Breaks if parallelism increases significantly or stages run concurrently.

### 4. Error-as-default-value antipattern (Risk S)

PgStacRepository methods return "empty" values on DB errors, preventing callers from distinguishing "not found" from "DB down". The critical instance (`collection_exists`) was fixed. Remaining instances accepted because callers use them for informational/display purposes.

### 5. Non-atomic multi-step operations (Risks O, P)

pgSTAC operations span multiple connections. Acceptable because pgSTAC is a materialized view that can be fully rebuilt from internal DB.

---

## Resolved Issues (for reference)

| Date | Issue | Resolution |
|------|-------|------------|
| 13 MAR 2026 | HALF_OPEN unlimited concurrent probes | `_half_open_permit_taken` flag in circuit breaker |
| 13 MAR 2026 | Hardcoded `app.tasks` schema in debug queries | `sql.SQL`/`sql.Identifier(self.schema_name)`, gated behind DEBUG |
| 13 MAR 2026 | `build_where_clause` operator injection | Whitelist: `AND`/`OR` only |
| 13 MAR 2026 | `list_jobs` unbounded result set | `LIMIT %s` with default 1000 |
| 13 MAR 2026 | Factory triple schema check (3 DB connections) | `_verified_schemas` class-level cache |
| 13 MAR 2026 | External config MI fallback to app identity | Require explicit `EXTERNAL_DB_MANAGED_IDENTITY_*` vars |
| 13 MAR 2026 | Retry failure bypasses stage completion | `complete_task_with_sql` replaces `update_task_status_direct` |
| 13 MAR 2026 | `store_stage_results` swallows exceptions | Removed try/except, errors propagate |
| 13 MAR 2026 | `fail_all_job_tasks` swallows exceptions | Removed try/except, errors propagate |
| 13 MAR 2026 | `reset_failed_job` doesn't delete child tasks | DELETE FROM tasks before job reset |
| 13 MAR 2026 | `batch_create_tasks` missing ON CONFLICT | Added ON CONFLICT (task_id) DO NOTHING |
| 13 MAR 2026 | `get_job_record` swallows DB errors | Removed try/except, errors propagate |
| 13 MAR 2026 | Misleading error context in queue_tasks | `task_created` flag for accurate error source |
| 13 MAR 2026 | Unpublish orphans split view catalog entries | `cleanup_split_view_metadata()` in unpublish path |
| 13 MAR 2026 | `geo_table_builder` column defs as f-strings | Replaced with `sql.Identifier()` + `sql.SQL()` composition |
| 13 MAR 2026 | `geom_type` via `sql.SQL()` without allowlist | `VALID_GEOM_TYPES` frozenset in 3 files |
| 13 MAR 2026 | `is_configured` OR vs AND logic mismatch | Changed to `bool(self.db_host and self.db_name)` |
| 13 MAR 2026 | App DB password reused for external connections | Require `EXTERNAL_DB_PASSWORD` env var |
| 13 MAR 2026 | `collection_exists()` returns False on DB error | Removed try/except, errors propagate |
| 13 MAR 2026 | Admin external DB endpoints lack explicit auth | Added `AuthLevel.FUNCTION` + host allowlist |
| 13 MAR 2026 | Rebuild limits silently truncate results | Increased to 100000 with warning logs |
| 13 MAR 2026 | `get_collection_item_ids` unbounded result set | Added LIMIT parameter (default 50000) |
| 13 MAR 2026 | `SET search_path` pollutes connection state | Changed to `SET LOCAL search_path` |
| 13 MAR 2026 | `pgstac_bootstrap.py` AttributeError in handler | `self.connection_string` → `self._pg_repo.conn_string` |
| 14 MAR 2026 | God-class PostgreSQLRepository (former B) | Decomposed into ManagedIdentityAuth + ConnectionManager + db_utils via internal composition |
| 14 MAR 2026 | Duplicate connection string building (former C) | Accepted as AR-4 — intentional dual paths for different connection modes |
| 14 MAR 2026 | `is_auth_error()` false-positive pool destruction | Tightened markers — removed bare "token"/"expired", added specific patterns |
| 14 MAR 2026 | Token logged in plaintext (pgstac_bootstrap) | Added `redact_connection_string()` utility, applied at log site |
| 14 MAR 2026 | `_ensure_schema_exists` swallows CircuitBreakerOpenError | Re-raises CircuitBreakerOpenError and ConfigurationError |
| 14 MAR 2026 | `EXTERNAL_DB_PASSWORD` via raw os.environ | Routed through `ExternalEnvironmentConfig.db_password` |
| 14 MAR 2026 | `DOCKER_DB_POOL_MIN/MAX` via raw os.environ | Routed through `DatabaseConfig.pool_min_size/pool_max_size` |
| 14 MAR 2026 | `_orphaned_pools` not thread-safe | Drain and shutdown orphan ops moved under `_pool_lock` |

---

## PostgreSQL Decomposition — Accepted Risks (14 MAR 2026)

### AR-V10-1: Contextmanager yield-twice pattern (MEDIUM)

`db_connections.py:_get_pooled_connection()` and `_get_single_use_connection()` — `@contextmanager` with `yield` inside a `for` retry loop. If caller exception string-matches retry criteria, generator could attempt second yield.

- **Why accepted**: Pre-existing from original code, not introduced by decomposition. `return` after `yield` exits normally. Edge case requires caller psycopg.Error matching dead-pool markers.
- **Revisit when**: `RuntimeError: generator didn't stop after throw()` observed in logs, or move to async generators.

### AR-V10-2: `_verified_schemas` not synchronized (MEDIUM)

`postgresql.py:150` — mutable `set()` class attribute shared across all subclasses without locking.

- **Why accepted**: CPython GIL makes `set.add(str)` atomic. Append-only, 3-5 entries max. Shared behavior is intentional.
- **Revisit when**: No-GIL Python (PEP 703), or concurrent init failures observed.

### AR-V10-3: `refresh_pool_credentials` on ManagedIdentityAuth (MEDIUM)

`db_auth.py:98-106` — pool lifecycle call on the auth class. Should be on `ConnectionManager`.

- **Why accepted**: One call site. Not worth a coordinator.
- **Revisit when**: Second call site appears, or auth/pool management grows.

### AR-V10-4: Dual token acquisition codepaths (MEDIUM)

`db_auth.py:243` uses `ManagedIdentityCredential` directly. `connection_pool.py:206` uses `infrastructure.auth.get_postgres_token()`.

- **Why accepted**: Different modes, different lifecycles. Pre-existing, not introduced by decomposition.
- **Revisit when**: Azure AD rate-limiting, or `connection_pool.py` refactor.

### AR-V10-5: Token potentially in psycopg_pool internal logs (LOW)

`connection_pool.py:226/283` — token in `conninfo` string passed to pool constructor.

- **Why accepted**: Cannot redact before passing to pool. Azure AD tokens are short-lived (~1 hour).
- **Revisit when**: Token exposure confirmed in log audit.

*Deferred fix items (DF-V10-1 through DF-V10-4) moved to `V10_DEFERRED_FIXES.md`.*

---

## DAG Data Layer (COMPETE Run 46 — 16 MAR 2026)

### AR-DAG-1: `when` clause in echo_test.yaml can deadlock

`when: "params.uppercase"` references `params.*` which is a job_params key, not a predecessor output path. `resolve_dotted_path` looks up `params` as a node name in `predecessor_outputs` — will raise `ParameterResolutionError` → task stays PENDING forever. Test fixture only.

- **Impact**: echo_test.yaml unusable for when-clause testing as-is
- **Revisit when**: Writing user docs or if echo_test.yaml is used as a template for real workflows

### AR-DAG-2: Deterministic run_id prevents re-running failed workflows

Same workflow_name + parameters always produces the same run_id. A FAILED run blocks resubmission with identical params. By design — prevents duplicate submissions (higher priority use case).

- **Impact**: Operators must vary a parameter or use a future resubmit endpoint to retry
- **Revisit when**: Implementing resubmit user story (D-1 deferred decision from D.3 GREENFIELD)

### ~~AR-DAG-3: `set_task_parameters` + `promote_task` non-atomic~~ — RESOLVED 16 MAR 2026

Merged into single `set_params_and_promote()` with CAS guard. Run 47 fix M5.

*AR-DAG-4 (no heartbeat) and AR-DAG-14 (no retry) moved to `V10_DEFERRED_FIXES.md` — these are bugs, not design decisions.*

### AR-DAG-5: Fan-out child IDs use `uuid4()` (not deterministic)

Fan-out child `task_instance_id` values use `uuid4()` rather than a deterministic derivation. Template-level CAS guard (`WHERE status = 'ready'`) prevents double-expansion. `UniqueViolation` on re-expansion is caught and treated as idempotent.

- **Impact**: None — double-expansion prevented at template level, not child ID level
- **Revisit when**: Never — acceptable

### AR-DAG-6: `fail_task` returns void (no confirmation of row update)

`fail_task` does `UPDATE ... AND status IN ('running', 'ready', 'pending')` but returns `None`, not a `bool` indicating whether the row was actually updated. All callers log and continue regardless.

- **Impact**: Silent no-op if task was already in a terminal state
- **Revisit when**: If `fail_task` is used in critical paths requiring confirmation of state change

---

## DAG Control Layer (COMPETE Run 47 — 16 MAR 2026)

### AR-DAG-7: `expand_fan_out` no CAS guard on template status

`expand_fan_out` does not use a `WHERE status = 'ready'` CAS guard on the template UPDATE. Instead, `UniqueViolation` on the child INSERT provides idempotency. Lease-based exclusion prevents concurrent orchestrator calls.

- **Impact**: None under lease. Double-call overwrites template with identical EXPANDED status.
- **Revisit when**: Multi-instance orchestrator without lease

### AR-DAG-8: `aggregate_fan_in` no CAS guard

Deterministic aggregation + lease exclusion. Double-call overwrites with identical data.

- **Impact**: None — aggregation is a pure function of child results, always produces same output.
- **Revisit when**: Multi-instance orchestrator without lease

### AR-DAG-9: `_build_adjacency_from_tasks` silently skips unknown IDs

Used only for skip-propagation in `dag_fan_engine.py` where partial data is expected after fan-out expansion (new children may not be in the current snapshot). Strict guard would crash the orchestrator.

- **Impact**: Skip propagation may miss dynamically-created fan-out children (they're created READY anyway — skip is irrelevant for them)
- **Revisit when**: Used for correctness-critical decisions beyond skip propagation

### AR-DAG-10: `time.sleep` not interruptible by `shutdown_event`

`time.sleep(cycle_interval)` blocks for up to 5 seconds even after `shutdown_event` is set. The event is checked at the top of the next cycle.

- **Impact**: Max 5s shutdown delay for background process. Acceptable.
- **Revisit when**: `cycle_interval` increases significantly (>30s)

### AR-DAG-11: Stale tasks snapshot across all 4 engines per cycle

All four engines receive the same `tasks` list and `predecessor_outputs` dict loaded once at cycle start. Writes by engine 1 are invisible to engines 2-4 within the same cycle. By design — fixed dispatch order trades one-tick latency for snapshot consistency.

- **Impact**: One-cycle delay for cascading effects (e.g., conditional completes → downstream promoted next cycle, not same cycle)
- **Revisit when**: Never — this is a deliberate architectural decision from ARB P

### AR-DAG-12: `WorkflowRunRepository` instantiated per-call in worker dual-poll

`_claim_next_workflow_task` and `_process_workflow_task` create a new `WorkflowRunRepository()` on each call rather than caching an instance. Lightweight init — no connection until `_get_connection()`.

- **Impact**: Minor object allocation overhead per poll cycle
- **Revisit when**: Repository init gains expensive setup (e.g., schema verification on construct)

*AR-DAG-13 (no heartbeat) and AR-DAG-14 (no retry) moved to `V10_DEFERRED_FIXES.md` — these are bugs that must be fixed before production, not design decisions.*
