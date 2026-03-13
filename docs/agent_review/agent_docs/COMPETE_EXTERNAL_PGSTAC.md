# COMPETE Run 4: External DB & PgSTAC

**Date**: 13 MAR 2026
**Version**: v0.10.1.1
**Scope**: External DB connection isolation, admin initialization, PgSTAC write correctness, STAC materialization, search registration
**Split**: D (External DB Security & Connection Isolation vs PgSTAC Data Integrity & Write Correctness)
**Files Reviewed**: 11 primary (external_config.py, database_config.py, postgresql.py, external_db_initializer.py, admin_external_db.py, health_checks/external.py, pgstac_repository.py, pgstac_bootstrap.py, stac_materialization.py, pgstac_search_registration.py, asset_approval_service.py)
**Fix Status**: 7/7 fixes applied — 3 HIGH, 3 MEDIUM, 1 LOW

---

## EXECUTIVE SUMMARY

The external DB surface demonstrates strong input validation (regex patterns on host/database/UMI) and correct credential isolation after the 13 MAR 2026 MI fallback fix. However, the admin initialization endpoint lacked explicit auth gating and host allowlisting, and the password-auth fallback path reused app DB credentials for external connections — a credential cross-contamination risk. The PgSTAC write surface has solid architectural foundations (upsert idempotency, centralized B2C sanitization, approval rollback on STAC failure) but suffers from the "error-as-default-value" antipattern: `collection_exists()` returning False on DB errors could clobber collection extents with placeholder bboxes, and rebuild operations had hardcoded limits that silently truncated results.

---

## TOP FIXES APPLIED

### Fix 1 (HIGH): `is_configured` used OR instead of AND

- **WHAT**: Changed `return bool(self.db_host or self.db_name)` to `return bool(self.db_host and self.db_name)`
- **WHY**: `from_environment()` uses AND logic for MI validation. With OR, setting only `EXTERNAL_DB_HOST` (no `EXTERNAL_DB_NAME`) made `is_configured=True` but skipped MI validation — downstream code would try connecting to an empty database name.
- **WHERE**: `config/external_config.py:121`

### Fix 2 (HIGH): App DB password reused for external DB connections

- **WHAT**: External DB password-auth path now requires `EXTERNAL_DB_PASSWORD` env var; raises ValueError if not set
- **WHY**: The old code used `self.config.postgis_password` (app DB password) to connect to external DB. If the two databases are on different servers (stated architecture), this sends app credentials to the wrong trust boundary.
- **WHERE**: `infrastructure/postgresql.py:_build_password_connection_string()`

### Fix 3 (HIGH): `collection_exists()` returned False on DB error

- **WHAT**: Removed try/except that swallowed all exceptions and returned False
- **WHY**: Callers like `materialize_release()` used this to decide whether to create a collection. A transient DB error → False → creates collection with placeholder bbox `[-180,-90,180,90]` via upsert → overwrites existing tight extent. DB errors now propagate; all callers already have appropriate exception handling.
- **WHERE**: `infrastructure/pgstac_repository.py:collection_exists()`

### Fix 4 (MEDIUM): Admin external DB endpoints lacked explicit auth + host allowlist

- **WHAT**: Added `auth_level=func.AuthLevel.FUNCTION` to both routes; added `EXTERNAL_DB_ALLOWED_HOSTS` env var check
- **WHY**: Without explicit auth_level, the endpoints relied on Azure Functions defaults. Added defense-in-depth: function key requirement + optional host allowlist. Allowlist is backward-compatible (no-op when env var unset).
- **WHERE**: `triggers/admin/admin_external_db.py:67,188` (auth_level) + lines 129-141, 249-261 (allowlist)

### Fix 5 (MEDIUM): Rebuild limits silently truncated results

- **WHAT**: Increased limits from 1000/10000 to 100000 with warning log when hit
- **WHY**: `rebuild_collection_from_db(limit=1000)` and `rebuild_all_from_db(limit=10000)` silently dropped releases beyond the limit. A "full catalog rebuild" producing an incomplete catalog with no warning defeats the purpose.
- **WHERE**: `services/stac_materialization.py:601,718`

### Fix 6 (MEDIUM): `get_collection_item_ids()` unbounded + `SET search_path` connection pollution

- **WHAT**: Added `limit` parameter (default 50000) to `get_collection_item_ids()`; changed `SET search_path` to `SET LOCAL search_path` in search registration
- **WHY**: Unbounded query could load millions of IDs for large tiled mosaics. `SET search_path` without `LOCAL` persisted across connection pool reuse, potentially causing subsequent queries to resolve against wrong schema.
- **WHERE**: `infrastructure/pgstac_repository.py:get_collection_item_ids()`, `services/pgstac_search_registration.py:148`

### Fix 7 (LOW): `pgstac_bootstrap.py` AttributeError in exception handler

- **WHAT**: Changed `self.connection_string` to `self._pg_repo.conn_string`
- **WHY**: `PgStacBootstrap.__init__()` never assigns `self.connection_string`. The old code would raise `AttributeError` in the exception handler, masking the real error.
- **WHERE**: `infrastructure/pgstac_bootstrap.py:916`

---

## ACCEPTED RISKS

### N. `update_collection_metadata` TOCTOU (MEDIUM)

Read-modify-write across separate connections. Two concurrent approvals into the same collection could race on extent updates. Mitigated by: (1) sequential approval flow in practice, (2) extent is recomputed from items on every approval, so the next approval corrects any stale extent.

- **Impact**: Extent temporarily stale (cosmetic — affects UI zoom, not data correctness)
- **Revisit when**: Concurrent bulk approvals become common
- **File**: `infrastructure/pgstac_repository.py:update_collection_metadata()`

### O. `rebuild_collection_from_db` non-atomic delete-then-reinsert (MEDIUM)

Items deleted one-by-one, then collection deleted, then reinserted. Collection invisible to consumers during the window. Acceptable because rebuild is a dev/admin operation, not runtime.

- **Impact**: Collection temporarily invisible during rebuild (seconds to minutes)
- **Revisit when**: Zero-downtime rebuild is required for production
- **File**: `services/stac_materialization.py:rebuild_collection_from_db()`

### P. Non-atomic `materialize_release` (MEDIUM)

Collection create → item insert → extent update are 3 separate connections. If extent update fails after item insert, collection has stale extent until next approval recalculates it. ADV-17 cleanup handles the collection-created-but-item-failed case.

- **Impact**: Extent temporarily stale on failed extent recomputation
- **File**: `services/stac_materialization.py:materialize_release()`

### Q. Search hash Python vs PostgreSQL (MEDIUM)

Python computes SHA256 of search query for dedup lookup, but PostgreSQL's GENERATED column uses `search_tohash(search, metadata)`. Lookup by Python hash may miss existing rows. Mitigated: code returns `result['hash']` (PostgreSQL-generated) on all code paths, so TiTiler always gets the correct hash. Worst case: unnecessary INSERT that updates via GENERATED column.

- **Impact**: Extra INSERT on duplicate registration (self-correcting)
- **Revisit when**: Dedup accuracy becomes critical
- **File**: `services/pgstac_search_registration.py:register_search()`

### R. N+1 connections in `_materialize_tiled_items` (MEDIUM)

Each item in a tiled collection is fetched and upserted individually — 2N connections for N items. Performance concern, not correctness.

- **Impact**: Slow materialization for large tiled collections
- **Revisit when**: Tiled collections exceed ~500 items
- **File**: `services/stac_materialization.py:_materialize_tiled_items()`

### S. Error-as-default-value in PgStacRepository query methods (LOW)

`get_collection()`, `get_item()`, `list_collections()`, `get_collection_item_count()` return None/[]/0 on DB errors. Callers cannot distinguish "not found" from "DB down". `collection_exists()` was the most dangerous instance (fixed). The remaining methods have lower blast radius since callers mostly use them for informational/display purposes.

- **Impact**: Misleading return values on transient DB errors
- **Revisit when**: Any of these methods gains correctness-critical callers
- **File**: `infrastructure/pgstac_repository.py` (multiple methods)

---

## ARCHITECTURE WINS

1. **Input validation regexes on ExternalDatabaseInitializer** — `_HOST_PATTERN`, `_DBNAME_PATTERN`, `_UUID_PATTERN`, `_UMI_NAME_PATTERN` prevent connection string injection.

2. **Explicit MI requirement for external DB** (13 MAR 2026) — No fallback to app DB identity vars. Fail-fast with clear error.

3. **Separate admin UMI for initialization** — The initializer uses a user-specified admin UMI (passed in request body), not the app's runtime UMI. Admin UMI can be revoked after setup.

4. **Minimal subprocess environment** — Only PATH + PG* vars passed to pypgstac. No leakage of storage keys or other secrets.

5. **ADV-17 collection cleanup on item failure** — Empty shell collections cleaned up when first item fails to materialize.

6. **Atomic approval with NOT EXISTS guard** — `approve_release_atomic()` uses single SQL UPDATE with WHERE guard preventing concurrent double-approval.

7. **STAC failure triggers approval rollback** — If pgSTAC write fails after DB approval, state is rolled back. Double-failure case handled with `MANUAL_INTERVENTION_REQUIRED`.

8. **DB-first ordering for revoke** — Internal DB updated first (source of truth), then pgSTAC. If pgSTAC delete fails, release is correctly marked REVOKED.

9. **Upsert everywhere** — `upsert_collection()` and `upsert_item()` make all pgSTAC writes idempotent by default.

10. **Centralized B2C sanitization** — All pgSTAC writes go through `STACMaterializer.sanitize_item_properties()`. No path bypasses sanitization.

11. **pgSTAC = deterministic function(internal DB)** — Full rebuild capability means pgSTAC can always be reconstructed from `asset_releases` + `cog_metadata`.

---

## FULL FINDING LOG (Gamma Recalibrated)

| # | Severity | Finding | Confidence | Source |
|---|----------|---------|------------|--------|
| 1 | HIGH | `is_configured` OR vs AND logic mismatch | CONFIRMED | Alpha |
| 2 | HIGH | App DB password reused for external connections | CONFIRMED | Alpha |
| 3 | HIGH | `collection_exists()` returns False on DB error | LIKELY | Beta |
| 4 | MEDIUM | Admin endpoints lack explicit auth_level | CONFIRMED | Alpha |
| 5 | MEDIUM | No target host allowlist on admin endpoint | CONFIRMED | Alpha |
| 6 | MEDIUM | Rebuild limits silently truncate results | CONFIRMED | Beta |
| 7 | MEDIUM | `get_collection_item_ids` unbounded result set | CONFIRMED | Beta |
| 8 | MEDIUM | `SET search_path` pollutes connection state | POSSIBLE | Beta |
| 9 | MEDIUM | `update_collection_metadata` TOCTOU | LIKELY | Beta |
| 10 | MEDIUM | `rebuild_collection_from_db` non-atomic | CONFIRMED | Beta |
| 11 | MEDIUM | Non-atomic `materialize_release` | CONFIRMED | Beta |
| 12 | MEDIUM | Search hash Python vs PostgreSQL mismatch | POSSIBLE | Beta |
| 13 | MEDIUM | N+1 connections in tiled materialization | CONFIRMED | Beta |
| 14 | MEDIUM | `rebuild_collection_from_db` fetches ALL then filters | CONFIRMED | Beta |
| 15 | MEDIUM | Error messages leak hostnames in health checks | CONFIRMED | Alpha |
| 16 | LOW | Error-as-default-value in PgStacRepository | CONFIRMED | Beta |
| 17 | LOW | `schemas` parameter not validated | POSSIBLE | Alpha |
| 18 | LOW | DBA SQL uses f-strings (display-only) | POSSIBLE | Alpha |
| 19 | LOW | pypgstac subprocess receives AAD token in env | POSSIBLE | Alpha |
| 20 | LOW | `sslmode=require` vs `verify-full` | CONFIRMED | Alpha |
| 21 | LOW | TiTiler health URL not validated for SSRF | POSSIBLE | Alpha |
| 22 | LOW | `pgstac_bootstrap.py` AttributeError in exception handler | CONFIRMED | Beta |

**Total: 3 HIGH, 11 MEDIUM, 8 LOW**

## FIX LOG (13 MAR 2026)

| # | Finding | Fix | File | Status |
|---|---------|-----|------|--------|
| 1 | HIGH: `is_configured` OR→AND | Changed to `bool(self.db_host and self.db_name)` | `external_config.py:121` | FIXED |
| 2 | HIGH: App password cross-contamination | Require `EXTERNAL_DB_PASSWORD` env var | `postgresql.py:_build_password_connection_string()` | FIXED |
| 3 | HIGH: `collection_exists` error swallowing | Removed try/except, errors propagate | `pgstac_repository.py:collection_exists()` | FIXED |
| 4 | MEDIUM: Admin auth + host allowlist | Added `AuthLevel.FUNCTION` + `EXTERNAL_DB_ALLOWED_HOSTS` | `admin_external_db.py:67,188` | FIXED |
| 5 | MEDIUM: Rebuild limits | Increased to 100000 with warning logs | `stac_materialization.py:601,718` | FIXED |
| 6 | MEDIUM: Unbounded items + search_path | Added LIMIT param + `SET LOCAL` | `pgstac_repository.py`, `pgstac_search_registration.py` | FIXED |
| 7 | LOW: AttributeError in exception handler | `self.connection_string` → `self._pg_repo.conn_string` | `pgstac_bootstrap.py:916` | FIXED |
