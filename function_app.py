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
from config import Config

# Initialize function app
app = func.FunctionApp()

# Repository will be initialized lazily when needed

# Queue client for job submission
def get_queue_client():
    # Try managed identity first, fallback to connection string for local dev
    if Config.STORAGE_ACCOUNT_NAME:
        # Use managed identity in production
        account_url = Config.get_storage_account_url('queue')
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
    else:
        # Fallback to connection string for local development
        Config.validate_storage_config()
        queue_service = QueueServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
    
    queue_name = "job-processing"
    
    # Ensure queue exists
    try:
        queue_service.create_queue(queue_name)
    except Exception:
        pass  # Queue already exists
    
    return queue_service.get_queue_client(queue_name)


@app.route(route="jobs", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a new processing job
    POST /api/jobs
    Body: {"dataset_id": "...", "resource_id": "...", "version_id": "...", "operation_type": "..."}
    Returns: {"job_id": "...", "status": "queued"}
    """
    logging.info("Job submission request received")
    
    try:
        # Parse request body
        try:
            req_body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON in request body"}),
                status_code=400,
                mimetype="application/json"
            )
        
        if not req_body:
            return func.HttpResponse(
                json.dumps({"error": "Request body is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Extract parameters
        dataset_id = req_body.get('dataset_id')
        resource_id = req_body.get('resource_id')
        version_id = req_body.get('version_id')
        operation_type = req_body.get('operation_type')
        
        # Create job request
        job_request = JobRequest(dataset_id, resource_id, version_id, operation_type)
        
        # Validate parameters
        is_valid, error_msg = job_request.validate()
        if not is_valid:
            return func.HttpResponse(
                json.dumps({"error": error_msg}),
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
            queue_client.send_message(message_content)
            
            # Update status to queued
            job_repo.update_job_status(job_request.job_id, JobStatus.QUEUED)
            
            logging.info(f"New job created and queued: {job_request.job_id}")
            response_msg = "Job created and queued for processing"
        else:
            logging.info(f"Job already exists: {job_request.job_id}")
            response_msg = "Job already exists (idempotency)"
        
        return func.HttpResponse(
            json.dumps({
                "job_id": job_request.job_id,
                "status": "queued",
                "message": response_msg,
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id,
                "operation_type": operation_type
            }),
            status_code=200 if is_new_job else 200,  # Both success cases
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in submit_job: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="jobs/{job_id}", methods=["GET"])
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get job status by job ID
    GET /api/jobs/{job_id}
    Returns: {"job_id": "...", "status": "...", "created_at": "...", ...}
    """
    job_id = req.route_params.get('job_id')
    logging.info(f"Job status request for: {job_id}")
    
    try:
        if not job_id:
            return func.HttpResponse(
                json.dumps({"error": "job_id parameter is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get job details
        job_repo = JobRepository()
        job_details = job_repo.get_job_details(job_id)
        
        if not job_details:
            return func.HttpResponse(
                json.dumps({"error": f"Job not found: {job_id}"}),
                status_code=404,
                mimetype="application/json"
            )
        
        logging.info(f"Job status retrieved: {job_id} -> {job_details['status']}")
        
        return func.HttpResponse(
            json.dumps(job_details),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in get_job_status: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


@app.queue_trigger(arg_name="msg", queue_name="job-processing", connection="AzureWebJobsStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
    """
    Process jobs from the queue
    Triggered by messages in job-processing queue
    """
    try:
        # Parse message
        message_content = msg.get_body().decode('utf-8')
        job_data = json.loads(message_content)
        
        job_id = job_data['job_id']
        dataset_id = job_data['dataset_id']
        resource_id = job_data['resource_id']
        version_id = job_data['version_id']
        operation_type = job_data['operation_type']
        
        logging.info(f"Processing job from queue: {job_id}")
        
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
        
        logging.info(f"Job completed successfully: {job_id}")
        
    except Exception as e:
        logging.error(f"Error processing job: {str(e)}")
        
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
            logging.error(f"Failed to update job status after error: {update_error}")
        
        # Re-raise the exception so Azure Functions knows the processing failed
        raise


@app.route(route="jobs/{job_id}/process", methods=["POST"])
def manual_process_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually process a pending job (for debugging)
    POST /api/jobs/{job_id}/process
    """
    job_id = req.route_params.get('job_id')
    logging.info(f"Manual processing request for job: {job_id}")
    
    try:
        if not job_id:
            return func.HttpResponse(
                json.dumps({"error": "job_id parameter is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get job details
        job_repo = JobRepository()
        job_details = job_repo.get_job_details(job_id)
        
        if not job_details:
            return func.HttpResponse(
                json.dumps({"error": f"Job not found: {job_id}"}),
                status_code=404,
                mimetype="application/json"
            )
        
        current_status = job_details['status']
        logging.info(f"Job {job_id} current status: {current_status}")
        
        if current_status not in [JobStatus.PENDING, JobStatus.QUEUED]:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Job is not in pending/queued status (current: {current_status})",
                    "job_id": job_id,
                    "current_status": current_status
                }),
                status_code=400,
                mimetype="application/json"
            )
        
        # Update status to processing
        job_repo.update_job_status(job_id, JobStatus.PROCESSING)
        logging.info(f"Updated job {job_id} to PROCESSING")
        
        # Get service and process
        service = ServiceFactory.get_service(job_details['operation_type'])
        result = service.process(
            job_id=job_id,
            dataset_id=job_details['dataset_id'],
            resource_id=job_details['resource_id'], 
            version_id=job_details['version_id'],
            operation_type=job_details['operation_type']
        )
        
        # Update status to completed
        job_repo.update_job_status(job_id, JobStatus.COMPLETED, result_data=result)
        logging.info(f"Job {job_id} completed successfully")
        
        return func.HttpResponse(
            json.dumps({
                "message": "Job processed successfully",
                "job_id": job_id,
                "previous_status": current_status,
                "new_status": JobStatus.COMPLETED,
                "result": result
            }),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in manual_process_job: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="storage/containers/{container_name}/list", methods=["GET"])
def list_container_contents(req: func.HttpRequest) -> func.HttpResponse:
    """
    List contents of a storage container
    GET /api/storage/containers/{container_name}/list
    Returns: {"container_name": "...", "blob_count": N, "blobs": [...]}
    """
    container_name = req.route_params.get('container_name')
    logging.info(f"Container listing request for: {container_name}")
    
    try:
        if not container_name:
            return func.HttpResponse(
                json.dumps({"error": "container_name parameter is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get storage repository and list contents
        storage_repo = StorageRepository()
        result = storage_repo.list_container_contents(container_name)
        
        logging.info(f"Listed {result['blob_count']} blobs in container {container_name}")
        
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in list_container_contents: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="storage/bronze/list", methods=["GET"])
def list_bronze_container(req: func.HttpRequest) -> func.HttpResponse:
    """
    List contents of the bronze container (convenience endpoint)
    GET /api/storage/bronze/list
    Returns: {"container_name": "bronze", "blob_count": N, "blobs": [...]}
    """
    logging.info("Bronze container listing request")
    
    try:
        # Get storage repository and list bronze container contents
        storage_repo = StorageRepository()
        result = storage_repo.list_container_contents()  # Uses default bronze container
        
        logging.info(f"Listed {result['blob_count']} blobs in bronze container")
        
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in list_bronze_container: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )