# ============================================================================
# H3 SPATIAL INDEXING CONFIGURATION
# ============================================================================
# STATUS: Configuration - H3 hexagonal grid system settings
# PURPOSE: Configure H3 grid generation, spatial filtering, and PostGIS storage
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no Azure resources)
# ============================================================================
"""
H3 spatial indexing configuration.

This module configures the H3 geospatial indexing system for global hierarchical gridding.

H3 Overview:
------------
H3 is Uber's Hexagonal Hierarchical Spatial Index - a discrete global grid system.
- Resolutions 0-15 (0 = coarsest, 15 = finest)
- Resolution 2 cells ≈ 86,000 km² (continental scale)
- Resolution 10 cells ≈ 15,000 m² (neighborhood scale)
- Uniform hexagonal tessellation (better than squares for spatial analysis)

ROADMAP (Under Development):
-----------------------------
This configuration module is being designed for future H3 functionality across
the full data lifecycle:

**Phase 1 - Current (PostGIS-based H3 grids):**
1. H3 cell generation with spatial filtering (land-only grids)
2. System reference tables (admin0 boundaries for spatial filters)
3. H3 pyramid generation (multi-resolution hierarchies)
4. PostGIS storage in geo.h3_* tables

**Phase 2 - Future (Analytics Integration):**
5. H3 grid export to GeoParquet (columnar analytics)
6. H3-indexed raster aggregation (zonal statistics per cell)
7. H3 time-series analysis (spatiotemporal data cubes)
8. DuckDB spatial joins (H3 GeoParquet ⟕ vector data)

**Phase 3 - Advanced Features:**
9. H3 data lake integration (partition by resolution + region)
10. H3 tessellation for ML training data (consistent spatial sampling)
11. Multi-resolution pyramids in Parquet (efficient zoom levels)
12. H3 cell attribute caching (precomputed statistics)

Logical Grouping:
-----------------
H3 configuration bridges multiple domains:
- **Database** (PostGIS): H3 cells stored as geometry + metadata tables
- **Analytics** (GeoParquet): H3 grids exported for columnar analytics
- **Raster** (COGs): H3 cells as aggregation units for zonal statistics
- **Vector** (Features): H3 as spatial join index for point-in-polygon

This separation allows H3 to evolve independently while integrating with
database, analytics, and ETL pipelines.

Example Future Workflow:
------------------------
```python
# Generate H3 grid in PostGIS (current)
job = submit_job("bootstrap_h3_land_grid_pyramid", {
    "resolution": 4,
    "spatial_filter": "curated_admin0"  # config.h3.spatial_filter_table
})

# Export to GeoParquet for analytics (future - Phase 2)
job = submit_job("export_h3_to_parquet", {
    "resolution": 4,
    "output_container": config.analytics.gold_tier_container,
    "partition_by": ["resolution", "continent"]
})

# Aggregate raster data to H3 cells (future - Phase 2)
job = submit_job("raster_to_h3_aggregation", {
    "source_collection": "landsat-8",
    "h3_resolution": 10,
    "statistic": "mean",
    "output_format": "parquet"  # H3 cell ID + statistics
})
```
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import parse_bool


class H3Config(BaseModel):
    """
    H3 spatial indexing system configuration.

    H3 (Hexagonal Hierarchical Spatial Index) is used for:
    - Global spatial gridding at multiple resolutions (0-15)
    - Land-filtered grid generation (skip ocean cells)
    - Multi-resolution spatial pyramids
    - Spatial aggregation and zonal statistics
    - Future: GeoParquet exports for columnar analytics

    Configuration Fields:
    ---------------------
    system_admin0_table: PostGIS table with admin0 (country) boundaries
        - Used for spatial filtering during H3 grid generation
        - Full qualified name: schema.table
        - Default: "geo.curated_admin0" (curated dataset prefix)

    spatial_filter_table: Short reference key for H3 spatial filters
        - Used in job parameters to select which filter to apply
        - No schema prefix (just the table suffix)
        - Default: "curated_admin0"
        - Allows flexible filter selection: "curated_admin0", "curated_continents", etc.

    default_resolution: Default H3 resolution for grid generation
        - Range: 0 (coarsest) to 15 (finest)
        - Default: 4 (good balance for global land grids)
        - Resolution 4 cells ≈ 1,770 km² (state/province scale)

    enable_land_filter: Enable spatial filtering to generate land-only grids
        - True: Only generate H3 cells over land masses (saves ~70% compute/storage)
        - False: Generate all H3 cells (including oceans)
        - Default: True

    Example Usage:
    -------------
    ```python
    from config import get_config

    config = get_config()

    # Access H3 settings
    print(f"Admin0 table: {config.h3.system_admin0_table}")
    print(f"Spatial filter: {config.h3.spatial_filter_table}")

    # Submit H3 bootstrap job
    job_params = {
        "resolution": config.h3.default_resolution,
        "spatial_filter": config.h3.spatial_filter_table,
        "enable_land_filter": config.h3.enable_land_filter
    }
    ```

    Future Enhancements (Phase 2 - Analytics):
    ------------------------------------------
    - export_to_parquet: Enable GeoParquet export of H3 grids
    - parquet_partition_by: Partition strategy (resolution, continent, both)
    - parquet_compression: Compression codec for GeoParquet (snappy, zstd)
    - cache_cell_statistics: Precompute statistics per H3 cell
    - pyramid_levels: Which resolutions to include in multi-res pyramids
    """

    # System reference tables (PostGIS)
    system_admin0_table: str = Field(
        default="geo.curated_admin0",
        description=(
            "PostGIS table containing admin0 (country) boundaries. "
            "Full qualified name (schema.table). "
            "Used for spatial filtering during H3 grid generation. "
            "Renamed from system_admin0 to curated_admin0 (15 DEC 2025)."
        )
    )

    spatial_filter_table: str = Field(
        default="curated_admin0",
        description=(
            "Short reference key for H3 spatial filters (no schema prefix). "
            "Used in job parameters to select which filter to apply. "
            "Allows flexible filter selection without hardcoding full table paths. "
            "Curated datasets use curated_ prefix for protection."
        )
    )

    # H3 grid generation settings
    default_resolution: int = Field(
        default=4,
        ge=0,
        le=15,
        description=(
            "Default H3 resolution for grid generation (0-15). "
            "Resolution 4 ≈ 1,770 km² per cell (state/province scale). "
            "Lower = coarser, Higher = finer."
        )
    )

    enable_land_filter: bool = Field(
        default=True,
        description=(
            "Enable spatial filtering to generate land-only grids. "
            "True = Only generate H3 cells over land (saves ~70% compute/storage). "
            "False = Generate all H3 cells including oceans."
        )
    )

    @classmethod
    def from_environment(cls) -> "H3Config":
        """
        Load H3 configuration from environment variables.

        Environment Variables:
        ---------------------
        H3_SYSTEM_ADMIN0_TABLE: PostGIS admin0 table (default: "geo.curated_admin0")
        H3_SPATIAL_FILTER_TABLE: Spatial filter key (default: "curated_admin0")
        H3_DEFAULT_RESOLUTION: Default H3 resolution (default: 4)
        H3_ENABLE_LAND_FILTER: Enable land filtering (default: "true")

        Returns:
            H3Config: Configured H3 settings
        """
        return cls(
            system_admin0_table=os.environ.get(
                "H3_SYSTEM_ADMIN0_TABLE",
                "geo.curated_admin0"  # Renamed from system_admin0 (15 DEC 2025)
            ),
            spatial_filter_table=os.environ.get(
                "H3_SPATIAL_FILTER_TABLE",
                "curated_admin0"  # Curated datasets use curated_ prefix
            ),
            default_resolution=int(os.environ.get("H3_DEFAULT_RESOLUTION", "4")),
            enable_land_filter=parse_bool(
                os.environ.get("H3_ENABLE_LAND_FILTER", "true")
            )
        )

    def debug_dict(self) -> dict:
        """
        Return debug-friendly configuration dictionary.

        Returns:
            dict: Configuration with all fields visible
        """
        return {
            "system_admin0_table": self.system_admin0_table,
            "spatial_filter_table": self.spatial_filter_table,
            "default_resolution": self.default_resolution,
            "enable_land_filter": self.enable_land_filter
        }


# Export
__all__ = ["H3Config"]
