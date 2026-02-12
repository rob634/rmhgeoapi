# ============================================================================
# RASTER RENDER CONFIG MODEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Render configuration for raster visualization
# PURPOSE: Pydantic model for app.raster_render_configs table (IaC DDL)
# LAST_REVIEWED: 12 FEB 2026
# EXPORTS: RasterRenderConfig
# DEPENDENCIES: pydantic
# ============================================================================
"""
Raster Render Configuration Model.

Server-side render configurations for raster visualization via TiTiler.
Follows the same "PostgreSQL as Source of Truth" pattern established for
OGC Styles (vector symbology).

Architecture:
    PostgreSQL (Source of Truth)
    └── app.raster_render_configs
        • cog_id (FK → cog_metadata)
        • render_id (e.g., "default", "flood-depth", "ndvi")
        • render_spec (TiTiler parameters as JSONB)
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    Render API  STAC Renders  TiTiler
    (CRUD)      Extension     Query Params

Key Differences from Vector Styles:
    - Vector: Client-side styling (CartoSym-JSON) → geo schema (replicable)
    - Raster: Server-side rendering (TiTiler params) → app schema (internal)

Table: app.raster_render_configs
Primary Key: id (SERIAL)
Unique: (cog_id, render_id)
Foreign Key: cog_id → app.cog_metadata(cog_id)

Usage:
    from core.models.raster_render_config import RasterRenderConfig

    config = RasterRenderConfig(
        cog_id="fathom-fluvial-defended-2020",
        render_id="flood-depth",
        title="Flood Depth Visualization",
        render_spec={
            "colormap_name": "blues",
            "rescale": [[0, 5]],
            "nodata": -9999
        },
        is_default=True
    )

    # Convert to STAC renders extension format
    stac_render = config.to_stac_render()

    # Convert to TiTiler query params
    titiler_params = config.to_titiler_params()

Created: 22 JAN 2026
Epic: E2 Raster Data as API → F2.11 Raster Render Configuration System
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict


class RasterRenderConfig(BaseModel):
    """
    Render configuration for raster visualization via TiTiler.

    Maps to: app.raster_render_configs

    Following the same IaC pattern as:
    - GeoTableCatalog (geo.table_catalog)
    - FeatureCollectionStyles (geo.feature_collection_styles)
    - VectorEtlTracking (app.vector_etl_tracking)

    Render Spec Fields (TiTiler Parameters):
        colormap_name: Named colormap (viridis, plasma, blues, etc.)
        colormap: Custom colormap dict {value: color}
        rescale: Min/max rescaling per band [[min, max], ...]
        bidx: Band indexes to use [1, 2, 3]
        expression: Band math expression "(b1-b2)/(b1+b2)"
        color_formula: rio-color formula "gamma r 1.5"
        resampling: Resampling method (nearest, bilinear, etc.)
        return_mask: Include alpha mask in response
        nodata: NoData value override
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "raster_render_configs"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["id"]
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["cog_id", "render_id"], "name": "uq_render_cog_render"}
    ]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "cog_id": "app.cog_metadata(cog_id)"
    }
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["cog_id"], "name": "idx_render_cog"},
        # Partial unique index: only one default per COG
        {"columns": ["cog_id"], "name": "idx_render_default",
         "partial_where": "is_default = true", "unique": True},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    id: Optional[int] = Field(
        default=None,
        description="Auto-generated primary key (SERIAL)"
    )

    cog_id: str = Field(
        ...,
        max_length=255,
        description="COG identifier (FK to cog_metadata)"
    )

    render_id: str = Field(
        ...,
        max_length=100,
        description="URL-safe render identifier (e.g., 'default', 'flood-depth')"
    )

    # =========================================================================
    # METADATA
    # =========================================================================
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Human-readable render title"
    )

    description: Optional[str] = Field(
        default=None,
        description="Render description"
    )

    # =========================================================================
    # RENDER SPECIFICATION (TiTiler Parameters)
    # =========================================================================
    render_spec: Dict[str, Any] = Field(
        ...,
        description="TiTiler render parameters (colormap, rescale, bidx, etc.)"
    )

    # =========================================================================
    # FLAGS
    # =========================================================================
    is_default: bool = Field(
        default=False,
        description="Whether this is the default render for the COG"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the render config was created"
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        description="When the render config was last updated"
    )

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "RasterRenderConfig":
        """
        Create RasterRenderConfig from database row.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            RasterRenderConfig instance
        """
        return cls(
            id=row.get('id'),
            cog_id=row.get('cog_id'),
            render_id=row.get('render_id'),
            title=row.get('title'),
            description=row.get('description'),
            render_spec=row.get('render_spec') or {},
            is_default=row.get('is_default', False),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    @classmethod
    def create_default_for_cog(
        cls,
        cog_id: str,
        dtype: str = "float32",
        band_count: int = 1,
        nodata: Optional[float] = None,
        data_min: Optional[float] = None,
        data_max: Optional[float] = None,
        detected_type: Optional[str] = None,
        default_ramp: Optional[str] = None,
    ) -> "RasterRenderConfig":
        """
        Generate sensible default render config based on raster properties.

        Uses detected_type (from raster validation) for smart colormap selection,
        consolidating logic previously duplicated in RasterVisualizationMetadata.

        Colormap priority: default_ramp (user override) > type-based default.

        Args:
            cog_id: COG identifier
            dtype: Numpy dtype (uint8, uint16, float32, etc.)
            band_count: Number of bands
            nodata: NoData value
            data_min: Actual data minimum (if known)
            data_max: Actual data maximum (if known)
            detected_type: Raster type from validation (dem, flood_depth, rgb, etc.)
            default_ramp: User-specified colormap override (ColorRamp enum value)

        Returns:
            RasterRenderConfig with sensible defaults
        """
        render_spec: Dict[str, Any] = {}

        # Set rescale based on dtype or actual data range
        if data_min is not None and data_max is not None:
            render_spec["rescale"] = [[data_min, data_max]]
        elif dtype == "uint8":
            render_spec["rescale"] = [[0, 255]]
        elif dtype == "uint16":
            render_spec["rescale"] = [[0, 65535]]
        elif dtype in ("int16",):
            render_spec["rescale"] = [[-32768, 32767]]
        elif dtype in ("float32", "float64"):
            render_spec["rescale"] = [[0, 1]]  # Assume normalized

        # Colormap selection: user override > type-based default
        # 12 FEB 2026: Expanded with domain types + default_ramp override
        if band_count >= 3:
            # RGB/RGBA/multispectral - select first 3 bands, no colormap
            render_spec["bidx"] = [1, 2, 3]
        elif default_ramp:
            # User explicitly chose a colormap — honor it
            render_spec["colormap_name"] = default_ramp
        elif detected_type == 'dem':
            render_spec["colormap_name"] = "terrain"
        elif detected_type in ('vegetation_index',):
            render_spec["colormap_name"] = "rdylgn"
        elif detected_type in ('flood_depth', 'flood_probability'):
            render_spec["colormap_name"] = "blues"
        elif detected_type == 'hydrology':
            render_spec["colormap_name"] = "ylgnbu"
        elif detected_type == 'temporal':
            render_spec["colormap_name"] = "spectral"
        elif detected_type == 'population':
            render_spec["colormap_name"] = "inferno"
        elif detected_type == 'categorical':
            render_spec["colormap_name"] = "viridis"
        elif band_count == 1:
            render_spec["colormap_name"] = "viridis"
        else:
            # 2 bands - just use first band with colormap
            render_spec["bidx"] = [1]
            render_spec["colormap_name"] = "viridis"

        if nodata is not None:
            render_spec["nodata"] = nodata

        return cls(
            cog_id=cog_id,
            render_id="default",
            title="Default Visualization",
            description="Auto-generated default render configuration",
            render_spec=render_spec,
            is_default=True
        )

    # =========================================================================
    # CONVERSION METHODS
    # =========================================================================

    def to_stac_render(self) -> Dict[str, Any]:
        """
        Convert to STAC Renders Extension format.

        The STAC Renders Extension embeds render configurations in the
        asset object, allowing clients to request specific visualizations.

        Returns:
            Dict suitable for embedding in asset.renders[render_id]

        Example output:
            {
                "title": "Flood Depth",
                "colormap_name": "blues",
                "rescale": [[0, 5]]
            }
        """
        render: Dict[str, Any] = {}

        if self.title:
            render["title"] = self.title
        if self.description:
            render["description"] = self.description

        # Map render_spec fields to STAC render format
        spec = self.render_spec or {}
        stac_fields = [
            "colormap_name", "colormap", "rescale", "bidx",
            "expression", "color_formula", "resampling",
            "return_mask", "nodata"
        ]
        for key in stac_fields:
            if key in spec and spec[key] is not None:
                render[key] = spec[key]

        return render

    def to_titiler_params(self) -> Dict[str, Any]:
        """
        Convert to TiTiler query parameters.

        Transforms the render_spec into query parameters that can be
        passed directly to TiTiler tile endpoints.

        Returns:
            Dict of query params for TiTiler tile requests

        Example output:
            {
                "colormap_name": "viridis",
                "rescale": "0,100",
                "bidx": "1"
            }
        """
        params: Dict[str, Any] = {}
        spec = self.render_spec or {}

        if "colormap_name" in spec:
            params["colormap_name"] = spec["colormap_name"]

        if "colormap" in spec:
            # Custom colormap as JSON
            import json
            params["colormap"] = json.dumps(spec["colormap"])

        if "rescale" in spec:
            # TiTiler expects comma-separated: rescale=0,100
            # Multiple bands: rescale=0,100&rescale=0,255
            rescale_list = spec["rescale"]
            if rescale_list:
                # For single rescale, just use first
                params["rescale"] = ",".join(map(str, rescale_list[0]))

        if "bidx" in spec:
            # Band indexes as comma-separated
            params["bidx"] = ",".join(map(str, spec["bidx"]))

        if "expression" in spec:
            params["expression"] = spec["expression"]

        if "color_formula" in spec:
            params["color_formula"] = spec["color_formula"]

        if "resampling" in spec:
            params["resampling"] = spec["resampling"]

        if "nodata" in spec:
            params["nodata"] = spec["nodata"]

        if "return_mask" in spec:
            params["return_mask"] = str(spec["return_mask"]).lower()

        return params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses.

        Returns:
            Dict representation of the render config
        """
        return {
            "id": self.id,
            "cog_id": self.cog_id,
            "render_id": self.render_id,
            "title": self.title,
            "description": self.description,
            "render_spec": self.render_spec,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
