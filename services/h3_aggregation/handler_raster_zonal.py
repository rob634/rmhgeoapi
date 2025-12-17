# ============================================================================
# CLAUDE CONTEXT - H3 RASTER ZONAL STATS HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Raster Zonal Statistics
# PURPOSE: Compute zonal statistics from COGs for H3 cell batches
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: h3_raster_zonal_stats
# DEPENDENCIES: rasterstats, rasterio, shapely
# ============================================================================
"""
H3 Raster Zonal Stats Handler.

Stage 2 of H3 raster aggregation workflow. Computes zonal statistics
from Cloud Optimized GeoTIFFs (COGs) for batches of H3 cells.

Features:
    - Uses rasterstats for efficient zonal statistics
    - Windowed COG reads for memory efficiency
    - Batch processing with configurable size
    - Multiple stat types: mean, sum, min, max, count, std, median

Usage:
    result = h3_raster_zonal_stats({
        "container": "silver-cogs",
        "blob_path": "population/worldpop_2020.tif",
        "dataset_id": "worldpop_2020",
        "band": 1,
        "resolution": 6,
        "iso3": "GRC",
        "batch_start": 0,
        "batch_size": 1000,
        "stats": ["mean", "sum", "count"]
    })
"""

import time
from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType

from .base import validate_resolution, validate_stat_types, validate_dataset_id


def h3_raster_zonal_stats(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Compute zonal statistics from COG raster for H3 cell batch.

    Stage 2 handler that:
    1. Loads H3 cells for batch range
    2. Fetches raster window from COG
    3. Computes zonal stats using rasterstats
    4. Inserts results to h3.zonal_stats

    Args:
        params: Task parameters containing:
            - container (str): Azure Blob Storage container
            - blob_path (str): Path to COG within container
            - dataset_id (str): Dataset identifier
            - band (int): Raster band (1-indexed, default: 1)
            - resolution (int): H3 resolution level
            - iso3 (str, optional): ISO3 country code
            - bbox (list, optional): Bounding box
            - polygon_wkt (str, optional): WKT polygon
            - batch_start (int): Starting offset
            - batch_size (int): Number of cells in batch
            - batch_index (int): Batch index for tracking
            - stats (list): Stat types to compute
            - append_history (bool): Skip existing values if True
            - source_job_id (str): Job ID for tracking

        context: Optional execution context (not used)

    Returns:
        Success dict with computation results:
        {
            "success": True,
            "result": {
                "cells_processed": int,
                "stats_inserted": int,
                "batch_index": int,
                "elapsed_time": float
            }
        }

    Raises:
        ValueError: If required parameters missing or invalid
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_raster_zonal_stats")
    start_time = time.time()

    # STEP 1: Validate parameters
    container = params.get('container')
    blob_path = params.get('blob_path')
    dataset_id = params.get('dataset_id')
    band = params.get('band', 1)
    resolution = params.get('resolution')
    batch_start = params.get('batch_start', 0)
    batch_size = params.get('batch_size', 1000)
    batch_index = params.get('batch_index', 0)
    stats = params.get('stats', ['mean', 'sum', 'count'])
    append_history = params.get('append_history', False)
    source_job_id = params.get('source_job_id')

    # Scope parameters
    iso3 = params.get('iso3')
    bbox = params.get('bbox')
    polygon_wkt = params.get('polygon_wkt')

    if not container:
        raise ValueError("container is required")
    if not blob_path:
        raise ValueError("blob_path is required")
    if not dataset_id:
        raise ValueError("dataset_id is required")
    if resolution is None:
        raise ValueError("resolution is required")

    validate_resolution(resolution)
    validate_dataset_id(dataset_id)
    validate_stat_types(stats)

    logger.info(f"📊 Zonal Stats - Batch {batch_index}: {dataset_id}")
    logger.info(f"   Source: {container}/{blob_path} (band {band})")
    logger.info(f"   Range: offset={batch_start}, size={batch_size}")
    logger.info(f"   Stats: {stats}")

    try:
        from infrastructure.h3_repository import H3Repository

        h3_repo = H3Repository()

        # STEP 2: Load H3 cells for batch
        cells = h3_repo.get_cells_for_aggregation(
            resolution=resolution,
            iso3=iso3,
            bbox=bbox,
            polygon_wkt=polygon_wkt,
            batch_start=batch_start,
            batch_size=batch_size
        )

        cells_count = len(cells)
        if cells_count == 0:
            logger.warning(f"⚠️ No cells in batch {batch_index} (offset={batch_start})")
            return {
                "success": True,
                "result": {
                    "cells_processed": 0,
                    "stats_inserted": 0,
                    "batch_index": batch_index,
                    "elapsed_time": time.time() - start_time,
                    "message": "No cells in batch range"
                }
            }

        logger.info(f"   Loaded {cells_count:,} cells")

        # STEP 3: Build COG URL
        cog_url = _build_cog_url(container, blob_path)
        logger.info(f"   COG URL: {cog_url}")

        # STEP 4: Compute zonal stats using rasterstats
        zonal_results = _compute_zonal_stats(
            cells=cells,
            cog_url=cog_url,
            band=band,
            stats=stats,
            logger=logger
        )

        logger.info(f"   Computed {len(zonal_results):,} stat values")

        # STEP 5: Build stat records for insertion
        stat_records = []
        for result in zonal_results:
            h3_index = result['h3_index']
            for stat_type in stats:
                value = result.get(stat_type)
                if value is not None:
                    stat_records.append({
                        'h3_index': h3_index,
                        'dataset_id': dataset_id,
                        'band': f"band_{band}",
                        'stat_type': stat_type,
                        'value': value,
                        'pixel_count': result.get('count'),
                        'nodata_count': result.get('nodata_count')
                    })

        # STEP 6: Insert to h3.zonal_stats
        stats_inserted = h3_repo.insert_zonal_stats_batch(
            stats=stat_records,
            append_history=append_history,
            source_job_id=source_job_id
        )

        elapsed_time = time.time() - start_time
        logger.info(f"✅ Batch {batch_index} complete: {stats_inserted:,} stats in {elapsed_time:.2f}s")

        return {
            "success": True,
            "result": {
                "cells_processed": cells_count,
                "stats_inserted": stats_inserted,
                "batch_index": batch_index,
                "batch_start": batch_start,
                "batch_size": batch_size,
                "elapsed_time": elapsed_time,
                "dataset_id": dataset_id,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Batch {batch_index} failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": f"Zonal stats failed: {str(e)}",
            "error_type": type(e).__name__,
            "batch_index": batch_index
        }


def _build_cog_url(container: str, blob_path: str) -> str:
    """
    Build Azure Blob Storage URL for COG access.

    Uses GDAL's /vsiaz/ virtual filesystem for direct COG access
    with range requests.

    Args:
        container: Azure Blob Storage container name
        blob_path: Path to COG within container

    Returns:
        GDAL-compatible Azure Blob URL
    """
    # Use /vsiaz/ for Azure Blob Storage with GDAL
    # Requires AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT env vars
    return f"/vsiaz/{container}/{blob_path}"


def _compute_zonal_stats(
    cells: List[Dict[str, Any]],
    cog_url: str,
    band: int,
    stats: List[str],
    logger
) -> List[Dict[str, Any]]:
    """
    Compute zonal statistics for H3 cells using rasterstats.

    Args:
        cells: List of cell dicts with h3_index and geom_wkt
        cog_url: GDAL-compatible raster URL
        band: Raster band (1-indexed)
        stats: Stat types to compute
        logger: Logger instance

    Returns:
        List of result dicts with h3_index and stat values
    """
    try:
        from rasterstats import zonal_stats
        from shapely import wkt
    except ImportError as e:
        raise ImportError(f"rasterstats or shapely not installed: {e}")

    # Convert cells to geometries
    geometries = []
    h3_indices = []
    for cell in cells:
        try:
            geom = wkt.loads(cell['geom_wkt'])
            geometries.append(geom)
            h3_indices.append(cell['h3_index'])
        except Exception as e:
            logger.warning(f"Failed to parse geometry for h3_index {cell.get('h3_index')}: {e}")
            continue

    if not geometries:
        logger.warning("No valid geometries to process")
        return []

    logger.debug(f"   Processing {len(geometries)} geometries...")

    # Compute zonal stats
    # rasterstats returns list of dicts with stat values
    try:
        results = zonal_stats(
            vectors=geometries,
            raster=cog_url,
            band=band,
            stats=stats,
            nodata=-9999,  # Common nodata value
            all_touched=True  # Include cells that touch polygon edge
        )
    except Exception as e:
        logger.error(f"rasterstats.zonal_stats failed: {e}")
        raise

    # Combine with h3_indices
    output = []
    for i, result in enumerate(results):
        if result is None:
            continue

        h3_index = h3_indices[i]
        result_dict = {'h3_index': h3_index}

        for stat_type in stats:
            value = result.get(stat_type)
            result_dict[stat_type] = value

        # Include count for pixel tracking
        result_dict['count'] = result.get('count', 0)

        output.append(result_dict)

    return output


# Export for handler registration
__all__ = ['h3_raster_zonal_stats']
