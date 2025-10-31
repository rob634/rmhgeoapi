# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone Repository - PostGIS vector data access
# PURPOSE: Direct PostGIS queries for OGC Features API with ST_AsGeoJSON optimization
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: OGCFeaturesRepository
# INTERFACES: None (standalone implementation)
# PYDANTIC_MODELS: None (uses plain dicts for SQL safety)
# DEPENDENCIES: psycopg, psycopg.sql, typing, datetime, logging
# SOURCE: PostgreSQL/PostGIS database (configurable schema)
# SCOPE: Vector feature queries with spatial, temporal, and attribute filtering
# VALIDATION: SQL injection prevention via psycopg.sql composition, feature-flagged optimization checks
# PATTERNS: Repository Pattern, Query Builder, SQL Composition
# ENTRY_POINTS: repo = OGCFeaturesRepository(config); features = repo.query_features(...)
# INDEX: OGCFeaturesRepository:55, query_features:248, _validate_table_optimization:821
# ============================================================================

"""
OGC Features Repository - PostGIS Direct Access

Provides efficient PostGIS queries for OGC Features API with:
- ST_AsGeoJSON() for GeoJSON serialization with precision control
- ST_Simplify() for geometry generalization
- ST_Intersects() for spatial filtering (bbox)
- Temporal filtering with flexible column names
- Simple attribute filtering (key=value equality)
- OGC standard sorting (sortby syntax)
- Spatial index optimization (feature-flagged validation)

Safety:
- All queries use psycopg.sql.SQL() composition (NO string concatenation)
- Dynamic identifiers via sql.Identifier()
- Values via parameterized queries (%s placeholders)
- SQL injection prevention guaranteed

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from contextlib import contextmanager
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .config import OGCFeaturesConfig, get_ogc_config

# Setup logging
logger = logging.getLogger(__name__)


class OGCFeaturesRepository:
    """
    PostGIS repository for OGC Features API queries.

    Provides direct PostgreSQL/PostGIS access with optimized queries for
    serving vector features via OGC API - Features specification.

    Features:
    - Collection discovery from geometry_columns
    - ST_AsGeoJSON with precision and simplification
    - Spatial filtering (bbox via ST_Intersects)
    - Temporal filtering (flexible datetime columns)
    - Attribute filtering (simple key=value)
    - Sorting (OGC sortby syntax)
    - Feature-flagged validation checks

    Thread Safety:
    - Each method creates its own connection
    - Safe for concurrent requests in Azure Functions
    """

    def __init__(self, config: Optional[OGCFeaturesConfig] = None):
        """
        Initialize repository with configuration.

        Args:
            config: OGC Features configuration (uses singleton if not provided)
        """
        self.config = config or get_ogc_config()
        logger.info(f"OGCFeaturesRepository initialized (schema: {self.config.ogc_schema}, validation: {self.config.enable_validation})")

    @contextmanager
    def _get_connection(self):
        """
        Context manager for PostgreSQL connections.

        Yields:
            psycopg connection with dict_row factory
        """
        conn = None
        try:
            conn = psycopg.connect(
                self.config.get_connection_string(),
                row_factory=dict_row
            )
            yield conn
        except psycopg.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    # ========================================================================
    # COLLECTION DISCOVERY
    # ========================================================================

    def list_collections(self) -> List[Dict[str, Any]]:
        """
        List all vector collections (tables) in configured schema.

        Queries PostGIS geometry_columns view for all tables with geometry.

        Returns:
            List of collection metadata dicts with keys:
            - id: Table name
            - geometry_column: Geometry column name
            - geometry_type: Geometry type (Point, LineString, Polygon, etc.)
            - srid: Spatial reference system ID
            - schema: Schema name
        """
        query = sql.SQL("""
            SELECT
                f_table_name as id,
                f_geometry_column as geometry_column,
                type as geometry_type,
                srid,
                f_table_schema as schema
            FROM geometry_columns
            WHERE f_table_schema = %s
            ORDER BY f_table_name
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (self.config.ogc_schema,))
                    collections = cur.fetchall()
                    logger.info(f"Found {len(collections)} collections in schema '{self.config.ogc_schema}'")
                    return collections
        except psycopg.Error as e:
            logger.error(f"Error listing collections: {e}")
            raise

    def get_collection_metadata(self, collection_id: str) -> Dict[str, Any]:
        """
        Get metadata for a specific collection.

        Retrieves:
        - Bounding box (ST_Extent)
        - Feature count
        - Geometry type and SRID
        - Datetime columns (for temporal query support)

        Args:
            collection_id: Table name

        Returns:
            Collection metadata dict with keys:
            - id: Table name
            - geometry_column: Geometry column name
            - geometry_type: Geometry type
            - srid: SRID
            - bbox: [minx, miny, maxx, maxy] or None
            - feature_count: Total features
            - datetime_columns: List of datetime column names
            - primary_key: Primary key column name (or None)
        """
        geom_column = self._detect_geometry_column(collection_id)

        # Query geometry metadata from geometry_columns
        geom_query = sql.SQL("""
            SELECT
                f_geometry_column as geometry_column,
                type as geometry_type,
                srid
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
        """)

        # Query bbox and count
        stats_query = sql.SQL("""
            SELECT
                ST_Extent({geom_col}) as extent,
                COUNT(*) as feature_count
            FROM {schema}.{table}
        """).format(
            geom_col=sql.Identifier(geom_column),
            schema=sql.Identifier(self.config.ogc_schema),
            table=sql.Identifier(collection_id)
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get geometry metadata
                    cur.execute(geom_query, (self.config.ogc_schema, collection_id))
                    geom_info = cur.fetchone()

                    if not geom_info:
                        raise ValueError(f"Collection '{collection_id}' not found in schema '{self.config.ogc_schema}'")

                    # Get stats
                    cur.execute(stats_query)
                    stats = cur.fetchone()

                    # Parse bbox from extent
                    bbox = None
                    if stats and stats.get('extent'):
                        bbox = self._parse_extent_to_bbox(stats['extent'])

                    # Get datetime columns
                    datetime_cols = self._detect_datetime_columns(collection_id, conn)

                    # Get primary key
                    pk_column = self._detect_primary_key(collection_id, conn)

                    metadata = {
                        'id': collection_id,
                        'geometry_column': geom_info['geometry_column'],
                        'geometry_type': geom_info['geometry_type'],
                        'srid': geom_info['srid'],
                        'bbox': bbox,
                        'feature_count': stats['feature_count'] if stats else 0,
                        'datetime_columns': datetime_cols,
                        'primary_key': pk_column
                    }

                    # Optional validation checks
                    if self.config.enable_validation:
                        validation_results = self._validate_table_optimization(collection_id, geom_column, conn)
                        metadata['validation'] = validation_results

                    return metadata

        except psycopg.Error as e:
            logger.error(f"Error getting metadata for collection '{collection_id}': {e}")
            raise

    # ========================================================================
    # FEATURE QUERIES
    # ========================================================================

    def query_features(
        self,
        collection_id: str,
        limit: int = 100,
        offset: int = 0,
        bbox: Optional[List[float]] = None,
        datetime_filter: Optional[str] = None,
        datetime_property: Optional[str] = None,
        property_filters: Optional[Dict[str, Any]] = None,
        sortby: Optional[str] = None,
        precision: int = 6,
        simplify: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query features from a collection with filters, sorting, and optimization.

        This is the main query method that supports all OGC Features parameters.

        Args:
            collection_id: Table name
            limit: Max features to return (1-10000)
            offset: Number of features to skip
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326
            datetime_filter: ISO 8601 instant or interval (e.g., "2024-01-01" or "2024-01-01/2024-12-31")
            datetime_property: Datetime column name (auto-detects if None)
            property_filters: Dict of attribute filters (key=value equality)
            sortby: OGC sortby syntax (e.g., "+year,-population")
            precision: Coordinate precision (decimal places)
            simplify: Simplification tolerance in meters (ST_Simplify)

        Returns:
            Tuple of (features_list, total_count)
            - features_list: List of GeoJSON-like dicts
            - total_count: Total matching features (for pagination)
        """
        geom_column = self._detect_geometry_column(collection_id)

        # Build query components
        query = self._build_feature_query(
            collection_id=collection_id,
            geom_column=geom_column,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime_filter=datetime_filter,
            datetime_property=datetime_property,
            property_filters=property_filters,
            sortby=sortby,
            precision=precision,
            simplify=simplify
        )

        # Build count query (same filters, no limit/offset/sort)
        count_query = self._build_count_query(
            collection_id=collection_id,
            bbox=bbox,
            datetime_filter=datetime_filter,
            datetime_property=datetime_property,
            property_filters=property_filters
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Set query timeout
                    cur.execute(f"SET statement_timeout = '{self.config.query_timeout_seconds}s'")

                    # Execute feature query
                    cur.execute(query['sql'], query['params'])
                    features = cur.fetchall()

                    # Execute count query
                    cur.execute(count_query['sql'], count_query['params'])
                    count_result = cur.fetchone()
                    total_count = count_result['count'] if count_result else 0

                    # Convert to GeoJSON-like format
                    geojson_features = self._convert_to_geojson_features(features, geom_column)

                    logger.info(f"Query returned {len(geojson_features)}/{total_count} features from '{collection_id}'")

                    return geojson_features, total_count

        except psycopg.Error as e:
            logger.error(f"Error querying features from '{collection_id}': {e}")
            raise

    def get_feature_by_id(
        self,
        collection_id: str,
        feature_id: str,
        precision: int = 6
    ) -> Optional[Dict[str, Any]]:
        """
        Get a single feature by ID.

        Args:
            collection_id: Table name
            feature_id: Feature ID (primary key value)
            precision: Coordinate precision

        Returns:
            GeoJSON-like feature dict or None if not found
        """
        geom_column = self._detect_geometry_column(collection_id)
        pk_column = self._detect_primary_key(collection_id)

        if not pk_column:
            raise ValueError(f"Collection '{collection_id}' has no primary key - cannot retrieve by ID")

        # Get all column names except geometry
        columns = self._get_table_columns(collection_id)
        non_geom_columns = [c for c in columns if c != geom_column]

        # Build query
        query = sql.SQL("""
            SELECT
                {columns},
                ST_AsGeoJSON({geom_col}, %s) as geometry
            FROM {schema}.{table}
            WHERE {pk_col} = %s
            LIMIT 1
        """).format(
            columns=sql.SQL(", ").join(sql.Identifier(c) for c in non_geom_columns),
            geom_col=sql.Identifier(geom_column),
            schema=sql.Identifier(self.config.ogc_schema),
            table=sql.Identifier(collection_id),
            pk_col=sql.Identifier(pk_column)
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (precision, feature_id))
                    result = cur.fetchone()

                    if not result:
                        return None

                    # Convert to GeoJSON feature
                    features = self._convert_to_geojson_features([result], geom_column)
                    return features[0] if features else None

        except psycopg.Error as e:
            logger.error(f"Error getting feature '{feature_id}' from '{collection_id}': {e}")
            raise

    # ========================================================================
    # QUERY BUILDING (SQL COMPOSITION)
    # ========================================================================

    def _build_feature_query(
        self,
        collection_id: str,
        geom_column: str,
        limit: int,
        offset: int,
        bbox: Optional[List[float]],
        datetime_filter: Optional[str],
        datetime_property: Optional[str],
        property_filters: Optional[Dict[str, Any]],
        sortby: Optional[str],
        precision: int,
        simplify: Optional[float]
    ) -> Dict[str, Any]:
        """
        Build complete feature query with all filters and optimizations.

        Returns:
            Dict with 'sql' (sql.Composed) and 'params' (tuple)
        """
        # Get all column names except geometry
        columns = self._get_table_columns(collection_id)
        non_geom_columns = [c for c in columns if c != geom_column]

        # Build geometry expression (with optional simplification)
        geom_expr, geom_params = self._build_geometry_expression(geom_column, simplify, precision)

        # Build WHERE clause
        where_clause, where_params = self._build_where_clause(
            collection_id=collection_id,
            geom_column=geom_column,
            bbox=bbox,
            datetime_filter=datetime_filter,
            datetime_property=datetime_property,
            property_filters=property_filters
        )

        # Build ORDER BY clause
        order_clause = self._build_order_clause(sortby)

        # Assemble query
        if where_clause:
            query = sql.SQL("""
                SELECT
                    {columns},
                    {geom_expr} as geometry
                FROM {schema}.{table}
                WHERE {where_clause}
                {order_clause}
                LIMIT %s OFFSET %s
            """).format(
                columns=sql.SQL(", ").join(sql.Identifier(c) for c in non_geom_columns),
                geom_expr=geom_expr,
                schema=sql.Identifier(self.config.ogc_schema),
                table=sql.Identifier(collection_id),
                where_clause=where_clause,
                order_clause=order_clause
            )
        else:
            query = sql.SQL("""
                SELECT
                    {columns},
                    {geom_expr} as geometry
                FROM {schema}.{table}
                {order_clause}
                LIMIT %s OFFSET %s
            """).format(
                columns=sql.SQL(", ").join(sql.Identifier(c) for c in non_geom_columns),
                geom_expr=geom_expr,
                schema=sql.Identifier(self.config.ogc_schema),
                table=sql.Identifier(collection_id),
                order_clause=order_clause
            )

        # Combine parameters: geometry params + where params + limit/offset
        params = tuple(geom_params) + tuple(where_params) + (limit, offset)

        return {'sql': query, 'params': params}

    def _build_count_query(
        self,
        collection_id: str,
        bbox: Optional[List[float]],
        datetime_filter: Optional[str],
        datetime_property: Optional[str],
        property_filters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build count query (same filters as feature query, no pagination).

        Returns:
            Dict with 'sql' (sql.Composed) and 'params' (tuple)
        """
        geom_column = self._detect_geometry_column(collection_id)

        where_clause, where_params = self._build_where_clause(
            collection_id=collection_id,
            geom_column=geom_column,
            bbox=bbox,
            datetime_filter=datetime_filter,
            datetime_property=datetime_property,
            property_filters=property_filters
        )

        if where_clause:
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.{table}
                WHERE {where_clause}
            """).format(
                schema=sql.Identifier(self.config.ogc_schema),
                table=sql.Identifier(collection_id),
                where_clause=where_clause
            )
        else:
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.{table}
            """).format(
                schema=sql.Identifier(self.config.ogc_schema),
                table=sql.Identifier(collection_id)
            )

        return {'sql': query, 'params': tuple(where_params)}

    def _build_where_clause(
        self,
        collection_id: str,
        geom_column: str,
        bbox: Optional[List[float]],
        datetime_filter: Optional[str],
        datetime_property: Optional[str],
        property_filters: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[sql.Composed], List[Any]]:
        """
        Build WHERE clause with spatial, temporal, and attribute filters.

        Returns:
            Tuple of (where_clause_sql, params_list)
        """
        conditions = []
        params = []

        # Spatial filter (bbox)
        if bbox and len(bbox) == 4:
            minx, miny, maxx, maxy = bbox
            conditions.append(sql.SQL(
                "ST_Intersects({geom_col}, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            ).format(geom_col=sql.Identifier(geom_column)))
            params.extend([minx, miny, maxx, maxy])

        # Temporal filter
        if datetime_filter:
            dt_column = datetime_property or self._detect_datetime_columns(collection_id)[0] if self._detect_datetime_columns(collection_id) else None

            if dt_column:
                # Parse datetime filter
                if "/" in datetime_filter:
                    # Interval: "start/end"
                    parts = datetime_filter.split("/")
                    start = parts[0] if parts[0] and parts[0] != ".." else None
                    end = parts[1] if parts[1] and parts[1] != ".." else None

                    if start and end:
                        conditions.append(sql.SQL(
                            "{dt_col} >= %s AND {dt_col} <= %s"
                        ).format(dt_col=sql.Identifier(dt_column)))
                        params.extend([start, end])
                    elif start:
                        conditions.append(sql.SQL(
                            "{dt_col} >= %s"
                        ).format(dt_col=sql.Identifier(dt_column)))
                        params.append(start)
                    elif end:
                        conditions.append(sql.SQL(
                            "{dt_col} <= %s"
                        ).format(dt_col=sql.Identifier(dt_column)))
                        params.append(end)
                else:
                    # Instant: exact match or date range
                    conditions.append(sql.SQL(
                        "{dt_col} >= %s AND {dt_col} < %s::timestamp + interval '1 day'"
                    ).format(dt_col=sql.Identifier(dt_column)))
                    params.extend([datetime_filter, datetime_filter])
            else:
                logger.warning(f"Temporal filter requested but no datetime columns found in '{collection_id}'")

        # Attribute filters (simple key=value)
        if property_filters:
            for key, value in property_filters.items():
                # Validate column exists
                if key in self._get_table_columns(collection_id):
                    conditions.append(sql.SQL(
                        "{col} = %s"
                    ).format(col=sql.Identifier(key)))
                    params.append(value)
                else:
                    logger.warning(f"Attribute filter on non-existent column '{key}' ignored")

        # Combine conditions with AND
        if not conditions:
            return None, []

        where_clause = sql.SQL(" AND ").join(conditions)
        return where_clause, params

    def _build_geometry_expression(
        self,
        geom_column: str,
        simplify: Optional[float],
        precision: int
    ) -> Tuple[sql.Composed, List[Any]]:
        """
        Build ST_AsGeoJSON expression with optional simplification.

        Returns:
            Tuple of (SQL expression, parameters list)
        """
        if simplify and simplify > 0:
            # With simplification (2 parameters: simplify tolerance, precision)
            expr = sql.SQL(
                "ST_AsGeoJSON(ST_Simplify({geom_col}, %s), %s)"
            ).format(geom_col=sql.Identifier(geom_column))
            return (expr, [simplify, precision])
        else:
            # No simplification (1 parameter: precision)
            expr = sql.SQL(
                "ST_AsGeoJSON({geom_col}, %s)"
            ).format(geom_col=sql.Identifier(geom_column))
            return (expr, [precision])

    def _build_order_clause(self, sortby: Optional[str]) -> sql.Composed:
        """
        Build ORDER BY clause from OGC sortby syntax.

        Args:
            sortby: OGC format (e.g., "+year,-population")

        Returns:
            SQL ORDER BY clause
        """
        if not sortby:
            return sql.SQL("")

        sort_parts = []
        for item in sortby.split(","):
            item = item.strip()
            if item.startswith("+"):
                col_name = item[1:]
                direction = sql.SQL("ASC")
            elif item.startswith("-"):
                col_name = item[1:]
                direction = sql.SQL("DESC")
            else:
                col_name = item
                direction = sql.SQL("ASC")

            sort_parts.append(
                sql.SQL("{col} {dir}").format(
                    col=sql.Identifier(col_name),
                    dir=direction
                )
            )

        if sort_parts:
            return sql.SQL("ORDER BY ") + sql.SQL(", ").join(sort_parts)

        return sql.SQL("")

    # ========================================================================
    # AUTO-DETECTION HELPERS
    # ========================================================================

    def _detect_geometry_column(self, collection_id: str) -> str:
        """
        Detect geometry column name for a table.

        Checks (in order):
        1. Config default (OGC_GEOMETRY_COLUMN)
        2. geometry_columns view
        3. Common names: geom, geometry, shape

        Args:
            collection_id: Table name

        Returns:
            Geometry column name

        Raises:
            ValueError: If no geometry column found
        """
        # Check geometry_columns view
        query = sql.SQL("""
            SELECT f_geometry_column
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (self.config.ogc_schema, collection_id))
                    result = cur.fetchone()

                    if result:
                        return result['f_geometry_column']

                    # Fallback: check common names
                    columns = self._get_table_columns(collection_id, conn)
                    for common_name in ['geom', 'geometry', 'shape', 'wkb_geometry']:
                        if common_name in columns:
                            logger.warning(f"Geometry column '{common_name}' detected by name (not in geometry_columns view)")
                            return common_name

                    raise ValueError(f"No geometry column found for table '{collection_id}'")

        except psycopg.Error as e:
            logger.error(f"Error detecting geometry column: {e}")
            raise

    def _detect_datetime_columns(self, collection_id: str, conn=None) -> List[str]:
        """
        Detect datetime columns in a table.

        Args:
            collection_id: Table name
            conn: Existing connection (optional)

        Returns:
            List of datetime column names
        """
        query = sql.SQL("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
                AND table_name = %s
                AND data_type IN ('timestamp', 'timestamp with time zone', 'timestamp without time zone', 'date', 'time')
            ORDER BY ordinal_position
        """)

        close_conn = False
        if conn is None:
            conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
            close_conn = True

        try:
            with conn.cursor() as cur:
                cur.execute(query, (self.config.ogc_schema, collection_id))
                results = cur.fetchall()
                return [r['column_name'] for r in results]
        finally:
            if close_conn:
                conn.close()

    def _detect_primary_key(self, collection_id: str, conn=None) -> Optional[str]:
        """
        Detect primary key column for a table.

        Args:
            collection_id: Table name
            conn: Existing connection (optional)

        Returns:
            Primary key column name or None
        """
        query = sql.SQL("""
            SELECT a.attname as column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """)

        close_conn = False
        if conn is None:
            conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
            close_conn = True

        try:
            with conn.cursor() as cur:
                full_table_name = f"{self.config.ogc_schema}.{collection_id}"
                cur.execute(query, (full_table_name,))
                result = cur.fetchone()
                return result['column_name'] if result else None
        finally:
            if close_conn:
                conn.close()

    def _get_table_columns(self, collection_id: str, conn=None) -> List[str]:
        """
        Get all column names for a table.

        Args:
            collection_id: Table name
            conn: Existing connection (optional)

        Returns:
            List of column names
        """
        query = sql.SQL("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """)

        close_conn = False
        if conn is None:
            conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
            close_conn = True

        try:
            with conn.cursor() as cur:
                cur.execute(query, (self.config.ogc_schema, collection_id))
                results = cur.fetchall()
                return [r['column_name'] for r in results]
        finally:
            if close_conn:
                conn.close()

    # ========================================================================
    # VALIDATION (FEATURE-FLAGGED)
    # ========================================================================

    def _validate_table_optimization(
        self,
        collection_id: str,
        geom_column: str,
        conn=None
    ) -> Dict[str, Any]:
        """
        Validate table optimization (spatial indexes, primary keys, etc.).

        Only runs if config.enable_validation = True.

        Args:
            collection_id: Table name
            geom_column: Geometry column name
            conn: Existing connection (optional)

        Returns:
            Validation results dict with warnings and recommendations
        """
        if not self.config.enable_validation:
            return {'validation_enabled': False}

        close_conn = False
        if conn is None:
            conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
            close_conn = True

        try:
            results = {
                'validation_enabled': True,
                'warnings': [],
                'recommendations': []
            }

            # Check for spatial index
            has_spatial_index = self._has_spatial_index(collection_id, geom_column, conn)
            if not has_spatial_index:
                results['warnings'].append(f"No GIST spatial index on '{geom_column}' - queries will be slow")
                results['recommendations'].append(f"CREATE INDEX idx_{collection_id}_{geom_column} ON {self.config.ogc_schema}.{collection_id} USING GIST({geom_column})")

            # Check for primary key
            pk_column = self._detect_primary_key(collection_id, conn)
            if not pk_column:
                results['warnings'].append("No primary key - feature ID retrieval not supported")
                results['recommendations'].append(f"ALTER TABLE {self.config.ogc_schema}.{collection_id} ADD PRIMARY KEY (id)")

            # Check for datetime columns (if none found, temporal queries won't work)
            datetime_cols = self._detect_datetime_columns(collection_id, conn)
            if not datetime_cols:
                results['warnings'].append("No datetime columns - temporal queries not supported")

            logger.info(f"Validation for '{collection_id}': {len(results['warnings'])} warnings, {len(results['recommendations'])} recommendations")

            return results

        finally:
            if close_conn:
                conn.close()

    def _has_spatial_index(
        self,
        collection_id: str,
        geom_column: str,
        conn=None
    ) -> bool:
        """
        Check if spatial index (GIST) exists on geometry column.

        Args:
            collection_id: Table name
            geom_column: Geometry column name
            conn: Existing connection (optional)

        Returns:
            True if GIST index exists
        """
        query = sql.SQL("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = %s
                AND tablename = %s
                AND indexdef LIKE %s
        """)

        close_conn = False
        if conn is None:
            conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
            close_conn = True

        try:
            with conn.cursor() as cur:
                # Check for GIST index on this column
                cur.execute(query, (self.config.ogc_schema, collection_id, f'%USING gist%{geom_column}%'))
                result = cur.fetchone()
                return result is not None
        finally:
            if close_conn:
                conn.close()

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _parse_extent_to_bbox(self, extent_str: str) -> Optional[List[float]]:
        """
        Parse PostGIS BOX string to bbox array.

        Args:
            extent_str: BOX string like "BOX(minx miny,maxx maxy)"

        Returns:
            [minx, miny, maxx, maxy] or None
        """
        if not extent_str:
            return None

        try:
            # Remove "BOX(" prefix and ")" suffix
            coords_str = extent_str.replace("BOX(", "").replace(")", "")
            # Split by comma
            parts = coords_str.split(",")
            # Parse min and max points
            min_point = parts[0].strip().split()
            max_point = parts[1].strip().split()

            return [
                float(min_point[0]),  # minx
                float(min_point[1]),  # miny
                float(max_point[0]),  # maxx
                float(max_point[1])   # maxy
            ]
        except (IndexError, ValueError) as e:
            logger.warning(f"Failed to parse extent '{extent_str}': {e}")
            return None

    def _convert_to_geojson_features(
        self,
        rows: List[Dict[str, Any]],
        geom_column: str
    ) -> List[Dict[str, Any]]:
        """
        Convert database rows to GeoJSON-like feature dicts.

        Args:
            rows: Database rows (with 'geometry' column as GeoJSON string)
            geom_column: Name of geometry column (for removal from properties)

        Returns:
            List of GeoJSON feature dicts
        """
        import json

        features = []
        for row in rows:
            # Extract geometry JSON string
            geom_json_str = row.pop('geometry', None)
            geom_json = json.loads(geom_json_str) if geom_json_str else None

            # Remove original geometry column if present
            row.pop(geom_column, None)

            # Build GeoJSON feature
            feature = {
                'type': 'Feature',
                'geometry': geom_json,
                'properties': dict(row)  # All remaining columns as properties
            }

            features.append(feature)

        return features
