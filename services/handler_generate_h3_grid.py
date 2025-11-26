# ============================================================================
# CLAUDE CONTEXT - UNIVERSAL H3 GRID GENERATION HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service Layer - Universal H3 grid generation for ALL resolutions (0-15)
# PURPOSE: Single DRY handler for generating H3 grids with flexible filtering
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: generate_h3_grid (task handler)
# INTERFACES: Task handler interface (dict → dict)
# PYDANTIC_MODELS: None (uses dict params)
# DEPENDENCIES: h3>=4.0.0, shapely, psycopg3, infrastructure.h3_repository
# SOURCE: Task parameters from H3 jobs (bootstrap, custom queries)
# SCOPE: Universal H3 generation - base OR cascade, with optional spatial filtering
# VALIDATION: Task parameter validation, resolution range (0-15), filter geometry
# PATTERNS: Repository pattern (H3Repository), DRY (single handler), flexible filtering
# ENTRY_POINTS: Called by CoreMachine task processor via services.ALL_HANDLERS registry
# INDEX:
#   - generate_h3_grid:50 - Main handler entry point
#   - _generate_from_base:150 - Generate from res 0 base cells
#   - _generate_from_cascade:250 - Generate from parent grid (batch support)
#   - _apply_spatial_filters:350 - Apply table/geometry/bbox filters (AND logic)
#   - _build_filter_geometry:450 - Construct shapely geometry from parameters
# ============================================================================

"""
Universal H3 Grid Generation Handler

Single DRY handler for ALL H3 resolutions (0-15) with flexible filtering.

Generation Modes:
    1. Base: Generate from scratch using h3.get_res0_cells()
    2. Cascade: Generate children from parent grid (requires parent_grid_id)

Filtering Options (AND logic - all must match):
    - spatial_filter_table: PostGIS table (e.g., 'geo.countries')
    - spatial_filter_geometry: WKT polygon/multipolygon
    - spatial_filter_bbox: [minx, miny, maxx, maxy]

Default Behavior:
    - use_cascade: true (use parent grid if exists, fallback to base if not)
    - filter_mode: 'intersects' (ST_Intersects for spatial filtering)
    - Filters combined with AND (cell must pass ALL filters)

Use Cases:
    1. Bootstrap pyramid: Cascade from res 2 → res 7 with land filter
    2. Independent resolution: Generate res 6 directly in Peru bbox
    3. Custom project area: Generate res 5 within specific polygon
    4. Multi-filter: Combine table + bbox for precise filtering

"""

import time
import logging
from typing import Dict, Any, List, Tuple, Optional, Generator

from config import get_config
from infrastructure.h3_repository import H3Repository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "GenerateH3Grid")


def generate_h3_grid(task_params: dict) -> dict:
    """
    Universal H3 grid generation handler for ALL resolutions (0-15).

    Single DRY handler supporting:
    - Base generation (from scratch)
    - Cascade generation (from parents)
    - Flexible spatial filtering (table, geometry, bbox)
    - Independent resolution creation
    - Batch processing for parallelism

    Args:
        task_params: dict containing:
            # REQUIRED
            - resolution: int (0-15, target H3 resolution)
            - grid_id: str (unique identifier, e.g. 'land_res2', 'peru_res6')

            # GENERATION (default: auto-detect)
            - use_cascade: bool (default: True - use parent if exists, else base)
            - parent_grid_id: str (required if use_cascade=True and parents exist)
            - batch_start: int (default: 0, for parallelism)
            - batch_size: int (default: None = all parents)

            # FILTERING (optional, AND logic)
            - spatial_filter_table: str (e.g., 'geo.countries')
            - spatial_filter_geometry: str (WKT polygon/multipolygon)
            - spatial_filter_bbox: List[float] [minx, miny, maxx, maxy]
            - filter_mode: str (default: 'intersects', options: 'contains', 'within')

            # METADATA
            - job_id: str (source job ID)
            - grid_type: str (default: 'land')

    Returns:
        dict containing:
            - success: bool
            - result: {
                "cells_generated": int,
                "cells_filtered": int (if filters applied),
                "cells_inserted": int,
                "grid_id": str,
                "resolution": int,
                "generation_mode": 'base' | 'cascade',
                "filters_applied": List[str],
                "processing_time_sec": float
              }
            - error: str (if success=False)

    Raises:
        ValueError: If resolution out of range, invalid parameters
        RuntimeError: If h3 schema doesn't exist or filter table missing

    Examples:
        # Bootstrap res 2 with country filter
        {"resolution": 2, "grid_id": "land_res2",
         "use_cascade": False,  # Generate from base
         "spatial_filter_table": "geo.system_admin0"}

        # Cascade res 3 from res 2 (batch processing)
        {"resolution": 3, "grid_id": "land_res3",
         "use_cascade": True, "parent_grid_id": "land_res2",
         "batch_start": 0, "batch_size": 500}

        # Independent res 6 in Peru bbox
        {"resolution": 6, "grid_id": "peru_res6",
         "use_cascade": False,
         "spatial_filter_bbox": [-81.5, -18.5, -68.5, 0.0]}

        # Res 5 with polygon + bbox filters (AND logic)
        {"resolution": 5, "grid_id": "project_res5",
         "use_cascade": False,
         "spatial_filter_geometry": "POLYGON((...))",
         "spatial_filter_bbox": [-70, -10, -65, -5]}
    """
    start_time = time.time()

    # ========================================================================
    # STEP 1: Validate parameters
    # ========================================================================
    resolution = task_params.get('resolution')
    grid_id = task_params.get('grid_id')
    use_cascade = task_params.get('use_cascade', True)
    parent_grid_id = task_params.get('parent_grid_id')
    batch_start = task_params.get('batch_start', 0)
    batch_size = task_params.get('batch_size')
    job_id = task_params.get('job_id', 'unknown')
    grid_type = task_params.get('grid_type', 'land')

    # Validate resolution
    if resolution is None or not isinstance(resolution, int):
        return {
            "success": False,
            "error": f"resolution must be int (0-15), got: {resolution}"
        }

    if not (0 <= resolution <= 15):
        return {
            "success": False,
            "error": f"resolution must be 0-15, got: {resolution}"
        }

    # Validate grid_id
    if not grid_id:
        return {
            "success": False,
            "error": "grid_id is required"
        }

    logger.info(f"🔷 H3 Grid Generation - Resolution {resolution}")
    logger.info(f"   Grid ID: {grid_id}")
    logger.info(f"   Use Cascade: {use_cascade}")
    logger.info(f"   Parent Grid: {parent_grid_id if parent_grid_id else 'N/A'}")
    logger.info(f"   Job ID: {job_id}")
    logger.info(f"   Batch: start={batch_start}, size={batch_size if batch_size else 'ALL'}")

    # Initialize repository
    repo = H3Repository()

    # ========================================================================
    # STEP 2: Determine generation mode and generate cells
    # ========================================================================
    generation_mode = 'cascade' if use_cascade and parent_grid_id else 'base'

    if generation_mode == 'cascade':
        logger.info(f"📊 Cascade Mode: Generating from parent grid '{parent_grid_id}'")

        # Validate parent grid exists
        logger.info(f"   Checking if parent grid exists...")
        if not repo.grid_exists(parent_grid_id):
            logger.error(f"❌ Parent grid '{parent_grid_id}' does not exist!")
            return {
                "success": False,
                "error": f"Parent grid '{parent_grid_id}' does not exist. Cannot cascade."
            }
        logger.info(f"   ✅ Parent grid exists, proceeding with cascade")

        # Generate from parent cascade
        logger.info(f"   Loading parent cells and generating children...")
        cells, parents_processed = _generate_from_cascade(
            repo=repo,
            parent_grid_id=parent_grid_id,
            target_resolution=resolution,
            batch_start=batch_start,
            batch_size=batch_size
        )

        logger.info(f"   ✅ Generated {len(cells)} cells from {parents_processed} parents")

    else:  # base mode
        logger.info(f"🌍 Base Mode: Generating from res 0 base cells")
        logger.info(f"   This will generate ALL H3 cells globally at res {resolution}")

        # Generate from base
        logger.info(f"   Starting H3 generation...")
        cells = _generate_from_base(resolution=resolution)

        logger.info(f"   ✅ Generated {len(cells)} cells globally")

    cells_generated = len(cells)

    # ========================================================================
    # STEP 3: Apply spatial filters (AND logic)
    # ========================================================================
    filters_applied = []
    cells_before_filter = cells_generated

    # Extract filter parameters
    spatial_filter_table = task_params.get('spatial_filter_table')
    spatial_filter_geometry = task_params.get('spatial_filter_geometry')
    spatial_filter_bbox = task_params.get('spatial_filter_bbox')
    filter_mode = task_params.get('filter_mode', 'intersects')

    # Apply filters if any specified
    if any([spatial_filter_table, spatial_filter_geometry, spatial_filter_bbox]):
        logger.info(f"🗺️  Applying spatial filters...")
        logger.info(f"   Cells before filtering: {cells_before_filter:,}")

        cells, filter_info = _apply_spatial_filters(
            cells=cells,
            spatial_filter_table=spatial_filter_table,
            spatial_filter_geometry=spatial_filter_geometry,
            spatial_filter_bbox=spatial_filter_bbox,
            filter_mode=filter_mode,
            repo=repo
        )

        filters_applied = filter_info['filters_applied']
        logger.info(f"   Filters applied: {', '.join(filters_applied)}")
        logger.info(f"   Cells after filtering: {len(cells):,}")
        logger.info(f"   Cells removed: {cells_before_filter - len(cells):,}")

    # ========================================================================
    # STEP 4: Insert cells to h3.grids
    # ========================================================================
    logger.info(f"💾 Inserting {len(cells):,} cells to h3.grids...")
    logger.info(f"   Target: h3.grids (grid_id={grid_id}, resolution={resolution})")
    logger.info(f"   Note: ON CONFLICT clause will skip duplicates automatically")

    insert_start = time.time()
    rows_inserted = repo.insert_h3_cells(
        cells=cells,
        grid_id=grid_id,
        grid_type=grid_type,
        source_job_id=job_id
    )
    insert_time = time.time() - insert_start

    logger.info(f"✅ Insert complete in {insert_time:.2f}s")
    logger.info(f"   Rows inserted: {rows_inserted:,}")
    logger.info(f"   Duplicates skipped: {len(cells) - rows_inserted:,}")

    # ========================================================================
    # STEP 5: Return result
    # ========================================================================
    elapsed_time = time.time() - start_time

    return {
        "success": True,
        "result": {
            "cells_generated": cells_generated,
            "cells_filtered": cells_before_filter - len(cells) if filters_applied else 0,
            "cells_inserted": rows_inserted,
            "grid_id": grid_id,
            "resolution": resolution,
            "generation_mode": generation_mode,
            "filters_applied": filters_applied,
            "processing_time_sec": round(elapsed_time, 2)
        }
    }


def _generate_from_base(resolution: int) -> List[Dict[str, Any]]:
    """
    Generate H3 cells from base resolution 0 cells.

    Uses h3-py to generate all cells at target resolution globally.
    Memory efficient generator pattern.

    Args:
        resolution: Target H3 resolution (0-15)

    Returns:
        List of cell dicts containing:
            - h3_index: int
            - resolution: int
            - geom_wkt: str
    """
    try:
        import h3
        from shapely.geometry import Polygon
    except ImportError as e:
        logger.error(f"❌ Missing required library: {e}")
        raise RuntimeError(f"Cannot generate H3 cells - missing dependency: {e}")

    logger.debug(f"Generating global H3 grid at resolution {resolution}")

    cells = []

    # Get all resolution 0 cells (122 base cells covering Earth)
    base_cells = h3.get_res0_cells()

    for base_cell in base_cells:
        # Get all children at target resolution
        if resolution == 0:
            children = [base_cell]
        else:
            children = h3.cell_to_children(base_cell, resolution)

        for cell in children:
            # h3 v4 returns hex strings - convert to int for database storage
            if isinstance(cell, str):
                h3_index_int = h3.str_to_int(cell)
            else:
                h3_index_int = int(cell)

            # Get geometry as WKT (cell_to_boundary returns [(lat, lng), ...])
            boundary = h3.cell_to_boundary(cell)
            coords = [(lng, lat) for lat, lng in boundary]  # Convert to (lng, lat) for WKT
            coords.append(coords[0])  # Close polygon
            polygon = Polygon(coords)
            geom_wkt = polygon.wkt

            cells.append({
                'h3_index': h3_index_int,
                'resolution': resolution,
                'geom_wkt': geom_wkt
            })

    logger.debug(f"Generated {len(cells)} cells from base")
    return cells


