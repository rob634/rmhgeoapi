"""
Job Submission HTTP Trigger.

HTTP endpoint for POST /api/jobs/{job_type} requests.

Key Features:
    - Idempotent job creation with SHA256-based deduplication
    - Parameter validation using job controller schemas
    - Service Bus queue integration

Exports:
    JobSubmissionTrigger: Job submission trigger class
    submit_job_trigger: Singleton trigger instance
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

        # Extract force parameter from query string (09 DEC 2025)
        force_retry = req.params.get('force', 'false').lower() == 'true'

        # IDEMPOTENCY CHECK: See if job already exists
        from infrastructure.factory import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        existing_job = repos['job_repo'].get_job(job_id)

        if existing_job:
            job_status = existing_job.status.value if hasattr(existing_job.status, 'value') else str(existing_job.status)
            self.logger.info(f"🔄 Job {job_id[:16]}... already exists with status: {job_status}")

            # If job already completed, return existing results without re-running
            if job_status == 'completed':
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

            # ====================================================================================
            # FAILED JOB RE-SUBMISSION (09 DEC 2025)
            # ====================================================================================
            # If job is failed, auto-retry: reset job state and re-queue
            # Previous error is preserved in job's metadata.error_history[]
            # ====================================================================================
            elif job_status == 'failed':
                self.logger.info(f"🔄 Re-submitting failed job {job_id[:16]}...")

                # Reset job state (preserves error history in metadata)
                reset_result = repos['job_repo'].reset_failed_job(job_id, preserve_error=True)

                if not reset_result.get('reset'):
                    # Concurrent modification or other issue
                    self.logger.warning(f"⚠️ Failed to reset job {job_id[:16]}... for re-submission")
                    return {
                        "job_id": job_id,
                        "status": "reset_failed",
                        "job_type": job_type,
                        "message": "Failed to reset job for re-submission (concurrent modification?)",
                        "previous_status": "failed",
                        "idempotent": True
                    }

                # Delete old tasks (they'll be recreated when job is processed)
                tasks_deleted = repos['task_repo'].delete_tasks_for_job(job_id)
                self.logger.info(f"🗑️ Cleared {tasks_deleted} old tasks for re-submission")

                # Re-queue the job
                self.logger.debug(f"📤 Re-queueing job for processing")
                try:
                    queue_result = controller.queue_job(job_id, validated_params)
                    self.logger.debug(f"📤 Queue result: {queue_result}")
                except Exception as queue_error:
                    self.logger.error(f"❌ Failed to re-queue job {job_id}: {queue_error}")
                    raise RuntimeError(f"Job re-queuing failed: {queue_error}")

                return {
                    "job_id": job_id,
                    "status": "resubmitted",
                    "job_type": job_type,
                    "message": "Previously failed job has been reset and re-queued",
                    "attempt": reset_result.get('attempt', 2),
                    "previous_status": "failed",
                    "previous_stage": reset_result.get('previous_stage'),
                    "previous_error": reset_result.get('previous_error'),
                    "tasks_cleared": tasks_deleted,
                    "queue_info": queue_result,
                    "idempotent": False
                }

            # Job is in progress (queued/processing) - check force parameter
            elif force_retry:
                # Cannot force retry a non-failed job
                self.logger.warning(f"⚠️ Cannot force retry job with status '{job_status}'")
                raise ValueError(
                    f"Cannot force retry job with status '{job_status}'. "
                    f"Only failed jobs can be re-submitted. "
                    f"Current job is still {job_status}."
                )

            else:
                # Job exists but not completed - return current status
                self.logger.info(f"⏳ Job in progress with status: {job_status}")
                return {
                    "job_id": job_id,
                    "status": job_status,
                    "job_type": job_type,
                    "message": f"Job already exists with status: {job_status} (idempotency - not re-queued)",
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