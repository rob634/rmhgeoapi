# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Comprehensive system health monitoring endpoint
# PURPOSE: System health monitoring HTTP trigger handling GET /api/health requests
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: HealthCheckTrigger, health_check_trigger (singleton instance)
# INTERFACES: SystemMonitoringTrigger (inherited from http_base)
# PYDANTIC_MODELS: None directly - uses dict responses for health status
# DEPENDENCIES: http_base.SystemMonitoringTrigger, config, core.schema.deployer.SchemaManagerFactory, utils.validator, azure.functions
# SOURCE: HTTP GET requests, environment variables, component status from PostgreSQL/Service Bus/Blob Storage/imports
# SCOPE: HTTP endpoint for monitoring 9 system components - database, Service Bus, imports, DuckDB, VSI, jobs registry, schema validation
# VALIDATION: Component connectivity checks, schema validation and auto-creation, import validation with auto-discovery, configuration checks
# PATTERNS: Template Method (base class), Health Check pattern, Component pattern, Status Code pattern (200/503/500)
# ENTRY_POINTS: GET /api/health - Used by function_app.py via health_check_trigger singleton
# INDEX: HealthCheckTrigger:56, process_request:66, handle_request:177, _check_database:326, _check_service_bus_queues:285, _check_import_validation:778, _check_vsi_support:946, _check_jobs_registry:1058
# ============================================================================

"""
Health Check HTTP Trigger - Comprehensive System Monitoring

Concrete implementation of health check endpoint using BaseHttpTrigger pattern.
Performs comprehensive health checks on all critical and optional system components
with proper HTTP status code semantics (200 healthy, 503 unhealthy, 500 error).

Components Monitored (9 total):
1. Import Validation - Critical dependency and application module validation with auto-discovery
2. Service Bus Queues - Jobs and tasks queues connectivity and message counts
3. Database Configuration - PostgreSQL connection string and environment variable validation
4. Database Connectivity - PostgreSQL health with schema validation, auto-creation, and query metrics
5. DuckDB - Optional analytical engine for serverless Parquet queries (non-critical)
6. VSI Support - Rasterio /vsicurl/ capability for Big Raster ETL (critical for large rasters)
7. Jobs Registry - Available job types from jobs.ALL_JOBS (critical for job submission)
8. Azure Table Storage - Deprecated (PostgreSQL replaced for ACID compliance)
9. Key Vault - Disabled (using environment variables only)

Health Check Features:
- Proper HTTP status codes: 200 (healthy), 503 (unhealthy), 500 (error)
- Component-level health status with detailed error messages
- Database query performance metrics (connection time, query time, function tests)
- Enhanced database metrics (jobs/tasks last 24h, status breakdown, PostgreSQL function testing)
- Schema validation and auto-creation via SchemaManagerFactory
- Detailed schema inspection (columns, functions, signatures) for debugging
- Import validation with auto-discovery and cache tracking
- VSI capability testing with real blob file (/vsicurl/ with SAS URL)
- Jobs registry validation (ensures job types are registered)
- Cache-Control headers to prevent stale health data
- Request ID tracking for correlation

Database Health Checks:
- PostgreSQL version and PostGIS version detection
- Schema existence validation (app schema, postgis schema)
- Table validation and auto-creation (jobs, tasks)
- PostgreSQL function testing (complete_task_and_check_stage, advance_job_stage, check_job_completion)
- Query performance metrics (connection time, query execution time)
- Job/Task metrics for last 24 hours (status breakdown, counts)
- STAC items count (optional)

Optional Components (don't fail overall health):
- DuckDB - Analytical engine for GeoParquet exports and serverless queries
- VSI Support - Required for Big Raster ETL but optional for core operations

API Endpoint:
    GET /api/health

Response (Healthy - 200 OK):
    {
        "status": "healthy",
        "components": {
            "imports": {"status": "healthy", ...},
            "service_bus": {"status": "healthy", ...},
            "database_config": {"status": "healthy", ...},
            "database": {"status": "healthy", "query_performance": {...}, ...},
            "duckdb": {"status": "healthy", ...},
            "vsi": {"status": "healthy", ...},
            "jobs": {"status": "healthy", "available_jobs": [...], ...},
            "tables": {"status": "deprecated", ...},
            "vault": {"status": "disabled", ...}
        },
        "environment": {
            "storage_account": "rmhazuregeo",
            "python_version": "3.11.x",
            "function_runtime": "python",
            "health_check_version": "v2025-10-25_VSI_CHECK_ENABLED"
        },
        "errors": [],
        "request_id": "uuid",
        "timestamp": "2025-10-29T12:34:56.789Z"
    }

Response (Unhealthy - 503 Service Unavailable):
    {
        "status": "unhealthy",
        "components": {...component_details...},
        "errors": [
            "Database connection failed: timeout",
            "Service Bus queue 'jobs' inaccessible"
        ],
        "request_id": "uuid",
        "timestamp": "2025-10-29T12:34:56.789Z"
    }

Response (Error - 500 Internal Server Error):
    {
        "error": "Internal server error",
        "message": "Health check failed: [exception details]",
        "request_id": "uuid",
        "timestamp": "2025-10-29T12:34:56.789Z",
        "status": "error"
    }

HTTP Status Code Semantics:
- 200 OK: All components healthy, system operational
- 503 Service Unavailable: One or more components unhealthy, system degraded
- 500 Internal Server Error: Health check itself failed, system state unknown
- 405 Method Not Allowed: Non-GET request attempted

Integration Points:
- SystemMonitoringTrigger base class (http_base.py) - Common monitoring patterns
- SchemaManagerFactory (core.schema.deployer) - Database schema validation/creation
- utils.validator - Import validation with auto-discovery
- RepositoryFactory - Component repository access
- Service Bus, PostgreSQL, Blob Storage - Infrastructure health checks

Usage Notes:
- Health check runs on every GET /api/health request (no caching at trigger level)
- Database health check is OPTIONAL (controlled by ENABLE_DATABASE_HEALTH_CHECK env var)
- Import validation uses 5-minute cache (managed by utils.validator)
- VSI check uses 4-hour SAS token for test file access
- Cache-Control: no-cache header prevents HTTP-level caching

Author: Robert and Geospatial Claude Legion
Date: Original implementation 2025
Last Updated: 29 OCT 2025
"""

