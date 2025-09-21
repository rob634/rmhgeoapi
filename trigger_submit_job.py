# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Primary job submission HTTP trigger handling POST /api/jobs/{job_type} requests
# EXPORTS: JobSubmissionTrigger (HTTP trigger class for job submission)
# INTERFACES: JobManagementTrigger (inherited from trigger_http_base)
# PYDANTIC_MODELS: None directly - uses controller validation for job parameters
# DEPENDENCIES: trigger_http_base, typing, azure.functions (implicit via base class)
# SOURCE: HTTP POST requests with JSON body containing job parameters
# SCOPE: HTTP endpoint for job creation, validation, and queue submission
# VALIDATION: Job type validation, parameter schema validation via controllers, DDH parameter checks
# PATTERNS: Template Method (implements base class abstract methods), Strategy (controller routing)
# ENTRY_POINTS: trigger = JobSubmissionTrigger(); response = trigger.handle_request(req)
# INDEX: JobSubmissionTrigger:88, process_request:120, _validate_ddh_parameters:200
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
            ValueError: For invalid parameters or unsupported job types
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
            ValueError: If job type is not supported
        """
        self.logger.debug(f"🎯 Loading controller for job_type: {job_type}")
        
        # Use JobFactory to create controllers
        self.logger.debug(f"🏗️ Using JobFactory to create controller for {job_type}")
        try:
            from controller_factories import JobFactory
            import controller_hello_world  # Import to trigger registration
            import controller_container  # Import to trigger registration of container controllers
            import controller_stac_setup  # Import to trigger registration of STAC setup controller
            
            controller = JobFactory.create_controller(job_type)
            self.logger.debug(f"✅ Controller for {job_type} created successfully via JobFactory")
            return controller
        except ValueError as e:
            # JobFactory raises ValueError for unknown job types
            self.logger.error(f"❌ Unknown job type {job_type}: {e}")
            
            # Get list of supported job types
            from schema_base import JobRegistry
            supported_jobs = JobRegistry.instance().list_job_types()
            
            raise ValueError(
                f"Invalid job type: '{job_type}'. "
                f"Supported job types: {', '.join(supported_jobs) if supported_jobs else 'none configured'}. "
                f"Please use one of the supported job types."
            )
        except Exception as error:
            self.logger.error(f"❌ Failed to create controller for {job_type}: {error}")
            raise RuntimeError(f"Controller creation failed for {job_type}: {error}")


# Create singleton instance for use in function_app.py  
submit_job_trigger = JobSubmissionTrigger()