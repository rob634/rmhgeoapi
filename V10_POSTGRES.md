# V10 PostgreSQL Infrastructure Refactor

**Created**: 13 MAR 2026
**Updated**: 14 MAR 2026
**Status**: Implementation complete — pending COMPETE review
**Target**: Decompose `PostgreSQLRepository` god class into composable components
**Justification**: Prepare infrastructure layer for "system in a box" product distribution
**Design Spec**: `docs/superpowers/specs/2026-03-14-postgresql-repository-decomposition-design.md`

---

## Why This Refactor

This codebase is being prepared as a distributable geospatial ETL product. When another team receives this repo, `infrastructure/postgresql.py` is the first thing that breaks their comprehension:

- **1,530 lines** in a single class mixing 6 unrelated concerns
- **24 domain repositories** inherit from it — it's the foundation of everything
- A new team needs to configure auth, pooling, and connection behavior for *their* Azure environment without understanding the entire monolith

| Audience | Current State | After Refactor |
|----------|--------------|----------------|
| New team adding a domain repo | Must read 1,530 lines of base class | Read ~200-line coordinator + extend |
| Team debugging auth issues | Auth mixed with pooling, circuit breaker, CRUD | Isolated `AuthProvider` with clear error paths |
| Team on different infra (AKS, ACA) | Connection strategy buried in conditionals | Swap `ConnectionManager` configuration |
| Team tuning resilience | Circuit breaker thresholds scattered | Configure `CircuitBreaker` independently |

---

## Current Architecture

### The God Class: `PostgreSQLRepository`

**File**: `infrastructure/postgresql.py` (2,632 lines total)
**Class span**: Lines 183–1711 (~1,530 lines)
**Inherits from**: `BaseRepository` (abstract, in `base.py`)

#### Six Concerns in One Class

| Concern | Methods | Lines (approx) |
|---------|---------|----------------|
| **Azure Managed Identity auth** | `_get_connection_string`, `_build_password_connection_string`, `_build_managed_identity_connection_string`, `_is_managed_identity_effective` | ~350 |
| **Connection lifecycle** | `_get_connection`, `_get_pooled_connection`, `_get_single_use_connection`, `_get_cursor` | ~230 |
| **Error classification** | `_is_managed_identity_auth_error`, `_is_transient_connection_error` | ~60 |
| **Token refresh** | `_refresh_managed_identity_conn_string`, `_refresh_pooled_managed_identity_credentials` | ~20 |
| **Schema management** | `_ensure_schema_exists`, `_table_exists` | ~200 |
| **Query execution + CRUD** | `_execute_query`, `execute_select`, `execute_insert`, `execute_update`, `execute_exists`, `execute_count`, `build_where_clause`, `build_where_in_clause` | ~520 |

#### Module-Level Helpers (before the class)

| Line | Function | Purpose |
|------|----------|---------|
| 108 | `_EnumDumper` | psycopg3 adapter: Enum → `.value` |
| 115 | `_register_type_adapters()` | Register dict/list→JSONB and Enum→.value on each connection |
| 128 | `_parse_jsonb_column()` | Safe JSONB parsing with explicit error on corruption |

### Full Inheritance Tree

