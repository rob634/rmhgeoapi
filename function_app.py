# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Azure Functions entry point orchestrating the geospatial ETL pipeline with HTTP and queue triggers
# EXPORTS: app (Function App), HTTP routes (health, jobs/*, db/*, schema/*), queue processors
# INTERFACES: Azure Functions triggers (HttpTrigger, QueueTrigger), controller classes
# PYDANTIC_MODELS: JobQueueMessage, TaskQueueMessage, JobSubmissionRequest (via triggers)
# DEPENDENCIES: azure.functions, trigger_* modules, controller_*, repository_consolidated, util_logger
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
    POST /api/jobs/{job_type} - Submit processing job
    GET  /api/jobs/{job_id} - Get job status and results
    GET  /api/monitor/poison - Check poison queue status
    POST /api/monitor/poison - Process poison messages
    GET  /api/admin/database - Database query endpoint for debugging

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
import datetime

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
# CRITICAL: This must run before any other imports to catch missing dependencies

# Application modules (our code) - Utilities
from util_import_validator import validator

# Perform fail-fast startup validation (only in Azure Functions or when explicitly enabled)
validator.ensure_startup_ready()

# ========================================================================
# APPLICATION IMPORTS - Our modules (validated at startup)
# ========================================================================

# Application modules (our code) - Core schemas and logging
from schema_base import JobStatus, TaskStatus, JobQueueMessage, TaskQueueMessage
from util_logger import LoggerFactory, ComponentType

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

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)





@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint using HTTP trigger base class."""
    return health_check_trigger.handle_request(req)


@app.route(route="jobs/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)


# Schema Generation Endpoints - Pydantic to SQL with psycopg.sql composition
@app.route(route="schema/generate", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def generate_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Get schema info from Pydantic models: GET /api/schema/generate"""
    from trigger_schema_pydantic_deploy import pydantic_deploy_trigger
    return pydantic_deploy_trigger.handle_request(req)


