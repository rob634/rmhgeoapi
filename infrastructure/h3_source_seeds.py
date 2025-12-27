# ============================================================================
# CLAUDE CONTEXT - H3 SOURCE CATALOG SEED DATA
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Seed Data for Source Catalog
# PURPOSE: Pre-defined source entries for common data sources
# LAST_REVIEWED: 27 DEC 2025
# EXPORTS: seed_planetary_computer_sources, COP_DEM_GLO_30
# DEPENDENCIES: infrastructure.h3_source_repository
# ============================================================================
"""
H3 Source Catalog Seed Data.

Pre-defined source entries for common data sources used in H3 aggregation.
Call seed_planetary_computer_sources() after schema deployment to register
standard Planetary Computer sources.

Usage:
    from infrastructure.h3_source_seeds import seed_planetary_computer_sources

    result = seed_planetary_computer_sources()
    print(f"Seeded {result['sources_registered']} sources")
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# ============================================================================
# COPERNICUS DEM GLO-30
# ============================================================================

COP_DEM_GLO_30 = {
    "id": "cop-dem-glo-30",
    "display_name": "Copernicus DEM GLO-30",
    "description": "Copernicus DEM (Digital Elevation Model) at 30m resolution. "
                   "Global coverage derived from WorldDEM, TanDEM-X, and ASTER data. "
                   "Covers latitudes from 90°N to 90°S.",

    # Source Connection
    "source_type": "planetary_computer",
    "stac_api_url": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "collection_id": "cop-dem-glo-30",
    "asset_key": "data",

    # Tile/Item Pattern
    "item_id_pattern": r"Copernicus_DSM_COG_\d+_[NS]\d+_\d+_[EW]\d+_\d+_DEM",
    "tile_size_degrees": 1.0,
    "tile_count": 26000,  # Approximate
    "tile_naming_convention": "lat_lon_grid",

    # Raster Properties
    "native_resolution_m": 30,
    "crs": "EPSG:4326",
    "data_type": "float32",
    "nodata_value": -32767.0,
    "value_range": {"min": -500, "max": 9000},
    "band_count": 1,
    "band_info": [{"band": 1, "name": "elevation", "unit": "meters", "description": "Elevation above sea level"}],

    # Aggregation Configuration
    "theme": "terrain",
    "recommended_stats": ["mean", "min", "max", "std"],
    "recommended_h3_res_min": 4,
    "recommended_h3_res_max": 8,
    "aggregation_method": "zonal_stats",
    "unit": "meters",

    # Coverage
    "coverage_type": "global",
    "land_only": True,

    # Temporal
    "is_temporal_series": False,
    "update_frequency": "static",

    # Performance Hints
    "avg_tile_size_mb": 50,
    "recommended_batch_size": 500,
    "requires_auth": True,

    # Provenance
    "source_provider": "European Space Agency / Copernicus",
    "source_url": "https://planetarycomputer.microsoft.com/dataset/cop-dem-glo-30",
    "source_license": "CC-BY-4.0",
    "citation": "Copernicus DEM - GLO-30. European Space Agency, Airbus. "
               "Available via Microsoft Planetary Computer."
}


# ============================================================================
# NASA DEM (NASADEM)
# ============================================================================

NASADEM = {
    "id": "nasadem",
    "display_name": "NASADEM Global DEM",
    "description": "NASA DEM derived from SRTM data with improved processing. "
                   "30m resolution, covers latitudes from 60°N to 56°S.",

    "source_type": "planetary_computer",
    "stac_api_url": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "collection_id": "nasadem",
    "asset_key": "elevation",

    "tile_size_degrees": 1.0,
    "tile_count": 14000,  # Approximate

    "native_resolution_m": 30,
    "crs": "EPSG:4326",
    "data_type": "int16",
    "nodata_value": -32768,
    "value_range": {"min": -500, "max": 9000},
    "band_count": 1,
    "band_info": [{"band": 1, "name": "elevation", "unit": "meters"}],

    "theme": "terrain",
    "recommended_stats": ["mean", "min", "max"],
    "recommended_h3_res_min": 4,
    "recommended_h3_res_max": 8,
    "aggregation_method": "zonal_stats",
    "unit": "meters",

    "coverage_type": "global",
    "land_only": True,
    "is_temporal_series": False,
    "update_frequency": "static",

    "avg_tile_size_mb": 25,
    "recommended_batch_size": 500,
    "requires_auth": True,

    "source_provider": "NASA",
    "source_url": "https://planetarycomputer.microsoft.com/dataset/nasadem",
    "source_license": "Public Domain",
}


# ============================================================================
# ESA WorldCover (Land Cover)
# ============================================================================

ESA_WORLDCOVER_2021 = {
    "id": "esa-worldcover-2021",
    "display_name": "ESA WorldCover 2021",
    "description": "ESA WorldCover 10m land cover map based on Sentinel-1 and Sentinel-2 data. "
                   "11 land cover classes.",

    "source_type": "planetary_computer",
    "stac_api_url": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "collection_id": "esa-worldcover",
    "asset_key": "map",

    "tile_size_degrees": 3.0,
    "tile_count": 2500,

    "native_resolution_m": 10,
    "crs": "EPSG:4326",
    "data_type": "uint8",
    "nodata_value": 0,
    "value_range": {"min": 10, "max": 95},
    "band_count": 1,
    "band_info": [{"band": 1, "name": "land_cover", "unit": "class", "description": "Land cover classification"}],

    "theme": "landcover",
    "recommended_stats": ["count"],  # Mode/majority is better for categorical
    "recommended_h3_res_min": 5,
    "recommended_h3_res_max": 9,
    "aggregation_method": "zonal_stats",
    "unit": "class",

    "coverage_type": "global",
    "land_only": True,
    "is_temporal_series": False,
    "update_frequency": "yearly",

    "avg_tile_size_mb": 100,
    "recommended_batch_size": 300,
    "requires_auth": True,

    "source_provider": "European Space Agency",
    "source_url": "https://planetarycomputer.microsoft.com/dataset/esa-worldcover",
    "source_license": "CC-BY-4.0",
}


# ============================================================================
# SEED FUNCTIONS
# ============================================================================

def seed_planetary_computer_sources() -> Dict[str, Any]:
    """
    Register all Planetary Computer source seeds.

    Returns:
        Dict with registration results
    """
    from infrastructure.h3_source_repository import H3SourceRepository

    repo = H3SourceRepository()

    sources = [
        COP_DEM_GLO_30,
        NASADEM,
        ESA_WORLDCOVER_2021,
    ]

    results = {
        "sources_registered": 0,
        "sources_updated": 0,
        "sources": [],
        "errors": []
    }

    for source in sources:
        try:
            result = repo.register_source(source)
            if result.get('created'):
                results["sources_registered"] += 1
            else:
                results["sources_updated"] += 1
            results["sources"].append({
                "id": source["id"],
                "theme": source["theme"],
                "created": result.get('created', False)
            })
            logger.info(f"✅ Registered source: {source['id']}")
        except Exception as e:
            results["errors"].append({
                "id": source["id"],
                "error": str(e)
            })
            logger.error(f"❌ Failed to register {source['id']}: {e}")

    logger.info(f"📊 Seeded {results['sources_registered']} new sources, "
                f"updated {results['sources_updated']} existing sources")

    return results


def seed_cop_dem_glo_30() -> Dict[str, Any]:
    """
    Register just the Copernicus DEM GLO-30 source.

    Convenience function for the most common use case.

    Returns:
        Dict with registration result
    """
    from infrastructure.h3_source_repository import H3SourceRepository

    repo = H3SourceRepository()
    result = repo.register_source(COP_DEM_GLO_30)

    logger.info(f"✅ Registered cop-dem-glo-30 (created={result.get('created')})")
    return result


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'COP_DEM_GLO_30',
    'NASADEM',
    'ESA_WORLDCOVER_2021',
    'seed_planetary_computer_sources',
    'seed_cop_dem_glo_30',
]
