"""
STAC Metadata Helper - Centralized Metadata Enrichment.

Consolidates scattered metadata generation into a clean, type-safe architecture:
    - Platform metadata (DDH identifiers) → platform:* properties
    - App metadata (job linkage) → app:* properties
    - Geographic metadata (ISO3 codes) → geo:* properties
    - Visualization metadata (TiTiler URLs) → links and assets

Exports:
    STACMetadataHelper: Main helper class for augmenting STAC items
    PlatformMetadata: Platform identifier dataclass
    AppMetadata: Job linkage dataclass
    VisualizationMetadata: TiTiler URL dataclass
"""

import logging
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# METADATA DATACLASSES
# =============================================================================

@dataclass
class PlatformMetadata:
    """
    Platform/DDH identifiers for STAC properties.

    Namespace: platform:*
    Source: PlatformRequest via job_parameters

    Attributes:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier
        request_id: Platform request hash (SHA256[:32])
        access_level: Data classification (public, OUO, restricted)
        client_id: Client application identifier (default: 'ddh')
    """
    dataset_id: Optional[str] = None
    resource_id: Optional[str] = None
    version_id: Optional[str] = None
    request_id: Optional[str] = None
    access_level: Optional[str] = None
    client_id: str = 'ddh'

    @classmethod
    def from_job_params(cls, params: Dict[str, Any]) -> Optional['PlatformMetadata']:
        """
        Factory method to extract PlatformMetadata from job parameters.

        Looks for platform identifiers in params dict. Returns None if
        no platform fields found.

        Args:
            params: Job or task parameters dict

        Returns:
            PlatformMetadata if any fields found, None otherwise
        """
        # Check if any platform fields exist
        platform_fields = [
            'dataset_id', 'resource_id', 'version_id',
            '_platform_request_id', 'request_id',
            'access_level', 'client_id'
        ]
        has_platform_data = any(params.get(f) for f in platform_fields)

        if not has_platform_data:
            # Also check nested platform_metadata dict
            nested = params.get('platform_metadata', {})
            if not nested:
                return None
            params = nested

        return cls(
            dataset_id=params.get('dataset_id'),
            resource_id=params.get('resource_id'),
            version_id=params.get('version_id'),
            request_id=params.get('_platform_request_id') or params.get('request_id'),
            access_level=params.get('access_level'),
            client_id=params.get('client_id', 'ddh')
        )

    def to_stac_properties(self) -> Dict[str, Any]:
        """
        Convert to STAC properties dict with platform:* prefix.

        Returns:
            Dict of namespaced properties (only non-None values)
        """
        props = {}
        if self.dataset_id:
            props['platform:dataset_id'] = self.dataset_id
        if self.resource_id:
            props['platform:resource_id'] = self.resource_id
        if self.version_id:
            props['platform:version_id'] = self.version_id
        if self.request_id:
            props['platform:request_id'] = self.request_id
        if self.access_level:
            props['platform:access_level'] = self.access_level
        if self.client_id:
            props['platform:client'] = self.client_id
        return props