```
BaseRepository (base.py)
    │   Pure abstract: validation, error context, logging
    │   _error_context(), _validate_status_transition(),
    │   _validate_stage_progression(), _validate_parent_child_relationship()
    │
    └── PostgreSQLRepository (postgresql.py:183) ← THE GOD CLASS
        │
        │   === 3 subclasses in same file (state machine persistence) ===
        │
        ├── PostgreSQLJobRepository (postgresql.py:1711)
        │   │   Implements IJobRepository
        │   │   5 methods: create_job, get_job, update_job, list_jobs, delete_job
        │   │
        │   └── JobRepository (jobs_tasks.py:60)
        │           Business logic: create_job_from_params, idempotency, contract enforcement
        │
        ├── PostgreSQLTaskRepository (postgresql.py:2018)
        │   │   Implements ITaskRepository
        │   │   4 methods: create_task, get_task, update_task, list_tasks_for_job
        │   │
        │   └── TaskRepository (jobs_tasks.py:708)
        │           Business logic: status transitions, validation
        │
        ├── PostgreSQLStageCompletionRepository (postgresql.py:2311)
        │   │   Implements IStageCompletionRepository
        │   │   3 atomic SQL functions: complete_task_and_check_stage,
        │   │   advance_job_stage, check_job_completion
        │   │
        │   └── StageCompletionRepository (jobs_tasks.py:1541)
        │           Business logic: logging, error wrapping
        │
        │   === 21 domain subclasses in separate files ===
        │
        ├── AssetRepository                ← infrastructure/asset_repository.py
        ├── ArtifactRepository             ← infrastructure/artifact_repository.py
        ├── ReleaseRepository              ← infrastructure/release_repository.py
        ├── ReleaseTableRepository         ← infrastructure/release_table_repository.py
        ├── ReleaseAuditRepository         ← infrastructure/release_audit_repository.py
        ├── RouteRepository                ← infrastructure/route_repository.py
        ├── ApiRequestRepository           ← infrastructure/platform.py
        ├── PlatformRegistryRepository     ← infrastructure/platform_registry_repository.py
        ├── PromotedDatasetRepository      ← infrastructure/promoted_repository.py
        ├── ExternalServiceRepository      ← infrastructure/external_service_repository.py
        ├── RasterMetadataRepository       ← infrastructure/raster_metadata_repository.py
        ├── RasterRenderRepository         ← infrastructure/raster_render_repository.py
        ├── H3Repository                   ← infrastructure/h3_repository.py
        ├── H3BatchTracker                 ← infrastructure/h3_batch_tracking.py
        ├── JanitorRepository              ← infrastructure/janitor_repository.py
        ├── JobEventRepository             ← infrastructure/job_event_repository.py
        ├── MetricsRepository              ← infrastructure/metrics_repository.py
        ├── MapStateRepository             ← infrastructure/map_state_repository.py
        ├── DatasetRefsRepository          ← infrastructure/dataset_refs_repository.py
        ├── SnapshotRepository             ← services/snapshot_service.py (odd location)
        └── (PgstacRepository uses PostgreSQLRepository internally, not via inheritance)
```

### Interface Contracts

Defined in `infrastructure/interface_repository.py`:

| Interface | Methods | Implemented By |
|-----------|---------|---------------|
| `IJobRepository` | create_job, get_job, update_job, list_jobs | PostgreSQLJobRepository |
| `ITaskRepository` | create_task, get_task, update_task, list_tasks_for_job | PostgreSQLTaskRepository |
| `IStageCompletionRepository` | complete_task_and_check_stage, advance_job_stage, check_job_completion | PostgreSQLStageCompletionRepository |
| `IJobEventRepository` | record_event, record_job_event, record_task_event, get_events_for_job, get_events_timeline | JobEventRepository |

`ParamNames` class enforces canonical parameter names across all implementations.

### Connection Modes

| Mode | When | Strategy |
|------|------|----------|
| **Pooled** | Docker workers (`APP_MODE=worker_docker`) | `psycopg_pool.ConnectionPool` via `ConnectionPoolManager`, 2-10 connections, 55min max lifetime |
| **Single-use** | Azure Functions (default) | New connection per operation, disposed after use |

Routing happens inside `_get_connection()` (line 731) which checks `ConnectionPoolManager.is_pool_mode()`.

### Authentication Priority Chain

1. **User-Assigned Managed Identity** — `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` + `DB_ADMIN_MANAGED_IDENTITY_NAME`
2. **System-Assigned Managed Identity** — detected via `WEBSITE_SITE_NAME` (running in Azure)
3. **Password Authentication** — `POSTGIS_PASSWORD` (local dev)
4. **FAIL** — no silent fallbacks

### Resilience (v0.10.1.1)

- **Circuit Breaker** (`infrastructure/circuit_breaker.py`): 3 failures in 10s → OPEN (block 30s) → HALF_OPEN (probe) → CLOSED
- **Transient retry** in `_get_single_use_connection()`: retries on network/timeout errors
- **Dead-pool detection** in `_get_pooled_connection()`: detects exhausted pools, MI auth retry
- **Pool health check**: validates connections before checkout

---

## Blast Radius Analysis

