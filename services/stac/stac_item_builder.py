# ============================================================================
# CLAUDE CONTEXT - CANONICAL STAC ITEM BUILDER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Service - Pure function STAC item construction
# PURPOSE: Build valid STAC 1.0.0 Item dicts for raster, tiled, and zarr
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: build_stac_item
# DEPENDENCIES: core.models.stac
# ============================================================================
"""
Canonical STAC Item Builder.

One function builds all STAC items — raster (single COG, tiled), zarr.
Pure function: no I/O, no side effects. Dict in, dict out.

The output is cached in cog_metadata.stac_item_json or zarr_metadata.stac_item_json,
then materialized to pgSTAC by STACMaterializer.materialize_to_pgstac().
"""
from typing import Any, Dict, List, Optional

_SENTINEL_DATETIME = "0001-01-01T00:00:00Z"


def build_stac_item(
    item_id: str,
    collection_id: str,
    bbox: List[float],
    asset_href: str,
    asset_type: str,
    asset_roles: Optional[List[str]] = None,
    asset_key: str = "data",
    datetime: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    crs: Optional[str] = None,
    transform: Optional[list] = None,
    raster_bands: Optional[list] = None,
    detected_type: Optional[str] = None,
    band_count: Optional[int] = None,
    data_type: Optional[str] = None,
    dataset_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    version_id: Optional[str] = None,
    iso3_codes: Optional[List[str]] = None,
    primary_iso3: Optional[str] = None,
    country_names: Optional[List[str]] = None,
    zarr_variables: Optional[List[str]] = None,
    zarr_dimensions: Optional[dict] = None,
    title: Optional[str] = None,
    job_id: Optional[str] = None,
    epoch: int = 5,
) -> Dict[str, Any]:
    """Build a canonical STAC 1.0.0 Item dict. Pure function — no I/O."""
    from core.models.stac import (
        STAC_VERSION, APP_PREFIX,
        STAC_EXT_PROJECTION, STAC_EXT_RASTER, STAC_EXT_RENDER, STAC_EXT_PROCESSING,
    )

    if asset_roles is None:
        asset_roles = ["data"]

    if not bbox or len(bbox) < 4:
        raise ValueError(f"bbox must have 4 elements [minx, miny, maxx, maxy], got: {bbox}")

    minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
        ]],
    }

    properties: Dict[str, Any] = {}

    if start_datetime and end_datetime:
        properties["datetime"] = start_datetime
        properties["start_datetime"] = start_datetime
        properties["end_datetime"] = end_datetime
    elif start_datetime:
        properties["datetime"] = start_datetime
        properties["start_datetime"] = start_datetime
    elif datetime:
        properties["datetime"] = datetime
    else:
        properties["datetime"] = _SENTINEL_DATETIME
        properties[f"{APP_PREFIX}:temporal_source"] = "unknown"

    if title:
        properties["title"] = title

    has_projection = False
    if crs:
        if crs.startswith("EPSG:"):
            try:
                properties["proj:epsg"] = int(crs.replace("EPSG:", ""))
                has_projection = True
            except ValueError:
                pass
        else:
            properties["proj:wkt2"] = crs
            has_projection = True
    if transform:
        properties["proj:transform"] = transform
        has_projection = True

    renders = None
    if detected_type and band_count and data_type:
        renders = _compute_renders(
            detected_type=detected_type,
            band_count=band_count,
            data_type=data_type,
            raster_bands=raster_bands,
        )
        if renders:
            properties["renders"] = renders

    properties[f"{APP_PREFIX}:managed_by"] = APP_PREFIX
    properties[f"{APP_PREFIX}:epoch"] = epoch
    properties["processing:lineage"] = f"Processed by {APP_PREFIX} epoch {epoch}"
    if job_id:
        properties[f"{APP_PREFIX}:job_id"] = job_id
    if detected_type:
        properties[f"{APP_PREFIX}:raster_type"] = detected_type

    if dataset_id:
        properties["ddh:dataset_id"] = dataset_id
    if resource_id:
        properties["ddh:resource_id"] = resource_id
    if version_id:
        properties["ddh:version_id"] = version_id

    if iso3_codes:
        properties["geo:iso3"] = iso3_codes
    if primary_iso3:
        properties["geo:primary_iso3"] = primary_iso3
    if country_names:
        properties["geo:countries"] = country_names

    if zarr_variables:
        properties["zarr:variables"] = zarr_variables
    if zarr_dimensions:
        properties["zarr:dimensions"] = zarr_dimensions

    extensions = []
    if has_projection:
        extensions.append(STAC_EXT_PROJECTION)
    if raster_bands:
        extensions.append(STAC_EXT_RASTER)
    if renders:
        extensions.append(STAC_EXT_RENDER)
    extensions.append(STAC_EXT_PROCESSING)

    asset: Dict[str, Any] = {
        "href": asset_href,
        "type": asset_type,
        "roles": asset_roles,
    }
    if raster_bands:
        asset["raster:bands"] = raster_bands

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": extensions,
        "id": item_id,
        "geometry": geometry,
        "bbox": list(bbox),
        "properties": properties,
        "collection": collection_id,
        "links": [],
        "assets": {asset_key: asset},
    }


def _compute_renders(
    detected_type: str, band_count: int, data_type: str, raster_bands: Optional[list],
) -> Optional[Dict[str, Any]]:
    """Delegate to stac_renders.build_renders() with format conversion."""
    from services.stac_renders import build_renders
    band_stats = None
    if raster_bands:
        band_stats = []
        for rb in raster_bands:
            stats = rb.get("statistics", {})
            band_stats.append({
                "statistics": {
                    "minimum": stats.get("min"),
                    "maximum": stats.get("max"),
                    "mean": stats.get("mean"),
                    "stddev": stats.get("stddev"),
                }
            })
    return build_renders(raster_type=detected_type, band_count=band_count, dtype=data_type, band_stats=band_stats)
