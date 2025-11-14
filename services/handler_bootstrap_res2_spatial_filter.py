# ============================================================================
# CLAUDE CONTEXT - H3 RESOLUTION 2 BOOTSTRAP WITH SPATIAL FILTERING
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service Layer - ONE-TIME spatial operation for H3 bootstrap
# PURPOSE: Generate global res 2 grid (5,882 cells), filter to land (~2,847 cells) via spatial join
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: bootstrap_res2_with_spatial_filter (task handler)
# INTERFACES: Task handler interface (dict → dict)
# PYDANTIC_MODELS: None (uses dict params)
# DEPENDENCIES: h3>=4.0.0, psycopg3, infrastructure.h3_repository
# SOURCE: Task parameters from bootstrap_h3_land_grid_pyramid job (Stage 1)
# SCOPE: Bootstrap Phase 2 - Resolution 2 reference grid with spatial attribution
# VALIDATION: Task parameter validation, schema existence checks
# PATTERNS: Repository pattern (H3Repository), safe SQL composition, idempotency
# ENTRY_POINTS: Called by CoreMachine task processor via services.ALL_HANDLERS registry
# INDEX:
#   - Lines 40-90: generate_global_res2_cells() - h3-py generator for all res 2 cells
#   - Lines 95-160: bootstrap_res2_with_spatial_filter() - main handler (15 min execution)
#   - Lines 95-110: Idempotency check (skip if land_res2 already complete)
#   - Lines 115-130: Generate and insert global res 2 cells (5,882 cells)
#   - Lines 135-150: Spatial filtering via ST_Intersects with config.h3_spatial_filter_table
#   - Lines 155-170: Extract land cell IDs and store in h3.reference_filters
#   - Lines 175-185: Update h3.grid_metadata with completion status
# ============================================================================

"""
H3 Resolution 2 Bootstrap Handler with Spatial Filtering

This is the ONLY spatial operation in the entire H3 bootstrap process.
All subsequent resolutions (3-7) use H3 parent-child relationships.

Workflow:
1. Generate global res 2 grid (5,882 hexagons covering Earth)
2. Insert all cells to h3.grids with grid_id='land_res2'
3. Perform ONE-TIME spatial join: ST_Intersects(h3.geom, geo.<spatial_filter_table>.geom)
   (spatial_filter_table from config.h3_spatial_filter_table, default: 'countries')
4. Update country_code and is_land=TRUE for land cells (~2,847 cells)
5. Extract land cell IDs into h3.reference_filters (parent IDs for res 3 cascade)
6. Update h3.grid_metadata with completion status

Performance:
- Execution time: ~15 minutes (one-time operation, acceptable)
- Memory: Generator pattern, low memory footprint
- Spatial operation: PostGIS ST_Intersects with spatial index

Expected Results:
- Total cells: 5,882 (global coverage)
- Land cells: ~2,847 (48.4% of global, avoids open ocean)
- Ocean cells: ~3,035 (51.6%, is_land=NULL)
"""

import time
import logging
from typing import Dict, Any, Generator, Optional

from config import get_config

# Initialize logger
logger = logging.getLogger(__name__)


def generate_global_res2_cells() -> Generator[Dict[str, Any], None, None]:
    """
    Generate ALL resolution 2 H3 cells (5,882 cells covering entire Earth).

    Uses h3-py to generate cells from 122 base resolution 0 cells.

    Yields:
        Dict containing:
            - h3_index: int (H3 cell index as 64-bit integer)
            - resolution: int (always 2)
            - geom_wkt: str (WKT POLYGON string)

    Performance:
        - Total cells: 5,882 (global coverage)
        - Execution time: ~5-10 seconds
        - Memory: Generator pattern, one cell at a time
    """
    try:
        import h3
        from shapely.geometry import Polygon
    except ImportError as e:
        logger.error(f"❌ Missing required library: {e}")
        raise RuntimeError(f"Cannot generate H3 cells - missing dependency: {e}")

    logger.info("🌍 Generating global H3 resolution 2 grid (5,882 cells)...")

    # Get all resolution 0 cells (122 base cells)
    base_cells = h3.get_res0_cells()
    logger.debug(f"Starting from {len(base_cells)} base cells at resolution 0")

    total_generated = 0

    for base_cell in base_cells:
        # Get all res 2 children for this base cell
        children = h3.cell_to_children(base_cell, 2)

        for cell in children:
            # Convert H3 index to integer
            if isinstance(cell, str):
                h3_index_int = int(cell, 16)
            else:
                h3_index_int = cell

            # Get cell boundary as list of (lat, lon) tuples
            boundary = h3.cell_to_boundary(cell)

            # Shapely expects (lon, lat) order for WKT
            coords = [(lon, lat) for lat, lon in boundary]

            # Create polygon and convert to WKT
            polygon = Polygon(coords)

            total_generated += 1

            # Log progress every 1,000 cells
            if total_generated % 1000 == 0:
                logger.debug(f"Generated {total_generated} H3 cells...")

            yield {
                'h3_index': h3_index_int,
                'resolution': 2,
                'geom_wkt': polygon.wkt
            }

    logger.info(f"✅ H3 cell generation complete - total cells: {total_generated}")


