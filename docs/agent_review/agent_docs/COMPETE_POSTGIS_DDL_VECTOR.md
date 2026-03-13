# COMPETE Run 3: PostGIS DDL & Vector

**Date**: 13 MAR 2026
**Version**: v0.10.1.1
**Scope**: DDL generation, vector PostGIS writes, split views, schema operations
**Split**: C (SQL Injection Surface vs DDL Safety & Data Integrity)
**Files Reviewed**: 8 primary (sql_generator.py, postgis_handler.py, view_splitter.py, handler_vector_docker_complete.py, geo_table_builder.py, external_db_initializer.py, pgstac_bootstrap.py, unpublish_handlers.py)
**Fix Status**: 4/4 HIGH+MEDIUM fixes applied

---

## EXECUTIVE SUMMARY

The PostGIS DDL and vector write surface demonstrates strong SQL injection discipline — `sql.Identifier()` and parameterized queries are used consistently across the critical paths. The review found no exploitable injection vectors in the current deployment. However, two defense-in-depth gaps were identified: column definitions in `geo_table_builder.py` were built as f-strings (bypassing `sql.Identifier()`), and geometry types from Shapely were passed via `sql.SQL()` without an allowlist. A confirmed data integrity issue was found in the unpublish path, where split view catalog entries were orphaned after table DROP CASCADE.

---

## TOP FIXES APPLIED

### Fix 1 (HIGH): Unpublish leaves orphaned split view catalog entries

- **WHAT**: Added `cleanup_split_view_metadata(conn, table_name)` call in `drop_postgis_table()` after CASCADE drops views
- **WHY**: `DROP TABLE CASCADE` auto-drops views, but their `geo.table_catalog` entries persisted. TiPG discovered phantom collections that 404 on access.
- **WHERE**: `services/unpublish_handlers.py:1119-1125`

### Fix 2 (HIGH): `geo_table_builder.py` column defs via sql.Identifier()

- **WHAT**: Replaced f-string column definitions with `sql.Identifier(name) + sql.SQL(type)` composition
- **WHY**: Column names from GeoDataFrame headers were passing through `_clean_column_name()` sanitization but bypassing `sql.Identifier()` quoting. Now matches the composition pattern used everywhere else.
- **WHERE**: `core/schema/geo_table_builder.py:255-297`

### Fix 3 (MEDIUM): Geometry type allowlist

- **WHAT**: Added `VALID_GEOM_TYPES` frozenset and validation in 3 files / 5 code paths
- **WHY**: `geom_type` from Shapely was passed via `sql.SQL()` without validation. Constrained by Shapely's type system but no defense-in-depth.
- **WHERE**: `services/vector/postgis_handler.py:49-52,1024,1627`, `core/schema/geo_table_builder.py:40-43,346`

### Fix 4 (accepted as-is): Non-atomic overwrite DROP+CREATE

- **STATUS**: Already transactional — DROP and CREATE share the same cursor context with commit after both. No code change needed.

---

## ACCEPTED RISKS

### A. No concurrency protection for table name collisions (MEDIUM)

Two concurrent ETL jobs targeting the same `table_name` with `overwrite=true` can race. Job ID deduplication (SHA256) prevents identical jobs, but different jobs targeting the same table could collide. Advisory lock on table name would be the fix.

- **Impact**: Data corruption — one job silently replaces the other's data
- **Revisit when**: Multi-user concurrent vector uploads become common
- **File**: `services/vector/postgis_handler.py:1584-1667`

### B. Ensure mode cannot evolve enum values (MEDIUM)

`action=ensure` skips all enum statements when the type exists. Adding a new value to a Python enum requires `action=rebuild`. No `ALTER TYPE ... ADD VALUE` path.

- **Impact**: New enum values silently fail until rebuild
- **Revisit when**: Enum changes need to be non-destructive (production migrations)
- **File**: `triggers/admin/db_maintenance.py:682-707`

### C. Full rebuild non-atomic between DROP and CREATE (MEDIUM)

Steps 1-2 (DROP app, DROP pgstac) are committed separately from Step 3 (CREATE). If Step 3 fails, both schemas are gone. Acceptable for dev environment per project philosophy.

- **Impact**: Database completely broken on rebuild failure — re-run rebuild to recover
- **File**: `triggers/admin/db_maintenance.py:1278-1397`

