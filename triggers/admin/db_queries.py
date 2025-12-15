"""
Database Queries Admin Trigger.

PostgreSQL query analysis and connection monitoring.

Consolidated endpoint pattern (15 DEC 2025):
    GET /api/dbadmin/activity?type={running|slow|locks|connections}

Exports:
    AdminDbQueriesTrigger: HTTP trigger class for query analysis
    admin_db_queries_trigger: Singleton instance of AdminDbQueriesTrigger
"""

import azure.functions as func
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbQueries")


@dataclass
class RouteDefinition:
    """Route configuration for registry pattern."""
    route: str
    methods: list
    handler: str
    description: str


class AdminDbQueriesTrigger:
    """
    Admin trigger for PostgreSQL query analysis.

    Singleton pattern for consistent configuration across requests.

    Consolidated API (15 DEC 2025):
        GET /api/dbadmin/activity?type={running|slow|locks|connections}
    """

    _instance: Optional['AdminDbQueriesTrigger'] = None

    # ========================================================================
    # ROUTE REGISTRY - Single source of truth for function_app.py
    # ========================================================================
    ROUTES = [
        RouteDefinition(
            route="dbadmin/activity",
            methods=["GET"],
            handler="handle_activity",
            description="Consolidated activity: ?type={running|slow|locks|connections}"
        ),
    ]

    # ========================================================================
    # OPERATIONS REGISTRY - Maps type param to handler method
    # ========================================================================
    OPERATIONS = {
        "running": "_get_running_queries",
        "slow": "_get_slow_queries",
        "locks": "_get_locks",
        "connections": "_get_connections",
    }

    def __new__(cls):
        """Singleton pattern - reuse instance across requests."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("🔧 Initializing AdminDbQueriesTrigger")
        self._initialized = True
        logger.info("✅ AdminDbQueriesTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbQueriesTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def db_repo(self) -> PostgreSQLRepository:
        """Lazy initialization of database repository."""
        if not hasattr(self, '_db_repo'):
            logger.debug("🔧 Lazy loading database repository")
            repos = RepositoryFactory.create_repositories()
            self._db_repo = repos['job_repo']
        return self._db_repo

    def handle_activity(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated activity endpoint with type parameter.

        GET /api/dbadmin/activity?type={running|slow|locks|connections}

        Query Parameters:
            type: Activity type (default: running)
                - running: Currently running queries
                - slow: Slow query statistics (requires pg_stat_statements)
                - locks: Current database locks
                - connections: Connection statistics

        Returns:
            JSON response with requested activity data
        """
        try:
            activity_type = req.params.get('type', 'running')
            logger.info(f"📥 DB Activity request: type={activity_type}")

            if activity_type not in self.OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Unknown activity type: {activity_type}",
                        'valid_types': list(self.OPERATIONS.keys()),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            handler_method = getattr(self, self.OPERATIONS[activity_type])
            return handler_method(req)

        except Exception as e:
            logger.error(f"❌ Error in handle_activity: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_running_queries(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get currently running queries.

        GET /api/admin/db/queries/running?limit=50

        Query Parameters:
            limit: Max queries to return (default: 50)

        Returns:
            {
                "queries": [
                    {
                        "pid": 12345,
                        "user": "rmhgeoapi",
                        "application": "Azure Functions",
                        "state": "active",
                        "query": "SELECT * FROM ...",
                        "duration_seconds": 2.5,
                        "wait_event_type": null,
                        "wait_event": null
                    },
                    ...
                ],
                "count": 5,
                "timestamp": "2025-11-03T..."
            }
        """
        limit = int(req.params.get('limit', 50))
        logger.info(f"📊 Getting running queries (limit={limit})")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            pid,
                            usename,
                            application_name,
                            state,
                            query,
                            EXTRACT(EPOCH FROM (now() - query_start)) as duration_seconds,
                            wait_event_type,
                            wait_event,
                            backend_start,
                            query_start
                        FROM pg_stat_activity
                        WHERE state != 'idle'
                        AND pid != pg_backend_pid()
                        ORDER BY query_start DESC
                        LIMIT %s;
                    """, (limit,))
                    rows = cursor.fetchall()

                    queries = []
                    for row in rows:
                        queries.append({
                            'pid': row['pid'],
                            'user': row['usename'],
                            'application': row['application_name'],
                            'state': row['state'],
                            'query': row['query'][:500] if row['query'] else None,  # Truncate long queries
                            'duration_seconds': float(row['duration_seconds']) if row['duration_seconds'] else 0,
                            'wait_event_type': row['wait_event_type'],
                            'wait_event': row['wait_event'],
                            'backend_start': row['backend_start'].isoformat() if row['backend_start'] else None,
                            'query_start': row['query_start'].isoformat() if row['query_start'] else None
                        })

            logger.info(f"✅ Found {len(queries)} running queries")

            return func.HttpResponse(
                body=json.dumps({
                    'queries': queries,
                    'count': len(queries),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting running queries: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_slow_queries(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get slow query statistics.

        GET /api/admin/db/queries/slow?limit=20

        Requires: pg_stat_statements extension

        Query Parameters:
            limit: Max queries to return (default: 20)

        Returns:
            {
                "available": true,
                "queries": [
                    {
                        "query": "SELECT * FROM ...",
                        "calls": 1000,
                        "total_time_seconds": 125.5,
                        "avg_time_ms": 125.5,
                        "max_time_ms": 500.0,
                        "rows": 50000
                    },
                    ...
                ],
                "count": 20,
                "timestamp": "2025-11-03T..."
            }
        """
        limit = int(req.params.get('limit', 20))
        logger.info(f"📊 Getting slow queries (limit={limit})")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if pg_stat_statements is available
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
                        ) as extension_exists;
                    """)
                    available = cursor.fetchone()['extension_exists']

                    if not available:
                        return func.HttpResponse(
                            body=json.dumps({
                                'available': False,
                                'message': 'pg_stat_statements extension not installed',
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }),
                            status_code=200,
                            mimetype='application/json'
                        )

                    # Get slow queries
                    cursor.execute("""
                        SELECT
                            query,
                            calls,
                            total_exec_time / 1000.0 as total_time_seconds,
                            mean_exec_time as avg_time_ms,
                            max_exec_time as max_time_ms,
                            rows
                        FROM pg_stat_statements
                        ORDER BY total_exec_time DESC
                        LIMIT %s;
                    """, (limit,))
                    rows = cursor.fetchall()

                    queries = []
                    for row in rows:
                        queries.append({
                            'query': row['query'][:500] if row['query'] else None,  # Truncate
                            'calls': row['calls'],
                            'total_time_seconds': float(row['total_time_seconds']) if row['total_time_seconds'] else 0,
                            'avg_time_ms': float(row['avg_time_ms']) if row['avg_time_ms'] else 0,
                            'max_time_ms': float(row['max_time_ms']) if row['max_time_ms'] else 0,
                            'rows': row['rows']
                        })

            logger.info(f"✅ Found {len(queries)} slow queries")

            return func.HttpResponse(
                body=json.dumps({
                    'available': True,
                    'queries': queries,
                    'count': len(queries),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting slow queries: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_locks(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get current database locks.

        GET /api/admin/db/locks

        Returns:
            {
                "locks": [
                    {
                        "pid": 12345,
                        "lock_type": "relation",
                        "mode": "AccessShareLock",
                        "granted": true,
                        "query": "SELECT * FROM ...",
                        "duration_seconds": 2.5,
                        "blocking_pids": [12346]
                    },
                    ...
                ],
                "blocking_count": 2,
                "total_count": 50,
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info("🔒 Getting current locks")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get locks with blocking information
                    cursor.execute("""
                        SELECT
                            l.pid,
                            l.locktype,
                            l.mode,
                            l.granted,
                            a.query,
                            EXTRACT(EPOCH FROM (now() - a.query_start)) as duration_seconds,
                            a.wait_event_type,
                            a.wait_event
                        FROM pg_locks l
                        LEFT JOIN pg_stat_activity a ON l.pid = a.pid
                        WHERE a.pid IS NOT NULL
                        ORDER BY l.granted, a.query_start;
                    """)
                    rows = cursor.fetchall()

                    locks = []
                    blocking_count = 0
                    for row in rows:
                        is_blocking = not row['granted']  # not granted
                        if is_blocking:
                            blocking_count += 1

                        locks.append({
                            'pid': row['pid'],
                            'lock_type': row['locktype'],
                            'mode': row['mode'],
                            'granted': row['granted'],
                            'query': row['query'][:200] if row['query'] else None,
                            'duration_seconds': float(row['duration_seconds']) if row['duration_seconds'] else 0,
                            'wait_event_type': row['wait_event_type'],
                            'wait_event': row['wait_event'],
                            'is_blocking': is_blocking
                        })

            logger.info(f"✅ Found {len(locks)} locks ({blocking_count} blocking)")

            return func.HttpResponse(
                body=json.dumps({
                    'locks': locks,
                    'blocking_count': blocking_count,
                    'total_count': len(locks),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting locks: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_connections(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get connection statistics.

        GET /api/admin/db/connections

        Returns:
            {
                "total_connections": 15,
                "active_connections": 5,
                "idle_connections": 10,
                "max_connections": 100,
                "utilization_percent": 15.0,
                "connections_by_application": [
                    {"application": "Azure Functions", "count": 10},
                    {"application": "psql", "count": 5}
                ],
                "connections_by_state": [
                    {"state": "active", "count": 5},
                    {"state": "idle", "count": 10}
                ],
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info("🔌 Getting connection statistics")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get total connection count
                    cursor.execute("SELECT count(*) as count FROM pg_stat_activity;")
                    total = cursor.fetchone()['count']

                    # Get active/idle counts
                    cursor.execute("""
                        SELECT
                            state,
                            count(*) as count
                        FROM pg_stat_activity
                        GROUP BY state;
                    """)
                    state_rows = cursor.fetchall()
                    by_state = [{'state': row['state'], 'count': row['count']} for row in state_rows]

                    active = sum(row['count'] for row in by_state if row['state'] == 'active')
                    idle = sum(row['count'] for row in by_state if row['state'] == 'idle')

                    # Get connections by application
                    cursor.execute("""
                        SELECT
                            application_name,
                            count(*) as count
                        FROM pg_stat_activity
                        WHERE application_name IS NOT NULL AND application_name != ''
                        GROUP BY application_name
                        ORDER BY count DESC;
                    """)
                    app_rows = cursor.fetchall()
                    by_app = [{'application': row['application_name'], 'count': row['count']} for row in app_rows]

                    # Get max connections
                    cursor.execute("SHOW max_connections;")
                    max_conn_row = cursor.fetchone()
                    max_conn = int(max_conn_row.get('max_connections', 100))

                    utilization = (total / max_conn * 100) if max_conn > 0 else 0

            logger.info(f"✅ Connections: {total} total, {active} active, {idle} idle (max: {max_conn})")

            return func.HttpResponse(
                body=json.dumps({
                    'total_connections': total,
                    'active_connections': active,
                    'idle_connections': idle,
                    'max_connections': max_conn,
                    'utilization_percent': round(utilization, 2),
                    'connections_by_application': by_app,
                    'connections_by_state': by_state,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting connections: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


# Create singleton instance
admin_db_queries_trigger = AdminDbQueriesTrigger.instance()
