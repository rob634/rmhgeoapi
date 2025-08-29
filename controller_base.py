"""
Abstract Base Controller - Redesign Architecture

Defines the abstract base class for all controllers in the new architecture.
Provides stage orchestration, task fan-out, and completion patterns.

Based on consolidated_redesign.md specifications:
- Job (Controller Layer): Orchestration with job_type specific completion
- Stage (Controller Layer): Sequential coordination 
- Task (Service + Repository Layer): Parallel execution with business logic

"Last task turns out the lights" completion pattern with atomic SQL operations.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import hashlib
import json
import logging

from schema_core import (
    JobStatus, TaskStatus, JobRecord, JobQueueMessage
)
from model_core import (
    TaskDefinition, JobExecutionContext, StageExecutionContext
)
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
        
        # Set job_type if not provided
        parameters = parameters.copy()  # Don't mutate original
        parameters['job_type'] = self.job_type
        
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
        job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories()
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
            jobId=job_id,
            jobType=self.job_type,
            stage=stage,
            parameters=parameters,
            stageResults=stage_results or {}
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
            # Initialize queue client
            account_url = config.queue_service_url
            queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
            queue_client = queue_service.get_queue_client(config.job_processing_queue)
            
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

    def __repr__(self):
        return f"<{self.__class__.__name__}(job_type='{self.job_type}', stages={len(self.workflow_definition.stages)})>"