# ============================================================================
# CLAUDE CONTEXT - RASTER PERSIST COLLECTION HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 raster collection)
# STATUS: Atomic handler - Write N cog_metadata rows for a raster collection
# PURPOSE: Receive correlated upload + COG + validation results from fan-ins,
#          build stac_item_json per file, upsert N cog_metadata rows.
# CREATED: 01 APR 2026
# EXPORTS: raster_persist_collection
# DEPENDENCIES: infrastructure.raster_metadata_repository, services.stac.stac_item_builder
# ============================================================================
"""
Raster Persist Collection -- write N cog_metadata rows from correlated fan-in results.

After the fan-out/fan-in cycles for download, COG creation, and upload complete,
this single-task handler receives the three correlated result lists and persists
one cog_metadata row per file. Each row caches a stac_item_json so
stac_materialize_item can later upsert them into pgSTAC.

Correlation is by positional index: all three lists are ordered identically
because the fan-out preserves order.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_persist_collection(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Persist N cog_metadata rows from correlated fan-in results for a collection.

    Params:
        upload_results (list): Fan-in collected upload results. Each wrapped as
            {"success": True, "result": {...}}. Inner keys: stac_item_id,
            silver_container, silver_blob_path, cog_url, cog_size_bytes, etag.
        cog_results (list): Fan-in collected COG results. Each wrapped. Inner keys:
            cog_path, cog_blob, bounds_4326, shape, raster_bands, rescale_range,
            transform, resolution, crs, compression, tile_size, overview_levels.
        file_specs (list): From homogeneity check (NOT fan-in wrapped). Each:
            blob_stem, blob_name, source_crs, raster_type (dict), band_count,
            dtype, nodata, source_bounds.
        collection_id (str): STAC collection ID.
        dataset_id, resource_id, version_id, access_level, title, tags,
            release_id, asset_id: Platform metadata.
        _run_id (str): System-injected, used as job_id.

    Returns:
        {"success": True, "result": {"cog_ids": [...], "collection_id": "...", "item_count": N}}
    """
    # ---- Extract parameters ------------------------------------------------
    upload_results = params.get("upload_results")
    cog_results = params.get("cog_results")
    file_specs = params.get("file_specs")
    collection_id = params.get("collection_id")
    job_id = params.get("_run_id") or params.get("job_id", "unknown")

    # Platform metadata
    dataset_id = params.get("dataset_id")
    resource_id = params.get("resource_id")
    version_id = params.get("version_id")
    release_id = params.get("release_id")

    # ---- Validate required inputs ------------------------------------------
    missing = []
    if not upload_results:
        missing.append("upload_results")
    if not cog_results:
        missing.append("cog_results")
    if not file_specs:
        missing.append("file_specs")
    if not collection_id:
        missing.append("collection_id")

    if missing:
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # ---- Unwrap fan-in results ---------------------------------------------
    # upload_results and cog_results are fan-in wrapped: {"success": ..., "result": {...}}
    # file_specs comes from a single task (homogeneity check), NOT fan-in wrapped.
    uploads = []
    for entry in upload_results:
        result = entry.get("result", entry) if isinstance(entry, dict) else {}
        uploads.append(result)

    cogs = []
    for entry in cog_results:
        result = entry.get("result", entry) if isinstance(entry, dict) else {}
        cogs.append(result)

    # ---- Validate list lengths match ---------------------------------------
    n = len(file_specs)
    if len(uploads) != n or len(cogs) != n:
        return {
            "success": False,
            "error": (
                f"List length mismatch: file_specs={n}, "
                f"upload_results={len(uploads)}, cog_results={len(cogs)}"
            ),
            "error_type": "ValidationError",
            "retryable": False,
        }

    if n == 0:
        return {
            "success": False,
            "error": "No files to persist (all lists empty)",
            "error_type": "DataError",
            "retryable": False,
        }

    # ---- Persist each file -------------------------------------------------
    try:
        from infrastructure.raster_metadata_repository import RasterMetadataRepository
        from services.stac_renders import recommend_colormap
        from services.stac.stac_item_builder import build_stac_item

        cog_repo = RasterMetadataRepository.instance()
        persisted_ids = []
        errors = []

        for idx in range(n):
            upload = uploads[idx]
            cog = cogs[idx]
            spec = file_specs[idx]

            stac_item_id = upload.get("stac_item_id")
            if not stac_item_id:
                errors.append(f"Index {idx}: missing stac_item_id in upload result")
                continue

            # Upload fields
            container = upload.get("silver_container", "silver-cogs")
            blob_path = upload.get("silver_blob_path", "")
            cog_url = upload.get("cog_url", "")

            # COG fields
            bounds = cog.get("bounds_4326", [])
            shape = cog.get("shape", [0, 0])
            crs = cog.get("crs", "EPSG:4326")
            raster_bands = cog.get("raster_bands")

            # File spec fields
            raster_type = spec.get("raster_type", {})
            detected_type = raster_type.get("type_name", "unknown") if isinstance(raster_type, dict) else str(raster_type)
            band_count = spec.get("band_count", 1)
            data_type = spec.get("dtype", "float32")
            nodata_val = spec.get("nodata")
            source_crs = spec.get("source_crs")
            blob_name = spec.get("blob_name", "")

            if len(bounds) < 4:
                errors.append(f"Index {idx} ({stac_item_id}): missing bounds_4326")
                continue

            # Build STAC item JSON
            try:
                stac_item_json = build_stac_item(
                    item_id=stac_item_id,
                    collection_id=collection_id,
                    bbox=bounds,
                    asset_href=cog_url,
                    asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    crs=crs,
                    detected_type=detected_type,
                    band_count=band_count,
                    data_type=data_type,
                    raster_bands=raster_bands,
                    job_id=job_id,
                    epoch=5,
                    dataset_id=dataset_id,
                    resource_id=resource_id,
                    version_id=version_id,
                )
            except Exception as build_err:
                errors.append(f"{stac_item_id}: stac_item build failed: {build_err}")
                continue

            colormap = recommend_colormap(detected_type)

            # Upsert cog_metadata row
            try:
                cog_repo.upsert(
                    cog_id=stac_item_id,
                    container=container,
                    blob_path=blob_path,
                    cog_url=cog_url,
                    width=shape[1] if len(shape) > 1 else 0,
                    height=shape[0] if len(shape) > 0 else 0,
                    band_count=band_count,
                    dtype=data_type,
                    nodata=nodata_val,
                    crs=crs,
                    is_cog=True,
                    bbox_minx=bounds[0],
                    bbox_miny=bounds[1],
                    bbox_maxx=bounds[2],
                    bbox_maxy=bounds[3],
                    colormap=colormap,
                    stac_item_id=stac_item_id,
                    stac_collection_id=collection_id,
                    etl_job_id=job_id,
                    source_file=blob_name,
                    source_crs=source_crs,
                    custom_properties={
                        "raster_type": detected_type,
                        "collection_member": True,
                    },
                    stac_item_json=stac_item_json,
                )
                persisted_ids.append(stac_item_id)
            except Exception as upsert_err:
                logger.warning(
                    "persist_collection: failed to upsert cog_metadata for %s: %s",
                    stac_item_id, upsert_err,
                )
                errors.append(f"{stac_item_id}: {upsert_err}")

        # ---- Check for total failure ---------------------------------------
        if not persisted_ids:
            return {
                "success": False,
                "error": f"All {n} file persists failed: {'; '.join(errors[:3])}",
                "error_type": "DatabaseError",
                "retryable": True,
            }

        logger.info(
            "raster_persist_collection: %d/%d files persisted for collection %s",
            len(persisted_ids), n, collection_id,
        )

        # ---- Update release (non-fatal) ------------------------------------
        if release_id:
            try:
                from infrastructure.release_repository import ReleaseRepository
                from core.models.asset import ProcessingStatus
                from datetime import datetime, timezone

                release_repo = ReleaseRepository()
                release_repo.update_physical_outputs(
                    release_id=release_id,
                    blob_path=f"cogs/{collection_id}/",
                    stac_item_id=collection_id,
                    output_mode="collection",
                    tile_count=len(persisted_ids),
                )
                release_repo.update_processing_status(
                    release_id,
                    ProcessingStatus.COMPLETED,
                    completed_at=datetime.now(timezone.utc),
                )
                logger.info(
                    "Updated release %s with collection outputs (%d files)",
                    release_id[:16], len(persisted_ids),
                )
            except Exception as rel_err:
                logger.warning(
                    "Failed to update release %s: %s (non-fatal)",
                    release_id[:16] if release_id else "unknown", rel_err,
                )

        return {
            "success": True,
            "result": {
                "cog_ids": persisted_ids,
                "collection_id": collection_id,
                "item_count": len(persisted_ids),
                "errors": errors if errors else None,
                "partial_failure": len(errors) > 0,
                "failure_ratio": f"{len(errors)}/{n}",
            },
        }

    except Exception as exc:
        import traceback
        logger.error(
            "raster_persist_collection failed: %s\n%s", exc, traceback.format_exc()
        )
        return {
            "success": False,
            "error": f"Collection persist failed: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }
