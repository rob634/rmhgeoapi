# ============================================================================
# H3 NATIVE STREAMING HANDLER
# ============================================================================
# STATUS: Services - High-performance H3 generation via h3-py C bindings
# PURPOSE: Stream H3 cells to PostGIS (3-4x faster than DuckDB approach)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
H3 Native Streaming Handler.

Generates H3 hexagonal grids using h3-py C bindings and streams to PostGIS.

Performance: 3-4x faster than DuckDB approach (15-25 sec vs 60-90 sec).

Architecture:
    - Generator pattern: Yields cells one at a time (memory efficient)
    - H3Repository: Managed identity authentication, safe SQL composition
    - Batch insertion: 1000 cells per batch (optimizes network round-trips)

Exports:
    h3_native_streaming_postgis: Task handler function
"""

import time
from typing import Dict, Any, Generator, List
import psutil
import logging

# Initialize logger
logger = logging.getLogger(__name__)


def generate_h3_cells_native(
    resolution: int,
    land_filter: bool = False
) -> Generator[Dict[str, Any], None, None]:
    """
    Generate H3 cells using h3-py with optional land filtering.

    Args:
        resolution: H3 resolution (0-15)
        land_filter: If True, filter to only land cells (NOT IMPLEMENTED YET)

    Yields:
        Dict containing:
            - h3_index: int (H3 cell index as 64-bit integer)
            - resolution: int (H3 resolution level)
            - geom_wkt: str (WKT POLYGON string)

    Performance:
        - Resolution 0: 122 cells, <1 second
        - Resolution 4: ~288,000 cells, 15-25 seconds
        - Memory: Generator pattern, only one cell in memory at a time
    """
    try:
        import h3
        from shapely.geometry import Polygon
    except ImportError as e:
        logger.error(f"Missing required library: {e}")
        raise RuntimeError(f"Cannot generate H3 cells - missing dependency: {e}")

    logger.info(f"Generating H3 cells at resolution {resolution} (land_filter={land_filter})")

    # Get all resolution 0 cells (122 base cells covering the globe)
    base_cells = h3.get_res0_cells()
    logger.debug(f"Starting from {len(base_cells)} base cells at resolution 0")

    total_generated = 0

    for base_cell in base_cells:
        # Get children at target resolution
        children = h3.cell_to_children(base_cell, resolution)

        for cell in children:
            # h3 v4 returns hex strings - convert to int for database storage
            if isinstance(cell, str):
                h3_index_int = h3.str_to_int(cell)
            else:
                h3_index_int = int(cell)

            # Get cell boundary as list of (lat, lon) tuples
            boundary = h3.cell_to_boundary(cell)

            # Shapely expects (lon, lat) order for WKT (not lat, lon!)
            coords = [(lon, lat) for lat, lon in boundary]

            # Create polygon and convert to WKT
            polygon = Polygon(coords)

            # TODO: Implement land filtering using Natural Earth data
            # For now, land_filter parameter is accepted but not applied
            if land_filter:
                # Placeholder for future land filtering logic
                # Could use shapely.contains() against Natural Earth land polygons
                pass

            total_generated += 1

            # Log progress every 10,000 cells
            if total_generated % 10000 == 0:
                logger.debug(f"Generated {total_generated} H3 cells...")

            yield {
                'h3_index': h3_index_int,
                'resolution': resolution,
                'geom_wkt': polygon.wkt
            }

    logger.info(f"H3 cell generation complete - total cells: {total_generated}")


def stream_to_postgis_sync(
    cells_generator: Generator[Dict[str, Any], None, None],
    grid_id: str,
    grid_type: str,
    source_job_id: str,
    batch_size: int = 1000
) -> int:
    """
    Stream H3 cells to PostGIS using H3Repository (managed identity safe).

    Uses synchronous batch insertion via H3Repository.insert_h3_cells().
    No connection pooling - each batch gets a fresh connection that is
    closed immediately after use.

    Args:
        cells_generator: Generator yielding H3 cell dictionaries
        grid_id: Unique grid identifier (e.g., 'global_res4')
        grid_type: Grid type ('global', 'land', 'ocean', 'custom')
        source_job_id: Job ID that generated this grid
        batch_size: Number of cells per batch insert (default: 1000)

    Returns:
        Total number of cells inserted

    Performance:
        - Batch insertion: Reduces round-trips vs single-row inserts
        - Repository pattern: Managed identity authentication
        - No pooling: Fresh connection per batch (safe for Azure Functions)

    Updated 25 NOV 2025: Replaced asyncpg with H3Repository for managed identity support.
    """
    from infrastructure.h3_repository import H3Repository

    logger.info(f"Starting sync stream to PostGIS via H3Repository (grid_id={grid_id}, batch_size={batch_size})")

    repo = H3Repository()
    batch: List[Dict[str, Any]] = []
    total_inserted = 0
    batch_count = 0

    for cell in cells_generator:
        batch.append(cell)

        if len(batch) >= batch_size:
            rows = repo.insert_h3_cells(batch, grid_id, grid_type, source_job_id)
            total_inserted += rows
            batch_count += 1

            if batch_count % 10 == 0:
                logger.debug(f"Inserted {total_inserted:,} cells ({batch_count} batches)")

            batch = []

    # Insert remaining cells
    if batch:
        rows = repo.insert_h3_cells(batch, grid_id, grid_type, source_job_id)
        total_inserted += rows

    logger.info(f"Stream complete: {total_inserted:,} cells inserted in {batch_count + (1 if batch else 0)} batches")
    return total_inserted


def h3_native_streaming_postgis(task_params: dict) -> dict:
    """
    Generate H3 grid using h3-py and stream directly to PostGIS.

    Task Handler Interface (called by CoreMachine task processor).

    Args:
        task_params: {
            'resolution': int (0-15) - H3 resolution level
            'grid_id': str - Unique grid identifier (e.g., 'global_res4')
            'grid_type': str - Grid type ('global', 'land', 'ocean', 'custom')
            'source_job_id': str - Job ID that created this grid
            'land_filter': bool (optional) - Filter to land cells only (default: False)
        }

    Returns:
        {
            'success': True/False,
            'result': {
                'grid_id': str,
                'table_name': str ('h3.grids'),
                'rows_inserted': int,
                'bbox': [minx, miny, maxx, maxy],
                'processing_time_seconds': float,
                'memory_used_mb': float
            },
            'error': str (if success=False)
        }

    Performance Metrics:
        - Resolution 0: 122 cells, ~5 seconds, ~50 MB memory
        - Resolution 4: ~288k cells, ~30-35 seconds, ~200 MB memory
        - Resolution 6: ~40M cells, ~1-2 hours, ~500 MB memory (estimated)

    Example Usage:
        task_params = {
            'resolution': 4,
            'grid_id': 'global_res4',
            'grid_type': 'global',
            'source_job_id': 'abc123',
            'land_filter': False
        }
        result = h3_native_streaming_postgis(task_params)
    """
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB

    # Extract parameters
    resolution = task_params.get('resolution')
    grid_id = task_params.get('grid_id')
    grid_type = task_params.get('grid_type')
    source_job_id = task_params.get('source_job_id')
    land_filter = task_params.get('land_filter', False)

    # Validate required parameters
    if resolution is None:
        return {
            'success': False,
            'error': "Missing required parameter: 'resolution'"
        }
    if not grid_id:
        return {
            'success': False,
            'error': "Missing required parameter: 'grid_id'"
        }
    if not grid_type:
        return {
            'success': False,
            'error': "Missing required parameter: 'grid_type'"
        }
    if not source_job_id:
        return {
            'success': False,
            'error': "Missing required parameter: 'source_job_id'"
        }

    # Validate resolution range
    if not (0 <= resolution <= 15):
        return {
            'success': False,
            'error': f"Invalid resolution: {resolution}. Must be 0-15."
        }

    logger.info(f"Starting H3 native streaming - resolution={resolution}, grid_id={grid_id}")

    try:
        # Generate cells using h3-py (generator pattern)
        cells_generator = generate_h3_cells_native(resolution, land_filter)

        # Stream to PostGIS using H3Repository (managed identity safe)
        rows_inserted = stream_to_postgis_sync(
            cells_generator,
            grid_id,
            grid_type,
            source_job_id
        )

        # Calculate bbox from PostGIS using H3Repository
        from infrastructure.h3_repository import H3Repository
        repo = H3Repository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        ST_XMin(extent) as minx,
                        ST_YMin(extent) as miny,
                        ST_XMax(extent) as maxx,
                        ST_YMax(extent) as maxy
                    FROM (
                        SELECT ST_Extent(geom) as extent
                        FROM h3.grids
                        WHERE grid_id = %s
                    ) AS bbox_calc
                """, (grid_id,))
                bbox_row = cur.fetchone()
                bbox = [bbox_row['minx'], bbox_row['miny'], bbox_row['maxx'], bbox_row['maxy']] if bbox_row and bbox_row['minx'] else [-180, -90, 180, 90]

        end_memory = process.memory_info().rss / 1024 / 1024
        processing_time = time.time() - start_time

        logger.info(
            f"H3 native streaming SUCCESS - "
            f"resolution={resolution}, cells={rows_inserted}, "
            f"time={processing_time:.2f}s, memory={end_memory - start_memory:.2f}MB"
        )

        return {
            'success': True,
            'result': {
                'grid_id': grid_id,
                'table_name': 'h3.grids',
                'rows_inserted': rows_inserted,
                'bbox': bbox,
                'processing_time_seconds': round(processing_time, 2),
                'memory_used_mb': round(end_memory - start_memory, 2)
            }
        }

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(
            f"H3 native streaming FAILED - "
            f"resolution={resolution}, grid_id={grid_id}, "
            f"error={str(e)}, time={processing_time:.2f}s"
        )
        return {
            'success': False,
            'error': f"H3 streaming failed: {str(e)}"
        }
