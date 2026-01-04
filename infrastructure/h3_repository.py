# ============================================================================
# H3 REPOSITORY
# ============================================================================
# STATUS: Infrastructure - H3 hexagonal grid data access layer
# PURPOSE: Safe PostgreSQL operations for h3.grids, h3.cells, and h3.zonal_stats
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
H3 Repository - Safe PostgreSQL Operations for H3 Hexagonal Grids.

Provides H3-specific repository implementation inheriting from PostgreSQLRepository.
Ensures safe SQL composition using psycopg.sql.Identifier() to prevent SQL injection.

Key Features:
    - Safe SQL composition using sql.Identifier() for schema/table/column names
    - Bulk insert operations using executemany() for performance
    - Spatial attribute updates via PostGIS ST_Intersects
    - Reference filter management for cascading children generation
    - Grid metadata tracking for bootstrap progress monitoring
    - Idempotency support via grid_exists checks

Schema:
    h3.grids - H3 hexagonal grid cells (resolutions 2-7)
    h3.reference_filters - Parent ID sets for child generation
    h3.grid_metadata - Bootstrap progress tracking

Exports:
    H3Repository: Repository for h3.grids operations
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from config import get_config

# Logger setup
logger = logging.getLogger(__name__)


class H3Repository(PostgreSQLRepository):
    """
    H3-specific repository for h3.grids operations.

    Inherits connection management, safe SQL composition, and transaction
    support from PostgreSQLRepository. All queries use sql.Identifier() for
    injection prevention.

    Schema: h3 (dedicated schema for system-generated H3 grids)

    Usage:
        repo = H3Repository()
        cells = [{'h3_index': 123, 'resolution': 2, 'geom_wkt': 'POLYGON(...)'}]
        rows_inserted = repo.insert_h3_cells(cells, grid_id='land_res2')
    """

    def __init__(self):
        """
        Initialize H3Repository with h3 schema.

        Uses parent PostgreSQLRepository for connection management,
        error handling, and transaction support.
        """
        # Initialize with h3 schema (separate from geo schema for user data)
        super().__init__(schema_name='h3')
        logger.info("✅ H3Repository initialized (schema: h3)")

    def insert_h3_cells(
        self,
        cells: List[Dict[str, Any]],
        grid_id: str,
        grid_type: str = 'land',
        source_job_id: Optional[str] = None
    ) -> int:
        """
        Bulk insert H3 cells using COPY + staging table.

        Uses PostgreSQL COPY FROM STDIN for 10-50x faster bulk loading
        compared to executemany(). Data is staged in a temp table then
        inserted with ST_GeomFromText() conversion.

        Parameters:
        ----------
        cells : List[Dict[str, Any]]
            List of H3 cell dictionaries with keys:
            - h3_index: int (H3 cell index as 64-bit integer)
            - resolution: int (H3 resolution level 0-15)
            - geom_wkt: str (WKT POLYGON string)
            - parent_res2: Optional[int] (top-level parent for partitioning)
            - parent_h3_index: Optional[int] (immediate parent)

        grid_id : str
            Grid identifier (e.g., 'land_res2', 'land_res6')

        grid_type : str, default='land'
            Grid type classification ('global', 'land', 'ocean', 'custom')

        source_job_id : Optional[str]
            CoreMachine job ID that created this grid

        Returns:
        -------
        int
            Number of rows inserted (excludes conflicts)

        Performance:
        -----------
        - 196K cells: ~30-60 sec (vs ~10 min with executemany)
        - Uses unlogged temp table (no WAL overhead)
        - Single INSERT...SELECT for batch index updates

        Example:
        -------
        >>> cells = [
        ...     {'h3_index': 585961714876129279, 'resolution': 2,
        ...      'geom_wkt': 'POLYGON((...))', 'parent_res2': None}
        ... ]
        >>> rows = repo.insert_h3_cells(cells, grid_id='land_res2')
        >>> print(f"Inserted {rows} cells")
        """
        from io import StringIO
        import time

        if not cells:
            logger.warning("⚠️ insert_h3_cells called with empty cells list")
            return 0

        start_time = time.time()
        cell_count = len(cells)
        logger.info(f"📦 Bulk inserting {cell_count:,} H3 cells using COPY...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # STEP 1: Create temp table (unlogged, no indexes, drops on commit)
                cur.execute("""
                    CREATE TEMP TABLE h3_staging (
                        h3_index BIGINT,
                        resolution SMALLINT,
                        geom_wkt TEXT,
                        parent_res2 BIGINT,
                        parent_h3_index BIGINT
                    ) ON COMMIT DROP
                """)

                # STEP 2: Build tab-separated data for COPY
                buffer = StringIO()
                for cell in cells:
                    h3_index = cell['h3_index']
                    resolution = cell['resolution']
                    geom_wkt = cell['geom_wkt']
                    # Use \N for NULL values in COPY format
                    parent_res2 = cell.get('parent_res2')
                    parent_res2_str = str(parent_res2) if parent_res2 is not None else '\\N'
                    parent_h3 = cell.get('parent_h3_index')
                    parent_h3_str = str(parent_h3) if parent_h3 is not None else '\\N'

                    buffer.write(f"{h3_index}\t{resolution}\t{geom_wkt}\t{parent_res2_str}\t{parent_h3_str}\n")

                buffer.seek(0)
                copy_start = time.time()

                # STEP 3: COPY FROM STDIN to staging table
                with cur.copy("COPY h3_staging (h3_index, resolution, geom_wkt, parent_res2, parent_h3_index) FROM STDIN") as copy:
                    copy.write(buffer.read())

                copy_time = time.time() - copy_start
                logger.debug(f"   COPY to staging: {copy_time:.2f}s")

                # STEP 4: INSERT...SELECT with geometry conversion
                # Use RETURNING to get accurate count (psycopg3 rowcount unreliable with ON CONFLICT)
                insert_start = time.time()
                cur.execute(sql.SQL("""
                    WITH inserted AS (
                        INSERT INTO {schema}.{table}
                            (h3_index, resolution, geom, grid_id, grid_type,
                             parent_res2, parent_h3_index, source_job_id)
                        SELECT
                            h3_index,
                            resolution,
                            ST_GeomFromText(geom_wkt, 4326),
                            %s,
                            %s,
                            parent_res2,
                            parent_h3_index,
                            %s
                        FROM h3_staging
                        ON CONFLICT (h3_index, grid_id) DO NOTHING
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM inserted
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('grids')
                ), (grid_id, grid_type, source_job_id))

                rowcount = cur.fetchone()['count']
                insert_time = time.time() - insert_start
                logger.debug(f"   INSERT...SELECT: {insert_time:.2f}s")

                # Commit (temp table auto-drops due to ON COMMIT DROP)
                conn.commit()

        total_time = time.time() - start_time
        rate = cell_count / total_time if total_time > 0 else 0
        logger.info(f"✅ Inserted {rowcount:,} H3 cells in {total_time:.2f}s ({rate:,.0f} cells/sec)")

        return rowcount

    def get_parent_ids(self, grid_id: str) -> List[Tuple[int, Optional[int]]]:
        """
        Load parent H3 indices for a grid.

        Used by cascading children handlers to get parent IDs for
        generating next resolution level.

        Parameters:
        ----------
        grid_id : str
            Parent grid ID (e.g., 'land_res2', 'land_res5')

        Returns:
        -------
        List[Tuple[int, Optional[int]]]
            List of (h3_index, parent_res2) tuples, sorted by h3_index

        Example:
        -------
        >>> parent_ids = repo.get_parent_ids('land_res2')
        >>> print(f"Found {len(parent_ids)} parents")
        >>> # Use for generating children
        >>> for h3_index, parent_res2 in parent_ids:
        ...     children = h3.cell_to_children(h3_index, target_resolution)
        """
        query = sql.SQL("""
            SELECT h3_index, parent_res2
            FROM {schema}.{table}
            WHERE grid_id = %s
            ORDER BY h3_index
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('grids')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (grid_id,))
                results = cur.fetchall()

        # Convert dict_row to tuples (h3_index, parent_res2)
        parent_ids = [(row['h3_index'], row['parent_res2']) for row in results]

        logger.info(f"📊 Loaded {len(parent_ids)} parent IDs from h3.grids (grid_id={grid_id})")
        return parent_ids

    def get_parent_cells(
        self,
        parent_grid_id: str,
        batch_start: int = 0,
        batch_size: Optional[int] = None
    ) -> List[Tuple[int, Optional[int]]]:
        """
        Load parent H3 indices with batching support for parallel processing.

        Used by cascade handlers to split parent processing across multiple tasks.
        Supports LIMIT/OFFSET for batching large parent sets.

        Parameters:
        ----------
        parent_grid_id : str
            Parent grid ID (e.g., 'test_albania_res2', 'land_res2')
        batch_start : int, optional
            Starting offset for batch (default: 0)
        batch_size : int, optional
            Number of parents to return (default: None = all remaining)

        Returns:
        -------
        List[Tuple[int, Optional[int]]]
            List of (h3_index, parent_res2) tuples for the requested batch

        Example:
        -------
        >>> # Get first 10 parents
        >>> batch1 = repo.get_parent_cells('land_res2', batch_start=0, batch_size=10)
        >>> # Get next 10 parents
        >>> batch2 = repo.get_parent_cells('land_res2', batch_start=10, batch_size=10)
        >>> # Get all remaining parents
        >>> all_parents = repo.get_parent_cells('land_res2')
        """
        if batch_size is not None:
            query = sql.SQL("""
                SELECT h3_index, parent_res2
                FROM {schema}.{table}
                WHERE grid_id = %s
                ORDER BY h3_index
                LIMIT %s OFFSET %s
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('grids')
            )
            params = (parent_grid_id, batch_size, batch_start)
        else:
            query = sql.SQL("""
                SELECT h3_index, parent_res2
                FROM {schema}.{table}
                WHERE grid_id = %s
                ORDER BY h3_index
                OFFSET %s
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('grids')
            )
            params = (parent_grid_id, batch_start)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        # Convert dict_row to tuples (h3_index, parent_res2)
        parent_cells = [(row['h3_index'], row['parent_res2']) for row in results]

        logger.info(
            f"📊 Loaded {len(parent_cells)} parent cells from h3.grids "
            f"(grid_id={parent_grid_id}, batch={batch_start}:{batch_start + len(parent_cells)})"
        )
        return parent_cells

    def update_spatial_attributes(
        self,
        grid_id: str,
        spatial_filter_table: Optional[str] = None
    ) -> int:
        """
        Update country_code and is_land via spatial join.

        Uses ST_Intersects to find which H3 cells intersect country
        polygons, then updates country_code and is_land=TRUE.

        This is the ONE-TIME spatial operation in the H3 bootstrap
        process (only runs for resolution 2 reference grid).

        Parameters:
        ----------
        grid_id : str
            Grid ID to update (e.g., 'land_res2')

        spatial_filter_table : Optional[str], default=None
            Fully-qualified table name for spatial filter source
            (must be in format 'schema.table').
            If None, uses config.h3_spatial_filter_table with 'geo' schema prefix.

        Returns:
        -------
        int
            Number of cells updated with country attributes

        Example:
        -------
        >>> rows_updated = repo.update_spatial_attributes('land_res2')
        >>> print(f"Updated {rows_updated} cells with country_code")

        Notes:
        -----
        - This is an expensive operation (spatial intersection)
        - Only run once for reference grid (res 2)
        - Children inherit parent_res2, no spatial ops needed
        """
        # Use config default if not provided
        if spatial_filter_table is None:
            config = get_config()
            spatial_filter_table = f"geo.{config.h3_spatial_filter_table}"
            logger.info(f"🗺️  Using spatial filter table from config: {spatial_filter_table}")

        # Parse schema.table from spatial_filter_table
        if '.' not in spatial_filter_table:
            raise ValueError(
                f"spatial_filter_table must be 'schema.table' format, "
                f"got: {spatial_filter_table}"
            )

        filter_schema, filter_table = spatial_filter_table.split('.', 1)

        # SAFE: sql.Identifier() for all schema/table/column names
        query = sql.SQL("""
            UPDATE {h3_schema}.{h3_table} h
            SET
                country_code = c.iso3,
                is_land = TRUE,
                updated_at = NOW()
            FROM {filter_schema}.{filter_table} c
            WHERE h.grid_id = %s
              AND ST_Intersects(h.geom, c.geom)
        """).format(
            h3_schema=sql.Identifier('h3'),
            h3_table=sql.Identifier('grids'),
            filter_schema=sql.Identifier(filter_schema),
            filter_table=sql.Identifier(filter_table)
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (grid_id,))
                rowcount = cur.rowcount
                conn.commit()

        logger.info(
            f"✅ Updated {rowcount} cells with country_code via "
            f"spatial join (grid_id={grid_id}, filter={spatial_filter_table})"
        )
        return rowcount

    def get_cell_count(self, grid_id: str) -> int:
        """
        Count cells for a grid_id.

        Parameters:
        ----------
        grid_id : str
            Grid identifier (e.g., 'land_res2')

        Returns:
        -------
        int
            Number of cells in this grid

        Example:
        -------
        >>> count = repo.get_cell_count('land_res6')
        >>> print(f"Grid has {count:,} cells")
        """
        query = sql.SQL("""
            SELECT COUNT(*) as count
            FROM {schema}.{table}
            WHERE grid_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('grids')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (grid_id,))
                result = cur.fetchone()

        count = result['count'] if result else 0
        logger.debug(f"📊 Cell count for {grid_id}: {count:,}")
        return count

    def grid_exists(self, grid_id: str) -> bool:
        """
        Check if grid_id exists (for idempotency).

        Parameters:
        ----------
        grid_id : str
            Grid identifier to check

        Returns:
        -------
        bool
            True if grid exists, False otherwise

        Example:
        -------
        >>> if repo.grid_exists('land_res2'):
        ...     print("Grid already exists, skipping generation")
        """
        query = sql.SQL("""
            SELECT EXISTS(
                SELECT 1 FROM {schema}.{table}
                WHERE grid_id = %s
                LIMIT 1
            ) as exists
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('grids')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (grid_id,))
                result = cur.fetchone()

        exists = result['exists'] if result else False
        logger.debug(f"🔍 Grid exists check: {grid_id} = {exists}")
        return exists

    def insert_reference_filter(
        self,
        filter_name: str,
        resolution: int,
        h3_indices: List[int],
        source_grid_id: str,
        source_job_id: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """
        Insert to h3.reference_filters table.

        Stores parent H3 indices as PostgreSQL BIGINT[] array.
        Used for cascading children generation (e.g., land_res2 parents
        for generating res 3-7).

        Parameters:
        ----------
        filter_name : str
            Unique filter identifier (e.g., 'land_res2')

        resolution : int
            Reference resolution level (0-15, typically 2 for bootstrap)

        h3_indices : List[int]
            List of parent H3 indices to store

        source_grid_id : str
            Source grid_id from h3.grids (e.g., 'land_res2')

        source_job_id : Optional[str]
            CoreMachine job ID that created this filter

        description : Optional[str]
            Human-readable description of filter

        Returns:
        -------
        bool
            True if inserted, False if already exists (conflict)

        Example:
        -------
        >>> land_cells = [585961714876129279, 585961714876129280, ...]
        >>> inserted = repo.insert_reference_filter(
        ...     filter_name='land_res2',
        ...     resolution=2,
        ...     h3_indices=land_cells,
        ...     source_grid_id='land_res2',
        ...     source_job_id='bootstrap_job_123'
        ... )
        """
        query = sql.SQL("""
            INSERT INTO {schema}.{table}
                (filter_name, description, h3_indices, resolution, cell_count,
                 source_grid_id, source_job_id)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (filter_name) DO NOTHING
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('reference_filters')
        )

        cell_count = len(h3_indices)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (filter_name, description, h3_indices, resolution, cell_count,
                     source_grid_id, source_job_id)
                )
                rowcount = cur.rowcount
                conn.commit()

        inserted = rowcount > 0
        if inserted:
            logger.info(
                f"✅ Inserted reference filter: {filter_name} "
                f"(resolution={resolution}, cells={cell_count:,})"
            )
        else:
            logger.warning(f"⚠️ Reference filter already exists: {filter_name}")

        return inserted

    def get_reference_filter(self, filter_name: str) -> Optional[List[int]]:
        """
        Load h3_indices from h3.reference_filters.

        Parameters:
        ----------
        filter_name : str
            Filter identifier (e.g., 'land_res2')

        Returns:
        -------
        Optional[List[int]]
            List of parent H3 indices, or None if not found

        Example:
        -------
        >>> parent_ids = repo.get_reference_filter('land_res2')
        >>> if parent_ids:
        ...     print(f"Found {len(parent_ids)} parent IDs")
        ...     for parent_id in parent_ids:
        ...         children = h3.cell_to_children(parent_id, target_res)
        """
        query = sql.SQL("""
            SELECT h3_indices, cell_count
            FROM {schema}.{table}
            WHERE filter_name = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('reference_filters')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (filter_name,))
                result = cur.fetchone()

        if not result:
            logger.warning(f"⚠️ Reference filter not found: {filter_name}")
            return None

        h3_indices = result['h3_indices']
        cell_count = result['cell_count']

        logger.info(f"📊 Loaded reference filter: {filter_name} ({cell_count:,} cells)")
        return h3_indices

    def update_grid_metadata(
        self,
        grid_id: str,
        resolution: int,
        status: str,
        cell_count: int,
        land_cell_count: Optional[int] = None,
        source_job_id: Optional[str] = None,
        parent_grid_id: Optional[str] = None
    ) -> None:
        """
        Update h3.grid_metadata for bootstrap tracking.

        Inserts or updates metadata for a grid, tracking bootstrap
        progress and completion status.

        Parameters:
        ----------
        grid_id : str
            Grid identifier (e.g., 'land_res2')

        resolution : int
            H3 resolution level (2-7)

        status : str
            Bootstrap status ('pending', 'processing', 'completed', 'failed')

        cell_count : int
            Total number of cells in this grid

        land_cell_count : Optional[int]
            Number of cells with is_land=true

        source_job_id : Optional[str]
            CoreMachine job ID that generated this grid

        parent_grid_id : Optional[str]
            Parent grid ID (e.g., 'land_res2' for 'land_res3')

        Example:
        -------
        >>> repo.update_grid_metadata(
        ...     grid_id='land_res2',
        ...     resolution=2,
        ...     status='completed',
        ...     cell_count=5882,
        ...     land_cell_count=2847,
        ...     source_job_id='bootstrap_job_123'
        ... )
        """
        query = sql.SQL("""
            INSERT INTO {schema}.{table}
                (grid_id, resolution, status, cell_count, land_cell_count,
                 source_job_id, parent_grid_id, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (grid_id) DO UPDATE SET
                resolution = EXCLUDED.resolution,
                status = EXCLUDED.status,
                cell_count = EXCLUDED.cell_count,
                land_cell_count = EXCLUDED.land_cell_count,
                source_job_id = EXCLUDED.source_job_id,
                parent_grid_id = EXCLUDED.parent_grid_id,
                updated_at = NOW()
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('grid_metadata')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (grid_id, resolution, status, cell_count, land_cell_count,
                     source_job_id, parent_grid_id)
                )
                conn.commit()

        logger.info(
            f"✅ Updated grid metadata: {grid_id} "
            f"(resolution={resolution}, cells={cell_count:,}, land={land_cell_count}, status={status})"
        )

    def get_grid_metadata(self, grid_id: str) -> Optional[Dict[str, Any]]:
        """
        Get grid metadata for a grid_id.

        Parameters:
        ----------
        grid_id : str
            Grid identifier

        Returns:
        -------
        Optional[Dict[str, Any]]
            Grid metadata dict or None if not found

        Example:
        -------
        >>> metadata = repo.get_grid_metadata('land_res6')
        >>> if metadata:
        ...     print(f"Status: {metadata['generation_status']}")
        ...     print(f"Cells: {metadata['cell_count']:,}")
        """
        query = sql.SQL("""
            SELECT
                grid_id, resolution, parent_grid_id, cell_count,
                generation_status, generation_job_id,
                created_at, updated_at
            FROM {schema}.{table}
            WHERE grid_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('grid_metadata')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (grid_id,))
                result = cur.fetchone()

        if result:
            logger.debug(f"📊 Grid metadata: {grid_id} - {result['generation_status']}")
        else:
            logger.debug(f"⚠️ Grid metadata not found: {grid_id}")

        return dict(result) if result else None

    # ========================================================================
    # NORMALIZED SCHEMA METHODS (h3.cells, h3.cell_admin0)
    # ========================================================================
    # These methods support the normalized H3 schema where:
    # - h3.cells stores unique geometry per h3_index (PRIMARY KEY)
    # - h3.cell_admin0 maps cells to countries (1:N relationship)
    # ========================================================================

    def insert_cells(
        self,
        cells: List[Dict[str, Any]],
        source_job_id: Optional[str] = None
    ) -> int:
        """
        Bulk insert H3 cells into normalized h3.cells table.

        Uses COPY + staging for performance. Cells are deduplicated by h3_index
        (PRIMARY KEY constraint with ON CONFLICT DO NOTHING).

        Parameters:
        ----------
        cells : List[Dict[str, Any]]
            List of H3 cell dictionaries with keys:
            - h3_index: int (H3 cell index as 64-bit integer)
            - resolution: int (H3 resolution level 0-15)
            - geom_wkt: str (WKT POLYGON string)
            - parent_h3_index: Optional[int] (immediate parent)
            - is_land: Optional[bool] (land classification)

        source_job_id : Optional[str]
            Job ID that created these cells

        Returns:
        -------
        int
            Number of NEW rows inserted (excludes duplicates)
        """
        from io import StringIO
        import time

        if not cells:
            logger.warning("⚠️ insert_cells called with empty cells list")
            return 0

        start_time = time.time()
        cell_count = len(cells)
        logger.info(f"📦 Bulk inserting {cell_count:,} cells into h3.cells...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # STEP 1: Create temp staging table
                cur.execute("""
                    CREATE TEMP TABLE h3_cells_staging (
                        h3_index BIGINT,
                        resolution SMALLINT,
                        geom_wkt TEXT,
                        parent_h3_index BIGINT,
                        is_land BOOLEAN
                    ) ON COMMIT DROP
                """)

                # STEP 2: Build COPY data
                buffer = StringIO()
                for cell in cells:
                    h3_index = cell['h3_index']
                    resolution = cell['resolution']
                    geom_wkt = cell['geom_wkt']
                    parent_h3 = cell.get('parent_h3_index')
                    parent_h3_str = str(parent_h3) if parent_h3 is not None else '\\N'
                    is_land = cell.get('is_land')
                    is_land_str = str(is_land).lower() if is_land is not None else '\\N'

                    buffer.write(f"{h3_index}\t{resolution}\t{geom_wkt}\t{parent_h3_str}\t{is_land_str}\n")

                buffer.seek(0)

                # STEP 3: COPY to staging
                with cur.copy("COPY h3_cells_staging (h3_index, resolution, geom_wkt, parent_h3_index, is_land) FROM STDIN") as copy:
                    copy.write(buffer.read())

                # STEP 4: INSERT into h3.cells with deduplication
                cur.execute(sql.SQL("""
                    WITH inserted AS (
                        INSERT INTO {schema}.{table}
                            (h3_index, resolution, geom, parent_h3_index, is_land, source_job_id)
                        SELECT
                            h3_index,
                            resolution,
                            ST_GeomFromText(geom_wkt, 4326),
                            parent_h3_index,
                            is_land,
                            %s
                        FROM h3_cells_staging
                        ON CONFLICT (h3_index) DO NOTHING
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM inserted
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('cells')
                ), (source_job_id,))

                rowcount = cur.fetchone()['count']
                conn.commit()

        total_time = time.time() - start_time
        rate = cell_count / total_time if total_time > 0 else 0
        logger.info(f"✅ Inserted {rowcount:,} new cells into h3.cells in {total_time:.2f}s ({rate:,.0f} cells/sec)")
        if rowcount < cell_count:
            logger.info(f"   ({cell_count - rowcount:,} duplicates skipped)")

        return rowcount

    def insert_cell_admin0_mappings(
        self,
        mappings: List[Dict[str, Any]]
    ) -> int:
        """
        Bulk insert H3 cell to country (admin0) mappings.

        Parameters:
        ----------
        mappings : List[Dict[str, Any]]
            List of mapping dictionaries with keys:
            - h3_index: int (H3 cell index)
            - iso3: str (ISO 3166-1 alpha-3 country code)
            - coverage_pct: Optional[float] (0.0-1.0)

        Returns:
        -------
        int
            Number of mappings inserted
        """
        from io import StringIO
        import time

        if not mappings:
            logger.warning("⚠️ insert_cell_admin0_mappings called with empty list")
            return 0

        start_time = time.time()
        mapping_count = len(mappings)
        logger.info(f"📦 Inserting {mapping_count:,} cell_admin0 mappings...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Create temp staging table
                cur.execute("""
                    CREATE TEMP TABLE admin0_staging (
                        h3_index BIGINT,
                        iso3 VARCHAR(3),
                        coverage_pct NUMERIC(5,4)
                    ) ON COMMIT DROP
                """)

                # Build COPY data
                buffer = StringIO()
                for m in mappings:
                    h3_index = m['h3_index']
                    iso3 = m['iso3']
                    coverage_pct = m.get('coverage_pct')
                    coverage_str = str(coverage_pct) if coverage_pct is not None else '\\N'
                    buffer.write(f"{h3_index}\t{iso3}\t{coverage_str}\n")

                buffer.seek(0)

                # COPY to staging
                with cur.copy("COPY admin0_staging (h3_index, iso3, coverage_pct) FROM STDIN") as copy:
                    copy.write(buffer.read())

                # INSERT with deduplication
                cur.execute(sql.SQL("""
                    WITH inserted AS (
                        INSERT INTO {schema}.{table}
                            (h3_index, iso3, coverage_pct)
                        SELECT h3_index, iso3, coverage_pct
                        FROM admin0_staging
                        ON CONFLICT (h3_index, iso3) DO NOTHING
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM inserted
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('cell_admin0')
                ))

                rowcount = cur.fetchone()['count']
                conn.commit()

        total_time = time.time() - start_time
        logger.info(f"✅ Inserted {rowcount:,} cell_admin0 mappings in {total_time:.2f}s")

        return rowcount

    def get_cells_by_resolution(
        self,
        resolution: int,
        batch_start: int = 0,
        batch_size: Optional[int] = None
    ) -> List[Tuple[int, Optional[int]]]:
        """
        Load H3 cells by resolution from normalized h3.cells table.

        Used for cascading children generation - replaces get_parent_cells
        for normalized schema.

        Parameters:
        ----------
        resolution : int
            H3 resolution level (0-15)
        batch_start : int
            Starting offset for batch (default: 0)
        batch_size : Optional[int]
            Number of cells to return (default: None = all)

        Returns:
        -------
        List[Tuple[int, Optional[int]]]
            List of (h3_index, parent_h3_index) tuples
        """
        if batch_size is not None:
            query = sql.SQL("""
                SELECT h3_index, parent_h3_index
                FROM {schema}.{table}
                WHERE resolution = %s
                ORDER BY h3_index
                LIMIT %s OFFSET %s
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('cells')
            )
            params = (resolution, batch_size, batch_start)
        else:
            query = sql.SQL("""
                SELECT h3_index, parent_h3_index
                FROM {schema}.{table}
                WHERE resolution = %s
                ORDER BY h3_index
                OFFSET %s
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('cells')
            )
            params = (resolution, batch_start)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        cells = [(row['h3_index'], row['parent_h3_index']) for row in results]
        logger.info(f"📊 Loaded {len(cells)} cells from h3.cells (resolution={resolution})")
        return cells

    def get_cell_count_by_resolution(self, resolution: int) -> int:
        """
        Count cells by resolution in normalized h3.cells table.

        Parameters:
        ----------
        resolution : int
            H3 resolution level (0-15)

        Returns:
        -------
        int
            Number of cells at this resolution
        """
        query = sql.SQL("""
            SELECT COUNT(*) as count
            FROM {schema}.{table}
            WHERE resolution = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('cells')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (resolution,))
                result = cur.fetchone()

        count = result['count'] if result else 0
        logger.debug(f"📊 Cell count for resolution {resolution}: {count:,}")
        return count

    def get_cells_with_admin0(
        self,
        iso3: str,
        resolution: Optional[int] = None
    ) -> List[int]:
        """
        Get H3 cell indices that belong to a country.

        Parameters:
        ----------
        iso3 : str
            ISO 3166-1 alpha-3 country code (e.g., 'ALB', 'MNE')
        resolution : Optional[int]
            Filter by resolution (optional)

        Returns:
        -------
        List[int]
            List of h3_index values for the country
        """
        if resolution is not None:
            query = sql.SQL("""
                SELECT c.h3_index
                FROM {schema}.cells c
                JOIN {schema}.cell_admin0 a ON c.h3_index = a.h3_index
                WHERE a.iso3 = %s AND c.resolution = %s
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            params = (iso3, resolution)
        else:
            query = sql.SQL("""
                SELECT c.h3_index
                FROM {schema}.cells c
                JOIN {schema}.cell_admin0 a ON c.h3_index = a.h3_index
                WHERE a.iso3 = %s
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            params = (iso3,)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        h3_indices = [row['h3_index'] for row in results]
        logger.info(f"📊 Found {len(h3_indices)} cells for {iso3}" +
                   (f" at resolution {resolution}" if resolution else ""))
        return h3_indices

    # ========================================================================
    # DATASET REGISTRY METHODS (h3.dataset_registry) - 22 DEC 2025
    # ========================================================================
    # Methods for managing the comprehensive dataset catalog.
    # Supports Planetary Computer, Azure Blob, and direct URL sources.
    # Theme column links to zonal_stats partitioning for scalability.
    # ========================================================================

    # Valid themes for partitioning (must match h3_schema.py)
    VALID_THEMES = ['terrain', 'water', 'climate', 'demographics', 'infrastructure', 'landcover', 'vegetation', 'agriculture']

    def register_dataset(
        self,
        id: str,
        display_name: str,
        theme: str,
        data_category: str,
        source_type: str,
        source_config: Dict[str, Any],
        stat_types: Optional[List[str]] = None,
        unit: Optional[str] = None,
        description: Optional[str] = None,
        source_name: Optional[str] = None,
        source_url: Optional[str] = None,
        source_license: Optional[str] = None,
        recommended_h3_res: Optional[List[int]] = None,
        nodata_value: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Register a dataset in h3.dataset_registry (UPSERT).

        Call this BEFORE running zonal stats aggregation to ensure the dataset
        is registered and theme is available for partition routing.

        Parameters:
        ----------
        id : str
            Unique dataset identifier (e.g., 'copdem_glo30', 'worldpop_2020')
        display_name : str
            Human-readable name (e.g., 'Copernicus DEM GLO-30')
        theme : str
            Partition key. Must be one of:
            terrain, water, climate, demographics, infrastructure, landcover, vegetation
        data_category : str
            Specific category (e.g., 'elevation', 'population', 'flood_depth')
        source_type : str
            One of: 'planetary_computer', 'azure', 'url'
        source_config : Dict[str, Any]
            Source-specific config. Examples:
            - planetary_computer: {"collection": "cop-dem-glo-30", "item_pattern": "...", "asset": "data"}
            - azure: {"container": "silver-cogs", "blob_path": "population/worldpop.tif"}
            - url: {"url": "https://example.com/data.tif"}
        stat_types : Optional[List[str]]
            Available stats (default: ['mean'])
        unit : Optional[str]
            Unit of measurement (e.g., 'meters', 'people')
        description : Optional[str]
            Detailed description
        source_name : Optional[str]
            Data provider (e.g., 'Microsoft Planetary Computer')
        source_url : Optional[str]
            Link to documentation
        source_license : Optional[str]
            SPDX license (e.g., 'CC-BY-4.0')
        recommended_h3_res : Optional[List[int]]
            Recommended H3 resolutions (e.g., [5, 6, 7])
        nodata_value : Optional[float]
            Nodata value for raster

        Returns:
        -------
        Dict with 'id', 'theme', 'created' (bool), 'updated_at'

        Raises:
        ------
        ValueError: If theme or source_type is invalid

        Example:
        -------
        >>> result = repo.register_dataset(
        ...     id='copdem_glo30',
        ...     display_name='Copernicus DEM GLO-30',
        ...     theme='terrain',
        ...     data_category='elevation',
        ...     source_type='planetary_computer',
        ...     source_config={
        ...         'collection': 'cop-dem-glo-30',
        ...         'item_pattern': 'Copernicus_DSM_COG_10_N{lat}_00_E{lon}_00_DEM',
        ...         'asset': 'data'
        ...     },
        ...     stat_types=['mean', 'min', 'max', 'std'],
        ...     unit='meters'
        ... )
        """
        import json

        # Validate theme
        if theme not in self.VALID_THEMES:
            raise ValueError(f"Invalid theme '{theme}'. Must be one of: {self.VALID_THEMES}")

        # Validate source_type
        valid_source_types = ['planetary_computer', 'azure', 'url']
        if source_type not in valid_source_types:
            raise ValueError(f"Invalid source_type '{source_type}'. Must be one of: {valid_source_types}")

        # Default stat_types
        if stat_types is None:
            stat_types = ['mean']

        query = sql.SQL("""
            INSERT INTO {schema}.{table} (
                id, display_name, description, theme, data_category,
                source_type, source_config, stat_types, unit,
                source_name, source_url, source_license,
                recommended_h3_res, nodata_value,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                theme = EXCLUDED.theme,
                data_category = EXCLUDED.data_category,
                source_type = EXCLUDED.source_type,
                source_config = EXCLUDED.source_config,
                stat_types = EXCLUDED.stat_types,
                unit = EXCLUDED.unit,
                source_name = EXCLUDED.source_name,
                source_url = EXCLUDED.source_url,
                source_license = EXCLUDED.source_license,
                recommended_h3_res = EXCLUDED.recommended_h3_res,
                nodata_value = EXCLUDED.nodata_value,
                updated_at = NOW()
            RETURNING id, theme, (xmax = 0) AS created, updated_at
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    id, display_name, description, theme, data_category,
                    source_type, json.dumps(source_config), stat_types, unit,
                    source_name, source_url, source_license,
                    recommended_h3_res, nodata_value
                ))
                result = cur.fetchone()
                conn.commit()

        action = "Registered" if result['created'] else "Updated"
        logger.info(f"✅ {action} dataset: {id} (theme={theme}, source={source_type})")

        return dict(result)

    def get_dataset(self, id: str) -> Optional[Dict[str, Any]]:
        """
        Get dataset metadata from h3.dataset_registry.

        Parameters:
        ----------
        id : str
            Dataset identifier

        Returns:
        -------
        Optional[Dict[str, Any]]
            Dataset entry or None if not found
        """
        query = sql.SQL("""
            SELECT *
            FROM {schema}.{table}
            WHERE id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (id,))
                result = cur.fetchone()

        if result:
            logger.debug(f"📊 Found dataset: {id} (theme={result['theme']})")
            return dict(result)
        else:
            logger.debug(f"⚠️ Dataset not found: {id}")
            return None

    def get_dataset_theme(self, dataset_id: str) -> Optional[str]:
        """
        Get the theme for a dataset (needed for zonal_stats partition routing).

        Parameters:
        ----------
        dataset_id : str
            Dataset identifier

        Returns:
        -------
        Optional[str]
            Theme string or None if dataset not found
        """
        query = sql.SQL("""
            SELECT theme FROM {schema}.{table} WHERE id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (dataset_id,))
                result = cur.fetchone()

        return result['theme'] if result else None

    def update_dataset_aggregation_state(
        self,
        id: str,
        job_id: str,
        cells_aggregated: int
    ) -> bool:
        """
        Update aggregation state after job completes.

        Parameters:
        ----------
        id : str
            Dataset identifier
        job_id : str
            Job ID that computed the stats
        cells_aggregated : int
            Number of cells with stats

        Returns:
        -------
        bool
            True if updated, False if not found
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET
                last_aggregation_at = NOW(),
                aggregation_job_id = %s,
                cells_aggregated = %s,
                updated_at = NOW()
            WHERE id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, cells_aggregated, id))
                rowcount = cur.rowcount
                conn.commit()

        if rowcount > 0:
            logger.info(f"✅ Updated aggregation state for {id}: job={job_id[:8]}..., cells={cells_aggregated:,}")
        else:
            logger.warning(f"⚠️ Dataset not found: {id}")

        return rowcount > 0

    def list_datasets(
        self,
        theme: Optional[str] = None,
        source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List datasets, optionally filtered by theme or source_type.

        Parameters:
        ----------
        theme : Optional[str]
            Filter by theme (terrain, water, etc.)
        source_type : Optional[str]
            Filter by source (planetary_computer, azure, url)

        Returns:
        -------
        List[Dict[str, Any]]
            List of dataset entries
        """
        # Build WHERE conditions using helper (24 DEC 2025 - injection-safe)
        where_conditions = {}
        if theme:
            where_conditions["theme"] = theme
        if source_type:
            where_conditions["source_type"] = source_type

        # Use execute_select helper for safe SQL composition
        return self.execute_select(
            table="dataset_registry",
            columns=["id", "display_name", "theme", "data_category", "source_type",
                     "stat_types", "unit", "last_aggregation_at", "cells_aggregated"],
            where=where_conditions if where_conditions else None,
            order_by=["theme", "id"],
            schema="h3"
        )

    # ========================================================================
    # LEGACY STAT REGISTRY METHODS (deprecated - use dataset_registry)
    # ========================================================================

    def register_stat_dataset(
        self,
        id: str,
        stat_category: str,
        display_name: str,
        description: Optional[str] = None,
        source_name: Optional[str] = None,
        source_url: Optional[str] = None,
        source_license: Optional[str] = None,
        resolution_range: Optional[List[int]] = None,
        stat_types: Optional[List[str]] = None,
        unit: Optional[str] = None,
        theme: str = 'terrain'
    ) -> bool:
        """
        Register a new dataset in the dataset_registry metadata catalog.

        Creates an entry for a new aggregation dataset BEFORE computing stats.
        This enables FK validation when inserting into zonal_stats/point_stats.

        Parameters:
        ----------
        id : str
            Unique dataset identifier (e.g., 'worldpop_2020', 'acled_2024')
        stat_category : str
            Data category (e.g., 'elevation', 'population', 'precipitation')
            Maps to data_category column in schema.
        display_name : str
            Human-readable name (e.g., 'WorldPop 2020 Population')
        description : Optional[str]
            Detailed explanation of the dataset
        source_name : Optional[str]
            Data source organization (e.g., 'WorldPop', 'ACLED')
        source_url : Optional[str]
            Link to original data source
        source_license : Optional[str]
            License identifier (e.g., 'CC-BY-4.0', 'ODC-BY')
        resolution_range : Optional[List[int]]
            Available H3 resolutions (e.g., [5, 6, 7])
        stat_types : Optional[List[str]]
            Available stat types (e.g., ['mean', 'sum', 'count'])
        unit : Optional[str]
            Unit of measurement (e.g., 'people/km²', 'count')
        theme : str
            Theme for partitioning (terrain, water, climate, demographics,
            infrastructure, landcover, vegetation). Default: 'terrain'.

        Returns:
        -------
        bool
            True if registered, False if already exists (conflict)

        Example:
        -------
        >>> repo.register_stat_dataset(
        ...     id='worldpop_2020',
        ...     stat_category='population',
        ...     display_name='WorldPop 2020 Population Estimates',
        ...     description='Gridded population estimates at 100m resolution',
        ...     theme='demographics',
        ...     source_name='WorldPop',
        ...     source_url='https://www.worldpop.org/',
        ...     source_license='CC-BY-4.0',
        ...     resolution_range=[5, 6, 7],
        ...     stat_types=['sum', 'mean', 'count'],
        ...     unit='people'
        ... )
        """
        # Build minimal source_config JSONB (required by schema)
        source_config = {"registered_via": "register_stat_dataset"}

        query = sql.SQL("""
            INSERT INTO {schema}.{table} (
                id, display_name, description, theme, data_category,
                source_type, source_config,
                source_name, source_url, source_license,
                recommended_h3_res, stat_types, unit,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                theme = EXCLUDED.theme,
                data_category = EXCLUDED.data_category,
                source_name = EXCLUDED.source_name,
                source_url = EXCLUDED.source_url,
                source_license = EXCLUDED.source_license,
                recommended_h3_res = EXCLUDED.recommended_h3_res,
                stat_types = EXCLUDED.stat_types,
                unit = EXCLUDED.unit,
                updated_at = NOW()
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        import json

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    id, display_name, description, theme, stat_category,
                    'url', json.dumps(source_config),  # source_type defaults to 'url'
                    source_name, source_url, source_license,
                    resolution_range, stat_types, unit
                ))
                rowcount = cur.rowcount
                conn.commit()

        if rowcount > 0:
            logger.info(f"✅ Registered stat dataset: {id} (theme={theme}, category={stat_category})")
        else:
            logger.info(f"📝 Updated stat dataset: {id}")

        return rowcount > 0

    def update_dataset_registry_provenance(
        self,
        id: str,
        job_id: str,
        cell_count: int
    ) -> bool:
        """
        Update provenance information after aggregation job completes.

        Records when the dataset was last computed and by which job.

        Parameters:
        ----------
        id : str
            Dataset identifier (e.g., 'worldpop_2020')
        job_id : str
            Job ID that computed the stats
        cell_count : int
            Number of cells with this stat

        Returns:
        -------
        bool
            True if updated, False if dataset not found

        Example:
        -------
        >>> repo.update_dataset_registry_provenance(
        ...     id='worldpop_2020',
        ...     job_id='abc123...',
        ...     cell_count=176472
        ... )
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET
                last_aggregation_at = NOW(),
                aggregation_job_id = %s,
                cells_aggregated = %s,
                updated_at = NOW()
            WHERE id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, cell_count, id))
                rowcount = cur.rowcount
                conn.commit()

        if rowcount > 0:
            logger.info(f"✅ Updated provenance for {id}: job={job_id[:8]}..., cells={cell_count:,}")
        else:
            logger.warning(f"⚠️ Dataset not found in dataset_registry: {id}")

        return rowcount > 0

    def get_dataset_registry_entry(self, id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a registered dataset.

        Parameters:
        ----------
        id : str
            Dataset identifier

        Returns:
        -------
        Optional[Dict[str, Any]]
            Registry entry dict or None if not found
        """
        query = sql.SQL("""
            SELECT
                id, stat_category, display_name, description,
                source_name, source_url, source_license,
                resolution_range, stat_types, unit,
                last_aggregation_at, last_aggregation_job_id, cell_count,
                created_at, updated_at
            FROM {schema}.{table}
            WHERE id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('dataset_registry')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (id,))
                result = cur.fetchone()

        if result:
            logger.debug(f"📊 Loaded stat registry entry: {id}")
            return dict(result)
        else:
            logger.debug(f"⚠️ Stat registry entry not found: {id}")
            return None

    def list_registered_stats(
        self,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all registered datasets, optionally filtered by category.

        Parameters:
        ----------
        category : Optional[str]
            Filter by stat_category (e.g., 'raster_zonal', 'vector_point')

        Returns:
        -------
        List[Dict[str, Any]]
            List of registry entries

        Example:
        -------
        >>> all_stats = repo.list_registered_stats()
        >>> raster_stats = repo.list_registered_stats(category='raster_zonal')
        """
        if category:
            query = sql.SQL("""
                SELECT
                    id, stat_category, display_name, description,
                    source_name, source_license, unit,
                    resolution_range, stat_types,
                    last_aggregation_at, cell_count
                FROM {schema}.{table}
                WHERE stat_category = %s
                ORDER BY id
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('dataset_registry')
            )
            params = (category,)
        else:
            query = sql.SQL("""
                SELECT
                    id, stat_category, display_name, description,
                    source_name, source_license, unit,
                    resolution_range, stat_types,
                    last_aggregation_at, cell_count
                FROM {schema}.{table}
                ORDER BY stat_category, id
            """).format(
                schema=sql.Identifier('h3'),
                table=sql.Identifier('dataset_registry')
            )
            params = ()

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        entries = [dict(row) for row in results]
        logger.info(f"📊 Found {len(entries)} registered stat datasets" +
                   (f" (category={category})" if category else ""))
        return entries

    # ========================================================================
    # AGGREGATION METHODS (h3.zonal_stats, h3.point_stats)
    # ========================================================================
    # Methods for aggregating data to H3 cells and storing results.
    # ========================================================================

    def get_cells_for_aggregation(
        self,
        resolution: int,
        iso3: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        polygon_wkt: Optional[str] = None,
        batch_start: int = 0,
        batch_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Load H3 cells for aggregation with spatial scope filtering.

        Supports filtering by country (iso3), bounding box, or polygon.
        Priority: iso3 → bbox → polygon_wkt → all cells.

        Parameters:
        ----------
        resolution : int
            H3 resolution level (0-15)
        iso3 : Optional[str]
            ISO 3166-1 alpha-3 country code (e.g., 'GRC', 'ALB')
        bbox : Optional[List[float]]
            Bounding box [minx, miny, maxx, maxy]
        polygon_wkt : Optional[str]
            WKT polygon for custom scope
        batch_start : int
            Starting offset for batch (default: 0)
        batch_size : Optional[int]
            Number of cells to return (default: None = all)

        Returns:
        -------
        List[Dict[str, Any]]
            List of cell dicts with keys:
            - h3_index: int
            - resolution: int
            - geom_wkt: str (WKT for rasterio/shapely)

        Example:
        -------
        >>> cells = repo.get_cells_for_aggregation(resolution=6, iso3='GRC')
        >>> len(cells)
        176472
        >>> cells[0].keys()
        dict_keys(['h3_index', 'resolution', 'geom_wkt'])
        """
        # Build query based on scope
        if iso3:
            # Filter by country via cell_admin0 mapping
            base_query = sql.SQL("""
                SELECT c.h3_index, c.resolution, ST_AsText(c.geom) as geom_wkt
                FROM {schema}.cells c
                JOIN {schema}.cell_admin0 a ON c.h3_index = a.h3_index
                WHERE c.resolution = %s AND a.iso3 = %s
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            base_params = [resolution, iso3]
            scope_desc = f"iso3={iso3}"

        elif bbox:
            if len(bbox) != 4:
                raise ValueError(f"bbox must be [minx, miny, maxx, maxy], got: {bbox}")
            minx, miny, maxx, maxy = bbox
            base_query = sql.SQL("""
                SELECT c.h3_index, c.resolution, ST_AsText(c.geom) as geom_wkt
                FROM {schema}.cells c
                WHERE c.resolution = %s
                  AND ST_Intersects(c.geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            base_params = [resolution, minx, miny, maxx, maxy]
            scope_desc = f"bbox={bbox}"

        elif polygon_wkt:
            base_query = sql.SQL("""
                SELECT c.h3_index, c.resolution, ST_AsText(c.geom) as geom_wkt
                FROM {schema}.cells c
                WHERE c.resolution = %s
                  AND ST_Intersects(c.geom, ST_GeomFromText(%s, 4326))
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            base_params = [resolution, polygon_wkt]
            scope_desc = "polygon_wkt"

        else:
            # All cells at resolution
            base_query = sql.SQL("""
                SELECT c.h3_index, c.resolution, ST_AsText(c.geom) as geom_wkt
                FROM {schema}.cells c
                WHERE c.resolution = %s
                ORDER BY c.h3_index
            """).format(schema=sql.Identifier('h3'))
            base_params = [resolution]
            scope_desc = "global"

        # Add LIMIT/OFFSET if batching
        if batch_size is not None:
            # Need to reconstruct query with LIMIT/OFFSET
            query_str = base_query.as_string(self.repo) if hasattr(self, 'repo') else str(base_query)
            # Append LIMIT/OFFSET to base query
            full_query = sql.SQL("{} LIMIT %s OFFSET %s").format(base_query)
            params = base_params + [batch_size, batch_start]
        else:
            full_query = sql.SQL("{} OFFSET %s").format(base_query)
            params = base_params + [batch_start]

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(full_query, params)
                results = cur.fetchall()

        cells = [dict(row) for row in results]
        logger.info(
            f"📊 Loaded {len(cells):,} cells for aggregation "
            f"(resolution={resolution}, scope={scope_desc}, batch={batch_start})"
        )
        return cells

    def count_cells_for_aggregation(
        self,
        resolution: int,
        iso3: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        polygon_wkt: Optional[str] = None
    ) -> int:
        """
        Count H3 cells matching aggregation scope.

        Used for inventory stage to calculate batch ranges.

        Parameters:
        ----------
        resolution : int
            H3 resolution level (0-15)
        iso3 : Optional[str]
            ISO 3166-1 alpha-3 country code
        bbox : Optional[List[float]]
            Bounding box [minx, miny, maxx, maxy]
        polygon_wkt : Optional[str]
            WKT polygon for custom scope

        Returns:
        -------
        int
            Number of cells matching scope
        """
        # Build count query based on scope
        if iso3:
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.cells c
                JOIN {schema}.cell_admin0 a ON c.h3_index = a.h3_index
                WHERE c.resolution = %s AND a.iso3 = %s
            """).format(schema=sql.Identifier('h3'))
            params = (resolution, iso3)
            scope_desc = f"iso3={iso3}"

        elif bbox:
            minx, miny, maxx, maxy = bbox
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.cells c
                WHERE c.resolution = %s
                  AND ST_Intersects(c.geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
            """).format(schema=sql.Identifier('h3'))
            params = (resolution, minx, miny, maxx, maxy)
            scope_desc = f"bbox"

        elif polygon_wkt:
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.cells c
                WHERE c.resolution = %s
                  AND ST_Intersects(c.geom, ST_GeomFromText(%s, 4326))
            """).format(schema=sql.Identifier('h3'))
            params = (resolution, polygon_wkt)
            scope_desc = "polygon_wkt"

        else:
            query = sql.SQL("""
                SELECT COUNT(*) as count
                FROM {schema}.cells c
                WHERE c.resolution = %s
            """).format(schema=sql.Identifier('h3'))
            params = (resolution,)
            scope_desc = "global"

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone()

        count = result['count'] if result else 0
        logger.info(f"📊 Cell count for aggregation: {count:,} (resolution={resolution}, scope={scope_desc})")
        return count

    def insert_zonal_stats_batch(
        self,
        stats: List[Dict[str, Any]],
        theme: str,
        append_history: bool = False,
        source_job_id: Optional[str] = None
    ) -> int:
        """
        Bulk insert zonal statistics into h3.zonal_stats (PARTITIONED BY THEME).

        Uses COPY + staging for performance. Default behavior overwrites
        existing stats (ON CONFLICT DO UPDATE). Set append_history=True
        to skip conflicts (preserves historical data).

        IMPORTANT: Theme is REQUIRED - it's the partition key for billion-row scale.

        Parameters:
        ----------
        stats : List[Dict[str, Any]]
            List of stat dictionaries with keys:
            - h3_index: int
            - dataset_id: str
            - band: str (default: 'band_1')
            - stat_type: str ('mean', 'sum', 'min', 'max', 'count', 'std')
            - value: float
            - pixel_count: int (optional)
            - nodata_count: int (optional)

        theme : str
            REQUIRED partition key. Must be one of:
            terrain, water, climate, demographics, infrastructure, landcover, vegetation

        append_history : bool
            If True, skip conflicts (don't overwrite existing).
            If False, update existing values (default).

        source_job_id : Optional[str]
            Job ID for tracking

        Returns:
        -------
        int
            Number of rows inserted/updated

        Raises:
        ------
        ValueError: If theme is invalid

        Example:
        -------
        >>> stats = [
        ...     {"h3_index": 123, "dataset_id": "copdem_glo30", "stat_type": "mean", "value": 450.5},
        ...     {"h3_index": 123, "dataset_id": "copdem_glo30", "stat_type": "max", "value": 523.0}
        ... ]
        >>> rows = repo.insert_zonal_stats_batch(stats, theme='terrain')
        """
        from io import StringIO
        import time

        if not stats:
            logger.warning("⚠️ insert_zonal_stats_batch called with empty list")
            return 0

        # Validate theme (partition key)
        if theme not in self.VALID_THEMES:
            raise ValueError(f"Invalid theme '{theme}'. Must be one of: {self.VALID_THEMES}")

        start_time = time.time()
        stat_count = len(stats)
        logger.info(f"📦 Inserting {stat_count:,} zonal stats into '{theme}' partition (append_history={append_history})...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Create temp staging table (now includes theme)
                cur.execute("""
                    CREATE TEMP TABLE zonal_staging (
                        theme VARCHAR(50),
                        h3_index BIGINT,
                        dataset_id VARCHAR(100),
                        band VARCHAR(50),
                        stat_type VARCHAR(20),
                        value DOUBLE PRECISION,
                        pixel_count INTEGER,
                        nodata_count INTEGER
                    ) ON COMMIT DROP
                """)

                # Build COPY data (theme is constant for all rows in batch)
                buffer = StringIO()
                for stat in stats:
                    h3_index = stat['h3_index']
                    dataset_id = stat['dataset_id']
                    band = stat.get('band', 'band_1')
                    stat_type = stat['stat_type']
                    value = stat.get('value')
                    value_str = str(value) if value is not None else '\\N'
                    pixel_count = stat.get('pixel_count')
                    pixel_str = str(pixel_count) if pixel_count is not None else '\\N'
                    nodata_count = stat.get('nodata_count')
                    nodata_str = str(nodata_count) if nodata_count is not None else '\\N'

                    buffer.write(f"{theme}\t{h3_index}\t{dataset_id}\t{band}\t{stat_type}\t{value_str}\t{pixel_str}\t{nodata_str}\n")

                buffer.seek(0)

                # COPY to staging
                with cur.copy("COPY zonal_staging (theme, h3_index, dataset_id, band, stat_type, value, pixel_count, nodata_count) FROM STDIN") as copy:
                    copy.write(buffer.read())

                # Insert with conflict handling
                # Primary key is now (theme, h3_index, dataset_id, band, stat_type)
                if append_history:
                    # Skip conflicts (preserve existing)
                    cur.execute(sql.SQL("""
                        WITH inserted AS (
                            INSERT INTO {schema}.{table}
                                (theme, h3_index, dataset_id, band, stat_type, value, pixel_count, nodata_count, source_job_id)
                            SELECT
                                theme, h3_index, dataset_id, band, stat_type, value, pixel_count, nodata_count, %s
                            FROM zonal_staging
                            ON CONFLICT (theme, h3_index, dataset_id, band, stat_type) DO NOTHING
                            RETURNING 1
                        )
                        SELECT COUNT(*) FROM inserted
                    """).format(
                        schema=sql.Identifier('h3'),
                        table=sql.Identifier('zonal_stats')
                    ), (source_job_id,))
                else:
                    # Update existing (default behavior)
                    cur.execute(sql.SQL("""
                        WITH inserted AS (
                            INSERT INTO {schema}.{table}
                                (theme, h3_index, dataset_id, band, stat_type, value, pixel_count, nodata_count, source_job_id, computed_at)
                            SELECT
                                theme, h3_index, dataset_id, band, stat_type, value, pixel_count, nodata_count, %s, NOW()
                            FROM zonal_staging
                            ON CONFLICT (theme, h3_index, dataset_id, band, stat_type) DO UPDATE SET
                                value = EXCLUDED.value,
                                pixel_count = EXCLUDED.pixel_count,
                                nodata_count = EXCLUDED.nodata_count,
                                source_job_id = EXCLUDED.source_job_id,
                                computed_at = NOW()
                            RETURNING 1
                        )
                        SELECT COUNT(*) FROM inserted
                    """).format(
                        schema=sql.Identifier('h3'),
                        table=sql.Identifier('zonal_stats')
                    ), (source_job_id,))

                rowcount = cur.fetchone()['count']
                conn.commit()

        total_time = time.time() - start_time
        rate = stat_count / total_time if total_time > 0 else 0
        logger.info(f"✅ Inserted {rowcount:,} zonal stats into '{theme}' partition in {total_time:.2f}s ({rate:,.0f} stats/sec)")

        return rowcount

    def insert_point_stats_batch(
        self,
        stats: List[Dict[str, Any]],
        source_job_id: Optional[str] = None
    ) -> int:
        """
        Bulk insert point aggregation stats into h3.point_stats.

        Uses COPY + staging for performance. Updates existing counts
        on conflict.

        Parameters:
        ----------
        stats : List[Dict[str, Any]]
            List of stat dictionaries with keys:
            - h3_index: int
            - source_id: str
            - category: str (optional)
            - count: int

        source_job_id : Optional[str]
            Job ID for tracking

        Returns:
        -------
        int
            Number of rows inserted/updated

        Example:
        -------
        >>> stats = [
        ...     {"h3_index": 123, "source_id": "osm_pois", "category": "restaurant", "count": 15},
        ...     {"h3_index": 123, "source_id": "osm_pois", "category": "hospital", "count": 2}
        ... ]
        >>> rows = repo.insert_point_stats_batch(stats)
        """
        from io import StringIO
        import time

        if not stats:
            logger.warning("⚠️ insert_point_stats_batch called with empty list")
            return 0

        start_time = time.time()
        stat_count = len(stats)
        logger.info(f"📦 Inserting {stat_count:,} point stats...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Create temp staging table
                cur.execute("""
                    CREATE TEMP TABLE point_staging (
                        h3_index BIGINT,
                        source_id VARCHAR(100),
                        category VARCHAR(100),
                        count INTEGER
                    ) ON COMMIT DROP
                """)

                # Build COPY data
                buffer = StringIO()
                for stat in stats:
                    h3_index = stat['h3_index']
                    source_id = stat['source_id']
                    category = stat.get('category')
                    category_str = category if category else '\\N'
                    count = stat.get('count', 0)

                    buffer.write(f"{h3_index}\t{source_id}\t{category_str}\t{count}\n")

                buffer.seek(0)

                # COPY to staging
                with cur.copy("COPY point_staging (h3_index, source_id, category, count) FROM STDIN") as copy:
                    copy.write(buffer.read())

                # Insert with conflict update
                cur.execute(sql.SQL("""
                    WITH inserted AS (
                        INSERT INTO {schema}.{table}
                            (h3_index, source_id, category, count, source_job_id, computed_at)
                        SELECT
                            h3_index, source_id, category, count, %s, NOW()
                        FROM point_staging
                        ON CONFLICT (h3_index, source_id, category) DO UPDATE SET
                            count = EXCLUDED.count,
                            source_job_id = EXCLUDED.source_job_id,
                            computed_at = NOW()
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM inserted
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('point_stats')
                ), (source_job_id,))

                rowcount = cur.fetchone()['count']
                conn.commit()

        total_time = time.time() - start_time
        rate = stat_count / total_time if total_time > 0 else 0
        logger.info(f"✅ Inserted {rowcount:,} point stats in {total_time:.2f}s ({rate:,.0f} stats/sec)")

        return rowcount
