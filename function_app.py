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
import logging

# Suppress Azure Identity and Azure SDK authentication/HTTP logging
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._internal").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.storage").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("msal").setLevel(logging.WARNING)  # Microsoft Authentication Library

import azure.functions as func

# ========================================================================
# QUEUE TRIGGER IMPORTS - Only needed for queue processing functions
# ========================================================================
# Note: HTTP endpoints now use trigger classes with their own imports
from schema_core import JobStatus, TaskStatus, JobQueueMessage, TaskQueueMessage
from util_logger import logger

# HTTP Trigger Classes - Infrastructure Layer
from trigger_health import health_check_trigger
from trigger_submit_job import submit_job_trigger
from trigger_get_job_status import get_job_status_trigger
from trigger_poison_monitor import poison_monitor_trigger

# Use centralized logger (imported from logger_setup)

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)





@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
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
            "jobId": "SHA256_hash",
            "jobType": "hello_world",
            "parameters": {
                "dataset_id": "container_name",
                "resource_id": "file_or_folder",
                "version_id": "v1",
                "system": false
            },
            "stage": 1,
            "retryCount": 0
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
    logger.info("🔄 Job queue trigger activated - processing with Pydantic architecture")
    logger.debug(f"📨 Raw queue message received: {msg}")
    
    # Check basic imports early
    try:
        logger.debug(f"🔧 Testing basic imports availability")
        from schema_core import JobQueueMessage, JobStatus
        logger.debug(f"✅ Core schema imports working: JobQueueMessage, JobStatus")
    except ImportError as basic_import_error:
        logger.error(f"❌ CRITICAL: Basic schema imports failed: {basic_import_error}")
        logger.debug(f"🔍 Basic import error type: {type(basic_import_error).__name__}")
        raise ImportError(f"Critical schema import failure: {basic_import_error}")
    
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
        
        logger.info(f"📨 Processing job: {job_message.job_id[:16]}... type={job_message.job_type}")
        logger.debug(f"📊 Full job message details: job_id={job_message.job_id}, job_type={job_message.job_type}, stage={job_message.stage}, parameters={job_message.parameters}")
        
        # Get repositories with strong typing
        logger.debug(f"🏗️ Creating repositories for job processing")
        try:
            from repository_data import RepositoryFactory
            logger.debug(f"📦 RepositoryFactory imported successfully")
        except ImportError as import_error:
            logger.error(f"❌ Failed to import RepositoryFactory: {import_error}")
            logger.debug(f"🔍 Import error details: {type(import_error).__name__}")
            raise ImportError(f"Repository import failed: {import_error}")
        
        try:
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
            logger.debug(f"✅ Repositories created with PostgreSQL backend: job_repo={type(job_repo)}, task_repo={type(task_repo)}, completion_detector={type(completion_detector)}")
        except Exception as repo_error:
            logger.error(f"❌ Failed to create repositories: {repo_error}")
            logger.debug(f"🔍 Repository creation error type: {type(repo_error).__name__}")
            raise RuntimeError(f"Repository creation failed: {repo_error}")
        
        # Load job record
        logger.debug(f"🔍 Loading job record for: {job_message.jobId}")
        try:
            job_record = job_repo.get_job(job_message.jobId)
            logger.debug(f"📋 Job record retrieval result: {job_record}")
        except Exception as load_error:
            logger.error(f"❌ Failed to load job record: {load_error}")
            logger.debug(f"🔍 Job load error type: {type(load_error).__name__}")
            raise RuntimeError(f"Job record load failed: {load_error}")
        
        if not job_record:
            logger.error(f"❌ Job record not found: {job_message.jobId}")
            raise ValueError(f"Job record not found: {job_message.jobId}")
        
        logger.debug(f"✅ Job record loaded successfully: status={job_record.status}")
        
        # Update job status to processing
        logger.debug(f"🔄 Updating job status to PROCESSING for: {job_message.jobId}")
        try:
            job_repo.update_job_status(job_message.jobId, JobStatus.PROCESSING)
            logger.debug(f"✅ Job status updated to PROCESSING")
        except Exception as status_error:
            logger.error(f"❌ Failed to update job status to PROCESSING: {status_error}")
            logger.debug(f"🔍 Status update error type: {type(status_error).__name__}")
            raise RuntimeError(f"Job status update failed: {status_error}")
        
        # Route to controller based on job type
        logger.debug(f"🎯 Routing to controller for job type: {job_message.job_type}")
        if job_message.job_type == "hello_world":
            logger.debug(f"📦 Importing HelloWorldController")
            try:
                from controller_hello_world import HelloWorldController
                logger.debug(f"✅ HelloWorldController imported successfully")
            except ImportError as controller_import_error:
                logger.error(f"❌ Failed to import HelloWorldController: {controller_import_error}")
                logger.debug(f"🔍 Controller import error type: {type(controller_import_error).__name__}")
                raise ImportError(f"HelloWorldController import failed: {controller_import_error}")
            
            try:
                controller = HelloWorldController()
                logger.debug(f"✅ HelloWorldController instantiated: {type(controller)}")
            except Exception as controller_error:
                logger.error(f"❌ Failed to instantiate HelloWorldController: {controller_error}")
                logger.debug(f"🔍 Controller instantiation error type: {type(controller_error).__name__}")
                raise RuntimeError(f"HelloWorldController instantiation failed: {controller_error}")
            
            # Process the job stage
            stage_params = {
                'job_record': job_record,
                'stage': job_message.stage,
                'parameters': job_message.parameters,
                'stage_results': job_message.stageResults
            }
            logger.debug(f"🚀 Processing job stage with params: {stage_params}")
            
            try:
                stage_result = controller.process_job_stage(
                    job_record=job_record,
                    stage=job_message.stage,
                    parameters=job_message.parameters,
                    stage_results=job_message.stageResults
                )
                logger.debug(f"✅ Stage processing result: {stage_result}")
                logger.info(f"✅ Job {job_message.jobId[:16]}... stage {job_message.stage} completed")
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
                logger.debug(f"🔧 Attempting to mark job as failed: {job_message.jobId}")
                job_repo.fail_job(job_message.jobId, str(e))
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
        4. Route to appropriate task handler based on taskType
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
            "taskId": "jobId_stage1_task0",
            "parentJobId": "SHA256_hash",
            "taskType": "hello_world",
            "stage": 1,
            "taskIndex": 0,
            "parameters": {
                "dataset_id": "container",
                "message": "Hello World!"
            },
            "retryCount": 0
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
        
        logger.info(f"📋 Processing task: {task_message.task_id} type={task_message.task_type}")
        logger.debug(f"📊 Full task message details: task_id={task_message.task_id}, parent_job_id={task_message.parent_job_id}, task_type={task_message.task_type}, parameters={task_message.parameters}")
        
        # Get repositories with strong typing
        logger.debug(f"🏗️ Creating repositories for task processing")
        try:
            from repository_data import RepositoryFactory
            logger.debug(f"📦 RepositoryFactory imported successfully")
        except ImportError as import_error:
            logger.error(f"❌ Failed to import RepositoryFactory for tasks: {import_error}")
            logger.debug(f"🔍 Task repository import error type: {type(import_error).__name__}")
            raise ImportError(f"Task repository import failed: {import_error}")
        
        try:
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
            logger.debug(f"✅ Repositories created with PostgreSQL backend: task_repo={type(task_repo)}, job_repo={type(job_repo)}, completion_detector={type(completion_detector)}")
        except Exception as repo_error:
            logger.error(f"❌ Failed to create repositories for tasks: {repo_error}")
            logger.debug(f"🔍 Task repository creation error type: {type(repo_error).__name__}")
            raise RuntimeError(f"Task repository creation failed: {repo_error}")
        
        # Load task record
        logger.debug(f"🔍 Loading task record for: {task_message.taskId}")
        try:
            task_record = task_repo.get_task(task_message.taskId)
            logger.debug(f"📋 Task record retrieval result: {task_record}")
        except Exception as load_error:
            logger.error(f"❌ Failed to load task record: {load_error}")
            logger.debug(f"🔍 Task load error type: {type(load_error).__name__}")
            raise RuntimeError(f"Task record load failed: {load_error}")
        
        if not task_record:
            logger.error(f"❌ Task record not found: {task_message.taskId}")
            raise ValueError(f"Task record not found: {task_message.taskId}")
        
        logger.debug(f"✅ Task record loaded successfully: status={task_record.status if hasattr(task_record, 'status') else 'unknown'}")
        
        # Update task status to processing
        logger.debug(f"🔄 Updating task status to PROCESSING for: {task_message.taskId}")
        try:
            task_repo.update_task_status(task_message.taskId, TaskStatus.PROCESSING)
            logger.debug(f"✅ Task status updated to PROCESSING")
        except Exception as status_error:
            logger.error(f"❌ Failed to update task status to PROCESSING: {status_error}")
            logger.debug(f"🔍 Task status update error type: {type(status_error).__name__}")
            raise RuntimeError(f"Task status update failed: {status_error}")
        
        # Route to task handler based on task type
        logger.debug(f"🎯 Routing to task handler for task type: {task_message.taskType}")
        if task_message.taskType in ["hello_world_greeting", "hello_world_reply"]:
            logger.debug(f"📦 Importing task handler for: {task_message.taskType}")
            try:
                from service_hello_world import get_hello_world_task
                from model_core import TaskExecutionContext
                logger.debug(f"✅ Task handler imported successfully")
            except ImportError as service_import_error:
                logger.error(f"❌ Failed to import task handler: {service_import_error}")
                logger.debug(f"🔍 Service import error type: {type(service_import_error).__name__}")
                raise ImportError(f"Task handler import failed: {service_import_error}")
            
            try:
                task_handler = get_hello_world_task(task_message.taskType)
                logger.debug(f"✅ Task handler instantiated: {type(task_handler)}")
            except Exception as service_error:
                logger.error(f"❌ Failed to instantiate task handler: {service_error}")
                logger.debug(f"🔍 Service instantiation error type: {type(service_error).__name__}")
                raise RuntimeError(f"Task handler instantiation failed: {service_error}")
            
            # Create proper execution context
            context = TaskExecutionContext(
                task_id=task_message.taskId,
                job_id=task_message.parentJobId,
                task_type=task_message.taskType,
                stage_number=task_message.stage,
                stage_name=f"stage_{task_message.stage}",
                task_index=task_message.taskIndex,
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
                    task_message.taskId, 
                    TaskStatus.COMPLETED, 
                    result_data=result
                )
                logger.debug(f"✅ Task status updated to COMPLETED with result data")
                logger.info(f"✅ Task {task_message.taskId} completed successfully")
            except Exception as update_error:
                logger.error(f"❌ Failed to update task completion status: {update_error}")
                logger.debug(f"🔍 Task completion update error type: {type(update_error).__name__}")
                raise RuntimeError(f"Task completion update failed: {update_error}")
            
        else:
            # Task handler not implemented
            error_msg = f"Task handler not implemented for task type: {task_message.taskType}"
            logger.error(f"❌ {error_msg}")
            
            # Get available task types dynamically
            try:
                from service_hello_world import HELLO_WORLD_TASKS
                available_types = list(HELLO_WORLD_TASKS.keys())
                logger.debug(f"📋 Available task types: {', '.join(available_types)}")
            except ImportError:
                logger.debug(f"📋 Available task types: [unable to load registry]")
            
            task_repo.update_task_status(
                task_message.taskId, 
                TaskStatus.FAILED, 
                error_message=error_msg
            )
        
        # CRITICAL: Check if parent job is complete (distributed detection)
        logger.debug(f"🔍 Checking job completion for parent: {task_message.parentJobId}")
        try:
            completion_result = completion_detector.check_job_completion(task_message.parentJobId)
            logger.debug(f"📊 Completion check result: is_complete={completion_result.is_complete}, task_count={len(completion_result.task_results) if hasattr(completion_result, 'task_results') else 'unknown'}")
        except Exception as completion_error:
            logger.error(f"❌ Failed to check job completion: {completion_error}")
            logger.debug(f"🔍 Completion check error type: {type(completion_error).__name__}")
            import traceback
            logger.debug(f"📍 Completion check traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Job completion check failed: {completion_error}")
        
        if completion_result.is_complete:
            logger.info(f"🎉 Job {task_message.parentJobId[:16]}... completed - all tasks finished!")
            
            # This is the last task - complete the parent job
            logger.debug(f"📦 Importing controller for job aggregation")
            try:
                from controller_hello_world import HelloWorldController
                logger.debug(f"✅ HelloWorldController imported for aggregation")
            except ImportError as controller_import_error:
                logger.error(f"❌ Failed to import controller for aggregation: {controller_import_error}")
                logger.debug(f"🔍 Controller aggregation import error type: {type(controller_import_error).__name__}")
                raise ImportError(f"Controller aggregation import failed: {controller_import_error}")
            
            try:
                controller = HelloWorldController()
                logger.debug(f"✅ Controller instantiated for aggregation: {type(controller)}")
            except Exception as controller_error:
                logger.error(f"❌ Failed to instantiate controller for aggregation: {controller_error}")
                logger.debug(f"🔍 Controller aggregation instantiation error type: {type(controller_error).__name__}")
                raise RuntimeError(f"Controller aggregation instantiation failed: {controller_error}")
            
            logger.debug(f"🔄 Aggregating job results with task count: {len(completion_result.task_results) if hasattr(completion_result, 'task_results') else 'unknown'}")
            try:
                job_result = controller.aggregate_job_results(
                    job_id=task_message.parentJobId,
                    task_results=completion_result.task_results
                )
                logger.debug(f"✅ Job results aggregated successfully: {job_result}")
            except Exception as aggregation_error:
                logger.error(f"❌ Failed to aggregate job results: {aggregation_error}")
                logger.debug(f"🔍 Aggregation error type: {type(aggregation_error).__name__}")
                import traceback
                logger.debug(f"📍 Aggregation traceback: {traceback.format_exc()}")
                raise RuntimeError(f"Job result aggregation failed: {aggregation_error}")
            
            # Update job status to completed
            logger.debug(f"💾 Updating job status to COMPLETED with result data")
            try:
                job_repo.update_job_status(
                    task_message.parentJobId,
                    JobStatus.COMPLETED,
                    result_data=job_result
                )
                logger.debug(f"✅ Job status updated to COMPLETED successfully")
                logger.info(f"✅ Job {task_message.parentJobId[:16]}... marked as completed")
            except Exception as job_update_error:
                logger.error(f"❌ Failed to update job completion status: {job_update_error}")
                logger.debug(f"🔍 Job update error type: {type(job_update_error).__name__}")
                raise RuntimeError(f"Job completion status update failed: {job_update_error}")
            
    except Exception as e:
        logger.error(f"❌ Error processing task: {str(e)}")
        
        # Try to mark task as failed
        try:
            if 'task_message' in locals():
                task_repo.update_task_status(
                    task_message.taskId,
                    TaskStatus.FAILED,
                    error_message=str(e)
                )
        except Exception as update_error:
            logger.error(f"Failed to update task status: {update_error}")
        
        # Re-raise so Azure Functions knows it failed
        raise





