# ============================================================================
# EXTERNAL REFERENCES MODELS
# ============================================================================
# STATUS: Core - Cross-type external system linkage
# PURPOSE: DDH and other external system references for datasets
# LAST_REVIEWED: 09 JAN 2026
# REVIEW_STATUS: Check 8 N/A - no infrastructure config
# ============================================================================
"""
External References Models.

Provides models for linking internal datasets to external catalog systems
like DDH (Data Hub Dashboard). These references are stored in app.dataset_refs
and apply across all data types (vector, raster, zarr).

Architecture Decision (from METADATA.md):
    DDH linkage is:
    - Cross-cutting (applies to vector, raster, zarr)
    - Critical for integration (needs indexing)
    - Structured (known schema, not random properties)

    Therefore: Create app.dataset_refs table with typed columns for DDH IDs
    plus JSONB for future systems.

Flow:
    PlatformRequest                    app.dataset_refs
    ├── dataset_id     ─────────────► ddh_dataset_id
    ├── resource_id    ─────────────► ddh_resource_id
    ├── version_id     ─────────────► ddh_version_id
    └── source_url     ─────────────► dataset_id + data_type

Exports:
    DataType: Data type enumeration
    DDHRefs: DDH-specific reference fields
    ExternalRefs: Container for all external system references
    DatasetRef: Complete dataset reference record

Created: 09 JAN 2026
Epic: E7 Pipeline Infrastructure → F7.8 Unified Metadata Architecture
"""

from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# DATA TYPE ENUM
# =============================================================================

class DataType(str, Enum):
    """
    Dataset type enumeration.

    Used to distinguish between different data storage formats
    in the cross-type app.dataset_refs table.
    """
    VECTOR = "vector"   # PostGIS tables (geo schema)
    RASTER = "raster"   # COG files (Azure blob storage)
    ZARR = "zarr"       # Zarr arrays (Azure blob storage)


# =============================================================================
# DDH REFERENCES MODEL
# =============================================================================

