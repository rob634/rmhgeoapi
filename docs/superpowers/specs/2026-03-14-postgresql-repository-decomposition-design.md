# PostgreSQL Repository Decomposition — Design Spec

**Date**: 14 MAR 2026
**Status**: Approved design, pending implementation
**Branch**: `dev` (create from `master`)
**Review Pipeline**: COMPETE (post-implementation)

---

## Problem

`PostgreSQLRepository` in `infrastructure/postgresql.py` is a 1,530-line god class mixing six concerns: Azure Managed Identity auth, connection pooling, circuit breaker integration, token refresh, schema management, and SQL query execution. 24 domain repositories inherit from it.

This platform is being prepared as a "system in a box" product for other teams. A team receiving this repo cannot understand, configure, or debug the database layer without reading the entire monolith.

## Design Principles

These are constitutional constraints — not negotiable in this refactor:

1. **Managed Identity only** — no pluggable auth strategy pattern. Password auth is a dev-only escape hatch.
2. **Docker-first** — pooled connections are the primary path. Functions single-use is transitional.
3. **Environment variable configuration** — teams configure via container env, not code changes.
4. **Zero breaking changes** — all 24 subclasses, the RepositoryFactory, and 41+ consumers must continue working unchanged.

## Approach: Internal Composition

Extract auth and connection management into internal collaborator classes. `PostgreSQLRepository` instantiates them in `__init__` and delegates. The public API surface is completely unchanged.

---

## Component 1: `ManagedIdentityAuth`

**File**: `infrastructure/db_auth.py` (~200 lines)
**Purpose**: Azure AD token acquisition and connection string management for PostgreSQL.

### Methods

| New Method | Extracted From | Visibility |
|---|---|---|
| `get_connection_string()` | `PostgreSQLRepository._get_connection_string()` (line 368) | Public — main job of this class |
| `_build_connection_string()` | `_build_managed_identity_connection_string()` (line 510) | Internal |
| `_build_dev_connection_string()` | `_build_password_connection_string()` (line 486) | Internal, dev-only |
| `is_auth_error(error)` | `_is_managed_identity_auth_error()` (line 636) | Public static |
| `is_active()` | `_is_managed_identity_effective()` (line 693) | Public |
| `refresh()` | `_refresh_managed_identity_conn_string()` (line 712) | Public — returns fresh connection string |
| `refresh_pool_credentials()` | `_refresh_pooled_managed_identity_credentials()` (line 720) | Public — pool-specific token refresh |

### Constructor

```python
ManagedIdentityAuth.__init__(self, config: AppConfig, target_database: str = "app",
                              connection_string_override: str = None)
```

Stores `config`, `target_database`, and resolves `ExternalEnvironmentConfig` (if `target_database="external"`) so all methods can access the full config state.

Reads from env vars via `AppConfig`:
- `POSTGIS_HOST`
- `POSTGIS_DATABASE`
- `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID`
- `DB_ADMIN_MANAGED_IDENTITY_NAME`
- `POSTGIS_PASSWORD` (dev-only fallback)

Resolves auth mode once at init (managed identity vs dev password). Subsequent `get_connection_string()` calls use the resolved mode.

Accepts optional `connection_string_override` for backward compatibility — if provided, `get_connection_string()` returns it directly without building one.

### Password Auth: Two Paths (dev-only)

The current code has two distinct password paths that `get_connection_string()` must preserve:

1. **App database**: Reads pre-built connection string from `config.postgis_connection_string` (a property on `AppConfig`). No explicit host/port building.
2. **External database**: Calls `_build_dev_connection_string(db_config: ExternalEnvironmentConfig)` which constructs from explicit host/port/database fields.

Both are dev-only fallbacks when managed identity is unavailable. The full priority chain within `get_connection_string()`:
1. `connection_string_override` (if passed) → return directly
2. Managed identity (user-assigned → system-assigned) → build MI connection string
3. Password fallback → app path reads `config.postgis_connection_string`, external path builds from `ExternalEnvironmentConfig`

### Connection String Caching

`get_connection_string()` caches the result in `self._cached_conn_string`. `refresh()` rebuilds and updates the cache. This supports the retry-refresh-retry pattern in `ConnectionManager._get_single_use_connection()`.

### External Database Support

`target_database` parameter ("app" vs "external") determines which env vars to read. External uses `EXTERNAL_DB_*` variables via `ExternalEnvironmentConfig`. Same behavior as today. `is_active()` uses the stored `target_database` and config to determine whether MI is effective for the current database target.

---

## Component 2: `ConnectionManager`

**File**: `infrastructure/db_connections.py` (~250 lines)
**Purpose**: PostgreSQL connection lifecycle — pooled and single-use modes, circuit breaker, retry logic.

### Methods

