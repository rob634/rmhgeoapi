"""
Base Job - Redesign Architecture

Defines the abstract base class for job state management and completion detection.
Handles job lifecycle, stage transitions, and result aggregation.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json
from datetime import datetime


class JobStatus(Enum):
    """Job status enumeration"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobExecutionContext:
    """Context information for job execution"""
    job_id: str
    job_type: str
    current_stage: int
    total_stages: int
    parameters: Dict[str, Any]
    stage_results: Dict[int, Dict[str, Any]]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BaseJob(ABC):
    """
    Abstract base class for job state management.
    
    Jobs orchestrate stage execution and handle completion detection.
    Implements the "last task turns out the lights" pattern.
    """

    def __init__(self, job_type: str):
        self.job_type = job_type

    @abstractmethod
    def should_proceed_to_next_stage(self, context: JobExecutionContext, 
                                   completed_stage_results: Dict[str, Any]) -> bool:
        """
        Determine if job should proceed to the next stage.
        
        Args:
            context: Job execution context
            completed_stage_results: Results from the completed stage
            
        Returns:
            True if should proceed, False if should stop or fail
        """
        pass

    @abstractmethod
    def aggregate_final_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        Aggregate results from all stages into final job result.
        
        Args:
            context: Job execution context with all stage results
            
        Returns:
            Final aggregated job result
        """
        pass

    def create_job_record(self, job_id: str, job_type: str, parameters: Dict[str, Any], 
                         total_stages: int) -> Dict[str, Any]:
        """Create initial job record"""
        return {
            'id': job_id,
            'job_type': job_type,
            'status': JobStatus.QUEUED.value,
            'stage': 1,  # Start with stage 1
            'parameters': parameters,
            'created_at': None,  # Will be set by repository
            'updated_at': None,  # Will be set by repository
            'metadata': {
                'total_stages': total_stages,
                'current_stage': 1,
                'stage_results': {}
            },
            'result_data': None,
            'error_details': None
        }

    def update_job_status(self, job_id: str, status: JobStatus, 
                         stage: Optional[int] = None, 
                         result_data: Optional[Dict[str, Any]] = None,
                         error_details: Optional[str] = None) -> Dict[str, Any]:
        """Update job status and related fields"""
        update_data = {
            'status': status.value,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if stage is not None:
            update_data['stage'] = stage
            
        if result_data is not None:
            update_data['result_data'] = json.dumps(result_data) if isinstance(result_data, dict) else result_data
            
        if error_details is not None:
            update_data['error_details'] = error_details
            
        return update_data

    def is_stage_complete(self, job_id: str, stage_number: int, 
                         completed_tasks: int, total_tasks: int) -> bool:
        """Check if all tasks in a stage are complete"""
        return completed_tasks >= total_tasks

    def should_transition_to_next_stage(self, current_stage: int, total_stages: int, 
                                      stage_results: Dict[str, Any]) -> bool:
        """
        Determine if job should transition to next stage.
        
        Base implementation checks if current stage succeeded and there are more stages.
        """
        if current_stage >= total_stages:
            return False
            
        # Check if current stage succeeded
        stage_status = stage_results.get('stage_status')
        return stage_status == 'completed'

    def is_final_stage(self, current_stage: int, total_stages: int) -> bool:
        """Check if current stage is the final stage"""
        return current_stage >= total_stages

    def calculate_job_completion_percentage(self, current_stage: int, total_stages: int,
                                          stage_task_progress: Optional[Dict[int, Tuple[int, int]]] = None) -> float:
        """
        Calculate job completion percentage.
        
        Args:
            current_stage: Current stage number
            total_stages: Total number of stages
            stage_task_progress: Optional dict of {stage_number: (completed_tasks, total_tasks)}
            
        Returns:
            Completion percentage (0.0 to 100.0)
        """
        if total_stages == 0:
            return 100.0
            
        # Base percentage from completed stages
        completed_stages = max(0, current_stage - 1)
        base_percentage = (completed_stages / total_stages) * 100
        
        # Add progress from current stage if provided
        if stage_task_progress and current_stage in stage_task_progress:
            completed_tasks, total_tasks = stage_task_progress[current_stage]
            if total_tasks > 0:
                stage_percentage = (completed_tasks / total_tasks) * (100 / total_stages)
                base_percentage += stage_percentage
                
        return min(100.0, base_percentage)

    def create_stage_transition_message(self, job_id: str, next_stage: int, 
                                      parameters: Dict[str, Any],
                                      stage_results: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        """Create queue message for next stage execution"""
        return {
            'job_id': job_id,
            'job_type': self.job_type,
            'stage': next_stage,
            'parameters': parameters,
            'stage_results': stage_results
        }

    def create_job_completion_message(self, job_id: str, final_results: Dict[str, Any]) -> Dict[str, Any]:
        """Create message for job completion processing"""
        return {
            'job_id': job_id,
            'job_type': self.job_type,
            'action': 'complete_job',
            'final_results': final_results,
            'completed_at': datetime.utcnow().isoformat()
        }

    def handle_job_failure(self, context: JobExecutionContext, error: Exception,
                          failed_stage: int) -> Dict[str, Any]:
        """
        Handle job failure at a specific stage.
        
        Prepares failure information for storage and potential retry.
        """
        return {
            'job_id': context.job_id,
            'job_type': context.job_type,
            'status': JobStatus.FAILED.value,
            'failed_at': datetime.utcnow().isoformat(),
            'failed_stage': failed_stage,
            'error_type': error.__class__.__name__,
            'error_message': str(error),
            'stage_results': context.stage_results  # Preserve completed stage results
        }

    def extract_job_metrics(self, context: JobExecutionContext, 
                           execution_start: str, execution_end: str) -> Dict[str, Any]:
        """
        Extract metrics from job execution for monitoring.
        
        Base implementation extracts basic metrics.
        Concrete jobs can override for custom metrics.
        """
        start_time = datetime.fromisoformat(execution_start.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(execution_end.replace('Z', '+00:00'))
        execution_time = (end_time - start_time).total_seconds()
        
        return {
            'job_type': context.job_type,
            'total_stages': context.total_stages,
            'execution_time_seconds': execution_time,
            'stages_completed': len(context.stage_results),
            'success': True,  # Override in failure cases
            'parameters_hash': hash(json.dumps(context.parameters, sort_keys=True))
        }

    def validate_job_completion(self, context: JobExecutionContext) -> Tuple[bool, str]:
        """
        Validate that job has completed successfully.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check all stages have results
        for stage_num in range(1, context.total_stages + 1):
            if stage_num not in context.stage_results:
                return False, f"Missing results for stage {stage_num}"
                
            stage_result = context.stage_results[stage_num]
            if stage_result.get('stage_status') != 'completed':
                return False, f"Stage {stage_num} did not complete successfully"
                
        return True, ""

    def __repr__(self):
        return f"<{self.__class__.__name__}(job_type='{self.job_type}')>"