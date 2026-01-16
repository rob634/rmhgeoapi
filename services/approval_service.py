# ============================================================================
# DATASET APPROVAL SERVICE
# ============================================================================
# STATUS: Service - Business logic for dataset approvals
# PURPOSE: Orchestrate approval workflow, STAC updates, and ADF triggers
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: ApprovalService
# DEPENDENCIES: infrastructure.approval_repository, infrastructure.pgstac_repository
# ============================================================================
"""
Dataset Approval Service.

Business logic for the dataset approval workflow. Handles:
- Creating approvals when jobs complete
- Approving datasets (update STAC, optionally trigger ADF)
- Rejecting datasets
- Resubmitting rejected datasets

Classification determines post-approval action:
- OUO: Just update STAC item with app:published=true
- PUBLIC: Trigger ADF pipeline + update STAC

Exports:
    ApprovalService: Business logic for approval workflow

Created: 16 JAN 2026
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from core.models import DatasetApproval, ApprovalStatus
from core.models.promoted import Classification
from infrastructure.approval_repository import ApprovalRepository, generate_approval_id

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ApprovalService")


class ApprovalService:
    """
    Service for dataset approval business logic.

    Orchestrates the approval workflow including:
    - STAC item property updates (app:published, app:approved_by, etc.)
    - ADF pipeline triggers for PUBLIC data
    - Status transitions with validation
    """

    def __init__(self):
        """Initialize with repository dependencies."""
        self.repo = ApprovalRepository()

    # =========================================================================
    # CREATE
    # =========================================================================

    def create_approval_for_job(
        self,
        job_id: str,
        job_type: str,
        classification: Classification = Classification.OUO,
        stac_item_id: Optional[str] = None,
        stac_collection_id: Optional[str] = None
    ) -> DatasetApproval:
        """
        Create a pending approval for a completed job.

        Called when an ETL job completes successfully. Creates an approval
        record that must be reviewed before the dataset is published.

        Args:
            job_id: The completed job ID
            job_type: Type of job (process_vector, process_raster_v2, etc.)
            classification: Data classification (OUO or PUBLIC)
            stac_item_id: STAC item ID if available
            stac_collection_id: STAC collection ID if available

        Returns:
            Created DatasetApproval in PENDING status
        """
        logger.info(f"Creating approval for job {job_id} (type: {job_type}, class: {classification.value})")

        return self.repo.create_for_job(
            job_id=job_id,
            job_type=job_type,
            classification=classification,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id
        )

    # =========================================================================
    # READ
    # =========================================================================

    def get_approval(self, approval_id: str) -> Optional[DatasetApproval]:
        """Get an approval by ID."""
        return self.repo.get_by_id(approval_id)

    def get_approval_for_job(self, job_id: str) -> Optional[DatasetApproval]:
        """Get the approval associated with a job."""
        return self.repo.get_by_job_id(job_id)

    def list_pending(self, limit: int = 50) -> List[DatasetApproval]:
        """List pending approvals."""
        return self.repo.list_pending(limit=limit)

    def list_approvals(
        self,
        status: Optional[ApprovalStatus] = None,
        classification: Optional[Classification] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DatasetApproval]:
        """
        List approvals with optional filters.

        Args:
            status: Filter by approval status
            classification: Filter by data classification
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of DatasetApproval records
        """
        return self.repo.list_all(
            limit=limit,
            offset=offset,
            status=status,
            classification=classification
        )

    def get_status_counts(self) -> Dict[str, int]:
        """Get counts of approvals by status."""
        return self.repo.count_by_status()

    # =========================================================================
    # APPROVE
    # =========================================================================

    def approve(
        self,
        approval_id: str,
        reviewer: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a dataset for publication.

        Performs the following:
        1. Validates approval is in PENDING status
        2. Updates STAC item with app:published=true
        3. If PUBLIC classification, triggers ADF pipeline
        4. Updates approval record to APPROVED status

        Args:
            approval_id: Approval to approve
            reviewer: Email or identifier of reviewer
            notes: Optional review notes

        Returns:
            Dict with:
                success: bool
                approval: Updated DatasetApproval
                action: 'stac_updated' or 'adf_triggered'
                adf_run_id: ADF run ID if applicable
                error: Error message if failed

        Raises:
            ValueError: If approval not found or invalid status
        """
        logger.info(f"Approving {approval_id} by {reviewer}")

        # Get approval
        approval = self.repo.get_by_id(approval_id)
        if not approval:
            return {
                'success': False,
                'error': f"Approval not found: {approval_id}"
            }

        # Validate status
        if approval.status != ApprovalStatus.PENDING:
            return {
                'success': False,
                'error': f"Cannot approve: status is '{approval.status.value}', expected 'pending'"
            }

        # Update STAC item with published=true
        stac_updated = self._update_stac_published(approval, reviewer)
        if not stac_updated['success']:
            logger.warning(f"STAC update failed for {approval_id}: {stac_updated.get('error')}")
            # Continue with approval - STAC update is best-effort

        # Check if we need to trigger ADF for PUBLIC data
        adf_run_id = None
        action = 'stac_updated'

        if approval.classification == Classification.PUBLIC:
            adf_result = self._trigger_adf_pipeline(approval)
            if adf_result['success']:
                adf_run_id = adf_result.get('run_id')
                action = 'adf_triggered'
                logger.info(f"ADF triggered for {approval_id}: {adf_run_id}")
            else:
                logger.warning(f"ADF trigger failed for {approval_id}: {adf_result.get('error')}")
                # Continue with approval - ADF is best-effort in current implementation

        # Update approval record
        updated = self.repo.approve(
            approval_id=approval_id,
            reviewer=reviewer,
            notes=notes,
            adf_run_id=adf_run_id
        )

        return {
            'success': True,
            'approval': updated,
            'action': action,
            'adf_run_id': adf_run_id,
            'stac_updated': stac_updated.get('success', False)
        }

    def _update_stac_published(self, approval: DatasetApproval, reviewer: str) -> Dict[str, Any]:
        """
        Update STAC item with published properties.

        Sets:
            app:published = true
            app:published_at = ISO timestamp
            app:approved_by = reviewer

        Args:
            approval: The approval record
            reviewer: Who approved

        Returns:
            Dict with success and optional error
        """
        if not approval.stac_item_id or not approval.stac_collection_id:
            return {
                'success': False,
                'error': 'Missing STAC item_id or collection_id'
            }

        try:
            from infrastructure.pgstac_repository import PgStacRepository
            pgstac = PgStacRepository()

            properties_update = {
                'app:published': True,
                'app:published_at': datetime.now(timezone.utc).isoformat(),
                'app:approved_by': reviewer
            }

            success = pgstac.update_item_properties(
                item_id=approval.stac_item_id,
                collection_id=approval.stac_collection_id,
                properties_update=properties_update
            )

            if success:
                logger.info(f"Updated STAC item {approval.stac_item_id} with published=true")
                return {'success': True}
            else:
                return {
                    'success': False,
                    'error': f"STAC item not found: {approval.stac_item_id}"
                }

        except Exception as e:
            logger.error(f"Error updating STAC item: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _trigger_adf_pipeline(self, approval: DatasetApproval) -> Dict[str, Any]:
        """
        Trigger ADF pipeline for PUBLIC data export.

        Args:
            approval: The approval record

        Returns:
            Dict with success, run_id, and optional error
        """
        try:
            from infrastructure.data_factory import get_data_factory_repository

            adf_repo = get_data_factory_repository()
            if not adf_repo:
                return {
                    'success': False,
                    'error': 'ADF not configured (missing ADF_SUBSCRIPTION_ID or ADF_FACTORY_NAME)'
                }

            # Trigger the export pipeline
            # Pipeline name and parameters TBD based on ADF configuration
            result = adf_repo.trigger_pipeline(
                pipeline_name='export_to_public',  # Configure via env var in future
                parameters={
                    'approval_id': approval.approval_id,
                    'job_id': approval.job_id,
                    'stac_item_id': approval.stac_item_id,
                    'stac_collection_id': approval.stac_collection_id,
                    'classification': approval.classification.value
                }
            )

            if result.get('run_id'):
                return {
                    'success': True,
                    'run_id': result['run_id'],
                    'poll_url': result.get('poll_url')
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown ADF error')
                }

        except ImportError:
            return {
                'success': False,
                'error': 'ADF module not available'
            }
        except Exception as e:
            logger.error(f"Error triggering ADF pipeline: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # REJECT
    # =========================================================================

    def reject(
        self,
        approval_id: str,
        reviewer: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Reject a dataset.

        Args:
            approval_id: Approval to reject
            reviewer: Email or identifier of reviewer
            reason: Rejection reason (required)

        Returns:
            Dict with success, approval, and optional error
        """
        logger.info(f"Rejecting {approval_id} by {reviewer}: {reason}")

        if not reason or not reason.strip():
            return {
                'success': False,
                'error': 'Rejection reason is required'
            }

        try:
            updated = self.repo.reject(
                approval_id=approval_id,
                reviewer=reviewer,
                reason=reason
            )

            if updated:
                return {
                    'success': True,
                    'approval': updated
                }
            else:
                return {
                    'success': False,
                    'error': f"Approval not found: {approval_id}"
                }

        except ValueError as e:
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # RESUBMIT
    # =========================================================================

    def resubmit(self, approval_id: str) -> Dict[str, Any]:
        """
        Resubmit a rejected approval back to pending.

        Args:
            approval_id: Approval to resubmit

        Returns:
            Dict with success, approval, and optional error
        """
        logger.info(f"Resubmitting {approval_id}")

        try:
            updated = self.repo.resubmit(approval_id)

            if updated:
                return {
                    'success': True,
                    'approval': updated
                }
            else:
                return {
                    'success': False,
                    'error': f"Approval not found: {approval_id}"
                }

        except ValueError as e:
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # TEST HELPERS
    # =========================================================================

    def create_test_approval(
        self,
        job_id: str = "test-job-123",
        job_type: str = "test_job",
        classification: str = "ouo"
    ) -> DatasetApproval:
        """
        Create a test approval for development/testing.

        Args:
            job_id: Test job ID
            job_type: Test job type
            classification: Classification string (ouo or public)

        Returns:
            Created test approval
        """
        class_enum = Classification.PUBLIC if classification.lower() == 'public' else Classification.OUO

        return self.create_approval_for_job(
            job_id=job_id,
            job_type=job_type,
            classification=class_enum,
            stac_item_id=f"test-item-{job_id[:8]}",
            stac_collection_id="test-collection"
        )


# Module exports
__all__ = ['ApprovalService']