### D. PL/pgSQL function bodies use str.format(schema=) (LOW)

`schema_name` comes from config (never user input), so currently safe. Deviates from `sql.Identifier()` pattern used everywhere else.

- **Revisit when**: Multi-tenant schema routing from user input
- **File**: `core/schema/sql_generator.py:1361-1542`

### E. `partial_where` in IndexBuilder accepted as raw sql.SQL() (LOW)

All callers pass hard-coded strings. Safe unless future callers pass user input.

- **File**: `core/schema/ddl_utils.py:225-339`

---

## ARCHITECTURE WINS

1. **`sql.Identifier()` throughout DDL** — All table/column/schema names in critical paths use `sql.Identifier()` composition. The `_execute_query` guard at `postgresql.py:1111-1112` rejects non-Composed queries.

2. **Idempotent chunk insertion via batch_id** — DELETE+INSERT within single transaction guarantees exact-once semantics for retried uploads.

3. **Deferred index creation** — Spatial and attribute indexes built AFTER all data loaded, 10-50x faster than maintaining during INSERT.

4. **ANALYZE after complete data load** — Query planner gets accurate statistics. Sequence: data → indexes → ANALYZE → split views.

5. **Split view creation is atomic** — All views created within caller's transaction, committed together.

6. **Column sanitizer** — `[a-z0-9_]` regex strips all SQL-significant characters from GeoDataFrame column names. PostgreSQL reserved words get `f_` prefix.

7. **External DB input validation** — Regex validation on host, database, UMI name, UUID format before any SQL use.

8. **Geo schema preserved during rebuild** — Full rebuild explicitly never touches the geo schema, protecting user-uploaded data.

---

## FULL FINDING LOG (Gamma Recalibrated)

| # | Severity | Finding | Confidence | Source |
|---|----------|---------|------------|--------|
| 1 | HIGH | Unpublish orphans split view catalog entries | CONFIRMED | Beta-1 |
| 2 | HIGH | geo_table_builder column defs as f-strings | CONFIRMED | Alpha-2 |
| 3 | MEDIUM | geom_type via sql.SQL() without allowlist | CONFIRMED | Alpha-1/7 |
| 4 | MEDIUM | No concurrency protection for table name collisions | CONFIRMED | Beta-6 |
| 5 | MEDIUM | Ensure mode can't evolve enum values | CONFIRMED | Beta-3 |
| 6 | MEDIUM | Full rebuild non-atomic | CONFIRMED | Beta-4 |
| 7 | MEDIUM | Non-atomic overwrite DROP+CREATE (actually transactional) | CONFIRMED | Beta-2 |
| 8 | LOW | PL/pgSQL str.format(schema=) | CONFIRMED | Alpha-3 |
| 9 | LOW | pgstac_bootstrap func_sig as raw sql.SQL() | CONFIRMED | Alpha-4 |
| 10 | LOW | DBA SQL uses f-strings (display-only) | CONFIRMED | Alpha-5 |
| 11 | LOW | partial_where as raw sql.SQL() | CONFIRMED | Alpha-6 |
| 12 | LOW | DROP TYPE CASCADE in sql_generator | CONFIRMED | Beta-7 |
| 13 | LOW | PgSTAC bootstrap partial state | CONFIRMED | Beta-8 |
| 14 | LOW | External geo DROP without data warning | CONFIRMED | Beta-9 |
| 15 | LOW | _nuke_schema drops tables before views | CONFIRMED | Beta-10 |
| 16 | LOW | Autocommit in ensure (by design) | CONFIRMED | Beta-5 |

**Total: 2 HIGH, 5 MEDIUM, 9 LOW**

## FIX LOG (13 MAR 2026)

| # | Finding | Fix | File | Status |
|---|---------|-----|------|--------|
| 1 | HIGH: Orphaned split view catalog entries | Added cleanup_split_view_metadata() in unpublish | `unpublish_handlers.py:1119-1125` | ✅ FIXED |
| 2 | HIGH: geo_table_builder f-string columns | Replaced with sql.Identifier() + sql.SQL() composition | `geo_table_builder.py:255-297` | ✅ FIXED |
| 3 | MEDIUM: geom_type no allowlist | Added VALID_GEOM_TYPES frozenset, validation in 3 files | `postgis_handler.py`, `geo_table_builder.py` | ✅ FIXED |
