# ============================================================================
# CLAUDE CONTEXT - DATABASE QUERIES ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - PostgreSQL query analysis
# PURPOSE: HTTP trigger for analyzing running queries, slow queries, locks, and connections
# LAST_REVIEWED: 03 NOV 2025
# EXPORTS: AdminDbQueriesTrigger - Singleton trigger for query analysis
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, psycopg, infrastructure.postgresql, util_logger
# SOURCE: PostgreSQL pg_stat_activity, pg_locks, pg_stat_statements (if available)
# SCOPE: Read-only query analysis for debugging performance and deadlocks
# VALIDATION: None yet (future APIM authentication)
# PATTERNS: Singleton trigger, RESTful admin API
# ENTRY_POINTS: AdminDbQueriesTrigger.instance().handle_request(req)
# INDEX: AdminDbQueriesTrigger:50, running_queries:150, slow_queries:250, locks:350, connections:450
# ============================================================================

"""
Database Queries Admin Trigger

Provides query analysis and connection monitoring:
- List currently running queries
- Analyze slow queries (if pg_stat_statements enabled)
- Show current locks and blocking queries
- Connection pool statistics

Endpoints:
    GET /api/admin/db/queries/running
    GET /api/admin/db/queries/slow
    GET /api/admin/db/locks
    GET /api/admin/db/connections

Critical for:
- Debugging performance issues
- Identifying deadlocks
- Monitoring connection pool usage
- Finding long-running queries

Author: Robert and Geospatial Claude Legion
Date: 03 NOV 2025
"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbQueries")


class AdminDbQueriesTrigger:
    """
    Admin trigger for PostgreSQL query analysis.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminDbQueriesTrigger'] = None

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

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route admin database query analysis requests.

        Routes:
            GET /api/db/queries/running
            GET /api/db/queries/slow
            GET /api/db/locks
            GET /api/db/connections

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with query analysis
        """
        try:
            # Determine operation from path
            path = req.url.split('/api/db/')[-1].strip('/')

            logger.info(f"📥 Admin DB Queries request: {path}")

            # Route to appropriate handler
            if path == 'queries/running':
                return self._get_running_queries(req)
            elif path == 'queries/slow':
                return self._get_slow_queries(req)
            elif path == 'locks':
                return self._get_locks(req)
            elif path == 'connections':
                return self._get_connections(req)
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path}'}),
                    status_code=404,
                    mimetype='application/json'
                )

        except Exception as e:
            logger.error(f"❌ Error in AdminDbQueriesTrigger: {e}")
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
                        );
                    """)
                    available = cursor.fetchone()[0]

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
