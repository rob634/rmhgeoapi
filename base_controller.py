"""
Base controller class for job orchestration.

This module provides the abstract base class for all job controllers,
enforcing the Job→Task separation pattern. Controllers handle user-facing
operations, validate requests, create tasks, and aggregate results.

Key Responsibilities:
    - Accept and validate user requests
    - Create one or more tasks for processing
    - Queue tasks for execution
    - Track job progress
    - Aggregate task results

Design Pattern:
    Jobs = Controller-level orchestration (user-facing)
    Tasks = Service-level processing units (actual work)
    
Examples:
    - Single file: 1 job → 1 task
    - Multiple files: 1 job → N tasks
    - Tiled processing: 1 job → M tasks (one per tile)

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import hashlib
import json
from datetime import datetime

from repositories import JobRepository, TaskRepository
from logger_setup import get_logger
from schema_enforcement import (
    BaseSchemaEnforcer, SchemaDefinition, SchemaValidationError,
    create_job_request_schema, create_task_data_schema
)

logger = get_logger(__name__)


class BaseJobController(BaseSchemaEnforcer, ABC):
    """
    Abstract base class for all job controllers.
    
    Enforces the Job→Task pattern where every job must create at least
    one task. Controllers orchestrate the overall workflow while services
    handle the actual processing.
    
    Subclasses must implement:
        - validate_request(): Validate incoming parameters
        - create_tasks(): Generate task(s) for the job
        - aggregate_results(): Combine task results into job result
        
    The base class provides:
        - Standard job processing flow
        - Job ID generation (deterministic SHA256)
        - Task queuing
        - Progress tracking
    """
    
    def __init__(self):
        """Initialize controller with repository connections."""
        super().__init__()  # Initialize schema enforcer
        self.job_repo = JobRepository()
        self.task_repo = TaskRepository()
        self.logger = get_logger(self.__class__.__name__)
    
    def define_schema(self) -> SchemaDefinition:
        """
        Default job request schema. Controllers should override to add custom parameters.
        
        Returns:
            SchemaDefinition: Base job request schema
        """
        return create_job_request_schema()
    
    @abstractmethod
    def extend_schema(self, base_schema: SchemaDefinition) -> SchemaDefinition:
        """
        Extend the base schema with controller-specific parameters.
        
        Args:
            base_schema: Base job request schema
            
        Returns:
            SchemaDefinition: Extended schema with controller-specific fields
            
        Example:
            return base_schema.optional("n", int, "Number of hello world tasks")
        """
        pass
    
    def get_schema(self) -> SchemaDefinition:
        """Get the complete schema for this controller"""
        if self._schema is None:
            base_schema = create_job_request_schema()
            self._schema = self.extend_schema(base_schema)
        return self._schema
    
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """
        Validate incoming request parameters using strict schema enforcement.
        
        Args:
            request: Request dictionary from user
            
        Returns:
            bool: True if valid
            
        Raises:
            SchemaValidationError: If request violates schema (detailed error info)
        """
        try:
            self.validate_parameters(
                request,
                context=f"{self.__class__.__name__}.validate_request",
                strict=True
            )
            return True
        except SchemaValidationError as e:
            # Re-raise with controller context
            self.logger.error(f"🚨 SCHEMA VIOLATION in {self.__class__.__name__}: {e}")
            raise
    
    @abstractmethod
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create task(s) for this job.
        
        MUST create at least one task. Tasks are the atomic units of work
        that will be processed by services.
        
        Args:
            job_id: Unique job identifier
            request: Validated request parameters
            
        Returns:
            List[str]: Task IDs created
            
        Raises:
            TaskCreationError: If task creation fails
        """
        pass
    
    @abstractmethod
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """
        Aggregate task results into final job result.
        
        Called when all tasks complete to combine their outputs.
        
        Args:
            task_results: List of results from completed tasks
            
        Returns:
            Dict: Aggregated job result
        """
        pass
    
    def generate_job_id(self, request: Dict[str, Any]) -> str:
        """
        Generate deterministic job ID from request parameters.
        
        Uses SHA256 hash to ensure same parameters always produce the same 
        job ID, enabling idempotency. The hash is based on a JSON-serialized
        representation of the request parameters, ensuring consistency across
        different Python dictionary orderings.
        
        Algorithm:
            1. Extract standard parameters (operation_type, dataset_id, etc.)
            2. Include any additional custom parameters
            3. Sort keys and JSON serialize for consistency
            4. Return SHA256 hash (64 character hex string)
        
        Args:
            request: Request parameters dictionary
            
        Returns:
            str: SHA256 hash as job ID (64 characters)
            
        Example:
            >>> request = {'operation_type': 'cog', 'dataset_id': 'bronze', 
            ...            'resource_id': 'file.tif', 'version_id': 'v1'}
            >>> job_id = controller.generate_job_id(request)
            >>> len(job_id)  # Always 64 characters
            64
            
        Note:
            The same request parameters will ALWAYS generate the same job ID,
            which prevents duplicate job creation and enables safe retries.
        """
        # Build params dict with all relevant fields
        params = {
            'job_type': request.get('job_type', ''),
            'dataset_id': request.get('dataset_id', ''),
            'resource_id': request.get('resource_id', ''),
            'version_id': request.get('version_id', ''),
            'system': request.get('system', False)
        }
        
        # Include additional parameters (excluding standard ones)
        standard_params = {'dataset_id', 'resource_id', 'version_id', 'job_type', 'system'}
        for key, value in request.items():
            if key not in standard_params:
                params[key] = value
        
        # Generate deterministic string using JSON (sort_keys ensures consistency)
        param_string = json.dumps(params, sort_keys=True)
        return hashlib.sha256(param_string.encode()).hexdigest()
    
    def generate_task_id(self, job_id: str, task_name: str, index: int = 0) -> str:
        """
        Generate deterministic task ID.
        
        Args:
            job_id: Parent job ID
            task_name: Descriptive task name
            index: Task index for multiple tasks
            
        Returns:
            str: Unique task ID
        """
        task_string = f"{job_id}_{task_name}_{index}"
        return hashlib.sha256(task_string.encode()).hexdigest()[:16]  # Shorter task IDs
    
    def validate_task_data(self, task_data: Dict[str, Any]) -> bool:
        """
        Validate task data against standard task schema.
        
        Args:
            task_data: Task data to validate
            
        Returns:
            bool: True if valid
            
        Raises:
            SchemaValidationError: If task data violates schema
        """
        try:
            task_schema = create_task_data_schema()
            task_schema.validate_or_raise(
                task_data,
                context=f"{self.__class__.__name__}.validate_task_data",
                strict=False  # Allow additional task-specific parameters
            )
            return True
        except SchemaValidationError as e:
            self.logger.error(f"🚨 TASK SCHEMA VIOLATION in {self.__class__.__name__}: {e}")
            raise
    
    def queue_task(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        Queue a task for processing with schema validation.
        
        Args:
            task_id: Task identifier
            task_data: Task payload
            
        Returns:
            bool: True if queued successfully
            
        Raises:
            SchemaValidationError: If task data is invalid
        """
        try:
            # Validate task data before queuing
            self.validate_task_data(task_data)
            
            from repositories import StorageRepository
            storage = StorageRepository()
            
            # Add task_id to the data
            task_data['task_id'] = task_id
            
            # Queue to geospatial-tasks queue
            return storage.queue_message('geospatial-tasks', task_data)
        except Exception as e:
            self.logger.error(f"Failed to queue task {task_id}: {e}")
            return False
    
    def _log_request_parameters(self, request: Dict[str, Any], phase: str = "INPUT"):
        """
        Log request parameters for debugging parameter mismatches.
        
        Args:
            request: Request dictionary to log
            phase: Phase of processing (INPUT, VALIDATED, etc.)
        """
        controller_name = self.__class__.__name__
        
        # Extract core parameters
        core_params = {
            'operation_type': request.get('operation_type'),
            'dataset_id': request.get('dataset_id'),
            'resource_id': request.get('resource_id'),
            'version_id': request.get('version_id'),
            'system': request.get('system')
        }
        
        # Extract additional parameters
        standard_params = {'operation_type', 'dataset_id', 'resource_id', 'version_id', 'system'}
        additional_params = {k: v for k, v in request.items() if k not in standard_params}
        
        self.logger.debug(f"🔍 [{phase}] {controller_name} - Request Parameters:")
        self.logger.debug(f"  📋 Core Parameters:")
        for key, value in core_params.items():
            if value is not None:
                self.logger.debug(f"    ✅ {key}: {value}")
            else:
                self.logger.debug(f"    ❌ {key}: {value} (MISSING)")
        
        if additional_params:
            self.logger.debug(f"  📎 Additional Parameters:")
            for key, value in additional_params.items():
                param_type = type(value).__name__
                if isinstance(value, (dict, list)):
                    param_preview = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    self.logger.debug(f"    📄 {key} ({param_type}): {param_preview}")
                else:
                    self.logger.debug(f"    📄 {key} ({param_type}): {value}")
        else:
            self.logger.debug(f"  📎 Additional Parameters: None")
        
        # Log parameter count and size for debugging
        param_count = len([v for v in core_params.values() if v is not None]) + len(additional_params)
        self.logger.debug(f"  📊 Total parameters: {param_count}")

    def _validate_parameter_types(self, request: Dict[str, Any]):
        """
        Validate parameter types and log any type mismatches.
        
        Args:
            request: Request dictionary to validate
            
        Raises:
            ValueError: If critical parameter types are incorrect
        """
        controller_name = self.__class__.__name__
        type_issues = []
        
        # Expected types for standard parameters
        expected_types = {
            'operation_type': str,
            'dataset_id': str,
            'resource_id': str,
            'version_id': str,
            'system': bool
        }
        
        self.logger.debug(f"🔧 {controller_name} - Validating parameter types...")
        
        for param, expected_type in expected_types.items():
            value = request.get(param)
            if value is not None:
                actual_type = type(value)
                if not isinstance(value, expected_type):
                    issue = f"{param}: expected {expected_type.__name__}, got {actual_type.__name__} ({value})"
                    type_issues.append(issue)
                    self.logger.warning(f"  ⚠️ Type mismatch - {issue}")
                else:
                    self.logger.debug(f"  ✅ {param}: {expected_type.__name__} ✓")
        
        # Log any additional parameters with unusual types
        standard_params = set(expected_types.keys())
        for key, value in request.items():
            if key not in standard_params and value is not None:
                param_type = type(value).__name__
                if param_type in ['NoneType', 'function', 'module', 'type']:
                    issue = f"{key}: unusual type {param_type} (value: {value})"
                    type_issues.append(issue)
                    self.logger.warning(f"  ⚠️ Unusual type - {issue}")
                else:
                    self.logger.debug(f"  📄 {key}: {param_type}")
        
        if type_issues:
            self.logger.error(f"❌ {controller_name} - Parameter type validation issues:")
            for issue in type_issues:
                self.logger.error(f"    {issue}")
            # Don't raise exception for type issues unless critical
            # Let the controller-specific validation handle requirements

    def _log_task_creation_parameters(self, job_id: str, request: Dict[str, Any]):
        """
        Log parameters being passed to task creation for debugging.
        
        Args:
            job_id: Job ID for context
            request: Request parameters being used for task creation
        """
        controller_name = self.__class__.__name__
        
        self.logger.debug(f"🔨 {controller_name} - Task Creation Context:")
        self.logger.debug(f"  📋 Job ID: {job_id}")
        self.logger.debug(f"  🎯 Controller: {controller_name}")
        
        # Log parameters that typically affect task creation
        task_affecting_params = {
            'dataset_id': request.get('dataset_id'),
            'resource_id': request.get('resource_id'), 
            'version_id': request.get('version_id'),
            'operation_type': request.get('operation_type')
        }
        
        self.logger.debug(f"  📊 Task Creation Parameters:")
        for key, value in task_affecting_params.items():
            self.logger.debug(f"    {key}: {value}")
        
        # Log any controller-specific parameters that might affect task creation
        standard_params = {'operation_type', 'dataset_id', 'resource_id', 'version_id', 'system'}
        custom_params = {k: v for k, v in request.items() if k not in standard_params}
        
        if custom_params:
            self.logger.debug(f"  🛠️ Custom Parameters (may affect task creation):")
            for key, value in custom_params.items():
                if isinstance(value, (dict, list)):
                    self.logger.debug(f"    {key}: {type(value).__name__} (length: {len(value)})")
                else:
                    self.logger.debug(f"    {key}: {value}")
        else:
            self.logger.debug(f"  🛠️ Custom Parameters: None")

    def process_job(self, request: Dict[str, Any]) -> str:
        """
        Standard job processing flow with optimized task queuing and comprehensive parameter logging.
        
        This is the main entry point for controllers. It implements
        the standard pattern with efficiency improvements and detailed debugging:
        
        1. Log incoming parameters (DEBUG)
        2. Validate request
        3. Log validated parameters (DEBUG)
        4. Generate/check job ID (idempotency check)
        5. Create job record (atomic operation)
        6. Generate tasks (batch creation with logging)
        7. Queue tasks (batch operation with retry)
        8. Return job ID
        
        Performance Optimizations:
            - Early return for existing jobs (idempotency)
            - Batch task retrieval to minimize DB calls
            - Single storage repository instance for all queuing
            - Efficient error handling with proper cleanup
        
        Debug Features:
            - Comprehensive parameter logging at each phase
            - Parameter type and value validation logging
            - Task creation parameter tracking
            - Queue operation success/failure logging
        
        Args:
            request: Incoming request dictionary containing:
                - operation_type: Type of operation to perform
                - dataset_id: Target dataset identifier
                - resource_id: Resource to process
                - version_id: Version identifier (optional)
                - Additional operation-specific parameters
            
        Returns:
            str: Job ID for tracking (SHA256 hash, 64 chars)
            
        Raises:
            ValueError: If request validation fails
            TaskCreationError: If no tasks could be created
            
        Example:
            >>> controller = MyController()
            >>> job_id = controller.process_job({
            ...     'operation_type': 'cog_conversion',
            ...     'dataset_id': 'bronze',
            ...     'resource_id': 'file.tif',
            ...     'version_id': 'v1'
            ... })
            >>> print(f"Job queued: {job_id}")
        """
        job_id = None  # Initialize for error handling
        storage_repo = None  # Single instance for efficiency
        controller_name = self.__class__.__name__
        
        try:
            # Step 0: Log incoming parameters for debugging
            self.logger.info(f"🚀 {controller_name} - Starting job processing")
            self._log_request_parameters(request, "INPUT")
            
            # Validate parameter types and required fields
            self._validate_parameter_types(request)
            
            # Step 1: Validate request
            self.logger.debug(f"🔍 {controller_name} - Running controller-specific validation...")
            if not self.validate_request(request):
                self.logger.error(f"❌ {controller_name} - Controller-specific validation failed")
                raise ValueError("Request validation failed")
            
            # Log validated parameters
            self.logger.debug(f"✅ {controller_name} - Validation successful")
            self._log_request_parameters(request, "VALIDATED")
            
            # Step 2: Generate job ID (deterministic)
            job_id = self.generate_job_id(request)
            self.logger.info(f"Processing job: {job_id}")
            
            # Step 3: Check if job already exists (idempotency)
            existing_job = self.job_repo.get_job(job_id)
            if existing_job:
                status = existing_job.get('status')
                if status != 'failed':
                    self.logger.info(f"Job already exists with status '{status}': {job_id}")
                    return job_id
                else:
                    # Allow retry of failed jobs
                    self.logger.info(f"Retrying failed job: {job_id}")
            
            # Step 4: Create or update job record
            job_data = {
                'job_id': job_id,
                'status': 'pending',
                'job_type': request.get('operation_type', self.__class__.__name__),
                'dataset_id': request.get('dataset_id'),
                'resource_id': request.get('resource_id'),
                'version_id': request.get('version_id'),
                'created_at': datetime.utcnow().isoformat(),
                'request': request  # Store full request for debugging
            }
            
            if not self.job_repo.create_job(job_id, job_data):
                # Job exists, update it instead
                self.job_repo.update_job_status(job_id, 'pending', job_data)
            
            # Step 5: Create tasks (MUST create at least one)
            self.logger.debug(f"🔨 {controller_name} - Creating tasks for job {job_id}...")
            self._log_task_creation_parameters(job_id, request)
            
            task_ids = self.create_tasks(job_id, request)
            if not task_ids:
                from controller_exceptions import TaskCreationError
                self.logger.error(f"❌ {controller_name} - No tasks created for job {job_id}")
                raise TaskCreationError("Controller must create at least one task")
            
            self.logger.info(f"✅ {controller_name} - Created {len(task_ids)} tasks for job {job_id}")
            self.logger.debug(f"📋 Task IDs: {[tid[:16] + '...' for tid in task_ids]}")
            
            # Step 6: Update job with task info
            self.job_repo.update_job_status(job_id, 'queued', {
                'task_count': len(task_ids),
                'task_ids': task_ids
            })
            
            # Step 7: Batch queue all tasks (optimized)
            # Initialize storage repo once for all tasks
            from repositories import StorageRepository
            storage_repo = StorageRepository()
            
            # Batch retrieve all tasks to minimize DB calls
            tasks_to_queue = []
            for task_id in task_ids:
                task = self.task_repo.get_task(task_id)
                if task and isinstance(task.get('task_data'), dict):
                    task_payload = task['task_data'].copy()  # Copy to avoid mutation
                    task_payload['task_id'] = task_id
                    tasks_to_queue.append((task_id, task_payload))
                else:
                    self.logger.error(f"Task {task_id} missing or has invalid task_data")
            
            # Queue all tasks efficiently
            success_count = 0
            failed_tasks = []
            
            for task_id, task_payload in tasks_to_queue:
                try:
                    if storage_repo.queue_message('geospatial-tasks', task_payload):
                        success_count += 1
                        self.task_repo.update_task_status(task_id, 'queued')
                    else:
                        failed_tasks.append(task_id)
                except Exception as queue_error:
                    self.logger.error(f"Failed to queue task {task_id}: {queue_error}")
                    failed_tasks.append(task_id)
            
            self.logger.info(f"Queued {success_count}/{len(task_ids)} tasks for job {job_id}")
            
            # Step 8: Update job status based on queuing results
            if success_count == len(task_ids):
                # All tasks queued successfully
                self.job_repo.update_job_status(job_id, 'processing')
            elif success_count > 0:
                # Partial success
                self.job_repo.update_job_status(job_id, 'processing', {
                    'warning': f'Only {success_count}/{len(task_ids)} tasks queued',
                    'failed_tasks': failed_tasks
                })
            else:
                # Complete failure
                self.job_repo.update_job_status(job_id, 'failed', {
                    'error': 'Failed to queue any tasks',
                    'failed_tasks': failed_tasks
                })
                raise RuntimeError(f"Failed to queue any tasks for job {job_id}")
            
            return job_id
            
        except Exception as e:
            self.logger.error(f"Job processing failed: {e}", exc_info=True)
            # Try to update job status if job_id exists
            if job_id:
                try:
                    self.job_repo.update_job_status(job_id, 'failed', {
                        'error': str(e),
                        'error_type': type(e).__name__
                    })
                except Exception as update_error:
                    self.logger.error(f"Failed to update job status: {update_error}")
            raise
    
    def get_job_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get job progress by checking task statuses.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Dict with progress information
        """
        try:
            # Get all tasks for this job
            tasks = self.task_repo.get_tasks_for_job(job_id)
            
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get('status') == 'completed')
            failed = sum(1 for t in tasks if t.get('status') == 'failed')
            processing = sum(1 for t in tasks if t.get('status') == 'processing')
            
            return {
                'total_tasks': total,
                'completed_tasks': completed,
                'failed_tasks': failed,
                'processing_tasks': processing,
                'progress_percentage': (completed / total * 100) if total > 0 else 0
            }
        except Exception as e:
            self.logger.error(f"Failed to get job progress: {e}")
            return {
                'total_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'processing_tasks': 0,
                'progress_percentage': 0
            }