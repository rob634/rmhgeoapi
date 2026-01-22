# ============================================================================
# CLAUDE CONTEXT - EXTERNAL SERVICE REPOSITORY
# ============================================================================
# STATUS: Infrastructure - External service registry CRUD operations
# PURPOSE: Database operations for app.external_services table
# CREATED: 22 JAN 2026
# LAST_REVIEWED: 22 JAN 2026
# ============================================================================
"""
External Service Repository - Geospatial Service Registry.

Provides CRUD operations for the external service registry table.
Supports service registration, health tracking, and monitoring queries.

Architecture:
    - Single table (app.external_services)
    - service_id = SHA256(url)[:32] for idempotent registration
    - JSONB fields for capabilities, history, metadata, tags

Methods:
    create(service) - Register new service
    get_by_id(service_id) - Lookup by ID
    get_by_url(url) - Lookup by URL (generates ID from URL)
    get_all(filters) - List services with optional filters
    update(service_id, updates) - Update service fields
    delete(service_id) - Remove service
    get_services_due_for_check() - Get services needing health check
    update_health_result(service_id, result) - Update after health check

Exports:
    ExternalServiceRepository: Service registry CRUD repository
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from core.models.external_service import ExternalService, ServiceType, ServiceStatus

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "external_service")


class ExternalServiceRepository(PostgreSQLRepository):
    """
    Repository for external service registry CRUD operations.

    Uses app.external_services table for service tracking and health monitoring.
    All queries use psycopg.sql composition for safety.

    Table: app.external_services
        service_id VARCHAR(32) PRIMARY KEY  -- SHA256(url)[:32]
        url TEXT NOT NULL
        service_type service_type NOT NULL
        detection_confidence FLOAT
        name VARCHAR(255) NOT NULL
        description TEXT
        tags JSONB
        status service_status NOT NULL
        enabled BOOLEAN
        detected_capabilities JSONB
        health_history JSONB
        last_response_ms INTEGER
        avg_response_ms INTEGER
        consecutive_failures INTEGER
        last_failure_reason VARCHAR(500)
        check_interval_minutes INTEGER
        last_check_at TIMESTAMPTZ
        next_check_at TIMESTAMPTZ
        metadata JSONB
        created_at TIMESTAMPTZ
        updated_at TIMESTAMPTZ
    """

    def __init__(self):
        super().__init__()
        # Schema deployed centrally via POST /api/dbadmin/maintenance?action=ensure&confirm=yes

    def create(self, service: ExternalService) -> ExternalService:
        """
        Insert new service record.

        Args:
            service: ExternalService model with all required fields

        Returns:
            ExternalService with database-assigned values
        """
        with self._error_context("service creation", service.service_id):
            query = sql.SQL("""
                INSERT INTO {}.external_services (
                    service_id, url, service_type, detection_confidence,
                    name, description, tags, status, enabled,
                    detected_capabilities, health_history,
                    last_response_ms, avg_response_ms,
                    consecutive_failures, last_failure_reason,
                    check_interval_minutes, last_check_at, next_check_at,
                    metadata, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
            """).format(sql.Identifier(self.schema_name))

            params = (
                service.service_id,
                service.url,
                service.service_type.value if isinstance(service.service_type, ServiceType) else service.service_type,
                service.detection_confidence,
                service.name,
                service.description,
                json.dumps(service.tags),
                service.status.value if isinstance(service.status, ServiceStatus) else service.status,
                service.enabled,
                json.dumps(service.detected_capabilities),
                json.dumps(service.health_history),
                service.last_response_ms,
                service.avg_response_ms,
                service.consecutive_failures,
                service.last_failure_reason,
                service.check_interval_minutes,
                service.last_check_at,
                service.next_check_at,
                json.dumps(service.metadata),
                service.created_at or datetime.now(timezone.utc),
                service.updated_at or datetime.now(timezone.utc),
            )

            row = self._execute_query(query, params, fetch='one')
            return self._row_to_service(row)

    def get_by_id(self, service_id: str) -> Optional[ExternalService]:
        """
        Get service by ID.

        Args:
            service_id: Service identifier (SHA256(url)[:32])

        Returns:
            ExternalService if found, None otherwise
        """
        with self._error_context("service lookup by id", service_id):
            query = sql.SQL("""
                SELECT * FROM {}.external_services WHERE service_id = %s
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(query, (service_id,), fetch='one')
            return self._row_to_service(row) if row else None

    def get_by_url(self, url: str) -> Optional[ExternalService]:
        """
        Get service by URL (computes service_id from URL).

        Args:
            url: Service endpoint URL

        Returns:
            ExternalService if found, None otherwise
        """
        service_id = ExternalService.generate_service_id(url)
        return self.get_by_id(service_id)

    def get_all(
        self,
        status: Optional[ServiceStatus] = None,
        service_type: Optional[ServiceType] = None,
        enabled: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ExternalService]:
        """
        Get all services with optional filters.

        Args:
            status: Optional status filter
            service_type: Optional service type filter
            enabled: Optional enabled filter
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of ExternalService records
        """
        with self._error_context("service list", f"status={status}, type={service_type}"):
            conditions = []
            params = []

            if status is not None:
                conditions.append("status = %s")
                params.append(status.value if isinstance(status, ServiceStatus) else status)

            if service_type is not None:
                conditions.append("service_type = %s")
                params.append(service_type.value if isinstance(service_type, ServiceType) else service_type)

            if enabled is not None:
                conditions.append("enabled = %s")
                params.append(enabled)

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            query = sql.SQL("""
                SELECT * FROM {}.external_services
                WHERE {}
                ORDER BY name
                LIMIT %s OFFSET %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.SQL(where_clause)
            )

            params.extend([limit, offset])
            rows = self._execute_query(query, tuple(params), fetch='all')
            return [self._row_to_service(row) for row in rows]

    def update(
        self,
        service_id: str,
        updates: Dict[str, Any]
    ) -> Optional[ExternalService]:
        """
        Update service fields.

        Args:
            service_id: Service to update
            updates: Dictionary of field -> value updates

        Returns:
            Updated ExternalService or None if not found
        """
        if not updates:
            return self.get_by_id(service_id)

        with self._error_context("service update", service_id):
            # Build SET clause dynamically
            set_parts = []
            params = []

            allowed_fields = {
                'service_type', 'detection_confidence', 'name', 'description',
                'tags', 'status', 'enabled', 'detected_capabilities',
                'health_history', 'last_response_ms', 'avg_response_ms',
                'consecutive_failures', 'last_failure_reason',
                'check_interval_minutes', 'last_check_at', 'next_check_at', 'metadata'
            }

            for field, value in updates.items():
                if field not in allowed_fields:
                    continue

                set_parts.append(f"{field} = %s")

                # Handle special serialization
                if field in ('tags', 'detected_capabilities', 'health_history', 'metadata'):
                    params.append(json.dumps(value))
                elif field == 'service_type' and isinstance(value, ServiceType):
                    params.append(value.value)
                elif field == 'status' and isinstance(value, ServiceStatus):
                    params.append(value.value)
                else:
                    params.append(value)

            if not set_parts:
                return self.get_by_id(service_id)

            # Always update updated_at
            set_parts.append("updated_at = NOW()")

            params.append(service_id)

            query = sql.SQL("""
                UPDATE {}.external_services
                SET {}
                WHERE service_id = %s
                RETURNING *
            """).format(
                sql.Identifier(self.schema_name),
                sql.SQL(", ".join(set_parts))
            )

            row = self._execute_query(query, tuple(params), fetch='one')
            return self._row_to_service(row) if row else None

    def delete(self, service_id: str) -> bool:
        """
        Delete service record.

        Args:
            service_id: Service to delete

        Returns:
            True if deleted, False if not found
        """
        with self._error_context("service delete", service_id):
            query = sql.SQL("""
                DELETE FROM {}.external_services
                WHERE service_id = %s
                RETURNING service_id
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(query, (service_id,), fetch='one')
            return row is not None

    def get_services_due_for_check(self, limit: int = 50) -> List[ExternalService]:
        """
        Get services that are due for health checking.

        Returns services where:
        - enabled = true
        - next_check_at <= NOW() OR next_check_at IS NULL

        Args:
            limit: Maximum number of services to return

        Returns:
            List of services needing health check
        """
        with self._error_context("services due for check", f"limit={limit}"):
            query = sql.SQL("""
                SELECT * FROM {}.external_services
                WHERE enabled = true
                  AND (next_check_at <= NOW() OR next_check_at IS NULL)
                ORDER BY next_check_at NULLS FIRST
                LIMIT %s
            """).format(sql.Identifier(self.schema_name))

            rows = self._execute_query(query, (limit,), fetch='all')
            return [self._row_to_service(row) for row in rows]

    def update_health_result(
        self,
        service_id: str,
        success: bool,
        response_ms: Optional[int],
        error: Optional[str] = None,
        new_status: Optional[ServiceStatus] = None
    ) -> Optional[ExternalService]:
        """
        Update service after health check.

        Updates health_history, response times, consecutive failures,
        status, and schedules next check.

        Args:
            service_id: Service to update
            success: Whether check was successful
            response_ms: Response time in milliseconds
            error: Error message if failed
            new_status: Optional status override

        Returns:
            Updated ExternalService or None if not found
        """
        with self._error_context("health result update", service_id):
            # Get current service
            service = self.get_by_id(service_id)
            if not service:
                return None

            # Update health history
            service.add_health_check_result(success, response_ms, error)

            # Update consecutive failures
            if success:
                consecutive_failures = 0
                last_failure_reason = None
            else:
                consecutive_failures = service.consecutive_failures + 1
                last_failure_reason = error

            # Determine status if not provided
            if new_status is None:
                if success:
                    new_status = ServiceStatus.ACTIVE
                elif consecutive_failures >= 3:
                    new_status = ServiceStatus.OFFLINE
                else:
                    new_status = service.status

            # Schedule next check
            next_check_at = datetime.now(timezone.utc) + timedelta(
                minutes=service.check_interval_minutes
            )

            # Update
            updates = {
                'health_history': service.health_history,
                'last_response_ms': response_ms if success else service.last_response_ms,
                'avg_response_ms': service.avg_response_ms,
                'consecutive_failures': consecutive_failures,
                'last_failure_reason': last_failure_reason,
                'status': new_status,
                'last_check_at': datetime.now(timezone.utc),
                'next_check_at': next_check_at
            }

            return self.update(service_id, updates)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get service statistics.

        Returns:
            Statistics dictionary with counts by status and type
        """
        with self._error_context("service stats", "all"):
            query = sql.SQL("""
                SELECT
                    COUNT(*) as total_services,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                    COUNT(CASE WHEN status = 'degraded' THEN 1 END) as degraded,
                    COUNT(CASE WHEN status = 'offline' THEN 1 END) as offline,
                    COUNT(CASE WHEN status = 'unknown' THEN 1 END) as unknown,
                    COUNT(CASE WHEN enabled = true THEN 1 END) as enabled,
                    COUNT(CASE WHEN enabled = false THEN 1 END) as disabled
                FROM {}.external_services
            """).format(sql.Identifier(self.schema_name))
            row = self._execute_query(query, fetch='one')

            # Get counts by service type
            type_query = sql.SQL("""
                SELECT service_type, COUNT(*) as count
                FROM {}.external_services
                GROUP BY service_type
            """).format(sql.Identifier(self.schema_name))
            type_rows = self._execute_query(type_query, fetch='all')

            return {
                'total_services': row['total_services'] if row else 0,
                'by_status': {
                    'active': row['active'] if row else 0,
                    'degraded': row['degraded'] if row else 0,
                    'offline': row['offline'] if row else 0,
                    'unknown': row['unknown'] if row else 0,
                },
                'enabled': row['enabled'] if row else 0,
                'disabled': row['disabled'] if row else 0,
                'by_type': {r['service_type']: r['count'] for r in type_rows}
            }

    def _row_to_service(self, row: Dict[str, Any]) -> ExternalService:
        """
        Convert database row to ExternalService model.

        Args:
            row: Database row as dict

        Returns:
            ExternalService model instance
        """
        return ExternalService(
            service_id=row['service_id'],
            url=row['url'],
            service_type=ServiceType(row['service_type']) if row.get('service_type') else ServiceType.UNKNOWN,
            detection_confidence=row.get('detection_confidence', 0.0),
            name=row['name'],
            description=row.get('description'),
            tags=row.get('tags', []) if isinstance(row.get('tags'), list) else json.loads(row.get('tags', '[]')),
            status=ServiceStatus(row['status']) if row.get('status') else ServiceStatus.UNKNOWN,
            enabled=row.get('enabled', True),
            detected_capabilities=row.get('detected_capabilities', {}) if isinstance(row.get('detected_capabilities'), dict) else json.loads(row.get('detected_capabilities', '{}')),
            health_history=row.get('health_history', []) if isinstance(row.get('health_history'), list) else json.loads(row.get('health_history', '[]')),
            last_response_ms=row.get('last_response_ms'),
            avg_response_ms=row.get('avg_response_ms'),
            consecutive_failures=row.get('consecutive_failures', 0),
            last_failure_reason=row.get('last_failure_reason'),
            check_interval_minutes=row.get('check_interval_minutes', 60),
            last_check_at=row.get('last_check_at'),
            next_check_at=row.get('next_check_at'),
            metadata=row.get('metadata', {}) if isinstance(row.get('metadata'), dict) else json.loads(row.get('metadata', '{}')),
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ExternalServiceRepository',
]
