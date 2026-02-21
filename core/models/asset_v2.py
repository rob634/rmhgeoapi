# ============================================================================
# CLAUDE CONTEXT - ASSET V2 MODEL (STABLE IDENTITY CONTAINER)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - V0.9 Asset/Release entity split
# PURPOSE: Define Asset as a stable identity container (~12 fields) that
#          replaces the identity portion of the monolithic GeospatialAsset
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: ApprovalState, ClearanceState, ProcessingStatus, Asset
# DEPENDENCIES: pydantic, datetime, hashlib
# ============================================================================
"""
Asset V2 Model -- Stable Identity Container.

Part of the V0.9 Asset/Release entity split. The Asset represents a dataset
identity (platform_id + dataset_id + resource_id) that can have multiple
Releases underneath it.

Design Principles:
    - Asset = WHO (stable identity, ~12 fields)
    - Release = WHAT + WHEN (versioned content, approval state, processing)
    - Asset ID is deterministic: SHA256(platform_id|dataset_id|resource_id)[:32]
    - No version in the Asset ID -- versions live on Release

Table: app.assets
Primary Key: asset_id (deterministic from platform_id + dataset_id + resource_id)

Created: 21 FEB 2026 as part of V0.9 Asset/Release entity split
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar, Literal
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum
import hashlib


# ============================================================================
# ENUMS (shared between Asset and Release)
# ============================================================================

class ApprovalState(str, Enum):
    """
    Approval workflow state for geospatial assets.

    Transitions:
    - PENDING_REVIEW -> APPROVED (approve with clearance_level)
    - PENDING_REVIEW -> REJECTED (reject with reason)
    - REJECTED -> PENDING_REVIEW (only via overwrite submit)
    - APPROVED -> REVOKED (unpublish - requires audit trail)
    """
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ClearanceState(str, Enum):
    """
    Security clearance level for geospatial assets.

    Access behavior:
    - UNCLEARED: Same as OUO (internal only), awaiting confirmation
    - OUO: Official Use Only, internal access confirmed
    - PUBLIC: Triggers ADF export to external zone
    """
    UNCLEARED = "uncleared"
    OUO = "ouo"
    PUBLIC = "public"


class ProcessingStatus(str, Enum):
    """
    Processing lifecycle state for geospatial assets.

    Transitions:
    - PENDING -> PROCESSING (job starts)
    - PROCESSING -> COMPLETED (job succeeds)
    - PROCESSING -> FAILED (job fails)
    - FAILED -> PENDING (retry submitted)
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# ASSET MODEL (STABLE IDENTITY CONTAINER)
# ============================================================================

class Asset(BaseModel):
    """
    V0.9 Asset -- stable identity container.

    Represents the WHO of a geospatial dataset. Identity is defined by the
    triple (platform_id, dataset_id, resource_id). Versions, approval state,
    and processing state live on Release entities underneath.

    Table: app.assets
    Primary Key: asset_id (deterministic SHA256)

    Fields (~12):
        - asset_id: Deterministic PK from identity triple
        - platform_id: B2B platform identifier
        - dataset_id: Dataset identifier (promoted from JSONB)
        - resource_id: Resource identifier (promoted from JSONB)
        - platform_refs: Optional JSONB for non-DDH platforms
        - data_type: "raster" or "vector"
        - release_count: Number of releases under this asset
        - created_at, updated_at: Timestamps
        - deleted_at, deleted_by: Soft delete for audit trail
    """
    model_config = ConfigDict(
        extra='ignore',
        str_strip_whitespace=True,
        # TODO (21 FEB 2026): json_encoders is deprecated in Pydantic V2.
        # Replace with @field_serializer when cleaning up. Currently dead code --
        # all serialization goes through hand-written to_dict() methods.
        json_encoders={datetime: lambda v: v.isoformat() if v else None}
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "assets"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["asset_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {
            "columns": ["platform_id", "dataset_id", "resource_id"],
            "name": "uq_assets_identity",
            "partial_where": "deleted_at IS NULL"
        }
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["platform_id"], "name": "idx_assets_platform"},
        {"columns": ["dataset_id", "resource_id"], "name": "idx_assets_dataset_resource"},
        {"columns": ["created_at"], "name": "idx_assets_created", "descending": True},
        {"columns": ["deleted_at"], "name": "idx_assets_active", "partial_where": "deleted_at IS NULL"},
        {"columns": ["platform_refs"], "name": "idx_assets_platform_refs", "index_type": "gin"},
    ]

    # =========================================================================
    # IDENTITY (Primary Key - Deterministic)
    # =========================================================================
    asset_id: str = Field(
        ...,
        max_length=64,
        description="Deterministic ID: SHA256(platform_id|dataset_id|resource_id)[:32]"
    )

    # =========================================================================
    # IDENTITY TRIPLE (promoted from JSONB in V0.8)
    # =========================================================================
    platform_id: str = Field(
        default="ddh",
        max_length=50,
        description="FK to platforms.platform_id - identifies B2B platform"
    )
    dataset_id: str = Field(
        ...,
        max_length=200,
        description="Dataset identifier (promoted from platform_refs JSONB)"
    )
    resource_id: str = Field(
        ...,
        max_length=200,
        description="Resource identifier (promoted from platform_refs JSONB)"
    )

    # =========================================================================
    # OPTIONAL PLATFORM REFERENCES
    # =========================================================================
    platform_refs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional JSONB for non-DDH platform-specific identifiers"
    )

    # =========================================================================
    # DATA TYPE
    # =========================================================================
    data_type: Literal["vector", "raster"] = Field(
        ...,
        description="Type of geospatial data"
    )

    # =========================================================================
    # RELEASE TRACKING
    # =========================================================================
    release_count: int = Field(
        default=0,
        ge=0,
        description="Number of releases under this asset"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When asset was first created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When asset was last modified"
    )

    # =========================================================================
    # SOFT DELETE (Audit Trail)
    # =========================================================================
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="When asset was deleted (soft delete for audit trail)"
    )
    deleted_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who deleted the asset"
    )

    # =========================================================================
    # STATIC METHODS
    # =========================================================================
    @staticmethod
    def generate_asset_id(platform_id: str, dataset_id: str, resource_id: str) -> str:
        """
        Generate deterministic asset ID from identity triple.

        V0.9 Design: Asset ID is derived from the stable identity triple
        (platform_id, dataset_id, resource_id). Version is NOT included --
        that belongs on Release.

        Args:
            platform_id: Platform identifier (e.g., "ddh")
            dataset_id: Dataset identifier (e.g., "floods")
            resource_id: Resource identifier (e.g., "jakarta")

        Returns:
            32-character hex string (truncated SHA256)

        Raises:
            ValueError: If any input is empty

        Example:
            Asset.generate_asset_id("ddh", "floods", "jakarta")
            # -> "a1b2c3d4e5f6..."  (32 chars)
        """
        if not platform_id:
            raise ValueError("platform_id is required")
        if not dataset_id:
            raise ValueError("dataset_id is required")
        if not resource_id:
            raise ValueError("resource_id is required")

        composite = f"{platform_id}|{dataset_id}|{resource_id}"
        return hashlib.sha256(composite.encode()).hexdigest()[:32]

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    def is_active(self) -> bool:
        """Check if asset is not deleted."""
        return self.deleted_at is None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Note: Does NOT include approval_state, clearance_state, or any
        Release-specific fields. Those live on the Release entity.
        """
        return {
            'asset_id': self.asset_id,
            'platform_id': self.platform_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'platform_refs': self.platform_refs,
            'data_type': self.data_type,
            'release_count': self.release_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'deleted_by': self.deleted_by,
        }
