# ============================================================================
# STAC METADATA HELPER
# ============================================================================
# STATUS: Service layer - Centralized metadata enrichment for STAC items
# PURPOSE: Ensure consistent metadata across all STAC items (raster and vector)
# LAST_REVIEWED: 22 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: STACMetadataHelper, PlatformMetadata, AppMetadata, VisualizationMetadata, RasterVisualizationMetadata
# DEPENDENCIES: stac-pydantic
# ============================================================================
"""
STAC Metadata Helper - Centralized Metadata Enrichment.

Consolidates scattered metadata generation into a clean, type-safe architecture:
    - Platform metadata (DDH identifiers) → platform:* properties
    - App metadata (job linkage) → app:* properties
    - Geographic metadata (ISO3 codes) → geo:* properties
    - Raster visualization metadata (band info, rescale, colormap) → app:* properties
    - Visualization metadata (TiTiler URLs) → links and assets

Smart TiTiler URL Generation (F2.9 - 30 DEC 2025):
    - Single-band DEMs → rescale + terrain colormap
    - Single-band float → rescale + viridis colormap
    - 3-band RGB → no extra params
    - 3-band BGR → bidx reordering
    - 4+ bands → bidx=1,2,3 or custom rgb_bands

Exports:
    STACMetadataHelper: Main helper class for augmenting STAC items
    PlatformMetadata: Platform identifier dataclass
    AppMetadata: Job linkage dataclass
    VisualizationMetadata: TiTiler URL dataclass
    RasterVisualizationMetadata: Raster band/type info for smart URLs
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

    Properties Generated:
        app:published - Always False on creation (requires explicit approval)
        app:created_by - Application identifier
        app:processing_timestamp - ISO timestamp
        app:job_id - Job ID (if provided)
        app:job_type - Job type (if provided)

    Note:
        F7.Approval (22 JAN 2026): All STAC items start with app:published=False.
        Publication requires explicit approval via ApprovalService.
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

        Note:
            app:published defaults to False - requires explicit approval
            to set True. This is part of the mandatory approval workflow
            (F7.Approval - 22 JAN 2026).
        """
        props = {
            'app:created_by': self.created_by,
            'app:processing_timestamp': self.processing_timestamp or datetime.now(timezone.utc).isoformat(),
            'app:published': False,  # F7.Approval: Requires explicit approval to publish
        }
        if self.job_id:
            props['app:job_id'] = self.job_id
        if self.job_type:
            props['app:job_type'] = self.job_type
        return props


