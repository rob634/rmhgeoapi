# Vector ETL Connection Reuse Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate per-chunk connection churn in the Docker vector ETL pipeline — use one database connection for the entire upload workflow instead of opening/closing a new TCP connection for every chunk.

**Architecture:** Thread a single connection from `_process_single_table()` down through table creation, chunk uploads, deferred indexes, ANALYZE, split views, and post-upload validation. The connection is opened once, commits after each logical operation (preserving per-chunk idempotency), and closes when the workflow completes or fails. No pool needed — this is a single sequential writer.

**Tech Stack:** psycopg3, contextmanager, existing `PostgreSQLRepository._get_connection()`

---

## Problem Statement

A 2M-row vector upload at 100K chunk_size opens **~30 separate TCP connections**:
- 1 for `create_table_with_batch_tracking`
- 1 for `register_table_metadata`
- 20 for `insert_chunk_idempotent` (one per chunk)
- 1 for `create_deferred_indexes`
- 1 for `analyze_table`
- 1 for split view operations
- 2+ for post-upload row count verification
- 1 for table_group catalog update

Each connection creates a `pg_temp_N` schema in PostgreSQL that persists until server restart. Two 2M-row jobs = 400+ zombie temp schemas → OOM on a 4GB Standard_B2s instance.

## Design Principles

1. **One connection per `_process_single_table()` invocation** — opened at entry, closed at exit
2. **Commit per logical operation** — preserves existing idempotency (batch_id DELETE+INSERT per chunk)
3. **Connection failure = task failure** — no reconnect logic in the upload loop. The existing task retry mechanism handles this
4. **`conn` parameter is optional** — methods that accept `conn=None` fall back to opening their own connection (backward compatibility for any callers outside the Docker ETL path)
5. **No pool for this path** — pool overhead is pointless for a single sequential writer

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `services/vector/postgis_handler.py` | Modify | Add `conn` parameter to 7 methods |
| `services/handler_vector_docker_complete.py` | Modify | Thread connection through `_process_single_table` |
| `tests/unit/test_connection_reuse.py` | Create | Verify single-connection behavior |

## Connection Flow (After)

```
_process_single_table()
  └── opens ONE connection via _pg_repo._get_connection()
       ├── create_table_with_batch_tracking(conn=conn)  → commit
       ├── register_table_metadata(conn=conn)            → commit
       ├── table_group catalog UPDATE                    → commit
       ├── _upload_chunks_with_checkpoints(conn=conn)
       │    ├── chunk 0: DELETE+INSERT → commit
       │    ├── chunk 1: DELETE+INSERT → commit
       │    └── chunk N: DELETE+INSERT → commit
       ├── create_deferred_indexes(conn=conn)            → commit
       ├── analyze_table(conn=conn)                      → commit
       ├── split views (conn=conn)                       → commit
       └── row count verification (conn=conn)            → (read-only)
```

---

## Chunk 1: Add `conn` Parameter to PostGIS Handler Methods

### Task 1: Add `conn` parameter to `insert_chunk_idempotent`

This is the highest-impact method — called once per chunk (20x for a 2M row job).

**Files:**
- Modify: `services/vector/postgis_handler.py:1664-1780`
- Create: `tests/unit/test_connection_reuse.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_connection_reuse.py
"""
Tests for connection reuse in VectorToPostGISHandler.

Verifies that when a connection is passed in, methods use it
instead of opening a new one.
"""
import pytest
from unittest.mock import MagicMock, patch, call


class TestInsertChunkIdempotentConnReuse:
    """insert_chunk_idempotent should use passed connection, not open new one."""

    @patch('services.vector.postgis_handler.VectorToPostGISHandler._insert_features_with_batch')
    def test_uses_provided_connection(self, mock_insert):
        """When conn is passed, _get_connection should NOT be called."""
        from services.vector.postgis_handler import VectorToPostGISHandler
        import geopandas as gpd
        from shapely.geometry import Point

        handler = VectorToPostGISHandler.__new__(VectorToPostGISHandler)
        handler._pg_repo = MagicMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.rowcount = 0
        mock_cursor.fetchone.return_value = {'count': 5}

        # Call with conn= parameter
        handler.insert_chunk_idempotent(
            chunk=gpd.GeoDataFrame({'geometry': [Point(0, 0)]}, crs="EPSG:4326"),
            table_name="test",
            schema="geo",
            batch_id="test-chunk-0",
            conn=mock_conn
        )

        # _get_connection should NOT have been called
        handler._pg_repo._get_connection.assert_not_called()

    def test_opens_own_connection_when_none(self):
        """When conn=None (default), opens own connection (backward compat)."""
        from services.vector.postgis_handler import VectorToPostGISHandler

        handler = VectorToPostGISHandler.__new__(VectorToPostGISHandler)
        handler._pg_repo = MagicMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        handler._pg_repo._get_connection.return_value.__enter__ = lambda s: mock_conn
        handler._pg_repo._get_connection.return_value.__exit__ = MagicMock(return_value=False)

        handler.insert_chunk_idempotent(
            chunk=MagicMock(),
            table_name="test",
            schema="geo",
            batch_id="test-chunk-0",
            # conn not passed — should open own
        )

        handler._pg_repo._get_connection.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_connection_reuse.py -v 2>&1 | head -30`
