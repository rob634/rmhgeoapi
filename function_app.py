"""
Azure Functions App for Geospatial ETL Pipeline.

This module serves as the entry point for the Azure Functions-based geospatial
ETL pipeline. It provides HTTP endpoints for job submission and status checking,
queue-based asynchronous processing, and comprehensive health monitoring.

Architecture:
    HTTP API → Queue → Processing Service → Storage/Database
             ↓                             ↓
        Job Tracking                  STAC Catalog
       (Table Storage)               (PostgreSQL/PostGIS)

Key Features:
    - Idempotent job processing with SHA256-based deduplication
    - Queue-based async processing with poison queue monitoring
    - Managed identity authentication with user delegation SAS
    - Support for files up to 20GB with smart metadata extraction
    - Comprehensive STAC cataloging with PostGIS integration
    - State management system for complex raster workflows

Endpoints:
    GET  /api/health - System health check with component status
    POST /api/jobs/{operation_type} - Submit processing job
    GET  /api/jobs/{job_id} - Get job status and results
    GET  /api/monitor/poison - Check poison queue status
    POST /api/monitor/poison - Process poison messages

Supported Operations:
    - list_container: List and inventory container contents
    - sync_container: Sync container to STAC catalog
    - catalog_file: Catalog individual file to STAC
    - validate_raster: Validate raster file integrity
    - cog_conversion: Convert raster to Cloud Optimized GeoTIFF
    - simple_cog: State-managed COG conversion (<4GB files)
    - database_health: Check database connectivity and status
    - setup_stac_geo_schema: Initialize STAC tables in PostgreSQL

Environment Variables:
    STORAGE_ACCOUNT_NAME: Azure storage account name
    AzureWebJobsStorage: Connection string for Functions runtime
    ENABLE_DATABASE_CHECK: Enable PostgreSQL health checks (optional)
    POSTGIS_HOST: PostgreSQL host for STAC catalog
    POSTGIS_DATABASE: PostgreSQL database name
    POSTGIS_USER: PostgreSQL username
    POSTGIS_PASSWORD: PostgreSQL password

Author: Azure Geospatial ETL Team
Version: 2.0.0
Last Updated: August 2025
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

from models import JobRequest, JobStatus
from repositories import JobRepository, StorageRepository
from services import ServiceFactory
from config import Config, APIParams, Defaults, AzureStorage
from logger_setup import logger, log_list, log_job_stage, log_queue_operation, log_service_processing
from state_integration import StateIntegration  # NEW: State management integration

# Use centralized logger (imported from logger_setup)

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Repository will be initialized lazily when needed

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
    # Check if we have the storage account name (extracted from AzureWebJobsStorage settings)
    if not Config.STORAGE_ACCOUNT_NAME:
        raise ValueError("Could not determine storage account name from AzureWebJobsStorage settings")
    
    # Use the same storage account as AzureWebJobsStorage
    account_url = Config.get_storage_account_url('queue')
    
    # Use DefaultAzureCredential which works with managed identity in Azure
    queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
    
    queue_name = AzureStorage.JOB_PROCESSING_QUEUE
    
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
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "storage_account": Config.STORAGE_ACCOUNT_NAME,
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
        
        account_url = Config.get_storage_account_url('queue')
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        
        # Check geospatial-jobs queue
        for queue_name in ["geospatial-jobs", "geospatial-tasks"]:
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
        
        account_url = Config.get_storage_account_url('table')
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
            from database_client import DatabaseClient
            
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
                        "host": Config.POSTGIS_HOST,
                        "database": Config.POSTGIS_DATABASE,
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


@app.route(route="jobs/{operation_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a new processing job to the ETL pipeline.
    
    Creates an idempotent job request based on SHA256 hash of parameters.
    Jobs are queued for asynchronous processing. Duplicate requests return
    the existing job status without creating a new job.
    
    Args:
        req: Azure Functions HTTP request with operation_type in path and
            job parameters in JSON body.
            
    Path Parameters:
        operation_type: The type of operation to perform (e.g., 'list_container',
            'cog_conversion', 'sync_container', 'catalog_file').
            
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
            
    Response Format:
        {
            "job_id": "SHA256_hash",
            "status": "queued" | "processing" | "completed" | "failed",
            "message": "Job created and queued" | "Duplicate request...",
            "is_duplicate": false | true,
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "operation_type": "...",
            "system": false | true
        }
        
    Supported Operations:
        - list_container: List and inventory container contents
        - sync_container: Sync entire container to STAC catalog  
        - catalog_file: Catalog individual file to STAC
        - validate_raster: Validate raster file integrity
        - cog_conversion: Convert raster to Cloud Optimized GeoTIFF
        - simple_cog: State-managed COG conversion for files <4GB
        - database_health: Check database connectivity
        - setup_stac_geo_schema: Initialize STAC tables
        
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
    operation_type = req.route_params.get(APIParams.OPERATION_TYPE)
    logger.debug(f"Received job submission request for operation: {operation_type}")
    
    logger.info(f"Job submission request received for operation: {operation_type}")
    
    try:
        # Validate operation type
        logger.debug(f"Validating operation type: {operation_type}")
        if not operation_type:
            logger.error("Operation type is required in the request path")
            return func.HttpResponse(
                json.dumps({"error": f"{APIParams.OPERATION_TYPE} parameter is required in path"}),
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
        dataset_id = req_body.get(APIParams.DATASET_ID)
        resource_id = req_body.get(APIParams.RESOURCE_ID)
        version_id = req_body.get(APIParams.VERSION_ID)
        system = req_body.get(APIParams.SYSTEM, Defaults.SYSTEM_FLAG)
        
        logger.debug(f"Extracted parameters: dataset_id={dataset_id}, resource_id={resource_id}, version_id={version_id}, system={system}")
        
        # Check if this operation uses state management (POC: simple_cog)
        try:
            state_integration = StateIntegration()
            if state_integration.is_state_managed_job(operation_type):
                logger.info(f"Using state management for operation: {operation_type}")
                
                # Handle state-managed operations
                if operation_type in ['simple_cog', 'cog_conversion_v2']:
                    try:
                        result = state_integration.submit_simple_cog_job(
                            dataset_id=dataset_id,
                            resource_id=resource_id,
                            version_id=version_id
                        )
                        
                        return func.HttpResponse(
                            json.dumps({
                                "job_id": result['job_id'],
                                "status": result['status'],
                                "message": result['message'],
                                "state_managed": True,
                                "log_list": log_list.log_messages
                            }),
                            status_code=200,
                            mimetype="application/json"
                        )
                    except Exception as e:
                        logger.error(f"State-managed job submission failed: {e}")
                        return func.HttpResponse(
                            json.dumps({
                                "error": str(e),
                                "state_managed": True,
                                "log_list": log_list.log_messages
                            }),
                            status_code=500,
                            mimetype="application/json"
                        )
        except Exception as e:
            logger.debug(f"State management check failed (non-fatal): {e}")
            # Continue without state management
        
        # Continue with existing job processing for non-state-managed operations
        # Create job request
        job_request = JobRequest(dataset_id, resource_id, version_id, operation_type, system)
        
        # Validate parameters
        is_valid, error_msg = job_request.validate()
        if not is_valid:
            return func.HttpResponse(
                json.dumps({"error": error_msg,
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Save job (idempotency check inside)
        job_repo = JobRepository()
        is_new_job = job_repo.save_job(job_request)
        
        if is_new_job:
            # Add to processing queue
            queue_client = get_queue_client()
            message_content = json.dumps(job_request.to_dict())
            logger.debug(f"📤 Sending message to queue: {message_content}")
            
            # Send message with explicit Base64 encoding since host.json expects it
            import base64
            encoded_message = base64.b64encode(message_content.encode('utf-8')).decode('ascii')
            queue_client.send_message(encoded_message)
            
            logger.debug(f"✅ Message sent to queue successfully for job: {job_request.job_id}")
            
            # Update status to queued
            job_repo.update_job_status(job_request.job_id, JobStatus.QUEUED)
            
            logger.info(f"New job created and queued: {job_request.job_id}")
            response_msg = "Job created and queued for processing"
            actual_status = "queued"
            is_duplicate = False
        else:
            # Get details of existing job to provide specific duplicate information
            existing_job = job_repo.get_job_details(job_request.job_id)
            current_status = existing_job.get('status', 'unknown') if existing_job else 'unknown'
            actual_status = current_status
            is_duplicate = True
            
            # Provide specific message based on current job state
            if current_status == JobStatus.COMPLETED:
                response_msg = "Duplicate request - job already completed successfully"
            elif current_status == JobStatus.FAILED:
                response_msg = "Duplicate request - job previously failed"
            elif current_status == JobStatus.PROCESSING:
                response_msg = "Duplicate request - job currently processing"
            elif current_status == JobStatus.QUEUED:
                response_msg = "Duplicate request - job already queued for processing"
            elif current_status == JobStatus.PENDING:
                response_msg = "Duplicate request - job pending in queue"
            else:
                response_msg = f"Duplicate request - job in {current_status} state"
            
            logger.info(f"Duplicate job request: {job_request.job_id} (status: {current_status})")
        
        return func.HttpResponse(
            json.dumps({
                APIParams.JOB_ID: job_request.job_id,
                APIParams.STATUS: actual_status,
                APIParams.MESSAGE: response_msg,
                APIParams.IS_DUPLICATE: is_duplicate,
                APIParams.DATASET_ID: dataset_id,
                APIParams.RESOURCE_ID: resource_id,
                APIParams.VERSION_ID: version_id,
                APIParams.OPERATION_TYPE: operation_type,
                APIParams.SYSTEM: system,
                "log_list": log_list.log_messages
            }),
            status_code=200,  # Always 200 for successful idempotent responses
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
            
    Response Format (Regular Job):
        {
            "job_id": "SHA256_hash",
            "status": "pending" | "queued" | "processing" | "completed" | "failed",
            "created_at": "ISO-8601 timestamp",
            "updated_at": "ISO-8601 timestamp",
            "dataset_id": "...",
            "resource_id": "...",
            "version_id": "...",
            "operation_type": "...",
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
    logger.debug(f"Received job status request for job_id: {job_id}")
    logger.info(f"Job status request for: {job_id}")
    
    try:
        if not job_id:
            return func.HttpResponse(
                json.dumps({"error": "job_id parameter is required",
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        
        # First check if this is a state-managed job
        state_integration = StateIntegration()
        state_job_details = state_integration.get_job_status_with_state(job_id)
        
        if state_job_details:
            # This is a state-managed job, return enhanced status
            logger.info(f"State-managed job status retrieved: {job_id} -> {state_job_details['status']}")
            return func.HttpResponse(
                json.dumps(state_job_details),
                status_code=200,
                mimetype="application/json"
            )
        
        # Fall back to regular job repository
        job_repo = JobRepository()
        job_details = job_repo.get_job_details(job_id)
        
        if not job_details:
            return func.HttpResponse(
                json.dumps({"error": f"Job not found: {job_id}",
                             'log_list': log_list.log_messages}),
                status_code=404,
                mimetype="application/json"
            )
        
        logger.info(f"Job status retrieved: {job_id} -> {job_details['status']}")
        
        return func.HttpResponse(
            json.dumps(job_details),
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
    Process jobs from the geospatial-jobs queue.
    
    Queue trigger function that processes job messages asynchronously.
    Handles message decoding, job validation, service routing, and status
    updates. Messages that fail after 5 attempts are moved to poison queue.
    
    Args:
        msg: Azure Functions queue message containing job data.
            Message is base64-encoded JSON with job parameters.
            
    Queue Message Format:
        {
            "job_id": "SHA256_hash",
            "dataset_id": "container_name",
            "resource_id": "file_or_folder",
            "version_id": "v1",
            "operation_type": "list_container",
            "system": false,
            "created_at": "ISO-8601 timestamp"
        }
        
    Processing Flow:
        1. Decode base64 message (handled by runtime)
        2. Parse JSON job data
        3. Validate required parameters
        4. Update job status to 'processing'
        5. Route to appropriate service based on operation_type
        6. Process job and capture results
        7. Update job status with results or error
        
    Error Handling:
        - Invalid JSON: Message rejected, sent to poison queue
        - Missing parameters: Job marked as failed
        - Service errors: Job marked as failed with error message
        - After 5 attempts: Message moved to poison queue automatically
        
    Note:
        - Base64 encoding/decoding handled by Azure Functions runtime
        - Messages are automatically retried on failure
        - Poison queue monitoring handled by separate timer trigger
    """
    logger.debug("🔄 QUEUE TRIGGER FIRED! Starting job processing")
    try:

        logger.debug(f"Message ID: {msg.id}, Dequeue count: {msg.dequeue_count}")
        
        # Parse message - Azure Functions handles base64 decoding when messageEncoding="base64"
        try:
            logger.debug("Loading message content from queue")
            
            # Get raw bytes from message
            message_bytes = msg.get_body()
            logger.debug(f"Received message bytes length: {len(message_bytes)}")
            
            # Try to decode as UTF-8 (Azure Functions should have already base64-decoded it)
            try:
                message_content = message_bytes.decode('utf-8')
                logger.debug(f"Successfully decoded message as UTF-8, length: {len(message_content)}")
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode message as UTF-8: {str(e)}")
                # Log first 100 bytes for debugging
                logger.error(f"First 100 bytes of message: {message_bytes[:100]}")
                raise
            
            if not message_content:
                logger.error("Received empty message content from queue")
                raise ValueError("Empty message content received")
                
            # Log first 200 chars of message for debugging (might be large)
            logger.debug(f"Message content preview: {message_content[:200]}...")
            
        except ValueError as e:
            logger.error(f"ValueError while decoding queue message: {str(e)}")
            raise 
        except Exception as e:
            logger.error(f"Unexpected error decoding queue message: {str(e)}")
            logger.error(f"Message type: {type(msg)}, Body type: {type(msg.get_body())}")
            raise 
        
        logger.debug(f"📨 Queue message received, attempting JSON parse")
        
        try:
            logger.debug("Parsing job data from message content")
            job_data = json.loads(message_content)
            logger.debug(f"Successfully parsed JSON, keys: {list(job_data.keys())}")
            logger.debug(f"Full job data: {job_data}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse job data as JSON: {str(e)}")
            logger.error(f"Invalid JSON content: {message_content[:500]}...")
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing job data: {str(e)}")
            raise
        
        logger.debug("Job data successfully parsed from queue message")
        
        job_id = job_data.get(APIParams.JOB_ID)
        if not job_id:
            logger.error("Missing job_id in queue message")
            raise ValueError("job_id is required in the queue message")
        logger.debug(f"Processing job with ID: {job_id}")
        
        operation_type = job_data.get(APIParams.OPERATION_TYPE)
        if not operation_type:
            logger.error("Missing operation_type in queue message")
            raise ValueError("operation_type is required in the queue message")
        
        dataset_id = job_data.get(APIParams.DATASET_ID)
        resource_id = job_data.get(APIParams.RESOURCE_ID)
        version_id = job_data.get(APIParams.VERSION_ID)
        
        system = job_data.get(APIParams.SYSTEM, Defaults.SYSTEM_FLAG)
        
        if not system:
            logger.debug("System flag is false, validating required parameters")
            if not dataset_id or not resource_id or not version_id:
                logger.error("Missing required parameters for DDH operation")
                raise ValueError(
                    f"dataset_id, resource_id, and version_id are required for DDH operations. "
                    f"Received: dataset_id={dataset_id}, resource_id={resource_id}, version_id={version_id}"
                )
            logger.debug("All required parameters for DDH operation are present")
            
        else:
            logger.debug("System flag is true, parameters are optional and used flexibly")
        
        try:
            log_queue_operation(job_id, "processing_start")
            log_job_stage(job_id, "queue_processing", "processing")
        except Exception as e:
            # Log the error but don't fail the job because of logging issues
            logger.warning(f"Could not log job processing start (non-fatal): {str(e)}")
        
        # Update status to processing
        job_repo = JobRepository()
        job_repo.update_job_status(job_id, JobStatus.PROCESSING)
        
        # Get appropriate service and process
        service = ServiceFactory.get_service(operation_type)
        result = service.process(job_id, dataset_id, resource_id, version_id, operation_type)
        
        # Update status to completed with results
        job_repo.update_job_status(
            job_id, 
            JobStatus.COMPLETED, 
            result_data=result
        )
        
        try:
            log_job_stage(job_id, "queue_processing", "completed")
            log_queue_operation(job_id, "processing_complete")
        except Exception as e:
            # Log the error but don't fail the job because of logging issues
            logger.warning(f"Could not log job completion (non-fatal): {str(e)}")
        
    except Exception as e:
        logger.error(f"Error processing job: {str(e)}")
        
        # Try to update job status to failed
        try:
            if 'job_id' in locals():
                job_repo = JobRepository()
                job_repo.update_job_status(
                    job_id, 
                    JobStatus.FAILED, 
                    error_message=str(e)
                )
        except Exception as update_error:
            logger.error(f"Failed to update job status after error: {update_error}")
        
        # Re-raise the exception so Azure Functions knows the processing failed
        raise


