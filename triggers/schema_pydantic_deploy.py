# ============================================================================
# PYDANTIC SCHEMA DEPLOYMENT TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/schema/deploy
# PURPOSE: Deploy Pydantic-generated schema to PostgreSQL database
# LAST_REVIEWED: 23 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: PydanticSchemaDeployTrigger, pydantic_schema_deploy_trigger
# DEPENDENCIES: psycopg, core.schema.sql_generator
# ============================================================================
"""
Pydantic Schema Deployment Trigger.

HTTP trigger for deploying Pydantic-generated schema to PostgreSQL database.

Exports:
    PydanticSchemaDeployTrigger: HTTP trigger class for schema deployment
    pydantic_schema_deploy_trigger: Singleton instance of PydanticSchemaDeployTrigger
"""

import azure.functions as func
import json
import psycopg
from psycopg import sql
from datetime import datetime, timezone

from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext
from config import get_config
from core.schema.sql_generator import PydanticToSQL
from core.models import (
    JobRecord,
    TaskRecord,
    ApiRequest
)
# NOTE: OrchestrationJob REMOVED (22 NOV 2025) - no job chaining in Platform

class PydanticSchemaDeployTrigger:
    """
    Deploy Pydantic-generated schema using ONLY composed SQL statements.
    NO STRING CONCATENATION - Following "No Backward Compatibility" philosophy.
    """
    
    def __init__(self):
        self.logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "PydanticDeploy")
        self.config = get_config()
    
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle schema operations - info, deploy, compare.
        
        Routes based on HTTP method and action parameter:
        - GET with action=info or no action: Show schema info
        - GET with action=compare: Show comparison info  
        - POST: Deploy schema (requires confirm=yes)
        
        Args:
            req: HTTP request
            
        Returns:
            HTTP response with operation results
        """
        method = req.method.upper()
        
        try:
            if method == "GET":
                # Check for action parameter
                action = req.params.get('action', 'info')
                
                if action == 'info' or action == 'generate':
                    return self._get_schema_info(req)
                elif action == 'compare':
                    return self._compare_schema(req)
                else:
                    return self._error_response(f"Unknown action: {action}", 400)
                    
            elif method == "POST":
                # Deploy schema
                return self._deploy_schema_handler(req)
            else:
                return self._error_response(f"Method {method} not supported", 405)
                
        except Exception as e:
            self.logger.error(f"Schema operation failed: {e}")
            return self._error_response(str(e), 500)
    
    def _get_schema_info(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get information about schema that would be generated.
        
        Args:
            req: HTTP request
            
        Returns:
            Schema generation info
        """
        try:
            # Get options from query params
            schema_name = req.params.get('schema', self.config.app_schema)
            
            # Generate schema using composed statements
            generator = PydanticToSQL(schema_name=schema_name)
            composed_statements = generator.generate_composed_statements()
            
            # Prepare response with statistics
            response = {
                "status": "success",
                "message": "Schema info from Pydantic models",
                "note": "Using psycopg.sql composition for SQL injection safety",
                "deployment": "Use POST /api/schema/deploy?confirm=yes to deploy",
                "statistics": {
                    "total_statements": len(composed_statements),
                    "enums_generated": len(generator.enums),
                    "tables_generated": 2,  # jobs and tasks
                    "functions_included": len(generator.load_static_functions()),
                    "indexes_created": 10,
                    "triggers_created": 4
                },
                "schema_name": schema_name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "method": "psycopg.sql composition"
            }
            
            return func.HttpResponse(
                json.dumps(response),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Schema info generation failed: {e}")
            return self._error_response(f"Info generation failed: {e}", 500)
    
    def _compare_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Compare generated schema info with current database.
        
        Args:
            req: HTTP request
            
        Returns:
            Comparison information
        """
        try:
            generator = PydanticToSQL(schema_name=self.config.app_schema)
            composed_statements = generator.generate_composed_statements()
            
            comparison = {
                "status": "info",
                "message": "Schema comparison info",
                "explanation": "Using psycopg.sql composition for safety",
                "composed_statements_count": len(composed_statements),
                "statement_types": {
                    "schema_and_path": 2,
                    "enums": len(generator.enums) * 2,  # DROP + CREATE for each
                    "tables": 2,
                    "indexes": 10,
                    "functions": len(generator.load_static_functions()),
                    "triggers": 4  # 2 drops + 2 creates
                },
                "deployment_method": "Use POST /api/schema/deploy?confirm=yes",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            return func.HttpResponse(
                json.dumps(comparison),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Schema comparison failed: {e}")
            return self._error_response(f"Comparison failed: {e}", 500)
    
    def _deploy_schema_handler(self, req: func.HttpRequest) -> func.HttpResponse:
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

        ARCHITECTURE PRINCIPLE (16 NOV 2025):
        Uses PostgreSQLRepository for all database connections.
        NO direct psycopg.connect() calls - repository pattern only.

        Args:
            generator: The PydanticToSQL generator instance

        Returns:
            Deployment result dictionary
        """
        try:
            # Use PostgreSQLRepository for connection management (16 NOV 2025)
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

            with repo._get_connection() as conn:
                # Get composed statements for ALL schemas (23 JAN 2026 - Fix missing ETL tables)
                # Must generate in dependency order: geo → app_core → app_etl
                self.logger.info("📦 Generating composed SQL statements from Pydantic models")

                # 1. Geo schema (geo.table_catalog) - must come first for FK dependencies
                geo_statements = generator.generate_geo_schema_ddl()
                self.logger.info(f"📦 Generated {len(geo_statements)} geo schema statements")

                # 2. App core (jobs, tasks, api_requests, etc.)
                app_core_statements = generator.generate_composed_statements()
                self.logger.info(f"📦 Generated {len(app_core_statements)} app core statements")

                # 3. ETL tracking (vector_etl_tracking, raster_etl_tracking) - has FK to geo.table_catalog
                etl_statements = generator.generate_etl_tracking_ddl(conn=None, verify_dependencies=False)
                self.logger.info(f"📦 Generated {len(etl_statements)} ETL tracking statements")

                # Combine all statements in dependency order
                composed_statements = geo_statements + app_core_statements + etl_statements
                self.logger.info(f"📦 Total: {len(composed_statements)} composed statements")

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
                                # Still count as executed since object exists
                                executed_statements.append(f"{stmt_type} (exists): {stmt_preview}")
                                continue

                            self.logger.error(f"❌ Statement failed: {error_msg}")
                            self.logger.error(f"   Statement type: {stmt_type}")
                            self.logger.error(f"   Failed SQL (first 500 chars): {stmt_str[:500]}")
                            errors.append({
                                "statement_type": stmt_type,
                                "statement": stmt_preview,
                                "error": error_msg,
                                "full_error": str(stmt_error)
                            })

                # ================================================================
                # PLATFORM TABLES - NOW AUTO-GENERATED (29 OCT 2025)
                # ================================================================
                # Platform tables are now auto-generated from Pydantic models:
                #   - core/models/platform.py: ApiRequest, OrchestrationJob
                #   - core/schema/sql_generator.py: Added to generate_composed_statements()
                #
                # Previously: 70 lines of manual DDL here
                # Now: 0 lines - Infrastructure-as-Code pattern.
                #
                # Tables created (renamed 29 OCT 2025):
                #   - app.api_requests (from ApiRequest, previously PlatformRecord)
                #   - app.orchestration_jobs (from OrchestrationJob, previously PlatformRequestJobMapping)
                #   - app.platform_request_status_enum (from PlatformRequestStatus)
                #   - app.data_type_enum (from DataType)
                #
                # Benefits:
                #   - Zero drift between Pydantic models and database schema
                #   - Consistent with JobRecord/TaskRecord pattern
                #   - Update model → schema updates automatically
                #   - Reduced LOC (70 lines removed!)
                #
                # Reference: PLATFORM_SCHEMA_COMPARISON.md
                # ================================================================

                self.logger.info("✅ Platform tables auto-generated from Pydantic models (Infrastructure-as-Code)")

                # Commit all changes (app schema with Platform tables auto-generated)
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
                    "timestamp": datetime.now(timezone.utc).isoformat()
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
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        # Connection automatically closed by context manager - no finally block needed
    
    def _error_response(self, message: str, status_code: int) -> func.HttpResponse:
        """
        Create error response.
        
        Args:
            message: Error message
            status_code: HTTP status code
            
        Returns:
            Error HTTP response
        """
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=status_code,
            mimetype="application/json"
        )
    
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
                    SELECT COUNT(*) as cnt
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                """, (self.config.app_schema,))
                table_count = cur.fetchone()['cnt']

                # Get table names
                cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """, (self.config.app_schema,))
                table_list = [row['table_name'] for row in cur.fetchall()]

                # Count functions
                cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM information_schema.routines
                    WHERE routine_schema = %s
                """, (self.config.app_schema,))
                function_count = cur.fetchone()['cnt']

                # Get function names
                cur.execute("""
                    SELECT routine_name
                    FROM information_schema.routines
                    WHERE routine_schema = %s
                    ORDER BY routine_name
                """, (self.config.app_schema,))
                function_list = [row['routine_name'] for row in cur.fetchall()]

                # Count enums
                cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM pg_type t
                    JOIN pg_namespace n ON t.typnamespace = n.oid
                    WHERE n.nspname = %s
                    AND t.typtype = 'e'
                """, (self.config.app_schema,))
                enum_count = cur.fetchone()['cnt']
                
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