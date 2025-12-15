"""
Curated Dataset Scheduler Trigger.

Timer trigger for daily curated dataset updates.
Runs at 2 AM UTC to check which datasets need updating.

Exports:
    CuratedSchedulerTrigger: Timer trigger class
    curated_scheduler_trigger: Singleton instance
"""

import azure.functions as func
import json
import traceback
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from util_logger import LoggerFactory, ComponentType
from config import get_config
from services.curated.registry_service import CuratedRegistryService
from core.models import CuratedUpdateType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "CuratedScheduler")


class CuratedSchedulerTrigger:
    """
    Scheduler trigger for daily curated dataset updates.

    Checks all enabled datasets with schedules and submits update jobs
    for those that are due.

    Singleton pattern for consistent configuration across invocations.
    """

    _instance: Optional['CuratedSchedulerTrigger'] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("Initializing CuratedSchedulerTrigger")
        self.config = get_config()
        self._initialized = True
        logger.info("CuratedSchedulerTrigger initialized")

    @classmethod
    def instance(cls) -> 'CuratedSchedulerTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def service(self) -> CuratedRegistryService:
        """Lazy initialization of registry service."""
        if not hasattr(self, '_service'):
            self._service = CuratedRegistryService.instance()
        return self._service

    def handle_timer(self, timer: func.TimerRequest) -> None:
        """
        Handle daily scheduler timer.

        Checks all enabled datasets and submits update jobs for those due.

        Args:
            timer: Azure Function timer request
        """
        start_time = datetime.now(timezone.utc)

        logger.info(f"Curated scheduler running at {start_time.isoformat()}")

        if timer.past_due:
            logger.warning("Curated scheduler timer is past due!")

        try:
            # Get all enabled datasets with schedules
            datasets_to_check = self.service.get_datasets_due_for_update()

            logger.info(f"Found {len(datasets_to_check)} datasets to check for updates")

            results = {
                "checked_at": start_time.isoformat(),
                "datasets_checked": len(datasets_to_check),
                "jobs_submitted": 0,
                "jobs_skipped": 0,
                "errors": []
            }

            for dataset in datasets_to_check:
                try:
                    # Check if this dataset is due based on its schedule
                    if self._is_due_for_update(dataset):
                        # Submit update job
                        job_result = self._submit_update_job(
                            dataset_id=dataset.dataset_id,
                            update_type=CuratedUpdateType.SCHEDULED
                        )

                        if job_result.get("success"):
                            results["jobs_submitted"] += 1
                            logger.info(
                                f"Submitted update job for {dataset.dataset_id}: "
                                f"{job_result.get('job_id')}"
                            )
                        else:
                            results["errors"].append({
                                "dataset_id": dataset.dataset_id,
                                "error": job_result.get("error")
                            })
                    else:
                        results["jobs_skipped"] += 1
                        logger.debug(f"Skipping {dataset.dataset_id} - not due yet")

                except Exception as e:
                    logger.error(f"Error processing {dataset.dataset_id}: {e}")
                    results["errors"].append({
                        "dataset_id": dataset.dataset_id,
                        "error": str(e)
                    })

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            logger.info(
                f"Curated scheduler completed in {duration:.2f}s: "
                f"{results['jobs_submitted']} jobs submitted, "
                f"{results['jobs_skipped']} skipped, "
                f"{len(results['errors'])} errors"
            )

        except Exception as e:
            logger.error(f"Curated scheduler failed: {e}")
            logger.error(traceback.format_exc())

    def _is_due_for_update(self, dataset) -> bool:
        """
        Check if a dataset is due for update based on its schedule.

        For now, uses a simple approach:
        - If last_checked_at is None, it's due
        - If schedule is set, check against last_checked_at

        Future: Full cron schedule evaluation.

        Args:
            dataset: CuratedDataset model

        Returns:
            True if dataset should be updated
        """
        # If never checked, it's due
        if dataset.last_checked_at is None:
            return True

        # If no schedule, it's manual-only
        if dataset.update_schedule is None:
            return False

        # Simple schedule parsing (basic support)
        schedule = dataset.update_schedule

        # Handle common patterns
        now = datetime.now(timezone.utc)
        hours_since_check = (now - dataset.last_checked_at).total_seconds() / 3600

        # Monthly: "0 0 1 * *" - check if more than 28 days
        if schedule.endswith("1 * *"):
            return hours_since_check >= 28 * 24

        # Weekly: "0 0 * * 0" - check if more than 6 days
        if "* * 0" in schedule or "* * 7" in schedule:
            return hours_since_check >= 6 * 24

        # Daily: "0 0 * * *" - check if more than 23 hours
        if schedule.count("*") >= 3:
            return hours_since_check >= 23

        # Default: run if more than 24 hours
        return hours_since_check >= 24

    def _submit_update_job(
        self,
        dataset_id: str,
        update_type: CuratedUpdateType = CuratedUpdateType.SCHEDULED
    ) -> Dict[str, Any]:
        """
        Submit a curated dataset update job.

        Args:
            dataset_id: Dataset to update
            update_type: What triggered this update

        Returns:
            {
                'success': bool,
                'job_id': str,
                'error': str
            }
        """
        try:
            from jobs import get_job_class
            from infrastructure import RepositoryFactory

            # Get the job class
            job_class = get_job_class("curated_dataset_update")

            # Prepare parameters
            params = {
                "dataset_id": dataset_id,
                "update_type": update_type.value
            }

            # Validate and submit
            validated = job_class.validate_job_parameters(params)
            job_id = job_class.generate_job_id(validated)

            # Create repositories
            repos = RepositoryFactory.create_repositories()

            # Create job record
            job_record = job_class.create_job_record(job_id, validated, repos['job_repo'])

            # Queue the job
            job_class.queue_job(job_id, validated, repos['queue_client'])

            return {
                "success": True,
                "job_id": job_id,
                "dataset_id": dataset_id
            }

        except Exception as e:
            logger.error(f"Failed to submit update job for {dataset_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "dataset_id": dataset_id
            }


# Create singleton instance
curated_scheduler_trigger = CuratedSchedulerTrigger.instance()

__all__ = [
    'CuratedSchedulerTrigger',
    'curated_scheduler_trigger'
]
