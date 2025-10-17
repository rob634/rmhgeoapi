# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# CATEGORY: HTTP TRIGGER ENDPOINTS
# PURPOSE: Azure Functions HTTP API endpoint
# EPOCH: Shared by all epochs (API layer)
# TODO: Audit for framework logic that may belong in CoreMachine# PURPOSE: Primary job submission HTTP trigger handling POST /api/jobs/{job_type} requests
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
from .http_base import JobManagementTrigger


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

        # Extract Service Bus toggle parameter
        use_service_bus = req_body.get("use_service_bus", False)
        
        # Extract additional parameters
        additional_params = {}
        standard_params = {"dataset_id", "resource_id", "version_id", "system", "use_service_bus"}
        for key, value in req_body.items():
            if key not in standard_params:
                additional_params[key] = value
        
        self.logger.debug(
            f"📦 Job parameters: dataset_id={dataset_id}, resource_id={resource_id}, "
            f"version_id={version_id}, system={system}, use_service_bus={use_service_bus}, "
            f"additional={list(additional_params.keys())}"
        )
        
        # Get controller for job type
        self.logger.debug(f"🎯 Getting controller for job_type: {job_type}")
        try:
            controller = self._get_controller_for_job_type(job_type)
            self.logger.debug(f"✅ Controller loaded successfully: {type(controller).__name__}")
        except Exception as controller_error:
            self.logger.error(f"❌ Failed to load controller for {job_type}: {controller_error}")
            raise
        
        # Create job parameters (including Service Bus toggle)
        job_params = {
            'dataset_id': dataset_id,
            'resource_id': resource_id,
            'version_id': version_id,
            'system': system,
            'use_service_bus': use_service_bus,  # Pass toggle to controller
            **additional_params
        }
        
        # ====================================================================================
        # JOB INTERFACE CONTRACT: Method 1 of 5
        # ====================================================================================
        # validate_job_parameters(params: dict) -> dict
        # - Validates and normalizes parameters before job creation
        # - Must return validated dict with defaults applied
        # - Enforced at import time by: jobs/__init__.py validate_job_registry()
        # ====================================================================================
        self.logger.debug(f"🔍 Starting parameter validation")
        validated_params = controller.validate_job_parameters(job_params)
        self.logger.debug(f"✅ Parameter validation complete")

        # ====================================================================================
        # JOB INTERFACE CONTRACT: Method 2 of 5
        # ====================================================================================
        # generate_job_id(params: dict) -> str
        # - Returns deterministic SHA256 hash for idempotency (same params = same job_id)
        # - Enables deduplication: identical job submissions return same job_id
        # - Enforced at import time by: jobs/__init__.py validate_job_registry()
        # ====================================================================================
        job_id = controller.generate_job_id(validated_params)
        self.logger.info(f"Checking for existing {job_type} job with ID: {job_id}")

        # IDEMPOTENCY CHECK: See if job already exists
        from infrastructure.factory import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        existing_job = repos['job_repo'].get_job(job_id)

        if existing_job:
            self.logger.info(f"🔄 Job {job_id[:16]}... already exists with status: {existing_job.status}")

            # If job already completed, return existing results without re-running
            if existing_job.status.value == 'completed':
                self.logger.info(f"✅ Job already completed - returning existing results")
                return {
                    "job_id": job_id,
                    "status": "already_completed",
                    "job_type": job_type,
                    "message": "Job already completed with identical parameters - returning existing results (idempotency)",
                    "parameters": validated_params,
                    "result_data": existing_job.result_data,
                    "created_at": existing_job.created_at.isoformat() if existing_job.created_at else None,
                    "completed_at": existing_job.updated_at.isoformat() if existing_job.updated_at else None,
                    "idempotent": True
                }
            else:
                # Job exists but not completed - return current status
                self.logger.info(f"⏳ Job in progress with status: {existing_job.status}")
                return {
                    "job_id": job_id,
                    "status": existing_job.status.value,
                    "job_type": job_type,
                    "message": f"Job already exists with status: {existing_job.status.value} (idempotency - not re-queued)",
                    "parameters": validated_params,
                    "created_at": existing_job.created_at.isoformat() if existing_job.created_at else None,
                    "current_stage": existing_job.stage,
                    "total_stages": existing_job.total_stages,
                    "idempotent": True
                }

        # Job doesn't exist - proceed with creation
        self.logger.info(f"Creating new {job_type} job with ID: {job_id}")

        # ====================================================================================
        # JOB INTERFACE CONTRACT: Method 3 of 5
        # ====================================================================================
        # create_job_record(job_id: str, params: dict) -> dict
        # - Creates JobRecord Pydantic model and persists to app.jobs table
        # - Must use RepositoryFactory.create_repositories() for database access
        # - Enforced at import time by: jobs/__init__.py validate_job_registry()
        # ====================================================================================
        self.logger.debug(f"💾 Creating job record")
        job_record = controller.create_job_record(job_id, validated_params)
        self.logger.debug(f"✅ Job record created")

        # ====================================================================================
        # JOB INTERFACE CONTRACT: Method 4 of 5
        # ====================================================================================
        # queue_job(job_id: str, params: dict) -> dict
        # - Creates JobQueueMessage and sends to Service Bus 'jobs' queue
        # - Message triggers CoreMachine to process job (core/machine.py)
        # - Enforced at import time by: jobs/__init__.py validate_job_registry()
        # ====================================================================================
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
            "queue_info": queue_result,
            "idempotent": False
        }
    
    def _get_controller_for_job_type(self, job_type: str):
        """
        Get controller instance for the specified job type.

        NO AUTO-PREFIXING: Job type must match exactly as registered.
        Queue routing determined by controller's queue_type declaration.

        Args:
            job_type: Exact job type as registered (e.g. 'hello_world' or 'sb_hello_world')

        Returns:
            Controller instance

        Raises:
            ValueError: If job type is not supported
        """
        self.logger.debug(f"🎯 Validating job_type: {job_type}")

        # Use EXPLICIT REGISTRY for job validation (NO decorators, NO factory!)
        # Direct dict lookup - crystal clear, no magic
        from jobs import ALL_JOBS

        if job_type not in ALL_JOBS:
            # Unknown job type - provide helpful error message
            available = list(ALL_JOBS.keys())
            error_msg = (
                f"Invalid job type: '{job_type}'. "
                f"Available job types: {', '.join(available) if available else 'none configured'}. "
                f"Please use one of the supported job types."
            )
            self.logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

        # Job type is valid - get job class from registry
        job_class = ALL_JOBS[job_type]
        self.logger.debug(f"✅ Job type validated: {job_type} ({job_class.__name__})")

        # Return job class (CoreMachine will use it for orchestration)
        return job_class


# Create singleton instance for use in function_app.py  
submit_job_trigger = JobSubmissionTrigger()