# ============================================================================
# DATASET APPROVAL MODELS
# ============================================================================
# STATUS: Core - QA workflow for dataset publication
# PURPOSE: Approval records for human review before STAC publication
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: DatasetApproval, ApprovalStatus
# DEPENDENCIES: pydantic, core.models.promoted.Classification
# ============================================================================
"""
Dataset Approval Models.

Pydantic models for the dataset approval system. When ETL jobs complete,
an approval record is created for human review before the dataset is
marked as "published" in STAC.

Classification determines post-approval action:
- OUO (Official Use Only): Update STAC app:published=true
- PUBLIC: Trigger ADF pipeline for external distribution + update STAC

Tables:
    app.dataset_approvals - Approval records for QA workflow

Exports:
    DatasetApproval: Approval record for a completed job
    ApprovalStatus: Status enum (pending, approved, rejected)

Created: 16 JAN 2026
"""

from datetime import datetime, timezone
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

from .promoted import Classification


class ApprovalStatus(str, Enum):
    """
    Status values for dataset approvals.

    State transitions:
    - PENDING -> APPROVED (reviewer approves)
    - PENDING -> REJECTED (reviewer rejects)
    - REJECTED -> PENDING (resubmit for review)
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DatasetApproval(BaseModel):
    """
    Approval record for a completed ETL job.

    When a job completes successfully and produces a STAC item, an approval
    record is created for human review. The reviewer can approve (publish)
    or reject (with reason) the dataset.

    Table: app.dataset_approvals
    Primary Key: approval_id

    Workflow:
        1. Job completes -> approval record created (status=pending)
        2. Reviewer views dataset in UI
        3. Reviewer approves or rejects
        4. If approved:
           - OUO: Update STAC item with app:published=true
           - PUBLIC: Trigger ADF pipeline + update STAC
        5. If rejected:
           - Record rejection reason
           - Can be resubmitted after fixes

    Examples:
        # Create pending approval
        DatasetApproval(
            approval_id="apr-abc123",
            job_id="job-xyz789",
            job_type="process_vector",
            classification=Classification.OUO,
            stac_item_id="admin-boundaries-chile-v1",
            stac_collection_id="admin-boundaries"
        )

        # After approval
        approval.status = ApprovalStatus.APPROVED
        approval.reviewer = "analyst@example.com"
        approval.reviewed_at = datetime.now(timezone.utc)
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat() if v else None}
    )

    # Identity
    approval_id: str = Field(
        ...,
        max_length=64,
        description="Unique approval ID (e.g., 'apr-{short_hash}')"
    )

    # Job reference
    job_id: str = Field(
        ...,
        max_length=64,
        description="ID of the completed job that created this dataset"
    )
    job_type: str = Field(
        ...,
        max_length=100,
        description="Type of job (process_vector, process_raster_v2, etc.)"
    )

    # Classification determines post-approval action
    classification: Classification = Field(
        default=Classification.OUO,
        description="Data classification: public (triggers ADF) or ouo (STAC only)"
    )

    # Status
    status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING,
        description="Current approval status"
    )

    # STAC references
    stac_item_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="STAC item ID to be published"
    )
    stac_collection_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="STAC collection ID"
    )

    # Review info
    reviewer: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Email or identifier of the reviewer"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Review notes (optional)"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason for rejection (required if rejected)"
    )

    # ADF integration (for PUBLIC classification)
    adf_run_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Azure Data Factory pipeline run ID (if PUBLIC approved)"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the approval record was created"
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        description="When the approval was reviewed (approved/rejected)"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was last modified"
    )

    def can_transition_to(self, new_status: ApprovalStatus) -> bool:
        """
        Validate approval status transitions.

        Allowed transitions:
        - PENDING -> APPROVED (approve)
        - PENDING -> REJECTED (reject)
        - REJECTED -> PENDING (resubmit)

        Args:
            new_status: The proposed new status

        Returns:
            True if transition is valid, False otherwise
        """
        current = ApprovalStatus(self.status) if isinstance(self.status, str) else self.status

        valid_transitions = {
            ApprovalStatus.PENDING: [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
            ApprovalStatus.REJECTED: [ApprovalStatus.PENDING],
            ApprovalStatus.APPROVED: [],  # Terminal state
        }

        return new_status in valid_transitions.get(current, [])


# Module exports
__all__ = [
    'DatasetApproval',
    'ApprovalStatus'
]
