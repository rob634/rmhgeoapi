# ============================================================================
# CLAUDE CONTEXT - RASTER PERSIST TILED HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6)
# STATUS: Atomic handler - Write N cog_metadata rows from tiled raster output
# PURPOSE: After fan-in aggregates tile results, persist each tile's metadata
#          to cog_metadata + render_config so STAC materialization can find them
# LAST_REVIEWED: 22 MAR 2026
# EXPORTS: raster_persist_tiled
# DEPENDENCIES: infrastructure.raster_metadata_repository, services.stac_renders
# ============================================================================
"""
Raster Persist Tiled — write N cog_metadata rows from aggregated fan-in results.

After the fan-out processes N tiles (extract → COG → upload), the fan-in
collects all tile results. This handler takes the aggregated list and
persists one cog_metadata + render_config row per tile.

Each row caches a stac_item_json so stac_materialize_item can later
upsert them into pgSTAC.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_persist_tiled(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Persist N cog_metadata rows from aggregated tile results.

    Params:
        collection_id (str, required): STAC collection ID
        tile_results (list[dict], required): Aggregated from fan-in, each with:
            {item_id, blob_path, container, cog_url, bounds_4326, cog_size_bytes, row, col}
        source_crs (str): Original CRS before reprojection
        detected_type (str): Raster type from validation
        band_count (int): Number of bands
        data_type (str): Numpy dtype
        nodata (float|None): Nodata value
        job_id (str): ETL traceability
        blob_name (str): Original source filename

    Returns:
        {"success": True, "result": {tiles_persisted, cog_ids, collection_id}}
    """
    collection_id = params.get("collection_id")
    tile_results = params.get("tile_results")
    source_crs = params.get("source_crs")
    detected_type = params.get("detected_type", "unknown")
    band_count = params.get("band_count", 1)
    data_type = params.get("data_type", "float32")
    nodata_val = params.get("nodata")
    job_id = params.get("job_id") or params.get("_run_id", "unknown")
    blob_name = params.get("blob_name")

    if not collection_id or not tile_results:
        missing = []
        if not collection_id:
            missing.append("collection_id")
        if not tile_results:
            missing.append("tile_results")
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # tile_results comes from fan-in aggregation — it's a list of completed task results
    # Each entry is the full result_data dict from a fan-out child
    tiles = []
    for entry in tile_results:
        # Fan-in collect mode wraps each child's result_data
        result = entry.get("result", entry) if isinstance(entry, dict) else {}
        if result.get("item_id"):
            tiles.append(result)

    if not tiles:
        return {
            "success": False,
            "error": "No valid tile results found in aggregated data",
            "error_type": "DataError",
            "retryable": False,
        }

    try:
        from infrastructure.raster_metadata_repository import RasterMetadataRepository
        from services.stac_renders import recommend_colormap
        from services.stac.stac_item_builder import build_stac_item

        cog_repo = RasterMetadataRepository.instance()
        colormap = recommend_colormap(detected_type)
        persisted_ids = []
        errors = []

        for tile in tiles:
            tile_cog_id = tile["item_id"]
            tile_blob_path = tile.get("blob_path", "")
            tile_container = tile.get("container", "silver-cogs")
            tile_bounds = tile.get("bounds_4326", [])
            tile_cog_url = tile.get("cog_url", "")
            tile_row = tile.get("row", 0)
            tile_col = tile.get("col", 0)

            # Build full stac_item_json for cog_metadata cache (rich metadata)
            stac_item_json = build_stac_item(
                item_id=tile_cog_id,
                collection_id=collection_id,
                bbox=tile_bounds if len(tile_bounds) >= 4 else [0, 0, 0, 0],
                asset_href=tile_cog_url,
                asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
                crs="EPSG:4326",
                detected_type=detected_type,
                band_count=band_count,
                data_type=data_type,
                job_id=job_id,
                epoch=5,
            )

            # Spatial bounds
            bbox_minx = tile_bounds[0] if len(tile_bounds) >= 4 else None
            bbox_miny = tile_bounds[1] if len(tile_bounds) >= 4 else None
            bbox_maxx = tile_bounds[2] if len(tile_bounds) >= 4 else None
            bbox_maxy = tile_bounds[3] if len(tile_bounds) >= 4 else None

            try:
                cog_repo.upsert(
                    cog_id=tile_cog_id,
                    container=tile_container,
                    blob_path=tile_blob_path,
                    cog_url=tile_cog_url,
                    width=0,  # Tile dimensions not tracked individually
                    height=0,
                    band_count=band_count,
                    dtype=data_type,
                    nodata=nodata_val,
                    crs="EPSG:4326",
                    is_cog=True,
                    bbox_minx=bbox_minx,
                    bbox_miny=bbox_miny,
                    bbox_maxx=bbox_maxx,
                    bbox_maxy=bbox_maxy,
                    colormap=colormap,
                    stac_item_id=tile_cog_id,
                    stac_collection_id=collection_id,
                    etl_job_id=job_id,
                    source_file=blob_name,
                    source_crs=source_crs,
                    custom_properties={
                        "raster_type": detected_type,
                        "tile_row": tile_row,
                        "tile_col": tile_col,
                    },
                    stac_item_json=stac_item_json,
                )
                persisted_ids.append(tile_cog_id)
            except Exception as tile_err:
                logger.warning(
                    "persist_tiled: failed to upsert cog_metadata for %s: %s",
                    tile_cog_id, tile_err,
                )
                errors.append(f"{tile_cog_id}: {tile_err}")

        if not persisted_ids:
            return {
                "success": False,
                "error": f"All {len(tiles)} tile persists failed: {'; '.join(errors[:3])}",
                "error_type": "DatabaseError",
                "retryable": True,
            }

        logger.info(
            "raster_persist_tiled: %d/%d tiles persisted for collection %s",
            len(persisted_ids), len(tiles), collection_id,
        )

        return {
            "success": True,
            "result": {
                "tiles_persisted": len(persisted_ids),
                "total_tiles": len(tiles),
                "cog_ids": persisted_ids,
                "collection_id": collection_id,
                "errors": errors if errors else None,
                "partial_failure": len(errors) > 0,
                "failure_ratio": f"{len(errors)}/{len(tiles)}",
            },
        }

    except Exception as exc:
        import traceback
        logger.error("raster_persist_tiled failed: %s\n%s", exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"Tiled persist failed: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }
