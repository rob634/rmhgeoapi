# ============================================================================
# CLAUDE CONTEXT - STAC PREVIEW ITEM BUILDER
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - Minimal STAC item skeleton for tiled TiTiler preview
# PURPOSE: Build skeleton preview items inserted into pgSTAC at processing time
# LAST_REVIEWED: 25 MAR 2026
# EXPORTS: build_preview_item
# DEPENDENCIES: core.models.stac
# ============================================================================
"""
STAC Preview Item Builder.

Builds minimal skeleton items for TiTiler tiled mosaic preview.
These are inserted into pgSTAC at processing time (before approval)
so TiTiler can render the mosaic immediately.

Full items replace these at approval time via materialize_to_pgstac().
"""
from typing import Any, Dict, List

from core.models.stac import STAC_VERSION

_SENTINEL_DATETIME = "0001-01-01T00:00:00Z"
_COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"


def build_preview_item(
    item_id: str,
    collection_id: str,
    bbox: List[float],
    asset_href: str,
    asset_type: str = _COG_MEDIA_TYPE,
) -> Dict[str, Any]:
    """Build a minimal STAC item for TiTiler tiled preview."""
    minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]
    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": [],
        "id": item_id,
        "collection": collection_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
            ]],
        },
        "bbox": list(bbox),
        "properties": {"datetime": _SENTINEL_DATETIME},
        "assets": {
            "data": {"href": asset_href, "type": asset_type, "roles": ["data"]},
        },
        "links": [],
    }
