# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Abstract base controller for Job→Stage→Task orchestration
# SOURCE: Environment variables (PostgreSQL) + Managed Identity (Azure Storage)
# SCOPE: Global job orchestration foundation for all workflow types
# VALIDATION: Pydantic workflow validation + Azure credential validation
# ============================================================================

"""
Abstract Base Controller - Job→Stage→Task Architecture

Abstract base class implementing the sophisticated Job→Stage→Task orchestration pattern
for complex geospatial workflows. Controllers define job types, coordinate sequential stages,
and manage parallel task execution with distributed completion detection.

Architecture Pattern:
    JOB (Controller Layer - Orchestration)
     ├── STAGE 1 (Sequential coordination)
     │   ├── Task A (Service + Repository Layer - Parallel)
     │   ├── Task B (Service + Repository Layer - Parallel) 
     │   └── Task C (Service + Repository Layer - Parallel)
     │                     ↓ Last task completes stage
     ├── STAGE 2 (Sequential coordination)
     │   ├── Task D (Service + Repository Layer - Parallel)
     │   └── Task E (Service + Repository Layer - Parallel)
     │                     ↓ Last task completes stage
     └── COMPLETION (job_type specific aggregation)

Key Features:
- Pydantic workflow definitions with stage sequences
- Sequential stages with parallel task execution within stages
- Idempotent job processing with SHA256-based deduplication
- "Last task turns out the lights" atomic completion detection
- Strong typing discipline with explicit error handling
- Centralized workflow validation and parameter schemas

Controller Responsibilities:
- Define job_type and workflow stages (orchestration only)
- Create and coordinate sequential stage transitions
- Fan-out parallel tasks within each stage
- Aggregate final job results from all task outputs
- Handle job completion and result formatting

Integration Points:
- Used by HTTP triggers for job submission
- Creates JobRecord and TaskDefinition objects
- Interfaces with RepositoryFactory for data persistence
- Routes to Service layer for business logic execution
- Integrates with queue system for asynchronous processing

Usage Example:
    class MyController(BaseController):
        def get_job_type(self) -> str:
            return "my_operation"
            
        def process_job_stage(self, job_record, stage, parameters, stage_results):
            # Stage coordination logic here
            pass

Author: Azure Geospatial ETL Team
"""

from abc import ABC, abstractmethod
import hashlib
import json
import logging

from schema_core import (
    JobStatus, TaskStatus, JobRecord, JobQueueMessage
)
from model_core import (
    TaskDefinition, JobExecutionContext, StageExecutionContext
)
from typing import List, Dict, Any, Optional
from schema_workflow import WorkflowDefinition, get_workflow_definition


