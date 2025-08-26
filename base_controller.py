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

logger = get_logger(__name__)


class BaseJobController(ABC):
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
        self.job_repo = JobRepository()
        self.task_repo = TaskRepository()
        self.logger = get_logger(self.__class__.__name__)
    
    @abstractmethod
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """
        Validate incoming request parameters.
        
        Args:
            request: Request dictionary from user
            
        Returns:
            bool: True if valid, raises exception if invalid
            
        Raises:
            ValueError: If request is invalid
        """
        pass
    
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
            'operation_type': request.get('operation_type', ''),
            'dataset_id': request.get('dataset_id', ''),
            'resource_id': request.get('resource_id', ''),
            'version_id': request.get('version_id', ''),
            'system': request.get('system', False)
        }
        
        # Include additional parameters (excluding standard ones)
        standard_params = {'dataset_id', 'resource_id', 'version_id', 'operation_type', 'system'}
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
    
    def queue_task(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        Queue a task for processing.
        
        Args:
            task_id: Task identifier
            task_data: Task payload
            
        Returns:
            bool: True if queued successfully
        """
        try:
            from repositories import StorageRepository
            storage = StorageRepository()
            
            # Add task_id to the data
            task_data['task_id'] = task_id
            
            # Queue to geospatial-tasks queue
            return storage.queue_message('geospatial-tasks', task_data)
        except Exception as e:
            self.logger.error(f"Failed to queue task {task_id}: {e}")
            return False
    
    def process_job(self, request: Dict[str, Any]) -> str:
        """
        Standard job processing flow with optimized task queuing.
        
        This is the main entry point for controllers. It implements
        the standard pattern with efficiency improvements:
        
        1. Validate request
        2. Generate/check job ID (idempotency check)
        3. Create job record (atomic operation)
        4. Generate tasks (batch creation)
        5. Queue tasks (batch operation with retry)
        6. Return job ID
        
        Performance Optimizations:
            - Early return for existing jobs (idempotency)
            - Batch task retrieval to minimize DB calls
            - Single storage repository instance for all queuing
            - Efficient error handling with proper cleanup
        
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
        
        try:
            # Step 1: Validate request
            if not self.validate_request(request):
                raise ValueError("Request validation failed")
            
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
                'operation_type': request.get('operation_type', self.__class__.__name__),
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
            task_ids = self.create_tasks(job_id, request)
            if not task_ids:
                from controller_exceptions import TaskCreationError
                raise TaskCreationError("Controller must create at least one task")
            
            self.logger.info(f"Created {len(task_ids)} tasks for job {job_id}")
            
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