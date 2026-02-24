# ============================================================================
# CLAUDE CONTEXT - EXTERNAL SERVICE REGISTRY MODELS
# ============================================================================
# STATUS: Core - External geospatial service tracking and health monitoring
# PURPOSE: Register, detect, and monitor external geospatial web services
# CREATED: 22 JAN 2026
# LAST_REVIEWED: 22 JAN 2026
# ============================================================================
"""
External Service Registry Models.

Provides tracking for external geospatial services (ArcGIS, WMS, WFS, STAC, etc.)
with automatic type detection and health monitoring capabilities.

Key Features:
    - Service type auto-detection from URL probing
    - Health status tracking with rolling history
    - Response time monitoring and degradation detection
    - Capability extraction for service discovery

Service Types Supported:
    - ArcGIS REST (MapServer, FeatureServer, ImageServer)
    - OGC Legacy (WMS, WFS, WMTS)
    - OGC API (Features, Tiles)
    - STAC API (NASA, Microsoft Planetary Computer)
    - XYZ/TMS Tiles (OpenStreetMap, Mapbox style)
    - COG Endpoints (direct Cloud-Optimized GeoTIFF URLs)

Exports:
    ServiceType: Geospatial service type enum
    ServiceStatus: Health status enum
    ExternalService: Database model for service records

Dependencies:
    pydantic: Data validation
    hashlib: URL hashing for idempotent IDs
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, ClassVar
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer
import hashlib


# ============================================================================
# ENUMS
# ============================================================================

class ServiceType(str, Enum):
    """
    Supported external geospatial service types.

    Detection is performed by probing service-specific endpoints and
    analyzing responses for characteristic signatures.
    """
    # ArcGIS REST Services
    ARCGIS_MAPSERVER = "arcgis_mapserver"
    ARCGIS_FEATURESERVER = "arcgis_featureserver"
    ARCGIS_IMAGESERVER = "arcgis_imageserver"

    # OGC Legacy Services (XML-based)
    WMS = "wms"
    WFS = "wfs"
    WMTS = "wmts"

    # OGC API Services (JSON-based, modern)
    OGC_API_FEATURES = "ogc_api_features"
    OGC_API_TILES = "ogc_api_tiles"

    # STAC API
    STAC_API = "stac_api"

    # Tile Services
    XYZ_TILES = "xyz_tiles"
    TMS_TILES = "tms_tiles"

    # Direct Data Endpoints
    COG_ENDPOINT = "cog_endpoint"

    # Fallback
    GENERIC_REST = "generic_rest"
    UNKNOWN = "unknown"


class ServiceStatus(str, Enum):
    """
    Service health status.

    State transitions:
    - UNKNOWN -> ACTIVE (first successful check)
    - UNKNOWN -> OFFLINE (first failed check)
    - ACTIVE -> DEGRADED (slow response for 3+ checks)
    - ACTIVE -> OFFLINE (3 consecutive failures)
    - DEGRADED -> ACTIVE (response normalizes)
    - DEGRADED -> OFFLINE (3 consecutive failures)
    - OFFLINE -> ACTIVE (successful check)
    """
    ACTIVE = "active"              # Responding normally
    DEGRADED = "degraded"          # Slow or partial failures
    OFFLINE = "offline"            # Not responding
    UNKNOWN = "unknown"            # Not yet checked
    MAINTENANCE = "maintenance"    # Known maintenance window (user-set)


# ============================================================================
# DATABASE MODELS
# ============================================================================

class ExternalService(BaseModel):
    """
    External geospatial service database model.

    Tracks external services for health monitoring, discovery, and
    capability extraction. Used by platform to register and monitor
    third-party geospatial data sources.

    Auto-generates:
        CREATE TABLE app.external_services (
            service_id VARCHAR(32) PRIMARY KEY,
            url TEXT NOT NULL,
            service_type VARCHAR(50) NOT NULL DEFAULT 'unknown',
            detection_confidence FLOAT DEFAULT 0.0,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            tags JSONB DEFAULT '[]',
            status VARCHAR(20) DEFAULT 'unknown',
            enabled BOOLEAN DEFAULT true,
            detected_capabilities JSONB DEFAULT '{}',
            health_history JSONB DEFAULT '[]',
            last_response_ms INTEGER,
            avg_response_ms INTEGER,
            consecutive_failures INTEGER DEFAULT 0,
            last_failure_reason VARCHAR(500),
            check_interval_minutes INTEGER DEFAULT 60,
            last_check_at TIMESTAMPTZ,
            next_check_at TIMESTAMPTZ,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """

    model_config = ConfigDict()

    @field_serializer('last_check_at', 'next_check_at', 'created_at', 'updated_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # ========================================================================
    # SQL DDL METADATA (Used by PydanticToSQL generator)
    # ClassVar annotations required for Pydantic 2 compatibility
    # ========================================================================
    __sql_table_name: ClassVar[str] = "external_services"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["service_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"name": "idx_external_services_status", "columns": ["status"]},
        {"name": "idx_external_services_type", "columns": ["service_type"]},
        {"name": "idx_external_services_next_check", "columns": ["next_check_at"]},
        {"name": "idx_external_services_enabled", "columns": ["enabled"],
         "partial_where": "enabled = true"},
        {"name": "idx_external_services_created_at", "columns": ["created_at"],
         "descending": True},
        {"name": "idx_external_services_capabilities", "columns": ["detected_capabilities"],
         "type": "gin"},
    ]

    # ========================================================================
    # PRIMARY KEY (Deterministic from URL)
    # ========================================================================
    service_id: str = Field(
        ...,
        max_length=32,
        description="SHA256(url)[:32] - idempotent identifier for deduplication"
    )

    # ========================================================================
    # SERVICE URL AND TYPE
    # ========================================================================
    url: str = Field(
        ...,
        description="Service endpoint URL"
    )
    service_type: ServiceType = Field(
        default=ServiceType.UNKNOWN,
        description="Detected service type"
    )
    detection_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of type detection (0.0-1.0)"
    )

    # ========================================================================
    # USER-PROVIDED METADATA
    # ========================================================================
    name: str = Field(
        ...,
        max_length=255,
        description="Human-readable service name"
    )
    description: Optional[str] = Field(
        None,
        description="Service description"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Tags for categorization (e.g., ['hydrology', 'usgs', 'federal'])"
    )

    # ========================================================================
    # STATUS TRACKING
    # ========================================================================
    status: ServiceStatus = Field(
        default=ServiceStatus.UNKNOWN,
        description="Current health status"
    )
    enabled: bool = Field(
        default=True,
        description="Whether health checks are enabled for this service"
    )

    # ========================================================================
    # DETECTED CAPABILITIES (From Probing)
    # ========================================================================
    detected_capabilities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Capabilities extracted during detection (layers, formats, CRS, bounds, etc.)"
    )

    # ========================================================================
    # HEALTH HISTORY (Rolling Window)
    # ========================================================================
    health_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Recent health check results (last 10 checks)"
    )

    # ========================================================================
    # RESPONSE TIME TRACKING
    # ========================================================================
    last_response_ms: Optional[int] = Field(
        None,
        description="Last response time in milliseconds"
    )
    avg_response_ms: Optional[int] = Field(
        None,
        description="Rolling average response time in milliseconds"
    )

    # ========================================================================
    # FAILURE TRACKING
    # ========================================================================
    consecutive_failures: int = Field(
        default=0,
        description="Count of consecutive health check failures"
    )
    last_failure_reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Reason for last failure (timeout, connection refused, etc.)"
    )

    # ========================================================================
    # CHECK SCHEDULING
    # ========================================================================
    check_interval_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Health check interval in minutes (5 min to 24 hours)"
    )
    last_check_at: Optional[datetime] = Field(
        None,
        description="Timestamp of last health check"
    )
    next_check_at: Optional[datetime] = Field(
        None,
        description="Timestamp of next scheduled check"
    )

    # ========================================================================
    # ADDITIONAL METADATA
    # ========================================================================
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (contact, documentation_url, etc.)"
    )

    # ========================================================================
    # TIMESTAMPS
    # ========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when service was registered"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of last update"
    )

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    @staticmethod
    def generate_service_id(url: str) -> str:
        """
        Generate deterministic service_id from URL.

        Uses SHA256 hash truncated to 32 chars for reasonable uniqueness
        while keeping IDs manageable.

        Args:
            url: Service endpoint URL

        Returns:
            32-character hex string
        """
        return hashlib.sha256(url.encode()).hexdigest()[:32]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'service_id': self.service_id,
            'url': self.url,
            'service_type': self.service_type.value if isinstance(self.service_type, ServiceType) else self.service_type,
            'detection_confidence': self.detection_confidence,
            'name': self.name,
            'description': self.description,
            'tags': self.tags,
            'status': self.status.value if isinstance(self.status, ServiceStatus) else self.status,
            'enabled': self.enabled,
            'detected_capabilities': self.detected_capabilities,
            'health_history': self.health_history,
            'last_response_ms': self.last_response_ms,
            'avg_response_ms': self.avg_response_ms,
            'consecutive_failures': self.consecutive_failures,
            'last_failure_reason': self.last_failure_reason,
            'check_interval_minutes': self.check_interval_minutes,
            'last_check_at': self.last_check_at.isoformat() if self.last_check_at else None,
            'next_check_at': self.next_check_at.isoformat() if self.next_check_at else None,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def add_health_check_result(
        self,
        success: bool,
        response_ms: Optional[int],
        error: Optional[str] = None
    ) -> None:
        """
        Add a health check result to the rolling history.

        Maintains last 10 checks and updates response time averages.

        Args:
            success: Whether the check was successful
            response_ms: Response time in milliseconds (None if failed)
            error: Error message if failed
        """
        result = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'success': success,
            'response_ms': response_ms,
            'error': error
        }

        # Add to history (keep last 10)
        self.health_history.append(result)
        if len(self.health_history) > 10:
            self.health_history = self.health_history[-10:]

        # Update response time tracking
        if success and response_ms is not None:
            self.last_response_ms = response_ms
            # Simple rolling average of successful checks
            successful_times = [
                h['response_ms'] for h in self.health_history
                if h['success'] and h['response_ms'] is not None
            ]
            if successful_times:
                self.avg_response_ms = int(sum(successful_times) / len(successful_times))

        # Update timestamps
        self.last_check_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


# ============================================================================
# SCHEMA METADATA - Used by PydanticToSQL generator
# ============================================================================

EXTERNAL_SERVICE_TABLE_NAMES = {
    'ExternalService': 'external_services'
}

EXTERNAL_SERVICE_PRIMARY_KEYS = {
    'ExternalService': ['service_id']
}

EXTERNAL_SERVICE_INDEXES = {
    'ExternalService': [
        ('status',),
        ('service_type',),
        ('next_check_at',),
        ('enabled',),
        ('created_at',),
    ]
}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ServiceType',
    'ServiceStatus',
    'ExternalService',
    'EXTERNAL_SERVICE_TABLE_NAMES',
    'EXTERNAL_SERVICE_PRIMARY_KEYS',
    'EXTERNAL_SERVICE_INDEXES',
]