### Instantiation & Consumption

| Consumer | Count | Pattern |
|----------|-------|---------|
| Direct subclasses | **24** | `class FooRepository(PostgreSQLRepository)` — all call `super().__init__()` |
| RepositoryFactory consumers | **41** | `RepositoryFactory.create_repositories()` returns `{'job_repo', 'task_repo', 'stage_completion_repo'}` |
| Direct instantiation sites | **31** | `FooRepository()` using global config |

### Dangerous Coupling Points

| Location | What It Does | Risk |
|----------|-------------|------|
| `core/schema/deployer.py` | Calls `self.repository._get_connection()` directly | **HIGH** — only external caller of this "private" method |
| `infrastructure/connection_pool.py` | Imports `_register_type_adapters` from postgresql.py | **MEDIUM** — module-level function, not class method |
| `infrastructure/postgis.py` | Imports `PostgreSQLRepository` for standalone table checks | **LOW** — thin wrapper |
| `services/curated/wdpa_handler.py` | Imports `PostgreSQLRepository` directly for ad-hoc queries | **LOW** — one-off usage |

### What's Safe vs Dangerous to Change

| Change | Risk | Reason |
|--------|------|--------|
| Extract auth into internal component | **Safe** | No subclass calls auth methods directly |
| Extract connection pooling internally | **Safe** | Already partially in `connection_pool.py` |
| Extract circuit breaker internally | **Safe** | Already in `circuit_breaker.py` |
| Refactor `_execute_query()` internals | **Safe** | Only accessed via public CRUD methods |
| **Change constructor signature** | **CRITICAL** | 24 subclasses call `super().__init__(connection_string, schema_name, config, target_database)` |
| **Rename/move CRUD methods** | **CRITICAL** | All 24 domain repos call `execute_select`, `execute_insert`, etc. |
| **Change `_get_connection()` return type** | **HIGH** | deployer.py + connection_pool.py break |
| **Change RepositoryFactory dict keys** | **CRITICAL** | 41+ consumer files break |

---

## Three Categories of Database Usage

Understanding what flows through `PostgreSQLRepository`:

### 1. Job Orchestration (schema: `app`)

**Tables**: `app.jobs`, `app.tasks`, `app.job_events`
**Used by**: CoreMachine, StateManager, task handlers
**Pattern**: State machine — create jobs, fan out tasks, atomically detect stage completion ("last task turns out the lights" via advisory locks), advance stages
**Repositories**: JobRepository, TaskRepository, StageCompletionRepository, JobEventRepository

### 2. PostGIS / Domain Data (schema: `geo`)

**Tables**: Dynamic per-dataset (created at runtime by vector/raster pipelines)
**Used by**: Vector handlers, raster handlers, OGC Features API, split-view creator
**Pattern**: GDAL/ogr2ogr writes tables, repositories manage metadata and catalog entries
**Repositories**: AssetRepository, ReleaseRepository, ReleaseTableRepository, RouteRepository, RasterMetadataRepository, H3Repository, plus 10+ more domain repos

### 3. STAC / pgSTAC Catalog (schema: `pgstac`)

**Tables**: `pgstac.items`, `pgstac.collections`
**Used by**: Approval workflow, TiTiler tile serving, STAC API
**Pattern**: Metadata materialized to pgSTAC at approval time (not at ingest). Vector data does NOT go in STAC — raster and Zarr only.
**Repositories**: PgstacRepository (uses PostgreSQLRepository internally, not via inheritance)

---

## Proposed Decomposition

### Target State

```
PostgreSQLRepository (~200 lines, thin coordinator)
    │
    ├── self._auth: AuthProvider
    │       Token acquisition, refresh, error detection
    │       Swappable: ManagedIdentityAuth, PasswordAuth, (future: CustomAuth)
    │
    ├── self._connections: ConnectionManager
    │       Pool vs single-use routing, circuit breaker integration
    │       Configurable: pool size, timeouts, mode
    │
    ├── self._executor: QueryExecutor
    │       _execute_query, type adapters, JSONB parsing
    │       The SQL execution engine
    │
    └── Public CRUD API (unchanged signatures)
            execute_select, execute_insert, execute_update,
            execute_exists, execute_count, build_where_clause, etc.
            These delegate to self._executor
```

