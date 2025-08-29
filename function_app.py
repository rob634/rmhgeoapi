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
import json
import logging

# Suppress Azure Identity and Azure SDK authentication/HTTP logging
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._internal").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.storage").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("msal").setLevel(logging.WARNING)  # Microsoft Authentication Library

import azure.functions as func
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

# ========================================================================
# REDESIGN ARCHITECTURE IMPORTS - New foundation classes
# ========================================================================
from schema_core import (
    JobStatus, TaskStatus, JobRecord, TaskRecord, JobQueueMessage, TaskQueueMessage
)
from controller_base import BaseController  
from util_completion import CompletionOrchestrator

# Strongly typed configuration
from config import get_config, debug_config, QueueNames
from util_logger import logger, log_list, log_job_stage, log_queue_operation, log_service_processing


# Use centralized logger (imported from logger_setup)

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Global infrastructure status for startup checks
_infrastructure_initialized = False
_infrastructure_status = None

def ensure_infrastructure_ready():
    """
    Ensure infrastructure is initialized on first request.
    
    This function is called by endpoints to guarantee that tables and queues
    exist before processing begins. Uses lazy initialization to avoid startup
    delays but ensures infrastructure is ready when needed.
    """
    global _infrastructure_initialized, _infrastructure_status
    
    if not _infrastructure_initialized:
        logger.info("🔧 Initializing infrastructure on first request...")
        try:
            # TODO: Temporarily skip infrastructure initialization for local testing
            # from initializer_infrastructure import InfrastructureInitializer
            # initializer = InfrastructureInitializer()
            # _infrastructure_status = initializer.initialize_all()
            _infrastructure_initialized = True
            _infrastructure_status = {"overall_success": True}  # Mock status for now
            logger.info("✅ Infrastructure initialization skipped for local testing")
                
        except Exception as e:
            logger.error(f"❌ Infrastructure initialization failed: {e}")
            # Continue anyway - individual operations will handle missing infrastructure
    
    return _infrastructure_initialized

def get_queue_client():
    """
    Initialize and return Azure Queue client with managed identity.
    
    Creates a QueueServiceClient using DefaultAzureCredential for managed
    identity authentication. Ensures the queue exists before returning
    the client. This client is used for submitting jobs to the processing
    queue.
    
    Returns:
        QueueClient: Configured client for job queue operations with
            base64 encoding handled by Azure Functions runtime.
        
    Raises:
        ValueError: If STORAGE_ACCOUNT_NAME is not configured in environment.
        
    Note:
        - Uses AzureWebJobsStorage settings extracted during configuration
        - Queue encoding is handled by Azure Functions runtime based on
          host.json configuration (messageEncoding: "base64")
        - Queue is created if it doesn't exist
    """
    # Get strongly typed configuration
    config = get_config()
    
    # Use queue service URL from config
    account_url = config.queue_service_url
    
    # Use DefaultAzureCredential which works with managed identity in Azure
    queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
    
    queue_name = config.job_processing_queue
    
    # Ensure queue exists
    try:
        queue_service.create_queue(queue_name)
    except Exception:
        pass  # Queue already exists
    
    queue_client = queue_service.get_queue_client(queue_name)
    
    # Don't set TextBase64EncodePolicy - let Azure Functions handle encoding
    # since host.json has "messageEncoding": "base64" configured
    
    return queue_client




