# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Job completion orchestration implementing "last task turns out lights" pattern
# SOURCE: No direct configuration - operates on passed job/task data and repositories
# SCOPE: Utility-specific completion detection and atomic stage/job transitions
# VALIDATION: Completion logic validation + atomic operation integrity checks
# ============================================================================

"""
Completion Orchestrator - Redesign Architecture

Handles the "Last task turns out the lights" completion pattern.
Provides atomic completion detection and stage/job transitions.

This is a utility class that implements the core completion logic
shared across all controllers in the redesign architecture.
"""

from typing import Dict, Any, Optional, Tuple, List
import logging
import json
from datetime import datetime

from model_core import (
    JobStatus, StageStatus, TaskStatus, JobExecutionContext,
    StageExecutionContext, TaskResult, StageResult, JobResult
)


class CompletionOrchestrator:
    """
    Handles atomic completion detection and stage/job transitions.
    
    Implements the "last task turns out the lights" pattern using
    atomic SQL operations to prevent race conditions between
    parallel tasks checking completion simultaneously.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def check_task_completion(self, task_id: str, job_id: str, stage_number: int,
                            task_result: TaskResult) -> Dict[str, Any]:
        """
        Atomic task completion check with "last task turns out lights" logic.
        
        This method should be called when a task completes. It will:
        1. Mark the task as complete
        2. Check if this is the last task in the stage
        3. If so, trigger stage completion and next stage (or job completion)
        
        Args:
            task_id: ID of the completed task
            job_id: ID of the parent job
            stage_number: Stage number the task belongs to
            task_result: Result data from task execution
            
        Returns:
            Dictionary with completion actions to take
        """
        self.logger.info(f"Checking task completion: {task_id} in job {job_id[:12]}... stage {stage_number}")
        
        # This would contain the atomic SQL operations:
        # 1. UPDATE tasks SET status='completed' WHERE id=$task_id
        # 2. Check if all tasks in stage are complete
        # 3. If so, trigger stage completion
        # 4. Check if this was the final stage
        # 5. If so, trigger job completion
        
        # For now, return the structure of what actions should be taken
        return {
            'task_completed': True,
            'task_id': task_id,
            'job_id': job_id,
            'stage_number': stage_number,
            'is_last_task_in_stage': False,  # Would be determined by SQL query
            'is_final_stage': False,         # Would be determined by job metadata
            'next_actions': []               # List of actions to take (stage_complete, job_complete, etc.)
        }
    
    def aggregate_stage_results(self, job_id: str, stage_number: int,
                              task_results: List[TaskResult]) -> StageResult:
        """
        Aggregate results from all tasks in a stage.
        
        Args:
            job_id: Job ID
            stage_number: Stage number
            task_results: List of results from all tasks in the stage
            
        Returns:
            StageResult with aggregated data
        """
        if not task_results:
            raise ValueError(f"No task results provided for stage {stage_number} in job {job_id}")
        
        # Calculate stage metrics
        successful_tasks = [task for task in task_results if task.success]
        failed_tasks = [task for task in task_results if not task.success]
        
        # Determine stage status
        if len(failed_tasks) == 0:
            stage_status = StageStatus.COMPLETED
        elif len(successful_tasks) == 0:
            stage_status = StageStatus.FAILED
        else:
            # Partial success - concrete controllers can override this logic
            stage_status = StageStatus.COMPLETED  # Default to completed if any tasks succeeded
        
        # Calculate execution time (max of all tasks)
        execution_time = max([task.execution_time_seconds for task in task_results], default=0.0)
        
        stage_name = task_results[0].task_type  # Get from first task, could be improved
        
        stage_result = StageResult(
            stage_number=stage_number,
            stage_name=stage_name,
            status=stage_status,
            task_results=task_results,
            execution_time_seconds=execution_time,
            completed_at=datetime.utcnow().isoformat()
        )
        
        self.logger.info(f"Aggregated stage {stage_number} results: {stage_result.task_count} tasks, "
                        f"{stage_result.successful_tasks} successful, {stage_result.success_rate:.1f}% success rate")
        
        return stage_result
    
    def should_proceed_to_next_stage(self, stage_result: StageResult, 
                                   job_context: JobExecutionContext) -> Tuple[bool, str]:
        """
        Determine if job should proceed to the next stage based on stage results.
        
        Args:
            stage_result: Results from the completed stage
            job_context: Job execution context
            
        Returns:
            Tuple of (should_proceed, reason)
        """
        if stage_result.status == StageStatus.FAILED:
            return False, f"Stage {stage_result.stage_number} failed"
        
        if stage_result.status != StageStatus.COMPLETED:
            return False, f"Stage {stage_result.stage_number} not completed"
        
        # Check if there are more stages
        if stage_result.stage_number >= job_context.total_stages:
            return False, "This is the final stage"
        
        # Additional checks can be added here (e.g., success rate thresholds)
        if stage_result.success_rate < 100.0:
            # Could be configurable per job type
            self.logger.warning(f"Stage {stage_result.stage_number} success rate "
                              f"{stage_result.success_rate:.1f}% but proceeding to next stage")
        
        return True, "Stage completed successfully"
    
    def create_stage_transition_actions(self, job_context: JobExecutionContext, 
                                      completed_stage: StageResult) -> List[Dict[str, Any]]:
        """
        Create actions for transitioning to the next stage.
        
        Args:
            job_context: Job execution context
            completed_stage: Results from the completed stage
            
        Returns:
            List of action dictionaries to execute
        """
        actions = []
        
        # Update job with stage results
        job_context.set_stage_result(completed_stage.stage_number, completed_stage.to_dict())
        
        # Check if should proceed to next stage
        should_proceed, reason = self.should_proceed_to_next_stage(completed_stage, job_context)
        
        if should_proceed:
            next_stage = completed_stage.stage_number + 1
            actions.append({
                'action': 'transition_to_next_stage',
                'job_id': job_context.job_id,
                'next_stage': next_stage,
                'stage_results': job_context.stage_results
            })
        else:
            # This is the final stage or stage failed
            if completed_stage.status == StageStatus.COMPLETED:
                actions.append({
                    'action': 'complete_job',
                    'job_id': job_context.job_id,
                    'final_status': JobStatus.COMPLETED.value,
                    'stage_results': job_context.stage_results
                })
            else:
                actions.append({
                    'action': 'fail_job',
                    'job_id': job_context.job_id,
                    'final_status': JobStatus.FAILED.value,
                    'failure_reason': reason,
                    'stage_results': job_context.stage_results
                })
        
        return actions
    
    def calculate_completion_percentage(self, job_context: JobExecutionContext,
                                     current_stage_progress: Optional[Tuple[int, int]] = None) -> float:
        """
        Calculate job completion percentage.
        
        Args:
            job_context: Job execution context
            current_stage_progress: Optional tuple of (completed_tasks, total_tasks) for current stage
            
        Returns:
            Completion percentage (0.0 to 100.0)
        """
        if job_context.total_stages == 0:
            return 100.0
        
        # Base percentage from completed stages
        completed_stages = len(job_context.stage_results)
        base_percentage = (completed_stages / job_context.total_stages) * 100
        
        # Add progress from current stage if provided
        if current_stage_progress:
            completed_tasks, total_tasks = current_stage_progress
            if total_tasks > 0:
                stage_percentage = (completed_tasks / total_tasks) * (100 / job_context.total_stages)
                base_percentage += stage_percentage
        
        return min(100.0, base_percentage)
    
    def is_zombie_task(self, task_record: Dict[str, Any], max_heartbeat_age_minutes: int = 10) -> bool:
        """
        Check if a task is a zombie (no heartbeat for extended period).
        
        Args:
            task_record: Task record from database
            max_heartbeat_age_minutes: Maximum age of heartbeat before considering zombie
            
        Returns:
            True if task appears to be a zombie
        """
        if task_record.get('status') != TaskStatus.PROCESSING.value:
            return False
        
        heartbeat = task_record.get('heartbeat')
        if not heartbeat:
            return True  # No heartbeat is suspicious
        
        # Parse heartbeat timestamp and check age
        try:
            heartbeat_time = datetime.fromisoformat(heartbeat.replace('Z', '+00:00'))
            age_minutes = (datetime.utcnow() - heartbeat_time).total_seconds() / 60
            return age_minutes > max_heartbeat_age_minutes
        except (ValueError, AttributeError):
            return True  # Invalid heartbeat format
    
    def handle_zombie_recovery(self, zombie_task_ids: List[str], job_id: str) -> Dict[str, Any]:
        """
        Handle recovery from zombie tasks.
        
        Args:
            zombie_task_ids: List of task IDs that appear to be zombies
            job_id: Job ID containing the zombie tasks
            
        Returns:
            Dictionary with recovery actions to take
        """
        self.logger.warning(f"Detected {len(zombie_task_ids)} zombie tasks in job {job_id[:12]}...")
        
        return {
            'zombie_tasks_detected': len(zombie_task_ids),
            'job_id': job_id,
            'zombie_task_ids': zombie_task_ids,
            'recovery_actions': [
                {'action': 'mark_tasks_failed', 'task_ids': zombie_task_ids},
                {'action': 'retry_tasks', 'task_ids': zombie_task_ids, 'max_retries': 3}
            ]
        }