def bootstrap_res2_with_spatial_filter(task_params: dict) -> dict:
    """
    Generate resolution 2 H3 grid with spatial filtering (ONE-TIME spatial operation).

    This handler performs the ONLY spatial operation in the H3 bootstrap process.
    All subsequent resolutions (3-7) use H3 parent-child math (no spatial ops).

    Args:
        task_params: Task parameters containing:
            - resolution: int (must be 2)
            - grid_id: str (e.g., 'land_res2')
            - filter_name: str (e.g., 'land_res2')
            - spatial_filter_table: Optional[str] (e.g., 'geo.countries')
              If None, uses config.h3_spatial_filter_table
            - job_id: str (source job ID)

    Returns:
        Dict containing:
            - success: bool
            - result: Dict with cell counts, filter info, processing time
            - error: str (if success=False)

    Raises:
        ValueError: If resolution != 2 or required params missing
        RuntimeError: If h3 schema doesn't exist or spatial filter table missing
    """
    start_time = time.time()

    # Import H3Repository
    try:
        from infrastructure.h3_repository import H3Repository
    except ImportError as e:
        logger.error(f"❌ Failed to import H3Repository: {e}")
        return {
            "success": False,
            "error": f"H3Repository import failed: {e}"
        }

    # Validate required parameters
    resolution = task_params.get('resolution')
    grid_id = task_params.get('grid_id', 'land_res2')
    filter_name = task_params.get('filter_name', 'land_res2')

    # Get spatial filter table from task params or config
    spatial_filter_table = task_params.get('spatial_filter_table')
    if spatial_filter_table is None:
        config = get_config()
        spatial_filter_table = f"geo.{config.h3_spatial_filter_table}"
        logger.info(f"🗺️  Using spatial filter table from config: {spatial_filter_table}")

    job_id = task_params.get('job_id', 'unknown')

    if resolution != 2:
        error_msg = f"Resolution must be 2 for this handler, got: {resolution}"
        logger.error(f"❌ {error_msg}")
        return {"success": False, "error": error_msg}

    logger.info(f"🚀 Starting resolution 2 bootstrap with spatial filtering")
    logger.info(f"   Grid ID: {grid_id}")
    logger.info(f"   Filter name: {filter_name}")
    logger.info(f"   Spatial filter: {spatial_filter_table}")
    logger.info(f"   Job ID: {job_id}")

    # Initialize repository
    repo = H3Repository()

    # ========================================================================
    # STEP 1: Idempotency check - skip if already complete
    # ========================================================================
    logger.info("🔍 Checking if land_res2 grid already exists...")

    if repo.grid_exists(grid_id):
        cell_count = repo.get_cell_count(grid_id)
        logger.warning(f"⚠️ Grid {grid_id} already exists with {cell_count} cells - skipping bootstrap")

        # Check if reference filter exists
        existing_filter = repo.get_reference_filter(filter_name)
        if existing_filter:
            logger.info(f"✅ Reference filter '{filter_name}' already exists with {len(existing_filter)} parent IDs")
            return {
                "success": True,
                "result": {
                    "grid_id": grid_id,
                    "schema": "h3",
                    "table": "h3.grids",
                    "status": "already_exists",
                    "cell_count": cell_count,
                    "filter_name": filter_name,
                    "filter_cell_count": len(existing_filter),
                    "processing_time_seconds": time.time() - start_time
                }
            }

    # ========================================================================
    # STEP 2: Generate and insert global res 2 cells (5,882 cells)
    # ========================================================================
    logger.info("🌍 Generating global resolution 2 H3 grid (5,882 cells)...")

    cells_generator = generate_global_res2_cells()

    # Batch cells for insertion
    batch = []
    batch_size = 1000
    total_inserted = 0

    for cell in cells_generator:
        # Add source_job_id to cell
        cell['source_job_id'] = job_id
        cell['grid_id'] = grid_id
        cell['grid_type'] = 'land'  # Will filter later

        batch.append(cell)

        if len(batch) >= batch_size:
            rows_inserted = repo.insert_h3_cells(
                cells=batch,
                grid_id=grid_id,
                grid_type='land',
                source_job_id=job_id
            )
            total_inserted += rows_inserted
            logger.info(f"✅ Inserted batch of {rows_inserted} cells (total: {total_inserted})")
            batch = []

    # Insert remaining cells
    if batch:
        rows_inserted = repo.insert_h3_cells(
            cells=batch,
            grid_id=grid_id,
            grid_type='land',
            source_job_id=job_id
        )
        total_inserted += rows_inserted
        logger.info(f"✅ Inserted final batch of {rows_inserted} cells (total: {total_inserted})")

    logger.info(f"✅ All resolution 2 cells inserted to h3.grids (total: {total_inserted})")

    # ========================================================================
    # STEP 3: Spatial filtering via ST_Intersects with config spatial filter table
    # ========================================================================
    logger.info(f"🗺️ Performing spatial join with {spatial_filter_table}...")
    logger.info("   This is the ONE-TIME spatial operation (15 min expected)...")

    spatial_start = time.time()

    try:
        updated_count = repo.update_spatial_attributes(
            grid_id=grid_id,
            spatial_filter_table=spatial_filter_table
        )

        spatial_duration = time.time() - spatial_start
        logger.info(f"✅ Spatial join complete - {updated_count} land cells identified ({spatial_duration:.1f} seconds)")

    except Exception as e:
        logger.error(f"❌ Spatial filtering failed: {e}")
        return {
            "success": False,
            "error": f"Spatial filtering failed: {e}"
        }

    # ========================================================================
    # STEP 4: Extract land cell IDs and store in h3.reference_filters
    # ========================================================================
    logger.info(f"📋 Extracting land cell IDs for reference filter '{filter_name}'...")

    # Get land cell IDs (is_land=TRUE)
    land_cells = repo.get_parent_ids(grid_id)
    land_cell_ids = [cell[0] for cell in land_cells if cell[0] is not None]  # cell[0] is h3_index

    logger.info(f"✅ Extracted {len(land_cell_ids)} land cell IDs")

    # Insert to h3.reference_filters
    try:
        repo.insert_reference_filter(
            filter_name=filter_name,
            resolution=2,
            h3_indices=land_cell_ids,
            source_grid_id=grid_id,
            source_job_id=job_id,
            description=f"Land cells at resolution 2 (filtered via ST_Intersects with {spatial_filter_table})"
        )
        logger.info(f"✅ Reference filter '{filter_name}' stored with {len(land_cell_ids)} parent IDs")

    except Exception as e:
        logger.error(f"❌ Failed to store reference filter: {e}")
        return {
            "success": False,
            "error": f"Failed to store reference filter: {e}"
        }

    # ========================================================================
    # STEP 5: Update h3.grid_metadata with completion status
    # ========================================================================
    logger.info(f"📊 Updating h3.grid_metadata for {grid_id}...")

    try:
        repo.update_grid_metadata(
            grid_id=grid_id,
            resolution=2,
            status='completed',
            cell_count=total_inserted,
            land_cell_count=len(land_cell_ids),
            source_job_id=job_id
        )
        logger.info(f"✅ Grid metadata updated for {grid_id}")

    except Exception as e:
        logger.warning(f"⚠️ Failed to update grid metadata: {e}")
        # Non-fatal - continue

    # ========================================================================
    # FINAL: Return success with metrics
    # ========================================================================
    processing_time = time.time() - start_time
    ocean_cells = total_inserted - len(land_cell_ids)

    result = {
        "success": True,
        "result": {
            "grid_id": grid_id,
            "schema": "h3",
            "table": "h3.grids",
            "total_cells": total_inserted,
            "land_cells": len(land_cell_ids),
            "ocean_cells": ocean_cells,
            "land_percentage": round((len(land_cell_ids) / total_inserted) * 100, 1),
            "filter_name": filter_name,
            "spatial_filter_table": spatial_filter_table,
            "processing_time_seconds": round(processing_time, 1),
            "spatial_join_seconds": round(spatial_duration, 1)
        }
    }

    logger.info(f"🎉 Resolution 2 bootstrap COMPLETE!")
    logger.info(f"   Total cells: {total_inserted}")
    logger.info(f"   Land cells: {len(land_cell_ids)} ({result['result']['land_percentage']}%)")
    logger.info(f"   Ocean cells: {ocean_cells}")
    logger.info(f"   Processing time: {processing_time:.1f} seconds")
    logger.info(f"   Reference filter '{filter_name}' ready for cascade to resolution 3")

    return result
