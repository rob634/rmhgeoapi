# ============================================================================
# JOB DATABASE MODELS
# ============================================================================
# STATUS: Core - JobRecord persistence boundary
# PURPOSE: Database representation of jobs with orchestration and audit fields
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Job Database Models.

Defines JobRecord, which represents a job in the PostgreSQL database.
Inherits from JobData (core.contracts) and adds persistence-specific fields:
    - status, stage, total_stages (orchestration tracking)
    - stage_results, result_data, error_details (execution tracking)
    - metadata (additional job metadata)
    - created_at, updated_at (audit trail)

Architecture:
    JobData (core.contracts) - Base contract with essential job properties
         |
    JobRecord (this file) - Database boundary specialization

Exports:
    JobRecord: Pydantic model for job database records

Dependencies:
    pydantic: Data validation
    core.contracts.JobData: Base contract
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import Field, ConfigDict

from core.contracts import JobData
from .enums import JobStatus


class JobRecord(JobData):
    """
    Database representation of a job.

    Inherits essential job properties from JobData:
    - job_id, job_type, parameters

    Adds persistence-specific fields:
    - status: Current execution status
    - stage: Current stage being processed
    - total_stages: Total number of stages in workflow
    - stage_results: Results from completed stages
    - metadata: Additional job metadata
    - result_data: Final job results
    - error_details: Error message if failed
    - created_at, updated_at: Audit timestamps

    V0.8 Release Control (30 JAN 2026):
    - asset_id: FK to GeospatialAsset being processed (nullable - not all jobs have assets)
    - platform_id: FK to Platform that submitted this job (nullable - internal jobs)

    This is the DATA half of the "Job" entity.
    The BEHAVIOR half is Workflow (services/workflow.py).
    They collaborate via composition in CoreMachine.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    # Status tracking (Database-specific)
    status: JobStatus = Field(default=JobStatus.QUEUED, description="Current job status")
    stage: int = Field(default=1, ge=1, description="Current stage number")
    total_stages: int = Field(default=1, ge=1, description="Total number of stages")

    # V0.8 Release Control: Asset & Platform linkage (30 JAN 2026)
    # Nullable - not all jobs have assets (e.g., hello_world, maintenance)
    asset_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="FK to geospatial_assets - the asset this job processes"
    )
    platform_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="FK to platforms - identifies B2B platform that submitted"
    )
    # V0.8.11: B2B request tracking (08 FEB 2026)
    # Links job to the B2B request that triggered it (for callback routing)
    request_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="B2B request ID that triggered this job (for callback routing)"
    )

    # V0.8.12: ETL Version Tracking (08 FEB 2026)
    # Records which version of the ETL executed this job instance
    # Set at job creation time - immutable record of which code ran
    etl_version: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Version of ETL app that executed this job (e.g., '0.8.11.3')"
    )

    # Data fields (Database-specific)
    stage_results: Dict[str, Any] = Field(default_factory=dict, description="Results from completed stages")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Job metadata")
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Final job results")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # Timestamps (Database-specific)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def can_transition_to(self, new_status: JobStatus) -> bool:
        """
        Validate job status transitions for multi-stage workflow.

        Allowed transitions:
        - QUEUED → PROCESSING (normal startup)
        - QUEUED → FAILED (early failure before processing starts - 11 NOV 2025)
        - PROCESSING → QUEUED (stage advancement re-queuing)
        - PROCESSING → COMPLETED/FAILED/COMPLETED_WITH_ERRORS (terminal states)
        - COMPLETED/FAILED/COMPLETED_WITH_ERRORS → Any (error recovery/retry)

        This supports multi-stage jobs that cycle between QUEUED and PROCESSING
        as they advance through stages. Jobs can also fail early (before reaching
        PROCESSING) due to task pickup failures, pre-processing validation errors,
        or database issues. After all stages complete, jobs transition to a terminal state.

        Args:
            new_status: The proposed new status

        Returns:
            True if transition is valid, False otherwise

        Examples:
            Normal 2-stage job lifecycle:
            QUEUED → PROCESSING (stage 1) → QUEUED (stage 2) → PROCESSING (stage 2) → COMPLETED

            Early failure (task pickup fails):
            QUEUED → FAILED
        """
        # Normalize current status to enum (handles string values from database)
        current = JobStatus(self.status) if isinstance(self.status, str) else self.status

        # Allow cycling between QUEUED and PROCESSING for stage advancement
        if current == JobStatus.QUEUED and new_status == JobStatus.PROCESSING:
            return True
        if current == JobStatus.PROCESSING and new_status == JobStatus.QUEUED:
            return True  # Stage advancement re-queuing

        # Allow early failure before processing starts (11 NOV 2025)
        # Handles cases where job fails during task pickup or pre-processing validation
        if current == JobStatus.QUEUED and new_status == JobStatus.FAILED:
            return True

        # Allow terminal transitions from PROCESSING
        if current == JobStatus.PROCESSING and new_status in [
            JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS
        ]:
            return True

        # Allow error recovery transitions from terminal states
        if current in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS]:
            return True  # Can restart from any terminal state

        return False