# ============================================================================
# CLAUDE CONTEXT - H3 BATCH TRACKING REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Batch-level idempotency tracking for H3 operations
# PURPOSE: Track batch completion status for resumable H3 jobs
# LAST_REVIEWED: 26 NOV 2025
# EXPORTS: H3BatchTracker
# INTERFACES: PostgreSQLRepository (inherits connection mgmt, transactions)
# PYDANTIC_MODELS: None (uses simple dicts)
# DEPENDENCIES: psycopg, psycopg.sql, infrastructure.postgresql.PostgreSQLRepository
# SOURCE: PostgreSQL database (h3.batch_progress table)
# SCOPE: Batch-level idempotency for H3 cascade and future aggregation jobs
# VALIDATION: SQL injection prevention via psycopg.sql.Identifier() composition
# PATTERNS: Repository pattern, UPSERT for retry handling, Safe SQL composition
# ENTRY_POINTS: tracker = H3BatchTracker(); tracker.is_batch_completed(job_id, batch_id)
# INDEX:
#   - H3BatchTracker:55
#   - is_batch_completed:85
#   - get_completed_batch_ids:120
#   - start_batch:160
#   - complete_batch:210
#   - fail_batch:260
#   - get_batch_summary:300
# ============================================================================

"""
H3 Batch Tracking Repository - Batch-level idempotency for H3 operations

This module provides batch completion tracking to enable resumable H3 jobs.
When a job fails partway through Stage 2 (cascade fan-out with ~200 batches),
only incomplete batches are re-executed on retry instead of all batches.

Architecture:
    PostgreSQLRepository (base class - connection mgmt, transactions)
        ↓
    H3BatchTracker (this class - batch progress operations)

Idempotency Pattern:
    LAYER 1: Database Constraints (Data Integrity)
        h3.grids: ON CONFLICT (h3_index, grid_id) DO NOTHING

    LAYER 2: Batch Tracking (Workflow Orchestration) - THIS CLASS
        h3.batch_progress table tracks completion
        Job queries completed before creating tasks
        Handler checks before processing

    LAYER 3: Defensive Coding (Edge Cases)
        Handler early-exit if batch already in DB

Workflow:
    1. Job creates N batch tasks (each gets a unique batch_id)
    2. Handler calls start_batch() → creates row with status='processing'
    3. Handler completes → complete_batch() sets status='completed'
    4. On job restart, create_tasks_for_stage() queries completed batches
    5. Only incomplete batches get new tasks created

Usage:
    tracker = H3BatchTracker()

    # Check if batch already done (handler early-exit)
    if tracker.is_batch_completed(job_id, batch_id):
        return {"success": True, "result": {"skipped": True}}

    # Record batch start
    tracker.start_batch(job_id, batch_id, stage=2, operation_type="cascade_h3_descendants")

    try:
        # ... do work ...
        tracker.complete_batch(job_id, batch_id, items_processed=100, items_inserted=95)
    except Exception as e:
        tracker.fail_batch(job_id, batch_id, str(e))
        raise
"""

import logging
from typing import Set, Optional, Dict, Any, List
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository

# Logger setup
logger = logging.getLogger(__name__)


class H3BatchTracker(PostgreSQLRepository):
    """
    Batch-level completion tracking for H3 operations.

    Enables resumable jobs by tracking which batches have completed.
    When a job fails partway through, only incomplete batches are
    re-executed on retry.

    Schema: h3 (h3.batch_progress table)

    Usage:
        tracker = H3BatchTracker()

        # In job definition - get batches to skip
        completed = tracker.get_completed_batch_ids(job_id, stage=2)
        for batch_idx in range(num_batches):
            batch_id = f"{job_id[:8]}-s2-batch{batch_idx}"
            if batch_id in completed:
                continue  # Skip completed batches
            tasks.append({"batch_id": batch_id, ...})

        # In handler - record progress
        tracker.start_batch(job_id, batch_id, stage=2, operation_type="cascade")
        # ... process batch ...
        tracker.complete_batch(job_id, batch_id, items_processed, items_inserted)
    """

    def __init__(self):
        """
        Initialize H3BatchTracker with h3 schema.

        Uses parent PostgreSQLRepository for connection management,
        error handling, and transaction support.
        """
        super().__init__(schema_name='h3')
        logger.debug("H3BatchTracker initialized (schema: h3)")

    def is_batch_completed(self, job_id: str, batch_id: str) -> bool:
        """
        Check if a batch has already completed successfully.

        Used by handlers for early-exit if batch already processed.
        This is a defensive check - ideally the task shouldn't be
        created if the batch is complete, but this provides safety.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)
        batch_id : str
            Unique batch identifier (e.g., "abc123-s2-batch42")

        Returns:
        -------
        bool
            True if batch status is 'completed', False otherwise

        Example:
        -------
        >>> if tracker.is_batch_completed(job_id, batch_id):
        ...     return {"success": True, "result": {"skipped": True}}
        """
        query = sql.SQL("""
            SELECT status
            FROM {schema}.{table}
            WHERE job_id = %s AND batch_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, batch_id))
                result = cur.fetchone()

        if result and result['status'] == 'completed':
            logger.info(f"✅ Batch already completed: {batch_id}")
            return True

        return False

    def get_completed_batch_ids(self, job_id: str, stage_number: int) -> Set[str]:
        """
        Get all completed batch_ids for a job and stage.

        Used by job definition's create_tasks_for_stage() to skip
        creating tasks for batches that already completed.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)
        stage_number : int
            Stage number (e.g., 2 for cascade fan-out)

        Returns:
        -------
        Set[str]
            Set of batch_ids that have status='completed'

        Example:
        -------
        >>> completed = tracker.get_completed_batch_ids(job_id, stage=2)
        >>> for batch_idx in range(num_batches):
        ...     batch_id = f"{job_id[:8]}-s2-batch{batch_idx}"
        ...     if batch_id in completed:
        ...         continue  # Skip this batch
        ...     tasks.append({"batch_id": batch_id, ...})
        """
        query = sql.SQL("""
            SELECT batch_id
            FROM {schema}.{table}
            WHERE job_id = %s
              AND stage_number = %s
              AND status = 'completed'
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, stage_number))
                results = cur.fetchall()

        completed_ids = {row['batch_id'] for row in results}

        if completed_ids:
            logger.info(
                f"📊 Found {len(completed_ids)} completed batches for "
                f"job={job_id[:8]}... stage={stage_number}"
            )

        return completed_ids

    def start_batch(
        self,
        job_id: str,
        batch_id: str,
        stage_number: int,
        batch_index: int,
        operation_type: str
    ) -> None:
        """
        Record batch as started (UPSERT for retry handling).

        Creates a new row with status='processing' or updates existing
        row if batch is being retried after a previous failure.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)
        batch_id : str
            Unique batch identifier (e.g., "abc123-s2-batch42")
        stage_number : int
            Stage number (e.g., 2 for cascade)
        batch_index : int
            Zero-based batch index within the stage
        operation_type : str
            Handler operation type (e.g., "cascade_h3_descendants")

        Example:
        -------
        >>> tracker.start_batch(
        ...     job_id="abc123...",
        ...     batch_id="abc123-s2-batch42",
        ...     stage_number=2,
        ...     batch_index=42,
        ...     operation_type="cascade_h3_descendants"
        ... )
        """
        query = sql.SQL("""
            INSERT INTO {schema}.{table}
                (job_id, batch_id, operation_type, stage_number, batch_index,
                 status, started_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, 'processing', NOW(), NOW())
            ON CONFLICT (job_id, batch_id) DO UPDATE SET
                status = 'processing',
                started_at = NOW(),
                updated_at = NOW(),
                error_message = NULL
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (job_id, batch_id, operation_type, stage_number, batch_index)
                )
                conn.commit()

        logger.info(f"▶️  Started batch: {batch_id} (operation={operation_type})")

    def complete_batch(
        self,
        job_id: str,
        batch_id: str,
        items_processed: int,
        items_inserted: int
    ) -> None:
        """
        Mark batch as completed with results.

        Updates batch status to 'completed' and records the number
        of items processed and inserted (for debugging/verification).

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)
        batch_id : str
            Unique batch identifier
        items_processed : int
            Number of items processed (e.g., parent cells)
        items_inserted : int
            Number of items actually inserted (excludes ON CONFLICT skips)

        Example:
        -------
        >>> tracker.complete_batch(
        ...     job_id="abc123...",
        ...     batch_id="abc123-s2-batch42",
        ...     items_processed=100,
        ...     items_inserted=95  # 5 were duplicates
        ... )
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET
                status = 'completed',
                completed_at = NOW(),
                updated_at = NOW(),
                items_processed = %s,
                items_inserted = %s
            WHERE job_id = %s AND batch_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (items_processed, items_inserted, job_id, batch_id))
                conn.commit()

        logger.info(
            f"✅ Completed batch: {batch_id} "
            f"(processed={items_processed}, inserted={items_inserted})"
        )

    def fail_batch(
        self,
        job_id: str,
        batch_id: str,
        error_message: str
    ) -> None:
        """
        Record batch failure with error details.

        Updates batch status to 'failed' and stores the error message
        for debugging. Failed batches will be retried on job restart.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)
        batch_id : str
            Unique batch identifier
        error_message : str
            Error details for debugging

        Example:
        -------
        >>> try:
        ...     # ... process batch ...
        ... except Exception as e:
        ...     tracker.fail_batch(job_id, batch_id, str(e))
        ...     raise
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET
                status = 'failed',
                updated_at = NOW(),
                error_message = %s
            WHERE job_id = %s AND batch_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (error_message, job_id, batch_id))
                conn.commit()

        logger.warning(f"❌ Failed batch: {batch_id} (error={error_message[:100]}...)")

    def get_batch_summary(self, job_id: str) -> Dict[str, Any]:
        """
        Get summary of batch progress for a job.

        Returns counts by status for monitoring and debugging.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)

        Returns:
        -------
        Dict[str, Any]
            Summary with keys: total, pending, processing, completed, failed

        Example:
        -------
        >>> summary = tracker.get_batch_summary(job_id)
        >>> print(f"Progress: {summary['completed']}/{summary['total']}")
        """
        query = sql.SQL("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                SUM(items_processed) FILTER (WHERE status = 'completed') as total_processed,
                SUM(items_inserted) FILTER (WHERE status = 'completed') as total_inserted
            FROM {schema}.{table}
            WHERE job_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                result = cur.fetchone()

        summary = {
            'total': result['total'] or 0,
            'pending': result['pending'] or 0,
            'processing': result['processing'] or 0,
            'completed': result['completed'] or 0,
            'failed': result['failed'] or 0,
            'total_processed': result['total_processed'] or 0,
            'total_inserted': result['total_inserted'] or 0
        }

        logger.info(
            f"📊 Batch summary for {job_id[:8]}...: "
            f"completed={summary['completed']}/{summary['total']}, "
            f"failed={summary['failed']}"
        )

        return summary

    def get_failed_batches(self, job_id: str) -> List[Dict[str, Any]]:
        """
        Get details of failed batches for debugging.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)

        Returns:
        -------
        List[Dict[str, Any]]
            List of failed batch records with error messages

        Example:
        -------
        >>> failed = tracker.get_failed_batches(job_id)
        >>> for batch in failed:
        ...     print(f"Batch {batch['batch_id']}: {batch['error_message']}")
        """
        query = sql.SQL("""
            SELECT
                batch_id, batch_index, stage_number, operation_type,
                error_message, started_at, updated_at
            FROM {schema}.{table}
            WHERE job_id = %s AND status = 'failed'
            ORDER BY batch_index
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                results = cur.fetchall()

        failed_batches = [dict(row) for row in results]

        if failed_batches:
            logger.warning(
                f"⚠️  Found {len(failed_batches)} failed batches for {job_id[:8]}..."
            )

        return failed_batches

    def cleanup_job_batches(self, job_id: str) -> int:
        """
        Delete all batch progress records for a job.

        Used for cleanup after job completion or for resetting
        a job to re-run from scratch.

        Parameters:
        ----------
        job_id : str
            CoreMachine job ID (SHA256 hash)

        Returns:
        -------
        int
            Number of records deleted

        Example:
        -------
        >>> deleted = tracker.cleanup_job_batches(job_id)
        >>> print(f"Cleaned up {deleted} batch records")
        """
        query = sql.SQL("""
            DELETE FROM {schema}.{table}
            WHERE job_id = %s
        """).format(
            schema=sql.Identifier('h3'),
            table=sql.Identifier('batch_progress')
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id,))
                rowcount = cur.rowcount
                conn.commit()

        logger.info(f"🧹 Cleaned up {rowcount} batch records for {job_id[:8]}...")
        return rowcount
