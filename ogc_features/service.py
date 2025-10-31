# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone Service - OGC Features API business logic
# PURPOSE: Business logic orchestration for OGC Features API endpoints
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: OGCFeaturesService
# INTERFACES: None (standalone implementation)
# PYDANTIC_MODELS: OGCLandingPage, OGCConformance, OGCCollection, OGCFeatureCollection, OGCLink
# DEPENDENCIES: typing, datetime, logging, urllib.parse
# SOURCE: Repository layer (OGCFeaturesRepository)
# SCOPE: Business logic for OGC API operations
# VALIDATION: Pydantic model validation
# PATTERNS: Service Layer, Facade Pattern
# ENTRY_POINTS: service = OGCFeaturesService(config); features = service.query_features(...)
# INDEX: OGCFeaturesService:61, get_landing_page:91, list_collections:154, query_features:274
# ============================================================================

"""
OGC Features Service - Business Logic Layer

Orchestrates OGC API - Features operations by coordinating between HTTP triggers
and the PostGIS repository layer. Handles:
- Response model creation (Pydantic)
- Link generation (self, next, prev, alternate)
- Pagination logic
- Error handling and validation
- Base URL management

This layer is responsible for implementing OGC API - Features specification
requirements while delegating database operations to the repository layer.

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs

from .config import OGCFeaturesConfig, get_ogc_config
from .repository import OGCFeaturesRepository
from .models import (
    OGCLandingPage,
    OGCConformance,
    OGCCollection,
    OGCCollectionList,
    OGCFeatureCollection,
    OGCLink,
    OGCExtent,
    OGCSpatialExtent,
    OGCQueryParameters
)

# Setup logging
logger = logging.getLogger(__name__)


class OGCFeaturesService:
    """
    Business logic service for OGC Features API.

    Orchestrates operations between HTTP triggers and repository layer,
    ensuring OGC API - Features specification compliance.

    Responsibilities:
    - Generate OGC-compliant responses (landing page, conformance, collections)
    - Create pagination links (self, next, prev)
    - Validate query parameters
    - Format feature collections with metadata
    - Handle base URL detection and link generation
    """

    def __init__(self, config: Optional[OGCFeaturesConfig] = None):
        """
        Initialize service with configuration.

        Args:
            config: OGC Features configuration (uses singleton if not provided)
        """
        self.config = config or get_ogc_config()
        self.repository = OGCFeaturesRepository(self.config)
        logger.info("OGCFeaturesService initialized")

    # ========================================================================
    # LANDING PAGE & CONFORMANCE
    # ========================================================================

    def get_landing_page(self, base_url: str) -> OGCLandingPage:
        """
        Generate OGC API - Features landing page.

        The landing page provides links to key API resources and capabilities.

        Args:
            base_url: Base URL for the API (e.g., https://example.com)

        Returns:
            OGCLandingPage model with links to API resources
        """
        links = [
            OGCLink(
                href=f"{base_url}/api/features",
                rel="self",
                type="application/json",
                title="This document"
            ),
            OGCLink(
                href=f"{base_url}/api/features/conformance",
                rel="conformance",
                type="application/json",
                title="Conformance classes"
            ),
            OGCLink(
                href=f"{base_url}/api/features/collections",
                rel="data",
                type="application/json",
                title="Collections"
            ),
            OGCLink(
                href="https://docs.ogc.org/is/17-069r4/17-069r4.html",
                rel="service-desc",
                type="text/html",
                title="OGC API - Features specification"
            )
        ]

        return OGCLandingPage(
            title="OGC API - Features",
            description="OGC API - Features implementation for PostGIS vector data",
            links=links
        )

    def get_conformance(self) -> OGCConformance:
        """
        Get conformance classes implemented by this API.

        Returns:
            OGCConformance model with conformance URIs
        """
        return OGCConformance(
            conformsTo=[
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
            ]
        )

    # ========================================================================
    # COLLECTIONS
    # ========================================================================

    def list_collections(self, base_url: str) -> OGCCollectionList:
        """
        List all available collections (vector tables).

        Queries PostGIS for all tables in configured schema and returns
        OGC-compliant collection metadata.

        Args:
            base_url: Base URL for link generation

        Returns:
            OGCCollectionList with all collections and links
        """
        # Get collections from repository
        raw_collections = self.repository.list_collections()

        # Convert to OGC Collection models
        collections = []
        for raw_col in raw_collections:
            collection = self._build_collection_model(raw_col, base_url, include_extent=False)
            collections.append(collection)

        # Build response links
        links = [
            OGCLink(
                href=f"{base_url}/api/features/collections",
                rel="self",
                type="application/json",
                title="This document"
            ),
            OGCLink(
                href=f"{base_url}/api/features",
                rel="parent",
                type="application/json",
                title="Landing page"
            )
        ]

        logger.info(f"Listed {len(collections)} collections")

        return OGCCollectionList(
            collections=collections,
            links=links
        )

    def get_collection(self, collection_id: str, base_url: str) -> OGCCollection:
        """
        Get detailed metadata for a specific collection.

        Args:
            collection_id: Collection identifier (table name)
            base_url: Base URL for link generation

        Returns:
            OGCCollection model with full metadata including extent

        Raises:
            ValueError: If collection not found
        """
        # Get metadata from repository
        metadata = self.repository.get_collection_metadata(collection_id)

        # Build extent
        extent = None
        if metadata.get('bbox'):
            extent = OGCExtent(
                spatial=OGCSpatialExtent(
                    bbox=[metadata['bbox']],
                    crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                )
            )

        # Build links
        links = [
            OGCLink(
                href=f"{base_url}/api/features/collections/{collection_id}",
                rel="self",
                type="application/json",
                title="This collection"
            ),
            OGCLink(
                href=f"{base_url}/api/features/collections/{collection_id}/items",
                rel="items",
                type="application/geo+json",
                title="Items in this collection"
            ),
            OGCLink(
                href=f"{base_url}/api/features/collections",
                rel="parent",
                type="application/json",
                title="All collections"
            )
        ]

        # Determine storage CRS from SRID
        srid = metadata.get('srid', 4326)
        storage_crs = f"http://www.opengis.net/def/crs/EPSG/0/{srid}"

        collection = OGCCollection(
            id=collection_id,
            title=collection_id.replace("_", " ").title(),
            description=f"Vector features from {collection_id} table ({metadata.get('feature_count', 0)} features)",
            links=links,
            extent=extent,
            itemType="feature",
            crs=[
                "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                "http://www.opengis.net/def/crs/EPSG/0/4326"
            ],
            storageCrs=storage_crs
        )

        logger.info(f"Retrieved collection metadata for '{collection_id}'")

        return collection

    # ========================================================================
    # FEATURE QUERIES
    # ========================================================================

    def query_features(
        self,
        collection_id: str,
        params: OGCQueryParameters,
        base_url: str,
        property_filters: Optional[Dict[str, Any]] = None
    ) -> OGCFeatureCollection:
        """
        Query features from a collection with filters and pagination.

        This is the main feature query method that implements OGC API - Features
        items endpoint with full filtering, sorting, and optimization support.

        Args:
            collection_id: Collection identifier (table name)
            params: Validated query parameters (OGCQueryParameters model)
            base_url: Base URL for link generation
            property_filters: Additional attribute filters from query string

        Returns:
            OGCFeatureCollection with features, metadata, and pagination links

        Raises:
            ValueError: If collection not found or parameters invalid
        """
        # Extract datetime components
        datetime_range = params.datetime_range
        datetime_start = datetime_range[0] if datetime_range else None
        datetime_end = datetime_range[1] if datetime_range else None

        # Reconstruct datetime filter for repository
        if datetime_start and datetime_end:
            if datetime_start == datetime_end:
                datetime_filter = datetime_start  # Instant
            else:
                datetime_filter = f"{datetime_start}/{datetime_end}"  # Interval
        elif datetime_start:
            datetime_filter = f"{datetime_start}/.."  # Open end
        elif datetime_end:
            datetime_filter = f"../{datetime_end}"  # Open start
        else:
            datetime_filter = None

        # Query features from repository
        features, total_count = self.repository.query_features(
            collection_id=collection_id,
            limit=params.limit,
            offset=params.offset,
            bbox=params.bbox,
            datetime_filter=datetime_filter,
            datetime_property=params.datetime_property,
            property_filters=property_filters,
            sortby=params.sortby,
            precision=params.precision,
            simplify=params.simplify
        )

        # Generate links
        links = self._generate_pagination_links(
            base_url=base_url,
            collection_id=collection_id,
            params=params,
            property_filters=property_filters,
            current_count=len(features),
            total_count=total_count
        )

        # Build response
        feature_collection = OGCFeatureCollection(
            type="FeatureCollection",
            features=features,
            numberMatched=total_count,
            numberReturned=len(features),
            timeStamp=datetime.now(timezone.utc).isoformat(),
            links=links,
            crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        )

        logger.info(f"Query returned {len(features)}/{total_count} features from '{collection_id}'")

        return feature_collection

    def get_feature(
        self,
        collection_id: str,
        feature_id: str,
        precision: int,
        base_url: str
    ) -> Dict[str, Any]:
        """
        Get a single feature by ID.

        Args:
            collection_id: Collection identifier (table name)
            feature_id: Feature identifier (primary key value)
            precision: Coordinate precision
            base_url: Base URL for link generation

        Returns:
            GeoJSON feature dict

        Raises:
            ValueError: If feature not found
        """
        feature = self.repository.get_feature_by_id(
            collection_id=collection_id,
            feature_id=feature_id,
            precision=precision
        )

        if not feature:
            raise ValueError(f"Feature '{feature_id}' not found in collection '{collection_id}'")

        # Add links to feature
        feature['links'] = [
            {
                'href': f"{base_url}/api/features/collections/{collection_id}/items/{feature_id}",
                'rel': 'self',
                'type': 'application/geo+json',
                'title': 'This feature'
            },
            {
                'href': f"{base_url}/api/features/collections/{collection_id}",
                'rel': 'collection',
                'type': 'application/json',
                'title': 'Parent collection'
            }
        ]

        logger.info(f"Retrieved feature '{feature_id}' from '{collection_id}'")

        return feature

    # ========================================================================
    # LINK GENERATION
    # ========================================================================

    def _generate_pagination_links(
        self,
        base_url: str,
        collection_id: str,
        params: OGCQueryParameters,
        property_filters: Optional[Dict[str, Any]],
        current_count: int,
        total_count: int
    ) -> List[OGCLink]:
        """
        Generate pagination links (self, next, prev) for feature collection.

        Args:
            base_url: Base URL for links
            collection_id: Collection identifier
            params: Query parameters
            property_filters: Attribute filters
            current_count: Number of features in current response
            total_count: Total matching features

        Returns:
            List of OGCLink models
        """
        links = []

        # Build query parameters dict
        query_params = {
            'limit': params.limit,
            'offset': params.offset
        }

        if params.bbox:
            query_params['bbox'] = ','.join(str(x) for x in params.bbox)
        if params.datetime:
            query_params['datetime'] = params.datetime
        if params.datetime_property:
            query_params['datetime_property'] = params.datetime_property
        if params.sortby:
            query_params['sortby'] = params.sortby
        if params.precision != 6:
            query_params['precision'] = params.precision
        if params.simplify:
            query_params['simplify'] = params.simplify

        # Add property filters
        if property_filters:
            query_params.update(property_filters)

        # Self link
        self_url = f"{base_url}/api/features/collections/{collection_id}/items?{urlencode(query_params)}"
        links.append(OGCLink(
            href=self_url,
            rel="self",
            type="application/geo+json",
            title="This page"
        ))

        # Next link (if more features available)
        if params.offset + current_count < total_count:
            next_params = query_params.copy()
            next_params['offset'] = params.offset + params.limit
            next_url = f"{base_url}/api/features/collections/{collection_id}/items?{urlencode(next_params)}"
            links.append(OGCLink(
                href=next_url,
                rel="next",
                type="application/geo+json",
                title="Next page"
            ))

        # Previous link (if not on first page)
        if params.offset > 0:
            prev_params = query_params.copy()
            prev_params['offset'] = max(0, params.offset - params.limit)
            prev_url = f"{base_url}/api/features/collections/{collection_id}/items?{urlencode(prev_params)}"
            links.append(OGCLink(
                href=prev_url,
                rel="prev",
                type="application/geo+json",
                title="Previous page"
            ))

        # Collection link
        collection_url = f"{base_url}/api/features/collections/{collection_id}"
        links.append(OGCLink(
            href=collection_url,
            rel="collection",
            type="application/json",
            title="Parent collection"
        ))

        return links

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _build_collection_model(
        self,
        raw_collection: Dict[str, Any],
        base_url: str,
        include_extent: bool = False
    ) -> OGCCollection:
        """
        Build OGCCollection model from repository data.

        Args:
            raw_collection: Raw collection dict from repository
            base_url: Base URL for links
            include_extent: Whether to include extent (expensive for list view)

        Returns:
            OGCCollection model
        """
        collection_id = raw_collection['id']

        # Build links
        links = [
            OGCLink(
                href=f"{base_url}/api/features/collections/{collection_id}",
                rel="self",
                type="application/json",
                title="This collection"
            ),
            OGCLink(
                href=f"{base_url}/api/features/collections/{collection_id}/items",
                rel="items",
                type="application/geo+json",
                title="Items"
            )
        ]

        # Determine CRS from SRID
        srid = raw_collection.get('srid', 4326)
        storage_crs = f"http://www.opengis.net/def/crs/EPSG/0/{srid}"

        # Build collection
        collection = OGCCollection(
            id=collection_id,
            title=collection_id.replace("_", " ").title(),
            description=f"Vector features from {collection_id}",
            links=links,
            extent=None,  # Expensive to compute for list view
            itemType="feature",
            crs=[
                "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                "http://www.opengis.net/def/crs/EPSG/0/4326"
            ],
            storageCrs=storage_crs
        )

        return collection
