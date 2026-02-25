# ============================================================================
# CLAUDE CONTEXT - ASSET V2 MODEL (STABLE IDENTITY CONTAINER)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - V0.9 Asset/Release entity split
# PURPOSE: Define Asset as a stable identity container (~12 fields) that
#          replaces the identity portion of the monolithic GeospatialAsset
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: ApprovalState, ClearanceState, ProcessingStatus, Asset, AssetRelease
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
from pydantic import BaseModel, Field, ConfigDict, field_serializer
from enum import Enum
import hashlib


# ============================================================================
# ENUMS (shared between Asset and Release)
# ============================================================================

class ApprovalState(str, Enum):
    """
    Approval workflow state for geospatial assets.

    Transitions:
    - PENDING_REVIEW -> APPROVED (approve with clearance_state)
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
    )

    @field_serializer('created_at', 'updated_at', 'deleted_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

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


# ============================================================================
# ASSET RELEASE MODEL (VERSIONED ARTIFACT WITH LIFECYCLE)
# ============================================================================

class AssetRelease(BaseModel):
    """
    V0.9 AssetRelease -- versioned artifact with lifecycle.

    Represents the WHAT + WHEN of a geospatial dataset. A Release is a versioned
    artifact that carries its own approval, clearance, and processing state.
    Multiple releases can coexist under one Asset.

    Table: app.asset_releases
    Primary Key: release_id
    Foreign Keys: asset_id -> app.assets(asset_id), job_id -> app.jobs(job_id)

    Lifecycle:
        - Created as draft (version_id=None, approval_state=PENDING_REVIEW)
        - Approved -> gets version_id ("v1", "v2", ...) and version_ordinal
        - Rejected -> can be overwritten with new data
        - Approved -> can be revoked (requires audit trail)

    Fields (~45):
        Identity: release_id, asset_id
        Version: version_id, suggested_version_id, version_ordinal, revision,
                 previous_release_id
        Flags: is_latest, is_served, request_id
        Physical: blob_path, table_name, stac_item_id, stac_collection_id,
                  stac_item_json, content_hash, source_file_hash, output_file_hash
        Processing: job_id, processing_status, processing_started_at,
                    processing_completed_at, last_error, workflow_id, node_summary
        Approval: approval_state, reviewer, reviewed_at, rejection_reason,
                  approval_notes, clearance_state, adf_run_id, cleared_at,
                  cleared_by, made_public_at, made_public_by
        Revocation: revoked_at, revoked_by, revocation_reason
        Timestamps: created_at, updated_at
        Priority: priority

    Created: 21 FEB 2026 as part of V0.9 Asset/Release entity split
    """
    model_config = ConfigDict(
        extra='ignore',
        str_strip_whitespace=True,
    )

    @field_serializer(
        'processing_started_at', 'processing_completed_at',
        'reviewed_at', 'cleared_at', 'made_public_at',
        'revoked_at', 'created_at', 'updated_at'
    )
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "asset_releases"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["release_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "asset_id": "app.assets(asset_id)",
        "job_id": "app.jobs(job_id)"
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["asset_id"], "name": "idx_releases_asset"},
        {"columns": ["version_id"], "name": "idx_releases_version"},
        {"columns": ["approval_state"], "name": "idx_releases_approval"},
        {"columns": ["processing_status"], "name": "idx_releases_processing"},
        {"columns": ["job_id"], "name": "idx_releases_job"},
        {"columns": ["stac_item_id"], "name": "idx_releases_stac_item"},
        {"columns": ["created_at"], "name": "idx_releases_created", "descending": True},
        {
            "columns": ["asset_id"],
            "name": "idx_releases_latest",
            "unique": True,
            "partial_where": "is_latest = true AND approval_state = 'approved'"
        },
        {
            "columns": ["asset_id"],
            "name": "idx_releases_pending",
            "partial_where": "approval_state = 'pending_review'"
        },
        {
            "columns": ["asset_id", "version_ordinal"],
            "name": "idx_releases_ordinal"
        },
        {
            "columns": ["request_id"],
            "name": "idx_releases_request",
            "partial_where": "request_id IS NOT NULL"
        },
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    release_id: str = Field(
        ...,
        max_length=64,
        description="Primary key for this release"
    )
    asset_id: str = Field(
        ...,
        max_length=64,
        description="FK to app.assets(asset_id) -- parent identity container"
    )

    # =========================================================================
    # VERSION
    # =========================================================================
    version_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Assigned at approval: 'v1', 'v2', etc. None = draft"
    )
    suggested_version_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Submitter's suggested version ID (metadata only, not authoritative)"
    )
    version_ordinal: int = Field(
        default=0,
        ge=0,
        description="Numeric version ordering: 1, 2, 3... reserved at draft creation. 0 = unassigned (legacy)"
    )
    revision: int = Field(
        default=1,
        ge=1,
        description="Overwrite counter -- incremented when draft is overwritten"
    )
    previous_release_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="FK to self -- links to the release this one supersedes"
    )

    # =========================================================================
    # FLAGS
    # =========================================================================
    is_latest: bool = Field(
        default=False,
        description="True if this is the latest approved release for the asset"
    )
    is_served: bool = Field(
        default=True,
        description="True if this release should be served via STAC/OGC APIs"
    )
    request_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Links to app.api_requests for audit trail"
    )

    # =========================================================================
    # PHYSICAL OUTPUTS
    # =========================================================================
    blob_path: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Azure Blob Storage path for raster outputs (COG)"
    )
    table_name: Optional[str] = Field(
        default=None,
        max_length=63,
        description="PostGIS table name for vector outputs"
    )
    stac_item_id: str = Field(
        ...,
        max_length=200,
        description="STAC item identifier (required for STAC materialization)"
    )
    stac_collection_id: str = Field(
        ...,
        max_length=200,
        description="STAC collection identifier (required for STAC materialization)"
    )
    stac_item_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Cached STAC item dict for materialization to pgSTAC"
    )
    content_hash: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Hash of the processed output content"
    )
    source_file_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Hash of the original source file"
    )
    output_file_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Hash of the final output file"
    )

    # =========================================================================
    # TILED OUTPUT METADATA
    # =========================================================================
    output_mode: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Output format: 'single' or 'tiled' (None for legacy/vector)"
    )
    tile_count: Optional[int] = Field(
        default=None,
        description="Number of COG tiles (tiled output only)"
    )
    search_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="pgSTAC search hash for mosaic discovery (tiled output only)"
    )

    # =========================================================================
    # PROCESSING LIFECYCLE
    # =========================================================================
    job_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="FK to app.jobs(job_id) -- processing job for this release"
    )
    processing_status: ProcessingStatus = Field(
        default=ProcessingStatus.PENDING,
        description="Current processing state"
    )
    processing_started_at: Optional[datetime] = Field(
        default=None,
        description="When processing began"
    )
    processing_completed_at: Optional[datetime] = Field(
        default=None,
        description="When processing finished (success or failure)"
    )
    last_error: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Last processing error message"
    )
    workflow_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Workflow/pipeline identifier for complex processing"
    )
    node_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Summary of processing node outputs (JSONB)"
    )

    # =========================================================================
    # APPROVAL LIFECYCLE
    # =========================================================================
    approval_state: ApprovalState = Field(
        default=ApprovalState.PENDING_REVIEW,
        description="Current approval workflow state"
    )
    reviewer: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who approved/rejected this release"
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        description="When the approval/rejection decision was made"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Why the release was rejected (free text)"
    )
    approval_notes: Optional[str] = Field(
        default=None,
        description="Notes from the reviewer (free text)"
    )
    clearance_state: ClearanceState = Field(
        default=ClearanceState.UNCLEARED,
        description="Security clearance level"
    )
    adf_run_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Azure Data Factory run ID for clearance pipeline"
    )
    cleared_at: Optional[datetime] = Field(
        default=None,
        description="When clearance was granted"
    )
    cleared_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who granted clearance"
    )
    made_public_at: Optional[datetime] = Field(
        default=None,
        description="When the release was made publicly accessible"
    )
    made_public_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who made the release public"
    )

    # =========================================================================
    # REVOCATION AUDIT
    # =========================================================================
    revoked_at: Optional[datetime] = Field(
        default=None,
        description="When the release was revoked"
    )
    revoked_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who revoked the release"
    )
    revocation_reason: Optional[str] = Field(
        default=None,
        description="Why the release was revoked (free text)"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When release was first created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When release was last modified"
    )

    # =========================================================================
    # PRIORITY
    # =========================================================================
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Processing priority (1=highest, 10=lowest)"
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    def can_approve(self) -> bool:
        """Check if this release can be approved (must be PENDING_REVIEW)."""
        return self.approval_state == ApprovalState.PENDING_REVIEW

    def can_reject(self) -> bool:
        """Check if this release can be rejected (must be PENDING_REVIEW)."""
        return self.approval_state == ApprovalState.PENDING_REVIEW

    def can_revoke(self) -> bool:
        """Check if this release can be revoked (must be APPROVED)."""
        return self.approval_state == ApprovalState.APPROVED

    def can_overwrite(self) -> bool:
        """Check if this release can be overwritten with new data."""
        return self.approval_state in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED)

    def is_draft(self) -> bool:
        """Check if this release is a draft (no version_id assigned)."""
        return self.version_id is None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Serializes:
        - Enum fields using .value
        - Datetime fields using .isoformat()
        - Dict/JSONB fields directly
        """
        return {
            # Identity
            'release_id': self.release_id,
            'asset_id': self.asset_id,
            # Version
            'version_id': self.version_id,
            'suggested_version_id': self.suggested_version_id,
            'version_ordinal': self.version_ordinal,
            'revision': self.revision,
            'previous_release_id': self.previous_release_id,
            # Flags
            'is_latest': self.is_latest,
            'is_served': self.is_served,
            'request_id': self.request_id,
            # Physical outputs
            'blob_path': self.blob_path,
            'table_name': self.table_name,
            'stac_item_id': self.stac_item_id,
            'stac_collection_id': self.stac_collection_id,
            'stac_item_json': self.stac_item_json,
            'content_hash': self.content_hash,
            'source_file_hash': self.source_file_hash,
            'output_file_hash': self.output_file_hash,
            # Tiled output metadata
            'output_mode': self.output_mode,
            'tile_count': self.tile_count,
            'search_id': self.search_id,
            # Processing lifecycle
            'job_id': self.job_id,
            'processing_status': self.processing_status.value if isinstance(self.processing_status, Enum) else self.processing_status,
            'processing_started_at': self.processing_started_at.isoformat() if self.processing_started_at else None,
            'processing_completed_at': self.processing_completed_at.isoformat() if self.processing_completed_at else None,
            'last_error': self.last_error,
            'workflow_id': self.workflow_id,
            'node_summary': self.node_summary,
            # Approval lifecycle
            'approval_state': self.approval_state.value if isinstance(self.approval_state, Enum) else self.approval_state,
            'reviewer': self.reviewer,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'rejection_reason': self.rejection_reason,
            'approval_notes': self.approval_notes,
            'clearance_state': self.clearance_state.value if isinstance(self.clearance_state, Enum) else self.clearance_state,
            'adf_run_id': self.adf_run_id,
            'cleared_at': self.cleared_at.isoformat() if self.cleared_at else None,
            'cleared_by': self.cleared_by,
            'made_public_at': self.made_public_at.isoformat() if self.made_public_at else None,
            'made_public_by': self.made_public_by,
            # Revocation audit
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'revoked_by': self.revoked_by,
            'revocation_reason': self.revocation_reason,
            # Timestamps
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            # Priority
            'priority': self.priority,
        }
