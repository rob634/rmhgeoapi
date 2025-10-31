# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Primary job submission endpoint for Job→Stage→Task architecture
# PURPOSE: Primary job submission HTTP trigger handling POST /api/jobs/{job_type} requests
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: JobSubmissionTrigger, submit_job_trigger (singleton instance)
# INTERFACES: JobManagementTrigger (inherited from http_base)
# PYDANTIC_MODELS: None directly - uses job controller validation for parameters
# DEPENDENCIES: http_base.JobManagementTrigger, azure.functions, jobs.ALL_JOBS, infrastructure.factory.RepositoryFactory
# SOURCE: HTTP POST requests with JSON body containing job parameters
# SCOPE: HTTP endpoint for job creation, validation, idempotency checks, and queue submission
# VALIDATION: Job type validation (ALL_JOBS registry), parameter schema validation (via job controllers), DDH parameter checks
# PATTERNS: Template Method (base class), Strategy (job controller routing), Idempotency (SHA256-based deduplication)
# ENTRY_POINTS: POST /api/jobs/{job_type} - Used by function_app.py via submit_job_trigger singleton
# INDEX: JobSubmissionTrigger:98, process_request:108, _get_controller_for_job_type:272
# ============================================================================

"""
Job Submission HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint implementation for job submission using BaseHttpTrigger pattern.
Handles creation of new processing jobs with idempotent behavior, parameter validation,
and job controller orchestration for the Job→Stage→Task architecture.

Key Features:
- Idempotent job creation with SHA256-based deduplication
- Parameter validation using job controller-specific schemas
- Explicit registry routing (jobs.ALL_JOBS) - no magic, crystal clear
- Comprehensive error handling with detailed messages
- Service Bus queue integration for asynchronous processing
- DDH parameter validation for ETL operations
- Service Bus toggle support (use_service_bus parameter) for migration flexibility

Job Creation Flow:
1. Extract job_type from URL path parameter
2. Extract and validate JSON request body parameters
3. Route to appropriate job controller based on job_type (via ALL_JOBS registry)
4. Validate parameters using controller's validate_job_parameters() method
5. Generate deterministic job ID via controller's generate_job_id() method (SHA256)
6. Check for existing job (idempotency) - return existing if already completed/in-progress
7. Create job record via controller's create_job_record() method
8. Queue job message via controller's queue_job() method (Service Bus)
9. Return job creation response with queue information

5-Method Job Interface Contract (enforced at import time):
1. validate_job_parameters(params: dict) -> dict - Validate and normalize parameters
2. generate_job_id(params: dict) -> str - SHA256 hash for idempotency
3. create_job_record(job_id: str, params: dict) -> dict - Persist JobRecord
4. queue_job(job_id: str, params: dict) -> dict - Send to Service Bus
5. get_workflow_definition() -> WorkflowDefinition - Return workflow spec

Supported Job Types (from jobs.ALL_JOBS):
- hello_world: Multi-stage greeting workflow
- sb_hello_world: Service Bus variant
- ingest_vector: PostGIS vector ingestion
- process_large_raster: Big Raster ETL with COG conversion
- list_container_contents: Container blob analysis (diamond pattern)
- Additional job types via jobs/__init__.py ALL_JOBS registry

Parameter Categories:
- Standard DDH Parameters: dataset_id, resource_id, version_id, system
- Job-specific Parameters: Varies by job_type (validated by job controller)
- System Parameters: use_service_bus (toggle Service Bus vs Storage Queue routing)

Integration Points:
- JobManagementTrigger base class (http_base.py) - Common HTTP patterns
- Job controllers (jobs/*.py) - Job-specific orchestration logic
- RepositoryFactory - Database persistence
- Service Bus - Asynchronous job/task processing
- CoreMachine (core/machine.py) - Job orchestration engine

API Endpoint:
    POST /api/jobs/{job_type}

Request Body:
    {
        "dataset_id": "container_name",     # Required for ETL operations
        "resource_id": "file_or_folder",    # Required for ETL operations
        "version_id": "v1.0",               # Required for ETL operations
        "system": false,                    # Optional: bypass DDH validation
        "use_service_bus": true,            # Optional: force Service Bus routing
        ...additional_job_specific_params   # Varies by job_type
    }

Response (Success - New Job):
    {
        "job_id": "sha256_hash_of_parameters",
        "status": "created",
        "job_type": "operation_type",
        "message": "Job created and queued for processing",
        "parameters": {...validated_parameters},
        "queue_info": {...queue_details},
        "idempotent": false
    }

Response (Idempotent - Existing Completed Job):
    {
        "job_id": "sha256_hash_of_parameters",
        "status": "already_completed",
        "job_type": "operation_type",
        "message": "Job already completed with identical parameters...",
        "parameters": {...validated_parameters},
        "result_data": {...existing_results},
        "created_at": "2025-10-29T12:00:00Z",
        "completed_at": "2025-10-29T12:05:00Z",
        "idempotent": true
    }

Response (Idempotent - Existing In-Progress Job):
    {
        "job_id": "sha256_hash_of_parameters",
        "status": "processing",
        "job_type": "operation_type",
        "message": "Job already exists with status: processing (not re-queued)",
        "parameters": {...validated_parameters},
        "current_stage": 2,
        "total_stages": 3,
        "idempotent": true
    }

Error Responses:
- 400: Invalid parameters or missing required fields
- 404: Unsupported job_type (not in ALL_JOBS registry)
- 500: Internal server error during job creation or queue submission

Author: Robert and Geospatial Claude Legion
Date: Original implementation 2025
Last Updated: 29 OCT 2025
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