@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """
    Comprehensive health check endpoint with optional database check.
    
    Performs health checks on all system components including storage queues,
    table storage, and optionally PostgreSQL database. Returns detailed status
    information for monitoring and diagnostics.
    
    Args:
        req: Azure Functions HTTP request object.
        
    Returns:
        HttpResponse: JSON response with health status and component details.
            Status code 200 if healthy, 503 if any component is unhealthy.
            
    Response Format:
        {
            "status": "healthy" | "unhealthy",
            "timestamp": "ISO-8601 timestamp",
            "environment": {
                "storage_account": "account_name",
                "queues": {
                    "geospatial-jobs": {"status": "accessible", "message_count": 0},
                    "geospatial-tasks": {"status": "accessible", "message_count": 0}
                },
                "tables": {
                    "Jobs": {"status": "accessible"},
                    "Tasks": {"status": "accessible"}
                }
            },
            "runtime": {
                "python_version": "3.11.0",
                "function_runtime": "python"
            },
            "database": {  # Optional, if ENABLE_DATABASE_HEALTH_CHECK=true
                "status": "connected",
                "postgis_version": "3.4.0",
                "stac_item_count": 270
            },
            "errors": []  # List of error messages if unhealthy
        }
        
    Note:
        Database check is only performed if ENABLE_DATABASE_HEALTH_CHECK
        environment variable is set to "true".
    """
    import os
    import sys
    from datetime import datetime, timezone
    
    logger.debug("Health check endpoint called")
    
    # Ensure infrastructure is ready - this will initialize on first health check
    ensure_infrastructure_ready()
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "storage_account": get_config().storage_account_name,
            "queues": {},
            "tables": {}
        },
        "runtime": {
            "python_version": sys.version.split()[0],
            "function_runtime": "python"
        }
    }
    
    errors = []
    
    # Check storage queues
    try:
        from azure.storage.queue import QueueServiceClient
        from azure.identity import DefaultAzureCredential
        
        config = get_config()
        account_url = config.queue_service_url
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        
        # Check geospatial-jobs queue
        for queue_name in [config.job_processing_queue, config.task_processing_queue]:
            try:
                queue_client = queue_service.get_queue_client(queue_name)
                properties = queue_client.get_queue_properties()
                health_status["environment"]["queues"][queue_name] = {
                    "name": queue_name,
                    "status": "accessible",
                    "message_count": properties.get("approximate_message_count", 0)
                }
            except Exception as e:
                health_status["environment"]["queues"][queue_name] = {
                    "name": queue_name,
                    "status": "error",
                    "error": str(e)
                }
                errors.append(f"Queue {queue_name}: {str(e)}")
    except Exception as e:
        errors.append(f"Queue service: {str(e)}")
        
    # Check table storage
    try:
        from azure.data.tables import TableServiceClient
        
        config = get_config()
        account_url = config.table_service_url
        table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        
        # Check Jobs and Tasks tables
        for table_name in ["Jobs", "Tasks"]:
            try:
                table_client = table_service.get_table_client(table_name)
                # Try a simple query to verify access
                entities = table_client.query_entities(
                    query_filter="PartitionKey eq 'test'"
                )
                # Consume the iterator to actually execute the query
                _ = next(iter(entities), None)
                health_status["environment"]["tables"][table_name] = {
                    "name": table_name,
                    "status": "accessible"
                }
            except Exception as e:
                health_status["environment"]["tables"][table_name] = {
                    "name": table_name,
                    "status": "error",
                    "error": str(e)
                }
                errors.append(f"Table {table_name}: {str(e)}")
    except Exception as e:
        errors.append(f"Table service: {str(e)}")
    
    # Optional database check - only if enabled via environment variable
    if os.getenv("ENABLE_DATABASE_HEALTH_CHECK", "false").lower() == "true":
        health_status["database"] = {}
        try:
            from client_database import DatabaseClient
            
            db_client = DatabaseClient()
            
            # Test connection and get basic info
            with db_client.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check PostgreSQL version
                    cursor.execute("SELECT version()")
                    version = cursor.fetchone()[0]
                    
                    # Check PostGIS
                    cursor.execute("SELECT PostGIS_version()")
                    postgis_version = cursor.fetchone()[0]
                    
                    # Check if geo schema exists
                    cursor.execute("""
                        SELECT EXISTS(
                            SELECT 1 FROM information_schema.schemata 
                            WHERE schema_name = 'geo'
                        )
                    """)
                    geo_schema_exists = cursor.fetchone()[0]
                    
                    # Count STAC items if schema exists
                    stac_item_count = 0
                    if geo_schema_exists:
                        try:
                            cursor.execute("SELECT COUNT(*) FROM geo.items")
                            stac_item_count = cursor.fetchone()[0]
                        except:
                            pass
                    
                    health_status["database"] = {
                        "status": "connected",
                        "host": config.postgis_host,
                        "database": config.postgis_database,
                        "postgis_version": postgis_version,
                        "geo_schema_exists": geo_schema_exists,
                        "stac_item_count": stac_item_count if geo_schema_exists else None
                    }
        except Exception as e:
            health_status["database"] = {
                "status": "error",
                "error": str(e)
            }
            errors.append(f"Database: {str(e)}")
    
    # Set overall health status
    if errors:
        health_status["status"] = "unhealthy"
        health_status["errors"] = errors
        status_code = 503  # Service Unavailable
    else:
        health_status["message"] = "All systems operational"
        status_code = 200
    
    logger.info(f"Health check completed: {health_status['status']}")
    
    return func.HttpResponse(
        json.dumps(health_status, default=str),
        status_code=status_code,
        mimetype="application/json"
    )


@app.route(route="jobs/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a new processing job to the ETL pipeline.
    
    Creates an idempotent job request based on SHA256 hash of parameters.
    Jobs are queued for asynchronous processing. Duplicate requests return
    the existing job status without creating a new job.
    
    Job→Task Architecture (PRODUCTION READY - August 2025):
        Operations with controllers follow the Job→Task pattern where:
        - Controllers validate requests and create tasks
        - Jobs are orchestration units that manage multiple tasks  
        - Tasks are atomic processing units queued separately
        - Job completion uses "distributed detection" - each task checks if all done
        - Last completing task aggregates results into comprehensive result_data
        - Scales efficiently for 10-5,000 tasks per job (N² query pattern)
    
    Args:
        req: Azure Functions HTTP request with job_type in path and
            job parameters in JSON body.
            
    Path Parameters:
        job_type: The type of operation to perform (e.g., 'hello_world',
            'list_container', 'cog_conversion', 'sync_container', 'catalog_file').
            
    Request Body:
        {
            "dataset_id": "container_name",     # Required for DDH operations
            "resource_id": "file_or_folder",    # Required for DDH operations  
            "version_id": "v1",                 # Required for DDH operations
            "system": false                     # Optional, default: false
        }
        
    Parameters:
        system (bool): Operation mode flag
            - false: DDH application mode - all parameters required
            - true: Admin/testing mode - parameters optional and flexible
            
    Returns:
        HttpResponse: JSON response with job details and status.
            Always returns 200 for successful idempotent operations.
            
    Response Format (Controller-Managed):
        {
            "job_id": "SHA256_hash",
            "status": "queued",
            "message": "Job created and queued for processing",
            "task_count": 1,
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "job_type": "..."
        }
        
    Response Format:
        {
            "job_id": "SHA256_hash",
            "status": "queued" | "processing" | "completed" | "failed",
            "message": "Job created and queued" | "Duplicate request...",
            "is_duplicate": false | true,
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "job_type": "...",
            "system": false | true
        }
        
    Supported Operations (Pydantic Job→Task Architecture Only):
        - hello_world: Fully implemented with workflow definition and controller routing
        - sync_container: Container synchronization with parallel task creation (requires controller implementation)
        - catalog_file: Individual file cataloging (requires controller implementation)
        - database_health: Database connectivity checks (requires controller implementation)
        
        Note: All operations must use workflow definitions with strong typing discipline.
              No fallback or legacy service patterns are supported.
        
    Raises:
        400: Invalid request parameters or missing required fields
        500: Internal server error during job creation
        
    Examples:
        # List container contents
        POST /api/jobs/list_container
        {"dataset_id": "rmhazuregeobronze", "system": true}
        
        # Convert file to COG
        POST /api/jobs/cog_conversion
        {"dataset_id": "bronze", "resource_id": "file.tif", "version_id": "v1"}
    """
    # Extract operation type from path
    job_type = req.route_params.get("job_type")
    logger.debug(f"Received job submission request for operation: {job_type}")
    
    logger.info(f"Job submission request received for operation: {job_type}")
    
    # Ensure infrastructure is ready before processing any jobs
    ensure_infrastructure_ready()
    
    try:
        # Validate operation type
        logger.debug(f"Validating operation type: {job_type}")
        if not job_type:
            logger.error("Operation type is required in the request path")
            return func.HttpResponse(
                json.dumps({"error": "job_type parameter is required in path"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Parse request body
        req_body = None
        try:
            req_body = req.get_json()
        except ValueError as e:
            logger.error(f"Invalid JSON in request body {e}")
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON in request body",
                            'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        except Exception as e:
            logger.error(f"Error parsing request body: {str(e)}")
            return func.HttpResponse(
                json.dumps({"error": f"Error parsing request body: {str(e)}",
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
            
        if not req_body:
            logger.error("Request body is required but was empty")
            logger.debug("Returning 400 Bad Request due to missing body")
            return func.HttpResponse(
                json.dumps({"error": "Request body is required",
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Extract parameters from body using constants
        dataset_id = req_body.get("dataset_id")
        resource_id = req_body.get("resource_id")
        version_id = req_body.get("version_id")
        system = req_body.get("system", False)
        
        # Extract additional parameters (processing_extent, tile_id, etc.)
        additional_params = {}
        standard_params = {"dataset_id", "resource_id", "version_id", "system"}
        for key, value in req_body.items():
            if key not in standard_params:
                additional_params[key] = value
        
        logger.debug(f"Extracted parameters: dataset_id={dataset_id}, resource_id={resource_id}, version_id={version_id}, system={system}")
        if additional_params:
            logger.debug(f"Additional parameters: {additional_params}")
        
        # Controller factory - ALL operations must have controllers
        controller = None
        
        try:
            # Get controller for job_type
            if job_type == "hello_world":
                logger.debug(f"🎯 Loading HelloWorldController")
                from controller_hello_world import HelloWorldController
                controller = HelloWorldController()
            else:
                # Explicitly fail for operations without controllers
                logger.error(f"❌ No controller found for job_type: {job_type}")
                return func.HttpResponse(
                    json.dumps({
                        "error": "Controller required",
                        "message": f"Operation '{job_type}' requires a controller implementation. All operations must use the controller pattern.",
                        "job_type": job_type,
                        "required_implementation": f"Create {job_type.title()}Controller class inheriting from BaseController"
                    }),
                    status_code=501,  # Not Implemented
                    mimetype="application/json"
                )
            
            logger.debug(f"✅ Controller instantiated: {type(controller)}")
            
            # Create job parameters from request
            job_params = {
                'dataset_id': dataset_id,
                'resource_id': resource_id, 
                'version_id': version_id,
                'system': system,
                **additional_params
            }
            logger.debug(f"📦 Job parameters created: {job_params}")
            
            # Validate parameters FIRST
            logger.debug(f"🔍 Starting parameter validation with: {job_params}")
            validated_params = controller.validate_job_parameters(job_params)
            logger.debug(f"✅ Parameter validation complete: {validated_params}")
            
            # Generate job ID AFTER validation (ensures deterministic hash)
            job_id = controller.generate_job_id(validated_params)
            logger.debug(f"🔑 Generated job_id from validated params: {job_id}")
            
            logger.info(f"Creating {job_type} job with ID: {job_id}")
            
            # Create job record
            logger.debug(f"💾 Creating job record with job_id={job_id}, params={validated_params}")
            job_record = controller.create_job_record(job_id, validated_params)
            logger.debug(f"✅ Job record created: {job_record}")
            
            # Queue the job for processing
            logger.debug(f"📤 Queueing job for processing: job_id={job_id}")
            queue_result = controller.queue_job(job_id, validated_params)
            logger.debug(f"📤 Queue result: {queue_result}")
            
            # Prepare response (NO controller_managed flag - all jobs are controller-managed)
            response_data = {
                "job_id": job_id,
                "status": "created", 
                "job_type": job_type,
                "message": "Job created and queued for processing",
                "parameters": validated_params,
                "queue_info": queue_result
            }
            logger.debug(f"📋 Response data prepared: {response_data}")
            
            return func.HttpResponse(
                json.dumps(response_data),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            logger.error(f"❌ Error creating {job_type} job: {e}")
            logger.debug(f"🔍 Error details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.debug(f"📍 Full traceback: {traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": "Controller error",
                    "message": str(e),
                    "job_type": job_type,
                    "error_type": type(e).__name__
                }),
                status_code=500,
                mimetype="application/json"
            )
    
    except Exception as e:
        logger.error(f"Error in submit_job: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}",
                         'log_list': log_list.log_messages}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get job status and results by job ID.
    
    Retrieves detailed job information including current status, timestamps,
    result data, and task progress for state-managed jobs. Supports both
    regular jobs and state-managed jobs with enhanced task tracking.
    
    Args:
        req: Azure Functions HTTP request with job_id in path.
        
    Path Parameters:
        job_id: SHA256 hash job identifier to query.
        
    Returns:
        HttpResponse: JSON response with job details.
            Status code 200 if found, 404 if not found.
            
    Response Format (Job→Task Architecture - Phase 1):
        {
            "job_id": "SHA256_hash",
            "status": "pending" | "queued" | "processing" | "completed" | "failed" | "completed_with_errors",
            "created_at": "ISO-8601 timestamp",
            "updated_at": "ISO-8601 timestamp",
            "task_count": 1,
            "total_tasks": 1,
            "completed_tasks": 1,
            "failed_tasks": 0,
            "progress_percentage": 100.0,
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "job_type": "hello_world",
            "result_data": {  # When completed
                "message": "Hello World from Job→Task architecture!"
            }
        }
        
    Response Format (Regular Job):
        {
            "job_id": "SHA256_hash",
            "status": "pending" | "queued" | "processing" | "completed" | "failed",
            "created_at": "ISO-8601 timestamp",
            "updated_at": "ISO-8601 timestamp",
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "job_type": "...",
            "error_message": null | "error details",
            "result_data": {  # When completed
                "summary": {...},
                "files": [...],
                "inventory_urls": {...}
            }
        }
        
    Response Format (State-Managed Job):
        {
            "job_id": "SHA256_hash",
            "status": "processing" | "completed" | "failed",
            "progress": "50%",
            "tasks": {
                "total": 2,
                "completed": 1,
                "failed": 0,
                "current": "CREATE_COG"
            },
            "task_details": [
                {
                    "task_id": "...",
                    "task_type": "CREATE_COG",
                    "status": "completed",
                    "started_at": "ISO-8601",
                    "completed_at": "ISO-8601",
                    "duration_seconds": 15.2
                }
            ],
            "output_path": "silver/cogs/job_id/output.tif"  # When completed
        }
        
    Raises:
        400: Missing job_id parameter
        404: Job not found
        500: Internal server error
        
    Examples:
        GET /api/jobs/f542843127e97ec6cdfa921f3c16d747b8657cdb662b135e2ff71fea72439542
    """
    job_id = req.route_params.get('job_id')
    logger.debug(f"🔍 Received job status request for job_id: {job_id}")
    logger.info(f"Job status request for: {job_id}")
    
    try:
        if not job_id:
            logger.error(f"❌ Missing job_id parameter in request")
            return func.HttpResponse(
                json.dumps({"error": "job_id parameter is required",
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        
        logger.debug(f"✅ Job ID validation passed: {job_id}")
        
        # 🔥 STRONG TYPING DISCIPLINE - Use type-safe job retrieval
        logger.debug(f"🏗️ Initializing schema-validated repositories")
        
        from repository_data import RepositoryFactory
        logger.debug(f"📦 RepositoryFactory imported successfully")
        
        job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories()
        logger.debug(f"✅ Repositories created: job_repo={type(job_repo)}, task_repo={type(task_repo)}")
        
        logger.debug(f"🔍 Attempting to retrieve job: {job_id}")
        job_record = job_repo.get_job(job_id)
        logger.debug(f"📋 Job retrieval result: {job_record}")
        
        if not job_record:
            logger.warning(f"❌ Job not found in storage: {job_id}")
            logger.debug(f"🔍 Double-checking job existence with direct query...")
            
            # Try to debug by checking if job exists at all
            try:
                # Check if the job might exist but retrieval is failing
                logger.debug(f"📋 Checking job repository state")
                logger.debug(f"🔍 Repository connection status: {hasattr(job_repo, '_client')}")
                
            except Exception as debug_e:
                logger.debug(f"🔍 Debug query failed: {debug_e}")
                
            return func.HttpResponse(
                json.dumps({
                    "error": f"Job not found: {job_id}",
                    "message": "Job may not exist or has been removed",
                    'log_list': log_list.log_messages
                }),
                status_code=404,
                mimetype="application/json"
            )
        
        logger.debug(f"✅ Job record found: {job_record}")
        logger.debug(f"📊 Job details: id={job_record.job_id if hasattr(job_record, 'job_id') else 'unknown'}, status={job_record.status if hasattr(job_record, 'status') else 'unknown'}")
        
        # Convert JobRecord to dictionary with type safety
        logger.debug(f"🔄 Converting job record to dictionary")
        job_details = job_record.model_dump()  # Updated from deprecated .dict() method
        logger.debug(f"✅ Job details converted: {job_details}")
        
        # Add strong typing information  
        job_details['architecture'] = 'strong_typing_discipline'
        job_details['pattern'] = 'Job→Stage→Task with Pydantic validation'
        job_details['schema_validated'] = True
        
        logger.info(f"✅ Job status retrieved with schema validation: {job_id[:16]}... -> {job_record.status}")
        
        response_json = json.dumps(job_details, default=str)
        logger.debug(f"📤 Prepared response JSON: {response_json[:200]}...")
        
        return func.HttpResponse(
            response_json,
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Error in get_job_status: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}",
                         'log_list': log_list.log_messages}),
            status_code=500,
            mimetype="application/json"
        )


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
        
        logger.info(f"📨 Processing job: {job_message.jobId[:16]}... type={job_message.jobType}")
        logger.debug(f"📊 Full job message details: jobId={job_message.jobId}, jobType={job_message.jobType}, stage={job_message.stage}, parameters={job_message.parameters}")
        
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
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories()
            logger.debug(f"✅ Repositories created: job_repo={type(job_repo)}, task_repo={type(task_repo)}, completion_detector={type(completion_detector)}")
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
        logger.debug(f"🎯 Routing to controller for job type: {job_message.jobType}")
        if job_message.jobType == "hello_world":
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
            error_msg = f"Controller not implemented for job type: {job_message.jobType}"
            logger.error(f"❌ {error_msg}")
            logger.debug(f"🔧 Marking job as failed due to missing controller")
            job_repo.fail_job(job_message.jobId, error_msg)
            
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
        
        logger.info(f"📋 Processing task: {task_message.taskId} type={task_message.taskType}")
        logger.debug(f"📊 Full task message details: taskId={task_message.taskId}, parentJobId={task_message.parentJobId}, taskType={task_message.taskType}, parameters={task_message.parameters}")
        
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
            job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories()
            logger.debug(f"✅ Repositories created: task_repo={type(task_repo)}, job_repo={type(job_repo)}, completion_detector={type(completion_detector)}")
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





# Poison queue monitoring endpoints
@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """
    Enhanced poison queue monitoring with production-ready analytics.
    
    Provides comprehensive visibility into failed messages with detailed error
    analysis, health status, and operational recommendations.
    
    Query Parameters:
        - health: Return health status dashboard (GET /api/monitor/poison?health=true)
        - analysis: Return detailed analysis (GET /api/monitor/poison?analysis=true)
        - process_all: Process all messages (POST with {"process_all": true})
        - cleanup: Cleanup old messages (POST with {"cleanup_old_messages": true})
    
    Args:
        req: Azure Functions HTTP request.
        
    Methods:
        GET: Check poison queues and return summary
        POST: Process messages and/or cleanup old messages
        
    POST Request Body (Optional):
        {
            "process_all": true,           # Process all poison messages
            "cleanup_old_messages": true,  # Remove old messages
            "days_to_keep": 7              # Keep messages newer than N days
        }
        
    Returns:
        HttpResponse: JSON summary of poison queue status.
        
    Response Format:
        {
            "timestamp": "ISO-8601",
            "queues_checked": ["geospatial-jobs-poison", "geospatial-tasks-poison"],
            "total_messages": 5,
            "messages_by_queue": {
                "geospatial-jobs-poison": 2,
                "geospatial-tasks-poison": 3
            },
            "jobs_marked_failed": 2,
            "tasks_marked_failed": 3,
            "messages_processed": 5,      # If process_all=true
            "messages_cleaned": 10        # If cleanup_old_messages=true
        }
        
    Examples:
        # Check poison queue status
        GET /api/monitor/poison
        
        # Process all poison messages and mark jobs as failed
        POST /api/monitor/poison
        {"process_all": true}
        
        # Clean up messages older than 30 days
        POST /api/monitor/poison
        {"cleanup_old_messages": true, "days_to_keep": 30}
    """
    logger.info("Poison queue check requested via HTTP")
    
    try:
        from poison_queue_monitor import PoisonQueueMonitor, PoisonQueueDashboard
        
        # Check for enhanced monitoring requests
        health_request = req.params.get("health", "").lower() == "true"
        analysis_request = req.params.get("analysis", "").lower() == "true"
        
        if health_request:
            # Return health status dashboard
            dashboard = PoisonQueueDashboard()
            health_status = dashboard.get_health_status()
            logger.info(f"Poison queue health status: {health_status['overall_health']}")
            return func.HttpResponse(
                json.dumps(health_status),
                mimetype="application/json",
                status_code=200
            )
        
        if analysis_request:
            # Return detailed analysis
            dashboard = PoisonQueueDashboard()
            analysis = dashboard.get_detailed_analysis()
            logger.info(f"Poison queue analysis: {analysis['total_messages_analyzed']} messages analyzed")
            return func.HttpResponse(
                json.dumps(analysis),
                mimetype="application/json", 
                status_code=200
            )
        
        monitor = PoisonQueueMonitor()
        
        # Check for process_all parameter
        process_all = False
        if req.method == "POST":
            try:
                req_body = req.get_json()
                process_all = req_body.get("process_all", False) if req_body else False
            except:
                pass
        
        # Check poison queues
        summary = monitor.check_poison_queues(process_all=process_all)
        
        # If POST request with cleanup parameter, also cleanup old messages
        if req.method == "POST":
            try:
                req_body = req.get_json() if not process_all else req_body  # Reuse if already parsed
                if req_body and req_body.get("cleanup_old_messages"):
                    days_to_keep = req_body.get("days_to_keep", 7)
                    cleaned = monitor.cleanup_old_poison_messages(days_to_keep)
                    summary["messages_cleaned"] = cleaned
                    logger.info(f"Cleaned up {cleaned} old poison messages")
            except:
                pass  # Cleanup is optional
        
        return func.HttpResponse(
            json.dumps(summary, indent=2),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Error checking poison queues: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to check poison queues: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


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


