# ============================================================================
# CURATED DATASET REGISTRY SERVICE
# ============================================================================
# STATUS: Service layer - Business logic for curated dataset management
# PURPOSE: Provide CRUD operations and validation for curated datasets
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: CuratedRegistryService, curated_registry_service
# ============================================================================
"""
Curated Dataset Registry Service.

Business logic layer for curated dataset management. Wraps repository
operations with validation, logging, and business rules.

Exports:
    CuratedRegistryService: Service class for curated dataset operations
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from util_logger import LoggerFactory, ComponentType
from core.models import (
    CuratedDataset,
    CuratedUpdateLog,
    CuratedSourceType,
    CuratedUpdateStrategy,
    CuratedUpdateType,
    CuratedUpdateStatus
)
from infrastructure import CuratedDatasetRepository, CuratedUpdateLogRepository

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "CuratedRegistry")


class CuratedRegistryService:
    """
    Service layer for curated dataset registry operations.

    Provides business logic and validation on top of repository CRUD.
    Singleton pattern ensures consistent state across requests.
    """

    _instance: Optional['CuratedRegistryService'] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize service (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("Initializing CuratedRegistryService")
        self._dataset_repo = CuratedDatasetRepository()
        self._log_repo = CuratedUpdateLogRepository()
        self._initialized = True
        logger.info("CuratedRegistryService initialized")

    @classmethod
    def instance(cls) -> 'CuratedRegistryService':
        """Get singleton instance."""
        return cls()

    # =========================================================================
    # Dataset Registry CRUD
    # =========================================================================

    def create_dataset(self, dataset: CuratedDataset) -> CuratedDataset:
        """
        Create a new curated dataset registry entry.

        Args:
            dataset: CuratedDataset model with all required fields

        Returns:
            Created CuratedDataset with timestamps

        Raises:
            ValueError: If dataset_id already exists or validation fails
        """
        logger.info(f"Creating curated dataset: {dataset.dataset_id}")

        # Additional validation
        if not dataset.target_table_name.startswith('curated_'):
            raise ValueError(
                f"target_table_name must start with 'curated_', "
                f"got: {dataset.target_table_name}"
            )

        return self._dataset_repo.create(dataset)

    def get_dataset(self, dataset_id: str) -> Optional[CuratedDataset]:
        """
        Get a curated dataset by ID.

        Args:
            dataset_id: Dataset identifier

        Returns:
            CuratedDataset if found, None otherwise
        """
        return self._dataset_repo.get_by_id(dataset_id)

    def list_datasets(self, enabled_only: bool = False) -> List[CuratedDataset]:
        """
        List all curated datasets.

        Args:
            enabled_only: If True, only return enabled datasets

        Returns:
            List of CuratedDataset models
        """
        return self._dataset_repo.list_all(enabled_only=enabled_only)

    def update_dataset(
        self,
        dataset_id: str,
        updates: Dict[str, Any]
    ) -> Optional[CuratedDataset]:
        """
        Update a curated dataset.

        Args:
            dataset_id: Dataset to update
            updates: Dictionary of field updates

        Returns:
            Updated CuratedDataset if found, None otherwise

        Raises:
            ValueError: If trying to set invalid target_table_name
        """
        # Validate target_table_name if being updated
        if 'target_table_name' in updates:
            if not updates['target_table_name'].startswith('curated_'):
                raise ValueError(
                    f"target_table_name must start with 'curated_', "
                    f"got: {updates['target_table_name']}"
                )

        logger.info(f"Updating curated dataset: {dataset_id}")
        return self._dataset_repo.update(dataset_id, updates)

    def delete_dataset(self, dataset_id: str) -> bool:
        """
        Delete a curated dataset registry entry.

        Note: This does NOT delete the actual data table.
        Use with caution - typically you want to disable instead.

        Args:
            dataset_id: Dataset to delete

        Returns:
            True if deleted, False if not found
        """
        logger.warning(f"Deleting curated dataset registry: {dataset_id}")
        return self._dataset_repo.delete(dataset_id)

    def enable_dataset(self, dataset_id: str) -> Optional[CuratedDataset]:
        """Enable scheduled updates for a dataset."""
        return self._dataset_repo.update(dataset_id, {'enabled': True})

    def disable_dataset(self, dataset_id: str) -> Optional[CuratedDataset]:
        """Disable scheduled updates for a dataset."""
        return self._dataset_repo.update(dataset_id, {'enabled': False})

    # =========================================================================
    # Update Log Operations
    # =========================================================================

    def start_update(
        self,
        dataset_id: str,
        job_id: str,
        update_type: CuratedUpdateType = CuratedUpdateType.MANUAL
    ) -> CuratedUpdateLog:
        """
        Record the start of an update operation.

        Args:
            dataset_id: Dataset being updated
            job_id: CoreMachine job ID
            update_type: What triggered the update

        Returns:
            Created CuratedUpdateLog with log_id
        """
        dataset = self.get_dataset(dataset_id)
        source_version = dataset.source_version if dataset else None

        log_entry = CuratedUpdateLog(
            dataset_id=dataset_id,
            job_id=job_id,
            update_type=update_type,
            source_version=source_version,
            status=CuratedUpdateStatus.STARTED,
            started_at=datetime.now(timezone.utc)
        )

        return self._log_repo.create(log_entry)

    def update_log_status(
        self,
        log_id: int,
        status: CuratedUpdateStatus,
        error_message: Optional[str] = None,
        records_total: Optional[int] = None
    ) -> None:
        """
        Update the status of an update log entry.

        Args:
            log_id: Log entry to update
            status: New status
            error_message: Error message if failed
            records_total: Total records if completed
        """
        self._log_repo.update_status(
            log_id=log_id,
            status=status,
            error_message=error_message,
            records_total=records_total
        )

    def complete_update(
        self,
        log_id: int,
        records_added: int = 0,
        records_updated: int = 0,
        records_deleted: int = 0,
        records_total: int = 0,
        source_version: Optional[str] = None
    ) -> None:
        """
        Mark an update as successfully completed.

        Updates both the log entry and the dataset registry.

        Args:
            log_id: Log entry ID
            records_added: Count of new records
            records_updated: Count of updated records
            records_deleted: Count of deleted records
            records_total: Total records after update
            source_version: New source version
        """
        # Update log entry
        self._log_repo.update_status(
            log_id=log_id,
            status=CuratedUpdateStatus.COMPLETED,
            records_total=records_total
        )

        # Get the log entry to find dataset_id and job_id
        # Note: We need to query this - for now use a direct connection
        # This could be improved by returning the log entry from update_status

    def fail_update(
        self,
        log_id: int,
        error_message: str
    ) -> None:
        """
        Mark an update as failed.

        Args:
            log_id: Log entry ID
            error_message: Description of what went wrong
        """
        self._log_repo.update_status(
            log_id=log_id,
            status=CuratedUpdateStatus.FAILED,
            error_message=error_message
        )

    def skip_update(
        self,
        log_id: int,
        reason: str = "No update needed (source unchanged)"
    ) -> None:
        """
        Mark an update as skipped (no changes detected).

        Args:
            log_id: Log entry ID
            reason: Why the update was skipped
        """
        self._log_repo.update_status(
            log_id=log_id,
            status=CuratedUpdateStatus.SKIPPED,
            error_message=reason
        )

    def get_update_history(
        self,
        dataset_id: str,
        limit: int = 20
    ) -> List[CuratedUpdateLog]:
        """
        Get update history for a dataset.

        Args:
            dataset_id: Dataset to get history for
            limit: Maximum entries to return

        Returns:
            List of log entries, newest first
        """
        return self._log_repo.get_history(dataset_id, limit)

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_datasets_due_for_update(self) -> List[CuratedDataset]:
        """
        Get datasets that are due for scheduled update.

        Returns datasets that:
        - Are enabled
        - Have a schedule defined
        - Schedule indicates update is due

        Returns:
            List of datasets due for update
        """
        # For now, return all enabled datasets with schedules
        # Cron schedule evaluation will be added in Phase 6
        datasets = self.list_datasets(enabled_only=True)
        return [d for d in datasets if d.update_schedule is not None]

    def to_dict(self, dataset: CuratedDataset) -> Dict[str, Any]:
        """
        Convert a CuratedDataset to a JSON-serializable dict.

        Args:
            dataset: Dataset to convert

        Returns:
            Dictionary with JSON-safe values
        """
        return {
            'dataset_id': dataset.dataset_id,
            'name': dataset.name,
            'description': dataset.description,
            'source_type': dataset.source_type.value,
            'source_url': dataset.source_url,
            'source_config': dataset.source_config,
            'job_type': dataset.job_type,
            'update_strategy': dataset.update_strategy.value,
            'update_schedule': dataset.update_schedule,
            'credential_key': dataset.credential_key,
            'target_table_name': dataset.target_table_name,
            'target_schema': dataset.target_schema,
            'enabled': dataset.enabled,
            'last_checked_at': dataset.last_checked_at.isoformat() if dataset.last_checked_at else None,
            'last_updated_at': dataset.last_updated_at.isoformat() if dataset.last_updated_at else None,
            'last_job_id': dataset.last_job_id,
            'source_version': dataset.source_version,
            'created_at': dataset.created_at.isoformat() if dataset.created_at else None,
            'updated_at': dataset.updated_at.isoformat() if dataset.updated_at else None
        }

    def log_to_dict(self, log: CuratedUpdateLog) -> Dict[str, Any]:
        """
        Convert a CuratedUpdateLog to a JSON-serializable dict.

        Args:
            log: Log entry to convert

        Returns:
            Dictionary with JSON-safe values
        """
        return {
            'log_id': log.log_id,
            'dataset_id': log.dataset_id,
            'job_id': log.job_id,
            'update_type': log.update_type.value,
            'source_version': log.source_version,
            'records_added': log.records_added,
            'records_updated': log.records_updated,
            'records_deleted': log.records_deleted,
            'records_total': log.records_total,
            'status': log.status.value,
            'error_message': log.error_message,
            'started_at': log.started_at.isoformat() if log.started_at else None,
            'completed_at': log.completed_at.isoformat() if log.completed_at else None,
            'duration_seconds': log.duration_seconds
        }


# Lazy singleton accessor - avoids import-time database connection
_curated_registry_service = None


def get_curated_registry_service() -> CuratedRegistryService:
    """Get the singleton CuratedRegistryService instance (lazy initialization)."""
    global _curated_registry_service
    if _curated_registry_service is None:
        _curated_registry_service = CuratedRegistryService.instance()
    return _curated_registry_service


__all__ = [
    'CuratedRegistryService',
    'get_curated_registry_service'
]
