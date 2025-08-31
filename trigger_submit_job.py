# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Primary job submission HTTP endpoint with controller routing
# SOURCE: Environment variables (PostgreSQL) + Managed Identity (Azure Storage)
# SCOPE: HTTP-specific job submission with queue integration and validation
# VALIDATION: Job parameter validation + controller schema validation
# ============================================================================

"""
Job Submission HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint implementation for job submission using BaseHttpTrigger pattern.
Handles creation of new processing jobs with idempotent behavior, parameter validation,
and controller-based job orchestration for the Job→Stage→Task architecture.

Key Features:
- Idempotent job creation with SHA256-based deduplication
- Parameter validation using controller-specific schemas
- Controller pattern routing based on job_type
- Comprehensive error handling with detailed messages
- Queue integration for asynchronous processing
- DDH parameter validation for ETL operations

Job Creation Flow:
1. Extract job_type from URL path parameter
2. Extract and validate JSON request body parameters
3. Route to appropriate controller based on job_type
4. Validate parameters using controller schema validation
5. Generate deterministic job ID (SHA256 of parameters)
6. Create job record in storage with validated parameters
7. Queue job message for asynchronous processing
8. Return job creation response with queue information

Supported Job Types:
- hello_world: Multi-stage greeting workflow (fully implemented)
- Additional job types require controller implementation

Parameter Categories:
- Standard DDH Parameters: dataset_id, resource_id, version_id, system
- Job-specific Parameters: Varies by job_type (validated by controller)
- System Parameters: Internal flags for bypassing validation

Integration Points:
- Uses JobManagementTrigger base class for common patterns
- Routes to controller implementations in controller_* files
- Integrates with RepositoryFactory for job storage
- Connects to Azure Storage Queues for processing

API Endpoint:
    POST /api/jobs/{job_type}
    
Request Body:
    {
        "dataset_id": "container_name",     # Required for ETL operations
        "resource_id": "file_or_folder",    # Required for ETL operations
        "version_id": "v1.0",               # Required for ETL operations
        "system": false,                    # Optional: bypass DDH validation
        ...additional_job_specific_params   # Varies by job_type
    }
    
Response:
    {
        "job_id": "sha256_hash_of_parameters",
        "status": "created",
        "job_type": "operation_type",
        "message": "Job created and queued for processing",
        "parameters": {...validated_parameters},
        "queue_info": {...queue_details},
        "request_id": "unique_request_id",
        "timestamp": "2025-01-30T12:34:56.789Z"
    }

Error Responses:
- 400: Invalid parameters or missing required fields
- 404: Unsupported job_type (no controller implementation)
- 500: Internal server error during job creation

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
        self.logger.debug(f"🎯 Getting controller for job_type: {job_type}")
        try:
            controller = self._get_controller_for_job_type(job_type)
            self.logger.debug(f"✅ Controller loaded successfully: {type(controller).__name__}")
        except Exception as controller_error:
            self.logger.error(f"❌ Failed to load controller for {job_type}: {controller_error}")
            raise
        
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
        try:
            queue_result = controller.queue_job(job_id, validated_params)
            self.logger.debug(f"📤 Queue result: {queue_result}")
        except Exception as queue_error:
            self.logger.error(f"❌ Failed to queue job {job_id}: {queue_error}")
            # Re-raise with more context about where the error occurred
            raise RuntimeError(f"Job queuing failed in controller.queue_job(): {queue_error}")
        
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
            self.logger.debug(f"🏗️ Importing HelloWorldController")
            try:
                from controller_hello_world import HelloWorldController
                self.logger.debug(f"✅ HelloWorldController imported successfully")
                
                self.logger.debug(f"🏗️ Instantiating HelloWorldController")
                controller = HelloWorldController()
                self.logger.debug(f"✅ HelloWorldController instantiated successfully")
                return controller
            except Exception as hello_error:
                self.logger.error(f"❌ Failed to create HelloWorldController: {hello_error}")
                raise RuntimeError(f"HelloWorldController creation failed: {hello_error}")
        else:
            # Explicitly fail for operations without controllers
            raise NotImplementedError(
                f"Operation '{job_type}' requires a controller implementation. "
                f"All operations must use the controller pattern. "
                f"Required: Create {job_type.title()}Controller class inheriting from BaseController"
            )


# Create singleton instance for use in function_app.py  
submit_job_trigger = JobSubmissionTrigger()