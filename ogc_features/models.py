"""
OGC API - Features Pydantic models.

Response models implementing OGC API - Features Core 1.0 specification.

Exports:
    OGCLink: Web linking model for resource relationships
    OGCLandingPage: Landing page response model
    OGCConformance: Conformance classes declaration model
    OGCCollection: Collection metadata model
    OGCFeatureCollection: GeoJSON feature collection response model
"""

from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class OGCLink(BaseModel):
    """
    OGC API Link object (RFC 8288 Web Linking).

    Links provide relationships between resources in the API.
    """
    href: str = Field(
        description="URL of the linked resource"
    )
    rel: str = Field(
        description="Link relation type (self, alternate, next, prev, etc.)"
    )
    type: Optional[str] = Field(
        default=None,
        description="Media type of the linked resource"
    )
    title: Optional[str] = Field(
        default=None,
        description="Human-readable title for the link"
    )
    hreflang: Optional[str] = Field(
        default=None,
        description="Language of the linked resource"
    )


class OGCLandingPage(BaseModel):
    """
    OGC API - Features Landing Page (root endpoint).

    The landing page provides links to API capabilities and resources.
    """
    title: str = Field(
        description="Title of the API"
    )
    description: Optional[str] = Field(
        default=None,
        description="Description of the API"
    )
    links: List[OGCLink] = Field(
        description="Links to API resources (conformance, collections, etc.)"
    )


class OGCConformance(BaseModel):
    """
    OGC API - Features Conformance Declaration.

    Lists the conformance classes implemented by this API.
    """
    conformsTo: List[str] = Field(
        description="List of conformance class URIs",
        default=[
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
        ]
    )


class OGCSpatialExtent(BaseModel):
    """Spatial extent of a collection (bounding box)."""
    bbox: List[List[float]] = Field(
        description="Bounding boxes (minx, miny, maxx, maxy) in CRS order"
    )
    crs: str = Field(
        default="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        description="Coordinate reference system"
    )


class OGCTemporalExtent(BaseModel):
    """Temporal extent of a collection."""
    interval: List[List[Optional[str]]] = Field(
        description="Temporal intervals (start, end) in ISO 8601 format"
    )
    trs: str = Field(
        default="http://www.opengis.net/def/uom/ISO-8601/0/Gregorian",
        description="Temporal reference system"
    )


class OGCExtent(BaseModel):
    """
    Spatial and temporal extent of a collection.
    """
    spatial: Optional[OGCSpatialExtent] = None
    temporal: Optional[OGCTemporalExtent] = None


class OGCCollection(BaseModel):
    """
    OGC API - Features Collection metadata.

    Represents a vector dataset (PostGIS table) served by the API.
    """
    id: str = Field(
        description="Unique identifier for the collection (table name)"
    )
    title: str = Field(
        description="Human-readable title"
    )
    description: Optional[str] = Field(
        default=None,
        description="Description of the collection"
    )
    links: List[OGCLink] = Field(
        description="Links to collection resources (items, metadata, etc.)"
    )
    extent: Optional[OGCExtent] = Field(
        default=None,
        description="Spatial and temporal extent"
    )
    itemType: Literal["feature"] = Field(
        default="feature",
        description="Type of items in collection"
    )
    crs: List[str] = Field(
        default=[
            "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            "http://www.opengis.net/def/crs/EPSG/0/4326"
        ],
        description="Supported coordinate reference systems"
    )
    storageCrs: Optional[str] = Field(
        default=None,
        description="Native storage CRS"
    )
    # =========================================================================
    # CUSTOM METADATA PROPERTIES (06 DEC 2025)
    # =========================================================================
    # OGC API - Features allows additional properties beyond the core spec.
    # This field contains ETL traceability and STAC linkage metadata from
    # geo.table_metadata registry (the source of truth for vector metadata).
    #
    # Properties include:
    #   - etl:job_id: CoreMachine job ID that created this table
    #   - source:file: Original filename (e.g., "countries.shp")
    #   - source:format: File format (shp, gpkg, geojson, csv, etc.)
    #   - source:crs: Original CRS before reprojection to EPSG:4326
    #   - stac:item_id: STAC item ID (if cataloged)
    #   - stac:collection_id: STAC collection ID (if cataloged)
    #   - created: Timestamp when table was created
    #   - updated: Timestamp when metadata was last updated
    # =========================================================================
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom collection metadata (ETL traceability, STAC linkage)"
    )


class OGCCollectionList(BaseModel):
    """
    OGC API - Features Collections list response.
    """
    collections: List[OGCCollection] = Field(
        description="List of available collections"
    )
    links: List[OGCLink] = Field(
        description="Links to related resources"
    )


class OGCFeatureCollection(BaseModel):
    """
    OGC API - Features FeatureCollection response (GeoJSON).

    Represents a collection of features returned from a query.
    """
    type: Literal["FeatureCollection"] = Field(
        default="FeatureCollection",
        description="GeoJSON type"
    )
    features: List[Dict[str, Any]] = Field(
        description="Array of GeoJSON Feature objects"
    )
    numberMatched: Optional[int] = Field(
        default=None,
        description="Total number of features matching the query"
    )
    numberReturned: int = Field(
        description="Number of features in this response"
    )
    timeStamp: str = Field(
        description="Timestamp of the response (ISO 8601)"
    )
    links: List[OGCLink] = Field(
        description="Links to related resources (self, next, prev, etc.)"
    )
    crs: Optional[str] = Field(
        default=None,
        description="Coordinate reference system of features"
    )


class OGCQueryParameters(BaseModel):
    """
    Query parameters for OGC Features items endpoint.

    Validated query parameters for feature queries with temporal, attribute,
    and sorting support.
    """
    # Pagination
    limit: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum number of features to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of features to skip (pagination)"
    )

    # Spatial filtering
    bbox: Optional[List[float]] = Field(
        default=None,
        description="Bounding box filter (minx,miny,maxx,maxy) in EPSG:4326"
    )

    # Temporal filtering (flexible column names)
    datetime: Optional[str] = Field(
        default=None,
        description="Temporal filter (ISO 8601 interval 'start/end' or instant 'YYYY-MM-DD')"
    )
    datetime_property: Optional[str] = Field(
        default=None,
        description="Datetime column name (optional - auto-detects if not specified)"
    )

    # Attribute filtering (simple key=value, parsed separately from query string)
    # property_filters will be populated by trigger layer from query params

    # Sorting
    sortby: Optional[str] = Field(
        default=None,
        description="OGC sortby syntax: +prop1,-prop2 (+ = ASC, - = DESC)"
    )

    # Geometry optimization
    precision: int = Field(
        default=6,
        ge=0,
        le=15,
        description="Coordinate precision (decimal places for quantization)"
    )
    simplify: Optional[float] = Field(
        default=None,
        ge=0,
        description="Simplification tolerance in meters (ST_Simplify)"
    )

    # CRS (Phase 1: EPSG:4326 only)
    crs: str = Field(
        default="EPSG:4326",
        description="Output coordinate reference system (EPSG:4326 only in Phase 1)"
    )

    @property
    def bbox_wkt(self) -> Optional[str]:
        """Convert bbox to WKT envelope for PostGIS."""
        if not self.bbox or len(self.bbox) != 4:
            return None
        minx, miny, maxx, maxy = self.bbox
        return f"SRID=4326;POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))"

    @property
    def datetime_range(self) -> Optional[tuple[Optional[str], Optional[str]]]:
        """
        Parse datetime parameter into (start, end) tuple.

        Returns:
            Tuple of (start_datetime, end_datetime) or None
            - Instant: ("2024-01-01", "2024-01-01")
            - Interval: ("2024-01-01", "2024-12-31")
            - Open start: (None, "2024-12-31")
            - Open end: ("2024-01-01", None)
        """
        if not self.datetime:
            return None

        # ISO 8601 interval: "start/end"
        if "/" in self.datetime:
            parts = self.datetime.split("/")
            start = parts[0] if parts[0] and parts[0] != ".." else None
            end = parts[1] if parts[1] and parts[1] != ".." else None
            return (start, end)

        # ISO 8601 instant: treat as exact day
        return (self.datetime, self.datetime)

    @property
    def sort_columns(self) -> Optional[List[tuple[str, str]]]:
        """
        Parse sortby parameter into list of (column, direction) tuples.

        Returns:
            List of (column_name, direction) where direction is 'ASC' or 'DESC'
            Example: "+year,-population" -> [("year", "ASC"), ("population", "DESC")]
        """
        if not self.sortby:
            return None

        result = []
        for item in self.sortby.split(","):
            item = item.strip()
            if item.startswith("+"):
                result.append((item[1:], "ASC"))
            elif item.startswith("-"):
                result.append((item[1:], "DESC"))
            else:
                # Default to ASC if no prefix
                result.append((item, "ASC"))

        return result if result else None
