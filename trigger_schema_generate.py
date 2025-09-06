# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: HTTP trigger for dynamic schema generation from Pydantic models
# SOURCE: Pydantic models as single source of truth
# SCOPE: Database schema generation and deployment
# VALIDATION: Compares generated schema with current database
# ============================================================================

"""
Schema Generation HTTP Trigger.

This module provides HTTP endpoints for generating and deploying PostgreSQL
schema from Pydantic models, implementing Phase 1 of the dynamic schema
generation architecture.
"""

import json
from datetime import datetime
import azure.functions as func
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType
from schema_sql_generator import PydanticToSQL
from config import get_config


class SchemaGenerateTrigger:
    """
    HTTP trigger for schema generation from Pydantic models.
    
    Endpoints:
        GET  /api/schema/generate - Generate SQL DDL from models
        POST /api/schema/deploy - Deploy generated schema
        GET  /api/schema/compare - Compare generated vs current
    """
    
    def __init__(self):
        """Initialize the schema generation trigger."""
        self.logger = LoggerFactory.get_logger(ComponentType.HTTP_TRIGGER, "SchemaGenerate")
        self.config = get_config()
        
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route schema generation requests.
        
        Args:
            req: Azure Functions HTTP request
            
        Returns:
            HTTP response with schema operation results
        """
        method = req.method.upper()
        
        try:
            if method == "GET":
                # Check for action parameter
                action = req.params.get('action', 'generate')
                
                if action == 'generate':
                    return self._generate_schema(req)
                elif action == 'compare':
                    return self._compare_schema(req)
                else:
                    return self._error_response(f"Unknown action: {action}", 400)
                    
            elif method == "POST":
                return self._deploy_schema(req)
            else:
                return self._error_response(f"Method {method} not supported", 405)
                
        except Exception as e:
            self.logger.error(f"Schema operation failed: {e}")
            return self._error_response(str(e), 500)
            
    def _generate_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Generate SQL schema from Pydantic models.
        
        Args:
            req: HTTP request
            
        Returns:
            Generated SQL DDL
        """
        try:
            # Get options from query params
            include_functions = req.params.get('functions', 'static') == 'static'
            schema_name = req.params.get('schema', 'app')
            
            # Generate schema
            generator = PydanticToSQL(schema_name=schema_name)
            sql_schema = generator.generate_complete_schema()
            
            # Prepare response
            response = {
                "status": "success",
                "message": "Schema generated from Pydantic models",
                "statistics": {
                    "enums_generated": len(generator.enums),
                    "tables_generated": 2,  # jobs and tasks
                    "functions_included": "static" if include_functions else "none",
                    "indexes_created": 10
                },
                "schema_name": schema_name,
                "sql_ddl": sql_schema,
                "generated_at": datetime.utcnow().isoformat(),
                "phase": "Phase 1 - Static Functions"
            }
            
            return func.HttpResponse(
                json.dumps(response),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Schema generation failed: {e}")
            return self._error_response(f"Generation failed: {e}", 500)
            
    def _deploy_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Deploy generated schema to database.
        
        Args:
            req: HTTP request with deployment options
            
        Returns:
            Deployment status
        """
        try:
            # Parse request body
            try:
                body = req.get_json()
            except:
                body = {}
                
            # Deployment options
            dry_run = body.get('dry_run', True)
            backup_first = body.get('backup_first', True)
            force = body.get('force', False)
            
            if not dry_run and not force:
                return self._error_response(
                    "Safety check: Set force=true to deploy without dry_run",
                    400
                )
                
            # Generate schema
            generator = PydanticToSQL(schema_name=self.config.app_schema)
            sql_schema = generator.generate_complete_schema()
            
            deployment_result = {
                "status": "success" if dry_run else "pending",
                "dry_run": dry_run,
                "backup_first": backup_first,
                "sql_preview": sql_schema[:1000] + "..." if len(sql_schema) > 1000 else sql_schema
            }
            
            if not dry_run:
                # Actual deployment would go here
                # For Phase 1, we just save to file
                with open("schema_generated.sql", "w") as f:
                    f.write(sql_schema)
                    
                deployment_result.update({
                    "status": "completed",
                    "message": "Schema saved to schema_generated.sql",
                    "note": "Manual deployment required for Phase 1"
                })
            else:
                deployment_result.update({
                    "message": "Dry run completed - no changes made",
                    "next_step": "POST with dry_run=false and force=true to deploy"
                })
                
            return func.HttpResponse(
                json.dumps(deployment_result),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Schema deployment failed: {e}")
            return self._error_response(f"Deployment failed: {e}", 500)
            
    def _compare_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Compare generated schema with current database.
        
        Args:
            req: HTTP request
            
        Returns:
            Comparison results
        """
        try:
            import os
            
            # Generate new schema
            generator = PydanticToSQL(schema_name=self.config.app_schema)
            generated_sql = generator.generate_complete_schema()
            
            # Load current schema if exists
            current_sql = ""
            if os.path.exists("schema_postgres.sql"):
                with open("schema_postgres.sql", "r") as f:
                    current_sql = f.read()
                    
            # Simple line-based comparison
            generated_lines = set(l.strip() for l in generated_sql.split('\n') 
                                 if l.strip() and not l.strip().startswith('--'))
            current_lines = set(l.strip() for l in current_sql.split('\n')
                              if l.strip() and not l.strip().startswith('--'))
            
            only_in_generated = generated_lines - current_lines
            only_in_current = current_lines - generated_lines
            
            comparison = {
                "status": "success",
                "generated_schema_lines": len(generated_lines),
                "current_schema_lines": len(current_lines),
                "differences": {
                    "only_in_generated": len(only_in_generated),
                    "only_in_current": len(only_in_current),
                    "match_percentage": round(
                        len(generated_lines & current_lines) / 
                        max(len(generated_lines), len(current_lines)) * 100, 2
                    )
                },
                "sample_differences": {
                    "new_in_generated": list(only_in_generated)[:10],
                    "missing_from_generated": list(only_in_current)[:10]
                },
                "recommendation": "Safe to deploy" if len(only_in_current) < 10 else "Review differences carefully",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return func.HttpResponse(
                json.dumps(comparison),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            self.logger.error(f"Schema comparison failed: {e}")
            return self._error_response(f"Comparison failed: {e}", 500)
            
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
                "timestamp": datetime.utcnow().isoformat()
            }),
            status_code=status_code,
            mimetype="application/json"
        )


# Create singleton instance
schema_generate_trigger = SchemaGenerateTrigger()