def _generate_from_cascade(
    repo: H3Repository,
    parent_grid_id: str,
    target_resolution: int,
    batch_start: int = 0,
    batch_size: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Generate H3 cells from parent grid (cascade).

    Uses H3 parent-child relationships (no spatial operations).
    Supports batch processing for parallelism.

    Args:
        repo: H3Repository instance
        parent_grid_id: Parent grid ID (e.g., 'land_res2')
        target_resolution: Target resolution (must be parent_resolution + 1)
        batch_start: Starting index in parent list (for batching)
        batch_size: Number of parents to process (None = all)

    Returns:
        Tuple of (cells list, parents_processed count)
    """
    try:
        import h3
        from shapely.geometry import Polygon
    except ImportError as e:
        logger.error(f"❌ Missing required library: {e}")
        raise RuntimeError(f"Cannot generate H3 cells - missing dependency: {e}")

    # Load parent IDs (uses H3Repository safe SQL)
    all_parent_ids = repo.get_parent_ids(parent_grid_id)

    # Apply batch slicing if specified
    if batch_size is not None:
        parent_batch = all_parent_ids[batch_start:batch_start + batch_size]
    else:
        parent_batch = all_parent_ids[batch_start:]

    logger.debug(f"Processing {len(parent_batch)} parents (batch: {batch_start} to {batch_start + len(parent_batch)})")

    cells = []

    for h3_index, parent_res2 in parent_batch:
        # Convert integer h3_index to hex string for h3 library v4+
        h3_str = h3.int_to_str(h3_index)

        # Generate 7 children for this parent (H3 deterministic)
        child_indices = h3.cell_to_children(h3_str, target_resolution)

        for child_index in child_indices:
            # h3 v4 returns hex strings - convert to int for database storage
            if isinstance(child_index, str):
                child_index_int = h3.str_to_int(child_index)
            else:
                child_index_int = int(child_index)

            # Get geometry as WKT (cell_to_boundary returns [(lat, lng), ...])
            boundary = h3.cell_to_boundary(child_index)
            coords = [(lng, lat) for lat, lng in boundary]  # Convert to (lng, lat) for WKT
            coords.append(coords[0])  # Close polygon
            polygon = Polygon(coords)
            geom_wkt = polygon.wkt

            cells.append({
                'h3_index': child_index_int,
                'resolution': target_resolution,
                'geom_wkt': geom_wkt,
                'parent_h3_index': h3_index,
                'parent_res2': parent_res2  # Inherit from parent (no lookup!)
            })

    return cells, len(parent_batch)


def _apply_spatial_filters(
    cells: List[Dict[str, Any]],
    spatial_filter_table: Optional[str],
    spatial_filter_geometry: Optional[str],
    spatial_filter_bbox: Optional[List[float]],
    filter_mode: str,
    repo: H3Repository
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Apply spatial filters to cells (AND logic - all must match).

    Filters:
        1. spatial_filter_table: PostGIS table intersection
        2. spatial_filter_geometry: WKT geometry intersection
        3. spatial_filter_bbox: Bounding box intersection

    All specified filters are combined with AND logic.

    Args:
        cells: List of cell dicts with geom_wkt
        spatial_filter_table: PostGIS table (e.g., 'geo.countries')
        spatial_filter_geometry: WKT polygon/multipolygon
        spatial_filter_bbox: [minx, miny, maxx, maxy]
        filter_mode: 'intersects' | 'contains' | 'within'
        repo: H3Repository instance

    Returns:
        Tuple of (filtered_cells, filter_info dict)
    """
    try:
        from shapely.geometry import box
        from shapely import wkt as shapely_wkt
    except ImportError as e:
        logger.error(f"❌ Missing shapely library: {e}")
        raise RuntimeError(f"Cannot apply spatial filters - missing shapely: {e}")

    filters_applied = []
    filter_geometry = None

    # Build combined filter geometry from bbox and/or WKT geometry
    geometry_filters = []

    if spatial_filter_bbox:
        bbox_geom = box(*spatial_filter_bbox)
        geometry_filters.append(bbox_geom)
        filters_applied.append(f"bbox{spatial_filter_bbox}")
        logger.debug(f"Added bbox filter: {spatial_filter_bbox}")

    if spatial_filter_geometry:
        wkt_geom = shapely_wkt.loads(spatial_filter_geometry)
        geometry_filters.append(wkt_geom)
        filters_applied.append("geometry(WKT)")
        logger.debug(f"Added WKT geometry filter")

    # Combine geometry filters (intersection = AND)
    if geometry_filters:
        filter_geometry = geometry_filters[0]
        for geom in geometry_filters[1:]:
            filter_geometry = filter_geometry.intersection(geom)

    # Apply geometry filter to cells (in-memory)
    if filter_geometry:
        logger.debug(f"Filtering cells with geometry filter (mode: {filter_mode})")
        filtered_cells = []

        for cell in cells:
            cell_geom = shapely_wkt.loads(cell['geom_wkt'])

            if filter_mode == 'intersects':
                passes = filter_geometry.intersects(cell_geom)
            elif filter_mode == 'contains':
                passes = filter_geometry.contains(cell_geom)
            elif filter_mode == 'within':
                passes = cell_geom.within(filter_geometry)
            else:
                passes = filter_geometry.intersects(cell_geom)  # default

            if passes:
                filtered_cells.append(cell)

        cells = filtered_cells
        logger.debug(f"Geometry filter retained {len(cells)} cells")

    # Apply PostGIS table filter (database-side after insert, or pre-filter)
    if spatial_filter_table:
        filters_applied.append(f"table({spatial_filter_table})")
        logger.debug(f"Table filter will be applied via PostGIS: {spatial_filter_table}")

        # NOTE: For table filtering, we could either:
        # 1. Pre-filter in Python (requires loading entire table - memory intensive)
        # 2. Post-filter in database after insert (UPDATE with ST_Intersects)
        #
        # Recommendation: Use post-insert UPDATE for table filters
        # This is handled by H3Repository.update_spatial_attributes()
        #
        # For now, we'll mark that table filter needs to be applied post-insert
        # The bootstrap job should call repo.update_spatial_attributes() after this handler

    filter_info = {
        "filters_applied": filters_applied,
        "filter_mode": filter_mode,
        "requires_post_insert_table_filter": spatial_filter_table is not None
    }

    return cells, filter_info


# ============================================================================
# MODULE EXPORT (Register in services/__init__.py)
# ============================================================================
# To register this handler:
# from .handler_generate_h3_grid import generate_h3_grid
# ALL_HANDLERS["generate_h3_grid"] = generate_h3_grid
