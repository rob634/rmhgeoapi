# ============================================================================
# CLAUDE CONTEXT - SNAPSHOT REPOSITORY
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Infrastructure - Database repository for system snapshots
# PURPOSE: CRUD operations for app.system_snapshots table
# LAST_REVIEWED: 26 MAR 2026
# EXPORTS: SnapshotRepository
# DEPENDENCIES: infrastructure.postgresql, core.models
# ============================================================================
"""
Snapshot Repository.

Database access layer for system configuration snapshots.
Moved from services/snapshot_service.py (26 MAR 2026) to follow the
repository-in-infrastructure convention.
"""

import json
from typing import List, Optional

from psycopg import sql

from core.models import SystemSnapshotRecord, SnapshotTriggerType
from infrastructure.postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "SnapshotRepository")


class SnapshotRepository(PostgreSQLRepository):
    """
    Repository for system snapshot database operations.

    Handles CRUD operations for app.system_snapshots table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "system_snapshots"
        self.schema = "app"

    def save(self, snapshot: SystemSnapshotRecord) -> SystemSnapshotRecord:
        """
        Save a system snapshot to the database.

        Args:
            snapshot: SystemSnapshotRecord to insert

        Returns:
            Created snapshot with snapshot_id populated
        """
        logger.info(f"Saving snapshot: trigger={snapshot.trigger_type.value}, hash={snapshot.config_hash[:16]}...")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            captured_at, trigger_type, instance_id, role_instance_id,
                            config_hash, environment_type, sku, region,
                            vnet_private_ip, dns_server, vnet_route_all,
                            worker_process_count,
                            config_from_env_count, config_defaults_count, discovered_var_count,
                            full_snapshot,
                            has_drift, drift_details, previous_snapshot_id,
                            app_version, notes
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s,
                            %s, %s
                        )
                        RETURNING snapshot_id
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        snapshot.captured_at,
                        snapshot.trigger_type.value,
                        snapshot.instance_id,
                        snapshot.role_instance_id,
                        snapshot.config_hash,
                        snapshot.environment_type,
                        snapshot.sku,
                        snapshot.region,
                        snapshot.vnet_private_ip,
                        snapshot.dns_server,
                        snapshot.vnet_route_all,
                        snapshot.worker_process_count,
                        snapshot.config_from_env_count,
                        snapshot.config_defaults_count,
                        snapshot.discovered_var_count,
                        json.dumps(snapshot.full_snapshot),
                        snapshot.has_drift,
                        json.dumps(snapshot.drift_details) if snapshot.drift_details else None,
                        snapshot.previous_snapshot_id,
                        snapshot.app_version,
                        snapshot.notes
                    )
                )
                row = cur.fetchone()
                conn.commit()

                # psycopg3 returns dict_row by default
                snapshot.snapshot_id = row['snapshot_id']
                logger.info(f"Saved snapshot: id={snapshot.snapshot_id}")
                return snapshot

    def get_latest(self, instance_id: Optional[str] = None) -> Optional[SystemSnapshotRecord]:
        """
        Get the most recent snapshot.

        Args:
            instance_id: If provided, get latest for this instance only

        Returns:
            Most recent SystemSnapshotRecord or None
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if instance_id:
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {}.{}
                            WHERE instance_id = %s
                            ORDER BY captured_at DESC
                            LIMIT 1
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (instance_id,)
                    )
                else:
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {}.{}
                            ORDER BY captured_at DESC
                            LIMIT 1
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        )
                    )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_id(self, snapshot_id: int) -> Optional[SystemSnapshotRecord]:
        """Get a snapshot by ID."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE snapshot_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (snapshot_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_with_drift(self, limit: int = 50) -> List[SystemSnapshotRecord]:
        """
        List snapshots where drift was detected.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of snapshots with has_drift=True
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE has_drift = true
                        ORDER BY captured_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (limit,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_recent(self, hours: int = 24, limit: int = 100) -> List[SystemSnapshotRecord]:
        """
        List recent snapshots.

        Args:
            hours: How many hours back to look
            limit: Maximum records to return

        Returns:
            List of recent SystemSnapshotRecords
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE captured_at > NOW() - INTERVAL '%s hours'
                        ORDER BY captured_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (hours, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row) -> Optional[SystemSnapshotRecord]:
        """Convert database row to Pydantic model."""
        if not row:
            return None

        # psycopg3 returns dict_row by default - use column names
        full_snapshot = row['full_snapshot']
        drift_details = row['drift_details']

        return SystemSnapshotRecord(
            snapshot_id=row['snapshot_id'],
            captured_at=row['captured_at'],
            trigger_type=SnapshotTriggerType(row['trigger_type']),
            instance_id=row['instance_id'],
            role_instance_id=row['role_instance_id'],
            config_hash=row['config_hash'],
            environment_type=row['environment_type'],
            sku=row['sku'],
            region=row['region'],
            vnet_private_ip=row['vnet_private_ip'],
            dns_server=row['dns_server'],
            vnet_route_all=row['vnet_route_all'],
            worker_process_count=row['worker_process_count'],
            config_from_env_count=row['config_from_env_count'],
            config_defaults_count=row['config_defaults_count'],
            discovered_var_count=row['discovered_var_count'],
            full_snapshot=full_snapshot if isinstance(full_snapshot, dict) else json.loads(full_snapshot) if full_snapshot else {},
            has_drift=row['has_drift'],
            drift_details=drift_details if isinstance(drift_details, dict) else json.loads(drift_details) if drift_details else None,
            previous_snapshot_id=row['previous_snapshot_id'],
            app_version=row['app_version'],
            notes=row['notes']
        )


__all__ = ['SnapshotRepository']