@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """Poison queue monitoring endpoint using HTTP trigger base class."""
    return poison_monitor_trigger.handle_request(req)


# Chunk processing now handled in process_task_queue function above


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def poison_queue_timer(timer: func.TimerRequest) -> None:
    """
    Automated poison queue monitoring timer.
    
    Runs every 5 minutes to check for messages in poison queues and
    automatically mark corresponding jobs and tasks as failed. This ensures
    failed processing attempts are properly tracked and visible in job status.
    
    Args:
        timer: Azure Functions timer request object (unused but required).
        
    Schedule:
        Runs every 5 minutes (0 */5 * * * *)
        Does not run on startup to avoid immediate processing
        
    Processing:
        1. Checks geospatial-jobs-poison queue for failed job messages
        2. Checks geospatial-tasks-poison queue for failed task messages
        3. Extracts job/task IDs from poison messages
        4. Updates corresponding records in Table Storage to 'failed' status
        5. Logs summary of actions taken
        
    Note:
        - Does not delete poison messages (kept for audit trail)
        - Runs silently unless messages are found
        - Errors are logged but don't fail the timer trigger
    """
    logger.info("Poison queue timer trigger fired")
    
    try:
        from poison_queue_monitor import PoisonQueueMonitor
        
        monitor = PoisonQueueMonitor()
        summary = monitor.check_poison_queues()
        
        if summary["poison_messages_found"] > 0:
            logger.warning(f"Found {summary['poison_messages_found']} messages in poison queues. "
                         f"Marked {summary['jobs_marked_failed']} jobs and "
                         f"{summary['tasks_marked_failed']} tasks as failed.")
        else:
            logger.debug("No messages found in poison queues")
            
    except Exception as e:
        logger.error(f"Error in poison queue timer: {str(e)}")


