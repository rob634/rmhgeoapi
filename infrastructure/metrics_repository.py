# ============================================================================
# METRICS REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Pipeline observability metrics storage
# PURPOSE: PostgreSQL storage for real-time job progress metrics
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Pipeline Observability Metrics Repository.

Provides PostgreSQL storage for real-time job progress metrics, enabling
dashboard polling and historical analysis of long-running jobs.

Table: app.job_metrics
-----------------------
Stores periodic snapshots of job progress with context-specific payloads.
Auto-created on first use (self-bootstrapping pattern).

Schema:
    id: SERIAL PRIMARY KEY
    job_id: VARCHAR(64) - Reference to app.jobs
    timestamp: TIMESTAMPTZ - When snapshot was taken
    metric_type: VARCHAR(50) - 'snapshot', 'event', 'error'
    payload: JSONB - Progress data, rates, context-specific metrics

Usage:
------
```python
from infrastructure.metrics_repository import MetricsRepository

repo = MetricsRepository()

# Write a snapshot
repo.write_snapshot(
    job_id="abc123",
    metric_type="snapshot",
    payload={
        "progress": {"stage": 2, "tasks_completed": 10},
        "rates": {"tasks_per_minute": 5.2},
        "context": {"cells_processed": 5000}
    }
)

# Get latest snapshot for a job
latest = repo.get_latest(job_id="abc123")

# Get history for a job
history = repo.get_history(job_id="abc123", limit=100)

# Cleanup old metrics
deleted = repo.cleanup(retention_minutes=60)
```
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)


