"""
H3 Base Grid Generation Handler

Executes H3 base grid generation tasks using Core Machine patterns.
Implements the H3BaseGridHandler protocol from models/h3_base.py.

Author: Robert and Geospatial Claude Legion
Date: 15 OCT 2025
"""

import time
from typing import Dict, Any

from models.h3_base import (
    H3BaseGridRequest,
    H3BaseGridResponse,
    EXPECTED_CELL_COUNTS
)
from services.h3_grid import H3GridService
from infrastructure.factory import RepositoryFactory
from util_logger import LoggerFactory, ComponentType
from config import get_config


def h3_base_generate(task_params: dict) -> dict:
    """
    Generate H3 base grid at specified resolution.

    Core Machine Contract:
        - Takes task_params dict (validated against H3BaseGridRequest)
        - Returns dict matching H3BaseGridResponse schema
        - Raises exceptions for failures (caught by Core Machine)

    Args:
        task_params: Task parameters from Core Machine

    Returns:
        Success/failure dict with grid statistics

    Performance:
        - Res 0: ~1 second (122 cells)
        - Res 1: ~2 seconds (842 cells)
        - Res 2: ~5 seconds (5,882 cells)
        - Res 3: ~20 seconds (41,162 cells)
        - Res 4: ~120 seconds (288,122 cells)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_base_generate")
    start_time = time.time()

    logger.info("=" * 80)
    logger.info("🔷 H3 BASE GRID GENERATION")
    logger.info("=" * 80)

    try:
        # Validate and parse parameters
        request = H3BaseGridRequest(**task_params)
        logger.info(f"📋 Parameters:")
        logger.info(f"   Resolution: {request.resolution}")
        logger.info(f"   Exclude antimeridian: {request.exclude_antimeridian}")
        logger.info(f"   Output: {request.output_folder}/{request.get_output_filename()}")

        # Log expected cell count
        expected = EXPECTED_CELL_COUNTS.get(request.resolution, {})
        logger.info(f"📊 Expected output:")
        logger.info(f"   ~{expected.get('total', 'unknown'):,} cells")
        logger.info(f"   ~{expected.get('avg_edge_km', 'unknown')} km edge length")

        # Get configuration and repositories
        config = get_config()
        duckdb_repo = RepositoryFactory.create_duckdb_repository()
        blob_repo = RepositoryFactory.create_blob_repository()

        # Initialize H3 grid service
        h3_service = H3GridService(
            duckdb_repo=duckdb_repo,
            blob_repo=blob_repo,
            gold_container=config.gold_container_name
        )

        # STEP 1: Generate H3 grid
        logger.info("🌐 STEP 1: Generating H3 grid...")
        grid_df = h3_service.generate_grid(
            resolution=request.resolution,
            exclude_antimeridian=request.exclude_antimeridian
        )
        total_cells = len(grid_df)
        logger.info(f"   ✅ Generated {total_cells:,} cells")

        # Calculate antimeridian exclusions
        expected_total = expected.get('total', 0)
        antimeridian_excluded = max(0, expected_total - total_cells) if expected_total else 0
        if antimeridian_excluded > 0:
            logger.info(f"   🌐 Excluded {antimeridian_excluded:,} antimeridian cells")

        # STEP 2: Save to gold container
        logger.info("💾 STEP 2: Saving to gold container...")
        blob_path = h3_service.save_grid(
            df=grid_df,
            filename=request.get_output_filename(),
            folder=request.output_folder
        )
        logger.info(f"   ✅ Saved to: gold/{blob_path}")

        # STEP 3: Calculate statistics
        stats = h3_service.get_grid_stats(grid_df)
        processing_time = time.time() - start_time

        logger.info("=" * 80)
        logger.info("✅ H3 BASE GRID GENERATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"   Resolution: {request.resolution}")
        logger.info(f"   Cells: {total_cells:,}")
        logger.info(f"   File size: {stats.memory_mb:.2f} MB")
        logger.info(f"   Processing time: {processing_time:.1f}s")
        logger.info(f"   Output: gold/{blob_path}")
        logger.info("=" * 80)

        # Build response matching H3BaseGridResponse schema
        response = H3BaseGridResponse(
            success=True,
            resolution=request.resolution,
            total_cells=total_cells,
            antimeridian_cells_excluded=antimeridian_excluded,
            blob_path=blob_path,
            file_size_mb=round(stats.memory_mb, 2),
            processing_time_seconds=round(processing_time, 2),
            min_h3_index=stats.min_h3_index or 0,
            max_h3_index=stats.max_h3_index or 0,
            memory_mb=round(stats.memory_mb, 2)
        )

        return response.model_dump()

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error("=" * 80)
        logger.error("❌ H3 BASE GRID GENERATION FAILED")
        logger.error("=" * 80)
        logger.error(f"   Error: {str(e)}")
        logger.error(f"   Type: {type(e).__name__}")
        logger.error(f"   Processing time: {processing_time:.1f}s")
        logger.error("=" * 80)

        import traceback
        logger.error(traceback.format_exc())

        # Return failure response
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "processing_time_seconds": round(processing_time, 2)
        }
