# V10 Accepted Risks & Architecture Decisions

**Version**: v0.10.1.1
**Last Updated**: 13 MAR 2026
**Source**: COMPETE adversarial code review pipeline — Runs 1-4

---

## Connection Infrastructure (Run 1)

### A. `update_task` GET-before-UPDATE for DEBUG logging

Extra DB read per task update for diagnostic logging. Bounded by task count per stage (1-20).

- **Impact**: ~2ms overhead per task update
- **Revisit when**: 100+ task stages become common
- **File**: `infrastructure/postgresql.py`, `update_task()`

### B. God-class `PostgreSQLRepository` (~2600 lines)

Single class owns connection management, SQL execution, and all domain queries. Cohesive — splitting creates circular deps on shared methods (`_get_connection`, `_execute_query`, `build_where_clause`).

- **Impact**: Large file, harder to navigate
- **Revisit when**: File exceeds ~3500 lines
- **File**: `infrastructure/postgresql.py`

### C. Duplicate connection string building

Pool path (Docker/MI-only) and full path (local-dev/password/external) build connection strings independently. Pool path is intentionally simpler — Docker always uses MI, never needs fallbacks.

- **Impact**: Auth logic changes require updating two paths
- **Revisit when**: Third auth method added (certificate, workload identity federation)
- **Files**: `infrastructure/connection_pool.py`, `infrastructure/postgresql.py:_get_connection_string()`

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

## PostgreSQL Decomposition — Deferred Items (14 MAR 2026)

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

### DF-V10-1: Remove backward-compatible aliases in postgresql.py

`postgresql.py:102-103` — `_register_type_adapters` and `_parse_jsonb_column` aliases. Update callers to import from `infrastructure.db_utils` directly.

- **Target**: V0.11

### DF-V10-2: `deployer.py` should use ConnectionManager directly

`core/schema/deployer.py` calls `self.repository._get_connection()`. Should use `ConnectionManager` or a public method.

- **Target**: Next deployer refactor.

### DF-V10-3: `SnapshotRepository` in wrong location

`services/snapshot_service.py` contains `SnapshotRepository(PostgreSQLRepository)`. Should be in `infrastructure/`.

- **Target**: Next services cleanup.

### DF-V10-4: Remove redundant `json.dumps()` calls

~50+ sites still call `json.dumps()` before PostgreSQL despite psycopg3 type adapters handling JSONB automatically.

- **Target**: V0.11 cleanup pass.
