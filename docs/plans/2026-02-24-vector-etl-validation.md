# Vector ETL Validation & False Success Prevention

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent false success in the vector ETL pipeline where empty/corrupt PostGIS tables are created and reported as successful. Add post-insert row count verification, TiPG end-to-end probe, and investigate PostgresSyntaxError from TiPG.

**Architecture:** Three validation layers added to existing `handler_vector_docker_complete.py` flow:
1. Post-insert DB row count check (Phase 3 exit gate)
2. TiPG feature probe (Phase 4 enhancement)
3. Column name hardening against PostgresSyntaxError

**Tech Stack:** Python 3.12, psycopg3 (`psycopg.sql`), TiPG OGC API, httpx

**Reference:** Conversation analysis 24 FEB 2026 — identified 3 gaps in vector ETL validation

---

## Context: Current Flow & Gaps

```
Phase 1: Load source → GeoDataFrame          ✅ Has empty-file guard
Phase 1: prepare_gdf() → validate geometries  ✅ Has all-null guard
Phase 2: CREATE TABLE in PostGIS              ✅ Has empty-GDF guard
Phase 3: INSERT chunks via executemany        ⚠️ GAP: counts prepared list, not DB rows
Phase 4: Refresh TiPG catalog                 ⚠️ GAP: no feature count probe
COMPLETE: Return success                      ❌ GAP: no total_rows > 0 guard
```

**Three confirmed gaps:**
- **G1**: `insert_chunk_idempotent()` reports `len(all_values)` not actual DB row count
- **G2**: Completion returns `success: True` even when `total_rows == 0`
- **G3**: No end-to-end validation that TiPG can actually serve the data

**Suspected issue — TiPG PostgresSyntaxError:**
- Column names from source files (Shapefiles, GeoJSON) pass through to PostGIS
- Two different column cleaning functions exist (lines 580-589 basic vs 1274-1281 advanced)
- Column names that are PostgreSQL reserved words ARE quoted via `sql.Identifier()` in CREATE/INSERT
- But TiPG introspects tables via `information_schema` — if TiPG's own SQL generation doesn't quote column names, reserved words like `order`, `type`, `date`, `group`, `level`, `name`, `user` would cause syntax errors
- Empty tables would NOT cause PostgresSyntaxError — this is a column naming issue

---

## Task 1: Post-Insert Row Count Verification (G1)

**Files:**
- Modify: `services/vector/postgis_handler.py:1706-1713`
- Modify: `services/handler_vector_docker_complete.py:646-734`

**Step 1: Add actual row count query after executemany**

In `insert_chunk_idempotent()`, after `conn.commit()` (line 1710), query actual count:

```python
# After line 1710: conn.commit()

# Verify actual insert count
cur.execute(
    sql.SQL("SELECT COUNT(*) FROM {schema}.{table} WHERE etl_batch_id = %s").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name)
    ),
    (batch_id,)
)
actual_count = cur.fetchone()[0]

if actual_count != len(all_values):
    logger.warning(
        f"[{batch_id}] Row count mismatch: prepared={len(all_values)}, "
        f"actual={actual_count} in {schema}.{table_name}"
    )

rows_inserted = actual_count  # Use DB truth, not prepared count
```

Replace line 1708 (`rows_inserted = len(all_values)`) with the verified count above.

**Step 2: Commit**
```
fix: Verify actual row count after INSERT in insert_chunk_idempotent [G1]
```

---

## Task 2: Zero-Row Guard Before Returning Success (G2)

**Files:**
- Modify: `services/handler_vector_docker_complete.py:290-335`

**Step 1: Add total row count verification after chunk upload**

After line 294 (`total_rows = upload_result.get('total_rows', 0)`), add:

```python
total_rows = upload_result.get('total_rows', 0)

# G2 FIX: Verify at least 1 row was inserted
if total_rows == 0:
    raise ValueError(
        f"Vector ETL completed all phases but inserted 0 rows into "
        f"{schema}.{table_name}. Table exists but is empty. "
        f"Source had {len(gdf)} features after validation — "
        f"data was lost during chunk upload."
    )
```

This raises into the existing `except` block (line 337) which handles failure logging, release status update, and error response.

**Step 2: Commit**
```
fix: Fail job if 0 rows inserted after chunk upload [G2]
```

---

## Task 3: Full Table Row Count Cross-Check (G1 supplement)

**Files:**
- Modify: `services/handler_vector_docker_complete.py:290-295`

**Step 1: After all chunks uploaded, verify total table count matches**

After the zero-row guard (Task 2), add a full table count cross-check:

```python
# Cross-check: query actual total rows in table
try:
    with handler._pg_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name)
                )
            )
            db_total = cur.fetchone()[0]

    if db_total != total_rows:
        logger.warning(
            f"[{job_id[:8]}] Row count discrepancy: "
            f"chunk sum={total_rows}, table COUNT(*)={db_total}"
        )
        # Use DB truth
        total_rows = db_total
except Exception as count_err:
    logger.warning(f"[{job_id[:8]}] Could not verify table row count: {count_err}")
```

**Step 2: Use verified count in metadata registration**

