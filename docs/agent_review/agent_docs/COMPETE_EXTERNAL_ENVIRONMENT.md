# COMPETE Run 42: External Environment Infrastructure

**Date**: 10 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Scope**: External Environment Infrastructure — config, DB initializer, health checks, connection wiring
**Split**: B (Internal vs External)
**Files**: 11
**Verdict**: Significant security gaps require fixes before production; core architecture is sound

---

## EXECUTIVE SUMMARY

The External Environment Infrastructure subsystem is a well-structured admin toolkit for provisioning external PostgreSQL databases with pgSTAC and geo schemas. Its core workflow — token acquisition, prerequisite checks, schema creation, function fixups — is logically sound and follows the project's stage-based patterns. However, **all three HTTP endpoints lack authentication, accept arbitrary connection targets from any caller, and return full Python stack traces in error responses**. The connection string is built via string interpolation of unsanitized HTTP input, creating a confirmed injection vector. The config layer violates the project's own Constitution (no silent fallbacks) in two places. These are not speculative concerns — every finding in this report was confirmed against the actual source code. The subsystem is acceptable for a single-developer dev environment today, but the top three fixes are mandatory before any broader use.

---

## TOP 5 FIXES

### Fix 1: Remove stack traces from HTTP error responses

- **WHAT**: Replace `traceback.format_exc()` in error responses with a generic error message and a correlation ID.
- **WHY**: Full tracebacks leak internal paths, library versions, and potentially AAD tokens that appear in connection strings during failures. This is the most immediately exploitable information disclosure.
- **WHERE**: `triggers/admin/admin_external_db.py`, function `external_db_initialize`, lines 157-167. Also function `external_db_prereqs`, lines 240-250.
- **HOW**: Log the traceback at `logger.error()` level (already done on lines 158, 241). Replace the response body with `{"error": "External DB initialization failed", "correlation_id": "<uuid>"}`. Remove `traceback.format_exc()` from response construction entirely.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Only changes error response format; no logic affected.

### Fix 2: Sanitize and validate connection parameters before building libpq connection string

- **WHAT**: Validate `target_host`, `target_database`, and `admin_umi_name` against strict regex before interpolating into the libpq key-value connection string.
- **WHY**: `target_host` flows from HTTP request body (line 117 of `admin_external_db.py`) directly into the libpq connection string (lines 194-201 of `external_db_initializer.py`) via f-string interpolation. A crafted `target_host` containing spaces and libpq keywords (e.g., `"evil.com password=stolen sslmode=disable"`) can inject arbitrary connection parameters.
- **WHERE**: `services/external_db_initializer.py`, method `_get_connection`, lines 194-201. Validate at entry in `__init__`, lines 144-161.
- **HOW**: In `__init__`, validate: (1) `target_host` must match `^[a-zA-Z0-9._-]+$`; (2) `target_database` must match `^[a-zA-Z0-9_-]+$`; (3) `admin_umi_name` must match `^[a-zA-Z0-9_-]+$`; (4) `admin_umi_client_id` must match UUID format. Alternatively, switch `_get_connection` to use `psycopg.connect()` with keyword arguments.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Adds input validation; valid inputs pass unchanged.

### Fix 3: Eliminate silent fallback from external DB to app DB in `postgresql.py`

- **WHAT**: Raise an explicit error when `target_database="external"` but external config is not configured, instead of silently falling back to the app schema.
- **WHY**: Violates Constitution rule 1.1. A misconfigured external environment silently writes to the internal app database. Same violation in `external_config.py:from_environment()` where `EXTERNAL_DB_HOST` falls back to `POSTGIS_HOST`.
- **WHERE**: `infrastructure/postgresql.py`, `__init__` method, lines 335-338. Also `config/external_config.py`, `from_environment`, lines 165-167.
- **HOW**: In postgresql.py, replace the `else` branch with: `elif target_database == "external": raise ConfigurationError("target_database='external' but external not configured")`. In external_config.py, change fallback from `os.environ.get("POSTGIS_HOST", "")` to just `""`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Medium. Any code relying on the silent fallback will start raising errors.

### Fix 4: Fix `is_configured` to read model fields instead of `os.environ`