@app.route(route="schema/deploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def deploy_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Deploy Pydantic-generated schema: POST /api/schema/deploy?confirm=yes"""
    from trigger_schema_pydantic_deploy import pydantic_deploy_trigger
    return pydantic_deploy_trigger.handle_request(req)


@app.route(route="schema/compare", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def compare_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Get schema comparison info: GET /api/schema/compare"""
    from trigger_schema_pydantic_deploy import pydantic_deploy_trigger
    return pydantic_deploy_trigger.handle_request(req)


# Legacy endpoint - redirects to /api/schema/deploy
@app.route(route="schema/deploy-pydantic", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def deploy_pydantic_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Legacy endpoint - use POST /api/schema/deploy?confirm=yes instead"""
    from trigger_schema_pydantic_deploy import pydantic_deploy_trigger
    return pydantic_deploy_trigger.handle_request(req)


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


@app.route(route="db/functions/test", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def test_database_functions(req: func.HttpRequest) -> func.HttpResponse:
    """Test PostgreSQL functions: GET /api/db/functions/test"""
    return function_test_trigger.handle_request(req)


# 🧪 SINGLE STAGE TEST - DEVELOPMENT ONLY  
@app.route(route="test/single-stage", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def test_single_stage(req: func.HttpRequest) -> func.HttpResponse:
    """Test single-stage job completion: POST /api/test/single-stage"""
    try:
        # NOTE: This test function needs to be updated to use new repository architecture
        import json
        return func.HttpResponse(
            json.dumps({"error": "Test function needs update for new repository architecture"}),
            status_code=501,
            mimetype="application/json"
        )
        from controller_factories import JobFactory
        import controller_hello_world  # Import to trigger registration
        import json
        import time
        
        # Create a minimal single-stage job manually
        repo = DataRepository()
        controller = JobFactory.create_controller("hello_world")
        
        # Create job record manually with total_stages=1
        job_data = {
            'job_id': 'test_single_stage_' + str(int(time.time())),
            'job_type': 'hello_world',
            'status': 'processing',
            'stage': 1,  
            'total_stages': 1,  # Single stage
            'parameters': {'n': 1, 'message': 'single stage test'},
            'stage_results': {},
            'result_data': None,
            'error_details': None
        }
        
        # Insert job
        success = repo.storage_adapter.raw_create_job(job_data)
        
        # Create and complete task manually
        task_data = {
            'task_id': f"{job_data['job_id']}_stage1_task0",
            'parent_job_id': job_data['job_id'],
            'task_type': 'hello_world_greeting',
            'status': 'completed',  # Already completed
            'stage': 1,
            'task_index': 0,
            'parameters': {'message': 'single stage test', 'greeting': 'Hello!'},
            'result_data': {'greeting': 'Hello from single stage!'},
            'error_details': None,
            'retry_count': 0,
            'heartbeat': None
        }
        
        # Insert completed task
        task_success = repo.storage_adapter.raw_create_task(task_data)
        
        return func.HttpResponse(
            json.dumps({
                'test': 'single_stage_completion',
                'job_created': success,
                'task_created': task_success,
                'completion_result': result,
                'job_id': job_data['job_id'],
                'should_trigger_completion': result.get('stage_complete', False)
            }),
            mimetype="application/json"
        )
        
    except Exception as e:
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# 🚨 VALIDATION DEBUGGING ENDPOINT - DEVELOPMENT ONLY
@app.route(route="debug/validation/task", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def debug_task_validation(req: func.HttpRequest) -> func.HttpResponse:
    """🔧 DEBUG: Test TaskRecord validation with raw data: POST /api/debug/validation/task"""
    from trigger_validation_debug import main as validation_debug_trigger
    return validation_debug_trigger(req)


@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="AzureWebJobsStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
    """
    Process jobs from the geospatial-jobs queue using Pydantic Job→Task architecture.
    
    Modern Pydantic-based job processing with strong typing discipline and workflow definitions.
    Jobs are orchestrated through controllers that create tasks for parallel processing.
    
    Args:
        msg: Azure Functions queue message containing job data.
            
    Queue Message Format (Pydantic Job→Task Architecture):
        {
            "job_id": "SHA256_hash",
            "job_type": "hello_world",
            "parameters": {
                "dataset_id": "container_name",
                "resource_id": "file_or_folder",
                "version_id": "v1",
                "system": false
            },
            "stage": 1,
            "retry_count": 0
        }
        
    Processing Flow:
        1. Decode and validate message using JobQueueMessage schema
        2. Load job record from storage with schema validation
        3. Route to appropriate controller based on jobType
        4. Controller processes stage and creates tasks if needed
        5. Update job status with stage results
        
    Error Handling:
        - Schema validation failures: Message rejected, job marked failed
        - Controller errors: Job marked failed with error details
        - After 5 attempts: Message moved to poison queue automatically
    """
    # Initialize queue-specific logger for poison queue debugging
    logger = LoggerFactory.get_queue_logger("geospatial-jobs")
    
    logger.info("🔄 Job queue trigger activated - processing with Pydantic architecture")
    logger.debug(f"📨 Raw queue message received: {msg}")
    
    # Note: Import validation now handled at startup via util_import_validator
    
    try:
        # Parse and validate message using Pydantic schema
        logger.debug(f"🔍 Decoding queue message body")
        try:
            message_content = msg.get_body().decode('utf-8')
            logger.debug(f"📋 Decoded message content: {message_content}")
        except Exception as decode_error:
            logger.error(f"❌ Failed to decode message body: {decode_error}")
            logger.debug(f"🔍 Message decode error type: {type(decode_error).__name__}")
            raise ValueError(f"Message decode failed: {decode_error}")
        
        logger.debug(f"🔧 Validating message with JobQueueMessage schema")
        try:
            job_message = JobQueueMessage.model_validate_json(message_content)
            logger.debug(f"✅ Message validation successful: {job_message}")
        except Exception as validation_error:
            logger.error(f"❌ Message validation failed: {validation_error}")
            logger.debug(f"🔍 Validation error type: {type(validation_error).__name__}")
            logger.debug(f"📋 Invalid message content: {message_content}")
            raise ValueError(f"Message validation failed: {validation_error}")
        
        # Update logger context with job details for better correlation
        logger.update_context(
            job_id=job_message.job_id,
            job_type=job_message.job_type,
            stage=job_message.stage
        )
        
        logger.info(f"📨 Processing job: {job_message.job_id[:16]}... type={job_message.job_type}")
        logger.debug(f"📊 Full job message details: job_id={job_message.job_id}, job_type={job_message.job_type}, stage={job_message.stage}, parameters={job_message.parameters}")
        
        # Get repositories (imports validated at startup)
        logger.debug(f"🏗️ Creating repositories for job processing")
        from repository_consolidated import RepositoryFactory
        
        try:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            task_repo = repos['task_repo']
            completion_detector = repos['completion_detector']
            logger.debug(f"✅ Repositories created with PostgreSQL backend")
        except Exception as repo_error:
            logger.error(f"❌ Failed to create repositories: {repo_error}")
            raise RuntimeError(f"Repository creation failed: {repo_error}")
        
        # Load job record
        logger.debug(f"🔍 Loading job record for: {job_message.job_id}")
        try:
            job_record = job_repo.get_job(job_message.job_id)
            logger.debug(f"📋 Job record retrieval result: {job_record}")
        except Exception as load_error:
            logger.error(f"❌ Failed to load job record: {load_error}")
            logger.debug(f"🔍 Job load error type: {type(load_error).__name__}")
            raise RuntimeError(f"Job record load failed: {load_error}")
        
        if not job_record:
            logger.error(f"❌ Job record not found: {job_message.job_id}")
            raise ValueError(f"Job record not found: {job_message.job_id}")
        
        logger.debug(f"✅ Job record loaded successfully: status={job_record.status}")
        
        # Update job status to processing
        logger.debug(f"🔄 Updating job status to PROCESSING for: {job_message.job_id}")
        try:
            job_repo.update_job_status(job_message.job_id, JobStatus.PROCESSING)
            logger.debug(f"✅ Job status updated to PROCESSING")
        except Exception as status_error:
            logger.error(f"❌ Failed to update job status to PROCESSING: {status_error}")
            logger.debug(f"🔍 Status update error type: {type(status_error).__name__}")
            raise RuntimeError(f"Job status update failed: {status_error}")
        
        # Route to controller based on job type (imports validated at startup)
        logger.debug(f"🎯 Routing to controller for job type: {job_message.job_type}")
        
        # Use JobFactory to get the appropriate controller
        from controller_factories import JobFactory
        import controller_hello_world  # Import to trigger registration
        
        try:
            controller = JobFactory.create_controller(job_message.job_type)
            logger.debug(f"✅ Controller for {job_message.job_type} instantiated via JobFactory")
        except Exception as controller_error:
            logger.error(f"❌ Failed to create controller for {job_message.job_type}: {controller_error}")
            raise RuntimeError(f"Controller creation failed for {job_message.job_type}: {controller_error}")
            
            # Process the job stage
            stage_params = {
                'job_record': job_record,
                'stage': job_message.stage,
                'parameters': job_message.parameters,
                'stage_results': job_message.stage_results
            }
            logger.debug(f"🚀 Processing job stage with params: {stage_params}")
            
            try:
                stage_results = controller.process_job_stage(
                    job_record=job_record,
                    stage=job_message.stage,
                    parameters=job_message.parameters,
                    stage_results=job_message.stage_results
                )
                logger.debug(f"✅ Stage processing result: {stage_results}")
                logger.info(f"✅ Job {job_message.job_id[:16]}... stage {job_message.stage} completed")
            except Exception as stage_error:
                logger.error(f"❌ Failed to process job stage: {stage_error}")
                logger.debug(f"🔍 Stage processing error type: {type(stage_error).__name__}")
                import traceback
                logger.debug(f"📍 Stage processing traceback: {traceback.format_exc()}")
                raise RuntimeError(f"Job stage processing failed: {stage_error}")
            
        else:
            # Controller not implemented
            error_msg = f"Controller not implemented for job type: {job_message.job_type}"
            logger.error(f"❌ {error_msg}")
            logger.debug(f"🔧 Marking job as failed due to missing controller")
            job_repo.fail_job(job_message.job_id, error_msg)
            
    except Exception as e:
        logger.error(f"❌ Error processing job: {str(e)}")
        logger.debug(f"🔍 Error details: {type(e).__name__}: {str(e)}")
        import traceback
        logger.debug(f"📍 Full error traceback: {traceback.format_exc()}")
        
        # Try to mark job as failed
        try:
            if 'job_message' in locals():
                logger.debug(f"🔧 Attempting to mark job as failed: {job_message.job_id}")
                job_repo.fail_job(job_message.job_id, str(e))
                logger.debug(f"✅ Job marked as failed successfully")
        except Exception as update_error:
            logger.error(f"❌ Failed to update job status: {update_error}")
            logger.debug(f"🔍 Update error details: {type(update_error).__name__}: {str(update_error)}")
        
        # Re-raise so Azure Functions knows it failed
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
    logger = LoggerFactory.get_queue_logger("geospatial-tasks")
    
    logger.info("🔄 Task queue trigger activated - processing with Pydantic architecture")
    logger.debug(f"📨 Raw task queue message received: {msg}")
    
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
    
    # Update logger context now that we have valid task details
    logger.update_context(
        task_id=task_message.task_id,
        job_id=task_message.parent_job_id,
        task_type=task_message.task_type,
        stage=task_message.stage
    )
    
    # ========================================================================
    # PHASE 2: REPOSITORY SETUP (Infrastructure)
    # ========================================================================
    try:
        from repository_consolidated import RepositoryFactory
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
        task_repo.update_task_status(task_message.task_id, TaskStatus.PROCESSING)
        logger.info(f"📋 Processing task: {task_message.task_id}")
        
    except Exception as load_error:
        logger.error(f"❌ Task loading failed: {load_error}")
        try:
            # Try to mark task as failed if possible
            logger.debug(f"🔧 Attempting to mark task as failed: {task_message.task_id}")
            task_repo.update_task_status(
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

######## ROBERT'S NOTES
######## This needs to be if task_message.task_type in <dynamically generated list of tasks based on the job type> 
######## TODO Task registry object from which to retrieve the business logic services
######## e.g. TaskServicesFactory.from_task_type(task_message.task_type)
######## For now, hardcoded hello world is ok until hello world is completely working
        if task_message.task_type in ["hello_world_greeting", "hello_world_reply"]:
            from service_hello_world import get_hello_world_task
            from schema_base import TaskExecutionContext
            
            task_handler = get_hello_world_task(task_message.task_type)
            
            # Create execution context
            context = TaskExecutionContext(
                task_id=task_message.task_id,
                parent_job_id=task_message.parent_job_id,
                stage=task_message.stage,
                task_index=task_message.task_index,
                parameters=task_message.parameters
            )
            
            # Execute task
            task_result = task_handler.execute(context)
            
            if not hasattr(task_result, 'result'):
                raise ValueError(f"Invalid task result object: {task_result}")
                
            logger.info(f"✅ Task executed successfully")
            
        else:
            # Get available task types for error message
            from service_hello_world import HELLO_WORLD_TASKS
            available_types = list(HELLO_WORLD_TASKS.keys())
            raise NotImplementedError(
                f"Handler not implemented for: {task_message.task_type}. "
                f"Available types: {', '.join(available_types)}"
            )
            
    except Exception as exec_error:
        logger.error(f"❌ Task execution failed: {exec_error}")
        
        # Create a failed task result for proper error tracking
        from schema_base import TaskResult
        task_result = TaskResult(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            stage_number=task_message.stage,
            task_type=task_message.task_type,
            status=TaskStatus.FAILED.value,
            success=False,
            result={},  # Empty result for failures
            error=str(exec_error),  # Capture error details
            execution_time_seconds=0.0
        )
        
        # Mark task as failed in database
        try:
            task_repo.update_task_status(
                task_message.task_id,
                TaskStatus.FAILED,
                additional_updates={'error_details': str(exec_error)}
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
                result_data=task_result.result if task_result.result else {},
                error_details=None  # Explicit None for successful tasks
            )
        else:
            # Task failed - pass error details as separate parameter
            error_msg = getattr(task_result, 'error', 'No result returned from task execution') if task_result else 'Task execution failed'
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
        stage_complete = stage_completion_result.get('stage_complete', False)
        if stage_complete:
            logger.info(f"🎯 Stage {task_message.stage} is now complete - last task turned out the lights")
        else:
            remaining = stage_completion_result.get('remaining_tasks', 'unknown')
            logger.info(f"⏳ Stage {task_message.stage} has {remaining} tasks remaining")
        
    except Exception as completion_error:
        logger.error(f"❌ Failed to mark task complete: {completion_error}")
        # This is critical - task executed but not marked complete
        # Try to update task status directly as fallback
        try:
            task_repo.update_task_status(
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
                    from controller_factories import JobFactory
                    import controller_hello_world  # Import to trigger registration
                    controller = JobFactory.create_controller(job_record.job_type)
                    
                    # Get all task results from completed job
                    final_job_check = completion_detector.check_job_completion(task_message.parent_job_id)
                    
                    if not final_job_check.job_complete:
                        raise RuntimeError(f"Job completion check failed - job not ready for completion: {task_message.parent_job_id}")
                    
                    # Convert JSONB task results to TaskResult objects
                    from schema_base import TaskResult, TaskStatus
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
                    final_status = job_repo.update_job_status(
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
                        job_repo.update_job_status(
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
                    from controller_factories import JobFactory
                    import controller_hello_world  # Import to trigger registration
                    controller = JobFactory.create_controller(job_record.job_type)
                    
                    # Collect current stage results
                    current_stage_result = completion_detector.check_job_completion(task_message.parent_job_id)
                    stage_task_results = current_stage_result.task_results or []
                    
                    # Create stage result summary
                    stage_results = {
                        'stage_number': task_message.stage,
                        'completed_tasks': len(stage_task_results),
                        'task_results': stage_task_results,
                        'stage_completed_at': datetime.datetime.utcnow().isoformat()
                    }
                    
                    # Advance job to next stage atomically
                    advancement_result = completion_detector.advance_job_stage(
                        job_id=task_message.parent_job_id,
                        current_stage=task_message.stage,
                        stage_results=stage_results
                    )
                    
                    if not advancement_result.get('job_updated', False):
                        raise RuntimeError(f"Failed to advance job {task_message.parent_job_id} from stage {task_message.stage}")
                    
                    new_stage = advancement_result.get('new_stage')
                    is_final = advancement_result.get('is_final_stage', False)
                    
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
                            'stage_completed_at': datetime.datetime.utcnow().isoformat(),
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
                                # Create task record
                                success = task_repo.create_task(task_def)
                                if success:
                                    # Queue task for execution  
                                    task_queue_message = TaskQueueMessage(
                                        task_id=task_def.task_id,
                                        parent_job_id=task_def.job_id,  # TaskDefinition uses job_id not parent_job_id
                                        task_type=task_def.task_type,
                                        stage=task_def.stage_number,  # TaskDefinition uses stage_number not stage
                                        task_index=0,  # Default task_index since TaskDefinition doesn't have this field
                                        parameters=task_def.parameters
                                    )
                                    
                                    # Send to task queue
                                    from azure.storage.queue import QueueServiceClient
                                    from config import get_config
                                    
                                    config = get_config()
                                    queue_service = QueueServiceClient(account_url=config.storage_account_url, credential=config.azure_credential)
                                    task_queue = queue_service.get_queue_client(config.task_processing_queue)
                                    
                                    task_queue.send_message(task_queue_message.model_dump_json())
                                    tasks_queued += 1
                                    logger.info(f"📨 Queued task {task_def.task_id}")
                                    
                            except Exception as task_error:
                                logger.error(f"❌ Failed to queue task {task_def.task_id}: {task_error}")
                                # Continue with other tasks - partial failure handling
                        
                        logger.info(f"🎯 Stage {new_stage} started with {tasks_queued}/{len(next_stage_tasks)} tasks queued")
                        
                        if tasks_queued == 0:
                            raise RuntimeError(f"No tasks successfully queued for stage {new_stage}")
                            
                except Exception as stage_error:
                    logger.error(f"❌ CRITICAL: Stage advancement failed: {stage_error}")
                    # Update job status to failed to prevent infinite stuck state
                    try:
                        job_repo.update_job_status(
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
        if final_job_check.is_complete:
            logger.info(f"🎉 Job fully complete: {task_message.parent_job_id[:16]}...")
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


@app.route(route="admin/database", methods=["GET"])
def query_database(req: func.HttpRequest) -> func.HttpResponse:
    """
    Legacy database query endpoint - DEPRECATED.
    
    🚨 DEPRECATED: Use new database monitoring endpoints instead:
        GET /api/db/jobs - Query jobs
        GET /api/db/tasks - Query tasks  
        GET /api/db/stats - Database statistics
        GET /api/db/functions/test - Test functions
        GET /api/health - Enhanced health with database metrics
    """
    import json
    from datetime import datetime, timezone
    
    return func.HttpResponse(
        body=json.dumps({
            "deprecated": True,
            "message": "This endpoint is deprecated. Use new database monitoring endpoints.",
            "new_endpoints": {
                "jobs": "/api/db/jobs",
                "tasks": "/api/db/tasks", 
                "statistics": "/api/db/stats",
                "function_tests": "/api/db/functions/test",
                "enhanced_health": "/api/health"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }),
        status_code=200,
        mimetype="application/json"
    )


@app.route(route="admin/test", methods=["GET"])
def test_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Simple test endpoint to verify route registration works."""
    import json
    from datetime import datetime, timezone
    
    return func.HttpResponse(
        body=json.dumps({
            "status": "test_endpoint_working",
            "message": "Route registration is working",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_params": dict(req.params)
        }),
        status_code=200,
        headers={'Content-Type': 'application/json'}
    )


# Chunk processing now handled in process_task_queue function above


# @app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
# def poison_queue_timer(timer: func.TimerRequest) -> None:
#     """
#     Automated poison queue monitoring timer.
#     
#     Runs every 5 minutes to check for messages in poison queues and
#     automatically mark corresponding jobs and tasks as failed. This ensures
#     failed processing attempts are properly tracked and visible in job status.
#     
#     Args:
#         timer: Azure Functions timer request object (unused but required).
#         
#     Schedule:
#         Runs every 5 minutes (0 */5 * * * *)
#         Does not run on startup to avoid immediate processing
#         
#     Processing:
#         1. Checks geospatial-jobs-poison queue for failed job messages
#         2. Checks geospatial-tasks-poison queue for failed task messages
#         3. Extracts job/task IDs from poison messages
#         4. Updates corresponding records in Table Storage to 'failed' status
#         5. Logs summary of actions taken
#         
#     Note:
#         - Does not delete poison messages (kept for audit trail)
#         - Runs silently unless messages are found
#         - Errors are logged but don't fail the timer trigger
#     """
#     # Initialize poison queue monitor logger
#     logger = LoggerFactory.get_logger(ComponentType.POISON_MONITOR, "PoisonQueueTimer")
#     
#     logger.info("Poison queue timer trigger fired")
#     
#     try:
#         from poison_queue_monitor import PoisonQueueMonitor
#         
#         monitor = PoisonQueueMonitor()
#         summary = monitor.check_poison_queues()
#         
#         if summary["poison_messages_found"] > 0:
#             logger.warning(f"Found {summary['poison_messages_found']} messages in poison queues. "
#                          f"Marked {summary['jobs_marked_failed']} jobs and "
#                          f"{summary['tasks_marked_failed']} tasks as failed.")
#         else:
#             logger.debug("No messages found in poison queues")
#             
#     except Exception as e:
#         logger.error(f"Error in poison queue timer: {str(e)}")


@app.function_name(name="force_create_functions")
@app.route(route="admin/functions/create", methods=["POST"])
def force_create_functions(req: func.HttpRequest) -> func.HttpResponse:
    """
    Force creation of PostgreSQL functions bypassing validation.
    
    This endpoint directly creates the required PostgreSQL functions without 
    checking table status, used when tables exist but function deployment is blocked.
    """
    from schema_manager import SchemaManagerFactory
    from datetime import datetime
    import json
    
    try:
        # Get schema manager
        schema_manager = SchemaManagerFactory.create_schema_manager()
        
        # Force create functions
        result = schema_manager.force_create_functions()
        
        if result['success']:
            return func.HttpResponse(
                body=json.dumps({
                    "status": "success",
                    "message": result['message'],
                    "functions_created": result['functions_created'],
                    "functions_count": result['functions_count'],
                    "timestamp": datetime.now().isoformat()
                }),
                status_code=200,
                headers={'Content-Type': 'application/json'}
            )
        else:
            return func.HttpResponse(
                body=json.dumps({
                    "status": "error",
                    "error": result['error'],
                    "functions_created": result.get('functions_created', []),
                    "timestamp": datetime.now().isoformat()
                }),
                status_code=500,
                headers={'Content-Type': 'application/json'}
            )
            
    except Exception as e:
        return func.HttpResponse(
            body=json.dumps({
                "status": "error",
                "error": f"Function creation failed: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )


