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
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

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
from schema_base import JobStatus, TaskStatus, TaskResult, TaskRecord
from schema_queue import JobQueueMessage, TaskQueueMessage
from util_logger import LoggerFactory
from util_logger import ComponentType
from config import get_config
from repository_factory import RepositoryFactory
from repository_postgresql import PostgreSQLRepository
from controller_factories import JobFactory
from service_factories import TaskHandlerFactory, TaskRegistry

# Import service modules to trigger handler registration via decorators
import service_hello_world  # Registers hello_world_greeting and hello_world_reply handlers

# Auto-discover and import all service modules to trigger handler registration
from service_factories import auto_discover_handlers
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

def _validate_and_parse_queue_message(msg: func.QueueMessage, logger) -> 'JobQueueMessage':
    """
    Phase 1 Helper: Validate and parse queue message.
    
    Handles message decoding and schema validation with clear error reporting.
    Fails fast if message is invalid to prevent unnecessary processing.
    
    Args:
        msg: Azure Functions queue message
        logger: Configured logger instance
        
    Returns:
        JobQueueMessage: Validated Pydantic message object
        
    Raises:
        ValueError: If message cannot be decoded or validated
    """
    logger.debug(f"🔍 Decoding queue message body")
    try:
        message_content = msg.get_body().decode('utf-8')
        logger.debug(f"📋 Decoded message content: {message_content}")
    except Exception as decode_error:
        logger.error(f"❌ Failed to decode message body: {decode_error}")
        raise ValueError(f"Message decode failed: {decode_error}")
    
    logger.debug(f"🔧 Validating message with JobQueueMessage schema")
    try:
        # Import already at top of file
        job_message = JobQueueMessage.model_validate_json(message_content)
        logger.debug(f"✅ Message validation successful: {job_message}")
        return job_message
    except Exception as validation_error:
        logger.error(f"❌ Message validation failed: {validation_error}")
        logger.debug(f"📋 Invalid message content: {message_content}")
        raise ValueError(f"Message validation failed: {validation_error}")


def _load_job_record_safely(job_message: 'JobQueueMessage', logger) -> tuple:
    """
    Phase 1 Helper: Load job record and create repositories.
    
    Handles repository creation and job record loading with defensive programming.
    Returns both repositories and job record for use in main processing.
    
    Args:
        job_message: Validated job queue message
        logger: Configured logger instance
        
    Returns:
        tuple: (repositories_dict, job_record)
        
    Raises:
        RuntimeError: If repositories cannot be created or job not found
    """
    logger.debug(f"🏗️ Creating repositories for job processing")
    # Import moved to top of file
    
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
        completion_detector = repos['completion_detector']
        logger.debug(f"✅ Repositories created with PostgreSQL backend")
    except Exception as repo_error:
        logger.error(f"❌ Failed to create repositories: {repo_error}")
        raise RuntimeError(f"Repository creation failed: {repo_error}")
    
    logger.debug(f"🔍 Loading job record for: {job_message.job_id}")
    try:
        job_record = job_repo.get_job(job_message.job_id)
        logger.debug(f"📋 Job record retrieval result: {job_record}")
    except Exception as load_error:
        logger.error(f"❌ Failed to load job record: {load_error}")
        raise RuntimeError(f"Job record load failed: {load_error}")
    
    if not job_record:
        logger.error(f"❌ Job record not found: {job_message.job_id}")
        raise ValueError(f"Job record not found: {job_message.job_id}")
    
    logger.debug(f"✅ Job record loaded successfully: status={job_record.status}")
    return repos, job_record


