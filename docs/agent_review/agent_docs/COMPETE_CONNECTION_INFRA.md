# COMPETE Run: Database Connection Infrastructure

**Date**: 13 MAR 2026
**Version**: v0.10.1.1
**Scope**: Connection pooling, circuit breaker, PostgreSQL repository base, database config
**Split**: A (Design vs Runtime)
**Files Reviewed**: 8 primary + 4 priority files
**Fix Status**: 5/5 TOP FIXES COMPLETE — all CRITICAL + HIGH findings resolved 13 MAR 2026

---

## EXECUTIVE SUMMARY

The database connection subsystem is functional and has served the project reliably through 10+ versioned deployments. The core architecture — dual-mode connections (pool for Docker, single-use for Functions), circuit breaker, and sql.Composed enforcement — is sound. However, two confirmed issues are genuinely dangerous: the circuit breaker HALF_OPEN state allows unlimited concurrent probes (contradicting its own docstring), and hardcoded `app.tasks` in debug queries will silently break task completion detection if APP_SCHEMA is ever reconfigured. The remaining findings are latent inefficiencies (triple schema check on factory call, N+1 in update_task, unbounded list_jobs) and code hygiene issues that are safe to defer but worth a cleanup pass.

---

## TOP 5 FIXES

### 1. Circuit breaker HALF_OPEN allows unlimited concurrent probes

- **WHAT**: Add a `_half_open_permit` boolean flag so only the first thread entering HALF_OPEN is allowed through; subsequent callers are rejected until the probe completes.
- **WHY**: When the circuit transitions OPEN→HALF_OPEN, every concurrent caller passes `check()` and hits the recovering database simultaneously. The docstring at line 19 promises "allow ONE request through" but the code at line 146-147 returns unconditionally for all HALF_OPEN callers. This defeats the entire purpose of the circuit breaker during recovery.
- **WHERE**: `infrastructure/circuit_breaker.py`, `check()` method, lines 113-147. Also affects `record_success()` (line 149) and `record_failure()` (line 161) which must reset the permit.
- **HOW**: Add `self._half_open_permit_taken = False` in `__init__`. In `check()`, when transitioning to HALF_OPEN (line 130), set `self._half_open_permit_taken = True` and return. At the existing HALF_OPEN branch (line 146), check if `_half_open_permit_taken` — if True, raise `CircuitBreakerOpenError` with a "probe in progress" message. In `record_success()` and `record_failure()`, reset `_half_open_permit_taken = False`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### 2. Hardcoded `app.tasks` schema in debug queries inside `complete_task_and_check_stage`

- **WHAT**: Replace the two raw SQL strings referencing `app.tasks` with `sql.SQL`/`sql.Identifier` composition using `self.schema_name`.
- **WHY**: Lines 2355-2357 and 2403-2410 contain `"SELECT status FROM app.tasks WHERE task_id = %s"`. If `APP_SCHEMA` != `"app"`, these queries silently hit the wrong schema. These also open separate connections inside the critical completion path, adding 2 extra connections per task completion.
- **WHERE**: `infrastructure/postgresql.py`, `complete_task_and_check_stage()`, lines 2353-2360 and 2401-2413.
- **HOW**: (a) Replace both raw strings with `sql.SQL(...).format(sql.Identifier(self.schema_name), sql.Identifier("tasks"))`. (b) Wrap in `if logger.isEnabledFor(logging.DEBUG):` to avoid connection overhead when not debugging.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### 3. `build_where_clause` does not validate the `operator` parameter

- **WHAT**: Add a whitelist check that `operator` is one of `("AND", "OR")` before interpolating into `sql.SQL`.
- **WHY**: Line 1276: `sql.SQL(f" {operator} ")` injects the `operator` string directly into SQL without validation. Currently all callers use default `"AND"`, but the method is public. Latent SQL injection vector that contradicts the "disciplined SQL composition" contract at line 1225.
- **WHERE**: `infrastructure/postgresql.py`, `build_where_clause()`, line 1276.
- **HOW**: Add at method top: `if operator.upper() not in ("AND", "OR"): raise ValueError(f"operator must be 'AND' or 'OR', got '{operator}'")`
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### 4. `list_jobs` returns unbounded result set

- **WHAT**: Add a `LIMIT` clause with a sensible default (e.g., 1000) and accept an optional `limit` parameter.
- **WHY**: Lines 1881-1949: both query branches have `ORDER BY created_at DESC` but no `LIMIT`. As the jobs table grows, this loads the entire table into memory with JSONB parsing per row.
- **WHERE**: `infrastructure/postgresql.py`, `list_jobs()`, lines 1881-1949.
- **HOW**: Add `limit: int = 1000` parameter. Append `sql.SQL(" LIMIT %s")` to both query branches.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### 5. Factory `create_repositories` triggers 3 schema checks (3 DB connections)

- **WHAT**: Cache schema verification per schema name so it only runs once per process.
- **WHY**: `factory.py:90-94` creates 3 repositories sequentially. Each calls `_ensure_schema_exists()`, opening a DB connection. That's 3 connections just to verify the same schema — on every factory call including cold starts.
- **WHERE**: `infrastructure/postgresql.py`, `__init__()` line 352, and `_ensure_schema_exists()` lines 1010-1063. Called from `infrastructure/factory.py` lines 90-94.
- **HOW**: Add class-level `_verified_schemas: set[str] = set()`. In `_ensure_schema_exists`, check `if self.schema_name in cls._verified_schemas: return` at top, add to set on success.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

---

## ACCEPTED RISKS

### A. `update_task` unconditional GET-before-UPDATE

Lines 2144-2155 add a read round-trip per task update for DEBUG logging. Overhead is bounded by task count per stage (typically 1-20). **Revisit** if 100+ task stages become common.

### B. God-class PostgreSQLRepository at ~2600 lines

Responsibilities are tightly cohesive. Splitting would create circular dependencies since `_get_connection`, `_execute_query`, and `build_where_clause` are shared. **Revisit** if file exceeds ~3500 lines.

### C. Duplicate connection string building

Pool version is simpler (Docker-only, MI-only). Full version handles local dev, password auth, external DBs. Unifying would increase coupling. **Revisit** if auth paths diverge further.

### D. ~~External config falls back to app config for MI vars~~ → RESOLVED 13 MAR 2026

**FIXED**: Removed silent fallback to app DB MI vars. When external DB is configured with MI, `EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID` and `EXTERNAL_DB_MANAGED_IDENTITY_NAME` are now **required** — `ValueError` raised at startup if missing. Prevents wrong-principal authentication when external DB uses a separate UMI.

### E. `_execute_query` wraps psycopg errors as RuntimeError

Loses structured error type but upstream decorators provide context. **Revisit** if retryable vs non-retryable error classification is added.

---

## ARCHITECTURE WINS

1. **`sql.Composed` enforcement in `_execute_query`** (postgresql.py:1111-1112). The `TypeError` guard rejecting non-Composed queries is the single most effective injection prevention mechanism in the project.

2. **Dual-mode connection management** (postgresql.py:795-950, connection_pool.py). Clean routing between pooled (Docker) and single-use (Functions) via `is_pool_mode()`. Pool's `configure` callback sets search_path and type adapters identically to single-use path.

3. **Circuit breaker with sliding-window failure tracking** (circuit_breaker.py:50-200). Windowed failure counting is superior to simple consecutive-failure counter — prevents stale failures from blocking the trip threshold. `get_stats()` provides complete observability.

4. **`ExternalDatabaseInitializer` input validation** (external_db_initializer.py:145-172). Regex validation of host, database name, UMI name, and UUID format prevents connection string injection at the source.

5. **`_register_type_adapters` as connection-level hook** (postgresql.py:115-125). dict→JSONB and Enum→.value adapters at connection creation eliminates an entire class of serialization bugs.

---

## FULL FINDING LOG (Gamma Recalibrated)

