# ============================================================================
# CLAUDE CONTEXT - VECTOR CREATE AND LOAD TABLES ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Create PostGIS tables and load GeoParquet data
# PURPOSE: For each geometry group, create a PostGIS table with batch tracking,
#          insert data in idempotent chunks (DELETE+INSERT by batch_id), build
#          deferred indexes, run ANALYZE, and verify row counts.
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_create_and_load_tables
# DEPENDENCIES: services.vector.postgis_handler, services.vector.view_splitter,
#               infrastructure.db_connections, psycopg, geopandas, pandas
# ============================================================================
"""
Vector Create and Load Tables - atomic handler for DAG workflows.

Receives geometry_groups from vector_validate_and_clean (list of GeoParquet
files, one per geometry type). For each group, creates a PostGIS table and
loads all data via idempotent per-chunk DELETE+INSERT.

Key design points:
- ONE database connection for the entire handler (DDL + all chunks + indexes
  + ANALYZE + verification), closed at end.
- PER-CHUNK commit: conn.commit() after each chunk's DELETE+INSERT. This is
  load-bearing for retry safety (committed chunks survive partial failure).
- NaT-to-None in value loop: secondary defense against year-48113 corruption.
- Deferred indexes: spatial/attribute/temporal indexes created AFTER all data
  is loaded (5-10x faster than incremental). etl_batch_id index is NOT
  deferred -- created with the table.
- Geometry type mapping: "polygon" -> MULTIPOLYGON, "line" -> MULTILINESTRING,
  "point" -> MULTIPOINT.
- Table naming: {table_name}_{geometry_type} when split (>1 group), plain
  {table_name} when single group.

Extracted from: handler_vector_docker_complete._process_single_table()
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Geometry type mapping: geometry_groups entry "geometry_type" -> PostGIS type
_GEOM_TYPE_MAP: Dict[str, str] = {
    "polygon": "MULTIPOLYGON",
    "line": "MULTILINESTRING",
    "point": "MULTIPOINT",
}

# Reserved columns -- must match handler 2's list (CR-6)
_RESERVED_COLS = frozenset({"id", "geom", "geometry", "etl_batch_id"})

# SQL injection guard: reject table/schema names with these characters
_SQL_INJECTION_PATTERN = re.compile(r"[;'\"\-]{1}|--")

# Default chunk size (Docker default -- NOT Function App 1000-5000 default)
_DEFAULT_CHUNK_SIZE = 100_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_sql_injection(name: str, label: str) -> Optional[str]:
    """
    Return an error string if `name` contains SQL-injection characters,
    None if clean.
    """
    if _SQL_INJECTION_PATTERN.search(name):
        return (
            f"{label} '{name}' contains invalid characters (;, --, ', \"). "
            "SQL injection guard rejected the value."
        )
    return None


def _validate_params(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate required parameters. Returns error dict on failure, None on success.
    """
    table_name = params.get("table_name")
    if not table_name:
        return {"success": False, "error": "table_name is required", "error_type": "ValidationError"}

    err = _check_sql_injection(table_name, "table_name")
    if err:
        return {"success": False, "error": err, "error_type": "ValidationError"}

    schema_name = params.get("schema_name", "geo")
    err = _check_sql_injection(schema_name, "schema_name")
    if err:
        return {"success": False, "error": err, "error_type": "ValidationError"}

    job_id = params.get("job_id")
    if not job_id:
        return {"success": False, "error": "job_id is required", "error_type": "ValidationError"}

    geometry_groups = params.get("geometry_groups")
    if not geometry_groups:
        return {
            "success": False,
            "error": "geometry_groups is required and must be a non-empty list",
            "error_type": "ValidationError",
        }

    for i, entry in enumerate(geometry_groups):
        for field in ("geometry_type", "row_count", "parquet_path"):
            if field not in entry:
                return {
                    "success": False,
                    "error": f"geometry_groups[{i}] missing required field '{field}'",
                    "error_type": "ValidationError",
                }
        if entry["geometry_type"] not in _GEOM_TYPE_MAP:
            return {
                "success": False,
                "error": (
                    f"geometry_groups[{i}].geometry_type '{entry['geometry_type']}' is not valid. "
                    f"Expected one of: {sorted(_GEOM_TYPE_MAP)}"
                ),
                "error_type": "ValidationError",
            }

    return None