def _verify_task_creation_success(job_id: str, task_repo, logger) -> list:
    """
    Phase 2 Helper: Verify tasks were actually created in database.
    
    Queries the database to confirm tasks exist for this job.
    This prevents jobs from being marked as PROCESSING when no tasks were created.
    
    Args:
        job_id: Job identifier to check for tasks
        task_repo: Task repository instance
        logger: Configured logger instance
        
    Returns:
        list: Created task records (empty list if no tasks found)
    """
    logger.debug(f"🔍 Verifying task creation for job: {job_id}")
    try:
        created_tasks = task_repo.list_tasks_for_job(job_id)
        task_count = len(created_tasks) if created_tasks else 0
        logger.debug(f"📊 Task verification result: {task_count} tasks found")
        return created_tasks or []
    except Exception as verification_error:
        logger.error(f"❌ Failed to verify task creation: {verification_error}")
        # Return empty list to indicate no tasks found
        return []


def _mark_job_failed_safely(job_id: str, error: Exception, job_repo, logger) -> None:
    """
    Phase 3 Helper: Safely mark job as failed with error details.
    
    Single point of failure handling with defensive programming.
    Ensures job status is updated even if error details cannot be formatted.
    
    Args:
        job_id: Job identifier to mark as failed
        error: Original exception that caused the failure
        job_repo: Job repository instance (may be None)
        logger: Configured logger instance
    """
    if not job_repo:
        logger.error(f"❌ Cannot mark job as failed - no job repository available")
        return
    
    logger.debug(f"🔧 Marking job as failed: {job_id}")
    try:
        # Imports moved to top of file
        
        error_details = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": "job_queue_processing"
        }
        
        # Try to get more detailed error information
        try:
            error_details["traceback"] = traceback.format_exc()
        except Exception:
            # Don't fail the failure handling due to traceback issues
            pass
        
        # Import already at top of file
        job_repo.update_job_status_with_validation(
            job_id, 
            JobStatus.FAILED, 
            additional_updates={"error_details": error_details}
        )
        logger.debug(f"✅ Job marked as failed successfully")
        logger.info(f"❌ Job {job_id[:16]}... marked as FAILED")
        
    except Exception as failure_error:
        logger.error(f"❌ CRITICAL: Failed to mark job as failed: {failure_error}")
        logger.error(f"❌ Original error: {error}")
        # This is critical but we don't want to raise here as it would mask the original error


