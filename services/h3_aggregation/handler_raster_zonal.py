# ============================================================================
# CLAUDE CONTEXT - H3 RASTER ZONAL STATS HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Raster Zonal Statistics
# PURPOSE: Compute zonal statistics from COGs for H3 cell batches
# LAST_REVIEWED: 27 DEC 2025
# EXPORTS: h3_raster_zonal_stats
# DEPENDENCIES: rasterstats, rasterio, shapely, pystac_client, util_logger
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
    - Supports Azure Blob Storage COGs (via SAS URL)
    - Supports Planetary Computer COGs (via signed URL)
    - **NEW**: Dynamic tile discovery for tiled datasets (27 DEC 2025)

Source Types:
    - "azure": Local Azure Blob Storage COG (requires container + blob_path)
    - "planetary_computer": Planetary Computer STAC item
        - With item_id: Single tile mode (legacy)
        - With source_id: Dynamic tile discovery mode (searches STAC for tiles)
    - "url": Direct HTTPS URL to COG (requires cog_url)

Usage (Azure):
    result = h3_raster_zonal_stats({
        "source_type": "azure",
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

Usage (Planetary Computer - Single Tile):
    result = h3_raster_zonal_stats({
        "source_type": "planetary_computer",
        "collection": "cop-dem-glo-30",
        "item_id": "Copernicus_DSM_COG_10_N35_00_E023_00",
        "asset": "data",
        "dataset_id": "copdem_glo30",
        "band": 1,
        "resolution": 6,
        "iso3": "GRC",
        "batch_start": 0,
        "batch_size": 1000,
        "stats": ["mean", "min", "max"]
    })

Usage (Planetary Computer - Dynamic Tile Discovery, 27 DEC 2025):
    result = h3_raster_zonal_stats({
        "source_type": "planetary_computer",
        "source_id": "cop-dem-glo-30",  # References h3.source_catalog
        "dataset_id": "copdem_glo30",
        "band": 1,
        "resolution": 6,
        "iso3": "RWA",
        "batch_start": 0,
        "batch_size": 500,
        "stats": ["mean", "min", "max"]
    })
    # Handler auto-discovers tiles covering Rwanda via STAC API search
"""

import time
from typing import Dict, Any, List, Optional
from util_logger import LoggerFactory, ComponentType, log_memory_checkpoint

from .base import validate_resolution, validate_stat_types, validate_dataset_id

# E13: Pipeline Observability (28 DEC 2025)
# Lazy import to avoid circular dependencies
_tracker_class = None

def _get_tracker_class():
    """Lazy load H3AggregationTracker to avoid import-time issues."""
    global _tracker_class
    if _tracker_class is None:
        from infrastructure.job_progress_contexts import H3AggregationTracker
        _tracker_class = H3AggregationTracker
    return _tracker_class


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
    source_type = params.get('source_type', 'azure')  # Default to Azure for backward compatibility
    dataset_id = params.get('dataset_id')
    band = params.get('band', 1)
    resolution = params.get('resolution')
    batch_start = params.get('batch_start', 0)
    batch_size = params.get('batch_size', 1000)
    batch_index = params.get('batch_index', 0)
    stats = params.get('stats', ['mean', 'sum', 'count'])
    append_history = params.get('append_history', False)
    source_job_id = params.get('source_job_id')
    nodata = params.get('nodata')  # Optional - will read from raster if not provided
    theme = params.get('theme')  # REQUIRED for partition routing - looked up from registry if not provided

    # Azure source parameters
    container = params.get('container')
    blob_path = params.get('blob_path')

    # Planetary Computer source parameters
    collection = params.get('collection')
    item_id = params.get('item_id')
    asset = params.get('asset', 'data')
    source_id = params.get('source_id')  # NEW: Reference to h3.source_catalog (27 DEC 2025)

    # Direct URL source parameter
    cog_url = params.get('cog_url')

    # Scope parameters
    iso3 = params.get('iso3')
    bbox = params.get('bbox')
    polygon_wkt = params.get('polygon_wkt')

    # Validate required parameters
    if not dataset_id:
        raise ValueError("dataset_id is required")
    if resolution is None:
        raise ValueError("resolution is required")

    # Validate source-specific parameters
    # NEW (27 DEC 2025): Support source_id for dynamic tile discovery
    use_dynamic_tile_discovery = False

    if source_type == 'azure':
        if not container:
            raise ValueError("container is required for source_type='azure'")
        if not blob_path:
            raise ValueError("blob_path is required for source_type='azure'")
    elif source_type == 'planetary_computer':
        if item_id:
            # Legacy mode: single tile specified
            if not collection:
                raise ValueError("collection is required when item_id is provided")
        elif source_id:
            # NEW: Dynamic tile discovery mode
            use_dynamic_tile_discovery = True
            logger.info(f"   Using dynamic tile discovery for source: {source_id}")
        else:
            raise ValueError(
                "Either 'item_id' (single tile mode) or 'source_id' (dynamic discovery) "
                "is required for source_type='planetary_computer'"
            )
    elif source_type == 'url':
        if not cog_url:
            raise ValueError("cog_url is required for source_type='url'")
    else:
        raise ValueError(f"Invalid source_type: {source_type}. Must be 'azure', 'planetary_computer', or 'url'")

    validate_resolution(resolution)
    validate_dataset_id(dataset_id)
    validate_stat_types(stats)

    logger.info(f"📊 Zonal Stats - Batch {batch_index}: {dataset_id}")
    logger.info(f"   Source type: {source_type}")
    if source_type == 'azure':
        logger.info(f"   Azure source: {container}/{blob_path} (band {band})")
    elif source_type == 'planetary_computer':
        logger.info(f"   PC source: {collection}/{item_id} asset={asset} (band {band})")
    else:
        logger.info(f"   URL source: {cog_url[:80]}... (band {band})")
    logger.info(f"   Range: offset={batch_start}, size={batch_size}")
    logger.info(f"   Stats: {stats}")

    # E13: Pipeline Observability - Create tracker for batch metrics (28 DEC 2025)
    tracker = None
    if source_job_id:
        try:
            TrackerClass = _get_tracker_class()
            tracker = TrackerClass(
                job_id=source_job_id,
                job_type="h3_raster_aggregation",
                auto_persist=True  # Write snapshots to app.job_metrics
            )
            # Note: Stage and task tracking is done at job level
            # Handler only records batch progress
        except Exception as e:
            logger.warning(f"Could not create metrics tracker: {e}")
            tracker = None

    try:
        from infrastructure.h3_repository import H3Repository

        h3_repo = H3Repository()

        # STEP 1.5: Get theme from dataset_registry or source_catalog (required for partition routing)
        if not theme:
            # Try dataset_registry first
            theme = h3_repo.get_dataset_theme(dataset_id)
            if theme:
                logger.info(f"   Theme from dataset_registry: {theme}")
            elif source_id:
                # NEW (27 DEC 2025): Fall back to source_catalog for dynamic discovery
                from infrastructure.h3_source_repository import H3SourceRepository
                source_repo = H3SourceRepository()
                try:
                    source_config = source_repo.get_source(source_id)
                    theme = source_config.get('theme')
                    logger.info(f"   Theme from source_catalog: {theme}")
                except ValueError:
                    pass  # Source not found, will raise below
            if not theme:
                raise ValueError(
                    f"Could not determine theme for dataset '{dataset_id}'. "
                    f"Either register in h3.dataset_registry, provide 'theme' parameter, "
                    f"or ensure source_id references a valid h3.source_catalog entry."
                )
        else:
            logger.info(f"   Theme from params: {theme}")

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

        # E13: Record cells loaded in tracker
        if tracker:
            tracker.set_cells_total(cells_count)

        # Memory checkpoint 1: After loading cells from database
        task_id = f"{source_job_id[:8] if source_job_id else 'unknown'}-b{batch_index}"
        log_memory_checkpoint(logger, "After loading H3 cells",
                              context_id=task_id,
                              cells_count=cells_count,
                              resolution=resolution)

        # STEP 3: Build COG URL based on source type
        # NEW (27 DEC 2025): Handle dynamic tile discovery for Planetary Computer
        if use_dynamic_tile_discovery:
            # Dynamic tile discovery mode - process all tiles covering the batch
            return _process_with_dynamic_tile_discovery(
                cells=cells,
                source_id=source_id,
                dataset_id=dataset_id,
                band=band,
                stats=stats,
                theme=theme,
                append_history=append_history,
                source_job_id=source_job_id,
                batch_index=batch_index,
                batch_start=batch_start,
                batch_size=batch_size,
                start_time=start_time,
                h3_repo=h3_repo,
                logger=logger,
                tracker=tracker  # E13: Pass tracker for dynamic discovery
            )

        # Standard single-tile mode
        if source_type == 'azure':
            raster_url, detected_nodata = _build_azure_cog_url(container, blob_path, logger)
        elif source_type == 'planetary_computer':
            raster_url, detected_nodata = _build_planetary_computer_url(collection, item_id, asset, logger)
        else:  # url
            raster_url = cog_url
            detected_nodata = None

        # Use provided nodata or detected nodata
        effective_nodata = nodata if nodata is not None else detected_nodata
        logger.info(f"   COG URL: {raster_url[:100]}...")
        logger.info(f"   Nodata value: {effective_nodata}")

        # Memory checkpoint 2: After COG URL resolution (includes STAC fetch for Planetary Computer)
        log_memory_checkpoint(logger, "After COG URL build",
                              context_id=task_id,
                              source_type=source_type)

        # STEP 4: Compute zonal stats using rasterstats
        zonal_results = _compute_zonal_stats(
            cells=cells,
            cog_url=raster_url,
            band=band,
            stats=stats,
            nodata=effective_nodata,
            logger=logger
        )

        logger.info(f"   Computed {len(zonal_results):,} stat values")

        # E13: Record batch progress in tracker
        if tracker:
            stats_count = len(zonal_results) * len(stats)
            tracker.record_batch(
                cells=cells_count,
                stats=stats_count,
                tile_id=item_id if item_id else (blob_path if blob_path else None),
                batch_index=batch_index
            )

        # Memory checkpoint 3: After zonal stats computation (PEAK MEMORY - rasterstats loads raster data)
        log_memory_checkpoint(logger, "After rasterstats computation",
                              context_id=task_id,
                              zonal_results_count=len(zonal_results),
                              stats_requested=stats)

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

        # STEP 6: Insert to h3.zonal_stats (partitioned by theme)
        stats_inserted = h3_repo.insert_zonal_stats_batch(
            stats=stat_records,
            theme=theme,  # Required partition key
            append_history=append_history,
            source_job_id=source_job_id
        )

        elapsed_time = time.time() - start_time
        logger.info(f"✅ Batch {batch_index} complete: {stats_inserted:,} stats in {elapsed_time:.2f}s")

        # Memory checkpoint 4: After database insertion (cleanup phase)
        log_memory_checkpoint(logger, "After DB insertion (cleanup)",
                              context_id=task_id,
                              stats_inserted=stats_inserted,
                              elapsed_seconds=round(elapsed_time, 2))

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


def _build_azure_cog_url(container: str, blob_path: str, logger) -> tuple:
    """
    Build Azure Blob Storage URL for COG access using SAS token.

    Uses /vsicurl/ with SAS URL for GDAL access. More reliable than
    /vsiaz/ which requires GDAL-level Azure credentials.

    Args:
        container: Azure Blob Storage container name
        blob_path: Path to COG within container
        logger: Logger instance

    Returns:
        Tuple of (GDAL-compatible URL, nodata value or None)
    """
    from infrastructure.blob import BlobRepository

    # Determine zone from container name
    is_silver_container = container.startswith('silver-')
    source_zone = "silver" if is_silver_container else "bronze"

    logger.debug(f"   Building Azure SAS URL for {source_zone} zone...")

    blob_repo = BlobRepository.for_zone(source_zone)
    sas_url = blob_repo.get_blob_url_with_sas(container, blob_path, hours=2)

    # Use /vsicurl/ for HTTPS access
    gdal_url = f"/vsicurl/{sas_url}"

    # Try to detect nodata from raster metadata
    nodata = None
    try:
        import rasterio
        with rasterio.open(sas_url) as src:
            nodata = src.nodata
            logger.debug(f"   Detected nodata from raster: {nodata}")
    except Exception as e:
        logger.debug(f"   Could not detect nodata from raster: {e}")

    return gdal_url, nodata


def _build_planetary_computer_url(collection: str, item_id: str, asset: str, logger) -> tuple:
    """
    Build Planetary Computer COG URL with signed token.

    Fetches STAC item and signs the asset URL for authenticated access.

    Args:
        collection: Planetary Computer collection ID (e.g., 'cop-dem-glo-30')
        item_id: STAC item ID
        asset: Asset key within the item (e.g., 'data')
        logger: Logger instance

    Returns:
        Tuple of (GDAL-compatible URL, nodata value or None)
    """
    try:
        import pystac_client
        import planetary_computer
    except ImportError as e:
        raise ImportError(
            f"pystac_client or planetary_computer not installed. "
            f"Install with: pip install pystac-client planetary-computer. Error: {e}"
        )

    logger.debug(f"   Fetching STAC item: {collection}/{item_id}")

    # Open Planetary Computer STAC API
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    # Fetch the specific item
    item = catalog.get_collection(collection).get_item(item_id)
    if item is None:
        raise ValueError(f"STAC item not found: {collection}/{item_id}")

    # Get asset URL
    if asset not in item.assets:
        available = list(item.assets.keys())
        raise ValueError(f"Asset '{asset}' not found. Available: {available}")

    asset_obj = item.assets[asset]
    signed_url = asset_obj.href

    logger.debug(f"   Got signed URL for asset '{asset}'")

    # Use /vsicurl/ for HTTPS access
    gdal_url = f"/vsicurl/{signed_url}"

    # Try to get nodata from STAC metadata
    nodata = None
    if hasattr(asset_obj, 'extra_fields'):
        # Check raster:bands extension
        raster_bands = asset_obj.extra_fields.get('raster:bands', [])
        if raster_bands and len(raster_bands) > 0:
            nodata = raster_bands[0].get('nodata')
            logger.debug(f"   Nodata from STAC metadata: {nodata}")

    # Fall back to reading from raster if not in STAC
    if nodata is None:
        try:
            import rasterio
            with rasterio.open(signed_url) as src:
                nodata = src.nodata
                logger.debug(f"   Detected nodata from raster: {nodata}")
        except Exception as e:
            logger.debug(f"   Could not detect nodata from raster: {e}")

    return gdal_url, nodata


def _compute_zonal_stats(
    cells: List[Dict[str, Any]],
    cog_url: str,
    band: int,
    stats: List[str],
    nodata: Any,
    logger
) -> List[Dict[str, Any]]:
    """
    Compute zonal statistics for H3 cells using rasterstats.

    Args:
        cells: List of cell dicts with h3_index and geom_wkt
        cog_url: GDAL-compatible raster URL (with /vsicurl/ prefix)
        band: Raster band (1-indexed)
        stats: Stat types to compute
        nodata: Nodata value (None to use raster's internal nodata)
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
        # Build kwargs - only include nodata if we have a value
        zs_kwargs = {
            'vectors': geometries,
            'raster': cog_url,
            'band': band,
            'stats': stats,
            'all_touched': True  # Include cells that touch polygon edge
        }
        if nodata is not None:
            zs_kwargs['nodata'] = nodata

        results = zonal_stats(**zs_kwargs)
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


# ============================================================================
# DYNAMIC TILE DISCOVERY (27 DEC 2025)
# ============================================================================

def _process_with_dynamic_tile_discovery(
    cells: List[Dict[str, Any]],
    source_id: str,
    dataset_id: str,
    band: int,
    stats: List[str],
    theme: str,
    append_history: bool,
    source_job_id: str,
    batch_index: int,
    batch_start: int,
    batch_size: int,
    start_time: float,
    h3_repo,
    logger,
    tracker=None  # E13: Optional H3AggregationTracker (28 DEC 2025)
) -> Dict[str, Any]:
    """
    Process H3 cells using dynamic tile discovery from source catalog.

    Automatically discovers Planetary Computer tiles that cover the cell
    batch's bounding box and processes each tile.

    Args:
        cells: List of H3 cells with geom_wkt
        source_id: Reference to h3.source_catalog entry
        dataset_id: Dataset identifier for storage
        band: Raster band (1-indexed)
        stats: Stat types to compute
        theme: Theme for partition routing
        append_history: Skip existing values if True
        source_job_id: Job ID for tracking
        batch_index: Batch index
        batch_start: Batch start offset
        batch_size: Batch size
        start_time: Start time for elapsed calculation
        h3_repo: H3Repository instance
        logger: Logger instance

    Returns:
        Success dict with computation results
    """
    try:
        import pystac_client
        import planetary_computer
    except ImportError as e:
        raise ImportError(
            f"pystac_client or planetary_computer not installed for dynamic tile discovery. "
            f"Install with: pip install pystac-client planetary-computer. Error: {e}"
        )

    from infrastructure.h3_source_repository import H3SourceRepository

    # STEP 1: Load source configuration from catalog
    source_repo = H3SourceRepository()
    try:
        source_config = source_repo.get_source(source_id)
    except ValueError as e:
        raise ValueError(f"Source '{source_id}' not found in h3.source_catalog: {e}")

    collection_id = source_config.get('collection_id')
    asset_key = source_config.get('asset_key', 'data')
    nodata_value = source_config.get('nodata_value')

    logger.info(f"   Source config: collection={collection_id}, asset={asset_key}")

    # STEP 2: Calculate bounding box from cells
    bbox = _calculate_cells_bbox(cells, logger)
    logger.info(f"   Cells bbox: {bbox}")

    # STEP 3: Discover tiles covering the bbox
    stac_api_url = source_config.get('stac_api_url', 'https://planetarycomputer.microsoft.com/api/stac/v1')

    catalog = pystac_client.Client.open(
        stac_api_url,
        modifier=planetary_computer.sign_inplace,
    )

    logger.info(f"   Searching STAC for tiles in bbox...")
    search = catalog.search(
        collections=[collection_id],
        bbox=bbox,
        max_items=100  # Safety limit - most batches should have < 10 tiles
    )

    items = list(search.items())
    logger.info(f"   Discovered {len(items)} tiles covering the batch")

    # E13: Record tiles discovered in tracker
    if tracker:
        tracker.set_tiles_discovered(
            count=len(items),
            tile_ids=[item.id for item in items[:10]]  # First 10 for context
        )
        tracker.set_cells_total(len(cells))

    if len(items) == 0:
        logger.warning(f"⚠️ No tiles found for bbox {bbox}")
        return {
            "success": True,
            "result": {
                "cells_processed": len(cells),
                "stats_inserted": 0,
                "tiles_processed": 0,
                "batch_index": batch_index,
                "elapsed_time": time.time() - start_time,
                "message": "No tiles found for batch area"
            }
        }

    # STEP 4: Process each tile
    all_stat_records = []
    processed_h3_indices = set()  # Track which cells have been processed

    for item in items:
        tile_id = item.id
        logger.debug(f"   Processing tile: {tile_id}")

        # E13: Record tile start
        if tracker:
            tracker.start_tile(tile_id)

        # Get asset URL
        if asset_key not in item.assets:
            logger.warning(f"   Asset '{asset_key}' not found in tile {tile_id}, skipping")
            continue

        signed_url = item.assets[asset_key].href
        gdal_url = f"/vsicurl/{signed_url}"

        # Get tile bounding box
        tile_bbox = item.bbox

        # Filter cells to those within this tile
        tile_cells = _filter_cells_to_tile_bbox(cells, tile_bbox, processed_h3_indices)

        if not tile_cells:
            logger.debug(f"   No unprocessed cells in tile {tile_id}")
            continue

        logger.debug(f"   Processing {len(tile_cells)} cells in tile {tile_id}")

        # Compute zonal stats for cells in this tile
        try:
            zonal_results = _compute_zonal_stats(
                cells=tile_cells,
                cog_url=gdal_url,
                band=band,
                stats=stats,
                nodata=nodata_value,
                logger=logger
            )

            # Build stat records
            for result in zonal_results:
                h3_index = result['h3_index']
                processed_h3_indices.add(h3_index)

                for stat_type in stats:
                    value = result.get(stat_type)
                    if value is not None:
                        all_stat_records.append({
                            'h3_index': h3_index,
                            'dataset_id': dataset_id,
                            'band': f"band_{band}",
                            'stat_type': stat_type,
                            'value': value,
                            'pixel_count': result.get('count'),
                            'nodata_count': result.get('nodata_count')
                        })

            # E13: Record batch progress for this tile
            if tracker:
                cells_in_tile = len(tile_cells)
                stats_in_tile = len(zonal_results) * len(stats)
                tracker.record_batch(
                    cells=cells_in_tile,
                    stats=stats_in_tile,
                    tile_id=tile_id,
                    batch_index=batch_index
                )
                tracker.complete_tile(tile_id)

        except Exception as e:
            logger.warning(f"   Failed to process tile {tile_id}: {e}")
            continue

    # STEP 5: Insert all stats to database
    if all_stat_records:
        stats_inserted = h3_repo.insert_zonal_stats_batch(
            stats=all_stat_records,
            theme=theme,
            append_history=append_history,
            source_job_id=source_job_id
        )
    else:
        stats_inserted = 0

    elapsed_time = time.time() - start_time
    logger.info(
        f"✅ Batch {batch_index} complete (dynamic discovery): "
        f"{len(processed_h3_indices)} cells, {stats_inserted} stats, "
        f"{len(items)} tiles in {elapsed_time:.2f}s"
    )

    return {
        "success": True,
        "result": {
            "cells_processed": len(processed_h3_indices),
            "cells_total": len(cells),
            "stats_inserted": stats_inserted,
            "tiles_discovered": len(items),
            "tiles_processed": len([i for i in items if i.id]),
            "batch_index": batch_index,
            "batch_start": batch_start,
            "batch_size": batch_size,
            "elapsed_time": elapsed_time,
            "dataset_id": dataset_id,
            "source_id": source_id,
            "source_job_id": source_job_id
        }
    }


def _calculate_cells_bbox(cells: List[Dict[str, Any]], logger) -> tuple:
    """
    Calculate bounding box from H3 cell geometries.

    Args:
        cells: List of cells with geom_wkt
        logger: Logger instance

    Returns:
        Tuple of (min_lon, min_lat, max_lon, max_lat)
    """
    from shapely import wkt

    min_lon = float('inf')
    min_lat = float('inf')
    max_lon = float('-inf')
    max_lat = float('-inf')

    for cell in cells:
        try:
            geom = wkt.loads(cell['geom_wkt'])
            bounds = geom.bounds  # (minx, miny, maxx, maxy)
            min_lon = min(min_lon, bounds[0])
            min_lat = min(min_lat, bounds[1])
            max_lon = max(max_lon, bounds[2])
            max_lat = max(max_lat, bounds[3])
        except Exception as e:
            logger.warning(f"Failed to parse geometry: {e}")
            continue

    return (min_lon, min_lat, max_lon, max_lat)


def _filter_cells_to_tile_bbox(
    cells: List[Dict[str, Any]],
    tile_bbox: tuple,
    already_processed: set
) -> List[Dict[str, Any]]:
    """
    Filter cells to those within a tile's bounding box.

    Also excludes cells that have already been processed to avoid duplicates.

    Args:
        cells: List of cells with h3_index and geom_wkt
        tile_bbox: Tile bounding box (min_lon, min_lat, max_lon, max_lat)
        already_processed: Set of h3_indices already processed

    Returns:
        Filtered list of cells
    """
    from shapely import wkt
    from shapely.geometry import box

    tile_min_lon, tile_min_lat, tile_max_lon, tile_max_lat = tile_bbox
    tile_box = box(tile_min_lon, tile_min_lat, tile_max_lon, tile_max_lat)

    filtered = []
    for cell in cells:
        h3_index = cell['h3_index']

        # Skip if already processed
        if h3_index in already_processed:
            continue

        try:
            geom = wkt.loads(cell['geom_wkt'])
            if geom.intersects(tile_box):
                filtered.append(cell)
        except Exception:
            continue

    return filtered


# Export for handler registration
__all__ = ['h3_raster_zonal_stats']
