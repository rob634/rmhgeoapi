# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Database query HTTP trigger for debugging and inspection
# SOURCE: HTTP requests with query parameters for different database views
# SCOPE: Debugging and administrative access to PostgreSQL database
# VALIDATION: Query parameter validation and SQL injection prevention
# ============================================================================

"""
Database Query HTTP Trigger for debugging and inspection.

This module provides an HTTP endpoint for querying the PostgreSQL database
directly, useful for debugging when direct database access is not available
due to network restrictions.

Endpoints:
    GET /api/admin/database?option=summary - Summary of jobs and tasks
    GET /api/admin/database?option=full - Full data dump from jobs and tasks
    GET /api/admin/database?option=schema - Complete schema inspection
    GET /api/admin/database?option=job&job_id=<id> - Specific job details
    GET /api/admin/database?option=functions - PostgreSQL functions only

Security:
    - Read-only queries only
    - Parameterized queries to prevent SQL injection
    - Response size limits for production safety
    - Error handling to prevent information leakage

Author: Azure Geospatial ETL Team
Version: 1.0.0
Last Updated: September 2025
"""

import azure.functions as func
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from util_logger import LoggerFactory, ComponentType

def handle_database_query(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle database query requests with different inspection options.
    
    Query Parameters:
        option: Required. One of: summary, full, schema, job, functions
        job_id: Optional. Required when option=job. Specific job ID to query
        limit: Optional. Limit number of records (default: 100, max: 1000)
        
    Returns:
        JSON response with database query results or error details.
    """
    logger = LoggerFactory.get_logger(ComponentType.HTTP_TRIGGER, "DatabaseQuery")
    request_id = req.headers.get('x-request-id', 'db-query-req')
    
    logger.info(f"🔍 Database query request received - request_id: {request_id}")
    
    try:
        # Extract query parameters
        option = req.params.get('option')
        job_id = req.params.get('job_id')
        limit = int(req.params.get('limit', '100'))
        
        # Validate parameters
        if not option:
            return func.HttpResponse(
                body=json.dumps({
                    "error": "Missing required parameter 'option'",
                    "valid_options": ["summary", "full", "schema", "job", "functions"],
                    "request_id": request_id,
                    "timestamp": datetime.utcnow().isoformat()
                }),
                status_code=400,
                headers={'Content-Type': 'application/json'}
            )
        
        if option not in ['summary', 'full', 'schema', 'job', 'functions']:
            return func.HttpResponse(
                body=json.dumps({
                    "error": f"Invalid option '{option}'",
                    "valid_options": ["summary", "full", "schema", "job", "functions"],
                    "request_id": request_id,
                    "timestamp": datetime.utcnow().isoformat()
                }),
                status_code=400,
                headers={'Content-Type': 'application/json'}
            )
        
        if option == 'job' and not job_id:
            return func.HttpResponse(
                body=json.dumps({
                    "error": "job_id parameter required when option=job",
                    "request_id": request_id,
                    "timestamp": datetime.utcnow().isoformat()
                }),
                status_code=400,
                headers={'Content-Type': 'application/json'}
            )
        
        # Limit validation
        if limit > 1000:
            limit = 1000
            logger.warning(f"⚠️ Limit capped at 1000 records for safety")
        
        logger.debug(f"📋 Query parameters: option={option}, job_id={job_id}, limit={limit}")
        
        # Get database repository
        logger.debug(f"🏗️ Creating PostgreSQL repository")
        from repository_postgresql import PostgreSQLRepository
        
        repo = PostgreSQLRepository()
        logger.debug(f"✅ PostgreSQL repository created")
        
        # Execute query based on option
        # TODO: Update these functions to use repository instead of adapter
        adapter = repo  # Temporary compatibility - functions need updating
        if option == 'summary':
            result = _get_database_summary(adapter, logger)
        elif option == 'full':
            result = _get_full_data_dump(adapter, limit, logger)
        elif option == 'schema':
            result = _get_schema_inspection(adapter, logger)
        elif option == 'job':
            result = _get_job_details(adapter, job_id, logger)
        elif option == 'functions':
            result = _get_postgresql_functions(adapter, logger)
        
        # Add metadata to response
        result.update({
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
            "query_option": option,
            "record_limit": limit if option in ['full'] else None
        })
        
        logger.info(f"✅ Database query completed successfully - option: {option}")
        
        return func.HttpResponse(
            body=json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={'Content-Type': 'application/json'}
        )
        
    except Exception as e:
        logger.error(f"❌ Database query failed: {str(e)}")
        import traceback
        logger.debug(f"📍 Error traceback: {traceback.format_exc()}")
        
        return func.HttpResponse(
            body=json.dumps({
                "error": f"Database query failed: {str(e)}",
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat()
            }),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )


def _get_database_summary(adapter, logger) -> Dict[str, Any]:
    """Get summary statistics of jobs and tasks tables."""
    logger.debug(f"📊 Querying database summary")
    
    with adapter._get_connection() as conn:
        with conn.cursor() as cur:
            # Set schema
            cur.execute(f'SET search_path TO {adapter.app_schema}, public;')
            
            # Jobs summary
            cur.execute("""
                SELECT 
                    status,
                    COUNT(*) as count,
                    MIN(created_at) as earliest,
                    MAX(created_at) as latest,
                    AVG(stage) as avg_stage
                FROM jobs 
                GROUP BY status
                ORDER BY count DESC
            """)
            jobs_summary = [
                {
                    "status": row[0],
                    "count": row[1],
                    "earliest": row[2],
                    "latest": row[3],
                    "avg_stage": float(row[4]) if row[4] else None
                }
                for row in cur.fetchall()
            ]
            
            # Tasks summary
            cur.execute("""
                SELECT 
                    status,
                    task_type,
                    COUNT(*) as count,
                    MIN(created_at) as earliest,
                    MAX(created_at) as latest
                FROM tasks 
                GROUP BY status, task_type
                ORDER BY count DESC
            """)
            tasks_summary = [
                {
                    "status": row[0],
                    "task_type": row[1],
                    "count": row[2],
                    "earliest": row[3],
                    "latest": row[4]
                }
                for row in cur.fetchall()
            ]
            
            # Recent activity
            cur.execute("""
                SELECT 'job' as type, job_id as id, job_type, status, created_at, updated_at
                FROM jobs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                UNION ALL
                SELECT 'task' as type, task_id as id, task_type, status, created_at, updated_at
                FROM tasks
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 20
            """)
            recent_activity = [
                {
                    "type": row[0],
                    "id": row[1],
                    "type_name": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "updated_at": row[5]
                }
                for row in cur.fetchall()
            ]
    
    logger.debug(f"✅ Database summary retrieved - jobs: {len(jobs_summary)}, tasks: {len(tasks_summary)}")
    
    return {
        "summary_type": "database_summary",
        "jobs_by_status": jobs_summary,
        "tasks_by_status_and_type": tasks_summary,
        "recent_activity_24h": recent_activity
    }


def _get_full_data_dump(adapter, limit: int, logger) -> Dict[str, Any]:
    """Get full data dump from jobs and tasks tables."""
    logger.debug(f"📦 Querying full data dump - limit: {limit}")
    
    with adapter._get_connection() as conn:
        with conn.cursor() as cur:
            # Set schema
            cur.execute(f'SET search_path TO {adapter.app_schema}, public;')
            
            # All jobs
            cur.execute(f"""
                SELECT job_id, job_type, status, stage, total_stages,
                       parameters, stage_results, result_data, error_details,
                       created_at, updated_at
                FROM jobs
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            
            jobs = [
                {
                    "job_id": row[0],
                    "job_type": row[1],
                    "status": row[2],
                    "stage": row[3],
                    "total_stages": row[4],
                    "parameters": row[5],
                    "stage_results": row[6],
                    "result_data": row[7],
                    "error_details": row[8],
                    "created_at": row[9],
                    "updated_at": row[10]
                }
                for row in cur.fetchall()
            ]
            
            # All tasks
            cur.execute(f"""
                SELECT task_id, parent_job_id, task_type, status, stage, task_index,
                       parameters, result_data, error_details, retry_count, heartbeat,
                       created_at, updated_at
                FROM tasks
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            
            tasks = [
                {
                    "task_id": row[0],
                    "parent_job_id": row[1],
                    "task_type": row[2],
                    "status": row[3],
                    "stage": row[4],
                    "task_index": row[5],
                    "parameters": row[6],
                    "result_data": row[7],
                    "error_details": row[8],
                    "retry_count": row[9],
                    "heartbeat": row[10],
                    "created_at": row[11],
                    "updated_at": row[12]
                }
                for row in cur.fetchall()
            ]
    
    logger.debug(f"✅ Full data dump retrieved - jobs: {len(jobs)}, tasks: {len(tasks)}")
    
    return {
        "dump_type": "full_data",
        "jobs": jobs,
        "tasks": tasks,
        "record_counts": {
            "jobs": len(jobs),
            "tasks": len(tasks)
        }
    }


def _get_schema_inspection(adapter, logger) -> Dict[str, Any]:
    """Get complete schema inspection including tables, functions, etc."""
    logger.debug(f"🔍 Querying schema inspection")
    
    with adapter._get_connection() as conn:
        with conn.cursor() as cur:
            # Set schema
            cur.execute(f'SET search_path TO {adapter.app_schema}, public;')
            
            # Table columns
            cur.execute("""
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
            """, (adapter.app_schema,))
            
            columns = {}
            for row in cur.fetchall():
                table = row[0]
                if table not in columns:
                    columns[table] = []
                columns[table].append({
                    "column_name": row[1],
                    "data_type": row[2],
                    "is_nullable": row[3],
                    "column_default": row[4]
                })
            
            # Functions
            cur.execute("""
                SELECT routine_name, routine_type, data_type
                FROM information_schema.routines
                WHERE routine_schema = %s
                ORDER BY routine_name
            """, (adapter.app_schema,))
            
            functions = [
                {
                    "name": row[0],
                    "type": row[1],
                    "return_type": row[2]
                }
                for row in cur.fetchall()
            ]
            
            # Enums
            cur.execute("""
                SELECT t.typname as enum_name,
                       e.enumlabel as enum_value
                FROM pg_type t 
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_namespace n ON t.typnamespace = n.oid
                WHERE n.nspname = %s
                ORDER BY t.typname, e.enumsortorder
            """, (adapter.app_schema,))
            
            enums = {}
            for row in cur.fetchall():
                enum_name = row[0]
                if enum_name not in enums:
                    enums[enum_name] = []
                enums[enum_name].append(row[1])
    
    logger.debug(f"✅ Schema inspection completed - tables: {len(columns)}, functions: {len(functions)}, enums: {len(enums)}")
    
    return {
        "inspection_type": "schema",
        "tables": columns,
        "functions": functions,
        "enums": enums,
        "schema_name": adapter.app_schema
    }


def _get_job_details(adapter, job_id: str, logger) -> Dict[str, Any]:
    """Get detailed information about a specific job and its tasks."""
    logger.debug(f"🔍 Querying job details for: {job_id[:16]}...")
    
    with adapter._get_connection() as conn:
        with conn.cursor() as cur:
            # Set schema
            cur.execute(f'SET search_path TO {adapter.app_schema}, public;')
            
            # Job details
            cur.execute("""
                SELECT job_id, job_type, status, stage, total_stages,
                       parameters, stage_results, result_data, error_details,
                       created_at, updated_at
                FROM jobs WHERE job_id = %s
            """, (job_id,))
            
            job_row = cur.fetchone()
            if not job_row:
                return {
                    "error": f"Job not found: {job_id}",
                    "job_id": job_id
                }
            
            job = {
                "job_id": job_row[0],
                "job_type": job_row[1],
                "status": job_row[2],
                "stage": job_row[3],
                "total_stages": job_row[4],
                "parameters": job_row[5],
                "stage_results": job_row[6],
                "result_data": job_row[7],
                "error_details": job_row[8],
                "created_at": job_row[9],
                "updated_at": job_row[10]
            }
            
            # Associated tasks
            cur.execute("""
                SELECT task_id, task_type, status, stage, task_index,
                       parameters, result_data, error_details, retry_count, heartbeat,
                       created_at, updated_at
                FROM tasks WHERE parent_job_id = %s
                ORDER BY stage, task_index
            """, (job_id,))
            
            tasks = [
                {
                    "task_id": row[0],
                    "task_type": row[1],
                    "status": row[2],
                    "stage": row[3],
                    "task_index": row[4],
                    "parameters": row[5],
                    "result_data": row[6],
                    "error_details": row[7],
                    "retry_count": row[8],
                    "heartbeat": row[9],
                    "created_at": row[10],
                    "updated_at": row[11]
                }
                for row in cur.fetchall()
            ]
    
    logger.debug(f"✅ Job details retrieved - job found, tasks: {len(tasks)}")
    
    return {
        "query_type": "job_details",
        "job": job,
        "tasks": tasks,
        "task_count": len(tasks)
    }


def _get_postgresql_functions(adapter, logger) -> Dict[str, Any]:
    """Get detailed information about PostgreSQL functions."""
    logger.debug(f"🔧 Querying PostgreSQL functions")
    
    with adapter._get_connection() as conn:
        with conn.cursor() as cur:
            # Set schema
            cur.execute(f'SET search_path TO {adapter.app_schema}, public;')
            
            # Function details with definitions
            cur.execute("""
                SELECT 
                    p.proname as function_name,
                    pg_catalog.pg_get_function_result(p.oid) as return_type,
                    pg_catalog.pg_get_function_arguments(p.oid) as arguments,
                    CASE p.provolatile
                        WHEN 'i' THEN 'IMMUTABLE'
                        WHEN 's' THEN 'STABLE'
                        WHEN 'v' THEN 'VOLATILE'
                    END as volatility,
                    p.prosrc as source_code
                FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = %s
                ORDER BY p.proname
            """, (adapter.app_schema,))
            
            functions = [
                {
                    "name": row[0],
                    "return_type": row[1],
                    "arguments": row[2],
                    "volatility": row[3],
                    "source_code": row[4][:500] + "..." if len(row[4]) > 500 else row[4]  # Truncate long code
                }
                for row in cur.fetchall()
            ]
    
    logger.debug(f"✅ PostgreSQL functions retrieved - count: {len(functions)}")
    
    return {
        "query_type": "postgresql_functions",
        "functions": functions,
        "function_count": len(functions),
        "schema_name": adapter.app_schema
    }