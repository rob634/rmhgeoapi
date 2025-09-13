# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Azure Functions entry point orchestrating the geospatial ETL pipeline with HTTP and queue triggers
# EXPORTS: app (Function App), HTTP routes (health, jobs/*, db/*, schema/*), queue processors
# INTERFACES: Azure Functions triggers (HttpTrigger, QueueTrigger), controller classes
# PYDANTIC_MODELS: JobQueueMessage, TaskQueueMessage, JobSubmissionRequest (via triggers)
# DEPENDENCIES: azure.functions, trigger_* modules, controller_*, repository_factory, util_logger
# SOURCE: HTTP requests, Azure Storage Queues (job-processing, task-processing), timer triggers
# SCOPE: Global application entry point managing all Azure Function triggers and orchestration
# VALIDATION: Request validation via trigger classes, queue message validation via Pydantic
# PATTERNS: Front Controller pattern, Message Queue pattern, Dependency Injection (via triggers)
# ENTRY_POINTS: Azure Functions runtime calls app routes; HTTP POST /api/jobs/{job_type}
# INDEX: Routes:144-238, Queue processors:629-825, Health monitoring:144, Job submission:150
# ============================================================================

"""
Azure Functions App for Geospatial ETL Pipeline - REDESIGN ARCHITECTURE.

This module serves as the entry point for the Azure Functions-based geospatial
ETL pipeline. It provides HTTP endpoints for job submission and status checking,
queue-based asynchronous processing, and comprehensive health monitoring.

🏗️ PYDANTIC-BASED ARCHITECTURE (August 29, 2025):
    HTTP API → Controller → Workflow Definition → Tasks → Queue → Service → Storage/Database
             ↓            ↓                   ↓                          ↓
    Job Record      Pydantic Validation   Task Records        STAC Catalog
                    (Strong Typing)       (Service Layer)   (PostgreSQL/PostGIS)

Job → Stage → Task Pattern:
    ✅ CLEAN ARCHITECTURE WITH PYDANTIC WORKFLOW DEFINITIONS
    - BaseController: Uses centralized Pydantic workflow definitions
    - WorkflowDefinition: Type-safe stage sequences with parameter validation
    - Sequential stages with parallel tasks within each stage  
    - "Last task turns out the lights" completion pattern
    - Strong typing discipline with explicit error handling (no fallbacks)
    - Clear separation: Controller (orchestration) vs Task (business logic)

Key Features:
    - Pydantic-based workflow definitions with strong typing discipline
    - Job→Task architecture with controller pattern
    - Idempotent job processing with SHA256-based deduplication
    - Queue-based async processing with poison queue monitoring
    - Managed identity authentication with user delegation SAS
    - Support for files up to 20GB with smart metadata extraction
    - Comprehensive STAC cataloging with PostGIS integration
    - Explicit error handling (no legacy fallbacks or compatibility layers)
    - Enhanced logging with visual indicators for debugging

Endpoints:
    GET  /api/health - System health check with component status
    POST /api/jobs/submit/{job_type} - Submit processing job
    GET  /api/jobs/status/{job_id} - Get job status and results
    GET  /api/monitor/poison - Check poison queue status
    POST /api/monitor/poison - Process poison messages
    POST /api/db/schema/nuke - Drop all schema objects (dev only)
    POST /api/db/schema/redeploy - Nuke and redeploy schema (dev only)

Supported Operations:
    Pydantic Workflow Definition Pattern (Job→Task Architecture):
    - hello_world: Fully implemented with controller routing and workflow validation

Processing Pattern - Pydantic Job→Task Queue Architecture:
    1. HTTP Request Processing:
       - HTTP request triggers workflow definition validation
       - Controller creates job record and stages based on workflow definition
       - Each stage creates parallel tasks with parameter validation
       - Job queued to geospatial-jobs queue for asynchronous processing
       - Explicit error handling with no fallback compatibility
       
    2. Queue-Based Task Execution:
       - geospatial-jobs queue: Job messages from controllers
       - geospatial-tasks queue: Task messages for atomic work units
       - Tasks processed independently with strong typing discipline
       - Last completing task aggregates results into job result_data
       - Poison queues monitor and recover failed messages
       - Each queue has dedicated Azure Function triggers for scalability

Environment Variables:
    STORAGE_ACCOUNT_NAME: Azure storage account name
    AzureWebJobsStorage: Connection string for Functions runtime
    ENABLE_DATABASE_CHECK: Enable PostgreSQL health checks (optional)
    POSTGIS_HOST: PostgreSQL host for STAC catalog
    POSTGIS_DATABASE: PostgreSQL database name
    POSTGIS_USER: PostgreSQL username
    POSTGIS_PASSWORD: PostgreSQL password

Author: Azure Geospatial ETL Team
Version: 2.1.0
Last Updated: January 2025
"""

