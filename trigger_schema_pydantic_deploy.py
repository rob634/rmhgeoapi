# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Deploy Pydantic-generated schema directly to database
# SOURCE: Pydantic models as single source of truth
# SCOPE: Direct database deployment for testing
# VALIDATION: Executes generated DDL against PostgreSQL
# ============================================================================

"""
Direct Pydantic Schema Deployment Trigger.

This module provides an endpoint to deploy the Pydantic-generated schema
directly to the database, bypassing the static SQL templates.
"""

import json
from datetime import datetime
import azure.functions as func
import psycopg

from util_logger import LoggerFactory, ComponentType
from schema_sql_generator import PydanticToSQL
from config import get_config


class PydanticSchemaDeployTrigger:
    """
    HTTP trigger for deploying Pydantic-generated schema directly.
    """
    
    def __init__(self):
        """Initialize the deployment trigger."""
        self.logger = LoggerFactory.get_logger(ComponentType.HTTP_TRIGGER, "PydanticDeploy")
        self.config = get_config()
        
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Deploy Pydantic-generated schema to database.
        
        Args:
            req: Azure Functions HTTP request
            
        Returns:
            Deployment status response
        """
        try:
            # Safety check - require confirmation
            confirm = req.params.get('confirm', '')
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
            
            # Try to use composed statements for better SQL safety
            use_composed = req.params.get('use_composed', 'false') == 'true'
            
            if use_composed:
                # Use new psycopg.sql composed statements
                self.logger.info("Using psycopg.sql composed statements for deployment")
                deployment_result = self._deploy_composed_statements(generator)
            else:
                # Get statements as list for backwards compatibility
                statements = generator.generate_statements_list()
                # Deploy to database
                self.logger.info("Deploying Pydantic-generated schema to database")
                deployment_result = self._deploy_schema_statements(statements, generator)
            
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
                    "timestamp": datetime.utcnow().isoformat()
                }),
                status_code=500,
                mimetype="application/json"
            )
    
    def _deploy_composed_statements(self, generator: PydanticToSQL) -> dict:
        """
        Deploy schema using psycopg.sql composed statements for maximum safety.
        
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
            composed_statements = generator.generate_composed_statements()
            
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
                            self.logger.debug(f"Object already exists (OK): {stmt_preview}")
                            continue
                        
                        self.logger.warning(f"Statement failed: {error_msg}")
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
                    "message": "Schema deployed using psycopg.sql composed statements",
                    "source": "Pydantic models with psycopg.sql composition",
                    "safety": "Maximum - using psycopg.sql for injection prevention",
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
    
    def _deploy_schema_statements(self, statements: list, generator: PydanticToSQL) -> dict:
        """
        Deploy schema using pre-parsed statements for better error handling.
        
        Args:
            statements: List of SQL statements to execute
            generator: The generator instance for metadata
            
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
            
            executed_statements = []
            errors = []
            do_block_count = 0
            table_count = 0
            function_count = 0
            index_count = 0
            trigger_count = 0
            
            with conn.cursor() as cur:
                for stmt in statements:
                    if not stmt.strip():
                        continue
                    
                    try:
                        # Identify statement type for logging
                        stmt_lower = stmt.lower()
                        stmt_preview = stmt[:100].replace('\n', ' ')
                        
                        if 'do $$' in stmt_lower:
                            stmt_type = "DO Block (ENUM)"
                            do_block_count += 1
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
                        
                        # Execute the statement
                        cur.execute(stmt)
                        executed_statements.append(f"{stmt_type}: {stmt_preview}")
                        
                    except Exception as stmt_error:
                        error_msg = str(stmt_error)
                        
                        # Handle expected errors gracefully
                        if "already exists" in error_msg.lower():
                            self.logger.debug(f"Object already exists (OK): {stmt_preview}")
                            # Don't count as error if it's an expected duplicate
                            continue
                        
                        self.logger.warning(f"Statement failed: {error_msg}")
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
                    "message": "Pydantic-generated schema deployed with improved handling",
                    "source": "Pydantic models with psycopg.sql composition",
                    "statistics": {
                        "statements_executed": len(executed_statements),
                        "statements_failed": len(errors),
                        "do_blocks_processed": do_block_count,
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
                "message": "Failed to deploy Pydantic-generated schema",
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            if conn:
                conn.close()
    
    def _deploy_schema(self, sql_schema: str) -> dict:
        """
        Deploy the generated schema to PostgreSQL.
        
        Args:
            sql_schema: Generated SQL DDL
            
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
            
            with conn.cursor() as cur:
                # Split schema into individual statements
                # Remove comments and empty lines for cleaner execution
                statements = []
                current_statement = []
                in_function = False
                
                for line in sql_schema.split('\n'):
                    # Skip pure comment lines unless in function
                    if line.strip().startswith('--') and not in_function:
                        continue
                    
                    # Track function blocks
                    if 'CREATE OR REPLACE FUNCTION' in line or 'CREATE FUNCTION' in line:
                        in_function = True
                    
                    # Add line to current statement
                    if line.strip():
                        current_statement.append(line)
                    
                    # Check for statement end
                    if line.strip().endswith(';') and not in_function:
                        if current_statement:
                            statements.append('\n'.join(current_statement))
                            current_statement = []
                    elif line.strip().endswith('$$;'):
                        # End of function
                        if current_statement:
                            statements.append('\n'.join(current_statement))
                            current_statement = []
                        in_function = False
                
                # Execute each statement
                executed_statements = []
                errors = []
                
                for stmt in statements:
                    if not stmt.strip():
                        continue
                        
                    try:
                        # Log what we're executing (first 100 chars)
                        stmt_preview = stmt[:100].replace('\n', ' ')
                        self.logger.debug(f"Executing: {stmt_preview}...")
                        
                        cur.execute(stmt)
                        executed_statements.append(stmt_preview)
                        
                    except Exception as stmt_error:
                        error_msg = f"Statement failed: {str(stmt_error)}"
                        self.logger.warning(error_msg)
                        errors.append({
                            "statement": stmt[:100],
                            "error": str(stmt_error)
                        })
                        # Continue with other statements
                
                # Commit the transaction
                conn.commit()
                
                # Verify deployment
                verification = self._verify_deployment(conn)
                
                result = {
                    "status": "success" if len(errors) == 0 else "partial",
                    "message": "Pydantic-generated schema deployed",
                    "source": "Pydantic models (Python classes)",
                    "statistics": {
                        "statements_executed": len(executed_statements),
                        "statements_failed": len(errors),
                        "tables_created": verification.get("tables", 0),
                        "functions_created": verification.get("functions", 0),
                        "enums_created": verification.get("enums", 0)
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
                "message": "Failed to deploy Pydantic-generated schema",
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            if conn:
                conn.close()
    
    def _verify_deployment(self, conn) -> dict:
        """
        Verify what was deployed.
        
        Args:
            conn: Database connection
            
        Returns:
            Verification results
        """
        try:
            with conn.cursor() as cur:
                # Count tables
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                """, (self.config.app_schema,))
                table_count = cur.fetchone()[0]
                
                # Count functions
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.routines 
                    WHERE routine_schema = %s
                """, (self.config.app_schema,))
                function_count = cur.fetchone()[0]
                
                # Count enums
                cur.execute("""
                    SELECT COUNT(*) FROM pg_type t
                    JOIN pg_namespace n ON t.typnamespace = n.oid
                    WHERE n.nspname = %s AND t.typtype = 'e'
                """, (self.config.app_schema,))
                enum_count = cur.fetchone()[0]
                
                # List tables
                cur.execute("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """, (self.config.app_schema,))
                tables = [row[0] for row in cur.fetchall()]
                
                # List functions
                cur.execute("""
                    SELECT routine_name FROM information_schema.routines 
                    WHERE routine_schema = %s
                    ORDER BY routine_name
                """, (self.config.app_schema,))
                functions = [row[0] for row in cur.fetchall()]
                
                return {
                    "tables": table_count,
                    "functions": function_count,
                    "enums": enum_count,
                    "table_list": tables,
                    "function_list": functions
                }
                
        except Exception as e:
            self.logger.error(f"Verification failed: {e}")
            return {
                "error": str(e)
            }


# Create singleton instance
pydantic_deploy_trigger = PydanticSchemaDeployTrigger()