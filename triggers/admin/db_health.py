"""
Database Health Admin Trigger.

Database health monitoring and performance metrics.

Exports:
    AdminDbHealthTrigger: HTTP trigger class for health monitoring
    admin_db_health_trigger: Singleton instance of AdminDbHealthTrigger
"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbHealth")


class AdminDbHealthTrigger:
    """
    Admin trigger for PostgreSQL health monitoring.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminDbHealthTrigger'] = None

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

        logger.info("🔧 Initializing AdminDbHealthTrigger")
        self._initialized = True
        logger.info("✅ AdminDbHealthTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbHealthTrigger':
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
        Route admin database health requests.

        Routes:
            GET /api/dbadmin/health
            GET /api/dbadmin/health/performance

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with health metrics
        """
        try:
            # Determine operation from path
            path = req.url.split('/api/dbadmin/health')[-1].strip('/')

            logger.info(f"📥 Admin DB Health request: {path or 'main'}")

            # Route to appropriate handler
            if not path:
                return self._get_health(req)
            elif path == 'performance':
                return self._get_performance(req)
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path}'}),
                    status_code=404,
                    mimetype='application/json'
                )

        except Exception as e:
            logger.error(f"❌ Error in AdminDbHealthTrigger: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_health(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get overall database health.

        GET /api/dbadmin/health

        Returns:
            {
                "status": "healthy",
                "connection_pool": {
                    "total": 15,
                    "active": 5,
                    "idle": 10,
                    "utilization_percent": 15.0
                },
                "database_size": {
                    "total": "512 MB",
                    "app_schema": "128 MB",
                    "geo_schema": "256 MB",
                    "pgstac_schema": "128 MB"
                },
                "vacuum_status": {
                    "tables_needing_vacuum": 2,
                    "tables_needing_analyze": 1
                },
                "replication": {
                    "is_replica": false,
                    "lag_seconds": null
                },
                "checks": [
                    {"name": "connection_pool", "status": "healthy", "message": "15% utilization"},
                    {"name": "table_bloat", "status": "warning", "message": "2 tables need vacuum"},
                    {"name": "long_running_queries", "status": "healthy", "message": "No queries > 5 min"}
                ],
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info("🏥 Getting database health")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            checks = []
            overall_status = "healthy"

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Connection pool status
                    cursor.execute("""
                        SELECT
                            count(*) as total,
                            count(*) FILTER (WHERE state = 'active') as active,
                            count(*) FILTER (WHERE state = 'idle') as idle
                        FROM pg_stat_activity;
                    """)
                    row = cursor.fetchone()
                    total_conn, active_conn, idle_conn = row['total'], row['active'], row['idle']

                    cursor.execute("SHOW max_connections;")
                    max_conn_row = cursor.fetchone()
                    # SHOW commands return dict like {'max_connections': '50'}
                    max_conn = int(max_conn_row.get('max_connections', 50))
                    utilization = (total_conn / max_conn * 100) if max_conn > 0 else 0

                    pool_status = "healthy" if utilization < 80 else "warning"
                    if pool_status == "warning":
                        overall_status = "warning"

                    checks.append({
                        'name': 'connection_pool',
                        'status': pool_status,
                        'message': f'{utilization:.1f}% utilization ({total_conn}/{max_conn})'
                    })

                    # Database sizes
                    cursor.execute("""
                        SELECT
                            pg_size_pretty(pg_database_size(current_database())) as total_size;
                    """)
                    total_size = cursor.fetchone()['total_size']

                    cursor.execute("""
                        SELECT
                            nspname,
                            pg_size_pretty(sum(pg_total_relation_size(c.oid))) as size
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE nspname IN ('app', 'geo', 'pgstac')
                        GROUP BY nspname;
                    """)
                    schema_rows = cursor.fetchall()
                    schema_sizes = {row['nspname']: row['size'] for row in schema_rows}

                    # Tables needing vacuum/analyze
                    cursor.execute("""
                        SELECT
                            count(*) FILTER (WHERE last_vacuum IS NULL OR last_vacuum < now() - interval '7 days') as need_vacuum,
                            count(*) FILTER (WHERE last_analyze IS NULL OR last_analyze < now() - interval '7 days') as need_analyze
                        FROM pg_stat_user_tables
                        WHERE schemaname IN ('app', 'geo', 'pgstac');
                    """)
                    row = cursor.fetchone()
                    need_vacuum, need_analyze = row['need_vacuum'], row['need_analyze']

                    vacuum_status = "healthy" if need_vacuum == 0 else "warning"
                    if vacuum_status == "warning":
                        overall_status = "warning"

                    checks.append({
                        'name': 'table_maintenance',
                        'status': vacuum_status,
                        'message': f'{need_vacuum} tables need vacuum, {need_analyze} need analyze'
                    })

                    # Long-running queries
                    cursor.execute("""
                        SELECT count(*) as count
                        FROM pg_stat_activity
                        WHERE state = 'active'
                        AND now() - query_start > interval '5 minutes'
                        AND pid != pg_backend_pid();
                    """)
                    long_queries = cursor.fetchone()['count']

                    query_status = "healthy" if long_queries == 0 else "warning"
                    if query_status == "warning":
                        overall_status = "warning"

                    checks.append({
                        'name': 'long_running_queries',
                        'status': query_status,
                        'message': f'{long_queries} queries running > 5 minutes' if long_queries > 0 else 'No long-running queries'
                    })

                    # Check if this is a replica
                    cursor.execute("SELECT pg_is_in_recovery() as is_in_recovery;")
                    is_replica = cursor.fetchone()['is_in_recovery']

            result = {
                'status': overall_status,
                'connection_pool': {
                    'total': total_conn,
                    'active': active_conn,
                    'idle': idle_conn,
                    'max': max_conn,
                    'utilization_percent': round(utilization, 2)
                },
                'database_size': {
                    'total': total_size,
                    'app_schema': schema_sizes.get('app', 'N/A'),
                    'geo_schema': schema_sizes.get('geo', 'N/A'),
                    'pgstac_schema': schema_sizes.get('pgstac', 'N/A')
                },
                'vacuum_status': {
                    'tables_needing_vacuum': need_vacuum,
                    'tables_needing_analyze': need_analyze
                },
                'replication': {
                    'is_replica': is_replica,
                    'lag_seconds': None
                },
                'checks': checks,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Database health: {overall_status}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting database health: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_performance(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get database performance metrics.

        GET /api/dbadmin/health/performance

        Returns:
            {
                "cache_hit_ratio": 0.99,
                "index_hit_ratio": 0.95,
                "sequential_scans": {
                    "total": 1000,
                    "tables_with_high_seqscans": [
                        {"table": "app.jobs", "seq_scans": 500}
                    ]
                },
                "transaction_stats": {
                    "commits": 10000,
                    "rollbacks": 50,
                    "rollback_ratio": 0.005
                },
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info("📊 Getting database performance metrics")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Cache hit ratio
                    cursor.execute("""
                        SELECT
                            sum(heap_blks_hit) / NULLIF(sum(heap_blks_hit + heap_blks_read), 0) as cache_hit_ratio
                        FROM pg_statio_user_tables;
                    """)
                    cache_hit = cursor.fetchone()['cache_hit_ratio']

                    # Index hit ratio
                    cursor.execute("""
                        SELECT
                            sum(idx_blks_hit) / NULLIF(sum(idx_blks_hit + idx_blks_read), 0) as index_hit_ratio
                        FROM pg_statio_user_indexes;
                    """)
                    index_hit = cursor.fetchone()['index_hit_ratio']

                    # Sequential scans
                    cursor.execute("""
                        SELECT
                            schemaname || '.' || tablename as table_name,
                            seq_scan
                        FROM pg_stat_user_tables
                        WHERE seq_scan > 100
                        ORDER BY seq_scan DESC
                        LIMIT 10;
                    """)
                    seqscan_rows = cursor.fetchall()
                    high_seqscans = [{'table': row['table_name'], 'seq_scans': row['seq_scan']} for row in seqscan_rows]

                    cursor.execute("SELECT sum(seq_scan) as total FROM pg_stat_user_tables;")
                    total_seqscans = cursor.fetchone()['total'] or 0

                    # Transaction stats
                    cursor.execute("""
                        SELECT
                            xact_commit,
                            xact_rollback
                        FROM pg_stat_database
                        WHERE datname = current_database();
                    """)
                    row = cursor.fetchone()
                    commits, rollbacks = row['xact_commit'], row['xact_rollback']
                    rollback_ratio = rollbacks / (commits + rollbacks) if (commits + rollbacks) > 0 else 0

            result = {
                'cache_hit_ratio': float(cache_hit) if cache_hit else 0.0,
                'index_hit_ratio': float(index_hit) if index_hit else 0.0,
                'sequential_scans': {
                    'total': int(total_seqscans),
                    'tables_with_high_seqscans': high_seqscans
                },
                'transaction_stats': {
                    'commits': commits,
                    'rollbacks': rollbacks,
                    'rollback_ratio': round(rollback_ratio, 4)
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Performance metrics: cache={cache_hit:.2%}, index={index_hit:.2%}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting performance metrics: {e}")
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
admin_db_health_trigger = AdminDbHealthTrigger.instance()