class BaseController(ABC):
    """
    Abstract base controller for all job types in the redesign architecture.
    
    CONTROLLER LAYER RESPONSIBILITY (Orchestration):
    - Defines job_type and sequential stages  
    - Orchestrates stage transitions
    - Aggregates final job results
    - Does NOT contain business logic (that lives in Task layer)
    
    Implements the Job → Stage → Task pattern:
    - Job: One or more stages with job_type specific completion
    - Stage: Sequential operations that create parallel tasks
    - Task: Where Service + Repository layers live for business logic
    """

    def __init__(self):
        self.job_type = self.get_job_type()
        
        # Load workflow definition - REQUIRED for all controllers
        try:
            self.workflow_definition = get_workflow_definition(self.job_type)
        except ValueError as e:
            raise ValueError(f"No workflow definition found for job_type '{self.job_type}'. "
                           f"All controllers must have workflow definitions defined in schema_workflow.py. "
                           f"Error: {e}")
        
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.logger.info(f"Loaded workflow definition for {self.job_type} with {len(self.workflow_definition.stages)} stages")

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by concrete controllers
    # ========================================================================
    
    @abstractmethod
    def get_job_type(self) -> str:
        """
        Return the unique job type identifier for this controller.
        
        This identifies the controller and determines routing.
        Must be unique across all controllers in the system.
        """
        pass


    @abstractmethod
    def create_stage_tasks(self, context: StageExecutionContext) -> List[TaskDefinition]:
        """
        Create tasks for a specific stage.
        
        This method defines what parallel tasks should be created for the stage.
        Tasks contain the business logic (Service + Repository layers).
        
        Args:
            context: Stage execution context with job parameters and previous results
            
        Returns:
            List of TaskDefinition objects for parallel execution
        """
        pass

    @abstractmethod
    def aggregate_job_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        Aggregate results from all stages into final job result.
        
        This is the job_type specific completion method that creates
        the final result after all stages are complete.
        
        Args:
            context: Job execution context with results from all stages
            
        Returns:
            Final aggregated job result dictionary
        """
        pass

    # ========================================================================
    # CONCRETE METHODS - Provided by base class for all controllers
    # ========================================================================

    def generate_job_id(self, parameters: Dict[str, Any]) -> str:
        """
        Generate idempotent job ID from parameters hash.
        
        Same parameters always generate the same job ID, providing
        natural deduplication without additional logic.
        """
        # Sort parameters for consistent hashing
        sorted_params = json.dumps(parameters, sort_keys=True, default=str)
        hash_input = f"{self.job_type}:{sorted_params}"
        job_id = hashlib.sha256(hash_input.encode()).hexdigest()
        self.logger.debug(f"Generated job_id {job_id[:12]}... for job_type {self.job_type}")
        return job_id

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize job parameters using workflow definition.
        
        All controllers MUST have workflow definitions for type-safe validation.
        """
        if not isinstance(parameters, dict):
            raise ValueError("Job parameters must be a dictionary")
        
        # Ensure job_type matches controller
        if parameters.get('job_type') and parameters['job_type'] != self.job_type:
            raise ValueError(f"Job type mismatch: expected {self.job_type}, got {parameters.get('job_type')}")
        
        # Don't mutate original parameters
        parameters = parameters.copy()
        
        # Use workflow definition validation - REQUIRED
        try:
            validated_params = self.workflow_definition.validate_job_parameters(parameters)
            self.logger.debug(f"Workflow validation successful for job_type {self.job_type}")
            return validated_params
        except Exception as e:
            self.logger.error(f"Workflow parameter validation failed: {e}")
            raise ValueError(f"Parameter validation failed: {e}")
    
    def validate_stage_parameters(self, stage_number: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for a specific stage using workflow definition
        
        Returns validated parameters with defaults applied
        """
        try:
            validated_params = self.workflow_definition.validate_stage_parameters(stage_number, parameters)
            self.logger.debug(f"Stage {stage_number} parameters validated successfully")
            return validated_params
        except Exception as e:
            self.logger.error(f"Stage {stage_number} parameter validation failed: {e}")
            raise ValueError(f"Stage {stage_number} parameter validation failed: {e}")
    
    def get_workflow_stage_definition(self, stage_number: int):
        """Get workflow stage definition for a stage number"""
        return self.workflow_definition.get_stage_by_number(stage_number)
    
    def get_next_stage_number(self, current_stage: int) -> Optional[int]:
        """Get the next stage number in the workflow sequence"""
        next_stage = self.workflow_definition.get_next_stage(current_stage)
        return next_stage.stage_number if next_stage else None
    
    def is_final_stage(self, stage_number: int) -> bool:
        """Check if a stage is the final stage in the workflow"""
        stage_def = self.workflow_definition.get_stage_by_number(stage_number)
        return stage_def.is_final_stage if stage_def else False

    def create_job_context(self, job_id: str, parameters: Dict[str, Any], 
                          current_stage: int = 1, stage_results: Dict[int, Dict[str, Any]] = None) -> JobExecutionContext:
        """Create job execution context for orchestration"""
        # Get total stages from workflow definition
        total_stages = len(self.workflow_definition.stages)
        
        return JobExecutionContext(
            job_id=job_id,
            job_type=self.job_type,
            current_stage=current_stage,
            total_stages=total_stages,
            parameters=parameters,
            stage_results=stage_results or {}
        )

    def create_stage_context(self, job_context: JobExecutionContext, stage_number: int) -> StageExecutionContext:
        """Create stage execution context from job context"""
        stage = self.workflow_definition.get_stage_by_number(stage_number)
        if not stage:
            raise ValueError(f"Stage {stage_number} not found in job_type {self.job_type}")
        
        # Get results from previous stage if available
        previous_stage_results = None
        if stage_number > 1:
            previous_stage_results = job_context.get_stage_result(stage_number - 1)
        
        return StageExecutionContext(
            job_id=job_context.job_id,
            stage_number=stage_number,
            stage_name=stage.stage_name,
            task_type=stage.task_type,
            job_parameters=job_context.parameters,
            previous_stage_results=previous_stage_results
        )

    def create_job_record(self, job_id: str, parameters: Dict[str, Any]) -> JobRecord:
        """Create and store the initial job record for database storage"""
        from repository_data import RepositoryFactory
        
        # Store the job record using repository interface
        job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
        job_record = job_repo.create_job(
            job_type=self.job_type,
            parameters=parameters,
            total_stages=len(self.workflow_definition.stages)
        )
        
        self.logger.info(f"Job record created and stored: {job_id[:16]}...")
        return job_record

    def create_job_queue_message(self, job_id: str, parameters: Dict[str, Any], 
                               stage: int = 1, stage_results: Dict[int, Dict[str, Any]] = None) -> JobQueueMessage:
        """Create message for jobs queue"""
        return JobQueueMessage(
            job_id=job_id,
            job_type=self.job_type,
            stage=stage,
            parameters=parameters,
            stage_results=stage_results or {}
        )

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue job for processing using Azure Storage Queue.
        
        Creates a job queue message and sends it to the geospatial-jobs queue
        for asynchronous processing by the queue trigger.
        
        Args:
            job_id: The unique job identifier
            parameters: Validated job parameters
            
        Returns:
            Dictionary with queue operation results
        """
        from azure.storage.queue import QueueServiceClient
        from azure.identity import DefaultAzureCredential
        from config import get_config
        import json
        
        config = get_config()
        
        # Create job queue message
        queue_message = self.create_job_queue_message(job_id, parameters)
        
        # Send to queue
        try:
            # Initialize queue client using managed identity
            account_url = config.queue_service_url
            self.logger.debug(f"🔐 Creating DefaultAzureCredential for queue operations")
            try:
                credential = DefaultAzureCredential()
                self.logger.debug(f"✅ DefaultAzureCredential created successfully")
            except Exception as cred_error:
                self.logger.error(f"❌ CRITICAL: Failed to create DefaultAzureCredential for storage queues: {cred_error}")
                raise RuntimeError(f"CRITICAL CONFIGURATION ERROR - Managed identity authentication failed for Azure Storage: {cred_error}")
            
            self.logger.debug(f"🔗 Creating QueueServiceClient with URL: {account_url}")
            try:
                queue_service = QueueServiceClient(account_url, credential=credential)
                queue_client = queue_service.get_queue_client(config.job_processing_queue)
                self.logger.debug(f"📤 Queue client created for: {config.job_processing_queue}")
            except Exception as queue_error:
                self.logger.error(f"❌ CRITICAL: Failed to create QueueServiceClient or queue client: {queue_error}")
                raise RuntimeError(f"CRITICAL CONFIGURATION ERROR - Azure Storage Queue access failed: {queue_error}")
            
            # Convert message to JSON
            message_json = queue_message.model_dump_json()
            self.logger.debug(f"Queueing job message: {message_json}")
            
            # Send message to queue
            queue_client.send_message(message_json)
            
            self.logger.info(f"Job {job_id[:16]}... queued successfully to {config.job_processing_queue}")
            
            return {
                "queued": True,
                "queue_name": config.job_processing_queue,
                "job_id": job_id,
                "stage": 1
            }
            
        except Exception as e:
            self.logger.error(f"Failed to queue job {job_id}: {e}")
            raise RuntimeError(f"Failed to queue job: {e}")

    # ========================================================================
    # TASK AND STAGE MANAGEMENT METHODS - Enhanced visibility and control
    # ========================================================================

    def list_stage_tasks(self, job_id: str, stage_number: int) -> List[Dict[str, Any]]:
        """
        List all tasks for a specific stage.
        
        Provides visibility into task progress within a stage.
        Useful for debugging, monitoring, and progress reporting.
        
        Args:
            job_id: The job identifier
            stage_number: The stage number to query
            
        Returns:
            List of task records for the specified stage
        """
        from repository_data import RepositoryFactory
        
        job_repo, task_repo, _ = RepositoryFactory.create_repositories('postgres')
        tasks = task_repo.get_tasks_by_stage(job_id, stage_number)
        
        self.logger.debug(f"Found {len(tasks)} tasks in stage {stage_number} for job {job_id[:16]}...")
        return tasks

    def get_job_tasks(self, job_id: str) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get all tasks grouped by stage.
        
        Provides complete visibility into job task structure across all stages.
        Essential for job monitoring and progress tracking.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary mapping stage numbers to lists of task records
        """
        tasks_by_stage = {}
        
        for stage in self.workflow_definition.stages:
            stage_tasks = self.list_stage_tasks(job_id, stage.stage_number)
            tasks_by_stage[stage.stage_number] = stage_tasks
        
        total_tasks = sum(len(tasks) for tasks in tasks_by_stage.values())
        self.logger.debug(f"Retrieved {total_tasks} tasks across {len(tasks_by_stage)} stages for job {job_id[:16]}...")
        
        return tasks_by_stage

    def get_task_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get task completion progress by stage.
        
        Provides detailed progress metrics for monitoring and UI display.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary with progress statistics by stage and overall job
        """
        tasks_by_stage = self.get_job_tasks(job_id)
        
        progress = {
            'job_id': job_id,
            'job_type': self.job_type,
            'total_stages': len(self.workflow_definition.stages),
            'stages': {},
            'overall': {
                'total_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'processing_tasks': 0,
                'pending_tasks': 0
            }
        }
        
        for stage_num, tasks in tasks_by_stage.items():
            stage_progress = {
                'stage_number': stage_num,
                'stage_name': f"stage_{stage_num}",
                'total_tasks': len(tasks),
                'completed_tasks': 0,
                'failed_tasks': 0,
                'processing_tasks': 0,
                'pending_tasks': 0
            }
            
            # Count task statuses
            for task in tasks:
                task_status = task.get('status', 'pending')
                if task_status == 'completed':
                    stage_progress['completed_tasks'] += 1
                    progress['overall']['completed_tasks'] += 1
                elif task_status == 'failed':
                    stage_progress['failed_tasks'] += 1
                    progress['overall']['failed_tasks'] += 1
                elif task_status == 'processing':
                    stage_progress['processing_tasks'] += 1
                    progress['overall']['processing_tasks'] += 1
                else:
                    stage_progress['pending_tasks'] += 1
                    progress['overall']['pending_tasks'] += 1
                
                progress['overall']['total_tasks'] += 1
            
            # Calculate percentages
            if stage_progress['total_tasks'] > 0:
                stage_progress['completion_percentage'] = (
                    stage_progress['completed_tasks'] / stage_progress['total_tasks']
                ) * 100
                stage_progress['is_complete'] = stage_progress['completed_tasks'] == stage_progress['total_tasks']
            else:
                stage_progress['completion_percentage'] = 0.0
                stage_progress['is_complete'] = False
            
            progress['stages'][stage_num] = stage_progress
        
        # Calculate overall percentage
        if progress['overall']['total_tasks'] > 0:
            progress['overall']['completion_percentage'] = (
                progress['overall']['completed_tasks'] / progress['overall']['total_tasks']
            ) * 100
        else:
            progress['overall']['completion_percentage'] = 0.0
        
        return progress

    def list_job_stages(self) -> List[Dict[str, Any]]:
        """
        List all stages for this job type from workflow definition.
        
        Provides stage metadata for job planning and monitoring.
        
        Returns:
            List of stage definition dictionaries
        """
        stages = []
        for stage in self.workflow_definition.stages:
            stage_info = {
                'stage_number': stage.stage_number,
                'stage_name': stage.stage_name,
                'task_type': stage.task_type,
                'is_final_stage': stage.is_final_stage,
                'description': getattr(stage, 'description', f'Stage {stage.stage_number} - {stage.stage_name}')
            }
            stages.append(stage_info)
        
        return stages

    def get_stage_status(self, job_id: str) -> Dict[int, str]:
        """
        Get completion status of each stage.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary mapping stage numbers to status strings
        """
        progress = self.get_task_progress(job_id)
        stage_status = {}
        
        for stage_num, stage_info in progress['stages'].items():
            if stage_info['is_complete']:
                if stage_info['failed_tasks'] > 0:
                    stage_status[stage_num] = 'completed_with_errors'
                else:
                    stage_status[stage_num] = 'completed'
            elif stage_info['processing_tasks'] > 0:
                stage_status[stage_num] = 'processing'
            elif stage_info['failed_tasks'] > 0 and stage_info['processing_tasks'] == 0:
                stage_status[stage_num] = 'failed'
            else:
                stage_status[stage_num] = 'pending'
        
        return stage_status

    def get_completed_stages(self, job_id: str) -> List[int]:
        """
        List completed stage numbers.
        
        Args:
            job_id: The job identifier
            
        Returns:
            List of stage numbers that have completed
        """
        stage_status = self.get_stage_status(job_id)
        completed = [
            stage_num for stage_num, status in stage_status.items() 
            if status in ['completed', 'completed_with_errors']
        ]
        
        self.logger.debug(f"Job {job_id[:16]}... has {len(completed)} completed stages: {completed}")
        return completed

    # ========================================================================
    # EXPLICIT JOB COMPLETION METHOD - Cleaner separation of concerns
    # ========================================================================

    def complete_job(self, job_id: str, all_task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Explicit job completion with full workflow context.
        
        This method provides a clear completion flow that:
        1. Creates complete job execution context from all task results
        2. Calls the abstract aggregate_job_results() for job-specific aggregation
        3. Updates job status to COMPLETED in database
        4. Returns the final aggregated result
        
        This is typically called by the "last task" completion detection.
        
        Args:
            job_id: The job identifier
            all_task_results: List of task results from all stages
            
        Returns:
            Final aggregated job result dictionary
        """
        self.logger.info(f"Starting explicit job completion for {job_id[:16]}... with {len(all_task_results)} task results")
        
        # Create job execution context from task results
        context = self._create_completion_context(job_id, all_task_results)
        self.logger.debug(f"Created completion context with {len(context.stage_results)} stage results")
        
        # Use the abstract method for job-specific aggregation
        self.logger.debug(f"Calling job-specific aggregate_job_results()")
        final_result = self.aggregate_job_results(context)
        self.logger.debug(f"Job aggregation complete: {list(final_result.keys()) if isinstance(final_result, dict) else 'non-dict result'}")
        
        # Store completion in database
        from repository_data import RepositoryFactory
        job_repo, _, _ = RepositoryFactory.create_repositories('postgres')
        
        self.logger.debug(f"Updating job status to COMPLETED in database")
        success = job_repo.complete_job(job_id, final_result)
        
        if success:
            self.logger.info(f"✅ Job {job_id[:16]}... completed successfully with {len(all_task_results)} tasks")
        else:
            self.logger.error(f"❌ Failed to update job completion status for {job_id[:16]}...")
            raise RuntimeError(f"Failed to complete job {job_id} in database")
        
        return final_result

    def _create_completion_context(self, job_id: str, all_task_results: List[Dict[str, Any]]) -> JobExecutionContext:
        """
        Create JobExecutionContext from task results for job completion.
        
        Args:
            job_id: The job identifier
            all_task_results: All task results from all stages
            
        Returns:
            JobExecutionContext with stage results populated
        """
        # Group task results by stage
        stage_results = {}
        
        for task_result in all_task_results:
            stage_num = task_result.get('stage_number', task_result.get('stage', 1))
            
            if stage_num not in stage_results:
                stage_results[stage_num] = {
                    'stage_number': stage_num,
                    'stage_name': f"stage_{stage_num}",
                    'task_results': [],
                    'stage_status': 'completed',
                    'total_tasks': 0,
                    'successful_tasks': 0,
                    'failed_tasks': 0
                }
            
            stage_results[stage_num]['task_results'].append(task_result)
            stage_results[stage_num]['total_tasks'] += 1
            
            if task_result.get('status') == 'completed':
                stage_results[stage_num]['successful_tasks'] += 1
            else:
                stage_results[stage_num]['failed_tasks'] += 1
        
        # Calculate success rates and stage status
        for stage_num, stage_data in stage_results.items():
            total = stage_data['total_tasks']
            successful = stage_data['successful_tasks']
            
            stage_data['success_rate'] = (successful / total * 100) if total > 0 else 0.0
            
            if stage_data['failed_tasks'] == 0:
                stage_data['stage_status'] = 'completed'
            elif stage_data['successful_tasks'] == 0:
                stage_data['stage_status'] = 'failed'
            else:
                stage_data['stage_status'] = 'completed_with_errors'
        
        # Get job parameters (would normally come from job record)
        # For now, create minimal context
        job_context = JobExecutionContext(
            job_id=job_id,
            job_type=self.job_type,
            current_stage=max(stage_results.keys()) if stage_results else 1,
            total_stages=len(self.workflow_definition.stages),
            parameters={'job_type': self.job_type},  # Minimal parameters
            stage_results=stage_results
        )
        
        return job_context

    def process_job_stage(self, job_record: 'JobRecord', stage: int, parameters: Dict[str, Any], stage_results: Dict[int, Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a specific stage by creating and queueing tasks.
        
        This is the main method called by the job queue processor to handle stage execution.
        It creates tasks for the stage and queues them to the task queue for parallel processing.
        
        Args:
            job_record: The job record from storage
            stage: Stage number to process
            parameters: Job parameters
            stage_results: Results from previous stages
            
        Returns:
            Dictionary with stage processing results
        """
        # Defensive programming - handle both JobRecord object and dict
        try:
            if hasattr(job_record, 'job_id'):
                job_id = job_record.job_id
                job_type_from_record = getattr(job_record, 'job_type', 'unknown')
            else:
                # Fallback for dict-like object
                job_id = job_record.get('job_id') or job_record.get('jobId', 'unknown_job_id')
                job_type_from_record = job_record.get('job_type') or job_record.get('jobType', 'unknown')
                self.logger.warning(f"⚠️ job_record is not a JobRecord object, type: {type(job_record)}")
        except Exception as e:
            self.logger.error(f"❌ Failed to extract job_id from job_record: {e}")
            self.logger.error(f"❌ job_record type: {type(job_record)}, content: {job_record}")
            raise RuntimeError(f"Invalid job_record format: {e}")
            
        self.logger.info(f"Processing stage {stage} for job {job_id[:16]}... type={self.job_type} (record_type={job_type_from_record})")
        
        # Create job and stage contexts
        job_context = self.create_job_context(
            job_id=job_id, 
            parameters=parameters,
            current_stage=stage, 
            stage_results=stage_results or {}
        )
        
        stage_context = self.create_stage_context(job_context, stage)
        
        # Create tasks for this stage using the abstract method
        try:
            task_definitions = self.create_stage_tasks(stage_context)
            self.logger.info(f"Created {len(task_definitions)} task definitions for stage {stage}")
        except Exception as e:
            self.logger.error(f"Failed to create stage tasks: {e}")
            raise RuntimeError(f"Failed to create tasks for stage {stage}: {e}")
        
        # Create and store task records, then queue them
        from repository_data import RepositoryFactory
        job_repo, task_repo, _ = RepositoryFactory.create_repositories('postgres')
        
        queued_tasks = 0
        failed_tasks = 0
        
        for i, task_def in enumerate(task_definitions):
            try:
                # Create task record in storage
                task_record = task_repo.create_task(
                    task_id=task_def.task_id,
                    job_id=task_def.job_id,
                    task_type=task_def.task_type,
                    stage_number=task_def.stage_number,
                    task_index=i,
                    parameters=task_def.parameters
                )
                
                # Create task queue message
                from schema_core import TaskQueueMessage
                task_message = TaskQueueMessage(
                    task_id=task_def.task_id,
                    parent_job_id=task_def.job_id,
                    task_type=task_def.task_type,
                    stage=task_def.stage_number,
                    task_index=i,
                    parameters=task_def.parameters
                )
                
                # Queue the task
                from azure.storage.queue import QueueServiceClient
                from azure.identity import DefaultAzureCredential
                from config import get_config
                
                config = get_config()
                account_url = config.queue_service_url
                
                self.logger.debug(f"🔐 Creating DefaultAzureCredential for task queue operations")
                try:
                    credential = DefaultAzureCredential()
                    self.logger.debug(f"✅ DefaultAzureCredential created successfully for tasks")
                except Exception as cred_error:
                    self.logger.error(f"❌ CRITICAL: Failed to create DefaultAzureCredential for task queues: {cred_error}")
                    raise RuntimeError(f"CRITICAL CONFIGURATION ERROR - Managed identity authentication failed for task queues: {cred_error}")
                
                self.logger.debug(f"🔗 Creating QueueServiceClient for tasks with URL: {account_url}")
                try:
                    queue_service = QueueServiceClient(account_url, credential=credential)
                    queue_client = queue_service.get_queue_client(config.task_processing_queue)
                    self.logger.debug(f"📤 Task queue client created for: {config.task_processing_queue}")
                except Exception as queue_error:
                    self.logger.error(f"❌ CRITICAL: Failed to create task QueueServiceClient or queue client: {queue_error}")
                    raise RuntimeError(f"CRITICAL CONFIGURATION ERROR - Azure Storage Task Queue access failed: {queue_error}")
                
                message_json = task_message.model_dump_json()
                queue_client.send_message(message_json)
                
                queued_tasks += 1
                self.logger.debug(f"Task queued: {task_def.task_id}")
                
            except Exception as e:
                self.logger.error(f"Failed to queue task {task_def.task_id}: {e}")
                failed_tasks += 1
        
        stage_result = {
            "stage_number": stage,
            "stage_name": stage_context.stage_name,
            "tasks_created": len(task_definitions),
            "tasks_queued": queued_tasks,
            "tasks_failed_to_queue": failed_tasks,
            "processing_status": "tasks_queued" if queued_tasks > 0 else "failed"
        }
        
        self.logger.info(f"Stage {stage} processing complete: {queued_tasks}/{len(task_definitions)} tasks queued successfully")
        return stage_result

    def __repr__(self):
        return f"<{self.__class__.__name__}(job_type='{self.job_type}', stages={len(self.workflow_definition.stages)})>"