@app.queue_trigger(
        arg_name="msg",
        queue_name="geospatial-tasks",
        connection="AzureWebJobsStorage")
def process_task_queue(msg: func.QueueMessage) -> None:
    """
    Process individual tasks from the geospatial-tasks queue.
    
    Handles granular work items created by jobs, such as cataloging individual
    files to STAC or processing raster chunks. Tasks are typically created by
    fan-out operations like sync_container which creates one task per file.
    
    Args:
        msg: Azure Functions queue message containing task data.
            
    Task Message Format:
        {
            "task_id": "UUID",
            "parent_job_id": "SHA256_hash",  # Original job that created this task
            "operation": "catalog_file",
            "parameters": {
                "container": "rmhazuregeobronze",
                "blob_name": "file.tif",
                "collection_id": "bronze-assets"
            }
        }
        
    Supported Task Operations:
        - catalog_file: Add individual file to STAC catalog
        - process_chunk: Process a raster chunk (for large files)
        - validate_output: Validate processing output
        
    Processing Flow:
        1. Decode task message
        2. Extract task parameters
        3. Route to appropriate handler
        4. Update task status in table storage
        5. Report completion to parent job
        
    Error Handling:
        - Task failures don't fail the parent job
        - Failed tasks are logged and counted
        - After 5 attempts, moved to geospatial-tasks-poison queue
        
    Note:
        Tasks are fire-and-forget operations that report back to parent job
        upon completion but don't block job completion.
    """
    from repositories import TaskRepository
    task_repo = TaskRepository()
    
    try:
        # Log the trigger
        logger.debug("🔄 TASK QUEUE TRIGGER FIRED! Starting task processing")
        logger.debug(f"Message ID: {msg.id}, Dequeue count: {msg.dequeue_count}")
        
        # Parse the message
        logger.debug("Loading task message content from queue")
        message_content = msg.get_body().decode('utf-8')
        logger.debug(f"Task message received, attempting JSON parse")
        
        task_data = json.loads(message_content)
        logger.debug(f"Task data successfully parsed from queue message")
        
        # Check if this is a state-managed task
        if 'task_id' in task_data and 'task_type' in task_data:
            logger.info(f"Detected state-managed task: {task_data.get('task_id')}")
            logger.info(f"  Task type: {task_data.get('task_type')}")
            logger.info(f"  Job ID: {task_data.get('job_id')}")
            
            try:
                state_integration = StateIntegration()
                logger.info(f"StateIntegration created successfully")
                
                state_result = state_integration.process_state_managed_task(task_data)
                if state_result is not None:
                    # This was a state-managed task, it's been processed
                    logger.info(f"State-managed task processed successfully")
                    return
                else:
                    logger.warning(f"State-managed task returned None - may have failed to initialize")
            except Exception as e:
                logger.error(f"Error in state management task processing: {e}", exc_info=True)
                # This is definitely a state-managed task that failed
                logger.error(f"State-managed task {task_data.get('task_id')} failed to process")
                raise
        else:
            logger.debug(f"Not a state-managed task (no task_id/task_type)")
            # Continue with regular processing
        
        # Check if this is a chunk processing task
        if task_data.get('operation') in ['process_chunk', 'assemble_chunks']:
            # Handle chunk processing tasks
            logger.info(f"Processing chunk task: {task_data.get('operation')}")
            from raster_chunked_processor import ChunkedRasterProcessor
            processor = ChunkedRasterProcessor()
            
            job_id = task_data.get('job_id')
            if task_data['operation'] == 'process_chunk':
                chunk_id = task_data.get('chunk_id')
                result = processor.process_chunk(job_id, chunk_id)
                logger.info(f"Chunk {chunk_id} processed for job {job_id}")
            else:  # assemble_chunks
                result = processor.assemble_chunks(job_id)
                logger.info(f"Chunks assembled for job {job_id}")
            return
        
        # Regular task processing
        task_id = task_data.get('task_id')
        parent_job_id = task_data.get('parent_job_id')
        operation_type = task_data.get('operation_type')
        
        if not task_id:
            logger.error("No task_id found in queue message")
            raise ValueError("task_id is required in queue message")
        
        logger.debug(f"Processing task with ID: {task_id}")
        logger.info(f"TASK_OP task_id={task_id[:16]}... operation=processing_start queue=geospatial-tasks")
        
        # Update task status to processing
        task_repo.update_task_status(task_id, "processing")
        
        # Get the appropriate service based on operation type
        from services import ServiceFactory
        service = ServiceFactory.get_service(operation_type)
        
        # Process the task
        logger.info(f"TASK_STAGE task_id={task_id[:16]}... stage=service_processing operation={operation_type}")
        
        result = service.process(
            job_id=task_id,  # Pass task_id as job_id for compatibility
            dataset_id=task_data.get('dataset_id'),
            resource_id=task_data.get('resource_id'),
            version_id=task_data.get('version_id'),
            operation_type=operation_type
        )
        
        # Update task status to completed
        task_repo.update_task_status(task_id, "completed", result_data=result)
        
        logger.info(f"TASK_OP task_id={task_id[:16]}... operation=processing_complete queue=geospatial-tasks")
        logger.info(f"Task {task_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing task: {str(e)}")
        
        # Try to update task status to failed
        if 'task_id' in locals() and task_id:
            try:
                task_repo.update_task_status(task_id, "failed", error_message=str(e))
            except Exception as update_error:
                logger.error(f"Failed to update task status after error: {update_error}")
        
        # Re-raise the exception so Azure Functions knows the processing failed
        raise


@app.route(route="jobs/{job_id}/process", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def manual_process_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually process a pending job (for debugging)
    POST /api/jobs/{job_id}/process
    """
    job_id = req.route_params.get('job_id')
    logger.info(f"Manual processing request for job: {job_id}")
    
    try:
        if not job_id:
            return func.HttpResponse(
                json.dumps({"error": "job_id parameter is required",
                             'log_list': log_list.log_messages}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get job details
        job_repo = JobRepository()
        job_details = job_repo.get_job_details(job_id)
        
        if not job_details:
            return func.HttpResponse(
                json.dumps({"error": f"Job not found: {job_id}",
                             'log_list': log_list.log_messages}),
                status_code=404,
                mimetype="application/json"
            )
        
        current_status = job_details['status']
        logger.info(f"Job {job_id} current status: {current_status}")
        
        if current_status not in [JobStatus.PENDING, JobStatus.QUEUED]:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Job is not in pending/queued status (current: {current_status})",
                    "job_id": job_id,
                    "current_status": current_status,
                    'log_list': log_list.log_messages
                }),
                status_code=400,
                mimetype="application/json"
            )
        
        # Update status to processing
        job_repo.update_job_status(job_id, JobStatus.PROCESSING)
        logger.info(f"Updated job {job_id} to PROCESSING")
        
        # Get service and process
        service = ServiceFactory.get_service(job_details[APIParams.OPERATION_TYPE])
        result = service.process(
            job_id=job_id,
            dataset_id=job_details[APIParams.DATASET_ID],
            resource_id=job_details[APIParams.RESOURCE_ID], 
            version_id=job_details[APIParams.VERSION_ID],
            operation_type=job_details[APIParams.OPERATION_TYPE]
        )
        
        # Update status to completed
        job_repo.update_job_status(job_id, JobStatus.COMPLETED, result_data=result)
        logger.info(f"Job {job_id} completed successfully")
        
        return func.HttpResponse(
            json.dumps({
                "message": "Job processed successfully",
                "job_id": job_id,
                "previous_status": current_status,
                "new_status": JobStatus.COMPLETED,
                "result": result,
                "log_list": log_list.log_messages
            }),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Error in manual_process_job: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}",
                         'log_list': log_list.log_messages}),
            status_code=500,
            mimetype="application/json"
        )


# Diagnostic endpoint for state management (TEMPORARY)
@app.route(route="diagnose/state", methods=["GET"])
def diagnose_state(req: func.HttpRequest) -> func.HttpResponse:
    """Diagnostic endpoint for state management"""
    from diagnose_state import diagnose_state_management
    return diagnose_state_management(req)

# Poison queue monitoring endpoints
@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """
    Monitor and manage poison queue messages.
    
    Provides visibility into failed messages that have been moved to poison
    queues after exceeding retry limits. Can optionally process or clean up
    old poison messages.
    
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
        from poison_queue_monitor import PoisonQueueMonitor
        
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


