# ============================================================================
# ETL TRACKING MODELS - INTERNAL APP SCHEMA ONLY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Models for internal ETL tracking (never replicated externally)
# PURPOSE: Pydantic models for app.vector_etl_tracking and related ETL tables
# LAST_REVIEWED: 21 JAN 2026
# EXPORTS: VectorEtlTracking
# DEPENDENCIES: pydantic
# ============================================================================
"""
ETL Tracking Models - Internal App Schema Only.

These models define ETL traceability tables that exist ONLY in the internal
app schema. They are NEVER replicated to external databases.

CRITICAL DESIGN PRINCIPLE:
    ETL tracking contains internal infrastructure details:
    - CoreMachine job IDs
    - Azure Blob source paths
    - Processing timestamps
    - Source CRS before transformation

    These are essential for debugging and audit within the platform,
    but should never be exposed to end-users or external services.

Architecture (21 JAN 2026):
    ┌─────────────────────────────────────────────────────────────────┐
    │                    INTERNAL DATABASE                            │
    ├─────────────────────────────────────────────────────────────────┤
    │  app schema (NEVER replicated)     geo schema (replicated)      │
    │  ├── jobs                          ├── table_catalog            │
    │  ├── tasks                         ├── brazilian_cities         │
    │  ├── vector_etl_tracking ──────────┼──► FK to table_name       │
    │  │   • etl_job_id                  │                            │
    │  │   • source_file                 │                            │
    │  │   • source_crs                  │                            │
    │  │   • processing_timestamp        │                            │
    │  └── (internal only)               └── (replicable)             │
    └─────────────────────────────────────────────────────────────────┘

Relationship:
    app.vector_etl_tracking.table_name → geo.table_catalog.table_name
    (Foreign key linking ETL history to service layer metadata)

Usage:
    from core.models.etl_tracking import VectorEtlTracking

    # Create from CoreMachine job result
    tracking = VectorEtlTracking(
        table_name="brazilian_cities",
        etl_job_id="abc123...",
        source_file="uploads/brazil.gpkg",
        source_format="gpkg",
        source_crs="EPSG:4674"
    )

    # Generate DDL
    from core.schema import PydanticToSQL
    ddl = PydanticToSQL.generate_create_table(VectorEtlTracking)

Created: 21 JAN 2026
Epic: E7 Infrastructure as Code → F7.IaC Separation of Concerns
Story: S7.IaC.2 Create ETL Tracking Pydantic Models
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class EtlStatus(str, Enum):
    """
    ETL processing status for tracking table.
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"  # Replaced by newer ETL run


class VectorEtlTracking(BaseModel):
    """
    ETL traceability record for vector datasets.

    This model maps to app.vector_etl_tracking and contains ONLY internal
    ETL processing fields. Service layer fields are in geo.table_catalog.

    Primary Key: (table_name, etl_job_id)
        Composite key allows multiple ETL runs per table (re-processing history)

    Foreign Key: table_name → geo.table_catalog.table_name

    NEVER REPLICATED:
        This table stays in the internal database only. External services
        (TiPG, etc.) never see this data. ADF only replicates geo schema.

    DDL Annotations:
        The __sql_* class attributes guide DDL generation via PydanticToSQL.
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints (ClassVar = not a model field)
    __sql_table_name: ClassVar[str] = "vector_etl_tracking"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["table_name", "etl_job_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "table_name": "geo.table_catalog(table_name)"
    }
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["table_name"], "name": "idx_vector_etl_table_name"},
        {"columns": ["etl_job_id"], "name": "idx_vector_etl_job_id"},
        {"columns": ["status"], "name": "idx_vector_etl_status"},
        {"columns": ["created_at"], "name": "idx_vector_etl_created", "descending": True},
        {"columns": ["source_hash"], "name": "idx_vector_etl_hash", "partial_where": "source_hash IS NOT NULL"},
    ]

    # ==========================================================================
    # IDENTITY (Composite Primary Key)
    # ==========================================================================
    table_name: str = Field(
        ...,
        max_length=255,
        description="PostGIS table name (FK to geo.table_catalog)"
    )

    etl_job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID that processed this dataset"
    )

    # ==========================================================================
    # SOURCE TRACEABILITY (Where did the data come from?)
    # ==========================================================================
    source_file: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Original source filename (Azure Blob path)"
    )

    source_format: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Source file format (shp, gpkg, geojson, csv, etc.)"
    )

    source_crs: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Original CRS before reprojection (e.g., EPSG:4674)"
    )

    source_size_bytes: Optional[int] = Field(
        default=None,
        description="Original source file size in bytes"
    )

    source_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="SHA256 hash of source file for deduplication"
    )

    # ==========================================================================
    # PROCESSING DETAILS (What happened during ETL?)
    # ==========================================================================
    status: EtlStatus = Field(
        default=EtlStatus.PENDING,
        description="ETL processing status"
    )

    processing_started_at: Optional[datetime] = Field(
        default=None,
        description="When ETL processing started"
    )

    processing_completed_at: Optional[datetime] = Field(
        default=None,
        description="When ETL processing completed"
    )

    processing_duration_ms: Optional[int] = Field(
        default=None,
        description="Processing duration in milliseconds"
    )

    # ==========================================================================
    # TRANSFORMATION DETAILS (What transformations were applied?)
    # ==========================================================================
    target_crs: str = Field(
        default="EPSG:4326",
        max_length=100,
        description="Target CRS after reprojection"
    )

    rows_read: Optional[int] = Field(
        default=None,
        description="Number of rows read from source"
    )

    rows_written: Optional[int] = Field(
        default=None,
        description="Number of rows written to PostGIS"
    )

    rows_skipped: Optional[int] = Field(
        default=None,
        description="Number of rows skipped (invalid geometry, etc.)"
    )

    geometry_repairs: Optional[int] = Field(
        default=None,
        description="Number of geometries repaired (ST_MakeValid)"
    )

    # ==========================================================================
    # PROCESSING SOFTWARE
    # ==========================================================================
    processing_software: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Processing software name (e.g., ogr2ogr, geopandas)"
    )

    processing_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Processing software version"
    )

    pipeline_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Platform pipeline version (from config.__version__)"
    )

    # ==========================================================================
    # ERROR TRACKING
    # ==========================================================================
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if processing failed"
    )

    error_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed error information (stored as JSONB)"
    )

    # ==========================================================================
    # AUDIT METADATA
    # ==========================================================================
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this tracking record was created"
    )

    created_by: Optional[str] = Field(
        default=None,
        max_length=255,
        description="User or system that initiated the ETL"
    )

    # ==========================================================================
    # FACTORY METHODS
    # ==========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "VectorEtlTracking":
        """
        Create VectorEtlTracking from database row.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            VectorEtlTracking instance
        """
        return cls(
            table_name=row.get('table_name'),
            etl_job_id=row.get('etl_job_id'),
            source_file=row.get('source_file'),
            source_format=row.get('source_format'),
            source_crs=row.get('source_crs'),
            source_size_bytes=row.get('source_size_bytes'),
            source_hash=row.get('source_hash'),
            status=row.get('status', EtlStatus.PENDING),
            processing_started_at=row.get('processing_started_at'),
            processing_completed_at=row.get('processing_completed_at'),
            processing_duration_ms=row.get('processing_duration_ms'),
            target_crs=row.get('target_crs', 'EPSG:4326'),
            rows_read=row.get('rows_read'),
            rows_written=row.get('rows_written'),
            rows_skipped=row.get('rows_skipped'),
            geometry_repairs=row.get('geometry_repairs'),
            processing_software=row.get('processing_software'),
            processing_version=row.get('processing_version'),
            pipeline_version=row.get('pipeline_version'),
            error_message=row.get('error_message'),
            error_details=row.get('error_details'),
            created_at=row.get('created_at', datetime.now(timezone.utc)),
            created_by=row.get('created_by')
        )

    @classmethod
    def from_vector_metadata(
        cls,
        metadata: "VectorMetadata",
        additional_fields: Optional[Dict[str, Any]] = None
    ) -> "VectorEtlTracking":
        """
        Create VectorEtlTracking from VectorMetadata (ETL fields only).

        This is the primary method for splitting unified metadata into
        service layer (GeoTableCatalog) and ETL layer (VectorEtlTracking).

        Args:
            metadata: Full VectorMetadata instance
            additional_fields: Optional dict with fields not in VectorMetadata
                              (e.g., rows_read, processing_duration_ms)

        Returns:
            VectorEtlTracking with ETL fields only
        """
        # Import here to avoid circular dependency
        from .unified_metadata import VectorMetadata

        additional = additional_fields or {}

        return cls(
            table_name=metadata.id,
            etl_job_id=metadata.etl_job_id or additional.get('etl_job_id', 'unknown'),
            source_file=metadata.source_file,
            source_format=metadata.source_format,
            source_crs=metadata.source_crs,
            source_size_bytes=additional.get('source_size_bytes'),
            source_hash=additional.get('source_hash'),
            status=additional.get('status', EtlStatus.COMPLETED),
            processing_started_at=additional.get('processing_started_at'),
            processing_completed_at=additional.get('processing_completed_at', datetime.now(timezone.utc)),
            processing_duration_ms=additional.get('processing_duration_ms'),
            target_crs=additional.get('target_crs', 'EPSG:4326'),
            rows_read=additional.get('rows_read'),
            rows_written=metadata.feature_count,
            rows_skipped=additional.get('rows_skipped'),
            geometry_repairs=additional.get('geometry_repairs'),
            processing_software=metadata.processing_software.get('name') if metadata.processing_software else None,
            processing_version=metadata.processing_software.get('version') if metadata.processing_software else None,
            pipeline_version=additional.get('pipeline_version'),
            error_message=additional.get('error_message'),
            error_details=additional.get('error_details'),
            created_at=metadata.created_at or datetime.now(timezone.utc),
            created_by=additional.get('created_by')
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database insertion.

        Returns:
            Dict suitable for INSERT/UPDATE operations
        """
        return self.model_dump(exclude_none=False, by_alias=True)

    def mark_started(self) -> None:
        """Mark ETL processing as started (mutates self)."""
        self.status = EtlStatus.PROCESSING
        self.processing_started_at = datetime.now(timezone.utc)

    def mark_completed(self, rows_written: int, duration_ms: Optional[int] = None) -> None:
        """
        Mark ETL processing as completed (mutates self).

        Args:
            rows_written: Number of rows successfully written
            duration_ms: Optional processing duration
        """
        self.status = EtlStatus.COMPLETED
        self.processing_completed_at = datetime.now(timezone.utc)
        self.rows_written = rows_written
        if duration_ms:
            self.processing_duration_ms = duration_ms
        elif self.processing_started_at:
            delta = self.processing_completed_at - self.processing_started_at
            self.processing_duration_ms = int(delta.total_seconds() * 1000)

    def mark_failed(self, error_message: str, error_details: Optional[Dict] = None) -> None:
        """
        Mark ETL processing as failed (mutates self).

        Args:
            error_message: Human-readable error message
            error_details: Optional detailed error information
        """
        self.status = EtlStatus.FAILED
        self.processing_completed_at = datetime.now(timezone.utc)
        self.error_message = error_message
        self.error_details = error_details
        if self.processing_started_at:
            delta = self.processing_completed_at - self.processing_started_at
            self.processing_duration_ms = int(delta.total_seconds() * 1000)


class RasterEtlTracking(BaseModel):
    """
    ETL traceability record for raster datasets (COGs).

    This model maps to app.raster_etl_tracking and contains ONLY internal
    ETL processing fields. Similar to VectorEtlTracking but for raster data.

    Primary Key: (cog_path, etl_job_id)

    PLACEHOLDER: Full implementation pending E2 Raster Pipeline completion.
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore'
    )

    # DDL generation hints (ClassVar = not a model field)
    __sql_table_name: ClassVar[str] = "raster_etl_tracking"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["cog_path", "etl_job_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["etl_job_id"], "name": "idx_raster_etl_job_id"},
        {"columns": ["status"], "name": "idx_raster_etl_status"},
        {"columns": ["created_at"], "name": "idx_raster_etl_created", "descending": True},
    ]

    # Identity
    cog_path: str = Field(
        ...,
        max_length=500,
        description="COG Azure Blob path"
    )

    etl_job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID that created this COG"
    )

    # Source traceability
    source_file: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Original source raster file"
    )

    source_format: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Source format (tif, nc, grib, etc.)"
    )

    source_crs: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Original CRS"
    )

    # Processing details
    status: EtlStatus = Field(
        default=EtlStatus.PENDING,
        description="ETL processing status"
    )

    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None

    # COG generation details
    compression: Optional[str] = Field(
        default=None,
        max_length=50,
        description="COG compression (deflate, lzw, zstd)"
    )

    tile_size: Optional[int] = Field(
        default=None,
        description="COG tile size"
    )

    cog_size_bytes: Optional[int] = Field(
        default=None,
        description="Generated COG file size"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )
