# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# CATEGORY: HTTP TRIGGER ENDPOINTS
# PURPOSE: Azure Functions HTTP API endpoint
# EPOCH: Shared by all epochs (API layer)
# TODO: Audit for framework logic that may belong in CoreMachine# PURPOSE: System health monitoring HTTP trigger handling GET /api/health requests
# EXPORTS: HealthCheckTrigger (HTTP trigger class for comprehensive health checks)
# INTERFACES: SystemMonitoringTrigger (inherited from trigger_http_base)
# PYDANTIC_MODELS: None directly - uses dict responses for health status
# DEPENDENCIES: trigger_http_base, config, service_schema_manager, util_import_validator, azure.functions
# SOURCE: HTTP GET requests, environment variables, component status from various services
# SCOPE: HTTP endpoint for monitoring all system components - database, storage, queues, imports
# VALIDATION: Component connectivity checks, schema validation, import validation, configuration checks
# PATTERNS: Template Method (implements base class), Health Check pattern, Component pattern
# ENTRY_POINTS: trigger = HealthCheckTrigger(); response = trigger.handle_request(req)
# INDEX: HealthCheckTrigger:45, process_request:55, handle_request:125, _check_database:265, _check_import_validation:710
# ============================================================================

"""
Health Check HTTP Trigger - System Monitoring

Concrete implementation of health check endpoint using BaseHttpTrigger.
Performs comprehensive health checks on all system components.

Usage:
    GET /api/health
    
Response:
    {
        "status": "healthy" | "unhealthy",
        "components": {
            "storage": {...},
            "queues": {...}, 
            "database": {...}
        },
        "timestamp": "ISO-8601",
        "request_id": "uuid"
    }

Author: Azure Geospatial ETL Team
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
                "function_runtime": "python"
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
        duckdb_health = self._check_duckdb()
        health_data["components"]["duckdb"] = duckdb_health
        # Note: DuckDB is optional - don't fail overall health if unavailable
        if duckdb_health["status"] == "error":
            health_data["errors"].append("DuckDB unavailable (optional analytical component)")

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
        """Enhanced PostgreSQL database health check with query metrics."""
        def check_pg():
            import psycopg
            import time
            from config import get_config
            
            config = get_config()
            start_time = time.time()
            
            # Build connection string
            # NOTE: Using config.postgis_password here (vs direct env var used by PostgreSQL adapter)
            # Both access the same POSTGIS_PASSWORD env var. See config.py postgis_password field documentation.
            conn_str = (
                f"host={config.postgis_host} "
                f"dbname={config.postgis_database} "
                f"user={config.postgis_user} "
                f"password={config.postgis_password} "
                f"port={config.postgis_port}"
            )
            
            with psycopg.connect(conn_str) as conn:
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
                    app_tables_status = {}
                    table_management_results = {}
                    
                    if app_schema_exists:
                        try:
                            # Use enhanced schema manager for complete table creation
                            schema_manager = SchemaManagerFactory.create_schema_manager()
                            validation_results = schema_manager.validate_and_initialize_schema()
                            
                            # Map schema manager results to health check format
                            if validation_results.get('tables_created'):
                                # Tables were created with complete schema
                                created_tables = validation_results.get('tables_created', [])
                                for table in ['jobs', 'tasks']:
                                    if table in created_tables:
                                        app_tables_status[table] = True
                                        table_management_results[table] = "created_with_complete_schema"
                                    else:
                                        app_tables_status[table] = True
                                        table_management_results[table] = "validated"
                            elif validation_results.get('tables_exist', False):
                                # Check for schema issues
                                schema_issues = validation_results.get('schema_issues', {})
                                for table in ['jobs', 'tasks']:
                                    if table in schema_issues:
                                        app_tables_status[table] = "schema_invalid"
                                        issues = schema_issues[table]
                                        table_management_results[table] = f"schema_issues: {', '.join(issues[:2])}"
                                    else:
                                        app_tables_status[table] = True
                                        table_management_results[table] = "validated"
                            else:
                                # Handle missing tables or other issues
                                missing_tables = validation_results.get('missing_tables', [])
                                existing_tables = validation_results.get('existing_tables', [])
                                
                                for table in ['jobs', 'tasks']:
                                    if table in missing_tables:
                                        app_tables_status[table] = "missing"
                                        table_management_results[table] = "table_missing_creation_failed"
                                    elif table in existing_tables:
                                        app_tables_status[table] = True
                                        table_management_results[table] = "validated"
                                    else:
                                        app_tables_status[table] = "unknown"
                                        table_management_results[table] = "status_unknown"
                                        
                        except Exception as schema_error:
                            # Fallback error handling
                            table_management_results['schema_manager_error'] = f"error: {str(schema_error)}"
                            app_tables_status['jobs'] = "error"
                            app_tables_status['tasks'] = "error"
                    
                    # DETAILED SCHEMA INSPECTION - Added for debugging function signature mismatches
                    detailed_schema_info = {}
                    try:
                        # Inspect actual table columns in the database
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
                        
                        # Inspect PostgreSQL function signatures
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
                        
                        # Test the problematic function call directly (isolated transaction)
                        try:
                            with conn.transaction():
                                cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_job_id')")
                                detailed_schema_info['function_test'] = "SUCCESS - Function signature matches query"
                        except Exception as func_error:
                            # Transaction auto-rolled back, cursor remains valid
                            detailed_schema_info['function_test'] = f"ERROR: {str(func_error)}"
                            detailed_schema_info['function_error_type'] = type(func_error).__name__

                    except Exception as inspect_error:
                        # Transaction auto-rolled back if it fails
                        detailed_schema_info['inspection_error'] = f"Failed to inspect schema: {str(inspect_error)}"
                    
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


# Create singleton instance for use in function_app.py
health_check_trigger = HealthCheckTrigger()