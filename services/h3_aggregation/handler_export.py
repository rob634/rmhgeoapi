# ============================================================================
# CLAUDE CONTEXT - H3 EXPORT HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - H3 Export to Geo Schema
# PURPOSE: Export denormalized H3 data to geo schema tables
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: h3_export_validate, h3_export_build, h3_export_register
# DEPENDENCIES: infrastructure.h3_repository, infrastructure.postgresql
# ============================================================================
"""
H3 Export Handler.

Three-stage export workflow for creating denormalized wide-format tables
from H3 zonal_stats. Exports to geo schema for mapping and download use cases.

Handlers:
    h3_export_validate: Check table existence, verify datasets in registry
    h3_export_build: Join cells + zonal_stats, pivot to wide, export
    h3_export_register: Update export catalog with metadata

Output Table Format:
    geo.{table_name}
    - h3_index BIGINT PRIMARY KEY
    - geom GEOMETRY(Polygon/Point, 4326)
    - iso3 VARCHAR(3) (optional)
    - {dataset_id}_{stat_type} columns for each variable
"""

from typing import Dict, Any, List, Optional
from util_logger import LoggerFactory, ComponentType
from psycopg import sql


# ============================================================================
# STAGE 1: VALIDATE
# ============================================================================

def h3_export_validate(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Validate export preconditions (Stage 1).

    Checks:
    1. Table doesn't exist (or overwrite=true)
    2. All datasets exist in h3.dataset_registry
    3. Datasets have data in h3.zonal_stats

    Args:
        params: Task parameters containing:
            - table_name (str): Target table name
            - variables (list): Variable definitions
            - overwrite (bool): Whether to overwrite existing table
            - source_job_id (str): Job ID for tracking

    Returns:
        Success dict with validation results
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_export_validate")

    table_name = params.get('table_name')
    variables = params.get('variables', [])
    overwrite = params.get('overwrite', False)
    source_job_id = params.get('source_job_id')

    logger.info(f"🔍 Validating export: geo.{table_name}")
    logger.info(f"   Variables: {len(variables)} datasets")
    logger.info(f"   Overwrite: {overwrite}")

    try:
        from infrastructure.postgresql import PostgreSQLRepository

        repo = PostgreSQLRepository(schema_name='geo')

        # CHECK 1: Table existence
        table_exists = _check_table_exists(repo, 'geo', table_name)
        logger.info(f"   Table exists: {table_exists}")

        if table_exists and not overwrite:
            error_msg = (
                f"Table geo.{table_name} already exists. "
                f"Use 'overwrite: true' to replace it."
            )
            logger.error(f"   ❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "result": {
                    "validation_passed": False,
                    "error": error_msg,
                    "table_exists": True
                }
            }

        # CHECK 2: Datasets exist in registry and have data
        from infrastructure.h3_repository import H3Repository
        h3_repo = H3Repository()

        dataset_info = []
        missing_data = []

        for var in variables:
            dataset_id = var['dataset_id']
            stat_types = var['stat_types']

            # Check registry
            dataset = h3_repo.get_dataset(dataset_id)
            if not dataset:
                missing_data.append(f"{dataset_id} (not in registry)")
                continue

            # Check for actual data in zonal_stats
            stat_count = _get_dataset_stat_count(h3_repo, dataset_id)
            if stat_count == 0:
                missing_data.append(f"{dataset_id} (no data in zonal_stats)")
                continue

            dataset_info.append({
                "dataset_id": dataset_id,
                "theme": dataset.get('theme'),
                "stat_types": stat_types,
                "stat_count": stat_count
            })
            logger.info(f"   ✓ {dataset_id}: {stat_count:,} stats, theme={dataset.get('theme')}")

        if missing_data:
            error_msg = f"Missing datasets or data: {missing_data}"
            logger.error(f"   ❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "result": {
                    "validation_passed": False,
                    "error": error_msg,
                    "missing_data": missing_data
                }
            }

        logger.info(f"✅ Validation passed")

        return {
            "success": True,
            "result": {
                "validation_passed": True,
                "table_name": table_name,
                "table_exists": table_exists,
                "will_overwrite": table_exists and overwrite,
                "datasets": dataset_info
            }
        }

    except Exception as e:
        logger.error(f"❌ Validation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "result": {
                "validation_passed": False,
                "error": str(e)
            }
        }