@dataclass
class AppMetadata:
    """
    Application-level metadata for STAC properties.

    Namespace: app:*
    Source: Job execution context

    Attributes:
        job_id: CoreMachine job ID (links STAC item back to job)
        job_type: Job type that created this item
        created_by: Application identifier (default: 'rmhazuregeoapi')
        processing_timestamp: When the item was created (auto-filled if None)
    """
    job_id: Optional[str] = None
    job_type: Optional[str] = None
    created_by: str = 'rmhazuregeoapi'
    processing_timestamp: Optional[str] = None

    def to_stac_properties(self) -> Dict[str, Any]:
        """
        Convert to STAC properties dict with app:* prefix.

        Returns:
            Dict of namespaced properties
        """
        props = {
            'app:created_by': self.created_by,
            'app:processing_timestamp': self.processing_timestamp or datetime.now(timezone.utc).isoformat()
        }
        if self.job_id:
            props['app:job_id'] = self.job_id
        if self.job_type:
            props['app:job_type'] = self.job_type
        return props


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

    Consolidates metadata generation for STAC collections and items across:
    - Platform metadata (DDH identifiers) → platform:*
    - Application metadata (job linkage) → app:*
    - Geographic metadata (ISO3 country codes) → geo:*
    - Visualization metadata (TiTiler URLs) → links + assets

    Args:
        iso3_service: ISO3 attribution service (creates default if None)
        search_registrar: pgSTAC search registration service (creates default if None)

    Example:
        helper = STACMetadataHelper()

        # Augment item with all metadata
        item_dict = helper.augment_item(
            item_dict=base_item,
            bbox=[-70.7, -56.3, -70.6, -56.2],
            container='silver-cogs',
            blob_name='collection/tile.tif',
            platform=PlatformMetadata(dataset_id='aerial-2024'),
            app=AppMetadata(job_id='abc123')
        )
    """

    def __init__(
        self,
        iso3_service: Optional['ISO3AttributionService'] = None,
        search_registrar: Optional['PgSTACSearchRegistration'] = None
    ):
        """
        Initialize with optional service injection.

        Args:
            iso3_service: ISO3 attribution service (lazy-loaded if None)
            search_registrar: pgSTAC search registration (lazy-loaded if None)
        """
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
    # LOW-LEVEL BUILDERS
    # -------------------------------------------------------------------------

    def build_platform_properties(self, platform: PlatformMetadata) -> Dict[str, Any]:
        """
        Build STAC properties from platform metadata.

        Args:
            platform: PlatformMetadata with DDH identifiers

        Returns:
            Dict of platform:* prefixed properties
        """
        return platform.to_stac_properties()

    def build_app_properties(self, app: AppMetadata) -> Dict[str, Any]:
        """
        Build STAC properties from application metadata.

        Args:
            app: AppMetadata with job linkage

        Returns:
            Dict of app:* prefixed properties
        """
        return app.to_stac_properties()

    def build_geographic_properties(
        self,
        bbox: Optional[List[float]] = None,
        geometry: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build STAC properties with ISO3 country attribution.

        Uses ISO3AttributionService for spatial queries.

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

    def build_titiler_links_cog(
        self,
        container: str,
        blob_name: str
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Generate TiTiler visualization links and assets for single COG.

        Args:
            container: Azure container name
            blob_name: Blob path within container

        Returns:
            Tuple of (links list, assets dict) for STAC item
        """
        base = self.config.titiler_base_url.rstrip('/')
        vsiaz_path = f"/vsiaz/{container}/{blob_name}"
        encoded = urllib.parse.quote(vsiaz_path, safe='')

        links = [
            {
                'rel': 'preview',
                'href': f"{base}/cog/WebMercatorQuad/map.html?url={encoded}",
                'type': 'text/html',
                'title': 'Interactive map viewer (TiTiler)'
            },
            {
                'rel': 'tilejson',
                'href': f"{base}/cog/WebMercatorQuad/tilejson.json?url={encoded}",
                'type': 'application/json',
                'title': 'TileJSON specification'
            }
        ]

        assets = {
            'thumbnail': {
                'href': f"{base}/cog/preview.png?url={encoded}&max_size=256",
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

        Optionally registers a pgSTAC search and returns URLs.

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
                logger.warning(f"   ⚠️  pgSTAC search registration failed (non-fatal): {e}")

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
        platform: Optional[PlatformMetadata] = None,
        app: Optional[AppMetadata] = None,
        include_iso3: bool = True,
        include_titiler: bool = True
    ) -> Dict[str, Any]:
        """
        Augment STAC item dict with all metadata categories.

        This is the primary entry point for adding metadata to items.

        Args:
            item_dict: Base STAC item dictionary
            bbox: Bounding box for geographic attribution (uses item bbox if None)
            container: Azure container for TiTiler URLs
            blob_name: Blob path for TiTiler URLs
            platform: Platform-layer metadata (DDH)
            app: Application-layer metadata (job linkage)
            include_iso3: Add ISO3 country codes (default True)
            include_titiler: Add TiTiler visualization links (default True)

        Returns:
            Augmented item_dict with additional properties, links, assets
        """
        # Ensure properties dict exists
        if 'properties' not in item_dict:
            item_dict['properties'] = {}

        # Use item bbox if not provided
        if bbox is None:
            bbox = item_dict.get('bbox')

        # Add platform metadata
        if platform:
            props = self.build_platform_properties(platform)
            item_dict['properties'].update(props)
            logger.debug(f"   Added platform metadata: {list(props.keys())}")

        # Add app metadata (job linkage)
        if app:
            props = self.build_app_properties(app)
            item_dict['properties'].update(props)
            logger.debug(f"   Added app metadata: {list(props.keys())}")

        # Add geographic metadata (ISO3)
        if include_iso3 and bbox:
            props = self.build_geographic_properties(bbox=bbox)
            if props:
                item_dict['properties'].update(props)
                logger.debug(f"   Added geographic metadata: {list(props.keys())}")

        # Add TiTiler visualization
        if include_titiler and container and blob_name:
            links, assets = self.build_titiler_links_cog(container, blob_name)

            if 'links' not in item_dict:
                item_dict['links'] = []
            item_dict['links'].extend(links)

            if 'assets' not in item_dict:
                item_dict['assets'] = {}
            item_dict['assets'].update(assets)

            logger.debug(f"   Added TiTiler links: {[l['rel'] for l in links]}")

        return item_dict

    def augment_collection(
        self,
        collection_dict: Dict[str, Any],
        bbox: Optional[List[float]] = None,
        platform: Optional[PlatformMetadata] = None,
        app: Optional[AppMetadata] = None,
        include_iso3: bool = True,
        register_search: bool = True
    ) -> Tuple[Dict[str, Any], VisualizationMetadata]:
        """
        Augment STAC collection dict with metadata and visualization.

        Args:
            collection_dict: Base STAC collection dictionary
            bbox: Collection bounding box
            platform: Platform-layer metadata
            app: Application-layer metadata
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

        # Add platform metadata to summaries
        if platform:
            if platform.dataset_id:
                summaries['platform:dataset_id'] = [platform.dataset_id]
            if platform.access_level:
                summaries['platform:access_level'] = [platform.access_level]
            if platform.client_id:
                summaries['platform:client'] = [platform.client_id]

        # Add app metadata to summaries
        if app:
            if app.job_id:
                summaries['app:job_id'] = [app.job_id]
            if app.job_type:
                summaries['app:job_type'] = [app.job_type]

        # Add ISO3 to summaries
        if include_iso3 and bbox:
            props = self.build_geographic_properties(bbox=bbox)
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


# Export classes
__all__ = [
    'STACMetadataHelper',
    'PlatformMetadata',
    'AppMetadata',
    'VisualizationMetadata'
]