| New Method | Extracted From | Visibility |
|---|---|---|
| `get_connection()` | `PostgreSQLRepository._get_connection()` (line 731) | Public context manager — main entry point |
| `_get_pooled_connection()` | `_get_pooled_connection()` (line 813) | Internal |
| `_get_single_use_connection()` | `_get_single_use_connection()` (line 876) | Internal |
| `get_cursor(conn)` | `_get_cursor()` (line 960) | Public — needed by `_execute_query` |
| `is_transient_error(error)` | `_is_transient_connection_error()` (line 667) | Public static |

### Constructor

```python
ConnectionManager.__init__(self, auth: ManagedIdentityAuth)
```

Takes a `ManagedIdentityAuth` instance. Reads pool configuration from env vars:
- `DB_POOL_MIN_SIZE` (default 2)
- `DB_POOL_MAX_SIZE` (default 10)
- Pool max lifetime: 55 minutes (Azure AD token safety)

### Integration Points

- **CircuitBreaker** (`infrastructure/circuit_breaker.py`): Checked before every connection attempt. Existing file, no changes.
- **ConnectionPoolManager** (`infrastructure/connection_pool.py`): Used for Docker pooled mode. Existing file, no changes.
- **Type adapters**: Calls `_register_type_adapters(conn)` on every new connection. Function stays in `postgresql.py` as module-level utility, imported by `ConnectionManager`.

### Retry-Refresh Flow (Single-Use Mode)

The current `_get_single_use_connection()` has a retry loop that mutates `self.conn_string` on auth failure. In the decomposed design:

1. `ConnectionManager._get_single_use_connection()` calls `self._auth.get_connection_string()` (returns cached string)
2. Attempts connection
3. On auth failure: calls `self._auth.refresh()` which rebuilds and updates the cached string
4. Next retry iteration calls `self._auth.get_connection_string()` again, gets the refreshed string

No mutable `conn_string` state on `ConnectionManager` — auth state lives entirely in `ManagedIdentityAuth`.

### Behavior Preserved

- Circuit breaker: CLOSED → check passes → connect. OPEN → raise immediately. HALF_OPEN → one probe.
- Pooled (Docker): Dead-pool detection, MI auth retry on token expiry.
- Single-use (Functions): Transient error retry (network, timeout).
- Type adapters registered on every connection (dict/list→JSONB, Enum→.value).

---

## Component 3: Slimmed `PostgreSQLRepository`

**File**: `infrastructure/postgresql.py` (same file, reduced class)
**Before**: ~1,530 lines
**After**: ~500 lines

### Constructor

```python
def __init__(self, connection_string=None, schema_name=None,
             config=None, target_database="app"):
    super().__init__()
    # Resolve schema_name and config (same logic as today)
    self._auth = ManagedIdentityAuth(
        config=config or get_config(),
        target_database=target_database,
        connection_string_override=connection_string
    )
    self._connections = ConnectionManager(self._auth)
    self._ensure_schema_exists()
```

**Signature unchanged.** All 24 subclasses continue calling `super().__init__()` with the same arguments.

### Delegation Methods

```python
@property
def conn_string(self) -> str:
    """Exposes connection string for external consumers.
    Read by: pgstac_repository.py, postgis_handler.py, health_checks/external.py,
    health_checks/database.py, pgstac_bootstrap.py
    """
    return self._auth.get_connection_string()

@contextmanager
def _get_connection(self):
    """Delegates to ConnectionManager.
    Used by: all subclasses, deployer.py, schema_analyzer.py, validators.py,
    config/database_config.py, and 30+ trigger/admin files.
    """
    with self._connections.get_connection() as conn:
        yield conn

def _get_cursor(self, conn=None):
    """Delegates to ConnectionManager."""
    return self._connections.get_cursor(conn)
```

**Note on CRUD builders**: `execute_select`, `execute_exists`, `execute_insert`, `execute_update`, and `execute_count` all call `self._get_connection()` directly (not through `_execute_query()`). The delegation method is the critical seam — both paths to connections must work.

### What Stays (not extracted)

| Method | Reason |
|---|---|
| `_ensure_schema_exists()` | Repository concern — "does my schema exist?" |
| `_table_exists()` | Repository concern — used by domain repos |
| `_execute_query()` | Core SQL execution engine — uses connections, handles commits |
| `execute_select()` | CRUD builder — the class's purpose |
| `execute_insert()` | CRUD builder |
| `execute_update()` | CRUD builder |
| `execute_exists()` | CRUD builder |
| `execute_count()` | CRUD builder |
| `build_where_clause()` | SQL composition helper |
| `build_where_in_clause()` | SQL composition helper |
| `_verified_schemas` (class-level set) | Schema existence cache shared across all instances — stays with `_ensure_schema_exists()` |

### Module-Level Utilities — Moved to `infrastructure/db_utils.py`

To avoid circular imports (`postgresql.py` imports `ConnectionManager` from `db_connections.py`, which would need to import `_register_type_adapters` back from `postgresql.py`), these utilities move to a shared module:

**File**: `infrastructure/db_utils.py` (~80 lines, new)

| Function | Current Location | Used By |
|---|---|---|
| `_register_type_adapters(conn)` | `postgresql.py:115` | `ConnectionManager`, `connection_pool.py` |
| `_parse_jsonb_column()` | `postgresql.py:128` | State machine repos in `postgresql.py` |
| `_EnumDumper` | `postgresql.py:108` | `_register_type_adapters` |

Import direction: `db_utils.py` ← `db_connections.py`, `postgresql.py`, `connection_pool.py`. No circular dependency.

### State Machine Subclasses (unchanged)

These stay in `postgresql.py`, completely untouched:

- `PostgreSQLJobRepository` (line ~1711 → renumbered after extraction)
- `PostgreSQLTaskRepository`
- `PostgreSQLStageCompletionRepository`

---

## What Does NOT Change

| Thing | Why |
|---|---|
| `BaseRepository` (base.py) | Not part of this refactor |
| `interface_repository.py` | Contracts unchanged |
| `jobs_tasks.py` (Layer 4 business repos) | Inherits from unchanged subclasses |
| All 21 domain repository subclasses | `super().__init__()` signature preserved |
| `RepositoryFactory` (factory.py) | Creates same classes with same args |
| 41+ consumer files | Use repos through unchanged public API |
| `connection_pool.py` | Existing file, called by `ConnectionManager` |
| `circuit_breaker.py` | Existing file, called by `ConnectionManager` |
| `core/schema/deployer.py` | `_get_connection()` preserved as delegation |
| `infrastructure/schema_analyzer.py` | Calls `repo._get_connection()` — delegation handles it |
| `infrastructure/validators.py` | Calls `repo._get_connection()` (3 sites) — delegation handles it |
| `config/database_config.py` | Calls `repo._get_connection()` — delegation handles it |
| 30+ trigger/admin files | Call `repo._get_connection()` via subclass instances — delegation handles all |

---

## File Impact Summary

| File | Change Type |
|---|---|
| `infrastructure/db_auth.py` | **NEW** (~200 lines) |
| `infrastructure/db_connections.py` | **NEW** (~250 lines) |
| `infrastructure/db_utils.py` | **NEW** (~80 lines) — type adapters, JSONB parsing |
| `infrastructure/postgresql.py` | **MODIFIED** — extract methods, add delegation, class shrinks from ~1,530 to ~500 lines |
| `infrastructure/connection_pool.py` | **MINOR** — update import of `_register_type_adapters` from `db_utils` instead of `postgresql` |
| `infrastructure/__init__.py` | **MINOR** — add lazy imports for new modules if needed |

Total: 3 new files, 3 modified files. Zero consumer changes.

### Import Order

`postgresql.py` imports `ManagedIdentityAuth` and `ConnectionManager` at **module level** (top of file). This is safe because:
- `db_auth.py` imports from `config` only (no infrastructure imports)
- `db_connections.py` imports from `db_auth.py`, `db_utils.py`, `circuit_breaker.py`, `connection_pool.py` (no postgresql.py import)
- `db_utils.py` imports from `psycopg` only (leaf node, no infrastructure imports)
- No circular dependency: `postgresql.py` → `db_connections.py` → `db_auth.py` → `config`

### Rollback Strategy

If post-merge testing reveals issues: revert the 3 new files and restore `postgresql.py` from the pre-refactor commit. Single `git revert` of the merge commit. The refactor is self-contained — no consumer files are modified.

---

## Verification Strategy

### Pre-merge Checks

1. **Import smoke test**: `python -c "from infrastructure.postgresql import PostgreSQLRepository; print('OK')"`
2. **Subclass instantiation**: Verify all 24 domain repos can be imported and instantiated
3. **Health check**: Deploy to dev, hit `/api/health`
4. **Job round-trip**: Submit `hello_world` job, verify completion
5. **Schema ensure**: `POST /api/dbadmin/maintenance?action=ensure&confirm=yes`

### Post-merge Review

Run **COMPETE** agent pipeline on the changed files:
- Scope: `infrastructure/db_auth.py`, `infrastructure/db_connections.py`, `infrastructure/postgresql.py`
- Alpha (architecture): Clean boundaries? Clear responsibilities?
- Beta (correctness): Same runtime behavior? No leaked state?
- Gamma (contradictions): Any assumptions violated?

Optional: Chain **REFLEXION** on any issues COMPETE surfaces.

---

## Open Items (deferred, not this refactor)

- [ ] `deployer.py` should use `ConnectionManager` directly instead of reaching through `_get_connection()`
- [ ] `SnapshotRepository` in `services/snapshot_service.py` should move to `infrastructure/`
- [ ] Remove redundant `json.dumps()` calls (~50+ sites) now that type adapters handle JSONB
- [ ] Evaluate removing Functions single-use connection path when Docker orchestrator ships
