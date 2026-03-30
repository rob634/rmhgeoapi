# ============================================================================
# CLAUDE CONTEXT - ZARR GENERATE PYRAMID HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Generate multiscale pyramid from flat Zarr store
# PURPOSE: Reads rechunked Zarr, generates ndpyramid levels, writes pyramid store
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: zarr_generate_pyramid
# DEPENDENCIES: ndpyramid, rioxarray, xarray, zarr
# ============================================================================
"""
Zarr Generate Pyramid — multiscale pyramid generation for TiTiler-xarray.

Reads a flat rechunked Zarr store, generates downsampled pyramid levels via
ndpyramid.pyramid_resample(), and writes a multi-group Zarr v3 store.
Output follows the Zarr multiscales convention (groups named 0, 1, 2, ...).

Level 0 = full resolution (identical to input data, lossless).
Levels 1-N = 2x downsampled per level. O(1) tile reads at any zoom.
Storage overhead: ~33% above base level.
"""

import time
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_generate_pyramid")

SPATIAL_NAMES = {"lat", "latitude", "y"}
LON_NAMES = {"lon", "longitude", "x"}
ALL_SPATIAL = SPATIAL_NAMES | LON_NAMES


def _detect_spatial_dims(ds):
    """Detect lat/lon dimension names from dataset."""
    lat_dim = lon_dim = None
    for dim in ds.dims:
        dim_lower = dim.lower()
        if dim_lower in SPATIAL_NAMES:
            lat_dim = dim
        elif dim_lower in LON_NAMES:
            lon_dim = dim
    return lat_dim, lon_dim


def _auto_detect_levels(dimensions, lat_dim, lon_dim, chunk_size=256):
    """Compute pyramid levels until coarsest fits in one chunk."""
    max_spatial = max(dimensions.get(lat_dim, 1), dimensions.get(lon_dim, 1))
    if max_spatial <= chunk_size:
        return 1
    levels = 0
    size = max_spatial
    while size > chunk_size:
        size //= 2
        levels += 1
    return max(levels, 1)