@dataclass
class RasterVisualizationMetadata:
    """
    Raster visualization metadata for STAC properties.

    Namespace: app:*
    Source: Raster validation results + rio-stac extraction

    Used to generate smart TiTiler URLs based on raster characteristics.
    Stored in STAC item properties for downstream viewer use.

    Attributes:
        raster_type: Detected type (rgb, rgba, dem, nir, multispectral, categorical)
        band_count: Number of bands
        dtype: Data type (uint8, uint16, float32, etc.)
        colorinterp: Color interpretation per band (red, green, blue, alpha, gray, etc.)
        rgb_bands: Recommended band indices for RGB display (1-indexed)
        rescale: Min/max rescale values with source info
        colormap: Recommended colormap name for single-band
        nodata: Nodata value if known
    """
    raster_type: Optional[str] = None
    band_count: Optional[int] = None
    dtype: Optional[str] = None
    colorinterp: Optional[List[str]] = None
    rgb_bands: Optional[List[int]] = None
    rescale: Optional[Dict[str, Any]] = None
    colormap: Optional[str] = None
    nodata: Optional[float] = None

    @classmethod
    def from_validation_result(cls, validation_result: Dict[str, Any]) -> 'RasterVisualizationMetadata':
        """
        Factory method to extract RasterVisualizationMetadata from raster validation result.

        Args:
            validation_result: Result dict from raster_validation.validate_raster()

        Returns:
            RasterVisualizationMetadata populated from validation data
        """
        result = validation_result.get('result', {})
        raster_type_info = result.get('raster_type', {})

        # Extract detected type
        detected_type = raster_type_info.get('detected_type', 'unknown')

        # Determine colormap based on raster type
        colormap = None
        if detected_type == 'dem':
            colormap = 'terrain'
        elif detected_type in ['ndvi', 'vegetation_index']:
            colormap = 'rdylgn'
        elif result.get('band_count', 0) == 1:
            colormap = 'viridis'

        # Determine RGB bands for multi-band imagery
        rgb_bands = None
        band_count = result.get('band_count', 0)
        if band_count == 4:
            # RGBA - use first 3 bands
            rgb_bands = [1, 2, 3]
        elif band_count == 8:
            # WorldView-3: use bands 5,3,2 for natural color
            rgb_bands = [5, 3, 2]
        elif band_count >= 10:
            # Sentinel-2/Landsat style: use bands 4,3,2 for natural color
            rgb_bands = [4, 3, 2]

        return cls(
            raster_type=detected_type,
            band_count=result.get('band_count'),
            dtype=result.get('dtype'),
            colorinterp=None,  # Not in validation result, comes from rio-stac
            rgb_bands=rgb_bands,
            rescale=None,  # Populated later from statistics
            colormap=colormap,
            nodata=result.get('nodata')
        )

    @classmethod
    def from_raster_type_params(cls, raster_type_info: Dict[str, Any]) -> 'RasterVisualizationMetadata':
        """
        Factory method to extract RasterVisualizationMetadata from job params raster_type dict.

        This handles the flattened structure passed through job parameters:
            {
                "detected_type": "multispectral",
                "band_count": 8,
                "data_type": "uint16",
                "optimal_cog_settings": {}
            }

        Args:
            raster_type_info: raster_type dict from job params (NOT full validation result)

        Returns:
            RasterVisualizationMetadata with band_count and rgb_bands properly set
        """
        if not raster_type_info or not isinstance(raster_type_info, dict):
            return cls()

        detected_type = raster_type_info.get('detected_type', 'unknown')
        band_count = raster_type_info.get('band_count', 0)
        # Note: params use 'data_type', validation uses 'dtype'
        dtype = raster_type_info.get('data_type') or raster_type_info.get('dtype')

        # Determine colormap based on raster type
        colormap = None
        if detected_type == 'dem':
            colormap = 'terrain'
        elif detected_type in ['ndvi', 'vegetation_index']:
            colormap = 'rdylgn'
        elif band_count == 1:
            colormap = 'viridis'

        # Determine RGB bands for multi-band imagery (04 JAN 2026)
        # Critical for TiTiler to avoid dimension errors on 4+ band rasters
        rgb_bands = None
        if band_count == 4:
            # RGBA - use first 3 bands
            rgb_bands = [1, 2, 3]
        elif band_count == 8:
            # WorldView-2/3: use bands 5,3,2 for natural color (Red, Green, Blue)
            rgb_bands = [5, 3, 2]
        elif band_count >= 10:
            # Sentinel-2/Landsat style: use bands 4,3,2 for natural color
            rgb_bands = [4, 3, 2]
        elif band_count > 3:
            # Generic multi-band: use first 3 bands
            rgb_bands = [1, 2, 3]

        return cls(
            raster_type=detected_type,
            band_count=band_count,
            dtype=dtype,
            colorinterp=None,
            rgb_bands=rgb_bands,
            rescale=None,
            colormap=colormap,
            nodata=raster_type_info.get('nodata')
        )

    def to_stac_properties(self) -> Dict[str, Any]:
        """
        Convert to STAC properties dict with app:* prefix.

        Returns:
            Dict of namespaced properties (only non-None values)
        """
        props = {}
        if self.raster_type:
            props['app:raster_type'] = self.raster_type
        if self.band_count is not None:
            props['app:band_count'] = self.band_count
        if self.dtype:
            props['app:dtype'] = self.dtype
        if self.colorinterp:
            props['app:colorinterp'] = self.colorinterp
        if self.rgb_bands:
            props['app:rgb_bands'] = self.rgb_bands
        if self.rescale:
            props['app:rescale'] = self.rescale
        if self.colormap:
            props['app:colormap'] = self.colormap
        if self.nodata is not None:
            props['app:nodata'] = self.nodata
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

    def build_raster_visualization_properties(
        self,
        raster_meta: RasterVisualizationMetadata
    ) -> Dict[str, Any]:
        """
        Build STAC properties from raster visualization metadata.

        Args:
            raster_meta: RasterVisualizationMetadata with band/type info

        Returns:
            Dict of app:* prefixed properties
        """
        return raster_meta.to_stac_properties()

    def _build_titiler_url_params(
        self,
        raster_meta: Optional[RasterVisualizationMetadata] = None
    ) -> str:
        """
        Build TiTiler URL parameters based on raster metadata.

        Implements the decision tree from TITILER-URL-GUIDE.md:
        - 1 band + float → rescale + colormap
        - 1 band + uint8 → grayscale (no params)
        - 3 bands RGB → no params
        - 4+ bands → bidx=1&bidx=2&bidx=3 (or custom rgb_bands)

        Args:
            raster_meta: Optional raster metadata for smart URL generation

        Returns:
            URL parameter string (without leading &)
        """
        if not raster_meta:
            return ""

        params = []
        band_count = raster_meta.band_count or 0
        dtype = raster_meta.dtype or ""
        raster_type = raster_meta.raster_type or ""
        colorinterp = raster_meta.colorinterp or []

        # Single band handling
        if band_count == 1:
            # Add rescale if available
            if raster_meta.rescale:
                min_val = raster_meta.rescale.get('min')
                max_val = raster_meta.rescale.get('max')
                if min_val is not None and max_val is not None:
                    params.append(f"rescale={min_val},{max_val}")

            # Add colormap based on type
            if raster_meta.colormap:
                params.append(f"colormap_name={raster_meta.colormap}")
            elif raster_type == 'dem':
                params.append("colormap_name=terrain")
            elif dtype in ['float32', 'float64', 'int16', 'int32']:
                params.append("colormap_name=viridis")

        # Multi-band handling (3+ bands)
        elif band_count >= 3:
            # Use custom rgb_bands if specified
            if raster_meta.rgb_bands:
                for band_idx in raster_meta.rgb_bands:
                    params.append(f"bidx={band_idx}")

            # Check colorinterp for BGR ordering
            elif len(colorinterp) >= 3:
                if colorinterp[:3] == ['blue', 'green', 'red']:
                    # BGR order - reorder to RGB
                    params.extend(["bidx=3", "bidx=2", "bidx=1"])
                elif band_count == 4 and colorinterp[3] != 'alpha':
                    # 4th band is not alpha - exclude it
                    params.extend(["bidx=1", "bidx=2", "bidx=3"])

            # Default for 4+ band without colorinterp info
            elif band_count >= 4 and not colorinterp:
                # Assume first 3 bands are RGB
                params.extend(["bidx=1", "bidx=2", "bidx=3"])

            # Add rescale for non-uint8 multi-band data (04 JAN 2026)
            # TiTiler requires one rescale param per displayed band for proper visualization
            if dtype not in ['uint8', '']:
                if raster_meta.rescale:
                    # Use provided rescale values
                    min_val = raster_meta.rescale.get('min', 0)
                    max_val = raster_meta.rescale.get('max', 10000)
                    rescale_str = f"{min_val},{max_val}"
                else:
                    # Smart defaults based on dtype (04 JAN 2026)
                    # WorldView/satellite uint16 typically ranges 0-2000 for reflectance
                    # Use conservative range that works for most satellite imagery
                    if dtype == 'uint16':
                        rescale_str = "0,2000"
                    elif dtype in ['int16']:
                        rescale_str = "-1000,1000"
                    elif dtype in ['float32', 'float64']:
                        rescale_str = "0,1"
                    else:
                        rescale_str = "0,10000"

                # Add one rescale per displayed band (3 for RGB display)
                num_display_bands = len(raster_meta.rgb_bands) if raster_meta.rgb_bands else 3
                for _ in range(num_display_bands):
                    params.append(f"rescale={rescale_str}")

        return "&".join(params)

    def build_titiler_links_cog(
        self,
        container: str,
        blob_name: str,
        raster_meta: Optional[RasterVisualizationMetadata] = None
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Generate TiTiler visualization links and assets for single COG.

        Args:
            container: Azure container name
            blob_name: Blob path within container
            raster_meta: Optional raster metadata for smart URL generation

        Returns:
            Tuple of (links list, assets dict) for STAC item
        """
        base = self.config.titiler_base_url.rstrip('/')
        vsiaz_path = f"/vsiaz/{container}/{blob_name}"
        encoded = urllib.parse.quote(vsiaz_path, safe='')

        # Build smart URL parameters based on raster type
        extra_params = self._build_titiler_url_params(raster_meta)
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

        # Thumbnail also uses smart params for proper rendering
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
        raster: Optional[RasterVisualizationMetadata] = None,
        include_iso3: bool = True,
        include_titiler: bool = True,
        file_checksum: Optional[str] = None,  # STAC file extension (21 JAN 2026)
        file_size: Optional[int] = None,  # STAC file extension (21 JAN 2026)
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
            raster: Raster visualization metadata (app:* properties + smart TiTiler URLs)
            include_iso3: Add ISO3 country codes (default True)
            include_titiler: Add TiTiler visualization links (default True)
            file_checksum: SHA-256 multihash for STAC file:checksum (21 JAN 2026)
            file_size: File size in bytes for STAC file:size (21 JAN 2026)

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

        # Add raster visualization metadata (app:*)
        if raster:
            props = self.build_raster_visualization_properties(raster)
            item_dict['properties'].update(props)
            logger.debug(f"   Added raster visualization metadata: {list(props.keys())}")

        # Add geographic metadata (ISO3)
        if include_iso3 and bbox:
            props = self.build_geographic_properties(bbox=bbox)
            if props:
                item_dict['properties'].update(props)
                logger.debug(f"   Added geographic metadata: {list(props.keys())}")

        # Add TiTiler visualization (with smart URLs if raster metadata provided)
        if include_titiler and container and blob_name:
            links, assets = self.build_titiler_links_cog(container, blob_name, raster)

            if 'links' not in item_dict:
                item_dict['links'] = []
            item_dict['links'].extend(links)

            if 'assets' not in item_dict:
                item_dict['assets'] = {}
            item_dict['assets'].update(assets)

            logger.debug(f"   Added TiTiler links: {[l['rel'] for l in links]}")

        # Add STAC file extension properties to data asset (21 JAN 2026)
        # Per https://github.com/stac-extensions/file
        if file_checksum or file_size:
            if 'assets' not in item_dict:
                item_dict['assets'] = {}

            # Ensure 'data' asset exists (rio-stac creates it, but be defensive)
            if 'data' not in item_dict['assets']:
                item_dict['assets']['data'] = {
                    'href': f"/vsiaz/{container}/{blob_name}" if container and blob_name else '',
                    'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                    'roles': ['data'],
                }

            # Add file extension properties
            if file_checksum:
                item_dict['assets']['data']['file:checksum'] = file_checksum
            if file_size:
                item_dict['assets']['data']['file:size'] = file_size

            # Add file extension to stac_extensions if not present
            file_extension_url = 'https://stac-extensions.github.io/file/v2.1.0/schema.json'
            if 'stac_extensions' not in item_dict:
                item_dict['stac_extensions'] = []
            if file_extension_url not in item_dict['stac_extensions']:
                item_dict['stac_extensions'].append(file_extension_url)

            logger.debug(f"   Added file extension: checksum={file_checksum[:20] if file_checksum else None}..., size={file_size}")

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
    'VisualizationMetadata',
    'RasterVisualizationMetadata'
]