class MetricsRepository(PostgreSQLRepository):
    """
    Repository for pipeline observability metrics.

    Stores job progress snapshots in app.job_metrics table.
    Self-bootstrapping: creates table on first use if not exists.

    Inherits from PostgreSQLRepository for connection management.
    """

    def __init__(self):
        """Initialize with app schema."""
        super().__init__(schema_name='app')
        self._table_ensured = False

    def _ensure_table(self):
        """
        Ensure job_metrics table exists (self-bootstrapping).

        Creates table on first use if not exists.
        Thread-safe via PostgreSQL's CREATE TABLE IF NOT EXISTS.
        """
        if self._table_ensured:
            return

        create_sql = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {schema}.job_metrics (
                id SERIAL PRIMARY KEY,
                job_id VARCHAR(64) NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metric_type VARCHAR(50) NOT NULL DEFAULT 'snapshot',
                payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,

                -- Constraints
                CONSTRAINT job_metrics_type_check
                    CHECK (metric_type IN ('snapshot', 'event', 'error', 'debug'))
            );

            -- Indexes for efficient querying
            CREATE INDEX IF NOT EXISTS idx_job_metrics_job_id
                ON {schema}.job_metrics(job_id);
            CREATE INDEX IF NOT EXISTS idx_job_metrics_timestamp
                ON {schema}.job_metrics(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_job_metrics_job_timestamp
                ON {schema}.job_metrics(job_id, timestamp DESC);
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(create_sql)
                conn.commit()
            self._table_ensured = True
            logger.info(f"Ensured {self.schema_name}.job_metrics table exists")
        except Exception as e:
            logger.error(f"Failed to ensure job_metrics table: {e}")
            raise

    def write_snapshot(
        self,
        job_id: str,
        metric_type: str,
        payload: Dict[str, Any]
    ) -> int:
        """
        Write a metrics snapshot to the database.

        Args:
            job_id: Job identifier
            metric_type: Type of metric ('snapshot', 'event', 'error', 'debug')
            payload: Metrics data as dictionary

        Returns:
            int: ID of inserted row
        """
        self._ensure_table()

        insert_sql = sql.SQL("""
            INSERT INTO {schema}.job_metrics (job_id, metric_type, payload)
            VALUES (%s, %s, %s)
            RETURNING id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(insert_sql, (job_id, metric_type, payload))
                    row_id = cur.fetchone()['id']  # dict_row returns dict, not tuple
                conn.commit()
            return row_id
        except Exception as e:
            logger.error(f"Failed to write metrics snapshot: {e}")
            raise

    def write_batch(
        self,
        snapshots: List[Dict[str, Any]]
    ) -> int:
        """
        Write multiple snapshots in a single transaction.

        Args:
            snapshots: List of dicts with job_id, metric_type, payload

        Returns:
            int: Number of rows inserted
        """
        if not snapshots:
            return 0

        self._ensure_table()

        insert_sql = sql.SQL("""
            INSERT INTO {schema}.job_metrics (job_id, metric_type, payload)
            VALUES (%s, %s, %s)
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    for snapshot in snapshots:
                        cur.execute(insert_sql, (
                            snapshot['job_id'],
                            snapshot.get('metric_type', 'snapshot'),
                            snapshot.get('payload', {})
                        ))
                conn.commit()
            return len(snapshots)
        except Exception as e:
            logger.error(f"Failed to write metrics batch: {e}")
            raise

    def get_latest(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent snapshot for a job.

        Args:
            job_id: Job identifier

        Returns:
            Latest snapshot dict or None if not found
        """
        self._ensure_table()

        query = sql.SQL("""
            SELECT id, job_id, timestamp, metric_type, payload
            FROM {schema}.job_metrics
            WHERE job_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id,))
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    return None
        except Exception as e:
            logger.error(f"Failed to get latest metrics: {e}")
            raise

    def get_history(
        self,
        job_id: str,
        limit: int = 100,
        metric_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get metrics history for a job.

        Args:
            job_id: Job identifier
            limit: Maximum number of records to return
            metric_type: Optional filter by metric type

        Returns:
            List of snapshot dicts, most recent first
        """
        self._ensure_table()

        if metric_type:
            query = sql.SQL("""
                SELECT id, job_id, timestamp, metric_type, payload
                FROM {schema}.job_metrics
                WHERE job_id = %s AND metric_type = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (job_id, metric_type, limit)
        else:
            query = sql.SQL("""
                SELECT id, job_id, timestamp, metric_type, payload
                FROM {schema}.job_metrics
                WHERE job_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (job_id, limit)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get metrics history: {e}")
            raise

    def get_active_jobs(self, minutes: int = 15) -> List[Dict[str, Any]]:
        """
        Get jobs with recent metrics activity.

        Args:
            minutes: Look back window in minutes

        Returns:
            List of job summaries with latest metrics
        """
        self._ensure_table()

        query = sql.SQL("""
            WITH recent_jobs AS (
                SELECT DISTINCT job_id
                FROM {schema}.job_metrics
                WHERE timestamp > NOW() - INTERVAL '%s minutes'
            ),
            latest_metrics AS (
                SELECT DISTINCT ON (m.job_id)
                    m.job_id,
                    m.timestamp,
                    m.metric_type,
                    m.payload
                FROM {schema}.job_metrics m
                JOIN recent_jobs r ON m.job_id = r.job_id
                ORDER BY m.job_id, m.timestamp DESC
            )
            SELECT
                lm.job_id,
                lm.timestamp as last_activity,
                lm.payload,
                j.job_type,
                j.status as job_status
            FROM latest_metrics lm
            LEFT JOIN {schema}.jobs j ON lm.job_id = j.job_id
            ORDER BY lm.timestamp DESC
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (minutes,))
                    return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get active jobs: {e}")
            raise

    def cleanup(self, retention_minutes: int = 60) -> int:
        """
        Delete metrics older than retention period.

        Args:
            retention_minutes: Delete metrics older than this many minutes

        Returns:
            int: Number of rows deleted
        """
        self._ensure_table()

        delete_sql = sql.SQL("""
            DELETE FROM {schema}.job_metrics
            WHERE timestamp < NOW() - INTERVAL '%s minutes'
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(delete_sql, (retention_minutes,))
                    deleted = cur.rowcount
                conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old metrics records")
            return deleted
        except Exception as e:
            logger.error(f"Failed to cleanup metrics: {e}")
            raise

    def get_job_summary(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get aggregated summary for a job's metrics.

        Args:
            job_id: Job identifier

        Returns:
            Summary dict with counts, time range, latest payload
        """
        self._ensure_table()

        query = sql.SQL("""
            SELECT
                job_id,
                COUNT(*) as total_snapshots,
                MIN(timestamp) as first_activity,
                MAX(timestamp) as last_activity,
                EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) as duration_seconds,
                (
                    SELECT payload
                    FROM {schema}.job_metrics
                    WHERE job_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                ) as latest_payload
            FROM {schema}.job_metrics
            WHERE job_id = %s
            GROUP BY job_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (job_id, job_id))
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    return None
        except Exception as e:
            logger.error(f"Failed to get job summary: {e}")
            raise


# Export
__all__ = ["MetricsRepository"]
