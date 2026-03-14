# COMPETE Review: PostgreSQL Repository Decomposition

**Date**: 14 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Split**: B — Internal vs External
**Scope**: infrastructure/db_auth.py, db_connections.py, db_utils.py, postgresql.py + priority files
**Agents**: Omega (scope) → Alpha (architecture) + Beta (correctness) → Gamma (contradictions) → Delta (final)
**Status**: Top 5 fixes applied (commit `abe02f4`). Remaining findings tracked below.

---

## EXECUTIVE SUMMARY

The decomposition of the PostgreSQL god class into `ManagedIdentityAuth`, `ConnectionManager`, `ConnectionPoolManager`, and `db_utils` is structurally sound and improves separation of concerns. The delegation layer in `postgresql.py` preserves backward compatibility for 30+ consumer files. However, two critical bugs can cause production incidents: the `is_auth_error()` false-positive markers can trigger unnecessary pool destruction on normal error messages, and `pgstac_bootstrap.py` logs connection strings containing live OAuth tokens in plaintext. The orphan-and-sweep pool lifecycle is well-designed but has a minor thread-safety gap on the orphaned pool list. Overall, this is good refactoring work with a short punch list of targeted fixes.

---

## TOP 5 FIXES

### Fix 1: Tighten `is_auth_error()` markers to prevent false-positive pool destruction

- **WHAT**: Remove the bare `"token"` and `"expired"` substring markers from the auth error detection list.
- **WHY**: Any error message containing these common English words triggers `refresh_pool_credentials()` → `recreate_pool()`, orphaning the active pool.
- **WHERE**: `infrastructure/db_auth.py`, `ManagedIdentityAuth.is_auth_error()`, lines 134-139.
- **HOW**: Replace `"token"` with `"token is expired"` or `"access token"`. Replace `"expired"` with `"token expired"` or `"credential expired"`. Rely primarily on SQLSTATE codes `28P01`/`28000`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 2: Redact token/password from logged connection string

- **WHAT**: Redact the `password=...` field before logging.
- **WHY**: `conn_string` contains live OAuth token or dev password. Appears in Application Insights.
- **WHERE**: `infrastructure/pgstac_bootstrap.py`, line 916. Audit other `conn_string` log sites.
- **HOW**: Add `redact_connection_string()` utility to `db_utils.py`. Apply at all log sites.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 3: Narrow `_ensure_schema_exists` exception handling

- **WHAT**: Let `CircuitBreakerOpenError` propagate instead of being swallowed.
- **WHY**: Bare `except Exception` catches circuit breaker signals, making the repository appear healthy when DB is confirmed down.
- **WHERE**: `infrastructure/postgresql.py`, `_ensure_schema_exists()`, line 294.
- **HOW**: Re-raise `CircuitBreakerOpenError` before generic catch, or narrow to `(psycopg.Error, OSError)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 4: Route env vars through AppConfig

- **WHAT**: Move `EXTERNAL_DB_PASSWORD` and `DOCKER_DB_POOL_MIN/MAX` into the config layer.
- **WHY**: Constitution rule 2.2 — direct `os.environ.get()` bypasses validation and diagnostics.
- **WHERE**: `infrastructure/db_auth.py:303`, `infrastructure/connection_pool.py:171-172`.
- **HOW**: Add fields to `ExternalEnvironmentConfig` and database config.
- **EFFORT**: Medium (1-4 hours).
- **RISK OF FIX**: Low.

### Fix 5: Thread-safe orphaned pool list

- **WHAT**: Move `_cleanup_orphaned_pools()` under `_pool_lock`.
- **WHY**: Concurrent `recreate_pool()` calls can race on list reads/writes.
- **WHERE**: `infrastructure/connection_pool.py`, lines 362-380 and 383-440.
- **HOW**: Call cleanup inside the lock scope, or add lock inside cleanup method.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

---

## ACCEPTED RISKS

- **`_verified_schemas` mutable class-level set**: CPython GIL makes it safe. Revisit only for no-GIL Python.
- **Contextmanager yield-twice pattern**: Pre-existing, not introduced by decomposition. Safe as written due to `return` after `yield`.
- **`refresh_pool_credentials` on auth class**: Cohesion violation but only one call site. Not worth a coordinator.
- **Dual token acquisition codepaths**: Intentional — different modes have different lifecycles.
- **`__import__('time')` inline**: Cosmetic, works correctly.

---

## ARCHITECTURE WINS

- **Clean decomposition boundaries**: Each file has one responsibility with documented import graph.
- **Zero-breaking-change delegation**: `conn_string` property + `_get_connection()` + `_get_cursor()` preserve all 30+ consumer interfaces.
- **Orphan-and-sweep pool recreation**: Three-layer defense (max_lifetime, server idle timeout, janitor) handles token rotation without killing in-flight connections.
- **Circuit breaker**: Textbook correct — sliding window, half-open probe, thread-safe singleton.
- **`db_utils.py` as leaf node**: Zero infrastructure deps, safe to import from any layer, prevents circular imports.

---

## ADDITIONAL FINDINGS (not in Top 5, for cleanup)

| # | Severity | Finding | File:Line |
|---|----------|---------|-----------|
| 6 | MEDIUM | Contextmanager yield-twice risk (pre-existing) | db_connections.py:149,204 |
| 7 | MEDIUM | _verified_schemas not synchronized | postgresql.py:150 |
| 8 | MEDIUM | _orphaned_pools race (covered in Fix 5) | connection_pool.py:363 |
| 9 | MEDIUM | refresh_pool_credentials wrong home | db_auth.py:98 |
| 10 | MEDIUM | Dual token acquisition paths | connection_pool.py:206 vs db_auth.py:243 |
| 11 | LOW | Unused `import os` in postgresql.py | postgresql.py:65 |
| 12 | LOW | Missing standard file headers | db_auth.py, db_connections.py, db_utils.py |
| 13 | LOW | Missing `__all__` exports | db_auth.py, db_connections.py, db_utils.py |
| 14 | LOW | get_cursor auto-commit underdocumented | db_connections.py:85 |
| 15 | LOW | backend_pid access on broken conn | db_connections.py:252 |
| 16 | LOW | `__import__('time')` inline | db_auth.py:268 |
| 17 | LOW | Duplicated transient-error marker lists | db_connections.py:108,158 |
| 18 | LOW | Stale LAST_REVIEWED header | postgresql.py:6 |
| 19 | LOW | Token potentially in psycopg_pool logs | connection_pool.py:226 |
| 20 | LOW | Backward-compat aliases need removal date | postgresql.py:102 |
