# ============================================================================
# CLAUDE CONTEXT - SERVICE HANDLER
# ============================================================================
# PURPOSE: Task handler for H3 Level 4 grid generation
# EXPORTS: h3_level4_generate (handler function)
# INTERFACES: Epoch 4 task handler pattern (@register_task decorator)
# PYDANTIC_MODELS: Uses TaskData from core.models
# DEPENDENCIES: services.h3_grid (H3GridService), infrastructure.factory
# SOURCE: Service Bus task queue messages
# SCOPE: Execute H3 Level 4 generation tasks
# VALIDATION: Parameter validation via TaskData
# PATTERNS: Handler function pattern, service composition
# ENTRY_POINTS: Registered in services/__init__.py
# INDEX: handler_function:30
# ============================================================================

"""
H3 Level 4 Grid Generation Task Handler.

Executes the complete Level 4 workflow:
    1. Generate global Level 4 grid (~3,500 cells)
    2. Filter by Overture Divisions land boundaries
    3. Save to gold container as GeoParquet

Handler function registered as "h3_level4_generate" task type.
"""

from typing import Dict, Any

from util_logger import LoggerFactory, ComponentType
from infrastructure.factory import RepositoryFactory
from services.h3_grid import H3GridService
from config import get_config


def h3_level4_generate(task_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate Level 4 H3 land grid.

    This handler executes the complete workflow in a single task:
        1. Generate global Level 4 grid (DuckDB H3 extension)
        2. Filter by Overture Divisions land boundaries (spatial join)
        3. Save result as GeoParquet to gold container

    Args:
        task_params: Task parameters
            - overture_release: Overture Maps release version
            - output_folder: Output folder in gold container
            - output_filename: Output filename

    Returns:
        Task result with grid statistics and output path

    Performance:
        - Global grid generation: ~10 seconds
        - Overture land filtering: ~60 seconds (serverless query)
        - GeoParquet save: ~5 seconds
        - Total: ~75 seconds

    Output:
        gold/h3/grids/land_h3_level4.parquet (~875 cells, ~500KB)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_level4_generate")

    # Extract parameters
    overture_release = task_params.get("overture_release")
    land_geojson_path = task_params.get("land_geojson_path")
    skip_land_filter = task_params.get("skip_land_filter", False)  # NEW: Allow skipping land filter
    output_folder = task_params.get("output_folder", "h3/grids")
    output_filename = task_params.get("output_filename", "land_h3_level4.parquet")

    logger.info("🌍 Starting Level 4 H3 grid generation...")

    if skip_land_filter:
        logger.info("   Mode: GLOBAL GRID (no land filtering)")
    else:
        logger.info("   Mode: LAND-FILTERED GRID")
        # Only set defaults if land filtering is enabled
        if land_geojson_path:
            logger.info(f"   Land source: GeoJSON ({land_geojson_path})")
        elif overture_release:
            logger.info(f"   Land source: Overture Maps ({overture_release})")
        else:
            # Only error if land filtering is requested but no source provided
            logger.error("   ❌ Land filtering requested but no land source provided")
            raise ValueError("Must provide land_geojson_path or overture_release when skip_land_filter=False")

    logger.info(f"   Output: gold/{output_folder}/{output_filename}")

    try:
        # Get configuration
        config = get_config()

        # Get repositories
        duckdb_repo = RepositoryFactory.create_duckdb_repository()
        blob_repo = RepositoryFactory.create_blob_repository()

        # Initialize H3 grid service
        h3_service = H3GridService(
            duckdb_repo=duckdb_repo,
            blob_repo=blob_repo,
            gold_container=config.gold_container_name
        )

        # STEP 1: Generate global Level 4 grid
        logger.info("📊 STEP 1: Generating global Level 4 grid...")
        global_grid = h3_service.generate_level4_grid()
        total_cells = len(global_grid)
        logger.info(f"   Generated {total_cells:,} cells globally")

        # STEP 2: Filter by land boundaries (optional)
        if skip_land_filter:
            logger.info("⏭️  STEP 2: SKIPPED (skip_land_filter=True)")
            final_grid = global_grid
            land_cells = total_cells
            reduction_percent = 0.0
        else:
            logger.info("🌊 STEP 2: Filtering by land boundaries...")
            land_grid = h3_service.filter_by_land(
                grid_df=global_grid,
                overture_release=overture_release,
                land_geojson_path=land_geojson_path
            )
            land_cells = len(land_grid)
            reduction_percent = (1 - land_cells / total_cells) * 100
            logger.info(f"   Filtered to {land_cells:,} land cells ({reduction_percent:.1f}% ocean removed)")
            final_grid = land_grid

        # STEP 3: Save to gold container
        logger.info("💾 STEP 3: Saving to gold container...")
        blob_path = h3_service.save_to_gold(
            df=final_grid,
            filename=output_filename,
            folder=output_folder
        )

        # Get grid statistics
        stats = h3_service.get_grid_stats(final_grid)

        logger.info(f"✅ Level 4 grid generation complete!")
        logger.info(f"   Output: gold/{blob_path}")
        logger.info(f"   Cells: {land_cells:,}")
        logger.info(f"   Memory: {stats['memory_mb']:.2f} MB")

        return {
            "success": True,
            "total_cells_generated": total_cells,
            "land_cells_filtered": land_cells,
            "reduction_percent": round(reduction_percent, 2),
            "blob_path": blob_path,
            "overture_release": overture_release,
            "file_size_mb": round(stats['memory_mb'], 2),
            "grid_stats": stats
        }

    except Exception as e:
        logger.error(f"❌ Level 4 grid generation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