# ============================================================================
# STAGE 2: BUILD
# ============================================================================

def h3_export_build(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Build export table by joining cells with zonal_stats (Stage 2).

    Process:
    1. Drop existing table if overwrite=true
    2. Build dynamic SQL with pivot columns
    3. Execute CREATE TABLE AS SELECT
    4. Create indexes
    5. Return row/column counts

    Args:
        params: Task parameters containing:
            - table_name (str): Target table name
            - resolution (int): H3 resolution level
            - variables (list): Variable definitions
            - geometry_type (str): 'polygon' or 'centroid'
            - iso3 (str): Optional country filter
            - bbox (list): Optional bounding box
            - polygon_wkt (str): Optional WKT polygon
            - overwrite (bool): Whether to overwrite
            - include_iso3_column (bool): Include iso3 column
            - source_job_id (str): Job ID

    Returns:
        Success dict with build results
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_export_build")

    table_name = params.get('table_name')
    resolution = params.get('resolution')
    variables = params.get('variables', [])
    geometry_type = params.get('geometry_type', 'polygon')
    iso3 = params.get('iso3')
    bbox = params.get('bbox')
    polygon_wkt = params.get('polygon_wkt')
    overwrite = params.get('overwrite', False)
    include_iso3_column = params.get('include_iso3_column', True)
    source_job_id = params.get('source_job_id')

    logger.info(f"🔨 Building export: geo.{table_name}")
    logger.info(f"   Resolution: {resolution}")
    logger.info(f"   Geometry: {geometry_type}")
    logger.info(f"   Variables: {[v['dataset_id'] for v in variables]}")

    try:
        from infrastructure.postgresql import PostgreSQLRepository

        repo = PostgreSQLRepository(schema_name='geo')

        # STEP 1: Drop existing table if overwrite
        if overwrite:
            _drop_table_if_exists(repo, 'geo', table_name)
            logger.info(f"   Dropped existing table (overwrite=true)")

        # STEP 2: Build pivot column definitions
        pivot_columns = []
        for var in variables:
            dataset_id = var['dataset_id']
            for stat_type in var['stat_types']:
                col_name = f"{dataset_id}_{stat_type}"
                pivot_columns.append({
                    "column_name": col_name,
                    "dataset_id": dataset_id,
                    "stat_type": stat_type
                })

        logger.info(f"   Pivot columns: {len(pivot_columns)}")

        # STEP 3: Build and execute CREATE TABLE AS SELECT
        row_count = _create_export_table(
            repo=repo,
            table_name=table_name,
            resolution=resolution,
            pivot_columns=pivot_columns,
            geometry_type=geometry_type,
            iso3=iso3,
            bbox=bbox,
            polygon_wkt=polygon_wkt,
            include_iso3_column=include_iso3_column
        )

        logger.info(f"   Created table with {row_count:,} rows")

        # STEP 4: Create indexes
        _create_export_indexes(repo, table_name, include_iso3_column)
        logger.info(f"   Created indexes")

        # STEP 5: Add table comment
        _add_table_comment(
            repo=repo,
            table_name=table_name,
            resolution=resolution,
            variables=variables,
            geometry_type=geometry_type,
            iso3=iso3,
            source_job_id=source_job_id
        )

        column_count = 2 + len(pivot_columns) + (1 if include_iso3_column else 0)  # h3_index, geom, (iso3), columns

        logger.info(f"✅ Export complete: geo.{table_name}")

        return {
            "success": True,
            "result": {
                "table_name": f"geo.{table_name}",
                "row_count": row_count,
                "column_count": column_count,
                "pivot_columns": [c['column_name'] for c in pivot_columns],
                "geometry_type": geometry_type,
                "resolution": resolution
            }
        }

    except Exception as e:
        logger.error(f"❌ Build failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# ============================================================================
# STAGE 3: REGISTER
# ============================================================================

def h3_export_register(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Register export in catalog (Stage 3).

    Updates export metadata for discovery and documentation.

    Args:
        params: Task parameters containing:
            - table_name (str): Table name
            - display_name (str): Human-readable name
            - description (str): Description
            - resolution (int): H3 resolution
            - variables (list): Variable definitions
            - geometry_type (str): Geometry type
            - iso3 (str): Country code if filtered
            - row_count (int): Number of rows
            - column_count (int): Number of columns
            - source_job_id (str): Job ID

    Returns:
        Success dict with registration results
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_export_register")

    table_name = params.get('table_name')
    display_name = params.get('display_name') or table_name
    description = params.get('description')
    resolution = params.get('resolution')
    variables = params.get('variables', [])
    geometry_type = params.get('geometry_type', 'polygon')
    iso3 = params.get('iso3')
    row_count = params.get('row_count', 0)
    column_count = params.get('column_count', 0)
    source_job_id = params.get('source_job_id')

    logger.info(f"📝 Registering export: geo.{table_name}")

    try:
        from infrastructure.postgresql import PostgreSQLRepository
        from datetime import datetime

        repo = PostgreSQLRepository(schema_name='geo')

        # Build export metadata
        export_metadata = {
            "table_name": table_name,
            "display_name": display_name,
            "description": description,
            "resolution": resolution,
            "geometry_type": geometry_type,
            "iso3": iso3,
            "row_count": row_count,
            "column_count": column_count,
            "datasets": [v['dataset_id'] for v in variables],
            "created_at": datetime.utcnow().isoformat(),
            "source_job_id": source_job_id
        }

        # Log the registration (actual catalog table can be added later)
        logger.info(f"   Display name: {display_name}")
        logger.info(f"   Rows: {row_count:,}")
        logger.info(f"   Columns: {column_count}")
        logger.info(f"   Datasets: {export_metadata['datasets']}")

        logger.info(f"✅ Registration complete")

        return {
            "success": True,
            "result": {
                "table_name": f"geo.{table_name}",
                "registered": True,
                "metadata": export_metadata
            }
        }

    except Exception as e:
        logger.error(f"❌ Registration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _check_table_exists(repo, schema: str, table_name: str) -> bool:
    """Check if table exists in schema."""
    query = sql.SQL("""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        ) as exists
    """)

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (schema, table_name))
            result = cur.fetchone()

    return result['exists'] if result else False


def _drop_table_if_exists(repo, schema: str, table_name: str) -> None:
    """Drop table if it exists."""
    query = sql.SQL("DROP TABLE IF EXISTS {schema}.{table} CASCADE").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name)
    )

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()


def _get_dataset_stat_count(h3_repo, dataset_id: str) -> int:
    """Get count of stats for dataset in zonal_stats."""
    query = sql.SQL("""
        SELECT COUNT(*) as count
        FROM {schema}.{table}
        WHERE dataset_id = %s
    """).format(
        schema=sql.Identifier('h3'),
        table=sql.Identifier('zonal_stats')
    )

    with h3_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (dataset_id,))
            result = cur.fetchone()

    return result['count'] if result else 0


def _create_export_table(
    repo,
    table_name: str,
    resolution: int,
    pivot_columns: List[Dict[str, str]],
    geometry_type: str,
    iso3: Optional[str],
    bbox: Optional[List[float]],
    polygon_wkt: Optional[str],
    include_iso3_column: bool
) -> int:
    """
    Create export table with pivoted data.

    Uses a single SQL query to:
    1. Select cells for scope
    2. Left join with zonal_stats
    3. Pivot stat_type into columns using conditional aggregation
    4. Create table in geo schema
    """
    # Build geometry expression
    if geometry_type == 'centroid':
        geom_expr = "ST_Centroid(c.geom)"
    else:
        geom_expr = "c.geom"

    # Build pivot SELECT expressions
    pivot_selects = []
    for col in pivot_columns:
        col_name = col['column_name']
        dataset_id = col['dataset_id']
        stat_type = col['stat_type']

        # Use conditional aggregation to pivot
        pivot_selects.append(sql.SQL(
            "MAX(CASE WHEN z.dataset_id = {dataset} AND z.stat_type = {stat} THEN z.value END) AS {col}"
        ).format(
            dataset=sql.Literal(dataset_id),
            stat=sql.Literal(stat_type),
            col=sql.Identifier(col_name)
        ))

    # Build WHERE clause for spatial filtering
    where_conditions = [sql.SQL("c.resolution = %s")]
    where_params = [resolution]

    if iso3:
        where_conditions.append(sql.SQL(
            "c.h3_index IN (SELECT h3_index FROM h3.cell_admin0 WHERE iso3 = %s)"
        ))
        where_params.append(iso3)
    elif bbox and len(bbox) == 4:
        where_conditions.append(sql.SQL(
            "ST_Intersects(c.geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
        ))
        where_params.extend(bbox)
    elif polygon_wkt:
        where_conditions.append(sql.SQL(
            "ST_Intersects(c.geom, ST_GeomFromText(%s, 4326))"
        ))
        where_params.append(polygon_wkt)

    where_clause = sql.SQL(" AND ").join(where_conditions)

    # Build optional iso3 column
    if include_iso3_column:
        iso3_select = sql.SQL(", (SELECT a.iso3 FROM h3.cell_admin0 a WHERE a.h3_index = c.h3_index LIMIT 1) AS iso3")
    else:
        iso3_select = sql.SQL("")

    # Build the full CREATE TABLE AS SELECT query
    query = sql.SQL("""
        CREATE TABLE {schema}.{table} AS
        SELECT
            c.h3_index,
            {geom_expr} AS geom
            {iso3_select},
            {pivot_columns}
        FROM h3.cells c
        LEFT JOIN h3.zonal_stats z ON c.h3_index = z.h3_index
        WHERE {where_clause}
        GROUP BY c.h3_index, c.geom
        ORDER BY c.h3_index
    """).format(
        schema=sql.Identifier('geo'),
        table=sql.Identifier(table_name),
        geom_expr=sql.SQL(geom_expr),
        iso3_select=iso3_select,
        pivot_columns=sql.SQL(", ").join(pivot_selects),
        where_clause=where_clause
    )

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, where_params)
        conn.commit()

    # Get row count
    count_query = sql.SQL("SELECT COUNT(*) as count FROM {schema}.{table}").format(
        schema=sql.Identifier('geo'),
        table=sql.Identifier(table_name)
    )

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(count_query)
            result = cur.fetchone()

    return result['count'] if result else 0


