# ============================================================================
# RASTER RENDER CONFIG SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Business logic - Raster render configuration orchestration
# PURPOSE: Coordinate render config lookup, validation, and response formatting
# LAST_REVIEWED: 22 JAN 2026
# EXPORTS: RasterRenderService, get_raster_render_service
# DEPENDENCIES: infrastructure.raster_render_repository
# ============================================================================
"""
Raster Render Config Service Layer.

Business logic for TiTiler render configurations:
- List render configs for a COG
- Get render config (with TiTiler param conversion)
- Create/update render configs
- Format API responses

Usage:
    service = get_raster_render_service()

    # List renders
    renders_list = service.list_renders("fathom-flood-2020", base_url)

    # Get render with TiTiler params
    render_data = service.get_render("fathom-flood-2020", "default")

    # Create render
    service.create_render("fathom-flood-2020", "flood-depth", {
        "colormap_name": "blues",
        "rescale": [[0, 5]]
    })

Created: 22 JAN 2026
Epic: E2 Raster Data as API → F2.11 Raster Render Configuration System
"""

import logging
from typing import Any, Dict, List, Optional

from core.models.raster_render_config import RasterRenderConfig
from infrastructure.raster_render_repository import (
    RasterRenderRepository,
    get_raster_render_repository
)

logger = logging.getLogger(__name__)


# Module-level singleton
_service_instance: Optional["RasterRenderService"] = None