| # | Severity | Finding | Confidence | Source |
|---|----------|---------|------------|--------|
| 1 | CRITICAL | HALF_OPEN unlimited probes | CONFIRMED | Beta CRITICAL-1 |
| 2 | CRITICAL | Hardcoded app.tasks schema | CONFIRMED | Beta HIGH-1 (promoted) |
| 3 | HIGH | God-class PostgreSQLRepository | PROBABLE | Alpha HIGH-2 |
| 4 | HIGH | Duplicate connection string building | CONFIRMED | Alpha HIGH-3 |
| 5 | HIGH | update_task N+1 | CONFIRMED | Beta HIGH-2 |
| 6 | HIGH | list_jobs no LIMIT | CONFIRMED | Beta HIGH-3 |
| 7 | HIGH | Factory triple schema check | CONFIRMED | Gamma BS-1 |
| 8 | HIGH | operator injection in build_where_clause | CONFIRMED | Beta MEDIUM-4 (promoted) |
| 9 | MEDIUM | Bidirectional coupling pool↔postgresql | CONFIRMED | Alpha HIGH-1 |
| 10 | MEDIUM | _ensure_schema_exists triggers circuit breaker | CONFIRMED | Alpha MEDIUM-5 + Beta E4 |
| 11 | MEDIUM | _execute_query RuntimeError wrapping | CONFIRMED | Beta MEDIUM-2 |
| 12 | MEDIUM | External health check bypasses repo pattern | CONFIRMED | Gamma BS-2 |
| 13 | MEDIUM | External config credential fallback | CONFIRMED | Gamma BS-4 |
| 14 | MEDIUM | Token-to-pool lifetime gap | PROBABLE | Beta R1 |
| 15 | MEDIUM | Circuit breaker + pool recreation ordering | SPECULATIVE | Beta R2 |
| 16 | MEDIUM | Debug queries add 2 extra connections | CONFIRMED | Beta R3 |
| 17 | LOW | hasattr dead code | CONFIRMED | Alpha MEDIUM-4 |
| 18 | LOW | Unused pool config fields | CONFIRMED | Alpha MEDIUM-6 |
| 19 | LOW | _register_type_adapters naming | CONFIRMED | Alpha MEDIUM-7 |
| 20 | LOW | CircuitBreakerState missing from __init__.py | CONFIRMED | Alpha LOW-9 |
| 21 | LOW | File headers inconsistent | PROBABLE | Alpha LOW-10 |
| 22 | LOW | yield-inside-retry fragile pattern | CONFIRMED | Beta E1 |
| 23 | LOW | _shutdown_requested benign race | CONFIRMED | Beta E3 |
| 24 | LOW | ExternalDatabaseInitializer raw SQL | CONFIRMED | Gamma BS-3 |
| 25 | LOW | Health check exception info leak | CONFIRMED | Gamma BS-5 |
| 26 | LOW | _get_pool_config idempotent race | CONFIRMED | Beta MEDIUM-1 |

**Total: 2 CRITICAL, 6 HIGH, 8 MEDIUM, 10 LOW**

---

## FIX LOG (13 MAR 2026)

| # | Finding | Fix | File | Status |
|---|---------|-----|------|--------|
| 1 | CRITICAL: HALF_OPEN unlimited probes | Added `_half_open_permit_taken` flag — first caller takes permit, rest rejected | `circuit_breaker.py` | ✅ FIXED |
| 2 | CRITICAL: Hardcoded `app.tasks` schema | Replaced raw SQL with `sql.SQL`/`sql.Identifier(self.schema_name)`, gated behind `logger.isEnabledFor(DEBUG)` | `postgresql.py:2355-2413` | ✅ FIXED |
| 3 | HIGH: `build_where_clause` operator injection | Added whitelist: `if operator.upper() not in ("AND", "OR"): raise ValueError(...)` | `postgresql.py:1280` | ✅ FIXED |
| 4 | HIGH: `list_jobs` unbounded result set | Added `limit: int = 1000` parameter, `LIMIT %s` appended to both query branches | `postgresql.py:1885-1955` | ✅ FIXED |
| 5 | HIGH: Factory triple schema check | Added `_verified_schemas: set` class-level cache; `_ensure_schema_exists()` checks cache first, adds on success | `postgresql.py:220,1043-1070` | ✅ FIXED |
| D | ACCEPTED→FIXED: External MI fallback | Removed silent fallback to app DB MI vars; `EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID` + `_NAME` now required when external DB configured with MI | `external_config.py:152-211` | ✅ FIXED |