def _create_export_indexes(repo, table_name: str, include_iso3_column: bool) -> None:
    """Create indexes on export table."""
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            # Primary key on h3_index
            cur.execute(sql.SQL(
                "ALTER TABLE {schema}.{table} ADD PRIMARY KEY (h3_index)"
            ).format(
                schema=sql.Identifier('geo'),
                table=sql.Identifier(table_name)
            ))

            # Spatial index
            cur.execute(sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON {schema}.{table} USING GIST(geom)"
            ).format(
                idx=sql.Identifier(f"idx_{table_name}_geom"),
                schema=sql.Identifier('geo'),
                table=sql.Identifier(table_name)
            ))

            # ISO3 index if column exists
            if include_iso3_column:
                cur.execute(sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {idx} ON {schema}.{table}(iso3)"
                ).format(
                    idx=sql.Identifier(f"idx_{table_name}_iso3"),
                    schema=sql.Identifier('geo'),
                    table=sql.Identifier(table_name)
                ))

        conn.commit()


def _add_table_comment(
    repo,
    table_name: str,
    resolution: int,
    variables: List[Dict],
    geometry_type: str,
    iso3: Optional[str],
    source_job_id: Optional[str]
) -> None:
    """Add comment to export table."""
    from datetime import datetime

    datasets = [v['dataset_id'] for v in variables]
    scope = f"iso3={iso3}" if iso3 else "global"

    comment = (
        f"H3 export table (resolution {resolution}, {geometry_type}). "
        f"Scope: {scope}. "
        f"Datasets: {', '.join(datasets)}. "
        f"Created: {datetime.utcnow().strftime('%d %b %Y').upper()}. "
        f"Job: {source_job_id[:8] if source_job_id else 'unknown'}."
    )

    query = sql.SQL("COMMENT ON TABLE {schema}.{table} IS {comment}").format(
        schema=sql.Identifier('geo'),
        table=sql.Identifier(table_name),
        comment=sql.Literal(comment)
    )

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()


# Export for handler registration
__all__ = ['h3_export_validate', 'h3_export_build', 'h3_export_register']
