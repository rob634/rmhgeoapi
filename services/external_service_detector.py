# ============================================================================
# CLAUDE CONTEXT - EXTERNAL SERVICE DETECTOR
# ============================================================================
# STATUS: Service - Geospatial service type detection from URLs
# PURPOSE: Probe URLs to identify service type and extract capabilities
# CREATED: 22 JAN 2026
# LAST_REVIEWED: 22 JAN 2026
# ============================================================================
"""
External Service Detector - Geospatial Service Type Detection.

Probes URLs to identify geospatial service types and extract capabilities.
Supports ArcGIS REST, OGC (WMS/WFS/WMTS), OGC API, STAC, XYZ tiles, and more.

Detection Strategy:
    1. URL Pattern Analysis - Quick initial classification
    2. Endpoint Probing - Definitive type confirmation
    3. Capability Extraction - Service metadata collection

Service Types Supported:
    - ArcGIS REST (MapServer, FeatureServer, ImageServer)
    - OGC Legacy (WMS, WFS, WMTS)
    - OGC API (Features, Tiles)
    - STAC API
    - XYZ/TMS Tiles
    - COG Endpoints

Exports:
    ServiceDetector: Service type detection class
    DetectionResult: Result dataclass
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from core.models.external_service import ServiceType

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "service_detector")


@dataclass
class DetectionResult:
    """Result of service type detection."""
    service_type: ServiceType
    confidence: float  # 0.0 to 1.0
    capabilities: Dict[str, Any]
    error: Optional[str] = None


class ServiceDetector:
    """
    Geospatial service type detector.

    Probes URLs to identify service type and extract capabilities.
    Uses httpx for HTTP requests with configurable timeout.
    """

    DEFAULT_TIMEOUT = 30.0  # seconds

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize detector.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout

        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available - detection will be limited")

    def detect(self, url: str) -> DetectionResult:
        """
        Detect service type from URL.

        Performs intelligent probing to identify service type
        and extract capabilities.

        Args:
            url: Service endpoint URL

        Returns:
            DetectionResult with type, confidence, and capabilities
        """
        if not HTTPX_AVAILABLE:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error="httpx not available"
            )

        logger.info(f"Detecting service type for: {url}")

        # Phase 1: URL pattern heuristics
        url_lower = url.lower()

        # ArcGIS REST patterns
        if '/mapserver' in url_lower:
            result = self._probe_arcgis(url, 'MapServer')
            if result.confidence > 0.5:
                return result

        if '/featureserver' in url_lower:
            result = self._probe_arcgis(url, 'FeatureServer')
            if result.confidence > 0.5:
                return result

        if '/imageserver' in url_lower:
            result = self._probe_arcgis(url, 'ImageServer')
            if result.confidence > 0.5:
                return result

        # XYZ/TMS tile pattern
        if re.search(r'[/{]\s*[zxy]\s*[}/]', url_lower) or '{z}' in url_lower:
            result = self._probe_xyz(url)
            if result.confidence > 0.5:
                return result

        # Phase 2: OGC Legacy services (WMS, WFS, WMTS)
        for service in ['WMS', 'WFS', 'WMTS']:
            result = self._probe_ogc_legacy(url, service)
            if result.confidence > 0.5:
                return result

        # Phase 3: OGC API services
        result = self._probe_ogc_api(url)
        if result.confidence > 0.5:
            return result

        # Phase 4: STAC API
        result = self._probe_stac(url)
        if result.confidence > 0.5:
            return result

        # Phase 5: COG endpoint
        result = self._probe_cog(url)
        if result.confidence > 0.5:
            return result

        # Phase 6: Generic REST fallback
        return self._probe_generic(url)

    def _make_request(
        self,
        url: str,
        method: str = 'GET',
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Tuple[Optional[httpx.Response], Optional[str]]:
        """
        Make HTTP request with error handling.

        Args:
            url: Request URL
            method: HTTP method
            params: Query parameters
            headers: Request headers

        Returns:
            Tuple of (response, error_message)
        """
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.request(method, url, params=params, headers=headers)
                return response, None
        except httpx.TimeoutException:
            return None, "Request timeout"
        except httpx.RequestError as e:
            return None, f"Request error: {str(e)}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"

    def _probe_arcgis(self, url: str, server_type: str) -> DetectionResult:
        """
        Probe ArcGIS REST service.

        Args:
            url: Service URL
            server_type: MapServer, FeatureServer, or ImageServer

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing ArcGIS {server_type}: {url}")

        # Add ?f=json to get JSON response
        response, error = self._make_request(url, params={'f': 'json'})

        if error or response is None:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        if response.status_code != 200:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=f"HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except Exception:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error="Invalid JSON response"
            )

        # Identify by response characteristics
        capabilities = {}

        if server_type == 'MapServer':
            if 'serviceDescription' in data or 'mapName' in data:
                capabilities = {
                    'service_description': data.get('serviceDescription', ''),
                    'map_name': data.get('mapName', ''),
                    'layers': [{'id': l.get('id'), 'name': l.get('name')} for l in data.get('layers', [])],
                    'spatial_reference': data.get('spatialReference', {}),
                    'initial_extent': data.get('initialExtent', {}),
                    'supported_image_formats': data.get('supportedImageFormatTypes', '').split(','),
                }
                return DetectionResult(
                    service_type=ServiceType.ARCGIS_MAPSERVER,
                    confidence=0.95,
                    capabilities=capabilities
                )

        elif server_type == 'FeatureServer':
            if 'layers' in data or 'tables' in data:
                capabilities = {
                    'service_description': data.get('serviceDescription', ''),
                    'layers': [{'id': l.get('id'), 'name': l.get('name'), 'geometry_type': l.get('geometryType')} for l in data.get('layers', [])],
                    'tables': [{'id': t.get('id'), 'name': t.get('name')} for t in data.get('tables', [])],
                    'has_versioned_data': data.get('hasVersionedData', False),
                    'supported_query_formats': data.get('supportedQueryFormats', '').split(','),
                }
                return DetectionResult(
                    service_type=ServiceType.ARCGIS_FEATURESERVER,
                    confidence=0.95,
                    capabilities=capabilities
                )

        elif server_type == 'ImageServer':
            if 'pixelSizeX' in data or 'bandCount' in data:
                capabilities = {
                    'service_description': data.get('serviceDescription', ''),
                    'band_count': data.get('bandCount'),
                    'pixel_type': data.get('pixelType'),
                    'extent': data.get('extent', {}),
                    'spatial_reference': data.get('spatialReference', {}),
                }
                return DetectionResult(
                    service_type=ServiceType.ARCGIS_IMAGESERVER,
                    confidence=0.95,
                    capabilities=capabilities
                )

        # ArcGIS but couldn't determine specific type
        return DetectionResult(
            service_type=ServiceType.GENERIC_REST,
            confidence=0.3,
            capabilities={'raw_response': data}
        )

    def _probe_ogc_legacy(self, url: str, service: str) -> DetectionResult:
        """
        Probe OGC legacy service (WMS, WFS, WMTS).

        Args:
            url: Service URL
            service: WMS, WFS, or WMTS

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing OGC {service}: {url}")

        # Build GetCapabilities request
        version = '1.3.0' if service == 'WMS' else '2.0.0' if service == 'WFS' else '1.0.0'
        params = {
            'SERVICE': service,
            'REQUEST': 'GetCapabilities',
            'VERSION': version
        }

        response, error = self._make_request(url, params=params)

        if error or response is None:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        if response.status_code != 200:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=f"HTTP {response.status_code}"
            )

        # Parse XML response
        try:
            content = response.text
            root = ET.fromstring(content)
        except ET.ParseError:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error="Invalid XML response"
            )

        # Check for service-specific root element
        root_tag = root.tag.lower()

        if service == 'WMS' and ('wms_capabilities' in root_tag or 'wmt_ms_capabilities' in root_tag):
            capabilities = self._extract_wms_capabilities(root)
            return DetectionResult(
                service_type=ServiceType.WMS,
                confidence=0.95,
                capabilities=capabilities
            )

        if service == 'WFS' and 'wfs_capabilities' in root_tag:
            capabilities = self._extract_wfs_capabilities(root)
            return DetectionResult(
                service_type=ServiceType.WFS,
                confidence=0.95,
                capabilities=capabilities
            )

        if service == 'WMTS' and 'capabilities' in root_tag:
            capabilities = self._extract_wmts_capabilities(root)
            return DetectionResult(
                service_type=ServiceType.WMTS,
                confidence=0.95,
                capabilities=capabilities
            )

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={}
        )

    def _probe_ogc_api(self, url: str) -> DetectionResult:
        """
        Probe OGC API service (Features, Tiles).

        Args:
            url: Service URL

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing OGC API: {url}")

        # Try landing page
        response, error = self._make_request(url, headers={'Accept': 'application/json'})

        if error or response is None or response.status_code != 200:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        try:
            data = response.json()
        except Exception:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={}
            )

        # Check for OGC API characteristics
        links = data.get('links', [])
        conformance_link = next(
            (l for l in links if l.get('rel') == 'conformance'),
            None
        )

        if conformance_link:
            # Fetch conformance
            conformance_url = urljoin(url, conformance_link.get('href', ''))
            conf_response, _ = self._make_request(conformance_url)

            if conf_response and conf_response.status_code == 200:
                try:
                    conf_data = conf_response.json()
                    conforms_to = conf_data.get('conformsTo', [])

                    # Check for Features
                    if any('features' in c.lower() for c in conforms_to):
                        return DetectionResult(
                            service_type=ServiceType.OGC_API_FEATURES,
                            confidence=0.95,
                            capabilities={
                                'title': data.get('title', ''),
                                'description': data.get('description', ''),
                                'conformsTo': conforms_to,
                                'links': links
                            }
                        )

                    # Check for Tiles
                    if any('tiles' in c.lower() for c in conforms_to):
                        return DetectionResult(
                            service_type=ServiceType.OGC_API_TILES,
                            confidence=0.95,
                            capabilities={
                                'title': data.get('title', ''),
                                'description': data.get('description', ''),
                                'conformsTo': conforms_to,
                                'links': links
                            }
                        )
                except Exception:
                    pass

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={}
        )

    def _probe_stac(self, url: str) -> DetectionResult:
        """
        Probe STAC API.

        Args:
            url: Service URL

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing STAC API: {url}")

        response, error = self._make_request(url, headers={'Accept': 'application/json'})

        if error or response is None or response.status_code != 200:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        try:
            data = response.json()
        except Exception:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={}
            )

        # Check for STAC characteristics
        if 'stac_version' in data:
            capabilities = {
                'stac_version': data.get('stac_version'),
                'type': data.get('type'),
                'id': data.get('id'),
                'title': data.get('title', ''),
                'description': data.get('description', ''),
                'links': data.get('links', []),
            }

            # Check if it's a Catalog, Collection, or Item
            stac_type = data.get('type', 'Catalog')
            capabilities['stac_type'] = stac_type

            return DetectionResult(
                service_type=ServiceType.STAC_API,
                confidence=0.95,
                capabilities=capabilities
            )

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={}
        )

    def _probe_xyz(self, url: str) -> DetectionResult:
        """
        Probe XYZ/TMS tile service.

        Args:
            url: Tile URL template (with {z}, {x}, {y} placeholders)

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing XYZ tiles: {url}")

        # Try to fetch tile 0/0/0
        test_url = url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0')
        test_url = re.sub(r'\{[zxy]\}', '0', test_url, flags=re.IGNORECASE)

        response, error = self._make_request(test_url)

        if error or response is None:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')

            if 'image' in content_type:
                # TMS uses inverted Y
                is_tms = '/tms/' in url.lower() or 'tms' in url.lower()

                return DetectionResult(
                    service_type=ServiceType.TMS_TILES if is_tms else ServiceType.XYZ_TILES,
                    confidence=0.8,
                    capabilities={
                        'url_template': url,
                        'content_type': content_type,
                        'is_tms': is_tms
                    }
                )

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={}
        )

    def _probe_cog(self, url: str) -> DetectionResult:
        """
        Probe Cloud-Optimized GeoTIFF endpoint.

        Args:
            url: COG URL

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing COG: {url}")

        # Use HEAD request to check content type
        response, error = self._make_request(url, method='HEAD')

        if error or response is None:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            content_length = response.headers.get('content-length')

            if 'tiff' in content_type.lower() or url.lower().endswith(('.tif', '.tiff')):
                return DetectionResult(
                    service_type=ServiceType.COG_ENDPOINT,
                    confidence=0.7,
                    capabilities={
                        'content_type': content_type,
                        'content_length': int(content_length) if content_length else None,
                        'accepts_range_requests': 'bytes' in response.headers.get('accept-ranges', '')
                    }
                )

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={}
        )

    def _probe_generic(self, url: str) -> DetectionResult:
        """
        Generic REST endpoint probe (fallback).

        Args:
            url: Service URL

        Returns:
            DetectionResult
        """
        logger.debug(f"Probing generic REST: {url}")

        response, error = self._make_request(url)

        if error or response is None:
            return DetectionResult(
                service_type=ServiceType.UNKNOWN,
                confidence=0.0,
                capabilities={},
                error=error
            )

        if response.status_code == 200:
            return DetectionResult(
                service_type=ServiceType.GENERIC_REST,
                confidence=0.3,
                capabilities={
                    'content_type': response.headers.get('content-type'),
                    'status_code': response.status_code
                }
            )

        return DetectionResult(
            service_type=ServiceType.UNKNOWN,
            confidence=0.0,
            capabilities={},
            error=f"HTTP {response.status_code}"
        )

    def _extract_wms_capabilities(self, root: ET.Element) -> Dict[str, Any]:
        """Extract capabilities from WMS GetCapabilities response."""
        # Simplified extraction - can be expanded
        ns = {'wms': 'http://www.opengis.net/wms'}

        capabilities = {
            'version': root.get('version', ''),
            'layers': [],
            'formats': []
        }

        # Try to find layers
        for layer in root.iter():
            if 'layer' in layer.tag.lower():
                name = layer.find('.//Name', ns) or layer.find('.//name')
                title = layer.find('.//Title', ns) or layer.find('.//title')
                if name is not None:
                    capabilities['layers'].append({
                        'name': name.text,
                        'title': title.text if title is not None else None
                    })

        return capabilities

    def _extract_wfs_capabilities(self, root: ET.Element) -> Dict[str, Any]:
        """Extract capabilities from WFS GetCapabilities response."""
        capabilities = {
            'version': root.get('version', ''),
            'feature_types': []
        }

        for ft in root.iter():
            if 'featuretype' in ft.tag.lower():
                name = ft.find('.//Name') or ft.find('.//name')
                title = ft.find('.//Title') or ft.find('.//title')
                if name is not None:
                    capabilities['feature_types'].append({
                        'name': name.text,
                        'title': title.text if title is not None else None
                    })

        return capabilities

    def _extract_wmts_capabilities(self, root: ET.Element) -> Dict[str, Any]:
        """Extract capabilities from WMTS GetCapabilities response."""
        capabilities = {
            'version': root.get('version', ''),
            'layers': [],
            'tile_matrix_sets': []
        }

        for layer in root.iter():
            if 'layer' in layer.tag.lower():
                identifier = layer.find('.//Identifier') or layer.find('.//identifier')
                title = layer.find('.//Title') or layer.find('.//title')
                if identifier is not None:
                    capabilities['layers'].append({
                        'identifier': identifier.text,
                        'title': title.text if title is not None else None
                    })

        return capabilities


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ServiceDetector',
    'DetectionResult',
]
