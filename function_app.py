# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Azure Functions entry point for geospatial ETL pipeline
# SOURCE: Environment variables for function bindings and configuration
# SCOPE: Global application entry point with HTTP triggers and queue processing
# VALIDATION: Azure Function binding validation and HTTP request validation
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
from schema_core import JobStatus, TaskStatus, JobQueueMessage, TaskQueueMessage
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
        from repository_data import RepositoryFactory
        
        try:
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
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
        if job_message.job_type == "hello_world":
            from controller_hello_world import HelloWorldController
            
            try:
                controller = HelloWorldController()
                logger.debug(f"✅ HelloWorldController instantiated")
            except Exception as controller_error:
                logger.error(f"❌ Failed to instantiate HelloWorldController: {controller_error}")
                raise RuntimeError(f"HelloWorldController instantiation failed: {controller_error}")
            
            # Process the job stage
            stage_params = {
                'job_record': job_record,
                'stage': job_message.stage,
                'parameters': job_message.parameters,
                'stage_results': job_message.stage_results
            }
            logger.debug(f"🚀 Processing job stage with params: {stage_params}")
            
            try:
                stage_result = controller.process_job_stage(
                    job_record=job_record,
                    stage=job_message.stage,
                    parameters=job_message.parameters,
                    stage_results=job_message.stage_results
                )
                logger.debug(f"✅ Stage processing result: {stage_result}")
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
    
    try:
        # Parse and validate message using Pydantic schema
        logger.debug(f"🔍 Decoding task queue message body")
        try:
            message_content = msg.get_body().decode('utf-8')
            logger.debug(f"📋 Decoded task message content: {message_content}")
        except Exception as decode_error:
            logger.error(f"❌ Failed to decode task message body: {decode_error}")
            logger.debug(f"🔍 Task message decode error type: {type(decode_error).__name__}")
            raise ValueError(f"Task message decode failed: {decode_error}")
        
        logger.debug(f"🔧 Validating message with TaskQueueMessage schema")
        try:
            task_message = TaskQueueMessage.model_validate_json(message_content)
            logger.debug(f"✅ Task message validation successful: {task_message}")
        except Exception as validation_error:
            logger.error(f"❌ Task message validation failed: {validation_error}")
            logger.debug(f"🔍 Task validation error type: {type(validation_error).__name__}")
            logger.debug(f"📋 Invalid task message content: {message_content}")
            raise ValueError(f"Task message validation failed: {validation_error}")
        
        # Update logger context with task details for better correlation
        logger.update_context(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            task_type=task_message.task_type,
            stage=task_message.stage
        )
        
        logger.info(f"📋 Processing task: {task_message.task_id} type={task_message.task_type}")
        logger.debug(f"📊 Full task message details: task_id={task_message.task_id}, parent_job_id={task_message.parent_job_id}, task_type={task_message.task_type}, parameters={task_message.parameters}")
        
        # Get repositories (imports validated at startup)
        logger.debug(f"🏗️ Creating repositories for task processing")
        from repository_data import RepositoryFactory
        
        try:
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
            logger.debug(f"✅ Repositories created with PostgreSQL backend")
        except Exception as repo_error:
            logger.error(f"❌ Failed to create repositories for tasks: {repo_error}")
            raise RuntimeError(f"Task repository creation failed: {repo_error}")
        
        # Load task record
        logger.debug(f"🔍 Loading task record for: {task_message.task_id}")
        try:
            task_record = task_repo.get_task(task_message.task_id)
            logger.debug(f"📋 Task record retrieval result: {task_record}")
        except Exception as load_error:
            logger.error(f"❌ Failed to load task record: {load_error}")
            logger.debug(f"🔍 Task load error type: {type(load_error).__name__}")
            raise RuntimeError(f"Task record load failed: {load_error}")
        
        if not task_record:
            logger.error(f"❌ Task record not found: {task_message.task_id}")
            raise ValueError(f"Task record not found: {task_message.task_id}")
        
        logger.debug(f"✅ Task record loaded successfully: status={task_record.status if hasattr(task_record, 'status') else 'unknown'}")
        
        # Update task status to processing
        logger.debug(f"🔄 Updating task status to PROCESSING for: {task_message.task_id}")
        try:
            task_repo.update_task_status(task_message.task_id, TaskStatus.PROCESSING)
            logger.debug(f"✅ Task status updated to PROCESSING")
        except Exception as status_error:
            logger.error(f"❌ Failed to update task status to PROCESSING: {status_error}")
            logger.debug(f"🔍 Task status update error type: {type(status_error).__name__}")
            raise RuntimeError(f"Task status update failed: {status_error}")
        
        # Route to task handler based on task type (imports validated at startup)
        logger.debug(f"🎯 Routing to task handler for task type: {task_message.task_type}")
        if task_message.task_type in ["hello_world_greeting", "hello_world_reply"]:
            from service_hello_world import get_hello_world_task
            from model_core import TaskExecutionContext
            
            try:
                task_handler = get_hello_world_task(task_message.task_type)
                logger.debug(f"✅ Task handler instantiated")
            except Exception as service_error:
                logger.error(f"❌ Failed to instantiate task handler: {service_error}")
                raise RuntimeError(f"Task handler instantiation failed: {service_error}")
            
            # Create proper execution context
            context = TaskExecutionContext(
                task_id=task_message.task_id,
                parent_job_id=task_message.parent_job_id,
                stage=task_message.stage,
                task_index=task_message.task_index,
                parameters=task_message.parameters
            )
            logger.debug(f"✅ Task execution context created: {context}")
            
            # Execute task with modern interface
            try:
                task_result = task_handler.execute(context)
                logger.debug(f"✅ Task execution result: {task_result}")
                
                # Extract result data from TaskResult object
                result = task_result.result if hasattr(task_result, 'result') else task_result
                logger.debug(f"✅ Extracted result data: {result}")
            except Exception as task_error:
                logger.error(f"❌ Task execution failed: {task_error}")
                logger.debug(f"🔍 Task execution error type: {type(task_error).__name__}")
                import traceback
                logger.debug(f"📍 Task execution traceback: {traceback.format_exc()}")
                raise RuntimeError(f"Task execution failed: {task_error}")
            
            # Update task with result
            logger.debug(f"💾 Updating task with completion status and result")
            try:
                task_repo.update_task_status(
                    task_message.task_id, 
                    TaskStatus.COMPLETED, 
                    additional_updates={'result_data': result}
                )
                logger.debug(f"✅ Task status updated to COMPLETED with result data")
                logger.info(f"✅ Task {task_message.task_id} completed successfully")
            except Exception as update_error:
                logger.error(f"❌ Failed to update task completion status: {update_error}")
                logger.debug(f"🔍 Task completion update error type: {type(update_error).__name__}")
                raise RuntimeError(f"Task completion update failed: {update_error}")
            
        else:
            # Task handler not implemented
            error_msg = f"Task handler not implemented for task type: {task_message.task_type}"
            logger.error(f"❌ {error_msg}")
            
            # Get available task types (imports validated at startup)
            from service_hello_world import HELLO_WORLD_TASKS
            available_types = list(HELLO_WORLD_TASKS.keys())
            logger.debug(f"📋 Available task types: {', '.join(available_types)}")
            
            task_repo.update_task_status(
                task_message.task_id, 
                TaskStatus.FAILED, 
                additional_updates={'error_details': error_msg}
            )
        
        # CRITICAL: Check if parent job is complete (distributed detection)
        logger.debug(f"🔍 Checking job completion for parent: {task_message.parent_job_id}")
        logger.debug(f"🎯 Current task: {task_message.task_id} (just completed)")
        try:
            completion_result = completion_detector.check_job_completion(task_message.parent_job_id)
            logger.debug(f"📊 Completion check result: is_complete={completion_result.is_complete}, task_count={len(completion_result.task_results) if hasattr(completion_result, 'task_results') else 'unknown'}")
            logger.debug(f"📊 Completion details: final_stage={getattr(completion_result, 'final_stage', 'unknown')}, completed_tasks={getattr(completion_result, 'completed_tasks', 'unknown')}, total_tasks={getattr(completion_result, 'total_tasks', 'unknown')}")
        except Exception as completion_error:
            logger.error(f"❌ COMPLETION DETECTION FAILED: {completion_error}")
            logger.error(f"⚠️ This error occurs AFTER task was marked as COMPLETED")
            logger.error(f"🔍 Completion check error type: {type(completion_error).__name__}")
            import traceback
            logger.error(f"📍 Completion check traceback: {traceback.format_exc()}")
            logger.error(f"🚨 This will trigger the outer exception handler that tries to mark completed tasks as failed")
            raise RuntimeError(f"Job completion check failed: {completion_error}")
        
        if completion_result.is_complete:
            logger.info(f"🎉 Job {task_message.parent_job_id[:16]}... completed - all tasks finished!")
            
            # This is the last task - complete the parent job (imports validated at startup)
            from controller_hello_world import HelloWorldController
            
            try:
                controller = HelloWorldController()
                logger.debug(f"✅ Controller instantiated for aggregation")
            except Exception as controller_error:
                logger.error(f"❌ Failed to instantiate controller for aggregation: {controller_error}")
                raise RuntimeError(f"Controller aggregation instantiation failed: {controller_error}")
            
            logger.debug(f"🔄 Aggregating job results with task count: {len(completion_result.task_results) if hasattr(completion_result, 'task_results') else 'unknown'}")
            try:
                # Use the complete_job method which handles JobExecutionContext properly
                job_result = controller.complete_job(
                    job_id=task_message.parent_job_id,
                    all_task_results=completion_result.task_results
                )
                logger.debug(f"✅ Job results aggregated and completed successfully: {job_result}")
                logger.info(f"✅ Job {task_message.parent_job_id[:16]}... marked as completed by complete_job()")
            except Exception as aggregation_error:
                logger.error(f"❌ JOB AGGREGATION FAILED: {aggregation_error}")
                logger.error(f"⚠️ This error occurs AFTER task was marked as COMPLETED") 
                logger.error(f"🔍 Job aggregation error type: {type(aggregation_error).__name__}")
                import traceback
                logger.error(f"📍 Job aggregation traceback: {traceback.format_exc()}")
                logger.error(f"🚨 This will trigger the outer exception handler that tries to mark completed tasks as failed")
                raise RuntimeError(f"Job completion failed: {aggregation_error}")
            
    except Exception as e:
        logger.error(f"❌ Error processing task: {str(e)}")
        
        # CRITICAL: Check current task status before attempting to mark as failed
        # This prevents invalid COMPLETED → FAILED transitions
        try:
            if 'task_message' in locals() and 'task_repo' in locals():
                logger.debug(f"🔍 Checking current task status before error handling for: {task_message.task_id}")
                
                # Get current task status to avoid invalid transitions
                current_task = task_repo.get_task(task_message.task_id)
                logger.debug(f"📋 Current task status: {current_task.status if current_task else 'NOT_FOUND'}")
                
                # Only mark as failed if not already in a terminal state
                if current_task and not current_task.status.is_terminal():
                    logger.debug(f"🔄 Marking non-terminal task as FAILED: {task_message.task_id}")
                    task_repo.update_task_status(
                        task_message.task_id,
                        TaskStatus.FAILED,
                        additional_updates={'error_details': str(e)}
                    )
                    logger.debug(f"✅ Task marked as FAILED successfully")
                elif current_task and current_task.status.is_terminal():
                    logger.warning(f"⚠️ Skipping status update - task already in terminal state: {current_task.status}")
                    logger.warning(f"⚠️ Error occurred after task completion: {str(e)}")
                    logger.warning(f"⚠️ This suggests an issue in job completion detection or aggregation")
                else:
                    logger.error(f"❌ Cannot update status - task not found: {task_message.task_id}")
                    
        except Exception as update_error:
            logger.error(f"❌ Failed to safely update task status: {update_error}")
            logger.debug(f"🔍 Status update error type: {type(update_error).__name__}")
        
        # Re-raise so Azure Functions knows it failed
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
    from datetime import datetime
    
    return func.HttpResponse(
        body=json.dumps({
            "status": "test_endpoint_working",
            "message": "Route registration is working",
            "timestamp": datetime.utcnow().isoformat(),
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
    from service_schema_manager import SchemaManagerFactory
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