# ========================================================================
# IMPORTS - Categorized by source for maintainability
# ========================================================================

# Native Python modules
import logging
import json
import traceback
from datetime import datetime, timezone

# Azure SDK modules (3rd party - Microsoft)
import azure.functions as func

# Suppress Azure Identity and Azure SDK authentication/HTTP logging
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._internal").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.storage").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("msal").setLevel(logging.WARNING)  # Microsoft Authentication Library

# ========================================================================
# STARTUP VALIDATION - Fail-fast import validation for critical dependencies
# ========================================================================
# FIXED: util_logger now uses dataclasses instead of Pydantic (stdlib only)

# Application modules (our code) - Utilities
from util_import_validator import validator

# Perform fail-fast startup validation (only in Azure Functions or when explicitly enabled)
validator.ensure_startup_ready()

# ========================================================================
# APPLICATION IMPORTS - Our modules (validated at startup)
# ========================================================================

# Application modules (our code) - Core schemas and logging
from schema_queue import JobQueueMessage, TaskQueueMessage
from util_logger import LoggerFactory
from util_logger import ComponentType
from repository_factory import RepositoryFactory
from repository_postgresql import PostgreSQLRepository
from controller_factories import JobFactory

# Import service modules to trigger handler registration via decorators
# NOTE: This import is required! It registers handlers via decorators on import
import service_hello_world  # Registers hello_world_greeting and hello_world_reply handlers
import service_blob  # Registers blob storage task handlers (analyze_and_orchestrate, extract_metadata, etc.)

# Auto-discover and import all service modules to trigger handler registration
from task_factory import auto_discover_handlers
auto_discover_handlers()

# Application modules (our code) - HTTP Trigger Classes  
from trigger_health import health_check_trigger
from trigger_submit_job import submit_job_trigger
from trigger_get_job_status import get_job_status_trigger
from trigger_poison_monitor import poison_monitor_trigger
from trigger_db_query import (
    jobs_query_trigger, 
    tasks_query_trigger, 
    db_stats_trigger, 
    enum_diagnostic_trigger,
    schema_nuke_trigger,
    function_test_trigger
)
from trigger_schema_pydantic_deploy import pydantic_deploy_trigger

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)





@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint using HTTP trigger base class."""
    return health_check_trigger.handle_request(req)


@app.route(route="jobs/submit/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/status/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)




# Database Query Endpoints - Phase 2 Database Monitoring
@app.route(route="db/jobs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query jobs with filtering: GET /api/db/jobs?limit=10&status=processing&hours=24"""
    return jobs_query_trigger.handle_request(req)


@app.route(route="db/jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS) 
def query_job_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get specific job by ID: GET /api/db/jobs/{job_id}"""
    return jobs_query_trigger.handle_request(req)


@app.route(route="db/tasks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_tasks(req: func.HttpRequest) -> func.HttpResponse:
    """Query tasks with filtering: GET /api/db/tasks?status=failed&limit=20"""
    return tasks_query_trigger.handle_request(req)


@app.route(route="db/tasks/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_tasks_for_job(req: func.HttpRequest) -> func.HttpResponse:
    """Get all tasks for a job: GET /api/db/tasks/{job_id}"""
    return tasks_query_trigger.handle_request(req)


@app.route(route="db/stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def database_stats(req: func.HttpRequest) -> func.HttpResponse:
    """Database statistics and health metrics: GET /api/db/stats"""
    return db_stats_trigger.handle_request(req)


@app.route(route="db/enums/diagnostic", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diagnose_enums(req: func.HttpRequest) -> func.HttpResponse:
    """Diagnose PostgreSQL enum types: GET /api/db/enums/diagnostic"""
    return enum_diagnostic_trigger.handle_request(req)


# 🚨 NUCLEAR RED BUTTON - DEVELOPMENT ONLY
@app.route(route="db/schema/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def nuclear_schema_reset(req: func.HttpRequest) -> func.HttpResponse:
    """🚨 NUCLEAR: Complete schema wipe and rebuild: POST /api/db/schema/nuke?confirm=yes"""
    return schema_nuke_trigger.handle_request(req)


# 🔄 CONSOLIDATED REBUILD - DEVELOPMENT ONLY
@app.route(route="db/schema/redeploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)  
def redeploy_schema(req: func.HttpRequest) -> func.HttpResponse:
    """
    🔄 REDEPLOY: Clean schema reset for development.
    POST /api/db/schema/redeploy?confirm=yes
    
    Single unified endpoint that:
    1. Drops ALL objects using Python discovery (no DO blocks)
    2. Deploys fresh schema from Pydantic models
    3. Uses psycopg.sql composition throughout
    
    Perfect for development deployments and testing.
    """
    # Imports moved to top of file
    
    # Check for confirmation
    confirm = req.params.get('confirm')
    if confirm != 'yes':
        return func.HttpResponse(
            body=json.dumps({
                "error": "Schema redeploy requires explicit confirmation",
                "usage": "POST /api/db/schema/redeploy?confirm=yes",
                "warning": "This will DESTROY ALL DATA and rebuild the schema",
                "implementation": "Clean Python-based discovery with psycopg.sql composition"
            }),
            status_code=400,
            headers={'Content-Type': 'application/json'}
        )
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": "schema_redeploy",
        "steps": []
    }
    
    # Step 1: Nuke the schema (clean Python implementation)
    nuke_response = schema_nuke_trigger.handle_request(req)
    nuke_data = json.loads(nuke_response.get_body())
    results["steps"].append({
        "step": "nuke_schema",
        "status": nuke_data.get("status", "failed"),
        "objects_dropped": nuke_data.get("total_objects_dropped", 0),
        "details": nuke_data.get("operations", [])
    })
    
    # Only proceed with deploy if nuke succeeded
    if nuke_response.status_code == 200:
        # Step 2: Deploy fresh schema
        # Import moved to top of file
        deploy_response = pydantic_deploy_trigger.handle_request(req)
        deploy_data = json.loads(deploy_response.get_body())
        results["steps"].append({
            "step": "deploy_schema",
            "status": deploy_data.get("status", "failed"),
            "objects_created": deploy_data.get("statistics", {}),
            "verification": deploy_data.get("verification", {})
        })
        
        # Overall status
        overall_success = deploy_response.status_code == 200
        results["overall_status"] = "success" if overall_success else "partial_failure"
        results["message"] = "Schema redeployed successfully" if overall_success else "Nuke succeeded but deploy failed"
        
        return func.HttpResponse(
            body=json.dumps(results),
            status_code=200 if overall_success else 500,
            headers={'Content-Type': 'application/json'}
        )
    else:
        results["overall_status"] = "failed"
        results["message"] = "Schema nuke failed - deploy not attempted"
        
        return func.HttpResponse(
            body=json.dumps(results),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )


@app.route(route="db/functions/test", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def test_database_functions(req: func.HttpRequest) -> func.HttpResponse:
    """Test PostgreSQL functions: GET /api/db/functions/test"""
    return function_test_trigger.handle_request(req)


@app.route(route="db/debug/all", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def debug_dump_all(req: func.HttpRequest) -> func.HttpResponse:
    """
    🔍 DEBUG: Dump all jobs and tasks for debugging.
    GET /api/db/debug/all?limit=100
    
    Returns complete data from both jobs and tasks tables for debugging.
    Perfect for when you don't have DBeaver access.
    """
    # Imports moved to top of file
    
    limit = int(req.params.get('limit', '100'))
    
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        
        # Get connection from repository
        # Import moved to top of file
        if isinstance(job_repo, PostgreSQLRepository):
            conn = job_repo._get_connection()
            cursor = conn.cursor()
            
            # Get all jobs
            cursor.execute(f"""
                SELECT 
                    job_id, job_type, status, stage, total_stages,
                    parameters, stage_results, result_data, error_details,
                    created_at, updated_at
                FROM {job_repo.schema_name}.jobs
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            
            jobs = []
            for row in cursor.fetchall():
                jobs.append({
                    "job_id": row[0],
                    "job_type": row[1],
                    "status": row[2],
                    "stage": row[3],
                    "total_stages": row[4],
                    "parameters": row[5],
                    "stage_results": row[6],
                    "result_data": row[7],
                    "error_details": row[8],
                    "created_at": row[9].isoformat() if row[9] else None,
                    "updated_at": row[10].isoformat() if row[10] else None
                })
            
            # Get all tasks
            cursor.execute(f"""
                SELECT 
                    task_id, job_id, task_type, status, stage,
                    parameters, result_data, error_details, retry_count,
                    created_at, updated_at
                FROM {job_repo.schema_name}.tasks
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            
            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    "task_id": row[0],
                    "job_id": row[1],
                    "task_type": row[2],
                    "status": row[3],
                    "stage": row[4],
                    "parameters": row[5],
                    "result_data": row[6],
                    "error_details": row[7],
                    "retry_count": row[8],
                    "created_at": row[9].isoformat() if row[9] else None,
                    "updated_at": row[10].isoformat() if row[10] else None
                })
            
            cursor.close()
            conn.close()
            
            return func.HttpResponse(
                body=json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "jobs_count": len(jobs),
                    "tasks_count": len(tasks),
                    "jobs": jobs,
                    "tasks": tasks
                }, default=str),
                status_code=200,
                headers={'Content-Type': 'application/json'}
            )
            
    except Exception as e:
        return func.HttpResponse(
            body=json.dumps({
                "error": f"Debug dump failed: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )



# ============================================================================
# JOB QUEUE PROCESSING HELPER FUNCTIONS
# ============================================================================

@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="AzureWebJobsStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
    """
    Process job queue messages by delegating to the appropriate controller.
    
    REFACTORED (12 SEP 2025):
    - All orchestration logic moved to BaseController
    - This function only handles message parsing and delegation
    - Controllers handle all job processing logic
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueProcessor.Jobs")
    logger.info("🔄 Job queue trigger activated")
    
    try:
        # Parse message
        message_content = msg.get_body().decode('utf-8')
        job_message = JobQueueMessage.model_validate_json(message_content)
        logger.info(f"📨 Processing job: {job_message.job_id[:16]}... type={job_message.job_type}")
        
        # Get controller and delegate all processing
        controller = JobFactory.create_controller(job_message.job_type)
        result = controller.process_job_queue_message(job_message)
        
        logger.info(f"✅ Job processing complete: {result}")
        
    except ValueError as e:
        logger.error(f"❌ Invalid message or job type: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Job processing failed: {e}")
        logger.debug(f"📍 Error traceback: {traceback.format_exc()}")
        raise


@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-tasks",
        connection="AzureWebJobsStorage")
def process_task_queue(msg: func.QueueMessage) -> None:
    """
    Process task queue messages by delegating to the appropriate controller.
    
    REFACTORED (12 SEP 2025):
    - All orchestration logic moved to BaseController
    - This function only handles message parsing and delegation
    - Controllers handle all task execution and completion logic
    
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueProcessor.Tasks")
    logger.info("🔄 Task queue trigger activated")
    
    try:
        # Parse message
        message_content = msg.get_body().decode('utf-8')
        task_message = TaskQueueMessage.model_validate_json(message_content)
        logger.info(f"📨 Processing task: {task_message.task_id} type={task_message.task_type}")
        
        # Get controller and delegate all processing
        controller = JobFactory.create_controller(task_message.job_type)
        result = controller.process_task_queue_message(task_message)
        
        logger.info(f"✅ Task processing complete: {result}")
        
    except ValueError as e:
        logger.error(f"❌ Invalid message or task type: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Task processing failed: {e}")
        logger.debug(f"📍 Error traceback: {traceback.format_exc()}")
        raise
@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """Poison queue monitoring endpoint using HTTP trigger base class."""
    return poison_monitor_trigger.handle_request(req)
