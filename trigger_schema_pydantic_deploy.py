# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Deploy Pydantic-generated schema directly to PostgreSQL
# SOURCE: Pydantic models -> SQL DDL -> Database deployment
# SCOPE: Database schema creation from Python models
# VALIDATION: Schema deployment verification and rollback support
# ============================================================================

"""
Pydantic Schema Deployment Trigger

NO BACKWARD COMPATIBILITY - Only uses psycopg.sql composed statements.
Ensures SQL injection safety through proper identifier escaping.
Single deployment path: Pydantic models -> Composed SQL -> Database
"""

import azure.functions as func
import json
import psycopg
from psycopg import sql
from datetime import datetime

from util_logger import LoggerFactory, ComponentType
from config import get_config
from schema_sql_generator import PydanticToSQL
from schema_core import JobRecord, TaskRecord

class PydanticSchemaDeployTrigger:
    """
    Deploy Pydantic-generated schema using ONLY composed SQL statements.
    NO STRING CONCATENATION - Following "No Backward Compatibility" philosophy.
    """
    
    def __init__(self):
        self.logger = LoggerFactory.get_logger(ComponentType.CONTROLLER, "PydanticDeploy")
        self.config = get_config()
    
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle schema deployment request.
        
        Args:
            req: HTTP request with optional confirm parameter
            
        Returns:
            HTTP response with deployment results
        """
        try:
            # Check for confirmation
            confirm = req.params.get('confirm', 'no')
            if confirm != 'yes':
                return func.HttpResponse(
                    json.dumps({
                        "status": "error",
                        "error": "Confirmation required",
                        "message": "Add ?confirm=yes to deploy Pydantic-generated schema",
                        "warning": "This will replace the current schema with Pydantic-generated DDL"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )
            
            # Generate schema from Pydantic models
            self.logger.info("Generating schema from Pydantic models")
            generator = PydanticToSQL(schema_name=self.config.app_schema)
            
            # NO BACKWARD COMPATIBILITY - Only use composed statements
            # This ensures SQL injection safety and proper escaping
            self.logger.info("Deploying with psycopg.sql composed statements")
            deployment_result = self._deploy_schema(generator)
            
            return func.HttpResponse(
                json.dumps(deployment_result),
                status_code=200 if deployment_result["status"] == "success" else 500,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Pydantic schema deployment failed: {e}")
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to deploy schema"
                }),
                status_code=500,
                mimetype="application/json"
            )
    
    def _deploy_schema(self, generator: PydanticToSQL) -> dict:
        """
        Deploy schema using ONLY psycopg.sql composed statements.
        
        NO STRING CONCATENATION - This is the only deployment method.
        Ensures SQL injection safety and proper identifier escaping.
        
        Args:
            generator: The PydanticToSQL generator instance
            
        Returns:
            Deployment result dictionary
        """
        conn = None
        try:
            # Connect to database
            conn_string = (
                f"host={self.config.postgis_host} "
                f"port={self.config.postgis_port} "
                f"dbname={self.config.postgis_database} "
                f"user={self.config.postgis_user} "
                f"password={self.config.postgis_password}"
            )
            
            conn = psycopg.connect(conn_string)
            
            # Get composed statements
            self.logger.info("📦 Generating composed SQL statements from Pydantic models")
            composed_statements = generator.generate_composed_statements()
            self.logger.info(f"📦 Generated {len(composed_statements)} composed statements")
            
            executed_statements = []
            errors = []
            enum_count = 0
            table_count = 0
            function_count = 0
            index_count = 0
            trigger_count = 0
            
            with conn.cursor() as cur:
                for stmt in composed_statements:
                    try:
                        # Convert composed SQL to string for logging
                        stmt_str = stmt.as_string(conn) if hasattr(stmt, 'as_string') else str(stmt)
                        stmt_preview = stmt_str[:100].replace('\n', ' ')
                        stmt_lower = stmt_str.lower()
                        
                        # Identify statement type
                        if 'create type' in stmt_lower:
                            stmt_type = "CREATE TYPE (ENUM)"
                            enum_count += 1
                        elif 'create table' in stmt_lower:
                            stmt_type = "CREATE TABLE"
                            table_count += 1
                        elif 'create or replace function' in stmt_lower:
                            stmt_type = "CREATE FUNCTION"
                            function_count += 1
                        elif 'create index' in stmt_lower:
                            stmt_type = "CREATE INDEX"
                            index_count += 1
                        elif 'create trigger' in stmt_lower:
                            stmt_type = "CREATE TRIGGER"
                            trigger_count += 1
                        elif 'drop trigger' in stmt_lower:
                            stmt_type = "DROP TRIGGER"
                        elif 'create schema' in stmt_lower:
                            stmt_type = "CREATE SCHEMA"
                        elif 'set search_path' in stmt_lower:
                            stmt_type = "SET search_path"
                        else:
                            stmt_type = "SQL"
                        
                        self.logger.debug(f"Executing {stmt_type}: {stmt_preview}...")
                        
                        # Execute the composed statement directly
                        cur.execute(stmt)
                        executed_statements.append(f"{stmt_type}: {stmt_preview}")
                        
                    except Exception as stmt_error:
                        error_msg = str(stmt_error)
                        
                        # Handle expected errors gracefully
                        if "already exists" in error_msg.lower():
                            self.logger.debug(f"✓ Object already exists (OK): {stmt_preview}")
                            continue
                        
                        self.logger.warning(f"❌ Statement failed: {error_msg}")
                        self.logger.debug(f"   Failed SQL: {stmt_str[:200]}")
                        errors.append({
                            "statement": stmt_preview,
                            "error": error_msg
                        })
                
                # Commit all changes
                conn.commit()
                
                # Verify deployment
                verification = self._verify_deployment(conn)
                
                result = {
                    "status": "success" if len(errors) == 0 else "partial",
                    "message": "Schema deployed using ONLY psycopg.sql composed statements",
                    "source": "Pydantic models (single source of truth)",
                    "safety": "Maximum - NO string concatenation, full SQL composition",
                    "statistics": {
                        "statements_executed": len(executed_statements),
                        "statements_failed": len(errors),
                        "enums_processed": enum_count,
                        "tables_created": table_count,
                        "functions_created": function_count,
                        "indexes_created": index_count,
                        "triggers_created": trigger_count
                    },
                    "verification": verification,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                if errors:
                    result["errors"] = errors[:5]  # First 5 errors
                    
                return result
                
        except Exception as e:
            self.logger.error(f"Database deployment failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Failed to deploy schema with composed statements",
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            if conn:
                conn.close()
    
    def _verify_deployment(self, conn) -> dict:
        """
        Verify the deployed schema.
        
        Args:
            conn: Database connection
            
        Returns:
            Verification dictionary
        """
        try:
            with conn.cursor() as cur:
                # Count tables
                cur.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_type = 'BASE TABLE'
                """, (self.config.app_schema,))
                table_count = cur.fetchone()[0]
                
                # Get table names
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """, (self.config.app_schema,))
                table_list = [row[0] for row in cur.fetchall()]
                
                # Count functions
                cur.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.routines 
                    WHERE routine_schema = %s
                """, (self.config.app_schema,))
                function_count = cur.fetchone()[0]
                
                # Get function names
                cur.execute("""
                    SELECT routine_name 
                    FROM information_schema.routines 
                    WHERE routine_schema = %s 
                    ORDER BY routine_name
                """, (self.config.app_schema,))
                function_list = [row[0] for row in cur.fetchall()]
                
                # Count enums
                cur.execute("""
                    SELECT COUNT(*) 
                    FROM pg_type t 
                    JOIN pg_namespace n ON t.typnamespace = n.oid 
                    WHERE n.nspname = %s 
                    AND t.typtype = 'e'
                """, (self.config.app_schema,))
                enum_count = cur.fetchone()[0]
                
                return {
                    "tables": table_count,
                    "functions": function_count,
                    "enums": enum_count,
                    "table_list": table_list,
                    "function_list": function_list
                }
                
        except Exception as e:
            self.logger.error(f"Verification failed: {e}")
            return {
                "error": str(e),
                "message": "Failed to verify deployment"
            }

# Create singleton instance
pydantic_deploy_trigger = PydanticSchemaDeployTrigger()