### Constraints (non-negotiable)

1. **Constructor signature unchanged**: `__init__(self, connection_string, schema_name, config, target_database)` — 24 subclasses depend on this
2. **CRUD method signatures unchanged**: `execute_select()`, `execute_insert()`, etc. — all 24 domain repos call these
3. **`_get_connection()` context manager preserved**: deployer.py calls it directly (should eventually be fixed, but not in this refactor)
4. **RepositoryFactory dict keys unchanged**: `{'job_repo', 'task_repo', 'stage_completion_repo'}` — 41 consumers
5. **Type adapter registration preserved**: `_register_type_adapters()` must run on every connection

### What Changes

| Component | Current Location | New Location | Lines (approx) |
|-----------|-----------------|-------------|----------------|
| Auth logic | PostgreSQLRepository methods | `infrastructure/auth_provider.py` | ~350 |
| Connection lifecycle | PostgreSQLRepository methods | `infrastructure/connection_manager.py` | ~250 |
| Error classification | PostgreSQLRepository static methods | `infrastructure/connection_manager.py` (or auth_provider) | ~60 |
| Query execution | PostgreSQLRepository._execute_query | `infrastructure/query_executor.py` | ~140 |
| Schema management | PostgreSQLRepository methods | stays in PostgreSQLRepository (or executor) | ~200 |
| CRUD builders | PostgreSQLRepository methods | stays in PostgreSQLRepository (delegates to executor) | ~320 |

### What Doesn't Change

- `BaseRepository` (base.py) — untouched
- `PostgreSQLJobRepository`, `PostgreSQLTaskRepository`, `PostgreSQLStageCompletionRepository` — untouched
- `JobRepository`, `TaskRepository`, `StageCompletionRepository` (jobs_tasks.py) — untouched
- All 21 domain repository subclasses — untouched
- `interface_repository.py` — untouched
- `RepositoryFactory` — untouched (or minimal changes to pass config)
- All 41+ consumer files — untouched

---

## Product Benefits (System in a Box)

| For distributable product... | This refactor enables... |
|-----|------|
| Team deploys on their Azure environment | Configure `AuthProvider` with their managed identity or password — one file, clear interface |
| Team runs on AKS instead of Functions | Configure `ConnectionManager` for their container runtime — pool size, mode, timeouts |
| Team needs to tune resilience | Circuit breaker thresholds in one place, not buried in connection logic |
| Team adds a new domain repository | Extend `PostgreSQLRepository` (~200 lines) — comprehensible base class |
| Team debugs "why can't it connect" | Auth, connections, and queries are isolated — error points to one component |
| Team wants to test DB layer | Mock `AuthProvider` or `ConnectionManager` independently |

---

## Open Questions

- [ ] Should `_get_connection()` be promoted to a public method? deployer.py already treats it as one
- [ ] Should the CRUD builders (`execute_select`, etc.) live on PostgreSQLRepository or on a mixin?
- [ ] Should `_register_type_adapters` move into `ConnectionManager` (since it's per-connection)?
- [ ] Does `SnapshotRepository` in `services/snapshot_service.py` need to move to `infrastructure/`?
- [ ] Should schema management (`_ensure_schema_exists`, `_table_exists`) be its own component or stay in the coordinator?

---

## Implementation Plan

*To be developed after brainstorm review.*

---

## File Index

| File | Role | Lines |
|------|------|-------|
| `infrastructure/postgresql.py` | God class + 3 state machine repos | 2,632 |
| `infrastructure/base.py` | Abstract base repository | ~560 |
| `infrastructure/interface_repository.py` | Interface contracts + ParamNames | ~830 |
| `infrastructure/jobs_tasks.py` | Business logic repos (Layer 4) | ~1,600 |
| `infrastructure/factory.py` | RepositoryFactory | TBD |
| `infrastructure/connection_pool.py` | ConnectionPoolManager (Docker mode) | TBD |
| `infrastructure/circuit_breaker.py` | CircuitBreaker (cascade prevention) | TBD |
| `core/schema/deployer.py` | Schema initialization (calls `_get_connection`) | TBD |
