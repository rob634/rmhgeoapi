# ============================================================================
# CLAUDE CONTEXT - STAC COLLECTION BUILDER
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - Canonical STAC collection factory
# PURPOSE: Pure function that builds all STAC collections — no I/O, no side effects
# LAST_REVIEWED: 25 MAR 2026
# EXPORTS: build_stac_collection
# DEPENDENCIES: core.models.stac
# ============================================================================
"""
Canonical STAC Collection Builder.

One function builds all STAC collections. Pure function: no I/O, no side effects.
Replaces build_raster_stac_collection() and pystac.Collection usage.
"""
from typing import Any, Dict, List, Optional

from core.models.stac import STAC_VERSION


def build_stac_collection(
    collection_id: str,
    bbox: Optional[List[float]] = None,
    temporal_start: Optional[str] = None,
    temporal_end: Optional[str] = None,
    description: Optional[str] = None,
    license: str = "proprietary",
    iso3_codes: Optional[List[str]] = None,
    primary_iso3: Optional[str] = None,
    country_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a canonical STAC 1.0.0 Collection dict. Pure function — no I/O."""
    if bbox is None:
        bbox = [-180, -90, 180, 90]

    collection: Dict[str, Any] = {
        "type": "Collection",
        "id": collection_id,
        "stac_version": STAC_VERSION,
        "description": description or f"Collection: {collection_id}",
        "links": [],
        "license": license,
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[temporal_start, temporal_end]]},
        },
        "stac_extensions": [],
    }

    if iso3_codes:
        collection["geo:iso3"] = iso3_codes
    if primary_iso3:
        collection["geo:primary_iso3"] = primary_iso3
    if country_names:
        collection["geo:countries"] = country_names

    return collection
