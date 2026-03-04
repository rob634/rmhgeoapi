# ============================================================================
# CLAUDE CONTEXT - RELEASE AUDIT REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Append-only audit event CRUD
# PURPOSE: Database operations for app.release_audit table
# CREATED: 03 MAR 2026
# LAST_REVIEWED: 03 MAR 2026
# ============================================================================
"""
Release Audit Repository - Append-Only Event Log.

Provides write and read operations for the release_audit table.
This is append-only: no update or delete methods.

Methods:
    record_event(...) - Insert audit event (non-fatal on failure)
    get_events_for_release(release_id) - All events for a release
    get_events_for_ordinal(asset_id, version_ordinal) - Events across revisions
    get_events_by_type(event_type, limit) - Filter by event type
    get_recent_events(hours, limit) - Recent events

Exports:
    ReleaseAuditRepository: Append-only audit CRUD
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from core.models.release_audit import ReleaseAuditEvent, ReleaseAuditEventType

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ReleaseAudit")


class ReleaseAuditRepository(PostgreSQLRepository):
    """
    Repository for release audit event operations.

    Append-only: record_event() inserts, read methods query.
    No update or delete — audit log is immutable.
    """

    def __init__(self):
        super().__init__()
        self.table = "release_audit"
        self.schema = "app"

    def record_event(
        self,
        release_id: str,
        asset_id: str,
        version_ordinal: int,
        revision: int,
        event_type: ReleaseAuditEventType,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        Record a release audit event. Returns audit_id or None on failure.

        This method is designed to be called inside a try/except by the caller.
        Audit emission must NEVER block the pipeline.
        """
        logger.info(
            f"Audit: {event_type.value} for release {release_id[:16]}... "
            f"(ord={version_ordinal}, rev={revision})"
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{}
                            (release_id, asset_id, version_ordinal, revision,
                             event_type, actor, reason, snapshot, metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
                        RETURNING audit_id
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        release_id,
                        asset_id,
                        version_ordinal,
                        revision,
                        event_type.value,
                        actor,
                        reason,
                        json.dumps(snapshot or {}),
                        json.dumps(metadata or {}),
                    )
                )
                row = cur.fetchone()
                conn.commit()
                audit_id = row['audit_id'] if row else None
                if audit_id:
                    logger.info(f"Audit event {audit_id} recorded")
                return audit_id

    def get_events_for_release(self, release_id: str) -> List[ReleaseAuditEvent]:
        """All events for a release, ordered chronologically."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE release_id = %s
                        ORDER BY created_at ASC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                rows = cur.fetchall()
                return [self._row_to_event(row) for row in rows]

    def get_events_for_ordinal(
        self, asset_id: str, version_ordinal: int
    ) -> List[ReleaseAuditEvent]:
        """All events for an ordinal across all revisions."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND version_ordinal = %s
                        ORDER BY created_at ASC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, version_ordinal)
                )
                rows = cur.fetchall()
                return [self._row_to_event(row) for row in rows]

    def get_events_by_type(
        self, event_type: ReleaseAuditEventType, limit: int = 50
    ) -> List[ReleaseAuditEvent]:
        """Recent events of a specific type."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE event_type = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (event_type.value, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_event(row) for row in rows]

    def get_recent_events(
        self, hours: int = 24, limit: int = 100
    ) -> List[ReleaseAuditEvent]:
        """Recent audit events across all releases."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE created_at >= NOW() - make_interval(hours => %s)
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (hours, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: Dict[str, Any]) -> ReleaseAuditEvent:
        """Convert database row dict to ReleaseAuditEvent model."""
        snapshot = row.get('snapshot', {})
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        meta = row.get('metadata', {})
        if isinstance(meta, str):
            meta = json.loads(meta)

        return ReleaseAuditEvent(
            audit_id=row.get('audit_id'),
            release_id=row['release_id'],
            asset_id=row['asset_id'],
            version_ordinal=row['version_ordinal'],
            revision=row['revision'],
            event_type=ReleaseAuditEventType(row['event_type']),
            actor=row.get('actor'),
            reason=row.get('reason'),
            snapshot=snapshot,
            metadata=meta,
            created_at=row['created_at'],
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ReleaseAuditRepository',
]
