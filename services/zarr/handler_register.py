# ============================================================================
# CLAUDE CONTEXT - ZARR REGISTER METADATA HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6)
# STATUS: Atomic handler - Write zarr_metadata + cache stac_item_json
# PURPOSE: After zarr copy/rechunk completes, open the silver store,
#          extract metadata, write to app.zarr_metadata. STAC materialization
#          is handled by the composable stac_materialize_item handler.
# LAST_REVIEWED: 23 MAR 2026
# EXPORTS: zarr_register_metadata
# DEPENDENCIES: xarray, infrastructure.zarr_metadata_repository
# ============================================================================
"""
Zarr Register Metadata — write zarr_metadata row from silver store.

Opens the Zarr store in silver via xarray, extracts dimensions, variables,
spatial extent, and temporal range. Builds and caches stac_item_json.
Does NOT write to pgSTAC — that's stac_materialize_item's job.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_register")


def zarr_register_metadata(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Extract metadata from silver Zarr store and persist to zarr_metadata table.

    Params:
        zarr_store_url (str, required): abfs:// URL to silver Zarr store
        stac_item_id (str, required): Deterministic STAC item ID
        collection_id (str, required): STAC collection ID
        dataset_id (str): Dataset identifier
        resource_id (str): Resource identifier
        pipeline (str): "ingest_zarr" or "netcdf_to_zarr"
        source_file (str): Original source filename
        title (str): Optional title
        access_level (str): Optional access level
        _run_id (str): System-injected

    Returns:
        {"success": True, "result": {zarr_id, variables, dimensions, ...}}
    """
    # Prefer target (silver) URL if available, fall back to source URL
    target_container = params.get("target_container", "silver-zarr")
    target_prefix = params.get("target_prefix")
    if target_prefix:
        zarr_store_url = f"abfs://{target_container}/{target_prefix}.zarr"
    else:
        zarr_store_url = params.get("zarr_store_url") or params.get("source_url")
    stac_item_id = params.get("stac_item_id")
    collection_id = params.get("collection_id")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")
    pipeline = params.get("pipeline", "ingest_zarr")
    source_file = params.get("source_file")
    title = params.get("title")
    access_level = params.get("access_level")
    run_id = params.get("_run_id", "unknown")
    # Spatial extent from validate handler (avoids re-extraction from pyramid store)
    validated_spatial_extent = params.get("spatial_extent")

    dry_run = params.get("dry_run", False)

    missing = []
    if not zarr_store_url:
        missing.append("zarr_store_url")
    if not stac_item_id:
        missing.append("stac_item_id")
    if not collection_id:
        missing.append("collection_id")
    if missing:
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    if dry_run:
        logger.info("zarr_register_metadata: [DRY-RUN] skipping registration")
        return {
            "success": True,
            "result": {
                "zarr_id": stac_item_id or "dry-run",
                "dry_run": True,
            },
        }

    try:
        import numpy as np
        import xarray as xr
        from infrastructure import BlobRepository
        from infrastructure.zarr_metadata_repository import ZarrMetadataRepository

        start = time.monotonic()

        # Parse store URL
        store_path = zarr_store_url.replace("abfs://", "")
        parts = store_path.split("/", 1)
        silver_container = parts[0]
        store_prefix = parts[1] if len(parts) > 1 else ""

        # Open Zarr store from silver — use BlobRepository for auth
        silver_repo = BlobRepository.for_zone("silver")
        silver_account = silver_repo.account_name
        storage_options = silver_repo.get_xarray_storage_options()

        zarr_store_url = f"abfs://{silver_container}/{store_prefix}"

        ds = None
        try:
            ds = xr.open_zarr(zarr_store_url, storage_options=storage_options, consolidated=True)
        except Exception:
            ds = xr.open_zarr(zarr_store_url, storage_options=storage_options, consolidated=False)

        # Extract metadata
        variables = list(ds.data_vars)
        dimensions = {dim: int(size) for dim, size in ds.dims.items()}

        # Spatial extent — prefer validated value (from source before pyramid coarsening)
        spatial_extent = validated_spatial_extent
        if not spatial_extent:
            from services.zarr import extract_spatial_extent
            spatial_extent = extract_spatial_extent(ds)

        # Time range
        time_range = None
        for time_name in ["time", "t"]:
            if time_name in ds.coords:
                try:
                    time_vals = ds.coords[time_name].values
                    time_range = [str(np.nanmin(time_vals)), str(np.nanmax(time_vals))]
                except Exception as time_exc:
                    logger.warning("Time range extraction failed for coord '%s': %s", time_name, time_exc)
                break

        time_steps = None
        if "time" in dimensions:
            time_steps = dimensions["time"]
        elif "t" in dimensions:
            time_steps = dimensions["t"]

        coord_names = list(ds.coords) if ds else []
        ds.close()

        # Build STAC item JSON — use global bbox fallback if spatial extent unavailable
        # Pyramid stores may not preserve coordinate arrays in coarsened groups
        if not spatial_extent:
            logger.warning(
                "zarr_register_metadata: no spatial coords found, using global bbox fallback. "
                "Store: %s, dims: %s, coords: %s",
                zarr_store_url, list(dimensions.keys()), coord_names,
            )
            spatial_extent = [-180.0, -90.0, 180.0, 90.0]
        bbox = spatial_extent

        now_iso = datetime.now(timezone.utc).isoformat()
        zarr_abfs_url = f"abfs://{silver_container}/{store_prefix}"

        from services.stac.stac_item_builder import build_stac_item

        # Temporal: use range if available, else stamp with current datetime
        start_dt = time_range[0] if time_range and len(time_range) == 2 else None
        end_dt = time_range[1] if time_range and len(time_range) == 2 else None
        datetime_val = None if time_range else now_iso

        stac_item_json = build_stac_item(
            item_id=stac_item_id,
            collection_id=collection_id,
            bbox=bbox,
            asset_href=zarr_abfs_url,
            asset_type="application/vnd+zarr",
            asset_key="zarr-store",
            asset_roles=["data"],
            datetime=datetime_val,
            start_datetime=start_dt,
            end_datetime=end_dt,
            zarr_variables=variables,
            zarr_dimensions=dimensions,
            dataset_id=dataset_id if dataset_id != "unknown" else None,
            resource_id=resource_id if resource_id != "unknown" else None,
            title=title,
            job_id=run_id,
            epoch=5,
        )

        # Preserve xarray:open_kwargs — engine/chunks metadata for catalog consumers.
        # storage_options deliberately omitted (DF-STAC-5: account_name is internal).
        stac_item_json["properties"]["xarray:open_kwargs"] = {
            "engine": "zarr",
            "chunks": {},
        }

        # Stamp data type for unpublish routing (P5: paired lifecycle discovery)
        stac_item_json["properties"]["geoetl:data_type"] = "zarr"

        # Stamp zarr asset title (build_stac_item sets only href/type/roles)
        stac_item_json["assets"]["zarr-store"]["title"] = "Zarr Store"

        # Write to zarr_metadata table
        zarr_repo = ZarrMetadataRepository()
        success = zarr_repo.upsert(
            zarr_id=stac_item_id,
            container=silver_container,
            store_prefix=store_prefix,
            store_url=zarr_abfs_url,
            variables=variables,
            dimensions=dimensions,
            bbox_minx=bbox[0],
            bbox_miny=bbox[1],
            bbox_maxx=bbox[2],
            bbox_maxy=bbox[3],
            crs="EPSG:4326",
            time_start=time_range[0] if time_range else None,
            time_end=time_range[1] if time_range else None,
            time_steps=time_steps,
            stac_item_id=stac_item_id,
            stac_collection_id=collection_id,
            stac_item_json=stac_item_json,
            pipeline=pipeline,
            etl_job_id=run_id,
            source_file=source_file,
            source_format="zarr" if pipeline == "ingest_zarr" else "netcdf",
        )

        # Cache stac_item_json in asset_releases for catalog lookups
        release_id = params.get("release_id")
        if release_id and stac_item_json:
            try:
                from infrastructure.release_repository import ReleaseRepository
                ReleaseRepository().update_stac_item_json(release_id, stac_item_json)
                logger.info("zarr_register_metadata: cached stac_item_json in release %s", release_id[:16])
            except Exception as rel_exc:
                logger.warning("zarr_register_metadata: failed to cache stac_item_json in release: %s", rel_exc)

        elapsed = time.monotonic() - start

        if not success:
            return {
                "success": False,
                "error": "zarr_metadata upsert returned False",
                "error_type": "DatabaseError",
                "retryable": True,
            }

        logger.info(
            "zarr_register_metadata: %s → zarr_metadata (%d vars, %s dims, %.1fs)",
            stac_item_id, len(variables), dimensions, elapsed,
        )

        return {
            "success": True,
            "result": {
                "zarr_id": stac_item_id,
                "collection_id": collection_id,
                "variables": variables,
                "dimensions": dimensions,
                "spatial_extent": spatial_extent,
                "time_range": time_range,
                "store_url": zarr_abfs_url,
                "stac_item_json_cached": True,
            },
        }

    except Exception as exc:
        import traceback
        logger.error("zarr_register_metadata failed: %s\n%s", exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"Zarr registration failed: {exc}",
            "error_type": "RegistrationError",
            "retryable": True,
        }