class DDHRefs(BaseModel):
    """
    DDH (Data Hub Dashboard) external system references.

    These identifiers link our internal datasets back to the DDH platform
    that requested their creation via the Platform API.

    All fields are optional because:
    1. Datasets can be created without going through DDH
    2. DDH may not provide all identifiers for every request

    Example:
        refs = DDHRefs(
            dataset_id="flood-hazard-data",
            resource_id="res-001",
            version_id="v1.0"
        )
    """
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: Optional[str] = Field(
        default=None,
        description="DDH dataset identifier"
    )
    resource_id: Optional[str] = Field(
        default=None,
        description="DDH resource identifier"
    )
    version_id: Optional[str] = Field(
        default=None,
        description="DDH version identifier"
    )

    def is_linked(self) -> bool:
        """Check if any DDH reference is set."""
        return any([self.dataset_id, self.resource_id, self.version_id])

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, excluding None values."""
        result = {}
        if self.dataset_id:
            result["dataset_id"] = self.dataset_id
        if self.resource_id:
            result["resource_id"] = self.resource_id
        if self.version_id:
            result["version_id"] = self.version_id
        return result


# =============================================================================
# EXTERNAL REFERENCES CONTAINER
# =============================================================================

class ExternalRefs(BaseModel):
    """
    Container for all external system references.

    Provides a single model that can hold references to multiple
    external catalog systems. Currently supports DDH, with extension
    points for future systems.

    Example:
        refs = ExternalRefs(
            ddh=DDHRefs(dataset_id="flood-data")
        )
    """
    ddh: Optional[DDHRefs] = Field(
        default=None,
        description="DDH platform references"
    )

    # Extension point for future external systems
    # Example: arcgis, geonode, etc.
    other_refs: Dict[str, Any] = Field(
        default_factory=dict,
        description="References to other external systems (future use)"
    )

    def is_linked_to_any(self) -> bool:
        """Check if any external system reference is set."""
        if self.ddh and self.ddh.is_linked():
            return True
        return bool(self.other_refs)


# =============================================================================
# DATASET REFERENCE RECORD
# =============================================================================

class DatasetRef(BaseModel):
    """
    Complete dataset reference record.

    Maps to app.dataset_refs table. Links internal dataset identifiers
    to external system references.

    This model is cross-type - it can reference vector, raster, or zarr
    datasets using the data_type field to distinguish.

    Example:
        ref = DatasetRef(
            dataset_id="admin_boundaries_chile",
            data_type=DataType.VECTOR,
            ddh_dataset_id="flood-boundaries",
            ddh_resource_id="res-001"
        )
    """
    model_config = ConfigDict(use_enum_values=True)

    # Internal identity
    dataset_id: str = Field(
        ...,
        description="Our internal dataset identifier (table name, blob path, etc.)"
    )
    data_type: DataType = Field(
        ...,
        description="Dataset type (vector, raster, zarr)"
    )

    # DDH references (typed for efficient indexing)
    ddh_dataset_id: Optional[str] = Field(
        default=None,
        description="DDH dataset identifier"
    )
    ddh_resource_id: Optional[str] = Field(
        default=None,
        description="DDH resource identifier"
    )
    ddh_version_id: Optional[str] = Field(
        default=None,
        description="DDH version identifier"
    )

    # Other external systems (JSONB in database)
    other_refs: Dict[str, Any] = Field(
        default_factory=dict,
        description="References to other external systems"
    )

    # Timestamps
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the reference was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="When the reference was last updated"
    )

    @classmethod
    def from_platform_request(
        cls,
        dataset_id: str,
        data_type: DataType,
        platform_dataset_id: Optional[str] = None,
        platform_resource_id: Optional[str] = None,
        platform_version_id: Optional[str] = None
    ) -> "DatasetRef":
        """
        Create DatasetRef from Platform API request parameters.

        Args:
            dataset_id: Internal dataset identifier
            data_type: Dataset type
            platform_dataset_id: DDH dataset_id from PlatformRequest
            platform_resource_id: DDH resource_id from PlatformRequest
            platform_version_id: DDH version_id from PlatformRequest

        Returns:
            DatasetRef instance
        """
        return cls(
            dataset_id=dataset_id,
            data_type=data_type,
            ddh_dataset_id=platform_dataset_id,
            ddh_resource_id=platform_resource_id,
            ddh_version_id=platform_version_id
        )

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "DatasetRef":
        """
        Create DatasetRef from app.dataset_refs database row.

        Args:
            row: Database row as dict

        Returns:
            DatasetRef instance
        """
        return cls(
            dataset_id=row['dataset_id'],
            data_type=DataType(row['data_type']),
            ddh_dataset_id=row.get('ddh_dataset_id'),
            ddh_resource_id=row.get('ddh_resource_id'),
            ddh_version_id=row.get('ddh_version_id'),
            other_refs=row.get('other_refs') or {},
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    def get_ddh_refs(self) -> DDHRefs:
        """Get DDH references as DDHRefs model."""
        return DDHRefs(
            dataset_id=self.ddh_dataset_id,
            resource_id=self.ddh_resource_id,
            version_id=self.ddh_version_id
        )

    def get_external_refs(self) -> ExternalRefs:
        """Get all external references as ExternalRefs model."""
        return ExternalRefs(
            ddh=self.get_ddh_refs(),
            other_refs=self.other_refs
        )

    def is_linked_to_ddh(self) -> bool:
        """Check if any DDH reference is set."""
        return any([
            self.ddh_dataset_id,
            self.ddh_resource_id,
            self.ddh_version_id
        ])


# =============================================================================
# DATABASE RECORD MODEL (for SQL generation)
# =============================================================================

class DatasetRefRecord(BaseModel):
    """
    Database record model for app.dataset_refs table.

    This model is used by sql_generator.py to create the database table.
    It has proper max_length constraints for DDL generation.

    Table: app.dataset_refs
    Primary Key: (dataset_id, data_type)
    """
    model_config = ConfigDict(use_enum_values=True)

    # Primary Key (composite)
    dataset_id: str = Field(
        ...,
        max_length=255,
        description="Internal dataset identifier (table name, blob path, etc.)"
    )
    data_type: str = Field(
        ...,
        max_length=20,
        description="Dataset type: vector, raster, zarr"
    )

    # DDH References (indexed for efficient lookup)
    ddh_dataset_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="DDH dataset identifier"
    )
    ddh_resource_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="DDH resource identifier"
    )
    ddh_version_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="DDH version identifier"
    )

    # Other external systems (JSONB)
    other_refs: Dict[str, Any] = Field(
        default_factory=dict,
        description="References to other external systems (JSONB)"
    )

    # Timestamps
    created_at: Optional[datetime] = Field(
        default=None,
        description="Record creation timestamp"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Record last update timestamp"
    )


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'DataType',
    'DDHRefs',
    'ExternalRefs',
    'DatasetRef',
    'DatasetRefRecord',
]
