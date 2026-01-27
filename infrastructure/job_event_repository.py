# ============================================================================
# CLAUDE CONTEXT - JOB EVENT REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Job execution event tracking
# PURPOSE: CRUD operations for app.job_events table
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# ============================================================================
"""
Job Event Repository - Execution Timeline Tracking.

Provides recording and querying of job execution events for both
FunctionApp and Docker workers. Enables "last successful checkpoint"
debugging and real-time progress visualization.

Architecture:
    - Single table (app.job_events)
    - SERIAL primary key (event_id) - auto-increment
    - Foreign key to app.jobs(job_id)
    - Row-oriented append-only event log
    - Optimized for time-series queries

Recording Methods (called during execution):
    record_event(event) - Insert single event
    record_job_event(...) - Convenience for job-level events
    record_task_event(...) - Convenience for task-level events

Query Methods (called by UI):
    get_events_for_job(job_id) - Get events with filtering
    get_events_for_task(task_id) - All events for a task
    get_latest_event(job_id) - Most recent event
    get_event_counts_by_type(job_id) - Summary counts
    get_events_timeline(job_id) - Formatted for UI display

Exports:
    JobEventRepository: Event CRUD repository
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from infrastructure.interface_repository import IJobEventRepository
from core.models.job_event import JobEvent, JobEventType, JobEventStatus

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "job_event")


class JobEventRepository(PostgreSQLRepository, IJobEventRepository):
    """
    Repository for job execution event CRUD operations.

    Implements IJobEventRepository interface (27 JAN 2026 - Orthodox compliance).
    Uses app.job_events table for timeline tracking.
    All queries use psycopg.sql composition for safety.

    Table: app.job_events
        event_id SERIAL PRIMARY KEY       -- Auto-increment (BUG-001 fix)
        job_id VARCHAR(64) NOT NULL       -- FK to app.jobs
        task_id VARCHAR(64)               -- NULL for job-level events
        stage INTEGER                     -- Stage number
        event_type VARCHAR(50) NOT NULL   -- JobEventType enum value
        event_status VARCHAR(20)          -- JobEventStatus enum value
        checkpoint_name VARCHAR(100)      -- For App Insights correlation
        event_data JSONB                  -- Flexible context
        error_message VARCHAR(1000)       -- Error details if failure
        duration_ms INTEGER               -- Operation timing
        created_at TIMESTAMPTZ            -- Event timestamp

    Thread Safety:
        - Each method acquires and releases its own connection
        - Safe for concurrent use from multiple workers
    """

    def __init__(self):
        super().__init__()
        # Schema deployed via POST /api/dbadmin/maintenance?action=ensure

    # =========================================================================
    # RECORDING METHODS (called during execution)
    # =========================================================================

    def record_event(self, event: JobEvent) -> int:
        """
        Record a single event to the database.

        Args:
            event: JobEvent model with all fields populated

        Returns:
            event_id of the inserted record

        Raises:
            DatabaseError: If insert fails
        """
        with self._error_context("record event", event.job_id):
            query = sql.SQL("""
                INSERT INTO {}.job_events (
                    job_id, task_id, stage, event_type, event_status,
                    checkpoint_name, event_data, error_message, duration_ms, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING event_id
            """).format(sql.Identifier(self.schema_name))

            # Convert enum values to strings
            event_type_value = event.event_type.value if isinstance(event.event_type, JobEventType) else event.event_type
            event_status_value = event.event_status.value if isinstance(event.event_status, JobEventStatus) else event.event_status

            params = (
                event.job_id,
                event.task_id,
                event.stage,
                event_type_value,
                event_status_value,
                event.checkpoint_name,
                json.dumps(event.event_data) if event.event_data else '{}',
                event.error_message,
                event.duration_ms,
                event.created_at or datetime.now(timezone.utc)
            )

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                    conn.commit()
                    event_id = result['event_id']  # dict_row returns dict, not tuple

                    logger.debug(
                        f"Recorded event {event_id}: {event_type_value} for job {event.job_id[:16]}..."
                    )
                    return event_id

    def record_job_event(
        self,
        job_id: str,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        stage: Optional[int] = None,
        checkpoint_name: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> int:
        """
        Convenience method for recording job-level events.

        Args:
            job_id: Job ID
            event_type: Type of event (e.g., JOB_CREATED, STAGE_STARTED)
            event_status: Outcome status (default: INFO)
            stage: Stage number if relevant
            checkpoint_name: App Insights checkpoint for correlation
            event_data: Additional context data
            error_message: Error message if failure

        Returns:
            event_id of the inserted record
        """
        event = JobEvent.create_job_event(
            job_id=job_id,
            event_type=event_type,
            event_status=event_status,
            checkpoint_name=checkpoint_name,
            event_data=event_data,
            error_message=error_message
        )
        # Add stage if provided
        if stage is not None:
            event.stage = stage

        return self.record_event(event)

    def record_task_event(
        self,
        job_id: str,
        task_id: str,
        stage: int,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        checkpoint_name: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> int:
        """
        Convenience method for recording task-level events.

        Args:
            job_id: Parent job ID
            task_id: Task ID
            stage: Stage number
            event_type: Type of event (e.g., TASK_STARTED, TASK_COMPLETED)
            event_status: Outcome status (default: INFO)
            checkpoint_name: App Insights checkpoint for correlation
            event_data: Additional context data
            error_message: Error message if failure
            duration_ms: Operation duration in milliseconds

        Returns:
            event_id of the inserted record
        """
        event = JobEvent.create_task_event(
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            event_type=event_type,
            event_status=event_status,
            checkpoint_name=checkpoint_name,
            event_data=event_data,
            error_message=error_message,
            duration_ms=duration_ms
        )

        return self.record_event(event)

    # =========================================================================
    # QUERY METHODS (called by UI)
    # =========================================================================

    def get_events_for_job(
        self,
        job_id: str,
        limit: int = 100,
        event_types: Optional[List[JobEventType]] = None,
        since: Optional[datetime] = None,
        include_task_events: bool = True
    ) -> List[JobEvent]:
        """
        Get events for a job, optionally filtered.

        Args:
            job_id: Job ID to query
            limit: Maximum events to return (default 100)
            event_types: Filter by specific event types
            since: Only return events after this timestamp
            include_task_events: Include task-level events (default True)

        Returns:
            List of JobEvent objects, ordered by created_at DESC
        """
        with self._error_context("get events for job", job_id):
            # Build query with optional filters
            conditions = ["job_id = %s"]
            params = [job_id]

            if event_types:
                type_values = [et.value if isinstance(et, JobEventType) else et for et in event_types]
                placeholders = ", ".join(["%s"] * len(type_values))
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(type_values)

            if since:
                conditions.append("created_at > %s")
                params.append(since)

            if not include_task_events:
                conditions.append("task_id IS NULL")

            params.append(limit)

            query = sql.SQL("""
                SELECT event_id, job_id, task_id, stage, event_type, event_status,
                       checkpoint_name, event_data, error_message, duration_ms, created_at
                FROM {}.job_events
                WHERE {}
                ORDER BY created_at DESC
                LIMIT %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
            )

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

                    events = []
                    for row in rows:
                        events.append(self._row_to_event(row))

                    return events

    def get_events_for_task(self, task_id: str) -> List[JobEvent]:
        """
        Get all events for a specific task.

        Args:
            task_id: Task ID to query

        Returns:
            List of JobEvent objects, ordered by created_at ASC
        """
        with self._error_context("get events for task", task_id):
            query = sql.SQL("""
                SELECT event_id, job_id, task_id, stage, event_type, event_status,
                       checkpoint_name, event_data, error_message, duration_ms, created_at
                FROM {}.job_events
                WHERE task_id = %s
                ORDER BY created_at ASC
            """).format(sql.Identifier(self.schema_name))

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (task_id,))
                    rows = cur.fetchall()

                    return [self._row_to_event(row) for row in rows]

    def get_latest_event(self, job_id: str) -> Optional[JobEvent]:
        """
        Get the most recent event for a job.

        Args:
            job_id: Job ID to query

        Returns:
            Most recent JobEvent, or None if no events exist
        """
        with self._error_context("get latest event", job_id):
            query = sql.SQL("""
                SELECT event_id, job_id, task_id, stage, event_type, event_status,
                       checkpoint_name, event_data, error_message, duration_ms, created_at
                FROM {}.job_events
                WHERE job_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """).format(sql.Identifier(self.schema_name))

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id,))
                    row = cur.fetchone()

                    if row:
                        return self._row_to_event(row)
                    return None

    def get_event_counts_by_type(self, job_id: str) -> Dict[str, int]:
        """
        Get count of events by type for a job.

        Args:
            job_id: Job ID to query

        Returns:
            Dict mapping event_type to count
        """
        with self._error_context("get event counts", job_id):
            query = sql.SQL("""
                SELECT event_type, COUNT(*) as count
                FROM {}.job_events
                WHERE job_id = %s
                GROUP BY event_type
                ORDER BY count DESC
            """).format(sql.Identifier(self.schema_name))

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id,))
                    rows = cur.fetchall()

                    return {row['event_type']: row['count'] for row in rows}  # dict_row

    def get_event_summary(self, job_id: str) -> Dict[str, Any]:
        """
        Get event summary statistics for a job.

        Args:
            job_id: Job ID to query

        Returns:
            Dict with:
                - total_events: Total event count
                - by_type: Counts by event type
                - by_status: Counts by event status
                - first_event: Timestamp of first event
                - last_event: Timestamp of last event
                - total_duration_ms: Sum of all duration_ms values
        """
        with self._error_context("get event summary", job_id):
            query = sql.SQL("""
                SELECT
                    COUNT(*) as total_events,
                    MIN(created_at) as first_event,
                    MAX(created_at) as last_event,
                    SUM(COALESCE(duration_ms, 0)) as total_duration_ms
                FROM {}.job_events
                WHERE job_id = %s
            """).format(sql.Identifier(self.schema_name))

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id,))
                    row = cur.fetchone()

                    # Get counts by type
                    by_type = self.get_event_counts_by_type(job_id)

                    # Get counts by status
                    status_query = sql.SQL("""
                        SELECT event_status, COUNT(*) as count
                        FROM {}.job_events
                        WHERE job_id = %s
                        GROUP BY event_status
                    """).format(sql.Identifier(self.schema_name))

                    cur.execute(status_query, (job_id,))
                    status_rows = cur.fetchall()
                    by_status = {r['event_status']: r['count'] for r in status_rows}  # dict_row

                    return {
                        'total_events': row['total_events'] or 0,
                        'by_type': by_type,
                        'by_status': by_status,
                        'first_event': row['first_event'].isoformat() if row['first_event'] else None,
                        'last_event': row['last_event'].isoformat() if row['last_event'] else None,
                        'total_duration_ms': row['total_duration_ms'] or 0
                    }

    def get_events_timeline(
        self,
        job_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get events formatted for timeline display.

        Args:
            job_id: Job ID to query
            limit: Maximum events to return

        Returns:
            List of dicts with:
                - event_id
                - timestamp (formatted)
                - event_type
                - event_status
                - summary (human-readable)
                - duration_ms (if available)
                - task_id (if task-level)
                - stage
        """
        events = self.get_events_for_job(job_id, limit=limit)

        timeline = []
        for event in events:
            timeline.append({
                'event_id': event.event_id,
                'timestamp': event.created_at.isoformat() if event.created_at else None,
                'timestamp_display': self._format_timestamp(event.created_at),
                'event_type': event.event_type.value if isinstance(event.event_type, JobEventType) else event.event_type,
                'event_type_display': self._format_event_type(event.event_type),
                'event_status': event.event_status.value if isinstance(event.event_status, JobEventStatus) else event.event_status,
                'summary': self._generate_event_summary(event),
                'duration_ms': event.duration_ms,
                'task_id': event.task_id,
                'task_id_short': event.task_id[:8] if event.task_id else None,
                'stage': event.stage,
                'checkpoint_name': event.checkpoint_name,
                'event_data': event.event_data,
                'error_message': event.error_message
            })

        return timeline

    def get_failure_context(
        self,
        job_id: str,
        preceding_count: int = 10
    ) -> Dict[str, Any]:
        """
        Get failure event and preceding events for debugging.

        Args:
            job_id: Job ID to query
            preceding_count: Number of events before failure to include

        Returns:
            Dict with:
                - failure_event: The failure event (if any)
                - preceding_events: Events before the failure
                - has_failure: Boolean indicating if job has a failure
        """
        with self._error_context("get failure context", job_id):
            # Find the first failure event
            query = sql.SQL("""
                SELECT event_id, job_id, task_id, stage, event_type, event_status,
                       checkpoint_name, event_data, error_message, duration_ms, created_at
                FROM {}.job_events
                WHERE job_id = %s AND event_status = 'failure'
                ORDER BY created_at ASC
                LIMIT 1
            """).format(sql.Identifier(self.schema_name))

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id,))
                    failure_row = cur.fetchone()

                    if not failure_row:
                        return {
                            'failure_event': None,
                            'preceding_events': [],
                            'has_failure': False
                        }

                    failure_event = self._row_to_event(failure_row)

                    # Get preceding events
                    preceding_query = sql.SQL("""
                        SELECT event_id, job_id, task_id, stage, event_type, event_status,
                               checkpoint_name, event_data, error_message, duration_ms, created_at
                        FROM {}.job_events
                        WHERE job_id = %s AND created_at < %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(sql.Identifier(self.schema_name))

                    cur.execute(preceding_query, (job_id, failure_event.created_at, preceding_count))
                    preceding_rows = cur.fetchall()

                    # Reverse to chronological order
                    preceding_events = [self._row_to_event(row) for row in reversed(preceding_rows)]

                    return {
                        'failure_event': failure_event,
                        'preceding_events': preceding_events,
                        'has_failure': True
                    }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _row_to_event(self, row: Dict[str, Any]) -> JobEvent:
        """Convert database row (dict from dict_row) to JobEvent object."""
        return JobEvent(
            event_id=row['event_id'],
            job_id=row['job_id'],
            task_id=row['task_id'],
            stage=row['stage'],
            event_type=JobEventType(row['event_type']) if row['event_type'] else None,
            event_status=JobEventStatus(row['event_status']) if row['event_status'] else JobEventStatus.INFO,
            checkpoint_name=row['checkpoint_name'],
            event_data=row['event_data'] if row['event_data'] else {},
            error_message=row['error_message'],
            duration_ms=row['duration_ms'],
            created_at=row['created_at']
        )

    def _format_timestamp(self, ts: Optional[datetime]) -> str:
        """Format timestamp for display."""
        if not ts:
            return ""
        return ts.strftime("%H:%M:%S")

    def _format_event_type(self, event_type: JobEventType) -> str:
        """Format event type for human-readable display."""
        if isinstance(event_type, JobEventType):
            event_type = event_type.value

        # Convert snake_case to Title Case
        return event_type.replace("_", " ").title()

    def _generate_event_summary(self, event: JobEvent) -> str:
        """Generate human-readable summary for an event."""
        event_type = event.event_type.value if isinstance(event.event_type, JobEventType) else event.event_type

        if event_type == "job_created":
            job_type = event.event_data.get("job_type", "unknown")
            return f"Job created ({job_type})"

        elif event_type == "job_started":
            return "Job execution started"

        elif event_type == "job_completed":
            return "Job completed successfully"

        elif event_type == "job_failed":
            return f"Job failed: {event.error_message or 'Unknown error'}"

        elif event_type == "stage_started":
            stage_name = event.event_data.get("stage_name", f"Stage {event.stage}")
            return f"Started {stage_name}"

        elif event_type == "stage_completed":
            return f"Stage {event.stage} completed"

        elif event_type == "task_queued":
            task_type = event.event_data.get("task_type", "task")
            queue = event.event_data.get("queue", "")
            return f"Queued {task_type}" + (f" → {queue}" if queue else "")

        elif event_type == "task_started":
            return f"Task started"

        elif event_type == "task_completed":
            duration = f" ({event.duration_ms}ms)" if event.duration_ms else ""
            return f"Task completed{duration}"

        elif event_type == "task_failed":
            return f"Task failed: {event.error_message or 'Unknown error'}"

        elif event_type == "task_retrying":
            attempt = event.event_data.get("attempt", "?")
            return f"Retrying task (attempt {attempt})"

        elif event_type == "checkpoint":
            return event.checkpoint_name or "Checkpoint reached"

        elif event_type == "callback_started":
            return "Platform callback started"

        elif event_type == "callback_success":
            return "Platform callback succeeded"

        elif event_type == "callback_failed":
            return f"Platform callback failed: {event.error_message or 'Unknown error'}"

        else:
            return event_type.replace("_", " ").title()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['JobEventRepository']