Expected: FAIL — `insert_chunk_idempotent` doesn't accept `conn` parameter yet

- [ ] **Step 3: Implement — add `conn` parameter to `insert_chunk_idempotent`**

In `services/vector/postgis_handler.py`, modify `insert_chunk_idempotent` (line 1664):

```python
def insert_chunk_idempotent(
    self,
    chunk: gpd.GeoDataFrame,
    table_name: str,
    schema: str,
    batch_id: str,
    conn=None            # <-- NEW: optional connection reuse
) -> Dict[str, int]:
    """..."""
    rows_deleted = 0
    rows_inserted = 0

    # Use provided connection or open a new one
    if conn is not None:
        # Caller owns the connection lifecycle
        self._do_idempotent_insert(conn, chunk, table_name, schema, batch_id)
    else:
        # Backward compatibility: open/close our own
        with self._pg_repo._get_connection() as conn:
            self._do_idempotent_insert(conn, chunk, table_name, schema, batch_id)
```

**IMPORTANT — Pattern for all 7 methods:**

The cleanest pattern to avoid duplicating the method body is a private helper that takes `conn` as required, and a public method that handles the "open or reuse" decision:

```python
from contextlib import contextmanager, nullcontext

def insert_chunk_idempotent(
    self,
    chunk: gpd.GeoDataFrame,
    table_name: str,
    schema: str,
    batch_id: str,
    conn=None
) -> Dict[str, int]:
    rows_deleted = 0
    rows_inserted = 0

    ctx = nullcontext(conn) if conn is not None else self._pg_repo._get_connection()
    with ctx as c:
        with c.cursor() as cur:
            # ... existing DELETE+INSERT logic unchanged ...
            # Replace all `conn.commit()` references with `c.commit()`

        c.commit()

    return {'rows_deleted': rows_deleted, 'rows_inserted': rows_inserted}
```

The `nullcontext(conn)` pattern is the key: when `conn` is provided, `nullcontext` yields it without opening/closing anything. When `conn is None`, `_get_connection()` opens a fresh connection and closes it on exit. **Zero code duplication.**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_connection_reuse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/vector/postgis_handler.py tests/unit/test_connection_reuse.py
git commit -m "feat: add conn parameter to insert_chunk_idempotent (connection reuse)"
```

---

### Task 2: Add `conn` parameter to remaining PostGIS handler methods

Apply the same `nullcontext` pattern to the other 6 methods that open their own connections.

**Files:**
- Modify: `services/vector/postgis_handler.py`

**Methods to modify (all use the same pattern):**

| Method | Line | Called by |
|--------|------|-----------|
| `create_table_with_batch_tracking` | 1538 | `_create_table_and_metadata` |
| `register_table_metadata` | 1880 | `_create_table_and_metadata` |
| `create_deferred_indexes` | 1802 | `_process_single_table` |
| `analyze_table` | 1786 | `_process_single_table` |
| `upload_chunk_with_metadata` | 1450 | (not in Docker path but include for consistency) |
| `create_table_only` | 917 | (not in Docker path but include for consistency) |

**Do NOT modify these** (different calling patterns, outside Docker ETL scope):
- `_insert_features` — already takes a cursor, no connection management
- `upload_chunk` — legacy Function App path, keep as-is
- `insert_features_only` — legacy Function App path, keep as-is
- `subdivide_complex_geometries` — complex swap-and-replace logic, separate concern

- [ ] **Step 1: Add `conn=None` + `nullcontext` pattern to each method**

For each method, the change is mechanical:

```python
# BEFORE (example: analyze_table)
def analyze_table(self, table_name: str, schema: str = "geo") -> None:
    with self._pg_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(...)
            conn.commit()

# AFTER
def analyze_table(self, table_name: str, schema: str = "geo", conn=None) -> None:
    from contextlib import nullcontext
    ctx = nullcontext(conn) if conn is not None else self._pg_repo._get_connection()
    with ctx as c:
        with c.cursor() as cur:
            cur.execute(...)
            c.commit()
```

Apply to all 6 methods. Import `nullcontext` once at file top (`from contextlib import nullcontext` — available in Python 3.7+).

- [ ] **Step 2: Add tests for two representative methods**

Add to `tests/unit/test_connection_reuse.py`:

```python
class TestAnalyzeTableConnReuse:
    def test_uses_provided_connection(self):
        from services.vector.postgis_handler import VectorToPostGISHandler
        handler = VectorToPostGISHandler.__new__(VectorToPostGISHandler)
        handler._pg_repo = MagicMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        handler.analyze_table("test_table", "geo", conn=mock_conn)

        handler._pg_repo._get_connection.assert_not_called()


class TestCreateDeferredIndexesConnReuse:
    def test_uses_provided_connection(self):
        from services.vector.postgis_handler import VectorToPostGISHandler
        import geopandas as gpd
        from shapely.geometry import Point

        handler = VectorToPostGISHandler.__new__(VectorToPostGISHandler)
        handler._pg_repo = MagicMock()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        gdf = gpd.GeoDataFrame({'col1': [1], 'geometry': [Point(0, 0)]}, crs="EPSG:4326")
        handler.create_deferred_indexes("test", "geo", gdf, conn=mock_conn)

        handler._pg_repo._get_connection.assert_not_called()
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_connection_reuse.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add services/vector/postgis_handler.py tests/unit/test_connection_reuse.py
git commit -m "feat: add conn parameter to 6 remaining postgis handler methods"
```

---

## Chunk 2: Thread Connection Through Docker ETL Workflow

### Task 3: Modify `_upload_chunks_with_checkpoints` to accept and use a connection

This is the hot loop — currently opens 20 connections for a 2M row job.

**Files:**
- Modify: `services/handler_vector_docker_complete.py:748-830`

- [ ] **Step 1: Add `conn` parameter and pass to `insert_chunk_idempotent`**

```python
def _upload_chunks_with_checkpoints(
    gdf,
    table_name: str,
    schema: str,
    chunk_size: int,
    job_id: str,
    checkpoint_fn,
    conn=None          # <-- NEW
) -> Dict[str, Any]:
    """..."""
    import time
    from services.vector.postgis_handler import VectorToPostGISHandler

    handler = VectorToPostGISHandler()
    # ... existing setup code ...

    for i in range(num_chunks):
        # ... existing chunk slicing ...

        # DELETE + INSERT in single transaction
        result = handler.insert_chunk_idempotent(
            chunk=chunk,
            table_name=table_name,
            schema=schema,
            batch_id=batch_id,
            conn=conn           # <-- PASS THROUGH
        )

        # ... existing checkpoint/logging ...
```

- [ ] **Step 2: Verify no other connection-opening code in this function**

The function creates `VectorToPostGISHandler()` at line 767 but only uses it to call `insert_chunk_idempotent`. The handler's `__init__` creates a `PostgreSQLRepository` (which builds a connection string) but does NOT open a connection. This is fine — the conn_string is only used if `conn=None` falls through.

- [ ] **Step 3: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "feat: thread conn through _upload_chunks_with_checkpoints"
```

---

### Task 4: Modify `_create_table_and_metadata` to accept and use a connection

**Files:**
- Modify: `services/handler_vector_docker_complete.py:605-700`

- [ ] **Step 1: Add `conn` parameter, pass to handler methods**

```python
def _create_table_and_metadata(
    gdf,
    table_name: str,
    schema: str,
    overwrite: bool,
    parameters: Dict[str, Any],
    load_info: Dict[str, Any],
    job_id: str,
    conn=None          # <-- NEW
) -> Dict[str, Any]:
    """..."""
    # ... existing setup ...

    handler.create_table_with_batch_tracking(
        table_name=table_name,
        schema=schema,
        gdf=gdf,
        indexes=indexes,
        overwrite=overwrite,
        conn=conn           # <-- PASS THROUGH
    )

    # ... vector tile URL generation (no DB) ...

    handler.register_table_metadata(
        # ... existing params ...
        conn=conn           # <-- PASS THROUGH (add as last kwarg)
    )
```

- [ ] **Step 2: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "feat: thread conn through _create_table_and_metadata"
```

---

### Task 5: Modify `_process_single_table` to own the connection

This is the orchestration point — opens ONE connection and passes it everywhere.

**Files:**
- Modify: `services/handler_vector_docker_complete.py:884-1100`

- [ ] **Step 1: Wrap the entire method body in a single `_get_connection()` context**

```python
def _process_single_table(
    gdf,
    table_name: str,
    schema: str,
    overwrite: bool,
    parameters: Dict[str, Any],
    load_info: Dict[str, Any],
    job_id: str,
    chunk_size: int,
    checkpoint_fn: callable,
    table_group: Optional[str] = None,
) -> Dict[str, Any]:
    from services.vector.postgis_handler import VectorToPostGISHandler

    logger.info(f"[{job_id[:8]}] Processing table: {schema}.{table_name} ({len(gdf)} features)")

    # === ONE CONNECTION FOR THE ENTIRE TABLE PROCESSING ===
    _handler = VectorToPostGISHandler()
    with _handler._pg_repo._get_connection() as conn:

        # Phase 2: Create table and metadata
        table_result = _create_table_and_metadata(
            gdf=gdf, table_name=table_name, schema=schema,
            overwrite=overwrite, parameters=parameters,
            load_info=load_info, job_id=job_id,
            conn=conn
        )

        # Set table_group in catalog if geometry split
        if table_group:
            try:
                from psycopg import sql as psql
                with conn.cursor() as cur:
                    cur.execute(
                        psql.SQL(
                            "UPDATE {schema}.table_catalog SET table_group = %s "
                            "WHERE table_name = %s"
                        ).format(schema=psql.Identifier("geo")),
                        (table_group, table_name)
                    )
                    conn.commit()
                logger.info(f"[{job_id[:8]}] Set table_group='{table_group}' for {table_name}")
            except Exception as e:
                logger.warning(f"[{job_id[:8]}] Failed to set table_group (non-fatal): {e}")

        checkpoint_fn(f"table_created_{table_name}", {
            "table": f"{schema}.{table_name}",
            "geometry_type": table_result['geometry_type'],
            "srid": table_result['srid']
        })

        # Phase 2.5: Create default style (no DB — writes to blob storage)
        style_result = _create_default_style(
            table_name=table_name,
            geometry_type=table_result['geometry_type'],
            style_params=parameters.get('style'),
            job_id=job_id
        )

        # Phase 3: Upload chunks (ALL use same connection)
        upload_result = _upload_chunks_with_checkpoints(
            gdf=gdf, table_name=table_name, schema=schema,
            chunk_size=chunk_size, job_id=job_id,
            checkpoint_fn=checkpoint_fn,
            conn=conn
        )

        # Phase 3.5: Deferred indexes + ANALYZE
        indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})
        _handler.create_deferred_indexes(
            table_name=table_name, schema=schema,
            gdf=gdf, indexes=indexes,
            conn=conn
        )
        _handler.analyze_table(table_name, schema, conn=conn)

        # Phase 3.7: Split views (if split_column specified)
        split_column = parameters.get('split_column')
        split_views_result = None

        if split_column:
            # ... existing split view logic ...
            # ALREADY uses a single conn block — just pass our conn instead
            # of opening _post_handler._pg_repo._get_connection()
            from services.vector.view_splitter import (
                validate_split_column, discover_split_values,
                create_split_views, register_split_views,
                cleanup_split_view_metadata,
            )
            from services.vector.column_sanitizer import sanitize_column_name as _sanitize_col

            split_column_sanitized = _sanitize_col(split_column)
            col_info = validate_split_column(conn, table_name, schema, split_column_sanitized)
            values = discover_split_values(conn, table_name, schema, split_column_sanitized)
            cleanup_split_view_metadata(conn, table_name)
            views = create_split_views(conn, table_name, schema, split_column_sanitized, values)
            registered = register_split_views(
                conn=conn, views=views, base_table_name=table_name,
                schema=schema, split_column=split_column_sanitized,
                base_title=parameters.get('title'),
                geometry_type=table_result['geometry_type'],
                srid=table_result.get('srid', 4326),
            )
            conn.commit()

            split_views_result = { ... }  # existing dict
            checkpoint_fn("split_views_created", split_views_result)

        # Phase 4: Row count verification
        from psycopg import sql as psql
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                    schema=psql.Identifier(schema),
                    table=psql.Identifier(table_name)
                )
            )
            total_rows = cur.fetchone()['count']

    # === CONNECTION CLOSED HERE ===

    # ... existing return dict assembly (no DB needed) ...
```

**CRITICAL SAFEGUARD — commit discipline:**
Every logical operation commits before proceeding. If the connection dies mid-chunk-5:
- Chunks 1-4 are committed and durable
- Chunk 5's transaction rolls back automatically (psycopg3 behavior)
- Task fails, retry creates a fresh connection, batch_id idempotency handles everything

- [ ] **Step 2: Verify `_create_default_style` does NOT use the database**

Check that style creation writes to blob storage, not PostGIS. If it does use DB, pass `conn` through.

Run: `grep -n '_get_connection' services/vector/style_manager.py` (or wherever styles are created)

- [ ] **Step 3: Count connections — should be exactly 1**

Add a temporary debug log at the top of `_process_single_table`:
```python
logger.info(f"[{job_id[:8]}] CONN_REUSE: Opening single connection for entire table processing")
```

And in `_upload_chunks_with_checkpoints`, add:
```python
if conn is not None:
    logger.info(f"[{job_id[:8]}] CONN_REUSE: Reusing connection for {num_chunks} chunks")
```

- [ ] **Step 4: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "feat: single connection for entire _process_single_table workflow"
```

---

### Task 6: Update `_process_single_table` post-upload verification

The existing post-upload row count check at lines 1073-1098 opens TWO more connections. Fold these into the main connection block.

**Files:**
- Modify: `services/handler_vector_docker_complete.py:1059-1110`

- [ ] **Step 1: Move row count verification inside the `with conn` block**

Already handled in Task 5's restructuring — the row count query uses the same `conn`. Remove the standalone `_post_handler._pg_repo._get_connection()` calls at lines 1076 and 1098.

- [ ] **Step 2: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "fix: eliminate extra connections for post-upload row verification"
```

---

### Task 7: Run full test suite and verify

- [ ] **Step 1: Run all unit tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify import works**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.handler_vector_docker_complete import vector_docker_complete; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify nullcontext import**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from contextlib import nullcontext; print('Available in Python 3.7+')"`
Expected: `Available in Python 3.7+`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: vector ETL connection reuse — 30 connections → 1 per table upload

Eliminates per-chunk TCP connection churn that caused 400+ pg_temp schemas
and OOM on Standard_B2s (4GB) PostgreSQL instance.

Before: 2M rows at 100K chunks = ~30 separate connections per job
After:  1 connection per _process_single_table() invocation

Idempotency preserved: per-chunk commit with batch_id DELETE+INSERT."
```

---

## Safeguards & Failure Modes

| Scenario | Behavior | Why it's safe |
|----------|----------|---------------|
| Network drops mid-chunk-5 | Connection dies, uncommitted chunk rolls back, task fails | Chunks 1-4 committed. Retry via batch_id handles all |
| Connection timeout (idle) | psycopg3 detects stale conn on next use, raises error | Task fails, retry gets fresh connection |
| OOM during large chunk | OS kills process | Docker restarts container, retry works |
| `register_table_metadata` fails | Rolls back to last commit (table created) | Retry re-runs from start with overwrite=true |
| Split view creation fails | Rolls back split view transaction | Base table + data intact, split can be retried |
| Caller outside Docker path | `conn=None` default → opens own connection | Zero breaking changes to Function App path |

## What This Does NOT Change

- **Function App path**: `upload_chunk()`, `insert_features_only()`, `create_table_only()` keep their existing single-use connection behavior when called without `conn`
- **Connection pool**: `ConnectionPoolManager` remains unchanged — it's used by the broader app (API endpoints, health checks), not by the ETL writer
- **H3 repository**: Already uses `ON COMMIT DROP` temp tables within single connections — different pattern, not affected
- **Multi-source handler**: Calls `_process_single_table` — gets connection reuse for free
