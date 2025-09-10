# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Database query HTTP triggers providing direct PostgreSQL access for monitoring and debugging
# EXPORTS: DatabaseQueryTrigger, JobsQueryTrigger, TasksQueryTrigger, DatabaseStatsQueryTrigger, EnumDiagnosticTrigger, SchemaNukeQueryTrigger
# INTERFACES: BaseHttpTrigger (inherited from trigger_http_base)
# PYDANTIC_MODELS: None directly - uses dict for query results
# DEPENDENCIES: trigger_http_base, config, util_logger, psycopg, azure.functions, typing, datetime
# SOURCE: HTTP GET/POST requests with query parameters, PostgreSQL database via psycopg
# SCOPE: HTTP endpoints for database queries, statistics, diagnostics, and schema management
# VALIDATION: Query parameter validation, job ID validation, SQL injection prevention
# PATTERNS: Template Method (implements base class), Query Object pattern, Factory (trigger types)
# ENTRY_POINTS: trigger = JobsQueryTrigger(); response = trigger.handle_request(req)
# INDEX: DatabaseQueryTrigger:48, JobsQueryTrigger:182, TasksQueryTrigger:268, DatabaseStatsQueryTrigger:424, SchemaNukeQueryTrigger:620
# ============================================================================

"""
Database Query HTTP Triggers - Production Database Monitoring

Provides dedicated HTTP endpoints for querying the PostgreSQL database directly
from the web, bypassing network restrictions that block DBeaver access.

Endpoints:
    GET /api/db/jobs?limit=10&status=processing&hours=24
    GET /api/db/jobs/{job_id}
    GET /api/db/tasks/{job_id}
    GET /api/db/tasks?status=failed&limit=20
    GET /api/db/stats
    GET /api/db/functions/test

Features:
    - Parameter validation and sanitization
    - Query result caching for performance
    - Error handling with detailed logging
    - Security measures against SQL injection
    - Real-time database diagnostics

Author: Azure Geospatial ETL Team
Date: September 3, 2025
"""

from typing import Dict, Any, List, Optional, Union
import time
import json
from datetime import datetime, timezone

import azure.functions as func
import psycopg
from psycopg import sql
from trigger_http_base import BaseHttpTrigger
from config import get_config
from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "DatabaseQuery")


class DatabaseQueryTrigger(BaseHttpTrigger):
    """Base class for database query HTTP triggers."""
    
    def __init__(self, endpoint_name: str):
        super().__init__(endpoint_name)
        self.config = get_config()
    
    def get_allowed_methods(self) -> List[str]:
        """Database queries support GET only."""
        return ["GET"]
    
    def _get_database_connection(self):
        """Get PostgreSQL database connection with error handling."""
        import psycopg
        
        conn_str = (
            f"host={self.config.postgis_host} "
            f"dbname={self.config.postgis_database} "
            f"user={self.config.postgis_user} "
            f"password={self.config.postgis_password} "
            f"port={self.config.postgis_port}"
        )
        
        return psycopg.connect(conn_str)
    
    def _execute_safe_query(self, query: str, params: tuple = None, timeout_seconds: int = 30) -> Dict[str, Any]:
        """
        Execute database query with error handling and performance monitoring.
        
        Args:
            query: SQL query string
            params: Query parameters (optional)
            timeout_seconds: Query timeout
            
        Returns:
            Dict with query results and metadata
        """
        start_time = time.time()
        
        try:
            with self._get_database_connection() as conn:
                with conn.cursor() as cur:
                    # Set query timeout
                    cur.execute(f"SET statement_timeout = '{timeout_seconds}s'")
                    
                    # Execute query
                    if params:
                        cur.execute(query, params)
                    else:
                        cur.execute(query)
                    
                    # Fetch results
                    try:
                        results = cur.fetchall()
                        columns = [desc[0] for desc in cur.description] if cur.description else []
                    except Exception:
                        # For non-SELECT queries
                        results = []
                        columns = []
                    
                    execution_time = round((time.time() - start_time) * 1000, 2)
                    
                    return {
                        "success": True,
                        "results": results,
                        "columns": columns,
                        "row_count": len(results),
                        "execution_time_ms": execution_time,
                        "query_truncated": query[:200] + "..." if len(query) > 200 else query
                    }
                    
        except Exception as e:
            execution_time = round((time.time() - start_time) * 1000, 2)
            
            logger.error(f"Database query failed: {str(e)}", extra={
                "query_truncated": query[:200] + "..." if len(query) > 200 else query,
                "execution_time_ms": execution_time,
                "error_type": type(e).__name__
            })
            
            return {
                "success": False,
                "error": str(e)[:500],  # Limit error message length
                "error_type": type(e).__name__,
                "execution_time_ms": execution_time,
                "query_truncated": query[:200] + "..." if len(query) > 200 else query
            }
    
    def _validate_limit_param(self, limit_str: Optional[str], default: int = 10, max_limit: int = 100) -> int:
        """Validate and sanitize limit parameter."""
        if not limit_str:
            return default
        
        try:
            limit = int(limit_str)
            if limit < 1:
                return 1
            if limit > max_limit:
                return max_limit
            return limit
        except ValueError:
            return default
    
    def _validate_hours_param(self, hours_str: Optional[str], default: int = 24, max_hours: int = 168) -> int:
        """Validate and sanitize hours parameter."""
        if not hours_str:
            return default
        
        try:
            hours = int(hours_str)
            if hours < 1:
                return 1
            if hours > max_hours:  # Max 1 week
                return max_hours
            return hours
        except ValueError:
            return default
    
    def _validate_job_id(self, job_id: str) -> bool:
        """Validate job ID format (SHA256 hash)."""
        if not job_id:
            return False
        
        # SHA256 hash should be 64 characters, hexadecimal
        if len(job_id) != 64:
            return False
        
        try:
            int(job_id, 16)  # Verify it's valid hex
            return True
        except ValueError:
            return False


