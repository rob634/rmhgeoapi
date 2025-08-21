"""
Database health check service for Azure Functions.
"""

from typing import Dict, Any, List
import time
from datetime import datetime, timezone

from services import BaseProcessingService
from database_client import DatabaseClient
from logger_setup import logger


class DatabaseHealthService(BaseProcessingService):
    """Service for checking database connectivity and health."""
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["database_health"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict[str, Any]:
        """
        Check database health and connectivity.
        
        Returns:
            Dictionary with health check results
        """
        logger.info("Starting database health check")
        start_time = time.time()
        
        health_status = {
            "service": "PostgreSQL Database",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "unknown",
            "details": {},
            "checks": []
        }
        
        try:
            # Create database client
            db = DatabaseClient()
            
            # Check 1: Basic connection
            logger.debug("Testing basic database connection")
            connection_check = {
                "name": "connection",
                "status": "pending",
                "message": "",
                "duration_ms": 0
            }
            check_start = time.time()
            
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                        if result and result[0] == 1:
                            connection_check["status"] = "healthy"
                            connection_check["message"] = "Connection successful"
                        else:
                            connection_check["status"] = "unhealthy"
                            connection_check["message"] = "Unexpected response from database"
            except Exception as e:
                connection_check["status"] = "unhealthy"
                connection_check["message"] = f"Connection failed: {str(e)}"
            
            connection_check["duration_ms"] = int((time.time() - check_start) * 1000)
            health_status["checks"].append(connection_check)
            
            # Check 2: Database version
            version_check = {
                "name": "version",
                "status": "pending",
                "message": "",
                "duration_ms": 0
            }
            check_start = time.time()
            
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT version()")
                        version = cursor.fetchone()[0]
                        version_check["status"] = "healthy"
                        version_check["message"] = version.split(' on ')[0]  # Just PostgreSQL version
                        health_status["details"]["postgresql_version"] = version
            except Exception as e:
                version_check["status"] = "unhealthy"
                version_check["message"] = f"Version check failed: {str(e)}"
            
            version_check["duration_ms"] = int((time.time() - check_start) * 1000)
            health_status["checks"].append(version_check)
            
            # Check 3: PostGIS extension
            postgis_check = {
                "name": "postgis",
                "status": "pending",
                "message": "",
                "duration_ms": 0
            }
            check_start = time.time()
            
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT PostGIS_version()")
                        postgis_version = cursor.fetchone()[0]
                        postgis_check["status"] = "healthy"
                        postgis_check["message"] = f"PostGIS {postgis_version.split(' ')[0]} available"
                        health_status["details"]["postgis_version"] = postgis_version
            except Exception as e:
                postgis_check["status"] = "warning"
                postgis_check["message"] = f"PostGIS not available: {str(e)}"
            
            postgis_check["duration_ms"] = int((time.time() - check_start) * 1000)
            health_status["checks"].append(postgis_check)
            
            # Check 4: Schema existence
            schema_check = {
                "name": "schema",
                "status": "pending",
                "message": "",
                "duration_ms": 0
            }
            check_start = time.time()
            
            try:
                if db.schema_exists():
                    schema_check["status"] = "healthy"
                    schema_check["message"] = f"Schema '{db.schema}' exists"
                    
                    # Count tables in schema
                    query = """
                        SELECT COUNT(*) 
                        FROM information_schema.tables 
                        WHERE table_schema = %s
                    """
                    tables = db.execute(query, [db.schema])
                    table_count = tables[0]['count'] if tables else 0
                    health_status["details"]["schema"] = db.schema
                    health_status["details"]["table_count"] = table_count
                else:
                    schema_check["status"] = "warning"
                    schema_check["message"] = f"Schema '{db.schema}' does not exist"
            except Exception as e:
                schema_check["status"] = "unhealthy"
                schema_check["message"] = f"Schema check failed: {str(e)}"
            
            schema_check["duration_ms"] = int((time.time() - check_start) * 1000)
            health_status["checks"].append(schema_check)
            
            # Check 5: Connection pool stats (if applicable)
            pool_check = {
                "name": "connection_pool",
                "status": "pending",
                "message": "",
                "duration_ms": 0
            }
            check_start = time.time()
            
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        # Check current connections
                        cursor.execute("""
                            SELECT count(*) 
                            FROM pg_stat_activity 
                            WHERE datname = %s
                        """, [db.database])
                        connection_count = cursor.fetchone()[0]
                        
                        # Check max connections
                        cursor.execute("SHOW max_connections")
                        max_connections = cursor.fetchone()[0]
                        
                        pool_check["status"] = "healthy"
                        pool_check["message"] = f"Connections: {connection_count}/{max_connections}"
                        health_status["details"]["current_connections"] = connection_count
                        health_status["details"]["max_connections"] = int(max_connections)
            except Exception as e:
                pool_check["status"] = "warning"
                pool_check["message"] = f"Pool stats unavailable: {str(e)}"
            
            pool_check["duration_ms"] = int((time.time() - check_start) * 1000)
            health_status["checks"].append(pool_check)
            
            # Overall status determination
            unhealthy_count = sum(1 for check in health_status["checks"] if check["status"] == "unhealthy")
            warning_count = sum(1 for check in health_status["checks"] if check["status"] == "warning")
            
            if unhealthy_count > 0:
                health_status["status"] = "unhealthy"
            elif warning_count > 0:
                health_status["status"] = "degraded"
            else:
                health_status["status"] = "healthy"
            
            # Add summary
            health_status["summary"] = {
                "total_checks": len(health_status["checks"]),
                "healthy": sum(1 for check in health_status["checks"] if check["status"] == "healthy"),
                "warnings": warning_count,
                "failures": unhealthy_count
            }
            
            # Add connection info (without password)
            health_status["connection_info"] = {
                "host": db.host,
                "port": db.port,
                "database": db.database,
                "user": db.user,
                "schema": db.schema
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
            health_status["checks"].append({
                "name": "initialization",
                "status": "unhealthy",
                "message": f"Failed to initialize database client: {str(e)}",
                "duration_ms": 0
            })
        
        # Calculate total duration
        health_status["duration_ms"] = int((time.time() - start_time) * 1000)
        
        logger.info(f"Database health check completed: {health_status['status']}")
        return health_status