from typing import Dict, Any, List
import os
import sys
from datetime import datetime, timezone

import azure.functions as func
from .http_base import SystemMonitoringTrigger
from config import get_config
from core.schema.deployer import SchemaManagerFactory
from utils import validator


class HealthCheckTrigger(SystemMonitoringTrigger):
    """Health check HTTP trigger implementation."""
    
    def __init__(self):
        super().__init__("health_check")
    
    def get_allowed_methods(self) -> List[str]:
        """Health check only supports GET."""
        return ["GET"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Perform comprehensive health check.
        
        Args:
            req: HTTP request (not used for health check)
            
        Returns:
            Health status data
        """
        health_data = {
            "status": "healthy",
            "components": {},
            "environment": {
                "storage_account": get_config().storage_account_name,
                "python_version": sys.version.split()[0],
                "function_runtime": "python",
                "health_check_version": "v2025-11-13_B3_OPTIMIZED"
            },
            "errors": []
        }
        
        # Check import validation (critical for application startup)
        import_health = self._check_import_validation()
        health_data["components"]["imports"] = import_health
        if import_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(import_health.get("errors", []))

        # Storage Queues - DEPRECATED (2 OCT 2025) - SERVICE BUS ONLY APPLICATION
        # queue_health = self._check_storage_queues()
        # health_data["components"]["queues"] = queue_health
        # if queue_health["status"] == "unhealthy":
        #     health_data["status"] = "unhealthy"
        #     health_data["errors"].extend(queue_health.get("errors", []))

        # Check Service Bus queues
        service_bus_health = self._check_service_bus_queues()
        health_data["components"]["service_bus"] = service_bus_health
        if service_bus_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(service_bus_health.get("errors", []))

        # Storage tables REMOVED (1 OCT 2025) - deprecated in favor of PostgreSQL
        # Azure Table Storage was replaced by PostgreSQL for ACID compliance
        health_data["components"]["tables"] = {
            "component": "tables",
            "status": "deprecated",
            "details": {"message": "Azure Table Storage deprecated - using PostgreSQL instead"},
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Key Vault disabled - using environment variables only
        # vault_health = self._check_vault_configuration()
        # health_data["components"]["vault"] = vault_health
        health_data["components"]["vault"] = {
            "component": "vault", 
            "status": "disabled",
            "details": {"message": "Key Vault disabled - using environment variables only"},
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Check database configuration
        db_config_health = self._check_database_configuration()
        health_data["components"]["database_config"] = db_config_health
        if db_config_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(db_config_health.get("errors", []))
        
        # Check database connectivity (optional)
        if self._should_check_database():
            db_health = self._check_database()
            health_data["components"]["database"] = db_health
            if db_health["status"] == "unhealthy":
                health_data["status"] = "unhealthy"
                health_data["errors"].extend(db_health.get("errors", []))

        # Check DuckDB analytical engine (optional component)
        # Controlled by ENABLE_DUCKDB_HEALTH_CHECK environment variable (default: false)
        config = get_config()
        if config.enable_duckdb_health_check:
            duckdb_health = self._check_duckdb()
            health_data["components"]["duckdb"] = duckdb_health
            # Note: DuckDB is optional - don't fail overall health if unavailable
            if duckdb_health["status"] == "error":
                health_data["errors"].append("DuckDB unavailable (optional analytical component)")
        else:
            health_data["components"]["duckdb"] = {
                "component": "duckdb",
                "status": "disabled",
                "details": {
                    "message": "DuckDB check disabled via config - module still available",
                    "enable_with": "Set ENABLE_DUCKDB_HEALTH_CHECK=true"
                },
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

        # Check rasterio VSI (Virtual File System) support (optional but important for Big Raster ETL)
        # Controlled by ENABLE_VSI_HEALTH_CHECK environment variable (default: false)
        if config.enable_vsi_health_check:
            try:
                self.logger.info("🔍 Starting VSI capability check...")
                vsi_health = self._check_vsi_support()
                self.logger.info(f"📊 VSI check result: {vsi_health.get('status', 'unknown')}")
                health_data["components"]["vsi"] = vsi_health
                # Note: VSI is optional but required for Big Raster ETL - don't fail overall health
                if vsi_health["status"] == "error":
                    health_data["errors"].append("Rasterio VSI unavailable (impacts Big Raster ETL workflow)")
            except Exception as vsi_error:
                self.logger.error(f"❌ VSI check failed with exception: {vsi_error}")
                health_data["components"]["vsi"] = {
                    "component": "vsi_support",
                    "status": "error",
                    "details": {"exception": str(vsi_error), "error_type": type(vsi_error).__name__},
                    "checked_at": datetime.now(timezone.utc).isoformat()
                }
        else:
            health_data["components"]["vsi"] = {
                "component": "vsi_support",
                "status": "disabled",
                "details": {
                    "message": "VSI check disabled via config - rasterio still available",
                    "enable_with": "Set ENABLE_VSI_HEALTH_CHECK=true"
                },
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

        # Check jobs registry (critical for job processing)
        jobs_health = self._check_jobs_registry()
        health_data["components"]["jobs"] = jobs_health
        if jobs_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(jobs_health.get("errors", []))

        # Check PgSTAC (optional but important for STAC workflows)
        # Controlled by ENABLE_DATABASE_HEALTH_CHECK environment variable
        if self._should_check_database():
            pgstac_health = self._check_pgstac()
            health_data["components"]["pgstac"] = pgstac_health
            # Note: PgSTAC is optional - don't fail overall health if unavailable
            if pgstac_health["status"] == "error":
                health_data["errors"].append("PgSTAC unavailable (impacts STAC collection/item workflows)")

        return health_data
    
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Override to provide proper HTTP status codes for health checks.
        
        Returns:
            - 200 OK when all components are healthy
            - 503 Service Unavailable when any component is unhealthy  
            - 500 Internal Server Error for unexpected errors
        """
        import json
        from datetime import datetime, timezone
        import uuid
        
        request_id = str(uuid.uuid4())
        
        try:
            # Validate HTTP method
            if req.method not in self.get_allowed_methods():
                return func.HttpResponse(
                    json.dumps({
                        "error": "Method not allowed",
                        "message": f"Method {req.method} not allowed. Allowed: GET",
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=405,
                    mimetype="application/json"
                )
            
            # Process the health check
            health_data = self.process_request(req)
            
            # Determine HTTP status code based on health status
            if health_data["status"] == "healthy":
                status_code = 200  # OK
            elif health_data["status"] == "unhealthy":
                status_code = 503  # Service Unavailable
            else:
                status_code = 500  # Internal Server Error (unexpected status)
            
            # Add response metadata
            response_data = {
                **health_data,
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            return func.HttpResponse(
                json.dumps(response_data, default=str),
                status_code=status_code,
                mimetype="application/json",
                headers={
                    "X-Request-ID": request_id,
                    "Cache-Control": "no-cache, no-store, must-revalidate"
                }
            )
            
        except Exception as e:
            # Log the error
            self.logger.error(f"💥 [{self.trigger_name}] Health check error: {e}")
            
            return func.HttpResponse(
                json.dumps({
                    "error": "Internal server error",
                    "message": f"Health check failed: {str(e)}",
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "error"
                }),
                status_code=500,
                mimetype="application/json",
                headers={"X-Request-ID": request_id}
            )
    
    def _check_storage_queues(self) -> Dict[str, Any]:
        """Check Azure Storage Queue health using QueueRepository. DEPRECATED - SERVICE BUS ONLY."""
        def check_queues():
            from infrastructure import RepositoryFactory
            from config import QueueNames

            # Use QueueRepository singleton - credential reused!
            queue_repo = RepositoryFactory.create_queue_repository()

            queue_status = {}
            for queue_name in [QueueNames.JOBS, QueueNames.TASKS]:
                try:
                    # Use repository method to get queue length
                    message_count = queue_repo.get_queue_length(queue_name)
                    queue_status[queue_name] = {
                        "status": "accessible",
                        "message_count": message_count
                    }
                except Exception as e:
                    queue_status[queue_name] = {
                        "status": "error",
                        "error": str(e)
                    }

            # Add singleton status to verify performance improvement
            queue_status["_repository_info"] = {
                "singleton_id": id(queue_repo),
                "type": "QueueRepository"
            }

            return queue_status

        return self.check_component_health("storage_queues", check_queues)

    def _check_service_bus_queues(self) -> Dict[str, Any]:
        """Check Azure Service Bus queue health using ServiceBusRepository."""
        def check_service_bus():
            from infrastructure.service_bus import ServiceBusRepository
            from config import get_config

            config = get_config()
            service_bus_repo = ServiceBusRepository()

            queue_status = {}
            queues_to_check = [
                config.service_bus_jobs_queue,
                config.service_bus_tasks_queue
            ]

            for queue_name in queues_to_check:
                try:
                    # Peek at queue to verify connectivity and get approximate count
                    message_count = service_bus_repo.get_queue_length(queue_name)
                    queue_status[queue_name] = {
                        "status": "accessible",
                        "approximate_message_count": message_count,
                        "note": "Count is approximate (peek limit: 100)"
                    }
                except Exception as e:
                    queue_status[queue_name] = {
                        "status": "error",
                        "error": str(e)
                    }

            # Add repository info
            queue_status["_repository_info"] = {
                "singleton_id": id(service_bus_repo),
                "type": "ServiceBusRepository",
                "namespace": config.service_bus_namespace
            }

            return queue_status

        return self.check_component_health("service_bus", check_service_bus)

    def _check_database(self) -> Dict[str, Any]:
        """Enhanced PostgreSQL database health check with query metrics.

        IMPORTANT: Uses PostgreSQLRepository which respects USE_MANAGED_IDENTITY setting.
        This ensures health check uses the same authentication method as the application.
        """
        def check_pg():
            import psycopg
            import time
            from config import get_config
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            start_time = time.time()

            # Use PostgreSQLRepository to get connection string (respects managed identity)
            # This ensures health check uses same auth method as application
            try:
                repo = PostgreSQLRepository(config=config)
                conn_str = repo.conn_string
            except Exception as repo_error:
                # If repository initialization fails, return error immediately
                return {
                    "component": "database",
                    "status": "unhealthy",
                    "error": f"Failed to initialize PostgreSQL repository: {str(repo_error)}",
                    "error_type": type(repo_error).__name__,
                    "checked_at": time.time()
                }

            # Use autocommit mode to allow subtransactions for isolated tests
            with psycopg.connect(conn_str, autocommit=True) as conn:
                with conn.cursor() as cur:
                    # Track connection time
                    connection_time_ms = round((time.time() - start_time) * 1000, 2)
                    # Check PostgreSQL version
                    cur.execute("SELECT version()")
                    pg_version = cur.fetchone()[0]
                    
                    # Check PostGIS version
                    cur.execute("SELECT PostGIS_Version()")
                    postgis_version = cur.fetchone()[0]
                    
                    # Check app schema exists (for jobs and tasks tables)
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.app_schema,))
                        app_schema_exists = cur.fetchone() is not None
                    except:
                        app_schema_exists = False
                    
                    # Check postgis schema exists (for STAC data)
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.postgis_schema,))
                        postgis_schema_exists = cur.fetchone() is not None
                    except:
                        postgis_schema_exists = False
                    
                    # Count STAC items (optional)
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {config.postgis_schema}.items")
                        stac_count = cur.fetchone()[0]
                    except:
                        stac_count = "unknown"
                    
                    # Ensure app tables exist and validate schema
                    # NOTE: Schema manager uses its own connection - skip during health check
                    # to avoid transaction context conflicts
                    app_tables_status = {}
                    table_management_results = {}

                    if app_schema_exists:
                        # Simple table existence check (no schema manager - it creates its own connection)
                        try:
                            for table_name in ['jobs', 'tasks']:
                                cur.execute("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables
                                        WHERE table_schema = %s
                                        AND table_name = %s
                                    )
                                """, (config.app_schema, table_name))
                                table_exists = cur.fetchone()[0]
                                app_tables_status[table_name] = table_exists
                                table_management_results[table_name] = "exists" if table_exists else "missing"
                        except Exception as table_check_error:
                            table_management_results['table_check_error'] = f"error: {str(table_check_error)}"
                            app_tables_status['jobs'] = False
                            app_tables_status['tasks'] = False
                    
                    # DETAILED SCHEMA INSPECTION - Added for debugging function signature mismatches
                    # NOTE: Each section wrapped in try-except to prevent transaction cascade failures
                    detailed_schema_info = {}

                    # Inspect table columns (separate transaction to avoid contamination)
                    try:
                        for table_name in ['jobs', 'tasks']:
                            cur.execute("""
                                SELECT column_name, data_type, is_nullable, column_default
                                FROM information_schema.columns
                                WHERE table_schema = %s AND table_name = %s
                                ORDER BY ordinal_position
                            """, (config.app_schema, table_name))

                            columns = cur.fetchall()
                            detailed_schema_info[f"{table_name}_columns"] = [
                                {
                                    "column_name": col[0],
                                    "data_type": col[1],
                                    "is_nullable": col[2],
                                    "column_default": col[3]
                                } for col in columns
                            ]
                    except Exception as col_error:
                        detailed_schema_info['columns_inspection_error'] = f"Column inspection failed: {str(col_error)}"

                    # Inspect PostgreSQL function signatures (separate transaction)
                    try:
                        cur.execute("""
                            SELECT
                                routine_name,
                                data_type as return_type,
                                routine_definition
                            FROM information_schema.routines
                            WHERE routine_schema = %s
                            AND routine_name IN ('check_job_completion', 'complete_task_and_check_stage', 'advance_job_stage')
                            ORDER BY routine_name
                        """, (config.app_schema,))

                        functions = cur.fetchall()
                        detailed_schema_info['postgresql_functions'] = [
                            {
                                "function_name": func[0],
                                "return_type": func[1],
                                "definition_snippet": func[2][:200] + "..." if func[2] and len(func[2]) > 200 else func[2]
                            } for func in functions
                        ]
                    except Exception as func_sig_error:
                        detailed_schema_info['function_signature_error'] = f"Function signature inspection failed: {str(func_sig_error)}"

                    # Test function call (isolated transaction - failure won't affect subsequent queries)
                    try:
                        with conn.transaction():
                            cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_job_id')")
                            detailed_schema_info['function_test'] = "SUCCESS - Function signature matches query"
                    except Exception as func_error:
                        # Transaction auto-rolled back by context manager
                        # Cursor remains valid for new queries
                        detailed_schema_info['function_test'] = f"ERROR: {str(func_error)}"
                        detailed_schema_info['function_error_type'] = type(func_error).__name__
                    
                    # NEW: Enhanced database query metrics for monitoring
                    query_metrics = {}
                    job_metrics = {}
                    task_metrics = {}
                    function_metrics = {}
                    
                    if app_schema_exists and app_tables_status.get('jobs', False) and app_tables_status.get('tasks', False):
                        try:
                            # Job counts and status breakdown (last 24h)
                            query_start = time.time()
                            cur.execute(f"""
                                SELECT 
                                    status::text,
                                    COUNT(*) as count
                                FROM {config.app_schema}.jobs 
                                WHERE created_at >= NOW() - INTERVAL '24 hours'
                                GROUP BY status::text
                            """)
                            job_status_counts = dict(cur.fetchall())
                            
                            # Total jobs in last 24h
                            cur.execute(f"""
                                SELECT COUNT(*) 
                                FROM {config.app_schema}.jobs 
                                WHERE created_at >= NOW() - INTERVAL '24 hours'
                            """)
                            total_jobs_24h = cur.fetchone()[0]
                            
                            job_query_time = round((time.time() - query_start) * 1000, 2)
                            
                            job_metrics = {
                                "total_last_24h": total_jobs_24h,
                                "status_breakdown": {
                                    "queued": job_status_counts.get('queued', 0),
                                    "processing": job_status_counts.get('processing', 0),
                                    "completed": job_status_counts.get('completed', 0),
                                    "failed": job_status_counts.get('failed', 0),
                                    "completed_with_errors": job_status_counts.get('completed_with_errors', 0)
                                },
                                "query_time_ms": job_query_time
                            }
                            
                            # Task counts and status breakdown (last 24h)
                            query_start = time.time()
                            cur.execute(f"""
                                SELECT 
                                    status::text,
                                    COUNT(*) as count
                                FROM {config.app_schema}.tasks 
                                WHERE created_at >= NOW() - INTERVAL '24 hours'
                                GROUP BY status::text
                            """)
                            task_status_counts = dict(cur.fetchall())
                            
                            # Total tasks in last 24h
                            cur.execute(f"""
                                SELECT COUNT(*) 
                                FROM {config.app_schema}.tasks 
                                WHERE created_at >= NOW() - INTERVAL '24 hours'
                            """)
                            total_tasks_24h = cur.fetchone()[0]
                            
                            task_query_time = round((time.time() - query_start) * 1000, 2)
                            
                            task_metrics = {
                                "total_last_24h": total_tasks_24h,
                                "status_breakdown": {
                                    "queued": task_status_counts.get('queued', 0),
                                    "processing": task_status_counts.get('processing', 0),
                                    "completed": task_status_counts.get('completed', 0),
                                    "failed": task_status_counts.get('failed', 0)
                                },
                                "query_time_ms": task_query_time
                            }
                            
                            # Test PostgreSQL functions with performance timing
                            function_tests = []
                            
                            for func_name in ['complete_task_and_check_stage', 'advance_job_stage', 'check_job_completion']:
                                func_start = time.time()
                                try:
                                    # Execute function test in isolated transaction
                                    with conn.transaction():
                                        if func_name == 'complete_task_and_check_stage':
                                            cur.execute(f"SET search_path TO {config.app_schema}, public")
                                            cur.execute(f"SELECT task_updated, is_last_task_in_stage, job_id, stage_number, remaining_tasks FROM {config.app_schema}.complete_task_and_check_stage('test_nonexistent_task', 'test_job_id', 1)")
                                        elif func_name == 'advance_job_stage':
                                            cur.execute(f"SET search_path TO {config.app_schema}, public")
                                            cur.execute(f"SELECT job_updated, new_stage, is_final_stage FROM {config.app_schema}.advance_job_stage('test_nonexistent_job', 1)")
                                        elif func_name == 'check_job_completion':
                                            cur.execute(f"SET search_path TO {config.app_schema}, public")
                                            cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_nonexistent_job')")

                                        result = cur.fetchone()

                                    # Transaction committed successfully
                                    func_time = round((time.time() - func_start) * 1000, 2)
                                    function_tests.append({
                                        "function_name": func_name,
                                        "status": "available",
                                        "execution_time_ms": func_time,
                                        "test_result": "function_callable"
                                    })
                                except Exception as func_error:
                                    # Transaction auto-rolled back, cursor remains valid
                                    function_tests.append({
                                        "function_name": func_name,
                                        "status": "error",
                                        "error": str(func_error)[:200],
                                        "execution_time_ms": 0
                                    })
                            
                            function_metrics = {
                                "functions_available": [f["function_name"] for f in function_tests if f["status"] == "available"],
                                "function_tests": function_tests,
                                "avg_function_time_ms": round(
                                    sum(f["execution_time_ms"] for f in function_tests if f["status"] == "available") / 
                                    max(len([f for f in function_tests if f["status"] == "available"]), 1), 2
                                )
                            }
                            
                            # Overall query performance metrics
                            query_metrics = {
                                "connection_time_ms": connection_time_ms,
                                "avg_query_time_ms": round((job_query_time + task_query_time) / 2, 2),
                                "total_queries_executed": 4 + len(function_tests),
                                "all_queries_successful": True
                            }
                            
                        except Exception as metrics_error:
                            query_metrics = {
                                "connection_time_ms": connection_time_ms,
                                "metrics_error": f"Failed to collect database metrics: {str(metrics_error)}",
                                "all_queries_successful": False
                            }
                    else:
                        query_metrics = {
                            "connection_time_ms": connection_time_ms,
                            "metrics_status": "tables_not_ready",
                            "all_queries_successful": False
                        }
                    
                    return {
                        "postgresql_version": pg_version.split()[0],
                        "postgis_version": postgis_version,
                        "connection": "successful",
                        "connection_time_ms": connection_time_ms,
                        "schema_health": {
                            "app_schema_name": config.app_schema,
                            "app_schema_exists": app_schema_exists,
                            "postgis_schema_name": config.postgis_schema,
                            "postgis_schema_exists": postgis_schema_exists,
                            "app_tables": app_tables_status if app_schema_exists else "schema_not_found"
                        },
                        "table_management": {
                            "auto_creation_enabled": True,
                            "operations_performed": table_management_results,
                            "tables_ready": all(status is True for status in app_tables_status.values()) if app_tables_status else False
                        },
                        "stac_data": {
                            "items_count": stac_count,
                            "schema_accessible": postgis_schema_exists
                        },
                        "detailed_schema_inspection": detailed_schema_info,
                        "jobs_last_24h": job_metrics,
                        "tasks_last_24h": task_metrics,
                        "function_availability": function_metrics,
                        "query_performance": query_metrics
                    }
        
        return self.check_component_health("database", check_pg)
    
    def _check_vault_configuration(self) -> Dict[str, Any]:
        """Check Azure Key Vault configuration and connectivity. DISABLED - using environment variables."""
        return {
            "component": "vault",
            "status": "disabled", 
            "details": {"message": "Key Vault disabled - using environment variables only"}
        }
        
        # DISABLED - Key Vault not configured for managed identity
        def check_vault():
            from infrastructure.vault import VaultRepositoryFactory, VaultAccessError
            
            config = get_config()
            
            # Validate configuration
            config_status = {
                "key_vault_name": config.key_vault_name,
                "key_vault_database_secret": config.key_vault_database_secret,
                "vault_url": f"https://{config.key_vault_name}.vault.azure.net/"
            }
            
            # Test vault connectivity
            try:
                vault_repo = VaultRepositoryFactory.create_with_config()
                vault_info = vault_repo.get_vault_info()
                
                # Test secret access (just to verify connectivity, not retrieve actual secret)
                try:
                    # This will test connectivity without exposing the secret
                    vault_repo.get_secret(config.key_vault_database_secret)
                    secret_accessible = True
                except VaultAccessError as e:
                    if "Failed to resolve" in str(e):
                        secret_accessible = "DNS resolution failed"
                    elif "authentication" in str(e).lower():
                        secret_accessible = "Authentication failed"
                    else:
                        secret_accessible = f"Access failed: {str(e)[:100]}..."
                
                return {
                    **config_status,
                    "vault_connectivity": "successful",
                    "authentication_type": vault_info["authentication_type"],
                    "secret_accessible": secret_accessible,
                    "cache_ttl_minutes": vault_info["cache_ttl_minutes"]
                }
                
            except Exception as e:
                return {
                    **config_status,
                    "vault_connectivity": "failed",
                    "error": str(e)[:200]
                }
        
        return self.check_component_health("vault", check_vault)
    
    def _check_database_configuration(self) -> Dict[str, Any]:
        """Check PostgreSQL database configuration."""
        def check_db_config():
            config = get_config()
            
            # Required environment variables
            required_env_vars = {
                "KEY_VAULT": os.getenv("KEY_VAULT"),
                "KEY_VAULT_DATABASE_SECRET": os.getenv("KEY_VAULT_DATABASE_SECRET"), 
                "POSTGIS_DATABASE": os.getenv("POSTGIS_DATABASE"),
                "POSTGIS_HOST": os.getenv("POSTGIS_HOST"),
                "POSTGIS_USER": os.getenv("POSTGIS_USER"),
                "POSTGIS_PORT": os.getenv("POSTGIS_PORT")
            }
            
            # Optional environment variables
            optional_env_vars = {
                "POSTGIS_PASSWORD": bool(os.getenv("POSTGIS_PASSWORD")),
                "POSTGIS_SCHEMA": os.getenv("POSTGIS_SCHEMA", "geo"),
                "APP_SCHEMA": os.getenv("APP_SCHEMA", "app")
            }
            
            # Check for missing required variables
            missing_vars = []
            present_vars = {}
            
            for var_name, var_value in required_env_vars.items():
                if var_value:
                    present_vars[var_name] = var_value
                else:
                    missing_vars.append(var_name)
            
            # Configuration from loaded config
            config_values = {
                "postgis_host": config.postgis_host,
                "postgis_port": config.postgis_port,
                "postgis_user": config.postgis_user,
                "postgis_database": config.postgis_database,
                "postgis_schema": config.postgis_schema,
                "app_schema": config.app_schema,
                "key_vault_name": config.key_vault_name,
                "key_vault_database_secret": config.key_vault_database_secret,
                "postgis_password_configured": bool(config.postgis_password)
            }
            
            return {
                "required_env_vars_present": present_vars,
                "missing_required_vars": missing_vars,
                "optional_env_vars": optional_env_vars,
                "loaded_config_values": config_values,
                "configuration_complete": len(missing_vars) == 0
            }
        
        return self.check_component_health("database_config", check_db_config)
    
    def _should_check_database(self) -> bool:
        """Check if database health check is enabled."""
        return os.getenv("ENABLE_DATABASE_HEALTH_CHECK", "false").lower() == "true"
    
    def _check_import_validation(self) -> Dict[str, Any]:
        """
        Check import validation status using enhanced auto-discovery validator.
        
        Provides comprehensive import health including:
        - Critical dependency validation (Azure SDK, Pydantic, etc.)
        - Auto-discovered application module validation
        - Historical validation tracking
        - Registry file status
        
        Returns:
            Dict with import validation health status
        """
        def check_imports():
            # Get comprehensive health status from enhanced validator
            import_status = validator.get_health_status()
            
            # Extract key metrics from validation results
            validation_results = import_status.get('imports', {})
            auto_discovery = validation_results.get('auto_discovery', {})
            critical_imports = validation_results.get('critical_imports', {})
            application_modules = validation_results.get('application_modules', {})
            
            # Count successful vs failed imports
            critical_success = len([m for m, d in critical_imports.get('details', {}).items() 
                                  if d.get('status') == 'success'])
            critical_total = len(critical_imports.get('details', {}))
            critical_failed = len(critical_imports.get('failed', []))
            
            app_success = len([m for m, d in application_modules.get('details', {}).items() 
                             if d.get('status') == 'success'])
            app_total = len(application_modules.get('details', {}))
            app_failed = len(application_modules.get('failed', []))
            
            # Generate summary statistics
            total_modules = critical_total + app_total
            total_success = critical_success + app_success
            total_failed = critical_failed + app_failed
            success_rate = (total_success / total_modules * 100) if total_modules > 0 else 0
            
            # Check if registry file exists and is accessible
            registry_status = "unknown"
            try:
                import os
                if os.path.exists('import_validation_registry.json'):
                    registry_status = "accessible"
                    registry_size = os.path.getsize('import_validation_registry.json')
                else:
                    registry_status = "not_found"
                    registry_size = 0
            except Exception as e:
                registry_status = f"error: {str(e)[:50]}"
                registry_size = 0
            
            # Get validation timestamp for cache status
            validation_timestamp = validation_results.get('timestamp', 'unknown')
            cache_age = "unknown"
            if validation_timestamp != 'unknown':
                try:
                    val_time = datetime.fromisoformat(validation_timestamp.replace('Z', '+00:00'))
                    cache_age = (datetime.now(timezone.utc).replace(tzinfo=None) - val_time.replace(tzinfo=None)).total_seconds()
                    cache_age = f"{int(cache_age)}s ago"
                except:
                    cache_age = "parse_error"
            
            return {
                "overall_success": import_status.get('overall_success', False),
                "validation_summary": import_status.get('summary', 'No summary available'),
                "statistics": {
                    "total_modules_discovered": total_modules,
                    "successful_imports": total_success,
                    "failed_imports": total_failed,
                    "success_rate_percent": round(success_rate, 1)
                },
                "critical_dependencies": {
                    "total": critical_total,
                    "successful": critical_success,
                    "failed": critical_failed,
                    "failed_modules": critical_imports.get('failed', [])
                },
                "application_modules": {
                    "total": app_total,
                    "successful": app_success, 
                    "failed": app_failed,
                    "failed_modules": application_modules.get('failed', []),
                    "auto_discovered": auto_discovery.get('modules_discovered', 0)
                },
                "auto_discovery": {
                    "enabled": True,
                    "modules_discovered": auto_discovery.get('modules_discovered', 0),
                    "patterns_used": auto_discovery.get('discovery_patterns_used', 0),
                    "registry_updated": auto_discovery.get('registry_updated', False)
                },
                "registry_file": {
                    "status": registry_status,
                    "size_bytes": registry_size if registry_status == "accessible" else None,
                    "location": "import_validation_registry.json"
                },
                "validation_cache": {
                    "timestamp": validation_timestamp,
                    "age": cache_age,
                    "cache_duration": "5 minutes"
                },
                "startup_validation": {
                    "enabled": validator.is_azure_functions or validator.force_validation,
                    "fail_fast_active": validator.is_azure_functions,
                    "environment_detected": "azure_functions" if validator.is_azure_functions else "local"
                }
            }
        
        return self.check_component_health("import_validation", check_imports)

    def _check_duckdb(self) -> Dict[str, Any]:
        """
        Check DuckDB analytical engine health (optional component).

        DuckDB is an optional analytical query engine used for:
        - Serverless queries over Azure Blob Storage Parquet files
        - Spatial analytics with PostGIS-like ST_* functions
        - GeoParquet exports for Gold tier data products

        This component is NOT critical for core operations - health check
        will not fail if DuckDB is unavailable or not installed.

        Returns:
            Dict with DuckDB health status, extensions, and connection info
        """
        def check_duckdb():
            try:
                # Try to import DuckDB repository
                from infrastructure.factory import RepositoryFactory

                # Create DuckDB repository singleton
                duckdb_repo = RepositoryFactory.create_duckdb_repository()

                # Get comprehensive health check from repository
                health_result = duckdb_repo.health_check()

                # Add component metadata
                health_result["component_type"] = "analytical_engine"
                health_result["optional"] = True
                health_result["purpose"] = "Serverless Parquet queries and GeoParquet exports"

                return health_result

            except ImportError as e:
                # DuckDB not installed - this is OK, it's optional
                return {
                    "status": "not_installed",
                    "optional": True,
                    "message": "DuckDB not installed (optional dependency)",
                    "install_command": "pip install duckdb>=1.1.0 pyarrow>=10.0.0",
                    "impact": "GeoParquet exports and serverless blob queries unavailable"
                }
            except Exception as e:
                # Other errors during initialization
                import traceback
                return {
                    "status": "error",
                    "optional": True,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "Analytical queries and GeoParquet exports unavailable"
                }

        return self.check_component_health("duckdb", check_duckdb)

    def _check_vsi_support(self) -> Dict[str, Any]:
        """
        Check rasterio VSI (Virtual File System) support (critical for Big Raster ETL).

        VSI allows reading rasters directly from cloud storage without downloading to /tmp.
        This is REQUIRED for Big Raster ETL workflow to avoid /tmp disk space exhaustion
        (Azure Functions /tmp is limited to ~500MB).

        Tests:
        - /vsicurl/ - HTTP/HTTPS access (works with SAS URLs)
        - GDAL drivers available
        - Connection to cloud storage

        Returns:
            Dict with VSI capability status and test results
        """
        def check_vsi():
            try:
                import rasterio
                from rasterio.env import Env
                from infrastructure.factory import RepositoryFactory
                from config import get_config

                # Get configuration
                config = get_config()

                # Get BlobRepository to generate SAS URL
                blob_repo = RepositoryFactory.create_blob_repository()

                # Use configured test file and container
                test_blob = config.vsi_test_file
                test_container = config.vsi_test_container

                # Generate SAS URL (4 hour expiry for health check stability)
                test_url = blob_repo.get_blob_url_with_sas(
                    container_name=test_container,
                    blob_name=test_blob,
                    hours=4
                )

                vsi_path = f"/vsicurl/{test_url}"

                # Test with timeout to prevent hanging
                with Env(GDAL_HTTP_TIMEOUT=10, CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff"):
                    try:
                        with rasterio.open(vsi_path) as src:
                            # Successfully opened via /vsicurl/
                            width = src.width
                            height = src.height
                            bands = src.count
                            driver = src.driver

                            return {
                                "status": "healthy",
                                "vsicurl_supported": True,
                                "gdal_version": rasterio.__gdal_version__,
                                "rasterio_version": rasterio.__version__,
                                "test_results": {
                                    "test_file": test_blob,
                                    "container": test_container,
                                    "file_size": f"{width}x{height}",
                                    "bands": bands,
                                    "driver": driver,
                                    "test_status": "success"
                                },
                                "capabilities": {
                                    "http_streaming": True,
                                    "https_streaming": True,
                                    "cloud_optimized_geotiff": True,
                                    "azure_blob_sas_compatible": True
                                },
                                "big_raster_etl_ready": True,
                                "note": f"/vsicurl/ works with Azure Blob Storage SAS URLs - tested with {test_container}/{test_blob}",
                                "config_source": "config.vsi_test_file, config.vsi_test_container"
                            }
                    except Exception as open_error:
                        # Failed to open file via /vsicurl/
                        return {
                            "status": "error",
                            "vsicurl_supported": False,
                            "gdal_version": rasterio.__gdal_version__,
                            "rasterio_version": rasterio.__version__,
                            "error": f"Failed to open test file: {str(open_error)[:200]}",
                            "error_type": type(open_error).__name__,
                            "test_url": f"{test_container}/{test_blob}",
                            "test_container": test_container,
                            "big_raster_etl_ready": False,
                            "impact": "Big Raster ETL will fail - cannot read from cloud storage without downloading"
                        }

            except ImportError as e:
                # Rasterio not installed
                return {
                    "status": "not_installed",
                    "error": "Rasterio not installed",
                    "install_command": "pip install rasterio>=1.3.0",
                    "big_raster_etl_ready": False,
                    "impact": "Big Raster ETL completely unavailable"
                }
            except Exception as e:
                # Other errors during initialization
                import traceback
                return {
                    "status": "error",
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "big_raster_etl_ready": False,
                    "impact": "Big Raster ETL may be unavailable"
                }

        return self.check_component_health("vsi_support", check_vsi)

    def _check_jobs_registry(self) -> Dict[str, Any]:
        """
        Check jobs registry status and available job types.

        This provides visibility into which jobs are registered and available,
        helping diagnose deployment issues where jobs fail to register.

        Returns:
            Dict with jobs registry health status including:
            - available_jobs: List of registered job type names
            - total_jobs: Count of registered jobs
            - registry_location: Where jobs are registered
            - validation_performed: Whether validation was successful
        """
        def check_jobs():
            from jobs import ALL_JOBS

            job_types = sorted(list(ALL_JOBS.keys()))

            return {
                "available_jobs": job_types,
                "total_jobs": len(job_types),
                "registry_location": "jobs/__init__.py",
                "validation_performed": True,
                "registry_type": "explicit",
                "note": "Jobs are explicitly registered in jobs/__init__.py ALL_JOBS dict"
            }

        return self.check_component_health("jobs", check_jobs)

    def _check_pgstac(self) -> Dict[str, Any]:
        """
        Check PgSTAC (PostgreSQL STAC extension) health.

        This provides visibility into PgSTAC installation status and critical table availability,
        particularly the pgstac.searches table which is required for TiTiler integration.

        Returns:
            Dict with PgSTAC health status including:
            - pgstac_version: Version string from pgstac.get_version()
            - schema_exists: Whether pgstac schema exists
            - critical_tables: Status of collections, items, searches tables
            - searches_table_exists: Specific check for searches table (required for search registration)
            - table_counts: Row counts for collections and items
        """
        def check_pgstac():
            from infrastructure.postgresql import PostgreSQLRepository
            from config import get_config

            config = get_config()
            repo = PostgreSQLRepository(schema_name='pgstac')

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Check if pgstac schema exists
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'pgstac') as schema_exists"
                        )
                        schema_exists = cur.fetchone()['schema_exists']

                        if not schema_exists:
                            return {
                                "schema_exists": False,
                                "installed": False,
                                "error": "PgSTAC schema not found - run /api/stac/setup to install",
                                "impact": "STAC collections and items cannot be created"
                            }

                        # Get PgSTAC version
                        pgstac_version = None
                        try:
                            cur.execute("SELECT pgstac.get_version() as version")
                            pgstac_version = cur.fetchone()['version']
                        except Exception as ver_error:
                            pgstac_version = f"error: {str(ver_error)[:100]}"

                        # Check critical tables existence
                        critical_tables = {}
                        for table_name in ['collections', 'items', 'searches']:
                            cur.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables
                                    WHERE table_schema = 'pgstac'
                                    AND table_name = %s
                                ) as table_exists
                            """, (table_name,))
                            table_exists = cur.fetchone()['table_exists']
                            critical_tables[table_name] = table_exists

                        # Get row counts for collections and items
                        table_counts = {}

                        if critical_tables.get('collections', False):
                            try:
                                cur.execute("SELECT COUNT(*) as count FROM pgstac.collections")
                                table_counts['collections'] = cur.fetchone()['count']
                            except Exception:
                                table_counts['collections'] = "error"
                        else:
                            table_counts['collections'] = "table_missing"

                        if critical_tables.get('items', False):
                            try:
                                cur.execute("SELECT COUNT(*) as count FROM pgstac.items")
                                table_counts['items'] = cur.fetchone()['count']
                            except Exception:
                                table_counts['items'] = "error"
                        else:
                            table_counts['items'] = "table_missing"

                        # Specific check for searches table (critical for TiTiler integration)
                        searches_table_exists = critical_tables.get('searches', False)

                        # Check critical functions for search registration (18 NOV 2025)
                        critical_functions = {}
                        function_warnings = []

                        try:
                            # Check for search_tohash and search_hash functions
                            cur.execute("""
                                SELECT p.proname
                                FROM pg_proc p
                                JOIN pg_namespace n ON p.pronamespace = n.oid
                                WHERE n.nspname = 'pgstac'
                                AND p.proname IN ('search_tohash', 'search_hash')
                            """)
                            functions_found = [row['proname'] for row in cur.fetchall()]

                            critical_functions['search_tohash'] = 'search_tohash' in functions_found
                            critical_functions['search_hash'] = 'search_hash' in functions_found

                            # Check if searches table has GENERATED hash column
                            if searches_table_exists:
                                try:
                                    cur.execute("""
                                        SELECT column_name, is_generated
                                        FROM information_schema.columns
                                        WHERE table_schema = 'pgstac'
                                        AND table_name = 'searches'
                                        AND column_name = 'hash'
                                    """)
                                    hash_column = cur.fetchone()

                                    if hash_column and hash_column.get('is_generated') == 'ALWAYS':
                                        critical_functions['searches_hash_column_generated'] = True
                                    else:
                                        critical_functions['searches_hash_column_generated'] = False
                                        function_warnings.append("searches.hash is not a GENERATED column")
                                except Exception:
                                    critical_functions['searches_hash_column_generated'] = None

                            # Generate warnings for missing functions
                            if not critical_functions['search_tohash']:
                                function_warnings.append("Missing function: pgstac.search_tohash()")
                            if not critical_functions['search_hash']:
                                function_warnings.append("Missing function: pgstac.search_hash()")

                        except Exception as func_error:
                            critical_functions['error'] = str(func_error)[:100]

                        # Determine overall health status
                        all_tables_exist = all(critical_tables.values())
                        all_functions_exist = critical_functions.get('search_tohash', False) and critical_functions.get('search_hash', False)

                        result = {
                            "schema_exists": True,
                            "installed": True,
                            "pgstac_version": pgstac_version,
                            "critical_tables": critical_tables,
                            "searches_table_exists": searches_table_exists,
                            "critical_functions": critical_functions,
                            "table_counts": table_counts,
                            "all_critical_tables_present": all_tables_exist,
                            "all_critical_functions_present": all_functions_exist
                        }

                        # Add warnings if issues detected
                        warnings = []

                        if not searches_table_exists:
                            warnings.append("pgstac.searches table missing - search registration will fail")

                        if not all_functions_exist:
                            warnings.extend(function_warnings)
                            warnings.append("Search registration will fail - run /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes")

                        if warnings:
                            result["warnings"] = warnings
                            result["impact"] = "Cannot register pgSTAC searches for TiTiler visualization"
                            result["fix"] = "Run /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes to reinstall pgSTAC"

                        return result

            except Exception as e:
                import traceback
                return {
                    "schema_exists": False,
                    "installed": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "PgSTAC health check failed - STAC operations may be impacted"
                }

        return self.check_component_health("pgstac", check_pgstac)


# Create singleton instance for use in function_app.py
health_check_trigger = HealthCheckTrigger()