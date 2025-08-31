# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Abstract job model base class for workflow orchestration and state management
# SOURCE: No direct configuration - provides job lifecycle management patterns
# SCOPE: Job-specific workflow orchestration foundation for all job type implementations
# VALIDATION: Pydantic v2 job parameter validation with lifecycle state constraints
# ============================================================================

"""
Base Job Model - Job→Stage→Task Architecture Core

Abstract base class defining the job lifecycle management patterns for the Azure Geospatial
ETL Pipeline. Provides comprehensive job state management, stage transition logic, completion
detection mechanisms, and result aggregation patterns that concrete job implementations
must customize for their specific workflows.

Architecture Responsibility:
    This module defines the JOB LAYER within the Job→Stage→Task architecture:
    - Job Layer: THIS MODULE - Workflow orchestration and state management
    - Stage Layer: Coordinates parallel task execution within workflow phases
    - Task Layer: Implements business logic for individual processing units
    - Repository Layer: Handles persistent storage and retrieval operations

Key Features:
- Abstract base class enforcing consistent job implementation patterns
- "Last task turns out the lights" completion detection with atomic operations
- Multi-stage workflow coordination with inter-stage data passing
- Comprehensive job lifecycle management (creation, processing, completion)
- Built-in progress tracking and completion percentage calculations
- Failure handling with stage-level error isolation and recovery options
- Job metrics extraction for monitoring and performance analysis
- Validation framework ensuring job integrity and successful completion

Job Lifecycle Stages:
    1. CREATION: BaseJob.create_job_record() → Initial job record with metadata
    2. QUEUING: Job parameters validated and queued for async processing
    3. STAGE EXECUTION: Sequential stage processing with parallel task execution
    4. STAGE COMPLETION: BaseJob.is_stage_complete() → Atomic completion detection
    5. STAGE TRANSITION: BaseJob.should_transition_to_next_stage() → Next stage logic
    6. FINAL AGGREGATION: BaseJob.aggregate_final_results() → Result consolidation
    7. COMPLETION: Job marked complete with final results stored

Completion Detection Pattern:
    The "last task turns out the lights" pattern ensures atomic stage completion:
    - Tasks complete independently and update their status
    - Final task in stage performs atomic completion check
    - Stage transitions only occur when ALL tasks complete
    - Race conditions prevented through repository-level atomic operations

Stage Transition Flow:
    STAGE 1 (All tasks complete)
         ↓ should_transition_to_next_stage()
    STAGE 2 (All tasks complete) 
         ↓ is_final_stage() = True
    JOB COMPLETION → aggregate_final_results()

Integration Points:
- Extended by concrete job controllers (HelloWorldController, etc.)
- Uses JobExecutionContext for state passing between stages
- Integrates with repository layer for persistent state management
- Connects to queue systems for asynchronous stage processing
- Provides metrics to monitoring systems for performance tracking

Abstract Methods (Must Implement):
- should_proceed_to_next_stage(): Custom logic for stage progression
- aggregate_final_results(): Job-specific result consolidation

Concrete Methods (Ready to Use):
- create_job_record(): Standardized job record creation
- update_job_status(): Status and metadata updates
- calculate_job_completion_percentage(): Progress tracking
- handle_job_failure(): Error handling and recovery
- validate_job_completion(): Final integrity checks

Usage Example:
    class CustomJobController(BaseJob):
        def __init__(self):
            super().__init__("custom_job")
        
        def should_proceed_to_next_stage(self, context, results):
            # Custom stage progression logic
            return results.get('success', False)
        
        def aggregate_final_results(self, context):
            # Custom result aggregation
            return {"total_processed": sum_results(context.stage_results)}

Author: Azure Geospatial ETL Team
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