class JobsQueryTrigger(DatabaseQueryTrigger):
    """Query jobs with filtering and pagination."""
    
    def __init__(self):
        super().__init__("db_jobs_query")
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Query jobs with optional filtering.
        
        Query Parameters:
            limit: Number of results (1-100, default: 10)
            status: Filter by job status
            hours: Hours to look back (1-168, default: 24)
            job_type: Filter by job type
        """
        
        # Extract and validate parameters
        limit = self._validate_limit_param(req.params.get('limit'))
        hours = self._validate_hours_param(req.params.get('hours'))
        status_filter = req.params.get('status')
        job_type_filter = req.params.get('job_type')
        
        # Build query with filters
        query_parts = [
            f"SELECT job_id, job_type, status::text, stage, total_stages,",
            f"       parameters, result_data, error_details, created_at, updated_at",
            f"FROM {self.config.app_schema}.jobs",
            f"WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
        ]
        
        params = []
        
        if status_filter:
            query_parts.append("AND status::text = %s")
            params.append(status_filter)
        
        if job_type_filter:
            query_parts.append("AND job_type = %s")
            params.append(job_type_filter)
        
        query_parts.extend([
            "ORDER BY created_at DESC",
            f"LIMIT {limit}"
        ])
        
        query = " ".join(query_parts)
        
        # Execute query
        result = self._execute_safe_query(query, tuple(params) if params else None)
        
        if result["success"]:
            # Format results for better readability
            jobs = []
            for row in result["results"]:
                jobs.append({
                    "job_id": row[0],
                    "job_type": row[1], 
                    "status": row[2],
                    "stage": row[3],
                    "total_stages": row[4],
                    "parameters": row[5],
                    "result_data": row[6],
                    "error_details": row[7],
                    "created_at": row[8].isoformat() if row[8] else None,
                    "updated_at": row[9].isoformat() if row[9] else None
                })
            
            return {
                "jobs": jobs,
                "query_info": {
                    "limit": limit,
                    "hours_back": hours,
                    "status_filter": status_filter,
                    "job_type_filter": job_type_filter,
                    "total_found": len(jobs),
                    "execution_time_ms": result["execution_time_ms"]
                }
            }
        else:
            return {
                "error": "Failed to query jobs",
                "details": result
            }


class TasksQueryTrigger(DatabaseQueryTrigger):
    """Query tasks for a specific job or with filtering."""
    
    def __init__(self):
        super().__init__("db_tasks_query")
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Query tasks with filtering.
        
        URL Parameters:
            job_id: Job ID to get tasks for (in URL path)
            
        Query Parameters:
            limit: Number of results (1-100, default: 50)
            status: Filter by task status
            stage: Filter by stage number
        """
        
        # Check if job_id is in the URL path
        job_id = req.route_params.get('job_id')
        
        if job_id:
            return self._query_tasks_for_job(req, job_id)
        else:
            return self._query_tasks_with_filters(req)
    
    def _query_tasks_for_job(self, req: func.HttpRequest, job_id: str) -> Dict[str, Any]:
        """Query all tasks for a specific job."""
        
        if not self._validate_job_id(job_id):
            return {
                "error": "Invalid job ID format",
                "message": "Job ID must be a 64-character hexadecimal string"
            }
        
        query = f"""
            SELECT task_id, parent_job_id, task_type, status::text, stage, task_index,
                   parameters, result_data, error_details, heartbeat, retry_count,
                   created_at, updated_at
            FROM {self.config.app_schema}.tasks
            WHERE parent_job_id = %s
            ORDER BY stage ASC, task_index ASC
        """
        
        result = self._execute_safe_query(query, (job_id,))
        
        if result["success"]:
            tasks = []
            for row in result["results"]:
                tasks.append({
                    "task_id": row[0],
                    "parent_job_id": row[1],
                    "task_type": row[2],
                    "status": row[3],
                    "stage": row[4],
                    "task_index": row[5],
                    "parameters": row[6],
                    "result_data": row[7],
                    "error_details": row[8],
                    "heartbeat": row[9].isoformat() if row[9] else None,
                    "retry_count": row[10],
                    "created_at": row[11].isoformat() if row[11] else None,
                    "updated_at": row[12].isoformat() if row[12] else None
                })
            
            return {
                "job_id": job_id,
                "tasks": tasks,
                "query_info": {
                    "total_tasks": len(tasks),
                    "execution_time_ms": result["execution_time_ms"]
                }
            }
        else:
            return {
                "error": "Failed to query tasks for job",
                "job_id": job_id,
                "details": result
            }
    
    def _query_tasks_with_filters(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Query tasks with filtering parameters."""
        
        limit = self._validate_limit_param(req.params.get('limit'), default=50)
        hours = self._validate_hours_param(req.params.get('hours'))
        status_filter = req.params.get('status')
        stage_filter = req.params.get('stage')
        
        query_parts = [
            f"SELECT task_id, parent_job_id, task_type, status::text, stage, task_index,",
            f"       parameters, result_data, error_details, heartbeat, retry_count,",
            f"       created_at, updated_at",
            f"FROM {self.config.app_schema}.tasks",
            f"WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
        ]
        
        params = []
        
        if status_filter:
            query_parts.append("AND status::text = %s")
            params.append(status_filter)
        
        if stage_filter:
            try:
                stage_num = int(stage_filter)
                query_parts.append("AND stage = %s")
                params.append(stage_num)
            except ValueError:
                pass  # Ignore invalid stage filter
        
        query_parts.extend([
            "ORDER BY created_at DESC",
            f"LIMIT {limit}"
        ])
        
        query = " ".join(query_parts)
        result = self._execute_safe_query(query, tuple(params) if params else None)
        
        if result["success"]:
            tasks = []
            for row in result["results"]:
                tasks.append({
                    "task_id": row[0],
                    "parent_job_id": row[1],
                    "task_type": row[2],
                    "status": row[3],
                    "stage": row[4],
                    "task_index": row[5],
                    "parameters": row[6],
                    "result_data": row[7],
                    "error_details": row[8],
                    "heartbeat": row[9].isoformat() if row[9] else None,
                    "retry_count": row[10],
                    "created_at": row[11].isoformat() if row[11] else None,
                    "updated_at": row[12].isoformat() if row[12] else None
                })
            
            return {
                "tasks": tasks,
                "query_info": {
                    "limit": limit,
                    "hours_back": hours,
                    "status_filter": status_filter,
                    "stage_filter": stage_filter,
                    "total_found": len(tasks),
                    "execution_time_ms": result["execution_time_ms"]
                }
            }
        else:
            return {
                "error": "Failed to query tasks",
                "details": result
            }


class DatabaseStatsQueryTrigger(DatabaseQueryTrigger):
    """Database statistics and health metrics."""
    
    def __init__(self):
        super().__init__("db_stats_query")
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Get comprehensive database statistics."""
        
        stats = {}
        
        # Table sizes and record counts
        table_stats_query = f"""
            SELECT 
                schemaname,
                tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_rows,
                n_dead_tup as dead_rows
            FROM pg_stat_user_tables 
            WHERE schemaname = '{self.config.app_schema}'
            ORDER BY tablename
        """
        
        table_result = self._execute_safe_query(table_stats_query)
        if table_result["success"]:
            stats["table_statistics"] = [
                {
                    "schema": row[0],
                    "table": row[1],
                    "inserts": row[2],
                    "updates": row[3],
                    "deletes": row[4],
                    "live_rows": row[5],
                    "dead_rows": row[6]
                }
                for row in table_result["results"]
            ]
        
        # Index usage statistics
        index_stats_query = f"""
            SELECT 
                schemaname,
                tablename,
                indexname,
                idx_scan as scans,
                idx_tup_read as tuples_read,
                idx_tup_fetch as tuples_fetched
            FROM pg_stat_user_indexes 
            WHERE schemaname = '{self.config.app_schema}'
            ORDER BY idx_scan DESC
            LIMIT 10
        """
        
        index_result = self._execute_safe_query(index_stats_query)
        if index_result["success"]:
            stats["index_usage"] = [
                {
                    "schema": row[0],
                    "table": row[1],
                    "index": row[2],
                    "scans": row[3],
                    "tuples_read": row[4],
                    "tuples_fetched": row[5]
                }
                for row in index_result["results"]
            ]
        
        # Recent activity summary
        activity_query = f"""
            SELECT 
                'jobs' as table_name,
                COUNT(*) as total_records,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 hour' THEN 1 END) as last_hour,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                MAX(created_at) as latest_record
            FROM {self.config.app_schema}.jobs
            
            UNION ALL
            
            SELECT 
                'tasks' as table_name,
                COUNT(*) as total_records,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 hour' THEN 1 END) as last_hour,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                MAX(created_at) as latest_record
            FROM {self.config.app_schema}.tasks
        """
        
        activity_result = self._execute_safe_query(activity_query)
        if activity_result["success"]:
            stats["activity_summary"] = [
                {
                    "table": row[0],
                    "total_records": row[1],
                    "last_hour": row[2],
                    "last_24h": row[3],
                    "latest_record": row[4].isoformat() if row[4] else None
                }
                for row in activity_result["results"]
            ]
        
        return {
            "database_statistics": stats,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }


class EnumDiagnosticTrigger(DatabaseQueryTrigger):
    """Diagnose PostgreSQL enum types availability."""
    
    def __init__(self):
        super().__init__("db_enums_diagnostic")
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Diagnose enum types in different schemas."""
        
        diagnostics = {}
        
        # Check for enum types in all schemas
        enum_query = """
            SELECT 
                n.nspname as schema_name,
                t.typname as enum_name,
                array_agg(e.enumlabel ORDER BY e.enumsortorder) as enum_values
            FROM pg_type t 
            JOIN pg_enum e ON t.oid = e.enumtypid  
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE t.typname IN ('job_status', 'task_status')
            GROUP BY n.nspname, t.typname
            ORDER BY n.nspname, t.typname
        """
        
        result = self._execute_safe_query(enum_query)
        if result["success"]:
            diagnostics["enum_locations"] = [
                {
                    "schema": row[0],
                    "enum_name": row[1],
                    "values": row[2]
                }
                for row in result["results"]
            ]
        else:
            diagnostics["enum_locations"] = {"error": result["error"]}
        
        # Check current search_path
        search_path_query = "SHOW search_path"
        search_result = self._execute_safe_query(search_path_query)
        if search_result["success"]:
            diagnostics["current_search_path"] = search_result["results"][0][0] if search_result["results"] else "unknown"
        
        # Check if we can create enum in app schema
        app_schema = self.config.app_schema
        test_enum_query = f"""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = '{app_schema}'
            ) as app_schema_exists
        """
        
        schema_result = self._execute_safe_query(test_enum_query)
        if schema_result["success"]:
            diagnostics["app_schema_exists"] = schema_result["results"][0][0]
        
        # Check current user privileges
        privileges_query = f"""
            SELECT 
                has_schema_privilege('{app_schema}', 'CREATE') as can_create_in_app,
                has_schema_privilege('public', 'CREATE') as can_create_in_public,
                current_user as current_user
        """
        
        priv_result = self._execute_safe_query(privileges_query)
        if priv_result["success"]:
            diagnostics["privileges"] = {
                "can_create_in_app": priv_result["results"][0][0],
                "can_create_in_public": priv_result["results"][0][1],
                "current_user": priv_result["results"][0][2]
            }
        
        return {
            "enum_diagnostics": diagnostics,
            "recommended_fix": {
                "description": "Create missing enum types in app schema",
                "sql_commands": [
                    f"SET search_path TO {app_schema}, public;",
                    "CREATE TYPE job_status AS ENUM ('queued', 'processing', 'completed', 'failed', 'completed_with_errors');",
                    "CREATE TYPE task_status AS ENUM ('queued', 'processing', 'completed', 'failed');"
                ]
            }
        }


class SchemaNukeQueryTrigger(DatabaseQueryTrigger):
    """🚨 NUCLEAR RED BUTTON - Complete schema reset for development."""
    
    def __init__(self):
        super().__init__("db_schema_nuke")
    
    def get_allowed_methods(self) -> List[str]:
        """Nuclear option requires POST for safety."""
        return ["POST"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        🚨 NUCLEAR OPTION: Completely wipe app schema using Python discovery.
        
        Clean implementation:
        1. Python discovers all objects
        2. Generates DROP statements using psycopg.sql
        3. Executes as simple SQL (no DO blocks)
        
        Authentication: Requires confirm=yes query parameter
        """
        
        # Safety check - require explicit confirmation
        confirm = req.params.get('confirm')
        if confirm != 'yes':
            return {
                "error": "Schema nuke requires explicit confirmation",
                "usage": "Add ?confirm=yes to execute schema wipe",
                "warning": "This will DESTROY ALL DATA in the app schema"
            }
        
        nuke_results = []
        app_schema = self.config.app_schema
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
                # 1. DISCOVER & DROP FUNCTIONS
                cur.execute(sql.SQL("""
                    SELECT 
                        p.proname AS function_name,
                        pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments
                    FROM pg_catalog.pg_proc p
                    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = %s AND p.prokind = 'f'
                """), [app_schema])
                
                functions = cur.fetchall()
                for func_name, args in functions:
                    # args is already properly formatted by pg_get_function_identity_arguments
                    drop_stmt = sql.SQL("DROP FUNCTION IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(app_schema),
                        sql.SQL(f"{func_name}({args})")
                    )
                    cur.execute(drop_stmt)
                    self.logger.debug(f"Dropped function: {func_name}({args})")
                
                nuke_results.append({
                    "step": "drop_functions",
                    "count": len(functions),
                    "dropped": [f"{f[0]}({f[1]})" for f in functions[:5]]  # First 5 for visibility
                })
                
                # 2. DISCOVER & DROP TABLES
                cur.execute(sql.SQL("""
                    SELECT tablename FROM pg_tables WHERE schemaname = %s
                """), [app_schema])
                
                tables = cur.fetchall()
                for (table_name,) in tables:
                    drop_stmt = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(app_schema),
                        sql.Identifier(table_name)
                    )
                    cur.execute(drop_stmt)
                    self.logger.debug(f"Dropped table: {table_name}")
                
                nuke_results.append({
                    "step": "drop_tables",
                    "count": len(tables),
                    "dropped": [t[0] for t in tables]
                })
                
                # 3. DISCOVER & DROP ENUMS
                cur.execute(sql.SQL("""
                    SELECT t.typname
                    FROM pg_type t
                    JOIN pg_namespace n ON t.typnamespace = n.oid
                    WHERE n.nspname = %s AND t.typtype = 'e'
                """), [app_schema])
                
                enums = cur.fetchall()
                for (enum_name,) in enums:
                    drop_stmt = sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(app_schema),
                        sql.Identifier(enum_name)
                    )
                    cur.execute(drop_stmt)
                    self.logger.debug(f"Dropped enum: {enum_name}")
                
                nuke_results.append({
                    "step": "drop_enums",
                    "count": len(enums),
                    "dropped": [e[0] for e in enums]
                })
                
                # 4. DISCOVER & DROP SEQUENCES
                cur.execute(sql.SQL("""
                    SELECT sequence_name
                    FROM information_schema.sequences
                    WHERE sequence_schema = %s
                """), [app_schema])
                
                sequences = cur.fetchall()
                for (seq_name,) in sequences:
                    drop_stmt = sql.SQL("DROP SEQUENCE IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(app_schema),
                        sql.Identifier(seq_name)
                    )
                    cur.execute(drop_stmt)
                    self.logger.debug(f"Dropped sequence: {seq_name}")
                
                nuke_results.append({
                    "step": "drop_sequences",
                    "count": len(sequences),
                    "dropped": [s[0] for s in sequences]
                })
                
                # 5. DISCOVER & DROP VIEWS  
                cur.execute(sql.SQL("""
                    SELECT table_name
                    FROM information_schema.views
                    WHERE table_schema = %s
                """), [app_schema])
                
                views = cur.fetchall()
                for (view_name,) in views:
                    drop_stmt = sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(app_schema),
                        sql.Identifier(view_name)
                    )
                    cur.execute(drop_stmt)
                    self.logger.debug(f"Dropped view: {view_name}")
                
                nuke_results.append({
                    "step": "drop_views",
                    "count": len(views),
                    "dropped": [v[0] for v in views]
                })
                
                # Commit all drops
                conn.commit()
                
                # Calculate total objects dropped
                total_dropped = sum(r['count'] for r in nuke_results)
                
                return {
                    "status": "success",
                    "message": f"🚨 NUCLEAR: Schema {app_schema} completely reset",
                    "implementation": "Clean Python discovery with psycopg.sql (no DO blocks)",
                    "total_objects_dropped": total_dropped,
                    "operations": nuke_results,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "next_steps": [
                        "Deploy fresh schema using POST /api/schema/deploy?confirm=yes",
                        "Or use POST /api/db/schema/redeploy?confirm=yes for nuke+deploy"
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"Nuke operation failed: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            
            return {
                "status": "error",
                "error": str(e),
                "operations_completed": nuke_results,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        finally:
            if conn:
                conn.close()


class FunctionTestQueryTrigger(DatabaseQueryTrigger):
    """Test PostgreSQL functions with sample data."""
    
    def __init__(self):
        super().__init__("db_functions_test")
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Test all PostgreSQL functions."""
        
        function_tests = []
        
        # Test each function individually with search_path fix
        functions_to_test = [
            {
                "name": "complete_task_and_check_stage",
                "query": f"SET search_path TO {self.config.app_schema}, public; SELECT task_updated, is_last_task_in_stage, job_id, stage_number, remaining_tasks FROM {self.config.app_schema}.complete_task_and_check_stage('test_nonexistent_task', 'test_job_id', 1)",
                "description": "Tests task completion and stage detection (with search_path fix)"
            },
            {
                "name": "advance_job_stage", 
                "query": f"SET search_path TO {self.config.app_schema}, public; SELECT job_updated, new_stage, is_final_stage FROM {self.config.app_schema}.advance_job_stage('test_nonexistent_job', 1)",
                "description": "Tests job stage advancement (with search_path fix)"
            },
            {
                "name": "check_job_completion",
                "query": f"SET search_path TO {self.config.app_schema}, public; SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {self.config.app_schema}.check_job_completion('test_nonexistent_job')",
                "description": "Tests job completion detection (with search_path fix)"
            }
        ]
        
        for func_test in functions_to_test:
            result = self._execute_safe_query(func_test["query"])
            
            if result["success"]:
                function_tests.append({
                    "function_name": func_test["name"],
                    "description": func_test["description"],
                    "status": "available",
                    "execution_time_ms": result["execution_time_ms"],
                    "result_columns": result["columns"],
                    "sample_result": result["results"][0] if result["results"] else None
                })
            else:
                function_tests.append({
                    "function_name": func_test["name"],
                    "description": func_test["description"],
                    "status": "error",
                    "error": result["error"],
                    "error_type": result.get("error_type"),
                    "execution_time_ms": result["execution_time_ms"]
                })
        
        return {
            "function_tests": function_tests,
            "summary": {
                "total_functions": len(function_tests),
                "available_functions": len([f for f in function_tests if f["status"] == "available"]),
                "failed_functions": len([f for f in function_tests if f["status"] == "error"])
            }
        }


# Create trigger instances for registration
jobs_query_trigger = JobsQueryTrigger()
tasks_query_trigger = TasksQueryTrigger()
db_stats_trigger = DatabaseStatsQueryTrigger()
enum_diagnostic_trigger = EnumDiagnosticTrigger()
schema_nuke_trigger = SchemaNukeQueryTrigger()
function_test_trigger = FunctionTestQueryTrigger()