In the `register_table_metadata()` call (~line 565-584), pass `total_rows` instead of `len(gdf)`:

```python
# OLD:
handler.register_table_metadata(..., feature_count=len(gdf), ...)

# NEW:
handler.register_table_metadata(..., feature_count=total_rows, ...)
```

Note: This requires reordering — metadata registration currently happens before chunk upload (Phase 2.5 area). If it can't be moved, update it after upload with a second call or UPDATE query.

**Step 3: Commit**
```
fix: Cross-check table row count and use DB truth for metadata [G1]
```

---

## Task 4: TiPG Feature Probe (G3)

**Files:**
- Modify: `services/handler_vector_docker_complete.py:237-288` (Phase 4)
- Modify: `infrastructure/service_layer_client.py` (add method)

**Step 1: Add `probe_collection()` to ServiceLayerClient**

```python
def probe_collection(self, collection_id: str, limit: int = 1) -> dict:
    """
    Probe a TiPG collection to verify it is servable.

    GET /collections/{collection_id}/items?limit=1

    Returns:
        dict with 'number_matched' (total features TiPG can serve),
        'number_returned' (features in this response), 'servable' (bool).

    Raises:
        httpx.HTTPStatusError: If the collection is not found or query fails.
    """
    url = f"{self._base_url}/collections/{collection_id}/items?limit={limit}"
    headers = self._get_auth_headers()

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        number_matched = data.get('numberMatched', 0)
        number_returned = data.get('numberReturned', 0)

        return {
            'number_matched': number_matched,
            'number_returned': number_returned,
            'servable': number_returned > 0
        }
```

**Step 2: Call probe after TiPG refresh in Phase 4**

After the existing TiPG refresh block (line 288), add:

```python
# Probe TiPG to verify collection is servable
try:
    probe = sl_client.probe_collection(tipg_collection_id)
    tipg_refresh_data['probe'] = probe

    if probe['number_matched'] == 0:
        logger.warning(
            f"[{job_id[:8]}] TiPG probe: {tipg_collection_id} has 0 features "
            f"(expected {total_rows}). Data may not be servable."
        )
    elif probe['number_matched'] != total_rows:
        logger.warning(
            f"[{job_id[:8]}] TiPG probe: {tipg_collection_id} reports "
            f"{probe['number_matched']} features, ETL inserted {total_rows}"
        )
    else:
        logger.info(
            f"[{job_id[:8]}] TiPG probe: {tipg_collection_id} confirmed "
            f"{probe['number_matched']} features servable"
        )
except Exception as probe_err:
    logger.warning(
        f"[{job_id[:8]}] TiPG probe failed (non-fatal): {probe_err}"
    )
    tipg_refresh_data['probe'] = {'status': 'failed', 'error': str(probe_err)}
```

**Important:** The probe is non-fatal. TiPG may not be reachable from Docker worker, or may need time to index. The row count guard (Task 2) is the hard gate.

**Step 3: Commit**
```
feat: Add TiPG feature probe to verify collection is servable [G3]
```

---

## Task 5: Investigate & Fix TiPG PostgresSyntaxError

**Files:**
- Modify: `services/vector/postgis_handler.py:580-589` (column cleaning)
- Create: `services/vector/column_sanitizer.py` (or add to existing)

**Step 1: Identify the root cause**

Query Application Insights for recent PostgresSyntaxError occurrences:

```bash
# Get recent TiPG-related errors
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where message contains 'PostgresSyntaxError' or message contains 'syntax error' | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
```

Also check TiPG logs (if accessible via rmhtitiler App Insights) for the exact SQL that fails.

**Step 2: Check if column names are the cause**

TiPG uses `pg_catalog` / `information_schema` to discover tables, then generates its own SQL to query them. If a column is named `order`, `type`, `date`, `group`, `level`, `name`, or `user`, TiPG's generated SQL may not quote the identifier.

Query to find tables with reserved-word columns:
```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'geo'
  AND column_name IN (
    'order', 'group', 'select', 'table', 'type', 'date', 'time',
    'user', 'level', 'name', 'desc', 'key', 'value', 'check',
    'index', 'comment', 'primary', 'foreign', 'references',
    'constraint', 'default', 'null', 'not', 'and', 'or',
    'natural', 'cross', 'inner', 'outer', 'left', 'right',
    'full', 'on', 'using', 'where', 'having', 'limit', 'offset',
    'union', 'except', 'intersect', 'all', 'any', 'some',
    'between', 'like', 'in', 'is', 'exists', 'case', 'when',
    'then', 'else', 'end', 'as', 'from', 'into', 'set',
    'update', 'delete', 'insert', 'create', 'drop', 'alter',
    'grant', 'revoke', 'begin', 'commit', 'rollback',
    'do', 'for', 'to', 'with', 'by', 'asc', 'cast',
    'abort', 'access', 'action', 'add', 'column', 'position',
    'range', 'result', 'row', 'rows', 'zone'
  )
ORDER BY table_name, column_name;
```

**Step 3: Harden column name cleaning**

Consolidate the two cleaning functions into one canonical sanitizer. The basic cleaner (line 580-589) misses:
- Column names starting with digits (no `col_` prefix)
- Non-ASCII characters
- PostgreSQL reserved words (should be prefixed or renamed)