def zarr_generate_pyramid(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Generate multiscale pyramid from a flat/rechunked Zarr store.

    Params:
        zarr_store_url (str): abfs:// URL of the rechunked store
        target_container (str): Output container (e.g. "silver-zarr")
        target_prefix (str): Output blob prefix (pyramid written to {prefix}_pyramid.zarr)
        pyramid_levels (int): Number of levels (0 = auto-detect from dimensions)
        resampling (str): "bilinear" (default), "nearest"
        zarr_format (int): 3 (default)
        dry_run (bool): If True, compute levels but skip write
        dimensions (dict): From validate handler — {dim_name: size}

    Returns:
        {"success": True, "result": {"pyramid_url": ..., "levels_generated": N, ...}}
    """
    start = time.time()

    zarr_store_url = params.get("zarr_store_url")
    target_container = params.get("target_container", "silver-zarr")
    target_prefix = params.get("target_prefix")
    pyramid_levels = params.get("pyramid_levels", 0)
    resampling = params.get("resampling", "bilinear")
    zarr_format = params.get("zarr_format", 3)
    dry_run = params.get("dry_run", True)
    dimensions = params.get("dimensions", {})

    if not zarr_store_url:
        return {
            "success": False,
            "error": "zarr_store_url is required",
            "error_type": "ValidationError",
        }

    logger.info(
        "zarr_generate_pyramid: source=%s, levels=%s, resampling=%s, dry_run=%s",
        zarr_store_url, pyramid_levels, resampling, dry_run,
    )

    try:
        import xarray as xr
        import rioxarray  # noqa: F401 — registers .rio accessor
        from ndpyramid import pyramid_coarsen

        # Resolve storage options — conditional on URL scheme
        # Local mount path: no storage_options needed
        # Cloud URL: zone-aware credentials via get_xarray_storage_options()
        #
        # IMPORTANT: zarr_store_url may point to Bronze OR Silver.
        # When rechunk is skipped (chunks already optimal), the URL is the
        # original Bronze abfs:// source. When rechunked, it's Silver.
        # We detect the zone by comparing the URL container against
        # target_container (always "silver-zarr" in the YAML default).
        from infrastructure.etl_mount import is_cloud_source
        if is_cloud_source(zarr_store_url):
            from infrastructure.blob import BlobRepository
            # Parse container from abfs://{container}/{path} or az://{container}/{path}
            url_stripped = zarr_store_url.split("://", 1)[1]
            url_container = url_stripped.split("/")[0]
            if url_container == target_container:
                # Rechunked output lives in Silver
                source_repo = BlobRepository.for_zone("silver")
            else:
                # Rechunk was skipped — URL points to original Bronze source
                source_repo = BlobRepository.for_zone("bronze")
            storage_options = source_repo.get_xarray_storage_options()
        else:
            storage_options = {}

        open_kwargs = {"consolidated": True}
        if storage_options:
            open_kwargs["storage_options"] = storage_options

        try:
            ds = xr.open_zarr(zarr_store_url, **open_kwargs)
        except Exception:
            logger.info("zarr_generate_pyramid: consolidated metadata not available, retrying without")
            open_kwargs["consolidated"] = False
            ds = xr.open_zarr(zarr_store_url, **open_kwargs)

        try:
            lat_dim, lon_dim = _detect_spatial_dims(ds)
            if not lat_dim or not lon_dim:
                return {
                    "success": False,
                    "error": f"Cannot detect spatial dimensions. Found: {list(ds.dims)}",
                    "error_type": "ValidationError",
                }

            if pyramid_levels <= 0:
                pyramid_levels = _auto_detect_levels(
                    dict(ds.sizes), lat_dim, lon_dim
                )

            level_sizes = {}
            lat_size = ds.sizes[lat_dim]
            lon_size = ds.sizes[lon_dim]
            for lvl in range(pyramid_levels + 1):
                factor = 2 ** lvl
                level_sizes[str(lvl)] = f"{lon_size // factor}x{lat_size // factor}"

            if dry_run:
                elapsed = time.time() - start
                logger.info(
                    "zarr_generate_pyramid: [DRY-RUN] would generate %d levels (%0.1fs)",
                    pyramid_levels, elapsed,
                )
                return {
                    "success": True,
                    "result": {
                        "pyramid_url": f"abfs://{target_container}/{target_prefix}_pyramid.zarr",
                        "levels_generated": pyramid_levels,
                        "resampling": resampling,
                        "level_sizes": level_sizes,
                        "dry_run": True,
                    },
                }

            ds = ds.rio.write_crs("EPSG:4326")

            # Build coarsen factors: [2, 4, 8, ...] for each pyramid level
            factors = [2 ** i for i in range(1, pyramid_levels + 1)]

            logger.info("zarr_generate_pyramid: generating %d levels via coarsen (factors=%s)...", pyramid_levels, factors)
            pyramid = pyramid_coarsen(
                ds,
                dims=[lon_dim, lat_dim],
                factors=factors,
                boundary="trim",
            )

            target_url = f"abfs://{target_container}/{target_prefix}_pyramid.zarr"
            from infrastructure.blob import BlobRepository
            silver_repo = BlobRepository.for_zone("silver")
            target_storage_options = silver_repo.get_xarray_storage_options()

            # Pre-cleanup: delete existing blobs at pyramid prefix to prevent
            # orphan groups when pyramid level count changes between runs
            pyramid_prefix = f"{target_prefix}_pyramid.zarr"
            cleanup = silver_repo.delete_blobs_by_prefix(target_container, pyramid_prefix)
            if cleanup["deleted_count"] > 0:
                logger.info(
                    "zarr_generate_pyramid: pre-cleanup deleted %d existing blobs "
                    "under %s/%s",
                    cleanup["deleted_count"], target_container, pyramid_prefix,
                )

            pyramid.to_zarr(
                target_url,
                zarr_format=zarr_format,
                consolidated=True,
                mode="w",
                storage_options=target_storage_options,
            )

            if zarr_format == 3:
                import zarr
                consolidate_store = zarr.storage.FsspecStore.from_url(
                    target_url, storage_options=target_storage_options,
                )
                zarr.consolidate_metadata(consolidate_store)
                logger.info("zarr_generate_pyramid: consolidated metadata (Zarr v3)")

            elapsed = time.time() - start
            logger.info(
                "zarr_generate_pyramid: completed %d levels to %s (%0.1fs)",
                pyramid_levels, target_url, elapsed,
            )

            return {
                "success": True,
                "result": {
                    "pyramid_url": target_url,
                    "levels_generated": pyramid_levels,
                    "resampling": resampling,
                    "level_sizes": level_sizes,
                },
            }

        finally:
            ds.close()

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_generate_pyramid failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
