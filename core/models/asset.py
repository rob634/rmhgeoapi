# ============================================================================
# GEOSPATIAL ASSET ENTITY MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - First-class entity for Platform API data model
# PURPOSE: Define GeospatialAsset and related models for V0.8 entity architecture
# LAST_REVIEWED: 29 JAN 2026
# EXPORTS: ApprovalState, ClearanceState, ProcessingStatus, GeospatialAsset, AssetRevision
# DEPENDENCIES: pydantic, datetime, uuid
# ============================================================================
"""
Geospatial Asset Entity Models.

First-class entities for the Platform API data model. These models represent
datasets managed through the Platform API with full lifecycle tracking.

Architecture:
    - GeospatialAsset: First-class entity with FOUR state dimensions
      - Revision State: Tracks versions (1, 2, 3...)
      - Approval State: pending_review | approved | rejected
      - Clearance State: uncleared | ouo | public
      - Processing State: pending | processing | completed | failed (DAG - 29 JAN 2026)
    - AssetRevision: Append-only audit log for superseded revisions

Design Decisions (documented in V0.8_ENTITIES.md):
    - Entity created on request receipt (before job runs)
    - Soft delete with deleted_at for audit trail
    - Advisory locks for concurrent request handling
    - Deterministic asset_id from DDH identifiers

Tables Auto-Generated (stored in app schema):
    - app.geospatial_assets
    - app.asset_revisions

Created: 29 JAN 2026 as part of V0.8 Entity Architecture
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar, Literal
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from enum import Enum
import hashlib


# ============================================================================
# ENUMS
# ============================================================================

class ApprovalState(str, Enum):
    """
    Approval workflow state for geospatial assets.

    Transitions:
    - PENDING_REVIEW -> APPROVED (approve with clearance_level)
    - PENDING_REVIEW -> REJECTED (reject with reason)
    - REJECTED -> PENDING_REVIEW (only via overwrite submit)

    Note: From rejected, user must submit with overwrite=true to reset.
    """
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClearanceState(str, Enum):
    """
    Security clearance level for geospatial assets.

    Access behavior:
    - UNCLEARED: Same as OUO (internal only), awaiting confirmation
    - OUO: Official Use Only, internal access confirmed
    - PUBLIC: Triggers ADF export to external zone

    Note: UNCLEARED and OUO have identical access behavior.
    The distinction is for B2B workflow confirmation.
    """
    UNCLEARED = "uncleared"
    OUO = "ouo"
    PUBLIC = "public"


class ProcessingStatus(str, Enum):
    """
    Processing lifecycle state for geospatial assets (DAG Orchestration - V0.8).

    This is the FOURTH state dimension, distinct from Revision/Approval/Clearance.
    Tracks workflow execution status.

    Transitions:
    - PENDING -> PROCESSING (job starts)
    - PROCESSING -> COMPLETED (job succeeds)
    - PROCESSING -> FAILED (job fails)
    - FAILED -> PENDING (retry submitted)

    Question this answers: "Has the workflow finished?"

    Added: 29 JAN 2026 - Prepares for rmhdagmaster Epoch 5 integration
    """
    PENDING = "pending"          # Request received, no job yet (or retry queued)
    PROCESSING = "processing"    # Job running (DAG workflow active)
    COMPLETED = "completed"      # Job finished successfully
    FAILED = "failed"            # Job failed (may retry)


# ============================================================================
# GEOSPATIAL ASSET MODEL
# ============================================================================

class GeospatialAsset(BaseModel):
    """
    First-class entity for datasets managed via Platform API.

    Created when Platform API receives a submit request.
    Tracks the full lifecycle: creation -> approval -> clearance -> deletion.

    Table: app.geospatial_assets
    Primary Key: asset_id (deterministic from dataset_id|resource_id|version_id)

    DDL generation uses __sql_* class attributes for model-driven schema.

    State Dimensions (FOUR as of 29 JAN 2026):
        1. Revision State: revision, current_job_id, content_hash
        2. Approval State: approval_state, reviewer, reviewed_at, rejection_reason
        3. Clearance State: clearance_state, adf_run_id
        4. Processing State: processing_status, processing_started_at, processing_completed_at
           (DAG Orchestration - prepares for rmhdagmaster Epoch 5)
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True,
        json_encoders={datetime: lambda v: v.isoformat() if v else None}
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "geospatial_assets"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["asset_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "current_job_id": "app.jobs(job_id)"
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["dataset_id", "resource_id", "version_id"], "name": "uq_assets_identity"}
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["dataset_id", "resource_id", "version_id"], "name": "idx_assets_identity"},
        {"columns": ["stac_item_id"], "name": "idx_assets_stac_item"},
        {"columns": ["approval_state"], "name": "idx_assets_approval"},
        {"columns": ["clearance_state"], "name": "idx_assets_clearance"},
        {"columns": ["current_job_id"], "name": "idx_assets_current_job"},
        {"columns": ["created_at"], "name": "idx_assets_created", "descending": True},
        {
            "columns": ["approval_state"],
            "name": "idx_assets_pending",
            "partial_where": "approval_state = 'pending_review' AND deleted_at IS NULL"
        },
        {
            "columns": ["deleted_at"],
            "name": "idx_assets_active",
            "partial_where": "deleted_at IS NULL"
        },
        # Platform Registry indexes (V0.8 - 29 JAN 2026)
        {"columns": ["platform_id"], "name": "idx_assets_platform"},
        {"columns": ["platform_refs"], "name": "idx_assets_platform_refs", "index_type": "gin"},
        # DAG Orchestration indexes (V0.8 - 29 JAN 2026)
        {"columns": ["processing_status"], "name": "idx_assets_processing_status"},
        {"columns": ["workflow_id"], "name": "idx_assets_workflow"},
        {"columns": ["processing_started_at"], "name": "idx_assets_processing_started", "descending": True},
        {
            "columns": ["processing_started_at"],
            "name": "idx_assets_stuck_processing",
            "partial_where": "processing_status = 'processing'"
        },
        {
            "columns": ["updated_at"],
            "name": "idx_assets_failed",
            "partial_where": "processing_status = 'failed' AND deleted_at IS NULL",
            "descending": True
        },
        {
            "columns": ["priority", "created_at"],
            "name": "idx_assets_priority_queue",
            "partial_where": "processing_status = 'pending' AND deleted_at IS NULL"
        },
    ]

    # =========================================================================
    # IDENTITY (Primary Key - Deterministic)
    # =========================================================================
    asset_id: str = Field(
        ...,
        max_length=64,
        description="Deterministic ID: SHA256(platform_id|platform_refs_json)[:32]"
    )

    # =========================================================================
    # PLATFORM IDENTIFICATION (V0.8 - 29 JAN 2026)
    # =========================================================================
    # Flexible B2B platform support with JSONB for platform-specific identifiers.
    # Enables queries like: WHERE platform_refs @> '{"dataset_id": "IDN_lulc"}'
    # =========================================================================
    platform_id: str = Field(
        default="ddh",
        max_length=50,
        description="FK to platforms.platform_id - identifies B2B platform"
    )
    platform_refs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Platform-specific identifiers as JSONB for flexible queries"
    )

    # =========================================================================
    # DDH IDENTIFIERS (Kept for backward compatibility during migration)
    # =========================================================================
    # These mirror values in platform_refs for DDH platform.
    # Eventually can be deprecated once all queries use platform_refs.
    # =========================================================================
    dataset_id: str = Field(
        ...,
        max_length=255,
        description="DDH dataset identifier (mirrored in platform_refs)"
    )
    resource_id: str = Field(
        ...,
        max_length=255,
        description="DDH resource identifier (mirrored in platform_refs)"
    )
    version_id: str = Field(
        ...,
        max_length=100,
        description="DDH version identifier (mirrored in platform_refs)"
    )

    # =========================================================================
    # DATA TYPE
    # =========================================================================
    data_type: Literal["vector", "raster"] = Field(
        ...,
        description="Type of geospatial data"
    )

    # =========================================================================
    # SERVICE OUTPUTS (What TiPG/TiTiler Serve)
    # =========================================================================
    table_name: Optional[str] = Field(
        default=None,
        max_length=63,
        description="PostGIS table name for vectors (geo.{name})"
    )
    blob_path: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Azure Blob path for rasters (silver-cogs/{path})"
    )
    stac_item_id: str = Field(
        ...,
        max_length=200,
        description="STAC item identifier"
    )
    stac_collection_id: str = Field(
        ...,
        max_length=200,
        description="STAC collection identifier"
    )

    # =========================================================================
    # REVISION STATE
    # =========================================================================
    revision: int = Field(
        default=1,
        ge=1,
        description="Revision counter, increments on overwrite"
    )
    current_job_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Job that created current revision (FK to jobs)"
    )
    content_hash: Optional[str] = Field(
        default=None,
        max_length=128,
        description="SHA256 hash of source file for change detection"
    )

    # =========================================================================
    # APPROVAL STATE
    # =========================================================================
    approval_state: ApprovalState = Field(
        default=ApprovalState.PENDING_REVIEW,
        description="Current approval workflow state"
    )
    reviewer: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Email of reviewer who approved/rejected"
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        description="When approval decision was made"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason for rejection (required if rejected)"
    )

    # =========================================================================
    # CLEARANCE STATE
    # =========================================================================
    clearance_state: ClearanceState = Field(
        default=ClearanceState.UNCLEARED,
        description="Security clearance level"
    )
    adf_run_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="ADF pipeline run ID (only for PUBLIC clearance)"
    )

    # =========================================================================
    # CLEARANCE AUDIT TRAIL (29 JAN 2026)
    # =========================================================================
    # Explicit audit columns for clearance changes. These events are rare:
    # - Use case: "Data was internal, later got permission to share publicly"
    # - Wrong clearance: Use unpublish workflow, not clearance change
    # =========================================================================
    cleared_at: Optional[datetime] = Field(
        default=None,
        description="When clearance first changed from UNCLEARED"
    )
    cleared_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who first cleared the asset (reviewer email)"
    )
    made_public_at: Optional[datetime] = Field(
        default=None,
        description="When clearance changed to PUBLIC (null if never public)"
    )
    made_public_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Who made the asset public"
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
    # DAG ORCHESTRATION FIELDS - TIER 1: NEEDED (29 JAN 2026)
    # =========================================================================
    # These fields prepare GeospatialAsset for rmhdagmaster DAG orchestration.
    # All have sensible defaults so Epoch 4 continues to work without changes.
    # =========================================================================
    workflow_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Workflow that processed this asset (e.g., 'raster_processing')"
    )
    workflow_version: Optional[int] = Field(
        default=None,
        ge=1,
        description="Version of workflow used (for debugging/rollback)"
    )
    job_count: int = Field(
        default=0,
        ge=0,
        description="Number of job attempts for this asset (retries + revisions)"
    )
    last_request_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Most recent request ID (for callback routing to B2B partner)"
    )

    # =========================================================================
    # DAG ORCHESTRATION FIELDS - TIER 2: HIGHLY HELPFUL (29 JAN 2026)
    # =========================================================================
    processing_status: ProcessingStatus = Field(
        default=ProcessingStatus.PENDING,
        description="Processing lifecycle state (4th dimension, distinct from approval)"
    )
    processing_started_at: Optional[datetime] = Field(
        default=None,
        description="When first job started (for SLA tracking)"
    )
    processing_completed_at: Optional[datetime] = Field(
        default=None,
        description="When processing finished successfully"
    )
    last_error: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Last error message if failed (convenience field)"
    )
    node_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Quick status JSONB: {total, completed, failed, current_node}"
    )

    # =========================================================================
    # DAG ORCHESTRATION FIELDS - TIER 3: NICE TO HAVE (29 JAN 2026)
    # =========================================================================
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Processing priority (1=highest, 10=lowest)"
    )
    estimated_completion_at: Optional[datetime] = Field(
        default=None,
        description="ETA based on workflow progress"
    )
    source_file_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="SHA256 of input file (change detection)"
    )
    output_file_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        description="SHA256 of output file (integrity verification)"
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    @staticmethod
    def generate_asset_id(
        dataset_id: str = None,
        resource_id: str = None,
        version_id: str = None,
        platform_id: str = None,
        platform_refs: Dict[str, Any] = None
    ) -> str:
        """
        Generate deterministic asset ID from platform identifiers.

        V0.8 Enhancement (29 JAN 2026):
        - New signature: generate_asset_id(platform_id="ddh", platform_refs={...})
        - Legacy signature: generate_asset_id(dataset_id, resource_id, version_id)
          (automatically converted to platform_refs for DDH)

        Args:
            dataset_id: DDH dataset identifier (legacy)
            resource_id: DDH resource identifier (legacy)
            version_id: DDH version identifier (legacy)
            platform_id: Platform identifier (new)
            platform_refs: Platform-specific identifiers (new)

        Returns:
            32-character hex string (truncated SHA256)

        Example:
            # New style
            generate_asset_id(
                platform_id="ddh",
                platform_refs={"dataset_id": "IDN_lulc", "resource_id": "jakarta", "version_id": "v1"}
            )
            # Legacy style (backward compatible)
            generate_asset_id("IDN_lulc", "jakarta", "v1")
        """
        import json

        # Handle legacy signature (DDH-specific)
        if dataset_id and not platform_refs:
            platform_id = "ddh"
            platform_refs = {
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id
            }

        if not platform_id or not platform_refs:
            raise ValueError("Must provide either (dataset_id, resource_id, version_id) or (platform_id, platform_refs)")

        # Sort keys for deterministic ordering
        sorted_refs = json.dumps(platform_refs, sort_keys=True, separators=(',', ':'))
        composite = f"{platform_id}|{sorted_refs}"
        return hashlib.sha256(composite.encode()).hexdigest()[:32]

    @staticmethod
    def generate_asset_id_ddh(dataset_id: str, resource_id: str, version_id: str) -> str:
        """
        Generate asset ID for DDH platform (backward compatible helper).

        Equivalent to:
            generate_asset_id(platform_id="ddh", platform_refs={
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id
            })

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            32-character hex string (truncated SHA256)
        """
        return GeospatialAsset.generate_asset_id(
            platform_id="ddh",
            platform_refs={
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id
            }
        )

    def is_active(self) -> bool:
        """Check if asset is not deleted."""
        return self.deleted_at is None

    def can_approve(self) -> bool:
        """Check if asset can be approved."""
        return (
            self.approval_state == ApprovalState.PENDING_REVIEW
            and self.is_active()
        )

    def can_reject(self) -> bool:
        """Check if asset can be rejected."""
        return (
            self.approval_state == ApprovalState.PENDING_REVIEW
            and self.is_active()
        )

    def can_change_clearance(self) -> bool:
        """
        Check if asset's clearance level can be changed.

        Clearance changes are allowed when:
        - Asset is approved (not pending or rejected)
        - Asset is not deleted

        Use cases:
        - ouo -> public: "Got permission to share publicly"
        - public -> ouo: "Need to remove from external" (with warning)
        """
        return (
            self.approval_state == ApprovalState.APPROVED
            and self.is_active()
        )

    def is_cleared(self) -> bool:
        """Check if asset has been cleared (not UNCLEARED)."""
        return self.clearance_state != ClearanceState.UNCLEARED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'asset_id': self.asset_id,
            'platform_id': self.platform_id,
            'platform_refs': self.platform_refs,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'data_type': self.data_type,
            'table_name': self.table_name,
            'blob_path': self.blob_path,
            'stac_item_id': self.stac_item_id,
            'stac_collection_id': self.stac_collection_id,
            'revision': self.revision,
            'current_job_id': self.current_job_id,
            'content_hash': self.content_hash,
            'approval_state': self.approval_state.value if isinstance(self.approval_state, Enum) else self.approval_state,
            'reviewer': self.reviewer,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'rejection_reason': self.rejection_reason,
            'clearance_state': self.clearance_state.value if isinstance(self.clearance_state, Enum) else self.clearance_state,
            'adf_run_id': self.adf_run_id,
            'cleared_at': self.cleared_at.isoformat() if self.cleared_at else None,
            'cleared_by': self.cleared_by,
            'made_public_at': self.made_public_at.isoformat() if self.made_public_at else None,
            'made_public_by': self.made_public_by,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'deleted_by': self.deleted_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            # DAG Orchestration fields (V0.8 - 29 JAN 2026)
            'workflow_id': self.workflow_id,
            'workflow_version': self.workflow_version,
            'job_count': self.job_count,
            'last_request_id': self.last_request_id,
            'processing_status': self.processing_status.value if isinstance(self.processing_status, Enum) else self.processing_status,
            'processing_started_at': self.processing_started_at.isoformat() if self.processing_started_at else None,
            'processing_completed_at': self.processing_completed_at.isoformat() if self.processing_completed_at else None,
            'last_error': self.last_error,
            'node_summary': self.node_summary,
            'priority': self.priority,
            'estimated_completion_at': self.estimated_completion_at.isoformat() if self.estimated_completion_at else None,
            'source_file_hash': self.source_file_hash,
            'output_file_hash': self.output_file_hash,
        }


# ============================================================================
# ASSET REVISION MODEL
# ============================================================================

class AssetRevision(BaseModel):
    """
    Append-only audit log for asset revision history.

    Created when an overwrite replaces existing asset data.
    Records the state at the moment of supersession.

    Table: app.asset_revisions
    Primary Key: revision_id (UUID)
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore'
    )

    # =========================================================================
    # DDL GENERATION HINTS
    # =========================================================================
    __sql_table_name: ClassVar[str] = "asset_revisions"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["revision_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "asset_id": "app.geospatial_assets(asset_id)",
        "job_id": "app.jobs(job_id)"
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["asset_id", "revision"], "name": "uq_revisions_asset_rev"}
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["asset_id"], "name": "idx_revisions_asset"},
        {"columns": ["asset_id", "revision"], "name": "idx_revisions_asset_rev"},
        {"columns": ["superseded_at"], "name": "idx_revisions_superseded", "descending": True},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    revision_id: UUID = Field(
        ...,
        description="Unique revision record ID"
    )
    asset_id: str = Field(
        ...,
        max_length=64,
        description="FK to geospatial_assets"
    )

    # =========================================================================
    # REVISION SNAPSHOT
    # =========================================================================
    revision: int = Field(
        ...,
        ge=1,
        description="Revision number that was superseded"
    )
    job_id: str = Field(
        ...,
        max_length=64,
        description="Job that created this revision"
    )
    content_hash: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Content hash at this revision"
    )

    # =========================================================================
    # STATE AT SUPERSESSION
    # =========================================================================
    approval_state_at_supersession: ApprovalState = Field(
        ...,
        description="Approval state when this revision was replaced"
    )
    clearance_state_at_supersession: ClearanceState = Field(
        ...,
        description="Clearance state when this revision was replaced"
    )
    reviewer_at_supersession: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Reviewer at time of supersession"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        ...,
        description="When this revision was originally created"
    )
    superseded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this revision was replaced"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'revision_id': str(self.revision_id),
            'asset_id': self.asset_id,
            'revision': self.revision,
            'job_id': self.job_id,
            'content_hash': self.content_hash,
            'approval_state_at_supersession': self.approval_state_at_supersession.value if isinstance(self.approval_state_at_supersession, Enum) else self.approval_state_at_supersession,
            'clearance_state_at_supersession': self.clearance_state_at_supersession.value if isinstance(self.clearance_state_at_supersession, Enum) else self.clearance_state_at_supersession,
            'reviewer_at_supersession': self.reviewer_at_supersession,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'superseded_at': self.superseded_at.isoformat() if self.superseded_at else None,
        }
