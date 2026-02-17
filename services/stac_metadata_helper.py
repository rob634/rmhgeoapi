# ============================================================================
# STAC METADATA HELPER
# ============================================================================
# STATUS: Service layer - Centralized metadata enrichment for STAC items
# PURPOSE: Ensure consistent metadata across all STAC items (raster and vector)
# LAST_REVIEWED: 16 FEB 2026
# REVIEW_STATUS: V0.9 P2.6 — Aligned with Epoch 5 property namespaces
# EXPORTS: STACMetadataHelper, VisualizationMetadata
# DEPENDENCIES: core.models.stac (ProvenanceProperties, PlatformProperties, GeoProperties)
# ============================================================================
"""
STAC Metadata Helper - Centralized Metadata Enrichment.

V0.9 P2.6 Rewrite (16 FEB 2026):
    Old dataclasses (PlatformMetadata, AppMetadata, RasterVisualizationMetadata) DELETED.
    Replaced by Pydantic models in core.models.stac:
        - ProvenanceProperties (geoetl:*)
        - PlatformProperties (ddh:*)
        - GeoProperties (geo:*)

    TiTiler URL generation now reads from properties.renders.default
    (STAC Render Extension v2.0.0) instead of custom app:* properties.

Exports:
    STACMetadataHelper: Main helper class for augmenting STAC items/collections
    VisualizationMetadata: TiTiler URL dataclass (for pgSTAC search links)
"""

import logging
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple

from core.models.stac import (
    ProvenanceProperties,
    PlatformProperties,
    GeoProperties,
    STAC_EXT_FILE,
)

logger = logging.getLogger(__name__)


# =============================================================================
# VISUALIZATION METADATA (kept — used for pgSTAC search links)
# =============================================================================

@dataclass
class VisualizationMetadata:
    """
    TiTiler visualization URLs for STAC links.

    Used to generate STAC links with rel='preview', 'tilejson', 'tiles'.

    Attributes:
        viewer_url: Interactive map viewer URL
        tilejson_url: TileJSON specification URL
        tiles_url: XYZ tile endpoint template
        thumbnail_url: Preview thumbnail URL
        search_id: pgSTAC search hash (for collections)
    """
    viewer_url: Optional[str] = None
    tilejson_url: Optional[str] = None
    tiles_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    search_id: Optional[str] = None

    def to_stac_links(self) -> List[Dict[str, str]]:
        """
        Convert to STAC link objects.

        Returns:
            List of link dicts with rel, href, type, title
        """
        links = []
        if self.viewer_url:
            links.append({
                'rel': 'preview',
                'href': self.viewer_url,
                'type': 'text/html',
                'title': 'Interactive map viewer (TiTiler)'
            })
        if self.tilejson_url:
            links.append({
                'rel': 'tilejson',
                'href': self.tilejson_url,
                'type': 'application/json',
                'title': 'TileJSON specification'
            })
        if self.tiles_url:
            links.append({
                'rel': 'tiles',
                'href': self.tiles_url,
                'type': 'image/png',
                'title': 'XYZ tile endpoint'
            })
        return links


# =============================================================================
# STAC METADATA HELPER
# =============================================================================

class STACMetadataHelper:
    """
    Centralized STAC metadata enrichment helper.

    V0.9 P2.6: Uses Pydantic models from core.models.stac instead of
    old dataclasses. TiTiler URLs read from properties.renders.default.

    Consolidates metadata generation for STAC collections and items:
    - Provenance metadata (geoetl:*) → ProvenanceProperties
    - Platform metadata (ddh:*) → PlatformProperties
    - Geographic metadata (geo:*) → GeoProperties (via ISO3AttributionService)
    - Visualization metadata (TiTiler URLs) → links + assets

    Example:
        helper = STACMetadataHelper()

        item_dict = helper.augment_item(
            item_dict=base_item,
            provenance=ProvenanceProperties(job_id='abc123', epoch=4),
            platform=PlatformProperties(dataset_id='aerial-2024'),
            include_iso3=True,
            include_titiler=True,
        )
    """

    def __init__(
        self,
        iso3_service: Optional['ISO3AttributionService'] = None,
        search_registrar: Optional['PgSTACSearchRegistration'] = None
    ):
        self._iso3_service = iso3_service
        self._search_registrar = search_registrar
        self._config = None

    @property
    def config(self):
        """Lazy-load app config."""
        if self._config is None:
            from config import get_config
            self._config = get_config()
        return self._config

    @property
    def iso3_service(self):
        """Lazy-load ISO3 attribution service."""
        if self._iso3_service is None:
            from services.iso3_attribution import ISO3AttributionService
            self._iso3_service = ISO3AttributionService()
        return self._iso3_service

    @property
    def search_registrar(self):
        """Lazy-load pgSTAC search registration service."""
        if self._search_registrar is None:
            from services.pgstac_search_registration import PgSTACSearchRegistration
            self._search_registrar = PgSTACSearchRegistration()
        return self._search_registrar

    # -------------------------------------------------------------------------
    # TITILER URL GENERATION (reads from renders.default)
    # -------------------------------------------------------------------------

    def _build_titiler_url_params_from_renders(
        self,
        item_dict: Dict[str, Any]
    ) -> str:
        """
        Build TiTiler URL parameters from properties.renders.default.

        V0.9 P2.6: Reads from STAC Render Extension v2.0.0 instead of
        custom app:* properties.

        Args:
            item_dict: STAC item dict with properties.renders.default

        Returns:
            URL parameter string (without leading &)
        """
        renders_default = (
            item_dict.get("properties", {})
            .get("renders", {})
            .get("default", {})
        )

        if not renders_default:
            return ""

        params = []

        # Rescale — renders stores as [[min, max], ...] per band
        rescale = renders_default.get("rescale")
        if rescale:
            for band_rescale in rescale:
                if isinstance(band_rescale, (list, tuple)) and len(band_rescale) == 2:
                    params.append(f"rescale={band_rescale[0]},{band_rescale[1]}")

        # Colormap
        colormap = renders_default.get("colormap_name")
        if colormap:
            params.append(f"colormap_name={colormap}")

        # Band indices
        bidx = renders_default.get("bidx")
        if bidx:
            for b in bidx:
                params.append(f"bidx={b}")

        # Nodata
        nodata = renders_default.get("nodata")
        if nodata is not None:
            params.append(f"nodata={nodata}")

        return "&".join(params)

    def build_titiler_links_cog(
        self,
        item_dict: Dict[str, Any],
        container: str,
        blob_name: str,
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Generate TiTiler visualization links and assets for single COG.

        V0.9 P2.6: Reads render params from item_dict properties.renders.default.

        Args:
            item_dict: STAC item dict (for reading renders.default)
            container: Azure container name
            blob_name: Blob path within container

        Returns:
            Tuple of (links list, assets dict) for STAC item
        """
        base = self.config.titiler_base_url.rstrip('/')
        vsiaz_path = f"/vsiaz/{container}/{blob_name}"
        encoded = urllib.parse.quote(vsiaz_path, safe='')

        # Build URL parameters from renders.default
        extra_params = self._build_titiler_url_params_from_renders(item_dict)
        param_suffix = f"&{extra_params}" if extra_params else ""

        links = [
            {
                'rel': 'preview',
                'href': f"{base}/cog/WebMercatorQuad/map.html?url={encoded}{param_suffix}",
                'type': 'text/html',
                'title': 'Interactive map viewer (TiTiler)'
            },
            {
                'rel': 'tilejson',
                'href': f"{base}/cog/WebMercatorQuad/tilejson.json?url={encoded}{param_suffix}",
                'type': 'application/json',
                'title': 'TileJSON specification'
            },
            {
                'rel': 'tiles',
                'href': f"{base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={encoded}{param_suffix}",
                'type': 'image/png',
                'title': 'XYZ tile endpoint (for web apps)'
            }
        ]

        # Thumbnail also uses render params for proper rendering
        assets = {
            'thumbnail': {
                'href': f"{base}/cog/preview.png?url={encoded}&max_size=256{param_suffix}",
                'type': 'image/png',
                'roles': ['thumbnail'],
                'title': 'Thumbnail preview'
            }
        }

        return links, assets

    def build_titiler_links_pgstac(
        self,
        collection_id: str,
        bbox: Optional[List[float]] = None,
        register: bool = True
    ) -> Tuple[List[Dict], VisualizationMetadata]:
        """
        Generate TiTiler-pgSTAC visualization links for collection.

        Args:
            collection_id: STAC collection ID
            bbox: Collection bounding box (for TileJSON auto-zoom)
            register: Whether to register search (default True)

        Returns:
            Tuple of (links list, VisualizationMetadata)
        """
        search_id = None
        urls = {}

        if register:
            try:
                search_id = self.search_registrar.register_collection_search(
                    collection_id=collection_id,
                    metadata={'name': f'{collection_id} mosaic'},
                    bbox=bbox
                )
                urls = self.search_registrar.get_search_urls(
                    search_id=search_id,
                    titiler_base_url=self.config.titiler_base_url,
                    assets=['data']
                )
            except Exception as e:
                logger.warning(f"   pgSTAC search registration failed (non-fatal): {e}")

        vis_meta = VisualizationMetadata(
            viewer_url=urls.get('viewer'),
            tilejson_url=urls.get('tilejson'),
            tiles_url=urls.get('tiles'),
            search_id=search_id
        )

        return vis_meta.to_stac_links(), vis_meta

    # -------------------------------------------------------------------------
    # HIGH-LEVEL AUGMENTATION METHODS
    # -------------------------------------------------------------------------

    def augment_item(
        self,
        item_dict: Dict[str, Any],
        bbox: Optional[List[float]] = None,
        container: Optional[str] = None,
        blob_name: Optional[str] = None,
        provenance: Optional[ProvenanceProperties] = None,
        platform: Optional[PlatformProperties] = None,
        geo: Optional[GeoProperties] = None,
        include_iso3: bool = True,
        include_titiler: bool = True,
        file_checksum: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Augment STAC item dict with all metadata categories.

        V0.9 P2.6: Uses Pydantic models instead of old dataclasses.
        TiTiler URLs read from properties.renders.default.

        Args:
            item_dict: Base STAC item dictionary (plain dict)
            bbox: Bounding box for geographic attribution (uses item bbox if None)
            container: Azure container for TiTiler URLs
            blob_name: Blob path for TiTiler URLs
            provenance: Provenance metadata (geoetl:*)
            platform: Platform metadata (ddh:*)
            geo: Geographic metadata (geo:*) — overrides ISO3 lookup if provided
            include_iso3: Look up ISO3 country codes if geo not provided (default True)
            include_titiler: Add TiTiler visualization links (default True)
            file_checksum: SHA-256 multihash for STAC file:checksum
            file_size: File size in bytes for STAC file:size

        Returns:
            Augmented item_dict with additional properties, links, assets
        """
        # Ensure properties dict exists
        if 'properties' not in item_dict:
            item_dict['properties'] = {}

        # Use item bbox if not provided
        if bbox is None:
            bbox = item_dict.get('bbox')

        # Add provenance metadata (geoetl:*)
        if provenance:
            props = provenance.to_prefixed_dict()
            item_dict['properties'].update(props)
            logger.debug(f"   Added provenance metadata: {list(props.keys())}")

        # Add platform metadata (ddh:*)
        if platform:
            props = platform.model_dump(by_alias=True, exclude_none=True)
            item_dict['properties'].update(props)
            logger.debug(f"   Added platform metadata: {list(props.keys())}")

        # Add geographic metadata (geo:*)
        if geo:
            props = geo.to_flat_dict()
            item_dict['properties'].update(props)
            logger.debug(f"   Added geographic metadata: {list(props.keys())}")
        elif include_iso3 and bbox:
            props = self._build_geographic_properties(bbox=bbox)
            if props:
                item_dict['properties'].update(props)
                logger.debug(f"   Added geographic metadata (ISO3 lookup): {list(props.keys())}")

        # Add TiTiler visualization (reads from renders.default)
        if include_titiler and container and blob_name:
            links, assets = self.build_titiler_links_cog(item_dict, container, blob_name)

            if 'links' not in item_dict:
                item_dict['links'] = []
            item_dict['links'].extend(links)

            if 'assets' not in item_dict:
                item_dict['assets'] = {}
            item_dict['assets'].update(assets)

            logger.debug(f"   Added TiTiler links: {[l['rel'] for l in links]}")

        # Add STAC file extension properties to data asset
        if file_checksum or file_size:
            self._add_file_extension(item_dict, container, blob_name, file_checksum, file_size)

        return item_dict

    def augment_collection(
        self,
        collection_dict: Dict[str, Any],
        bbox: Optional[List[float]] = None,
        provenance: Optional[ProvenanceProperties] = None,
        platform: Optional[PlatformProperties] = None,
        include_iso3: bool = True,
        register_search: bool = True
    ) -> Tuple[Dict[str, Any], VisualizationMetadata]:
        """
        Augment STAC collection dict with metadata and visualization.

        V0.9 P2.6: platform:* → ddh:*, app:* → geoetl:*

        Args:
            collection_dict: Base STAC collection dictionary
            bbox: Collection bounding box
            provenance: Provenance metadata (geoetl:*)
            platform: Platform metadata (ddh:*)
            include_iso3: Add ISO3 country codes to summaries
            register_search: Register pgSTAC search for visualization

        Returns:
            Tuple of (augmented collection_dict, VisualizationMetadata)
        """
        collection_id = collection_dict.get('id')

        # Extract bbox from extent if not provided
        if bbox is None and 'extent' in collection_dict:
            extent = collection_dict['extent']
            if isinstance(extent, dict) and 'spatial' in extent:
                bboxes = extent['spatial'].get('bbox', [])
                if bboxes:
                    bbox = bboxes[0]

        # Initialize summaries
        summaries = collection_dict.get('summaries', {})

        # Add platform metadata to summaries (ddh:*)
        if platform:
            platform_props = platform.model_dump(by_alias=True, exclude_none=True)
            for key, val in platform_props.items():
                summaries[key] = [val]

        # Add provenance metadata to summaries (geoetl:*)
        if provenance:
            prov_props = provenance.to_prefixed_dict()
            for key, val in prov_props.items():
                summaries[key] = [val]

        # Add ISO3 to summaries
        if include_iso3 and bbox:
            props = self._build_geographic_properties(bbox=bbox)
            if props.get('geo:iso3'):
                summaries['geo:iso3'] = props['geo:iso3']
            if props.get('geo:primary_iso3'):
                summaries['geo:primary_iso3'] = [props['geo:primary_iso3']]

        collection_dict['summaries'] = summaries

        # Add visualization links
        vis_meta = VisualizationMetadata()
        if register_search and collection_id:
            links, vis_meta = self.build_titiler_links_pgstac(
                collection_id=collection_id,
                bbox=bbox,
                register=True
            )

            if 'links' not in collection_dict:
                collection_dict['links'] = []
            collection_dict['links'].extend(links)

            # Add search_id to summaries
            if vis_meta.search_id:
                summaries['mosaic:search_id'] = [vis_meta.search_id]

            logger.debug(f"   Added collection visualization: search_id={vis_meta.search_id}")

        return collection_dict, vis_meta

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _build_geographic_properties(
        self,
        bbox: Optional[List[float]] = None,
        geometry: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build geo:* properties via ISO3AttributionService lookup.

        Args:
            bbox: Bounding box [minx, miny, maxx, maxy]
            geometry: GeoJSON geometry (alternative to bbox)

        Returns:
            Dict of geo:* prefixed properties
        """
        if bbox:
            attribution = self.iso3_service.get_attribution_for_bbox(bbox)
        elif geometry:
            attribution = self.iso3_service.get_attribution_for_geometry(geometry)
        else:
            return {}

        return attribution.to_stac_properties()

    @staticmethod
    def _add_file_extension(
        item_dict: Dict[str, Any],
        container: Optional[str],
        blob_name: Optional[str],
        file_checksum: Optional[str],
        file_size: Optional[int],
    ) -> None:
        """Add STAC file extension properties to data asset."""
        if 'assets' not in item_dict:
            item_dict['assets'] = {}

        # Ensure 'data' asset exists
        if 'data' not in item_dict['assets']:
            item_dict['assets']['data'] = {
                'href': f"/vsiaz/{container}/{blob_name}" if container and blob_name else '',
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data'],
            }

        if file_checksum:
            item_dict['assets']['data']['file:checksum'] = file_checksum
        if file_size:
            item_dict['assets']['data']['file:size'] = file_size

        # Add file extension URL if not present
        if 'stac_extensions' not in item_dict:
            item_dict['stac_extensions'] = []
        if STAC_EXT_FILE not in item_dict['stac_extensions']:
            item_dict['stac_extensions'].append(STAC_EXT_FILE)

        logger.debug(f"   Added file extension: checksum={file_checksum[:20] if file_checksum else None}..., size={file_size}")


# Export classes
__all__ = [
    'STACMetadataHelper',
    'VisualizationMetadata',
]