def _build_table_name(base: str, geometry_type: str, is_split: bool) -> str:
    """Return the final PostGIS table name for this geometry group."""
    if is_split:
        return f"{base}_{geometry_type}"
    return base


def _log_progress(
    job_id: str,
    table_name: str,
    chunks_done: int,
    total_chunks: int,
    rows_done: int,
    total_rows: int,
    start_time: float,
) -> None:
    """Log progress at 25/50/75/100% milestones (rows/sec included)."""
    if total_chunks == 0:
        return
    pct = int(chunks_done / total_chunks * 100)
    # Only fire at milestone boundaries
    milestones = (25, 50, 75, 100)
    prev_pct = int((chunks_done - 1) / total_chunks * 100) if chunks_done > 1 else 0
    for milestone in milestones:
        if prev_pct < milestone <= pct:
            elapsed = time.time() - start_time
            rate = rows_done / elapsed if elapsed > 0 else 0
            logger.info(
                f"[{job_id[:8]}] {table_name} progress: {milestone}% "
                f"({rows_done:,}/{total_rows:,} rows, "
                f"{elapsed:.1f}s elapsed, {rate:.0f} rows/sec)"
            )


# ---------------------------------------------------------------------------
# Per-table processing
# ---------------------------------------------------------------------------

def _process_one_table(
    *,
    group: Dict[str, Any],
    actual_table_name: str,
    schema_name: str,
    job_id: str,
    overwrite: bool,
    chunk_size: int,
    indexes: Dict[str, Any],
    is_split: bool,
    geometry_type: str,
    warnings: List[str],
) -> Dict[str, Any]:
    """
    Full per-table lifecycle on a single shared connection:
      1. Read GeoParquet
      2. Existence check + optional overwrite
      3. CREATE TABLE with etl_batch_id (and its index)
      4. INSERT all chunks with per-chunk commit and NaT-to-None
      5. Deferred indexes (GIST, BTREE, temporal)
      6. ANALYZE
      7. Zero-row check + SELECT COUNT(*) cross-check
      8. Compute bbox from GeoDataFrame

    Returns a table result dict on success. Raises on failure.
    """
    import pandas as pd
    import geopandas as gpd
    from psycopg import sql as psql
    from services.vector.postgis_handler import VectorToPostGISHandler

    parquet_path = group["parquet_path"]
    expected_rows = group["row_count"]

    # --- 1. Read GeoParquet ---
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(
            f"GeoParquet file not found at '{parquet_path}' for geometry_type='{geometry_type}'"
        )

    logger.info(
        f"[{job_id[:8]}] Reading GeoParquet: {parquet_path} "
        f"(expected {expected_rows:,} rows, geometry_type={geometry_type})"
    )
    gdf = gpd.read_parquet(parquet_path)
    actual_row_count_in_file = len(gdf)
    logger.info(
        f"[{job_id[:8]}] Loaded {actual_row_count_in_file:,} rows from GeoParquet "
        f"for {schema_name}.{actual_table_name}"
    )

    # Collect attribute columns (excluding reserved and geometry sentinel)
    attr_cols = [
        col for col in gdf.columns
        if col != "geometry" and col.lower() not in _RESERVED_COLS
    ]
    column_count = len(attr_cols) + 1  # +1 for geom

    # Compute bbox from GDF (used in result; ANALYZE updates planner stats separately)
    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    bbox = [float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])]

    # --- 2-3. Table existence check, overwrite, CREATE TABLE ---
    handler = VectorToPostGISHandler()

    with handler._pg_repo._get_connection() as conn:
        conn_pid = conn.info.backend_pid
        logger.info(
            f"[{job_id[:8]}] Connection opened for {schema_name}.{actual_table_name} "
            f"pid={conn_pid}"
        )

        with conn.cursor() as cur:
            # Existence check
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (schema_name, actual_table_name),
            )
            table_exists = cur.fetchone()["exists"]

        if table_exists:
            if not overwrite:
                raise _TableExistsError(
                    f"Table {schema_name}.{actual_table_name} already exists. "
                    "Set overwrite=true to replace it."
                )
            # Overwrite path: cleanup split view metadata FIRST, then DROP CASCADE
            logger.info(
                f"[{job_id[:8]}] overwrite=true: cleaning split view metadata for "
                f"{actual_table_name} then DROP CASCADE"
            )
            try:
                from services.vector.view_splitter import cleanup_split_view_metadata
                cleanup_split_view_metadata(conn, actual_table_name)
                conn.commit()
            except Exception as cleanup_err:
                warn_msg = (
                    f"cleanup_split_view_metadata for {actual_table_name} failed "
                    f"(non-fatal, proceeding with DROP): {cleanup_err}"
                )
                logger.warning(f"[{job_id[:8]}] {warn_msg}")
                warnings.append(warn_msg)

            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "DROP TABLE IF EXISTS {schema}.{table} CASCADE"
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                    )
                )
            conn.commit()
            logger.info(
                f"[{job_id[:8]}] Dropped {schema_name}.{actual_table_name} CASCADE"
            )
            warnings.append(
                f"Existing table {schema_name}.{actual_table_name} dropped (overwrite=true)"
            )

        # CREATE TABLE with etl_batch_id + etl_batch_id index (NOT deferred)
        pg_geom_type = _GEOM_TYPE_MAP[geometry_type]

        # Build column definitions from GeoParquet, skipping reserved cols
        with conn.cursor() as cur:
            skipped_cols = []
            col_defs = []
            for col in gdf.columns:
                if col == "geometry":
                    continue
                if col.lower() in _RESERVED_COLS:
                    skipped_cols.append(col)
                    continue
                pg_type = handler._get_postgres_type(gdf[col].dtype)
                col_defs.append(
                    psql.Identifier(col) + psql.SQL(f" {pg_type}")
                )

            if skipped_cols:
                logger.warning(
                    f"[{job_id[:8]}] Skipped reserved columns from source data "
                    f"for {actual_table_name}: {skipped_cols}"
                )

            if col_defs:
                create_sql = psql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        id SERIAL PRIMARY KEY,
                        geom GEOMETRY({geom_type}, 4326),
                        etl_batch_id TEXT,
                        {columns}
                    )
                    """
                ).format(
                    schema=psql.Identifier(schema_name),
                    table=psql.Identifier(actual_table_name),
                    geom_type=psql.SQL(pg_geom_type),
                    columns=psql.SQL(", ").join(col_defs),
                )
            else:
                create_sql = psql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        id SERIAL PRIMARY KEY,
                        geom GEOMETRY({geom_type}, 4326),
                        etl_batch_id TEXT
                    )
                    """
                ).format(
                    schema=psql.Identifier(schema_name),
                    table=psql.Identifier(actual_table_name),
                    geom_type=psql.SQL(pg_geom_type),
                )

            cur.execute(create_sql)

            # etl_batch_id index -- NOT deferred (needed for DELETE in idempotent pattern)
            cur.execute(
                psql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {schema}.{table} (etl_batch_id)
                    """
                ).format(
                    idx_name=psql.Identifier(f"idx_{actual_table_name}_etl_batch_id"),
                    schema=psql.Identifier(schema_name),
                    table=psql.Identifier(actual_table_name),
                )
            )
            conn.commit()
            logger.info(
                f"[{job_id[:8]}] Created table {schema_name}.{actual_table_name} "
                f"(geom={pg_geom_type}, {len(col_defs)} attr cols, etl_batch_id index ready)"
            )

        # --- 4. INSERT all chunks with per-chunk commit + NaT-to-None ---
        total_rows = actual_row_count_in_file
        total_chunks = (total_rows + chunk_size - 1) // chunk_size if total_rows > 0 else 0
        rows_inserted_by_chunks = 0
        load_start = time.time()

        logger.info(
            f"[{job_id[:8]}] Starting chunk load: {total_rows:,} rows, "
            f"{total_chunks} chunks of {chunk_size:,}"
        )

        for i in range(total_chunks):
            chunk_start_row = i * chunk_size
            chunk_end_row = min(chunk_start_row + chunk_size, total_rows)
            chunk = gdf.iloc[chunk_start_row:chunk_end_row]
            batch_id = f"{job_id[:8]}-chunk-{i}"

            chunk_attr_cols = [
                col for col in chunk.columns
                if col != "geometry" and col.lower() not in _RESERVED_COLS
            ]

            logger.info(
                f"[{batch_id}] DELETE+INSERT: Starting idempotent upsert "
                f"for batch_id={batch_id} into {schema_name}.{actual_table_name}, "
                f"inserting {len(chunk)} rows"
            )

            with conn.cursor() as cur:
                # DELETE phase (idempotency -- removes prior partial attempt)
                cur.execute(
                    psql.SQL(
                        "DELETE FROM {schema}.{table} WHERE etl_batch_id = %s"
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                    ),
                    (batch_id,),
                )
                rows_deleted = cur.rowcount
                logger.info(
                    f"[{batch_id}] DELETE phase: removed {rows_deleted} existing rows "
                    f"from {schema_name}.{actual_table_name}"
                )

                # INSERT phase
                if chunk_attr_cols:
                    cols_sql = psql.SQL(", ").join(
                        [psql.Identifier(col) for col in chunk_attr_cols]
                    )
                    placeholders = psql.SQL(", ").join(
                        [psql.Placeholder()] * len(chunk_attr_cols)
                    )
                    insert_stmt = psql.SQL(
                        """
                        INSERT INTO {schema}.{table} (geom, etl_batch_id, {cols})
                        VALUES (ST_GeomFromWKB(%s, 4326), %s, {placeholders})
                        """
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                        cols=cols_sql,
                        placeholders=placeholders,
                    )
                else:
                    insert_stmt = psql.SQL(
                        """
                        INSERT INTO {schema}.{table} (geom, etl_batch_id)
                        VALUES (ST_GeomFromWKB(%s, 4326), %s)
                        """
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                    )

                # Build values with NaT-to-None conversion (S-1: secondary defense)
                all_values = []
                for _, row in chunk.iterrows():
                    geom_wkb = row.geometry.wkb
                    if chunk_attr_cols:
                        row_vals = tuple(
                            None if val is pd.NaT else val
                            for val in (row[col] for col in chunk_attr_cols)
                        )
                        all_values.append((geom_wkb, batch_id) + row_vals)
                    else:
                        all_values.append((geom_wkb, batch_id))

                cur.executemany(insert_stmt, all_values)

            # Per-chunk commit (S-4: load-bearing for retry safety)
            conn.commit()

            # Per-chunk row count verification (H3-B5)
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT COUNT(*) FROM {schema}.{table} WHERE etl_batch_id = %s"
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                    ),
                    (batch_id,),
                )
                chunk_db_count = cur.fetchone()["count"]

            chunk_expected = len(chunk)
            if chunk_db_count != chunk_expected:
                warn_msg = (
                    f"[{batch_id}] Row count mismatch: "
                    f"prepared={chunk_expected}, actual={chunk_db_count} "
                    f"in {schema_name}.{actual_table_name}"
                )
                logger.warning(warn_msg)
                warnings.append(warn_msg)

            rows_inserted_by_chunks += chunk_db_count
            logger.info(
                f"[{job_id[:8]}] Chunk {i + 1}/{total_chunks} complete: "
                f"deleted={rows_deleted}, inserted={chunk_db_count}"
            )

            # Progress milestones (H3-B15)
            _log_progress(
                job_id=job_id,
                table_name=actual_table_name,
                chunks_done=i + 1,
                total_chunks=total_chunks,
                rows_done=rows_inserted_by_chunks,
                total_rows=total_rows,
                start_time=load_start,
            )

        # --- 5. Deferred indexes (C-2: created AFTER all data loaded) ---
        handler.create_deferred_indexes(
            table_name=actual_table_name,
            schema=schema_name,
            gdf=gdf,
            indexes=indexes,
            conn=conn,
        )

        # --- 6. ANALYZE ---
        handler.analyze_table(actual_table_name, schema_name, conn=conn)

        # --- 7. Zero-row check + SELECT COUNT(*) cross-check ---
        # Zero-row check (H3-B9)
        if rows_inserted_by_chunks == 0:
            raise _ZeroRowsError(
                f"Zero rows inserted into {schema_name}.{actual_table_name}. "
                f"Source GeoParquet had {actual_row_count_in_file} rows."
            )

        # Cross-check (H3-B10): SELECT COUNT(*) is authoritative
        verified_row_count = rows_inserted_by_chunks
        try:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL(
                        "SELECT COUNT(*) FROM {schema}.{table}"
                    ).format(
                        schema=psql.Identifier(schema_name),
                        table=psql.Identifier(actual_table_name),
                    )
                )
                db_total = cur.fetchone()["count"]

            if db_total != rows_inserted_by_chunks:
                warn_msg = (
                    f"Row count discrepancy for {actual_table_name}: "
                    f"chunk sum={rows_inserted_by_chunks}, COUNT(*)={db_total}"
                )
                logger.warning(f"[{job_id[:8]}] {warn_msg}")
                warnings.append(warn_msg)

            verified_row_count = db_total  # DB count is authoritative
        except Exception as count_err:
            warn_msg = (
                f"Could not verify row count for {actual_table_name} "
                f"via SELECT COUNT(*): {count_err}"
            )
            logger.warning(f"[{job_id[:8]}] {warn_msg}")
            warnings.append(warn_msg)

        logger.info(
            f"[{job_id[:8]}] Connection closing for {schema_name}.{actual_table_name} "
            f"pid={conn_pid}"
        )

    # Connection closed here (with block exit)

    table_suffix = geometry_type if is_split else None
    has_spatial_index = indexes.get("spatial", True)

    return {
        "table_name": actual_table_name,
        "schema_name": schema_name,
        "geometry_type": geometry_type,
        "row_count": verified_row_count,
        "rows_inserted_by_chunks": rows_inserted_by_chunks,
        "column_count": column_count,
        "has_spatial_index": has_spatial_index,
        "srid": 4326,
        "bbox": bbox,
        "is_split": is_split,
        "table_suffix": table_suffix,
    }


# ---------------------------------------------------------------------------
# Sentinel exception types (used for error_type classification)
# ---------------------------------------------------------------------------

class _TableExistsError(Exception):
    pass


class _ZeroRowsError(Exception):
    pass


class _IntermediateNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public handler entry point
# ---------------------------------------------------------------------------

def vector_create_and_load_tables(
    params: Dict[str, Any],
    context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Create PostGIS tables and load GeoParquet data for each geometry group.

    Params:
        table_name       (str, required): Base PostGIS table name.
        schema_name      (str, default "geo"): Target schema.
        job_id           (str, required): Job ID for batch tracking and logging.
        geometry_groups  (list, required): From vector_validate_and_clean.
                         Each entry: {geometry_type, row_count, parquet_path}.
        processing_options (dict, optional):
            overwrite    (bool, default false): Drop existing table before create.
            chunk_size   (int, default 100000): Rows per INSERT chunk.
        _run_id          (str, system-injected): DAG run ID.
        _node_name       (str, system-injected): DAG node name.

    Returns:
        {"success": True, "result": {tables_created, total_rows_loaded, ...}}
        {"success": False, "error": str, "error_type": str}
    """
    # --- Parameter extraction ---
    err = _validate_params(params)
    if err:
        return err

    table_name: str = params["table_name"]
    schema_name: str = params.get("schema_name", "geo")
    job_id: str = params["job_id"]
    geometry_groups: List[Dict[str, Any]] = params["geometry_groups"]

    processing_options: Dict[str, Any] = params.get("processing_options") or {}
    overwrite: bool = bool(processing_options.get("overwrite", False))
    chunk_size: int = int(processing_options.get("chunk_size", _DEFAULT_CHUNK_SIZE))

    # Index config -- spatial index enabled by default; no attribute/temporal unless specified
    indexes: Dict[str, Any] = {
        "spatial": True,
        "attributes": [],
        "temporal": [],
    }

    is_split: bool = len(geometry_groups) > 1
    warnings: List[str] = []
    tables_created: List[Dict[str, Any]] = []
    total_rows_loaded: int = 0

    logger.info(
        f"[{job_id[:8]}] vector_create_and_load_tables: "
        f"table={table_name}, schema={schema_name}, "
        f"groups={len(geometry_groups)}, is_split={is_split}, "
        f"overwrite={overwrite}, chunk_size={chunk_size:,}"
    )

    # --- Validate parquet files exist before starting any DB work ---
    for i, group in enumerate(geometry_groups):
        ppath = group["parquet_path"]
        if not os.path.exists(ppath):
            return {
                "success": False,
                "error": (
                    f"geometry_groups[{i}].parquet_path not found: '{ppath}'"
                ),
                "error_type": "IntermediateNotFoundError",
            }

    # --- Process each geometry group ---
    try:
        for group in geometry_groups:
            geometry_type: str = group["geometry_type"]
            actual_table_name = _build_table_name(table_name, geometry_type, is_split)

            logger.info(
                f"[{job_id[:8]}] Processing geometry group: "
                f"type={geometry_type}, table={schema_name}.{actual_table_name}, "
                f"parquet={group['parquet_path']}"
            )

            table_result = _process_one_table(
                group=group,
                actual_table_name=actual_table_name,
                schema_name=schema_name,
                job_id=job_id,
                overwrite=overwrite,
                chunk_size=chunk_size,
                indexes=indexes,
                is_split=is_split,
                geometry_type=geometry_type,
                warnings=warnings,
            )

            tables_created.append(table_result)
            total_rows_loaded += table_result["row_count"]

            logger.info(
                f"[{job_id[:8]}] Completed {schema_name}.{actual_table_name}: "
                f"{table_result['row_count']:,} rows verified"
            )

    except _TableExistsError as e:
        logger.error(f"[{job_id[:8]}] TableExistsError: {e}")
        return {"success": False, "error": str(e), "error_type": "TableExistsError"}

    except _ZeroRowsError as e:
        logger.error(f"[{job_id[:8]}] ZeroRowsError: {e}")
        return {"success": False, "error": str(e), "error_type": "ZeroRowsError"}

    except FileNotFoundError as e:
        logger.error(f"[{job_id[:8]}] IntermediateNotFoundError: {e}")
        return {"success": False, "error": str(e), "error_type": "IntermediateNotFoundError"}

    except Exception as e:
        # Classify database errors vs generic handler errors
        try:
            import psycopg
            if isinstance(e, psycopg.Error):
                logger.error(
                    f"[{job_id[:8]}] DatabaseError in vector_create_and_load_tables: {e}",
                    exc_info=True,
                )
                return {
                    "success": False,
                    "error": str(e),
                    "error_type": "DatabaseError",
                }
        except ImportError:
            pass

        logger.error(
            f"[{job_id[:8]}] HandlerError in vector_create_and_load_tables: {e}",
            exc_info=True,
        )
        return {"success": False, "error": str(e), "error_type": "HandlerError"}

    # --- Global zero-row check across all tables (H3-B9) ---
    if total_rows_loaded == 0:
        return {
            "success": False,
            "error": (
                f"Zero rows loaded across all {len(tables_created)} table(s) "
                f"for base table '{table_name}'."
            ),
            "error_type": "ZeroRowsError",
        }

    overwrite_performed = overwrite and any(
        w for w in warnings if "dropped" in w
    )

    logger.info(
        f"[{job_id[:8]}] vector_create_and_load_tables complete: "
        f"{len(tables_created)} table(s), {total_rows_loaded:,} total rows"
    )

    return {
        "success": True,
        "result": {
            "tables_created": tables_created,
            "total_rows_loaded": total_rows_loaded,
            "total_tables": len(tables_created),
            "overwrite_performed": overwrite_performed,
            "chunk_size_used": chunk_size,
            "warnings": warnings,
        },
    }