- **WHAT**: Change `is_configured` property to check `self.db_host` and `self.db_name` instead of reading `os.environ` directly.
- **WHY**: The Pydantic model already loaded and validated these values. Reading `os.environ` again bypasses model-level defaults, transformations, and test overrides. An instance constructed with explicit arguments reports `is_configured=False` even with valid values.
- **WHERE**: `config/external_config.py`, property `is_configured`, lines 118-124.
- **HOW**: Replace body with `return bool(self.db_host or self.db_name)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 5: Minimize subprocess environment for pypgstac migrate

- **WHAT**: Build a minimal environment dict instead of copying the full `os.environ`.
- **WHY**: `os.environ.copy()` at line 412 passes every secret (Azure connection strings, storage keys, database credentials) to the subprocess.
- **WHERE**: `services/external_db_initializer.py`, method `_initialize_pgstac_schema`, lines 411-419.
- **HOW**: Replace with minimal dict containing only `PATH`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. Test that pypgstac still runs with reduced environment.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Medium. pypgstac may depend on unstated environment variables.

---

## ALL FINDINGS — SEVERITY RECALIBRATION

### CRITICAL (Must fix before production use)

| # | ID | Finding | Confidence |
|---|-----|---------|------------|
| 1 | F2/AR4 | Full stack traces in HTTP error responses (admin_external_db.py:160-164, 243-249). AAD token leakage risk. | CONFIRMED |
| 2 | F4/C1 | Connection string injection via unsanitized target_host (external_db_initializer.py:194-201). | CONFIRMED |
| 3 | F1 | No authentication on admin initialization endpoints (admin_external_db.py:63-167). | CONFIRMED |

### HIGH (Should fix before production use)

| # | ID | Finding | Confidence |
|---|-----|---------|------------|
| 4 | F3 | Admin UMI client ID in GET query string (admin_external_db.py:199). | CONFIRMED |
| 5 | R2 | Subprocess inherits full environment (external_db_initializer.py:412). | CONFIRMED |
| 6 | AR3 | POSTGIS_HOST fallback violates Constitution 1.1 (external_config.py:165-167). | CONFIRMED |
| 7 | BS7 | Silent fallback to app DB when external not configured (postgresql.py:335-338). | CONFIRMED |

### MEDIUM (Fix in next iteration)

| # | ID | Finding | Confidence |
|---|-----|---------|------------|
| 8 | H1/E1 | is_configured reads os.environ instead of model fields (external_config.py:119-124). | CONFIRMED |
| 9 | AR1 | sql.SQL() for function signatures (external_db_initializer.py:521-527). Zero practical risk. | CONFIRMED |
| 10 | AR2/F5 | External storage health check bypasses BlobRepository (external.py:194-199). | CONFIRMED |
| 11 | BS3/F8 | db_connection_timeout configured but never used (external_config.py:101-104). | CONFIRMED |
| 12 | F7 | Token not refreshed between multi-step operations (external_db_initializer.py:225, 798-800). | CONFIRMED |
| 13 | H2/BS2 | PublicDatabaseConfig dead code (database_config.py:542-689). | CONFIRMED |

### LOW (Cleanup)

| # | ID | Finding | Confidence |
|---|-----|---------|------------|
| 14 | L2 | ExternalDatabaseInitializer hardcodes PGSTAC_SCHEMA (external_db_initializer.py:142). | CONFIRMED |
| 15 | BS1 | ExternalDefaults duplicates DatabaseDefaults values (defaults.py:807-808 vs 255-258). | CONFIRMED |
| 16 | BS4 | schemas=[] produces success=True with no work (external_db_initializer.py:753-754). | CONFIRMED |
| 17 | BS6 | check_database_configuration reads os.environ directly (database.py:286-297). | CONFIRMED |
| 18 | M5 | Redundant is_external_configured() check in health check (external.py:61). | CONFIRMED |
| 19 | M1 | DBA SQL strings use f-string (display-only, never executed). | CONFIRMED |
| 20 | M2/C2 | ExternalDatabaseInitializer bypasses Repository pattern. Architecturally justified. | CONFIRMED |
| 21 | F10 | Error messages in check_prerequisites may leak connection details. | PROBABLE |

---

## ACCEPTED RISKS

### A1: No authentication on admin endpoints (F1)
Acceptable today: single-developer dev environment, endpoints require valid AAD Managed Identity client ID to actually connect. **Revisit when**: second user gains access, external network path opens, or before production.

### A2: Admin UMI client ID in GET query string (F3)
The UMI client ID is not a secret credential — it identifies which managed identity to use, not a password. Token acquisition happens server-side via AAD. **Revisit when**: endpoint exposed to browser-based clients.

### A3: Token not refreshed between multi-step operations (F7)
AAD tokens last 60-90 minutes. Full initialization takes under 5 minutes. **Revisit when**: operations become long-running or retries span token expiry.

### A4: PublicDatabaseConfig dead code (H2/BS2)
Harmless dead code that increases maintenance surface. **Revisit when**: next cleanup iteration.

### A5: db_connection_timeout unused (BS3/F8)
Connection to unreachable hosts may hang indefinitely. Acceptable in dev where operator can kill the request. **Revisit when**: automated/scheduled initialization added.

---

## ARCHITECTURE WINS

1. **Structured step-based initialization result**: `InitStep` / `ExternalInitResult` pattern with per-step status, SQL executed, error messages, and timing provides excellent observability. Preserve this pattern.

2. **Proper psycopg.sql composition for DDL**: Schema creation consistently uses `sql.Identifier()` for schema and role names (lines 326, 402-404 in external_db_initializer.py). Correct approach that prevents SQL injection.

3. **AAD Managed Identity for auth**: Uses `ManagedIdentityCredential` with explicit `client_id` (line 177) for scoped database tokens, not passwords.

4. **Prerequisite check as separate endpoint**: Lets operators verify DBA prerequisites before initialization. Fail-fast design prevents partial initialization. `dba_sql` output shows exactly what the DBA needs to run.

5. **Dry-run mode**: Threads through all steps, allowing SQL preview without modifying the target database. Strong operational safety pattern.

---

## SCOPE SPLIT DETAILS

| Field | Value |
|-------|-------|
| **Split** | B (Internal vs External) |
| **Alpha scope** | Internal Logic and Invariants |
| **Beta scope** | External Interfaces and Boundaries |
| **Gamma priority files** | config/defaults.py, triggers/health_checks/__init__.py, triggers/health_checks/database.py |

---

## TOKEN USAGE

| Agent | Role | Estimated Tokens |
|-------|------|-----------------|
| Omega | Scope split | — (inline) |
| Alpha | Internal Logic | ~121K |
| Beta | External Interfaces | ~91K |
| Gamma | Contradictions | ~101K |
| Delta | Final Report | ~38K |
| **Total** | | **~351K** |
