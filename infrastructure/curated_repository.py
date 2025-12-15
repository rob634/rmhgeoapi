"""
Curated Dataset Repository.

Database operations for curated dataset management. Handles all persistence
for the curated_datasets registry and curated_update_log audit table.

Exports:
    CuratedDatasetRepository: CRUD operations for curated datasets
    CuratedUpdateLogRepository: Audit log operations
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from core.models import (
    CuratedDataset,
    CuratedUpdateLog,
    CuratedSourceType,
    CuratedUpdateStrategy,
    CuratedUpdateType,
    CuratedUpdateStatus
)
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "CuratedRepository")


class CuratedDatasetRepository(PostgreSQLRepository):
    """
    Repository for curated dataset registry operations.

    Handles CRUD operations for app.curated_datasets table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "curated_datasets"
        self.schema = "app"

    def create(self, dataset: CuratedDataset) -> CuratedDataset:
        """
        Create a new curated dataset registry entry.

        Args:
            dataset: CuratedDataset model to insert

        Returns:
            Created CuratedDataset with timestamps

        Raises:
            ValueError: If dataset_id already exists
        """
        logger.info(f"Creating curated dataset: {dataset.dataset_id}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if already exists
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} WHERE dataset_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset.dataset_id,)
                )
                if cur.fetchone():
                    raise ValueError(f"Dataset '{dataset.dataset_id}' already exists")

                # Insert
                now = datetime.now(timezone.utc)
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            dataset_id, name, description,
                            source_type, source_url, source_config,
                            job_type, update_strategy, update_schedule,
                            credential_key,
                            target_table_name, target_schema,
                            enabled, last_checked_at, last_updated_at,
                            last_job_id, source_version,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        dataset.dataset_id, dataset.name, dataset.description,
                        dataset.source_type.value, dataset.source_url, dataset.source_config,
                        dataset.job_type, dataset.update_strategy.value, dataset.update_schedule,
                        dataset.credential_key,
                        dataset.target_table_name, dataset.target_schema,
                        dataset.enabled, dataset.last_checked_at, dataset.last_updated_at,
                        dataset.last_job_id, dataset.source_version,
                        now, now
                    )
                )
                row = cur.fetchone()
                conn.commit()

                logger.info(f"Created curated dataset: {dataset.dataset_id}")
                return self._row_to_model(row)

    def get_by_id(self, dataset_id: str) -> Optional[CuratedDataset]:
        """
        Get a curated dataset by ID.

        Args:
            dataset_id: Dataset identifier

        Returns:
            CuratedDataset if found, None otherwise
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE dataset_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_all(self, enabled_only: bool = False) -> List[CuratedDataset]:
        """
        List all curated datasets.

        Args:
            enabled_only: If True, only return enabled datasets

        Returns:
            List of CuratedDataset models
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if enabled_only:
                    cur.execute(
                        sql.SQL("SELECT * FROM {}.{} WHERE enabled = true ORDER BY name").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        )
                    )
                else:
                    cur.execute(
                        sql.SQL("SELECT * FROM {}.{} ORDER BY name").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        )
                    )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def update(self, dataset_id: str, updates: Dict[str, Any]) -> Optional[CuratedDataset]:
        """
        Update a curated dataset.

        Args:
            dataset_id: Dataset to update
            updates: Dictionary of field updates

        Returns:
            Updated CuratedDataset if found, None otherwise
        """
        if not updates:
            return self.get_by_id(dataset_id)

        # Always update updated_at
        updates['updated_at'] = datetime.now(timezone.utc)

        # Convert enum values to strings
        for key, value in updates.items():
            if isinstance(value, (CuratedSourceType, CuratedUpdateStrategy)):
                updates[key] = value.value

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)

        values.append(dataset_id)  # For WHERE clause

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE dataset_id = %s RETURNING *").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                row = cur.fetchone()
                conn.commit()

                return self._row_to_model(row) if row else None

    def delete(self, dataset_id: str) -> bool:
        """
        Delete a curated dataset registry entry.

        Note: This does NOT delete the actual data table.
        Use with caution - typically you want to disable instead.

        Args:
            dataset_id: Dataset to delete

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {}.{} WHERE dataset_id = %s RETURNING dataset_id").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset_id,)
                )
                deleted = cur.fetchone()
                conn.commit()

                if deleted:
                    logger.info(f"Deleted curated dataset registry: {dataset_id}")
                return deleted is not None

    def update_last_checked(self, dataset_id: str, source_version: Optional[str] = None) -> None:
        """
        Update last_checked_at timestamp (called by scheduler).

        Args:
            dataset_id: Dataset that was checked
            source_version: New source version if changed
        """
        updates = {'last_checked_at': datetime.now(timezone.utc)}
        if source_version:
            updates['source_version'] = source_version
        self.update(dataset_id, updates)

    def update_last_updated(
        self,
        dataset_id: str,
        job_id: str,
        source_version: Optional[str] = None
    ) -> None:
        """
        Update last_updated_at timestamp (called after successful update).

        Args:
            dataset_id: Dataset that was updated
            job_id: Job ID that performed the update
            source_version: New source version
        """
        updates = {
            'last_updated_at': datetime.now(timezone.utc),
            'last_checked_at': datetime.now(timezone.utc),
            'last_job_id': job_id
        }
        if source_version:
            updates['source_version'] = source_version
        self.update(dataset_id, updates)

    def _row_to_model(self, row: Dict[str, Any]) -> CuratedDataset:
        """Convert database row to CuratedDataset model."""
        return CuratedDataset(
            dataset_id=row['dataset_id'],
            name=row['name'],
            description=row.get('description'),
            source_type=CuratedSourceType(row['source_type']),
            source_url=row['source_url'],
            source_config=row.get('source_config', {}),
            job_type=row['job_type'],
            update_strategy=CuratedUpdateStrategy(row['update_strategy']),
            update_schedule=row.get('update_schedule'),
            credential_key=row.get('credential_key'),
            target_table_name=row['target_table_name'],
            target_schema=row.get('target_schema', 'geo'),
            enabled=row.get('enabled', True),
            last_checked_at=row.get('last_checked_at'),
            last_updated_at=row.get('last_updated_at'),
            last_job_id=row.get('last_job_id'),
            source_version=row.get('source_version'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )


class CuratedUpdateLogRepository(PostgreSQLRepository):
    """
    Repository for curated update log operations.

    Handles audit logging for app.curated_update_log table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "curated_update_log"
        self.schema = "app"

    def create(self, log_entry: CuratedUpdateLog) -> CuratedUpdateLog:
        """
        Create a new update log entry.

        Args:
            log_entry: CuratedUpdateLog model to insert

        Returns:
            Created log entry with generated log_id
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            dataset_id, job_id,
                            update_type, source_version,
                            records_added, records_updated, records_deleted, records_total,
                            status, error_message,
                            started_at, completed_at, duration_seconds
                        ) VALUES (
                            %s, %s,
                            %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s
                        )
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        log_entry.dataset_id, log_entry.job_id,
                        log_entry.update_type.value, log_entry.source_version,
                        log_entry.records_added, log_entry.records_updated,
                        log_entry.records_deleted, log_entry.records_total,
                        log_entry.status.value, log_entry.error_message,
                        log_entry.started_at, log_entry.completed_at, log_entry.duration_seconds
                    )
                )
                row = cur.fetchone()
                conn.commit()

                return self._row_to_model(row)

    def update_status(
        self,
        log_id: int,
        status: CuratedUpdateStatus,
        error_message: Optional[str] = None,
        records_total: Optional[int] = None
    ) -> None:
        """
        Update the status of a log entry.

        Args:
            log_id: Log entry to update
            status: New status
            error_message: Error message if failed
            records_total: Total records if completed
        """
        updates = {'status': status.value}

        if error_message:
            updates['error_message'] = error_message
        if records_total is not None:
            updates['records_total'] = records_total

        # Mark completion time
        if status in (CuratedUpdateStatus.COMPLETED, CuratedUpdateStatus.FAILED, CuratedUpdateStatus.SKIPPED):
            now = datetime.now(timezone.utc)
            updates['completed_at'] = now

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)

        values.append(log_id)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET {} WHERE log_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table),
                        sql.SQL(", ").join(set_parts)
                    ),
                    values
                )
                conn.commit()

    def get_history(
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
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE dataset_id = %s
                        ORDER BY started_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (dataset_id, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: Dict[str, Any]) -> CuratedUpdateLog:
        """Convert database row to CuratedUpdateLog model."""
        return CuratedUpdateLog(
            log_id=row['log_id'],
            dataset_id=row['dataset_id'],
            job_id=row['job_id'],
            update_type=CuratedUpdateType(row['update_type']),
            source_version=row.get('source_version'),
            records_added=row.get('records_added', 0),
            records_updated=row.get('records_updated', 0),
            records_deleted=row.get('records_deleted', 0),
            records_total=row.get('records_total', 0),
            status=CuratedUpdateStatus(row['status']),
            error_message=row.get('error_message'),
            started_at=row.get('started_at'),
            completed_at=row.get('completed_at'),
            duration_seconds=row.get('duration_seconds')
        )


# Module exports
__all__ = [
    'CuratedDatasetRepository',
    'CuratedUpdateLogRepository'
]
