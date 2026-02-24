# ============================================================================
# UNPUBLISH AUDIT MODELS
# ============================================================================
# STATUS: Core - Audit trail for unpublish operations
# PURPOSE: Track deletions for audit, idempotency, and potential recovery
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Unpublish Audit Models.

Pydantic models for unpublish_jobs audit table. Records all unpublish
operations for audit trail and idempotency management.

Purpose:
    - Audit trail: What was deleted, when, by which job
    - Idempotency fix: Marks original jobs as "unpublished"
    - Recovery: Preserves artifact metadata for potential restoration

Exports:
    UnpublishJobRecord: Audit record for unpublish operations
    UnpublishStatus: Status enumeration
    UnpublishType: Type of unpublish operation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer
import uuid


class UnpublishType(str, Enum):
    """Types of unpublish operations."""
    RASTER = "raster"        # Unpublish raster STAC item + COG blobs
    VECTOR = "vector"        # Unpublish vector STAC item + PostGIS table
    STAC_ONLY = "stac_only"  # Unpublish STAC item only (no artifact deletion)


class UnpublishStatus(str, Enum):
    """Status of an unpublish operation."""
    PENDING = "pending"      # Queued but not started
    DRY_RUN = "dry_run"      # Completed as dry-run (no deletions)
    COMPLETED = "completed"  # Successfully unpublished
    FAILED = "failed"        # Unpublish failed
    PARTIAL = "partial"      # Some artifacts deleted, others failed


class UnpublishJobRecord(BaseModel):
    """
    Database representation of an unpublish operation.

    Records all unpublish operations for audit trail and recovery.
    Each unpublish job creates one record documenting what was deleted.

    Primary Key: unpublish_id (UUID)

    Key Relationships:
    - unpublish_job_id: The unpublish_raster/unpublish_vector job ID
    - original_job_id: The original processing job that created the artifact
    - stac_item_id + collection_id: The STAC item that was unpublished

    Artifacts Deleted (JSONB):
    - blobs: List of blob paths deleted from storage
    - table_name: PostGIS table dropped (vectors only)
    - stac_item: STAC item record (preserved for potential recovery)
    - collection_deleted: Whether empty collection was removed
    """

    model_config = ConfigDict()

    @field_serializer('created_at', 'completed_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # Primary Key
    # =========================================================================
    unpublish_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        max_length=64,
        description="Unique unpublish operation ID (UUID)"
    )

    # =========================================================================
    # Job References
    # =========================================================================
    unpublish_job_id: str = Field(
        ...,
        max_length=64,
        description="Job ID of the unpublish_raster/unpublish_vector job"
    )
    unpublish_type: UnpublishType = Field(
        ...,
        description="Type of unpublish operation (raster, vector, stac_only)"
    )

    # =========================================================================
    # Original Job Tracking (for idempotency fix)
    # =========================================================================
    original_job_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Job ID that originally created the artifact (from STAC item properties)"
    )
    original_job_type: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Type of original job (e.g., 'process_raster_v2', 'process_vector')"
    )
    original_parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Original job parameters (preserved for audit)"
    )

    # =========================================================================
    # STAC Item Reference
    # =========================================================================
    stac_item_id: str = Field(
        ...,
        max_length=256,
        description="STAC item ID that was unpublished"
    )
    collection_id: str = Field(
        ...,
        max_length=256,
        description="STAC collection the item belonged to"
    )

    # =========================================================================
    # Artifacts Deleted
    # =========================================================================
    artifacts_deleted: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed record of what was deleted: {blobs: [], table: '', stac_item: {...}}"
    )
    collection_deleted: bool = Field(
        default=False,
        description="Whether the collection was also deleted (empty after item removal)"
    )

    # =========================================================================
    # Status & Execution
    # =========================================================================
    status: UnpublishStatus = Field(
        default=UnpublishStatus.PENDING,
        description="Status of the unpublish operation"
    )
    dry_run: bool = Field(
        default=True,
        description="Whether this was a dry-run (preview only, no deletions)"
    )
    error_details: Optional[str] = Field(
        default=None,
        description="Error message if unpublish failed"
    )

    # =========================================================================
    # Timestamps
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the unpublish record was created"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the unpublish operation completed"
    )


# Module exports
__all__ = [
    'UnpublishJobRecord',
    'UnpublishType',
    'UnpublishStatus'
]