```python
# services/vector/column_sanitizer.py
import re

# PostgreSQL reserved words most commonly found in geodata column names
# Full list: https://www.postgresql.org/docs/current/sql-keywords-appendix.html
PG_RESERVED_WORDS = frozenset({
    'order', 'group', 'select', 'table', 'type', 'date', 'time',
    'user', 'level', 'name', 'desc', 'key', 'value', 'check',
    'index', 'comment', 'primary', 'constraint', 'default', 'null',
    'natural', 'cross', 'inner', 'outer', 'left', 'right', 'full',
    'on', 'where', 'having', 'limit', 'offset', 'all', 'any',
    'between', 'like', 'in', 'is', 'exists', 'case', 'when',
    'then', 'else', 'end', 'as', 'from', 'into', 'set',
    'column', 'position', 'range', 'result', 'row', 'rows', 'zone',
    'do', 'for', 'to', 'with', 'by', 'asc', 'cast', 'action',
    'abort', 'access', 'add', 'grant', 'revoke',
})


def sanitize_column_name(name: str) -> str:
    """
    Sanitize a column name for safe use in PostGIS AND TiPG.

    Rules:
    1. Lowercase
    2. Replace non-alphanumeric with underscore
    3. Collapse multiple underscores
    4. Prefix numeric-leading names with 'col_'
    5. Prefix PostgreSQL reserved words with 'f_' (field)
    6. Fallback to 'unnamed_column' for empty result

    Why prefix reserved words instead of relying on quoting:
    - Our INSERT/CREATE uses sql.Identifier() (safe)
    - But TiPG generates its own SQL from information_schema
    - TiPG may NOT quote column names → PostgresSyntaxError
    - Prefixing avoids the problem at source
    """
    cleaned = name.lower()
    cleaned = re.sub(r'[^a-z0-9_]', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')

    if not cleaned:
        return 'unnamed_column'

    if cleaned[0].isdigit():
        cleaned = 'col_' + cleaned

    if cleaned in PG_RESERVED_WORDS:
        cleaned = 'f_' + cleaned

    return cleaned
```

**Step 4: Replace both column cleaning call sites**

In `prepare_gdf()` (line 580-589), replace the inline list comprehension:
```python
# OLD (line 580-589):
gdf.columns = [
    col.lower().replace(' ', '_').replace('-', '_')...
    for col in gdf.columns
]

# NEW:
from services.vector.column_sanitizer import sanitize_column_name
gdf.columns = [
    sanitize_column_name(col) if col != 'geometry' else col
    for col in gdf.columns
]
```

In the `clean_col` function (line 1274-1281), replace with import:
```python
# OLD (line 1274-1281):
def clean_col(name): ...

# NEW:
from services.vector.column_sanitizer import sanitize_column_name as clean_col
```

**Step 5: Commit**
```
fix: Canonical column sanitizer with reserved word prefixing for TiPG compat [PostgresSyntaxError]
```

---

## Task 6: Add TiPG Error to ERRORS_AND_FIXES.md

**Files:**
- Modify: `docs_claude/ERRORS_AND_FIXES.md`

**Step 1: Document the error**

Add under Database Errors section:

```markdown
### DB-0XX: TiPG PostgresSyntaxError on Vector Collections

**Error**: `PostgresSyntaxError` when TiPG tries to serve a vector collection
**Symptoms**: Collection visible in TiPG catalog but returns 500 error on feature queries
**Root Cause**: Source data column names contained PostgreSQL reserved words (e.g., `type`, `order`, `name`, `date`, `group`). Our ETL quotes identifiers via `sql.Identifier()`, but TiPG generates its own SQL from `information_schema` and may not quote all column names.
**Fix**: Column sanitizer (`services/vector/column_sanitizer.py`) now prefixes reserved words with `f_` (e.g., `type` → `f_type`)
**Prevention**: All vector ETL paths use `sanitize_column_name()` before table creation
**Related**: Task 5 of vector-etl-validation plan (24 FEB 2026)
```

**Step 2: Commit**
```
docs: Document TiPG PostgresSyntaxError cause and fix [DB-0XX]
```

---

## Task Order & Dependencies

```
Task 1 (row count verification)     ← independent
Task 2 (zero-row guard)             ← independent
Task 3 (full table cross-check)     ← after Task 1
Task 4 (TiPG probe)                 ← independent
Task 5 (column sanitizer)           ← independent
Task 6 (documentation)              ← after Task 5
```

Tasks 1, 2, 4, 5 can be done in parallel. Task 3 depends on Task 1. Task 6 depends on Task 5.

---

## Coverage Summary

| Gap | Task | Type | Effort |
|-----|------|------|--------|
| G1: Row count not verified | Task 1 + Task 3 | Bug fix | Small |
| G2: Success with 0 rows | Task 2 | Bug fix | Trivial |
| G3: No TiPG end-to-end check | Task 4 | Enhancement | Small |
| PostgresSyntaxError | Task 5 | Bug fix | Medium |
| Documentation | Task 6 | Docs | Trivial |
