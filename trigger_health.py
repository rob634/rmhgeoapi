# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: System health monitoring HTTP endpoint with component validation
# SOURCE: Environment variables (PostgreSQL) + Managed Identity (Azure Storage)
# SCOPE: HTTP-specific health checks for all system components and dependencies
# VALIDATION: Component health validation + infrastructure connectivity checks
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

import azure.functions as func
from trigger_http_base import SystemMonitoringTrigger
from config import get_config


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
        
        # Check storage queues
        queue_health = self._check_storage_queues()
        health_data["components"]["queues"] = queue_health
        if queue_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(queue_health.get("errors", []))
        
        # Check storage tables
        table_health = self._check_storage_tables()
        health_data["components"]["tables"] = table_health
        if table_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(table_health.get("errors", []))
        
        # Key Vault disabled - using environment variables only
        # vault_health = self._check_vault_configuration()
        # health_data["components"]["vault"] = vault_health
        from datetime import datetime
        health_data["components"]["vault"] = {
            "component": "vault", 
            "status": "disabled",
            "details": {"message": "Key Vault disabled - using environment variables only"},
            "checked_at": datetime.utcnow().isoformat() + "Z"
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
        
        return health_data
    
    def _check_storage_queues(self) -> Dict[str, Any]:
        """Check Azure Storage Queue health."""
        def check_queues():
            from azure.storage.queue import QueueServiceClient
            from azure.identity import DefaultAzureCredential
            from config import QueueNames
            
            config = get_config()
            credential = DefaultAzureCredential()
            queue_service = QueueServiceClient(
                account_url=f"https://{config.storage_account_name}.queue.core.windows.net",
                credential=credential
            )
            
            queue_status = {}
            for queue_name in [QueueNames.JOBS, QueueNames.TASKS]:
                try:
                    queue_client = queue_service.get_queue_client(queue_name)
                    properties = queue_client.get_queue_properties()
                    queue_status[queue_name] = {
                        "status": "accessible",
                        "message_count": properties.approximate_message_count
                    }
                except Exception as e:
                    queue_status[queue_name] = {
                        "status": "error",
                        "error": str(e)
                    }
            
            return queue_status
        
        return self.check_component_health("storage_queues", check_queues)
    
    def _check_storage_tables(self) -> Dict[str, Any]:
        """Check Azure Table Storage health."""
        def check_tables():
            from azure.data.tables import TableServiceClient
            from azure.identity import DefaultAzureCredential
            
            config = get_config()
            credential = DefaultAzureCredential()
            table_service = TableServiceClient(
                endpoint=f"https://{config.storage_account_name}.table.core.windows.net",
                credential=credential
            )
            
            table_status = {}
            for table_name in ["jobs", "tasks"]:
                try:
                    table_client = table_service.get_table_client(table_name)
                    # Simple query to test accessibility
                    entities = list(table_client.list_entities(select="PartitionKey", results_per_page=1))
                    table_status[table_name] = {
                        "status": "accessible",
                        "sample_entities": len(entities)
                    }
                except Exception as e:
                    table_status[table_name] = {
                        "status": "error", 
                        "error": str(e)
                    }
            
            return table_status
        
        return self.check_component_health("storage_tables", check_tables)
    
    def _check_database(self) -> Dict[str, Any]:
        """Check PostgreSQL database health (optional)."""
        def check_pg():
            import psycopg
            from config import get_config
            
            config = get_config()
            
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
                        # Define required table schemas
                        table_definitions = {
                            'jobs': """
                                CREATE TABLE IF NOT EXISTS {schema}.jobs (
                                    id VARCHAR(255) PRIMARY KEY,
                                    job_type VARCHAR(100) NOT NULL,
                                    status VARCHAR(50) DEFAULT 'queued',
                                    stage INTEGER DEFAULT 1,
                                    total_stages INTEGER DEFAULT 1,
                                    parameters JSONB,
                                    stage_results JSONB DEFAULT '{{}}',
                                    result_data JSONB,
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    heartbeat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                )
                            """,
                            'tasks': """
                                CREATE TABLE IF NOT EXISTS {schema}.tasks (
                                    id VARCHAR(255) PRIMARY KEY,
                                    job_id VARCHAR(255) NOT NULL,
                                    task_type VARCHAR(100) NOT NULL,
                                    status VARCHAR(50) DEFAULT 'queued',
                                    stage_number INTEGER NOT NULL,
                                    parameters JSONB,
                                    result_data JSONB,
                                    retry_count INTEGER DEFAULT 0,
                                    heartbeat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    FOREIGN KEY (job_id) REFERENCES {schema}.jobs(id) ON DELETE CASCADE
                                )
                            """
                        }
                        
                        for table_name, table_sql in table_definitions.items():
                            try:
                                # Check if table exists
                                cur.execute(
                                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                                    (config.app_schema, table_name)
                                )
                                table_exists = cur.fetchone() is not None
                                
                                if not table_exists:
                                    # Create the table
                                    formatted_sql = table_sql.format(schema=config.app_schema)
                                    cur.execute(formatted_sql)
                                    table_management_results[table_name] = "created"
                                    app_tables_status[table_name] = True
                                else:
                                    # Validate existing table schema
                                    cur.execute("""
                                        SELECT column_name, data_type 
                                        FROM information_schema.columns 
                                        WHERE table_schema = %s AND table_name = %s
                                        ORDER BY ordinal_position
                                    """, (config.app_schema, table_name))
                                    columns = cur.fetchall()
                                    
                                    required_columns = {
                                        'jobs': ['id', 'job_type', 'status', 'stage', 'total_stages', 'parameters'],
                                        'tasks': ['id', 'job_id', 'task_type', 'status', 'stage_number', 'parameters']
                                    }
                                    
                                    existing_columns = [col[0] for col in columns]
                                    missing_columns = [col for col in required_columns[table_name] if col not in existing_columns]
                                    
                                    if missing_columns:
                                        table_management_results[table_name] = f"schema_incomplete_missing_{len(missing_columns)}_columns"
                                        app_tables_status[table_name] = "schema_invalid"
                                    else:
                                        table_management_results[table_name] = "validated"
                                        app_tables_status[table_name] = True
                                        
                            except Exception as table_error:
                                table_management_results[table_name] = f"error_{str(table_error)[:50]}"
                                app_tables_status[table_name] = False
                    
                    return {
                        "postgresql_version": pg_version.split()[0],
                        "postgis_version": postgis_version,
                        "connection": "successful",
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
                        }
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
            from repository_vault import VaultRepositoryFactory, VaultAccessError
            
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
                "APP_SCHEMA": os.getenv("APP_SCHEMA", "rmhgeoapi")
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


# Create singleton instance for use in function_app.py
health_check_trigger = HealthCheckTrigger()