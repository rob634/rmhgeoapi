# ============================================================================
# CLAUDE CONTEXT - RASTER PERSIST APP TABLES ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Upsert cog_metadata + raster_render_configs
# PURPOSE: Persist COG metadata and default render config to app schema tables,
#          caching a constructed stac_item_json as the source of truth for
#          later STAC materialization.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_persist_app_tables
# DEPENDENCIES: infrastructure.raster_metadata_repository,
#               infrastructure.raster_render_repository,
#               core.models.raster_render_config,
#               services.stac_renders
# ============================================================================
"""
Raster Persist App Tables - atomic handler for DAG workflows.

Upserts one row into app.cog_metadata and inserts one row into
app.raster_render_configs. Constructs and caches stac_item_json in the
cog_metadata row as the rebuild source of truth for pgSTAC materialization.

No blob I/O. No network I/O. Pure database writes.

Extracted from: services/handler_process_raster_complete.py
    Phase 3a (cog_metadata upsert): L1901-2018
    Phase 3b (render_config insert): L2021-2048

Sub-step independence:
    Each write (cog_metadata, render_config) is wrapped in its own try/except.
    Individual failures are non-fatal and reflected in degradation flags.
    The handler returns success=False only when ALL writes fail.

STAC JSON structure (P-S2):
    stac_item_json must include the fields that stac_materialize_item reads:
        id, type, geometry, bbox, collection,
        stac_version, stac_extensions,
        properties.datetime, properties.proj:epsg, properties.proj:transform,
        properties.renders, properties.processing:lineage,
        properties.geoetl:job_id, properties.geoetl:raster_type,
        assets.data.href (=/vsiaz/ path), assets.data.raster:bands
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# HANDLER ENTRY POINT
# ============================================================================

def raster_persist_app_tables(
    params: Dict[str, Any],
    context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Upsert app.cog_metadata and app.raster_render_configs for a processed COG.

    Receives all metadata from upstream DAG handlers via params (wired by the
    workflow YAML `receives:` directives). No blob or file I/O.

    Params (required):
        stac_item_id       str   Canonical STAC item ID (also the cog_id PK).
        collection_id      str   STAC collection / dataset bucket.
        silver_container   str   Azure storage container holding the COG.
        silver_blob_path   str   Blob path within the container.
        cog_url            str   /vsiaz/<container>/<blob_path> for GDAL/TiTiler.
        cog_size_bytes     int   COG file size in bytes.
        etag               str   Azure blob ETag.
        bounds_4326        list  [minx, miny, maxx, maxy] in WGS84.
        shape              list  [height, width] in pixels.
        raster_bands       list  raster:bands statistics list.
        rescale_range      list  [min, max] visualisation range.
        transform          list  Affine transform [a,b,c,d,e,f].
        resolution         list  [x_res, y_res] in CRS units.
        crs                str   CRS string e.g. "EPSG:4326".
        compression        str   COG compression method.
        tile_size          list  COG internal tile [width, height].
        overview_levels    list  COG overview level list.
        detected_type      str   Raster domain type (dem, rgb, flood_depth, …).
        band_count         int   Number of raster bands.
        data_type          str   Numpy dtype string (float32, uint8, …).
        source_crs         str   CRS of the source file before reprojection.
        blob_name          str   Source blob path (ETL provenance).
        job_id             str   ETL job identifier (_run_id).

    Params (optional):
        file_checksum      str   SHA-256 checksum of the COG file.
        nodata             float NoData pixel value.
        default_ramp       str   User-specified colormap override.

    Returns:
        Success:
            {"success": True, "result": {cog_metadata_upserted, cog_id,
             render_config_written, render_id, stac_item_json_cached, colormap}}
        Success with degradation:
            {"success": True, "result": {cog_metadata_upserted: False,
             cog_metadata_error, render_config_written: False,
             render_config_error, stac_item_json_cached: False}}
        All writes failed:
            {"success": False, "error": "All database writes failed",
             "error_type": "DatabaseError", "retryable": True}
        Invalid parameters:
            {"success": False, "error": "...", "error_type": "InvalidParameterError",
             "retryable": False}
    """

    try:  # Outer try/except — guarantees handler contract on unexpected errors
        # ------------------------------------------------------------------
        # Parameter extraction and validation
        # ------------------------------------------------------------------
        stac_item_id = params.get("stac_item_id")
        collection_id = params.get("collection_id")
        silver_container = params.get("silver_container")
        silver_blob_path = params.get("silver_blob_path")
        cog_url = params.get("cog_url")
        job_id = params.get("job_id") or params.get("_run_id")

        required = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "silver_container": silver_container,
            "silver_blob_path": silver_blob_path,
            "cog_url": cog_url,
            "job_id": job_id,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            return {
                "success": False,
                "error": f"Missing required parameters: {', '.join(missing)}",
                "error_type": "InvalidParameterError",
                "retryable": False,
            }

        # Optional / derived fields
        cog_size_bytes: Optional[int] = params.get("cog_size_bytes")
        etag: Optional[str] = params.get("etag")
        bounds_4326: list = params.get("bounds_4326") or []
        shape: list = params.get("shape") or []
        raster_bands: Optional[list] = params.get("raster_bands")
        rescale_range: Optional[list] = params.get("rescale_range")
        transform: Optional[list] = params.get("transform")
        resolution: Optional[list] = params.get("resolution")
        crs: str = params.get("crs") or "EPSG:4326"
        compression: Optional[str] = params.get("compression")
        tile_size = params.get("tile_size")
        overview_levels: Optional[list] = params.get("overview_levels")
        detected_type: str = params.get("detected_type") or "unknown"
        band_count: int = params.get("band_count") or 1
        data_type: str = params.get("data_type") or "float32"
        nodata: Optional[float] = params.get("nodata")
        source_crs: Optional[str] = params.get("source_crs")
        blob_name: Optional[str] = params.get("blob_name")
        default_ramp: Optional[str] = params.get("default_ramp")

        # Validate bounds list (P-B6)
        if bounds_4326 and len(bounds_4326) < 4:
            logger.warning(
                "bounds_4326 has fewer than 4 elements (%d); spatial bounds will be null",
                len(bounds_4326),
            )
            bounds_4326 = []

        # Validate shape list (P-B7)
        if shape and len(shape) < 2:
            logger.warning(
                "shape has fewer than 2 elements (%d); dimensions will be 0",
                len(shape),
            )
            shape = []

        # Spatial bounds (P-B6)
        bbox_minx: Optional[float] = bounds_4326[0] if len(bounds_4326) >= 4 else None
        bbox_miny: Optional[float] = bounds_4326[1] if len(bounds_4326) >= 4 else None
        bbox_maxx: Optional[float] = bounds_4326[2] if len(bounds_4326) >= 4 else None
        bbox_maxy: Optional[float] = bounds_4326[3] if len(bounds_4326) >= 4 else None

        # Dimensions (P-B7)
        cog_height: int = shape[0] if len(shape) >= 2 else 0
        cog_width: int = shape[1] if len(shape) >= 2 else 0

        # tile_size → blocksize (P-B8)
        blocksize: Optional[list] = tile_size if isinstance(tile_size, list) else None

        # Colormap for cog_metadata.colormap field (P-B2)
        # Deferred import — services.stac_renders has no heavy deps but kept consistent
        try:
            from services.stac_renders import recommend_colormap
            colormap: Optional[str] = recommend_colormap(detected_type)
        except Exception as _cm_err:
            logger.warning("recommend_colormap import failed: %s", _cm_err)
            colormap = None

        # ------------------------------------------------------------------
        # Build stac_item_json (P-B9 / P-N1)
        # ------------------------------------------------------------------
        # Construct before the DB writes so it can be included in the upsert.
        # This is a pure function — no I/O, always succeeds unless a stac.py
        # constant import fails (which would be a programming error).
        stac_item_json: Optional[Dict[str, Any]] = None
        try:
            from services.stac.stac_item_builder import build_stac_item

            if bounds_4326 and len(bounds_4326) >= 4:
                stac_item_json = build_stac_item(
                    item_id=stac_item_id,
                    collection_id=collection_id,
                    bbox=bounds_4326,
                    asset_href=cog_url,
                    asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    crs=crs,
                    transform=transform,
                    raster_bands=raster_bands,
                    detected_type=detected_type,
                    band_count=band_count,
                    data_type=data_type,
                    job_id=job_id,
                    epoch=5,
                )
            else:
                logger.warning(
                    "bounds_4326 empty or too short — skipping stac_item_json build for %s",
                    stac_item_id,
                )
        except Exception as stac_build_err:
            logger.warning(
                "stac_item_json construction failed (non-fatal, will cache null): %s",
                stac_build_err,
            )

        # ------------------------------------------------------------------
        # Sub-step A: app.cog_metadata upsert (P-B1, P-B10, P-B11, P-B12, P-B13)
        # ------------------------------------------------------------------
        cog_metadata_upserted = False
        cog_metadata_error: Optional[str] = None

        try:
            from infrastructure.raster_metadata_repository import RasterMetadataRepository

            cog_repo = RasterMetadataRepository.instance()
            success = cog_repo.upsert(
                # Identity (P-S1 — stac_item_id is the PK for both tables)
                cog_id=stac_item_id,
                container=silver_container,
                blob_path=silver_blob_path,
                cog_url=cog_url,
                # Dimensions (P-B7)
                width=cog_width,
                height=cog_height,
                # Raster type info
                band_count=band_count,
                dtype=data_type,
                nodata=nodata,
                # CRS (P-B13 — already a string like "EPSG:4326" from create_cog)
                crs=crs,
                # COG processing metadata
                is_cog=True,           # P-S4 — always True for this handler
                compression=compression,
                blocksize=blocksize,   # P-B8
                overview_levels=overview_levels,
                # Spatial (P-B6)
                bbox_minx=bbox_minx,
                bbox_miny=bbox_miny,
                bbox_maxx=bbox_maxx,
                bbox_maxy=bbox_maxy,
                # Geospatial detail
                transform=transform,
                resolution=resolution,
                raster_bands=raster_bands,
                rescale_range=rescale_range,
                # Visualization
                colormap=colormap,     # P-B2
                # STAC linkage
                stac_item_id=stac_item_id,
                stac_collection_id=collection_id,
                # ETL provenance (P-B11)
                etl_job_id=job_id,
                source_file=blob_name,
                source_crs=source_crs,
                # Raster type for query/filter (P-B12)
                custom_properties={"raster_type": detected_type},
                # STAC rebuild source of truth (P-B9)
                stac_item_json=stac_item_json,
            )

            if success:
                cog_metadata_upserted = True
                logger.info(
                    "cog_metadata upserted: %s (%dx%d, %s, cog_url=%s)",
                    stac_item_id, cog_width, cog_height, detected_type, cog_url,
                )
            else:
                # RasterMetadataRepository.upsert() returns False on error (already logs)
                cog_metadata_error = "upsert() returned False (table may be missing)"
                logger.warning(
                    "cog_metadata upsert returned False for %s", stac_item_id
                )

        except Exception as cog_meta_err:
            cog_metadata_error = str(cog_meta_err)
            logger.warning(
                "cog_metadata upsert failed (non-fatal) for %s: %s",
                stac_item_id, cog_meta_err,
            )

        # ------------------------------------------------------------------
        # Sub-step B: app.raster_render_configs insert (P-B3, P-B4, P-B10)
        # ------------------------------------------------------------------
        render_config_written = False
        render_config_error: Optional[str] = None
        render_colormap: Optional[str] = None

        try:
            from infrastructure.raster_render_repository import get_raster_render_repository
            from core.models.raster_render_config import RasterRenderConfig

            # P-B3: create default render config from raster type info
            # P-S3: detected_type drives colormap selection (not user raster_type string)
            render_config = RasterRenderConfig.create_default_for_cog(
                cog_id=stac_item_id,   # P-S1 — same key as cog_metadata
                dtype=data_type,
                band_count=band_count,
                nodata=nodata,
                detected_type=detected_type,
                default_ramp=default_ramp,
            )

            # P-B4: persist to app.raster_render_configs
            render_repo = get_raster_render_repository()
            render_repo.create_from_model(render_config)

            render_config_written = True
            render_colormap = render_config.render_spec.get("colormap_name")
            logger.info(
                "render_config persisted: %s (render_id=default, colormap=%s)",
                stac_item_id, render_colormap,
            )

        except Exception as render_err:
            render_config_error = str(render_err)
            logger.warning(
                "render_config creation failed (non-fatal) for %s: %s",
                stac_item_id, render_err,
            )

        # ------------------------------------------------------------------
        # Compose result
        # ------------------------------------------------------------------
        stac_item_json_cached = cog_metadata_upserted and stac_item_json is not None

        any_success = cog_metadata_upserted or render_config_written

        if not any_success:
            # All writes failed — caller should retry
            errors = []
            if cog_metadata_error:
                errors.append(f"cog_metadata: {cog_metadata_error}")
            if render_config_error:
                errors.append(f"render_config: {render_config_error}")
            return {
                "success": False,
                "error": "All database writes failed: " + "; ".join(errors),
                "error_type": "DatabaseError",
                "retryable": True,
            }

        result: Dict[str, Any] = {
            "cog_metadata_upserted": cog_metadata_upserted,
            "render_config_written": render_config_written,
            "stac_item_json_cached": stac_item_json_cached,
        }

        if cog_metadata_upserted:
            result["cog_id"] = stac_item_id
        else:
            result["cog_metadata_error"] = cog_metadata_error

        if render_config_written:
            result["render_id"] = "default"
            result["colormap"] = render_colormap or colormap
        else:
            result["render_config_error"] = render_config_error

        return {"success": True, "result": result}

    except Exception as exc:
        import traceback
        logger.error(f"raster_persist_app_tables unexpected error: {exc}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": f"Unexpected error in raster_persist_app_tables: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }
