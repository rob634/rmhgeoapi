"""
Azure Functions App for Geospatial ETL Pipeline
MVP implementation with job submission, status checking, and queue processing
"""
import json
import logging

import azure.functions as func
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

from models import JobRequest, JobStatus
from repositories import JobRepository, StorageRepository
from services import ServiceFactory
from config import Config, APIParams, Defaults, AzureStorage
from logger_setup import logger, log_list, log_job_stage, log_queue_operation, log_service_processing

# Use centralized logger (imported from logger_setup)

# Initialize function app
app = func.FunctionApp()

# Repository will be initialized lazily when needed

# Queue client for job submission - always use managed identity
def get_queue_client():
    if not Config.STORAGE_ACCOUNT_NAME:
        raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
    
    # Always use managed identity in Azure Functions
    account_url = Config.get_storage_account_url('queue')
    queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
    
    queue_name = AzureStorage.JOB_PROCESSING_QUEUE
    
    # Ensure queue exists
    try:
        queue_service.create_queue(queue_name)
    except Exception:
        pass  # Queue already exists
    
    return queue_service.get_queue_client(queue_name)


@app.route(route="jobs/{operation_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a new processing job
    POST /api/jobs/{operation_type}
    Body: {"dataset_id": "...", "resource_id": "...", "version_id": "...", "system": false}
    Returns: {"job_id": "...", "status": "queued"}
    
    Parameters:
    - system: boolean (default: false)
      * false: DDH application requests - dataset_id/resource_id/version_id are mandatory
      * true: Admin/testing requests - parameters are optional and used flexibly
    
    Supported operation types:
    - hello_world: Basic test operation
    - list_container: List container contents with file details
    
    For DDH operations (system=false):
    - All ETL parameters (dataset_id, resource_id, version_id) are required
    
    For admin operations (system=true):
    - dataset_id: Used as container name for list_container
    - resource_id: Used as prefix filter (use "none" for no filter)
    - version_id: Optional, can be any value
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
            queue_client.send_message(message_content)
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
    Get job status by job ID
    GET /api/jobs/{job_id}
    Returns: {"job_id": "...", "status": "...", "created_at": "...", ...}
    """
    job_id = req.route_params.get('job_id')
    logger.info(f"Job status request for: {job_id}")
    
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


@app.queue_trigger(arg_name="msg", queue_name="geospatial-jobs", connection="QueueStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
    """
    Process jobs from the queue
    Triggered by messages in job-processing queue
    """
    try:
        logger.debug("🔄 QUEUE TRIGGER FIRED! Starting job processing")
        # Parse message
        try:
            logger.debug("Loading message content from queue")
            message_content = msg.get_body().decode('utf-8')
            logger.debug(f"Message content: {message_content}")
            if not message_content:
                logger.error("Received empty message content from queue")
                raise ValueError("Empty message content received")
        except ValueError as e:
            logger.error(f"ValueError failed to decode queue message: {str(e)}")
            raise 
        except Exception as e:
            logger.error(f"Failed to decode queue message: {str(e)}")
            raise 
        logger.debug(f"📨 Queue message received: {message_content}")
        
        try:
            logger.debug("Parsing job data from message content")
            job_data = json.loads(message_content)
            logger.debug(f"Parsed job data: {job_data}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse job data from message: {str(e)}")
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
            logger.error(f"Failed to log job processing start: {str(e)}")
            #raise
        
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
        
        log_job_stage(job_id, "queue_processing", "completed")
        log_queue_operation(job_id, "processing_complete")
        
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