def get_raster_render_service() -> "RasterRenderService":
    """
    Get singleton RasterRenderService instance.

    Returns:
        RasterRenderService singleton
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = RasterRenderService()
    return _service_instance


class RasterRenderService:
    """
    Raster render configuration business logic.

    Orchestrates render config retrieval, validation, and API response formatting.
    Coordinates between repository (data access) and HTTP handlers.
    """

    def __init__(self, repository: Optional[RasterRenderRepository] = None):
        """
        Initialize service with optional repository.

        Args:
            repository: Render repository (uses singleton if not provided)
        """
        self.repository = repository or get_raster_render_repository()
        logger.debug("RasterRenderService initialized")

    # =========================================================================
    # LIST OPERATIONS
    # =========================================================================

    def list_renders(self, cog_id: str, base_url: str) -> Dict[str, Any]:
        """
        List available render configs for a COG.

        Returns API response with render configs and links.

        Args:
            cog_id: COG identifier
            base_url: Base URL for link generation

        Returns:
            API response dict with renders and links
        """
        renders = self.repository.list_renders(cog_id)

        renders_url = f"{base_url}/api/raster/{cog_id}/renders"

        response = {
            "cog_id": cog_id,
            "renders": [r.to_dict() for r in renders],
            "count": len(renders),
            "links": [
                {
                    "rel": "self",
                    "href": renders_url,
                    "type": "application/json"
                }
            ]
        }

        # Add link to STAC item if we know the collection
        # (would need to look up cog_metadata for collection_id)

        return response

    def list_renders_for_stac(self, cog_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get renders formatted for STAC asset.renders embedding.

        Args:
            cog_id: COG identifier

        Returns:
            Dict of render_id → STAC render format

        Example:
            {
                "default": {"title": "...", "colormap_name": "viridis"},
                "flood-depth": {"title": "...", "colormap_name": "blues"}
            }
        """
        return self.repository.get_renders_for_stac(cog_id)

    # =========================================================================
    # GET OPERATIONS
    # =========================================================================

    def get_render(
        self,
        cog_id: str,
        render_id: str,
        include_titiler_params: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific render config.

        Args:
            cog_id: COG identifier
            render_id: Render identifier
            include_titiler_params: If True, include pre-formatted TiTiler params

        Returns:
            Render config dict or None if not found
        """
        render = self.repository.get_render(cog_id, render_id)
        if not render:
            return None

        response = render.to_dict()

        if include_titiler_params:
            response["titiler_params"] = render.to_titiler_params()
            response["stac_render"] = render.to_stac_render()

        return response

    def get_default_render(
        self,
        cog_id: str,
        include_titiler_params: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Get the default render config for a COG.

        Args:
            cog_id: COG identifier
            include_titiler_params: If True, include pre-formatted TiTiler params

        Returns:
            Default render config dict or None if not set
        """
        render = self.repository.get_default_render(cog_id)
        if not render:
            return None

        response = render.to_dict()

        if include_titiler_params:
            response["titiler_params"] = render.to_titiler_params()
            response["stac_render"] = render.to_stac_render()

        return response

    def get_titiler_params(self, cog_id: str, render_id: str) -> Optional[Dict[str, Any]]:
        """
        Get TiTiler query parameters for a render config.

        Convenience method for TiTiler integration.

        Args:
            cog_id: COG identifier
            render_id: Render identifier

        Returns:
            Dict of TiTiler query params or None if not found
        """
        render = self.repository.get_render(cog_id, render_id)
        if not render:
            return None
        return render.to_titiler_params()

    # =========================================================================
    # CREATE/UPDATE OPERATIONS
    # =========================================================================

    def create_render(
        self,
        cog_id: str,
        render_id: str,
        render_spec: Dict[str, Any],
        title: Optional[str] = None,
        description: Optional[str] = None,
        is_default: bool = False
    ) -> Dict[str, Any]:
        """
        Create or update a render config.

        Args:
            cog_id: COG identifier
            render_id: Render identifier (URL-safe)
            render_spec: TiTiler render parameters
            title: Human-readable title
            description: Render description
            is_default: Whether this is the default render

        Returns:
            Created/updated render config dict

        Raises:
            ValueError: If render_spec is invalid
        """
        # Validate render_spec has at least some content
        if not render_spec:
            raise ValueError("render_spec cannot be empty")

        # Validate known fields
        valid_fields = {
            "colormap_name", "colormap", "rescale", "bidx",
            "expression", "color_formula", "resampling",
            "return_mask", "nodata"
        }
        unknown_fields = set(render_spec.keys()) - valid_fields
        if unknown_fields:
            logger.warning(f"Unknown render_spec fields: {unknown_fields}")

        # Create via repository
        self.repository.create_render(
            cog_id=cog_id,
            render_id=render_id,
            render_spec=render_spec,
            title=title,
            description=description,
            is_default=is_default
        )

        # Return the created config
        return self.get_render(cog_id, render_id, include_titiler_params=True)

    def create_default_for_cog(
        self,
        cog_id: str,
        dtype: str = "float32",
        band_count: int = 1,
        nodata: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Auto-generate and save a default render config based on raster properties.

        Args:
            cog_id: COG identifier
            dtype: Numpy dtype (uint8, uint16, float32, etc.)
            band_count: Number of bands
            nodata: NoData value

        Returns:
            Created render config dict
        """
        self.repository.create_default_render_for_cog(
            cog_id=cog_id,
            dtype=dtype,
            band_count=band_count,
            nodata=nodata
        )

        return self.get_render(cog_id, "default", include_titiler_params=True)

    def set_default(self, cog_id: str, render_id: str) -> bool:
        """
        Set a render config as the default for its COG.

        Args:
            cog_id: COG identifier
            render_id: Render identifier to set as default

        Returns:
            True if updated, False if render not found
        """
        return self.repository.set_default(cog_id, render_id)

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    def delete_render(self, cog_id: str, render_id: str) -> bool:
        """
        Delete a render config.

        Args:
            cog_id: COG identifier
            render_id: Render identifier

        Returns:
            True if deleted, False if not found
        """
        return self.repository.delete_render(cog_id, render_id)

    def delete_all_renders(self, cog_id: str) -> int:
        """
        Delete all render configs for a COG.

        Used when unpublishing/deleting a COG.

        Args:
            cog_id: COG identifier

        Returns:
            Number of renders deleted
        """
        return self.repository.delete_all_renders(cog_id)

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate_render_spec(self, render_spec: Dict[str, Any]) -> List[str]:
        """
        Validate a render_spec and return any warnings/errors.

        Args:
            render_spec: TiTiler render parameters

        Returns:
            List of validation messages (empty if valid)
        """
        messages = []

        if not render_spec:
            messages.append("render_spec is empty")
            return messages

        # Check for mutually exclusive fields
        if "colormap_name" in render_spec and "colormap" in render_spec:
            messages.append("colormap_name and colormap are mutually exclusive")

        # Validate rescale format
        if "rescale" in render_spec:
            rescale = render_spec["rescale"]
            if not isinstance(rescale, list):
                messages.append("rescale must be a list of [min, max] pairs")
            else:
                for i, r in enumerate(rescale):
                    if not isinstance(r, list) or len(r) != 2:
                        messages.append(f"rescale[{i}] must be [min, max]")

        # Validate bidx
        if "bidx" in render_spec:
            bidx = render_spec["bidx"]
            if not isinstance(bidx, list) or not all(isinstance(b, int) for b in bidx):
                messages.append("bidx must be a list of integers")

        # Validate colormap_name
        known_colormaps = {
            "viridis", "plasma", "inferno", "magma", "cividis",
            "greys", "purples", "blues", "greens", "oranges", "reds",
            "ylorbr", "ylorrd", "orrd", "purd", "rdpu", "bupu",
            "gnbu", "pubu", "ylgnbu", "pubugn", "bugn", "ylgn",
            "spectral", "rdylgn", "rdylbu", "rdgy", "rdbu", "piyg",
            "prgn", "brbg", "coolwarm", "bwr", "seismic"
        }
        if "colormap_name" in render_spec:
            cm = render_spec["colormap_name"].lower()
            if cm not in known_colormaps:
                messages.append(f"Unknown colormap_name '{cm}' (may still work)")

        return messages

    # =========================================================================
    # UTILITY
    # =========================================================================

    def render_exists(self, cog_id: str, render_id: str) -> bool:
        """Check if a render config exists."""
        return self.repository.render_exists(cog_id, render_id)

    def count_renders(self, cog_id: str) -> int:
        """Count render configs for a COG."""
        return self.repository.count_renders(cog_id)