@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="AzureWebJobsStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
    """
    Process jobs from the geospatial-jobs queue using restructured exception handling.
    
    IMPROVED ARCHITECTURE (10 September 2025):
    - Clean phase-based processing with helper functions
    - Job status updated to PROCESSING only AFTER successful task creation
    - Single point of failure handling with defensive programming
    - Task creation verification to prevent stuck PROCESSING jobs
    
    Processing Flow:
        Phase 1: Message validation and job loading (fail fast)
        Phase 2: Task creation with immediate status updates
        Phase 3: Success/failure handling based on verified results
        
    Critical Improvements:
        - No premature job status updates
        - Tasks verified in database before status change
        - Immediate FAILED status on any task creation failure
        - Defensive error handling with resource cleanup
    """
    # Initialize logger
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueProcessor.Jobs")
    logger.info("🔄 Job queue trigger activated - using restructured processing")
    logger.debug(f"📨 Raw queue message received: {msg}")
    
    # Initialize variables for cleanup
    job_message = None
    repos = None
    
    try:
        # ================================================================
        # PHASE 1: EARLY VALIDATION AND SETUP (fail fast)
        # ================================================================
        
        # Parse and validate message
        job_message = _validate_and_parse_queue_message(msg, logger)
        logger.info(f"📨 Processing job: {job_message.job_id[:16]}... type={job_message.job_type}")
        
        # Load job record and create repositories
        repos, job_record = _load_job_record_safely(job_message, logger)
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
        
        # ================================================================
        # PHASE 2: TASK CREATION (critical section)
        # ================================================================
        
        # Import and create controller
        # Import moved to top of file
        logger.debug(f"🎯 Creating controller for job type: {job_message.job_type}")
        
        try:
            controller = JobFactory.create_controller(job_message.job_type)
            logger.debug(f"✅ Controller created successfully")
        except Exception as controller_error:
            logger.error(f"❌ Controller creation failed: {controller_error}")
            raise RuntimeError(f"Controller creation failed: {controller_error}")
        
        # Execute task creation through controller
        logger.debug(f"🚀 Starting task creation for stage {job_message.stage}")
        
        try:
            # Process job stage (creates tasks)
            stage_results = controller.process_job_stage(
                job_record=job_record,
                stage=job_message.stage,
                parameters=job_message.parameters,
                stage_results=job_message.stage_results
            )
            logger.debug(f"🎯 Controller returned stage results: {stage_results}")
            
        except Exception as task_creation_error:
            logger.error(f"❌ Task creation failed: {task_creation_error}")
            # Immediate failure handling - mark job as failed
            _mark_job_failed_safely(job_message.job_id, task_creation_error, job_repo, logger)
            raise RuntimeError(f"Task creation failed: {task_creation_error}")
        
        # ================================================================
        # PHASE 3: VERIFICATION AND STATUS UPDATE
        # ================================================================
        
        # Verify tasks were actually created in database
        created_tasks = _verify_task_creation_success(job_message.job_id, task_repo, logger)
        
        if created_tasks:
            # SUCCESS: Tasks verified in database, safe to update status
            logger.debug(f"✅ Task creation verified: {len(created_tasks)} tasks found")
            
            try:
                # Import already at top of file
                job_repo.update_job_status_with_validation(job_message.job_id, JobStatus.PROCESSING)
                logger.info(f"✅ Job {job_message.job_id[:16]}... advanced to PROCESSING with {len(created_tasks)} tasks")
                
            except Exception as status_error:
                logger.error(f"❌ Status update failed after successful task creation: {status_error}")
                logger.warning(f"⚠️ Tasks created successfully but status update failed - job may need manual correction")
                # Don't raise - tasks were created successfully
                
        else:
            # FAILURE: No tasks found despite controller success
            error_msg = "Task creation reported success but no tasks found in database"
            logger.error(f"❌ {error_msg}")
            verification_error = RuntimeError(error_msg)
            _mark_job_failed_safely(job_message.job_id, verification_error, job_repo, logger)
            raise verification_error
            
    except Exception as processing_error:
        # ================================================================
        # SINGLE POINT OF FAILURE HANDLING
        # ================================================================
        
        logger.error(f"❌ Job processing failed: {processing_error}")
        
        # Log job details if available
        if job_message:
            logger.error(f"📋 Job details - ID: {job_message.job_id}, Type: {job_message.job_type}, Stage: {job_message.stage}")
        
        # Additional error context
        # Import moved to top of file
        logger.debug(f"📍 Error traceback: {traceback.format_exc()}")
        
        # Attempt to mark job as failed if we have the necessary resources
        if job_message and repos and repos.get('job_repo'):
            _mark_job_failed_safely(job_message.job_id, processing_error, repos['job_repo'], logger)
        else:
            logger.error(f"❌ CRITICAL: Cannot mark job as failed - insufficient resources")
        
        # Re-raise for Azure Functions runtime
        logger.debug(f"🔄 Re-raising exception for Azure Functions runtime")
        raise


@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-tasks",
        connection="AzureWebJobsStorage")
def process_task_queue(msg: func.QueueMessage) -> None:
    """
    Process individual tasks from the geospatial-tasks queue using Pydantic Job→Task architecture.
    
    Modern Pydantic-based task processing with distributed job completion detection.
    Tasks are atomic work units created by controllers with strong typing discipline.
    
    Core Processing Flow:
        1. Decode and validate task message using TaskQueueMessage schema
        2. Load task record from storage with schema validation
        3. Update task status to 'processing'
        4. Route to appropriate task handler based on task_type
        5. Execute task with validated parameters
        6. Update task status to 'completed'/'failed'
        7. CRITICAL: Check if parent job is complete (distributed detection)
        8. If all tasks done, aggregate results and complete job
    
    Distributed Job Completion ("Last Task Wins"):
        Every task completion triggers completion detection:
        - Queries ALL tasks for the parent job
        - Counts completed vs total tasks
        - If all done, aggregates task results into job result_data
        - Only the LAST completing task performs job completion
    
    Args:
        msg: Azure Functions queue message containing task data.
            
    Task Message Format (Pydantic Job→Task Architecture):
        {
            "task_id": "job_id_stage1_task0",
            "parent_job_id": "SHA256_hash",
            "task_type": "hello_world",
            "stage": 1,
            "task_index": 0,
            "parameters": {
                "dataset_id": "container",
                "message": "Hello World!"
            },
            "retry_count": 0
        }
        
    Supported Task Types:
        - hello_world: Fully implemented with result aggregation
        - catalog_file: File cataloging tasks (requires implementation)
        - process_tile: Raster tile processing (requires implementation)
        
    Error Handling:
        - Schema validation failures: Task marked failed
        - Task handler errors: Task marked failed with error details
        - After 5 attempts: Message moved to poison queue
        - Failed tasks counted in parent job statistics
    """
    # Initialize task queue-specific logger
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueProcessor.Tasks")
    
    logger.info("🔄 Task queue trigger activated - processing with Pydantic architecture")
    logger.debug(f"📨 Raw task queue message received: {msg}")
    
    # Import controller factory once at the beginning
    # Import moved to top of file
    
    # ========================================================================
    # PHASE 1: MESSAGE VALIDATION (No task context yet)
    # ========================================================================
    try:
        message_content = msg.get_body().decode('utf-8')
        task_message = TaskQueueMessage.model_validate_json(message_content)
        logger.info(f"✅ Task message validated: {task_message.task_id}")
    except Exception as validation_error:
        # Can't mark task as failed - we don't have a valid task_id
        logger.error(f"❌ Invalid queue message: {validation_error}")
        raise  # Let Azure Functions handle the retry/poison queue logic
    
    # Log task details for context
    logger.info(f"📋 Task: {task_message.task_id} for job {task_message.parent_job_id[:16]}...")
    
    # ========================================================================
    # PHASE 2: REPOSITORY SETUP (Infrastructure)
    # ========================================================================
    try:
        # Import moved to top of file
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
        completion_detector = repos['completion_detector']
        logger.debug("✅ Repositories created")
    except Exception as repo_error:
        # Infrastructure failure - can't even access database to mark task failed
        logger.error(f"❌ Repository creation failed: {repo_error}")
        raise
    
    # ========================================================================
    # PHASE 3: TASK LOADING & VALIDATION
    # ========================================================================
    try:
        task_record = task_repo.get_task(task_message.task_id)
        if not task_record:
            raise ValueError(f"Task record not found: {task_message.task_id}")
        
        # Update task status to processing
        # With maxDequeueCount=1, tasks should never be retried
        task_repo.update_task_status_with_validation(task_message.task_id, TaskStatus.PROCESSING)
        logger.info(f"📋 Processing task: {task_message.task_id}")
        
    except Exception as load_error:
        logger.error(f"❌ Task loading failed: {load_error}")
        try:
            # Try to mark task as failed if possible
            logger.debug(f"🔧 Attempting to mark task as failed: {task_message.task_id}")
            task_repo.update_task_status_with_validation(
                task_message.task_id, 
                TaskStatus.FAILED,
                additional_updates={'error_details': f"Failed to load task: {load_error}"}
            )
        except:
            logger.error(f"❌ Failed to mark task as failed: {task_message.task_id}")
            pass  # Best effort - database might be unreachable
        raise
    
    # ========================================================================
    # PHASE 4: TASK EXECUTION (Business Logic)
    # ========================================================================
    task_result = None
    
    try:
        # Route to task handler based on task type

        # Custom exception for internal task registration errors
        class TaskNotRegisteredException(Exception):
            """Internal error when task type is not registered in the system."""
            pass
        
        # Use TaskHandlerFactory with Robert's implicit lineage pattern
        # The factory automatically injects predecessor data access for multi-stage workflows
        # Import moved to top of file
        
        # Auto-discover and register task handlers
        # Task handlers are registered via decorators at import time
        
        # Verify handler is registered
        registry = TaskRegistry.instance()
        if not registry.is_registered(task_message.task_type):
            available_types = registry.list_task_types()
            raise TaskNotRegisteredException(
                f"INTERNAL ERROR: No handler registered for task_type '{task_message.task_type}'. "
                f"This is a system configuration error. "
                f"Available types: {', '.join(available_types) if available_types else 'none'}. "
                f"Required: Register handler using @TaskRegistry.register(task_type) decorator"
            )
        
        # Get handler with lineage context
        # This implements Robert's pattern: tasks in stage N can access stage N-1 data
        handler = TaskHandlerFactory.get_handler(task_message, task_repo)
        
        # Execute task - handler returns TaskResult
        task_result = handler(task_message.parameters)
        
        if not task_result.success:
            raise RuntimeError(f"Task execution failed: {task_result.error_details}")
        
        logger.info(f"✅ Task executed via TaskHandlerFactory with lineage support")
            
    except Exception as exec_error:
        logger.error(f"❌ Task execution failed: {exec_error}")
        logger.error(f"Task details - ID: {task_message.task_id}, Type: {task_message.task_type}, Stage: {task_message.stage}")
        
        # Create a failed task result for proper error tracking
        # Import moved to top of file
        task_result = TaskResult(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            stage_number=task_message.stage,
            task_type=task_message.task_type,
            status=TaskStatus.FAILED,  # This will make success property return False
            result_data={},  # Empty result for failures - FIXED field name
            error_details=f"{type(exec_error).__name__}: {str(exec_error)}",  # FIXED field name
            execution_time_seconds=0.0
        )
        
        # Mark task as failed in database
        try:
            # Import moved to top of file
            task_repo.update_task_status_with_validation(
                task_message.task_id,
                TaskStatus.FAILED,
                additional_updates={
                    'error_details': f"{type(exec_error).__name__}: {str(exec_error)}\n{traceback.format_exc()}"
                }
            )
        except Exception as update_error:
            logger.error(f"❌ Failed to update task status: {update_error}")
        
        # Don't re-raise - continue to completion phase with error details
    
    # ========================================================================
    # PHASE 5: ATOMIC COMPLETION & STAGE DETECTION
    # ========================================================================

    if hasattr(completion_detector,'complete_task_and_check_stage'):
        logger.debug(f"Proceeding to atomic completion complete_task_and_check_stage")
    else:
        logger.error(f"Completion detector object is broken: lacks complete_task_and_check_stage method")
        raise RuntimeError("Completion detector is not functional")

    try:
        # Atomic "last task turns out lights" pattern
        # PostgreSQL function now properly validates job_id and stage match the task
        
        if task_result and hasattr(task_result, 'success') and task_result.success:
            # Task succeeded - pass result data
            logger.debug(f"✅ Task {task_message.task_id} succeeded, marking as completed")
            stage_completion_result = completion_detector.complete_task_and_check_stage(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                stage=task_message.stage,
                result_data=task_result.result_data if task_result.result_data else {},
                error_details=None  # Explicit None for successful tasks
            )
        else:
            # Task failed - pass error details as separate parameter
            error_msg = getattr(task_result, 'error_details', 'No result returned from task execution') if task_result else 'Task execution failed'
            logger.warning(f"⚠️ Task {task_message.task_id} failed with error: {error_msg}")
            stage_completion_result = completion_detector.complete_task_and_check_stage(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                stage=task_message.stage,
                result_data={},  # Empty result for failures
                error_details=error_msg  # Pass error as separate parameter
            )
        
        logger.info(f"✅ Task {task_message.task_id} marked as completed")
        
        # Check if this was the last task in the stage
        stage_complete = stage_completion_result.stage_complete
        if stage_complete:
            logger.info(f"🎯 Stage {task_message.stage} is now complete - last task turned out the lights")
        else:
            remaining = stage_completion_result.remaining_tasks
            logger.info(f"⏳ Stage {task_message.stage} has {remaining} tasks remaining")
        
    except Exception as completion_error:
        logger.error(f"❌ Failed to mark task complete: {completion_error}")
        # This is critical - task executed but not marked complete
        # Try to update task status directly as fallback
        try:
            task_repo.update_task_status_with_validation(
                task_message.task_id,
                TaskStatus.FAILED,
                additional_updates={'error_details': f'Completion detection failed: {str(completion_error)}'}
            )
        except:
            pass  # Best effort fallback
        raise
    
    # ========================================================================
    # PHASE 6: STAGE ADVANCEMENT (CRITICAL - Job stuck without this)
    # ========================================================================
    if stage_complete:
        try:
            logger.info(f"🎯 Stage {task_message.stage} completed")
            
            # Get job status to determine next action
            job_record = job_repo.get_job(task_message.parent_job_id)
            if not job_record:
                raise ValueError(f"Job not found: {task_message.parent_job_id}")
            
            if job_record.stage >= job_record.total_stages:
                # Final stage - complete the job
                logger.info(f"🏁 Final stage - completing job")
                
                try:
                    # Get controller for job completion
                    controller = JobFactory.create_controller(job_record.job_type)
                    
                    # Get all task results from completed job
                    final_job_check = completion_detector.check_job_completion(task_message.parent_job_id)
                    
                    if not final_job_check.job_complete:
                        raise RuntimeError(f"Job completion check failed - job not ready for completion: {task_message.parent_job_id}")
                    
                    # Convert JSONB task results to TaskResult objects
                    # Import moved to top of file
                    task_result_objects = []
                    for task_data in final_job_check.task_results or []:
                        # task_data is a dict from PostgreSQL JSONB
                        if isinstance(task_data, dict):
                            # Create TaskResult from the JSONB data
                            task_result = TaskResult(
                                task_id=task_data.get('task_id', ''),
                                job_id=task_data.get('job_id', task_message.parent_job_id),
                                stage_number=task_data.get('stage', job_record.stage),
                                task_type=task_data.get('task_type', job_record.job_type),
                                status=task_data.get('status', TaskStatus.COMPLETED.value),
                                result=task_data.get('result_data', {}),
                                error=task_data.get('error_details'),
                                execution_time_seconds=task_data.get('execution_time_seconds', 0.0),
                                completed_at=task_data.get('completed_at')
                            )
                            task_result_objects.append(task_result)
                    
                    # Aggregate results from all tasks in the final stage
                    logger.info(f"🎯 Aggregating results from {len(task_result_objects)} tasks for job completion")
                    
                    aggregated_results = controller.aggregate_stage_results(
                        stage_number=job_record.stage,
                        task_results=task_result_objects
                    )
                    
                    if not aggregated_results:
                        raise RuntimeError(f"Stage aggregation failed - no results returned: {task_message.parent_job_id}")
                    
                    # Update job status to completed with aggregated results
                    final_status = job_repo.update_job_status_with_validation(
                        job_id=task_message.parent_job_id,
                        new_status=JobStatus.COMPLETED,
                        additional_updates={'result_data': aggregated_results}
                    )
                    
                    logger.info(f"🎊 Job {task_message.parent_job_id[:16]}... COMPLETED successfully")
                    logger.info(f"📊 Final job status: {final_status}")
                    
                except Exception as completion_error:
                    logger.error(f"❌ CRITICAL: Job completion failed: {completion_error}")
                    # Mark job as completed_with_errors instead of failed to acknowledge partial success
                    try:
                        job_repo.update_job_status_with_validation(
                            job_id=task_message.parent_job_id,
                            new_status=JobStatus.COMPLETED_WITH_ERRORS,
                            additional_updates={'error_details': f"Job completion failed: {str(completion_error)}"}
                        )
                        logger.error(f"🟡 Job {task_message.parent_job_id} marked as COMPLETED_WITH_ERRORS")
                    except Exception as status_error:
                        logger.error(f"❌ Failed to update job status: {status_error}")
                    raise  # Re-raise for proper error handling
                
            else:
                logger.info(f"🔄 Advancing to stage {job_record.stage + 1}")
           
                # STAGE ADVANCEMENT IMPLEMENTATION
                try:
                    # Get controller for job orchestration using JobFactory
                    controller = JobFactory.create_controller(job_record.job_type)
                    
                    # Collect current stage results
                    current_stage_result = completion_detector.check_job_completion(task_message.parent_job_id)
                    stage_task_results = current_stage_result.task_results or []
                    
                    # Create stage result summary
                    stage_results = {
                        'stage_number': task_message.stage,
                        'completed_tasks': len(stage_task_results),
                        'task_results': stage_task_results,
                        'stage_completed_at': datetime.now(timezone.utc).isoformat()
                    }
                    
                    # Advance job to next stage atomically
                    advancement_result = completion_detector.advance_job_stage(
                        job_id=task_message.parent_job_id,
                        current_stage=task_message.stage,
                        stage_results=stage_results
                    )
                    
                    if not advancement_result.job_updated:
                        raise RuntimeError(f"Failed to advance job {task_message.parent_job_id} from stage {task_message.stage}")
                    
                    new_stage = advancement_result.new_stage
                    is_final = advancement_result.is_final_stage or False
                    
                    logger.info(f"✅ Job advanced from stage {task_message.stage} → stage {new_stage}")
                    
                    if is_final:
                        logger.info(f"🏁 Reached final stage {new_stage} - job should complete on next task completion")
                    else:
                        # Create tasks for next stage
                        logger.info(f"🔄 Creating tasks for stage {new_stage}")
                        
                        # Prepare previous stage results for next stage
                        # This includes the results from the stage that just completed
                        previous_stage_results = {
                            'stage_number': task_message.stage,
                            'completed_tasks': len(stage_task_results),
                            'task_results': stage_task_results,
                            'stage_completed_at': datetime.now(timezone.utc).isoformat(),
                            # Include any accumulated results from job record
                            'accumulated_results': job_record.stage_results or {}
                        }
                        
                        # Create tasks for next stage with correct parameters
                        next_stage_tasks = controller.create_stage_tasks(
                            stage_number=new_stage,
                            job_id=task_message.parent_job_id,
                            job_parameters=job_record.parameters,
                            previous_stage_results=previous_stage_results
                        )
                        
                        if not next_stage_tasks:
                            raise RuntimeError(f"No tasks created for stage {new_stage} - job would be stuck")
                        
                        # Queue tasks for next stage
                        tasks_queued = 0
                        for task_def in next_stage_tasks:
                            try:
                                # Convert TaskDefinition to TaskRecord for database insertion
                                task_record = TaskRecord(
                                    task_id=task_def.task_id,
                                    parent_job_id=task_def.job_id,  # TaskDefinition uses job_id
                                    task_type=task_def.task_type,
                                    status=TaskStatus.QUEUED,
                                    stage=task_def.stage_number,  # TaskDefinition uses stage_number
                                    task_index=task_def.parameters.get('task_index', '0'),  # Extract from params if available
                                    parameters=task_def.parameters,
                                    metadata={},
                                    retry_count=task_def.retry_count
                                )
                                
                                # Create task record
                                success = task_repo.create_task(task_record)
                                if success:
                                    logger.info(f"✅ Task {task_def.task_id} created in database, now queuing...")
                                    # Queue task for execution  
                                    task_queue_message = TaskQueueMessage(
                                        task_id=task_def.task_id,
                                        parent_job_id=task_def.job_id,  # TaskDefinition uses job_id not parent_job_id
                                        task_type=task_def.task_type,
                                        stage=task_def.stage_number,  # TaskDefinition uses stage_number not stage
                                        task_index=str(task_def.parameters.get('task_index', '0')),  # Ensure it's a string
                                        parameters=task_def.parameters
                                    )
                                    
                                    # Send to task queue
                                    # Create fresh credential for queue operations
                                    config = get_config()
                                    logger.info(f"📤 Attempting to queue task {task_def.task_id} to {config.task_processing_queue}")
                                    logger.debug(f"Config loaded, queue URL: {config.queue_service_url}")
                                    credential = DefaultAzureCredential()
                                    logger.debug(f"Credential created")
                                    queue_service = QueueServiceClient(account_url=config.queue_service_url, credential=credential)
                                    logger.debug(f"Queue service created")
                                    task_queue = queue_service.get_queue_client(config.task_processing_queue)
                                    logger.debug(f"Queue client created for {config.task_processing_queue}")
                                    
                                    message_json = task_queue_message.model_dump_json()
                                    logger.debug(f"Message JSON created, length: {len(message_json)}")
                                    task_queue.send_message(message_json)
                                    logger.debug(f"Message sent successfully")
                                    tasks_queued += 1
                                    logger.info(f"📨 Queued task {task_def.task_id}")
                                    
                            except Exception as task_error:
                                logger.error(f"❌ Failed to queue task {task_def.task_id}: {task_error}")
                                logger.error(f"❌ Error type: {type(task_error).__name__}")
                                logger.error(f"❌ Error details: {str(task_error)}")
                                import traceback
                                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                                # Continue with other tasks - partial failure handling
                        
                        logger.info(f"🎯 Stage {new_stage} started with {tasks_queued}/{len(next_stage_tasks)} tasks queued")
                        
                        if tasks_queued == 0:
                            raise RuntimeError(f"No tasks successfully queued for stage {new_stage}")
                            
                except Exception as stage_error:
                    logger.error(f"❌ CRITICAL: Stage advancement failed: {stage_error}")
                    # Update job status to failed to prevent infinite stuck state
                    try:
                        job_repo.update_job_status_with_validation(
                            job_id=task_message.parent_job_id,
                            new_status=JobStatus.FAILED,
                            additional_updates={'error_details': f"Stage advancement failed: {str(stage_error)}"}
                        )
                        logger.error(f"🔴 Job {task_message.parent_job_id} marked as FAILED due to stage advancement error")
                    except Exception as status_error:
                        logger.error(f"❌ Failed to mark job as failed: {status_error}")
                    raise  # Re-raise original error
                
        except Exception as advancement_error:
            # CRITICAL FAILURE - Job workflow is broken
            logger.error(f"❌ CRITICAL: Stage advancement failed - job stuck: {advancement_error}")
            raise  # Must re-raise - this is a critical failure
    else:
        logger.warning(f"⚠️ Job {task_message.parent_job_id} is not complete")
    # ========================================================================
    # PHASE 7: JOB COMPLETION CHECK (CRITICAL - Final verification)
    # ========================================================================
    try:
        final_job_check = completion_detector.check_job_completion(task_message.parent_job_id)
        if final_job_check.job_complete:
            logger.info(f"🎉 Job fully complete: {task_message.parent_job_id[:16]}...")
            
            # Update job status to COMPLETED
            job_repo.update_job_status_with_validation(
                job_id=task_message.parent_job_id,
                new_status=JobStatus.COMPLETED
            )
            logger.info(f"✅ Job status updated to COMPLETED: {task_message.parent_job_id[:16]}...")
            
            # Optionally, aggregate final results
            final_results = {
                "total_tasks": final_job_check.total_tasks,
                "completed_tasks": final_job_check.completed_tasks,
                "final_stage": final_job_check.final_stage,
                "completion_timestamp": datetime.utcnow().isoformat()
            }
            job_repo.update_job(
                job_id=task_message.parent_job_id,
                updates={"result_data": final_results}
            )
            
        else:
            logger.debug(f"📊 Job not yet complete: more stages or tasks pending")
            
    except Exception as job_check_error:
        # Final verification failure
        logger.error(f"❌ Job completion check failed: {job_check_error}")
        raise


@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """Poison queue monitoring endpoint using HTTP trigger base class."""
    return poison_monitor_trigger.handle_request(req)
