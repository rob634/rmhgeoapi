"""
Azure Functions App for Geospatial ETL Pipeline
MVP implementation with job submission, status checking, and queue processing
"""
import json
import logging
import os
from typing import Dict, Any

import azure.functions as func
from azure.storage.queue import QueueServiceClient

from models import JobRequest, JobStatus
from repositories import JobRepository
from services import ServiceFactory

# Initialize function app
app = func.FunctionApp()

# Repository will be initialized lazily when needed

# Queue client for job submission
def get_queue_client():
    # Try managed identity first, fallback to connection string for local dev
    storage_account_name = os.environ.get('STORAGE_ACCOUNT_NAME')
    
    if storage_account_name:
        # Use managed identity in production
        from azure.identity import DefaultAzureCredential
        account_url = f"https://{storage_account_name}.queue.core.windows.net"
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
    else:
        # Fallback to connection string for local development
        connection_string = os.environ.get('AzureWebJobsStorage')
        if not connection_string:
            raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage environment variable must be set")
        queue_service = QueueServiceClient.from_connection_string(connection_string)
    
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