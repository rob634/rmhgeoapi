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
                insert_start = time.time()
                cur.execute(sql.SQL("""
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
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('grids')
                ), (grid_id, grid_type, source_job_id))

                rowcount = cur.rowcount
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
