"""
Job Submission HTTP Trigger - Job Management

Concrete implementation of job submission endpoint using BaseHttpTrigger.
Handles creation of new processing jobs with idempotent behavior.

Usage:
    POST /api/jobs/{job_type}
    {
        "dataset_id": "container_name",
        "resource_id": "file_or_folder", 
        "version_id": "v1",
        "system": false,
        ... additional parameters
    }
    
Response:
    {
        "job_id": "SHA256_hash",
        "status": "created",
        "job_type": "operation_type",
        "message": "Job created and queued for processing",
        "parameters": {...},
        "queue_info": {...},
        "request_id": "uuid",
        "timestamp": "ISO-8601"
    }

Author: Azure Geospatial ETL Team
"""

from typing import Dict, Any, List

import azure.functions as func
from trigger_http_base import JobManagementTrigger


class JobSubmissionTrigger(JobManagementTrigger):
    """Job submission HTTP trigger implementation."""
    
    def __init__(self):
        super().__init__("submit_job")
    
    def get_allowed_methods(self) -> List[str]:
        """Job submission only supports POST."""
        return ["POST"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job submission request.
        
        Args:
            req: HTTP request with job_type in path and parameters in body
            
        Returns:
            Job creation response data
            
        Raises:
            ValueError: For invalid parameters
            NotImplementedError: For unsupported job types
        """
        # Extract job type from path
        path_params = self.extract_path_params(req, ["job_type"])
        job_type = path_params["job_type"]
        
        # Extract and validate request body
        req_body = self.extract_json_body(req, required=True)
        
        # Extract standard parameters
        dataset_id = req_body.get("dataset_id")
        resource_id = req_body.get("resource_id")
        version_id = req_body.get("version_id")
        system = req_body.get("system", False)
        
        # Extract additional parameters
        additional_params = {}
        standard_params = {"dataset_id", "resource_id", "version_id", "system"}
        for key, value in req_body.items():
            if key not in standard_params:
                additional_params[key] = value
        
        self.logger.debug(
            f"📦 Job parameters: dataset_id={dataset_id}, resource_id={resource_id}, "
            f"version_id={version_id}, system={system}, additional={list(additional_params.keys())}"
        )
        
        # Get controller for job type
        controller = self._get_controller_for_job_type(job_type)
        
        # Create job parameters
        job_params = {
            'dataset_id': dataset_id,
            'resource_id': resource_id, 
            'version_id': version_id,
            'system': system,
            **additional_params
        }
        
        # Validate parameters
        self.logger.debug(f"🔍 Starting parameter validation")
        validated_params = controller.validate_job_parameters(job_params)
        self.logger.debug(f"✅ Parameter validation complete")
        
        # Generate job ID from validated parameters
        job_id = controller.generate_job_id(validated_params)
        self.logger.info(f"Creating {job_type} job with ID: {job_id}")
        
        # Create job record
        self.logger.debug(f"💾 Creating job record")
        job_record = controller.create_job_record(job_id, validated_params)
        self.logger.debug(f"✅ Job record created")
        
        # Queue the job for processing
        self.logger.debug(f"📤 Queueing job for processing")
        queue_result = controller.queue_job(job_id, validated_params)
        self.logger.debug(f"📤 Queue result: {queue_result}")
        
        # Return success response
        return {
            "job_id": job_id,
            "status": "created", 
            "job_type": job_type,
            "message": "Job created and queued for processing",
            "parameters": validated_params,
            "queue_info": queue_result
        }
    
    def _get_controller_for_job_type(self, job_type: str):
        """
        Get controller instance for the specified job type.
        
        Args:
            job_type: Type of job to create controller for
            
        Returns:
            Controller instance
            
        Raises:
            NotImplementedError: If no controller exists for job type
        """
        self.logger.debug(f"🎯 Loading controller for job_type: {job_type}")
        
        if job_type == "hello_world":
            from controller_hello_world import HelloWorldController
            return HelloWorldController()
        else:
            # Explicitly fail for operations without controllers
            raise NotImplementedError(
                f"Operation '{job_type}' requires a controller implementation. "
                f"All operations must use the controller pattern. "
                f"Required: Create {job_type.title()}Controller class inheriting from BaseController"
            )


# Create singleton instance for use in function_app.py  
submit_job_trigger = JobSubmissionTrigger()