"""
Centralized task management for the Job→Task architecture.

This module provides a centralized manager for task operations,
including task creation, ID generation, state tracking, job completion
detection, and coordination with repositories.

Key Features:
    - Deterministic task ID generation
    - Task lifecycle management (creation → queued → processing → completed/failed)
    - Distributed job completion detection ("last task wins" pattern)
    - Task result aggregation for job completion
    - Atomic job status updates with comprehensive result data

Architecture Pattern:
    Jobs (user-facing orchestration) → Tasks (atomic work units)
    
    Each task completion triggers a job completion check where:
    1. Task updates its own status to completed/failed
    2. Task queries all other tasks for the same job
    3. If all tasks are done, task updates job status with aggregated results
    4. This creates an "N² query pattern" that's efficient for <5,000 tasks

Job Completion Flow:
    Task 1 completes → Check: Are we all done? → No, continue
    Task 2 completes → Check: Are we all done? → No, continue  
    Task N completes → Check: Are we all done? → Yes! Update job to completed

Result Data Aggregation:
    When job completes, result_data includes:
    - Summary of task counts and status
    - Sample task results (limited for storage efficiency)
    - Error details from failed tasks
    - Completion timestamps

Author: Azure Geospatial ETL Team
Version: 1.1.0 - Enhanced with result aggregation and completion detection
"""
import hashlib
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from repositories import TaskRepository, JobRepository
from logger_setup import get_logger

logger = get_logger(__name__)


class TaskManager:
    """
    Centralized task management service for the Job→Task architecture.
    
    This class orchestrates the complete task lifecycle and implements the
    "distributed job completion detection" pattern where each completing task
    checks if the entire job is done.
    
    Core Responsibilities:
        - Task ID generation (deterministic SHA256-based)
        - Task creation and storage in Azure Table Storage
        - Task state transitions (queued → processing → completed/failed)
        - Job completion detection via "last task wins" pattern
        - Task result aggregation into job-level result_data
        - Job-task relationship management and lineage tracking
    
    Architecture Benefits:
        - No separate orchestrator needed for job completion
        - Real-time job completion (instant when last task finishes)
        - Fault tolerant (if tasks fail, others continue checking)
        - Scales efficiently for 10-5,000 tasks per job
    
    Completion Detection Algorithm:
        1. Every task completion calls check_job_completion()
        2. Method queries ALL tasks for the job (N² pattern)
        3. Counts completed vs total tasks
        4. If all done, aggregates results and updates job status
        5. Only the last task actually performs the job completion
    
    Performance Characteristics:
        - Sweet spot: 10-1,000 tasks (current workload)
        - Acceptable: 1,000-5,000 tasks
        - Redesign needed: >5,000 tasks (becomes N² expensive)
    
    Usage Example:
        manager = TaskManager()
        task_ids = manager.create_tasks(job_id, task_definitions)
        # Tasks execute independently...
        # Last task completion automatically updates job status
    """
    
    def __init__(self):
        """Initialize task manager with repositories."""
        self.task_repo = TaskRepository()
        self.job_repo = JobRepository()
        self.logger = get_logger(self.__class__.__name__)
    
    def generate_task_id(self, job_id: str, task_type: str, 
                        index: int = 0, params: Dict = None) -> str:
        """
        Generate a deterministic task ID.
        
        Creates consistent task IDs that are reproducible for the same inputs,
        enabling idempotency.
        
        Args:
            job_id: Parent job ID
            task_type: Type of task (e.g., 'cog_conversion', 'validation')
            index: Task index for multiple similar tasks
            params: Optional parameters to include in hash
            
        Returns:
            str: Deterministic task ID (16 chars)
        """
        # Build deterministic string
        id_parts = {
            'job_id': job_id,
            'task_type': task_type,
            'index': index
        }
        
        # Add optional parameters if provided
        if params:
            # Only include deterministic params (not timestamps)
            deterministic_params = {
                k: v for k, v in params.items()
                if k not in ['created_at', 'updated_at', 'timestamp']
            }
            id_parts['params'] = deterministic_params
        
        # Create hash
        id_string = json.dumps(id_parts, sort_keys=True)
        full_hash = hashlib.sha256(id_string.encode()).hexdigest()
        
        # Return first 16 chars for shorter IDs
        return full_hash[:16]
    
    def create_task(self, job_id: str, task_type: str, task_data: Dict[str, Any],
                   index: int = 0) -> Optional[str]:
        """
        Create a new task and store it in the repository.
        
        Args:
            job_id: Parent job ID
            task_type: Type of task
            task_data: Task payload data
            index: Task index for ordering
            
        Returns:
            str: Task ID if created successfully, None if exists
        """
        try:
            # Generate task ID
            task_id = self.generate_task_id(job_id, task_type, index, task_data)
            
            # Add metadata to task data
            task_data.update({
                'task_id': task_id,
                'parent_job_id': job_id,
                'task_type': task_type,
                'index': index,
                'status': 'queued',
                'created_at': datetime.utcnow().isoformat()
            })
            
            # Store in repository
            if self.task_repo.create_task(task_id, job_id, task_data):
                self.logger.info(f"Created task {task_id} for job {job_id}")
                return task_id
            else:
                self.logger.debug(f"Task already exists: {task_id}")
                return task_id  # Return existing task ID for idempotency
                
        except Exception as e:
            self.logger.error(f"Failed to create task: {e}")
            return None
    
    def create_tasks_batch(self, job_id: str, task_definitions: List[Dict]) -> List[str]:
        """
        Create multiple tasks in batch with optimized performance.
        
        Efficiently creates multiple tasks by minimizing database calls and
        using batch operations where possible. Particularly useful for fan-out
        patterns where one job creates many parallel tasks.
        
        Performance Optimizations:
            - Pre-generates all task IDs before any DB operations
            - Validates all definitions before creating any tasks
            - Returns partial success list if some tasks fail
            - Logs detailed metrics for monitoring
        
        Args:
            job_id: Parent job ID
            task_definitions: List of task definitions, each containing:
                - task_type (str): Type of task (e.g., 'cog_conversion')
                - task_data (dict): Task payload with operation parameters
                - index (int, optional): Task ordering index (auto-assigned if missing)
                
        Returns:
            List[str]: Successfully created task IDs (may be partial on failure)
            
        Example:
            >>> definitions = [
            ...     {'task_type': 'validate', 'task_data': {'file': 'a.tif'}},
            ...     {'task_type': 'convert', 'task_data': {'file': 'b.tif'}},
            ...     {'task_type': 'catalog', 'task_data': {'file': 'c.tif'}}
            ... ]
            >>> task_ids = manager.create_tasks_batch(job_id, definitions)
            >>> print(f"Created {len(task_ids)} tasks")
            
        Note:
            For large batches (>100 tasks), consider using create_task directly
            in chunks to avoid memory issues with very large definition lists.
        """
        if not task_definitions:
            self.logger.warning(f"No task definitions provided for job {job_id}")
            return []
        
        task_ids = []
        failed_count = 0
        start_time = datetime.utcnow()
        
        # Validate and prepare all tasks first
        prepared_tasks = []
        for i, definition in enumerate(task_definitions):
            try:
                task_type = definition.get('task_type', 'generic')
                task_data = definition.get('task_data', {})
                index = definition.get('index', i)
                
                # Pre-generate task ID for validation
                task_id = self.generate_task_id(job_id, task_type, index, task_data)
                prepared_tasks.append((task_id, task_type, task_data, index))
            except Exception as e:
                self.logger.error(f"Failed to prepare task {i}: {e}")
                failed_count += 1
        
        # Create all prepared tasks
        for task_id, task_type, task_data, index in prepared_tasks:
            try:
                # create_task handles idempotency internally
                created_id = self.create_task(job_id, task_type, task_data, index)
                if created_id:
                    task_ids.append(created_id)
                else:
                    failed_count += 1
            except Exception as e:
                self.logger.error(f"Failed to create task {task_id}: {e}")
                failed_count += 1
        
        # Log performance metrics
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        self.logger.info(
            f"Batch created {len(task_ids)}/{len(task_definitions)} tasks "
            f"for job {job_id} in {elapsed:.2f}s "
            f"({len(task_ids)/elapsed:.1f} tasks/sec)" if elapsed > 0 else ""
        )
        
        if failed_count > 0:
            self.logger.warning(f"{failed_count} tasks failed to create for job {job_id}")
        
        return task_ids
    
    def update_task_status(self, task_id: str, status: str, 
                          metadata: Dict = None) -> bool:
        """
        Update task status with optional metadata.
        
        Args:
            task_id: Task to update
            status: New status
            metadata: Optional metadata to store
            
        Returns:
            bool: True if updated successfully
        """
        try:
            # Add timestamp to metadata
            if metadata is None:
                metadata = {}
            metadata['updated_at'] = datetime.utcnow().isoformat()
            metadata['status'] = status
            
            # Update in repository
            result = self.task_repo.update_task_status(task_id, status, metadata)
            
            # Check if this affects job completion
            task = self.task_repo.get_task(task_id)
            if task and status in ['completed', 'failed']:
                job_id = task.get('parent_job_id')
                
                # Check for stage completion and advancement (for sequential jobs)
                if status == 'completed':
                    self.check_stage_completion_and_advance(job_id, task_id)
                
                # Check overall job completion
                self._check_job_completion(job_id)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to update task {task_id} status: {e}")
            return False
    
    def _check_job_completion(self, job_id: str) -> None:
        """
        Check if all tasks for a job are complete and update job status.
        
        Args:
            job_id: Job to check
        """
        if not job_id:
            return
        
        try:
            # Get all tasks for this job
            tasks = self.task_repo.get_tasks_for_job(job_id)
            if not tasks:
                return
            
            # Count task statuses
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get('status') == 'completed')
            failed = sum(1 for t in tasks if t.get('status') == 'failed')
            
            # Update job metadata
            job_metadata = {
                'total_tasks': total,
                'completed_tasks': completed,
                'failed_tasks': failed,
                'progress_percentage': (completed + failed) / total * 100
            }
            
            # Determine job status
            if completed + failed == total:
                # All tasks finished - aggregate results
                task_results = []
                for task in tasks:
                    task_result = {
                        'task_id': task.get('task_id'),
                        'task_type': task.get('task_type'),
                        'status': task.get('status'),
                        'result': task.get('result_data'),
                        'error': task.get('error_message')
                    }
                    task_results.append(task_result)
                
                # Build aggregated result_data
                result_data = {
                    'task_results': task_results,
                    'task_summary': {
                        'total_tasks': total,
                        'successful_tasks': completed,
                        'failed_tasks': failed
                    }
                }
                
                # Add job-specific result aggregation (for hello_world)
                self._aggregate_job_specific_results(result_data, tasks)
                
                # Update job with aggregated results
                job_metadata.update({'result_data': result_data})
                
                if failed == 0:
                    # All succeeded
                    self.job_repo.update_job_status(job_id, 'completed', job_metadata)
                    self.logger.info(f"Job {job_id} completed successfully with {completed} tasks")
                elif completed == 0:
                    # All failed
                    self.job_repo.update_job_status(job_id, 'failed', job_metadata)
                    self.logger.error(f"Job {job_id} failed - all tasks failed")
                else:
                    # Partial success
                    self.job_repo.update_job_status(job_id, 'completed_with_errors', job_metadata)
                    self.logger.warning(f"Job {job_id} completed with {failed} failed tasks")
            else:
                # Still processing
                self.job_repo.update_job_status(job_id, 'processing', job_metadata)
                
        except Exception as e:
            self.logger.error(f"Failed to check job completion for {job_id}: {e}")
    
    def _aggregate_job_specific_results(self, result_data: Dict, tasks: List[Dict]) -> None:
        """
        Aggregate job-specific results based on task types.
        
        Args:
            result_data: Job result data to modify
            tasks: List of completed tasks
        """
        try:
            # Check if this is a hello_world job
            task_types = [task.get('task_type') for task in tasks]
            if 'hello_world' in task_types:
                self._aggregate_hello_world_results(result_data, tasks)
                
        except Exception as e:
            self.logger.error(f"Failed to aggregate job-specific results: {e}")
    
    def _aggregate_hello_world_results(self, result_data: Dict, tasks: List[Dict]) -> None:
        """
        Aggregate hello_world job results into hello_statistics and hello_messages.
        
        Args:
            result_data: Job result data to modify
            tasks: List of completed tasks
        """
        hello_messages = []
        successful_hellos = 0
        failed_hellos = 0
        failed_hello_numbers = []
        
        for task in tasks:
            if task.get('task_type') == 'hello_world':
                if task.get('status') == 'completed':
                    successful_hellos += 1
                    task_result = task.get('result_data')
                    if task_result and isinstance(task_result, dict):
                        greeting = task_result.get('greeting')
                        if greeting:
                            hello_messages.append(greeting)
                elif task.get('status') == 'failed':
                    failed_hellos += 1
                    task_result = task.get('result_data')
                    if task_result and isinstance(task_result, dict):
                        hello_number = task_result.get('hello_number')
                        if hello_number:
                            failed_hello_numbers.append(hello_number)
        
        total_hellos = successful_hellos + failed_hellos
        success_rate = (successful_hellos / total_hellos * 100) if total_hellos > 0 else 0
        
        # Add hello_world specific aggregation
        result_data['hello_statistics'] = {
            'total_hellos_requested': total_hellos,
            'hellos_completed_successfully': successful_hellos,
            'hellos_failed': failed_hellos,
            'success_rate': round(success_rate, 1)
        }
        
        if failed_hello_numbers:
            result_data['hello_statistics']['failed_hello_numbers'] = failed_hello_numbers
            
        result_data['hello_messages'] = hello_messages
    
    def check_and_update_job_status(self, job_id: str):
        """
        Check task completion and update job status with aggregated results.
        
        This is the core of the "distributed job completion detection" pattern.
        Called by every task upon completion to check if the entire job is done.
        
        Algorithm:
            1. Query ALL tasks for this job (creates N² query pattern)
            2. Count completed, failed, and total tasks
            3. Collect task results and error messages
            4. If all tasks done:
               - Aggregate results into comprehensive result_data
               - Update job status (completed/failed/completed_with_errors)
               - Include task summaries, results, and timestamps
            5. If still processing, update progress metadata only
        
        Performance Impact:
            - Called N times (once per task completion)
            - Queries N tasks each time = N² total queries
            - Efficient for <5,000 tasks, expensive beyond that
        
        Result Data Structure:
            For successful jobs:
            {
                'status': 'completed',
                'message': 'Job completed successfully with N tasks',
                'summary': {'total_tasks': N, 'completed_tasks': N, 'failed_tasks': 0},
                'task_results': [{'task_id': '...', 'result': {...}}, ...],
                'completed_at': '2025-08-27T17:30:00Z'
            }
            
            For failed jobs:
            {
                'status': 'failed', 
                'message': 'All N tasks failed',
                'task_errors': [{'task_id': '...', 'error': '...'}, ...],
                'failed_at': '2025-08-27T17:30:00Z'
            }
        
        Args:
            job_id: Job to check and potentially complete
            
        Note:
            Only the LAST task to complete actually performs the job status update.
            All other tasks see "still processing" and exit without updating job.
        """
        try:
            self.logger.debug(f"📊 Checking and updating job status for: {job_id}")
            
            # Get all tasks for this job
            tasks = self.task_repo.get_tasks_for_job(job_id)
            if not tasks:
                self.logger.warning(f"  No tasks found for job {job_id} - cannot update status")
                return
            
            # Count task statuses - only valid statuses: queued, processing, completed, failed
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get('status') == 'completed')
            failed = sum(1 for t in tasks if t.get('status') == 'failed')
            queued = sum(1 for t in tasks if t.get('status') == 'queued')
            processing = sum(1 for t in tasks if t.get('status') == 'processing')
            
            self.logger.debug(f"  Task counts - Total: {total}, Completed: {completed}, Failed: {failed}, Queued: {queued}, Processing: {processing}")
            
            # CRITICAL: Job is only complete when NO tasks are queued/processing
            active_tasks = queued + processing
            finished_tasks = completed + failed
            
            # Collect task results for job completion
            task_results = []
            error_messages = []
            
            for task in tasks:
                task_status = task.get('status')
                task_id = task.get('task_id')
                
                if task_status == 'completed':
                    # Get task result if available
                    result = task.get('result')
                    if result:
                        task_results.append({
                            'task_id': task_id,
                            'task_type': task.get('task_type') or task.get('operation_type'),
                            'resource_id': task.get('resource_id'),
                            'status': 'completed',
                            'result': result
                        })
                elif task_status == 'failed':
                    # Collect error information
                    error_msg = task.get('error_message', 'Task failed')
                    error_messages.append({
                        'task_id': task_id,
                        'task_type': task.get('task_type') or task.get('operation_type'),
                        'resource_id': task.get('resource_id'),
                        'error': error_msg
                    })
            
            # Update job metadata
            job_metadata = {
                'total_tasks': total,
                'completed_tasks': completed,
                'failed_tasks': failed,
                'queued_tasks': queued,
                'processing_tasks': processing,
                'progress_percentage': (finished_tasks) / total * 100 if total > 0 else 0,
                'task_results': task_results,
                'task_errors': error_messages if error_messages else None
            }
            
            # Determine job status - FIXED: Only complete when NO active tasks
            if active_tasks == 0 and finished_tasks == total:
                # All tasks finished
                if failed == 0:
                    # All succeeded - prepare result data
                    result_data = {
                        'status': 'completed',
                        'message': f'Job completed successfully with {total} tasks',
                        'summary': {
                            'total_tasks': total,
                            'completed_tasks': completed,
                            'failed_tasks': failed
                        },
                        'task_results': task_results[:10],  # Limit to first 10 for storage efficiency
                        'completed_at': datetime.utcnow().isoformat()
                    }
                    
                    # Add job-specific result aggregation (hello_world, etc.)
                    self._aggregate_job_specific_results(result_data, tasks)
                    
                    self.logger.info(f"✅ All {total} tasks completed successfully - updating job to COMPLETED")
                    self.job_repo.update_job_status(job_id, 'completed', job_metadata, result_data=result_data)
                    self.logger.info(f"🎉 Job {job_id} marked as COMPLETED with result data")
                elif completed == 0:
                    # All failed - prepare error message
                    error_msg = f'All {total} tasks failed'
                    result_data = {
                        'status': 'failed',
                        'message': error_msg,
                        'summary': {
                            'total_tasks': total,
                            'completed_tasks': completed,
                            'failed_tasks': failed
                        },
                        'task_errors': error_messages[:10],  # Limit to first 10 for storage efficiency
                        'failed_at': datetime.utcnow().isoformat()
                    }
                    
                    self.logger.error(f"❌ All {total} tasks failed - updating job to FAILED")
                    self.job_repo.update_job_status(job_id, 'failed', job_metadata, error_message=error_msg, result_data=result_data)
                    self.logger.error(f"💀 Job {job_id} marked as FAILED with error data")
                else:
                    # Partial success - prepare mixed result
                    result_data = {
                        'status': 'completed_with_errors',
                        'message': f'Job completed with {completed} successful and {failed} failed tasks',
                        'summary': {
                            'total_tasks': total,
                            'completed_tasks': completed,
                            'failed_tasks': failed
                        },
                        'task_results': task_results[:5],  # Limited successful results
                        'task_errors': error_messages[:5],  # Limited error results
                        'completed_at': datetime.utcnow().isoformat()
                    }
                    
                    # Add job-specific result aggregation (hello_world, etc.) for successful tasks
                    self._aggregate_job_specific_results(result_data, tasks)
                    
                    self.logger.warning(f"⚠️ {completed} tasks succeeded, {failed} failed - updating job to COMPLETED_WITH_ERRORS")
                    self.job_repo.update_job_status(job_id, 'completed_with_errors', job_metadata, result_data=result_data)
                    self.logger.warning(f"⚠️ Job {job_id} marked as COMPLETED_WITH_ERRORS with mixed result data")
            else:
                # Still processing - tasks are queued or processing
                self.logger.debug(f"  Job still processing - {active_tasks} active tasks remaining (Queued: {queued}, Processing: {processing})")
                self.job_repo.update_job_status(job_id, 'processing', job_metadata)
                
        except Exception as e:
            self.logger.error(f"❌ Failed to check and update job status for {job_id}: {e}", exc_info=True)
    
    def check_job_completion(self, job_id: str) -> bool:
        """
        Public interface for checking job completion status.
        
        This method is called from the Azure Functions task processor 
        (function_app.py) after every task completion to determine if
        the job is done.
        
        Workflow:
            1. Calls check_and_update_job_status() to handle completion logic
            2. Queries all tasks to determine completion status
            3. Returns boolean indicating if job is complete
            
        Called From:
            - function_app.py:1170 (after successful task completion)
            - function_app.py:1190 (after task failure)
            
        Completion Logic:
            A job is "complete" when all tasks are in terminal states:
            - completed_tasks + failed_tasks == total_tasks
            
        Side Effects:
            - May update job status to completed/failed if this is the last task
            - May aggregate task results into job result_data
            - Logs completion status for monitoring
        
        Args:
            job_id: Job identifier to check
            
        Returns:
            bool: True if all tasks are complete (succeeded OR failed)
                  False if any tasks are still queued/processing
                  
        Example Usage:
            # In Azure Functions task processor
            task_manager = TaskManager()
            job_complete = task_manager.check_job_completion(parent_job_id)
            if job_complete:
                logger.info("🎉 All tasks completed for job")
            else:
                logger.info("⏳ Job still has pending tasks")
        """
        try:
            self.logger.debug(f"🔍 Checking job completion for job: {job_id}")
            
            # Check and update job status
            self.logger.debug(f"  Calling check_and_update_job_status()")
            self.check_and_update_job_status(job_id)
            
            # Get all tasks for this job
            self.logger.debug(f"  Getting all tasks for job: {job_id}")
            tasks = self.task_repo.get_tasks_for_job(job_id)
            if not tasks:
                self.logger.warning(f"  No tasks found for job {job_id}")
                return False
            
            # Check if all tasks are in terminal state
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get('status') == 'completed')
            failed = sum(1 for t in tasks if t.get('status') == 'failed')
            processing = sum(1 for t in tasks if t.get('status') == 'processing')
            queued = sum(1 for t in tasks if t.get('status') == 'queued')
            
            self.logger.info(f"  Job {job_id} task status summary:")
            self.logger.info(f"    Total: {total}, Completed: {completed}, Failed: {failed}, Processing: {processing}, Queued: {queued}")
            
            all_done = (completed + failed) == total
            self.logger.info(f"  All tasks complete: {all_done}")
            
            return all_done
            
        except Exception as e:
            self.logger.error(f"❌ Failed to check job completion for {job_id}: {e}", exc_info=True)
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """
        Get task details.
        
        Args:
            task_id: Task to retrieve
            
        Returns:
            Dict: Task data or None if not found
        """
        return self.task_repo.get_task(task_id)
    
    def get_tasks_for_job(self, job_id: str) -> List[Dict]:
        """
        Get all tasks for a job.
        
        Args:
            job_id: Parent job ID
            
        Returns:
            List[Dict]: List of tasks
        """
        return self.task_repo.get_tasks_for_job(job_id)
    
    def get_next_task(self, job_id: str, current_index: int) -> Optional[Dict]:
        """
        Get the next task in sequence for a job.
        
        Args:
            job_id: Parent job ID
            current_index: Current task index
            
        Returns:
            Dict: Next task or None if no more tasks
        """
        tasks = self.get_tasks_for_job(job_id)
        
        # Sort by index
        sorted_tasks = sorted(tasks, key=lambda t: t.get('index', 0))
        
        # Find next task after current index
        for task in sorted_tasks:
            if task.get('index', 0) > current_index:
                return task
        
        return None
    
    def validate_task_transition(self, task_id: str, from_status: str, 
                                 to_status: str) -> bool:
        """
        Validate if a task status transition is allowed.
        
        Args:
            task_id: Task to transition
            from_status: Current status
            to_status: Desired status
            
        Returns:
            bool: True if transition is valid
        """
        # Define valid transitions
        valid_transitions = {
            'pending': ['queued', 'processing', 'failed'],
            'queued': ['processing', 'failed'],
            'processing': ['completed', 'failed'],
            'failed': ['pending', 'queued'],  # Allow retry
            'completed': []  # Terminal state
        }
        
        allowed = valid_transitions.get(from_status, [])
        
        if to_status not in allowed:
            self.logger.warning(
                f"Invalid task transition for {task_id}: {from_status} -> {to_status}"
            )
            return False
        
        return True
    
    # ========================================
    # STAGE MANAGEMENT METHODS (Job Chaining)
    # ========================================
    
    def check_stage_completion_and_advance(self, job_id: str, completed_task_id: str):
        """
        Check if current stage is complete and advance to next stage if ready.
        
        This is the core method for sequential job chaining. Called when any task
        completes to check if the entire current stage is done, and if so, advance
        to the next stage by creating new tasks.
        
        Algorithm:
        1. Get current job state and stage information
        2. Get all tasks for current stage
        3. Check if all current stage tasks are complete
        4. If complete:
           - Record stage completion with actual timing
           - If more stages remain: advance to next stage
           - If all stages done: complete the sequential job
        
        Args:
            job_id: Job to check for stage completion
            completed_task_id: ID of the task that just completed
        """
        try:
            self.logger.debug(f"🎯 Checking stage completion for job {job_id} after task {completed_task_id[:8]}... completed")
            
            # Get current job state
            job = self.job_repo.get_job(job_id)
            if not job:
                self.logger.warning(f"Job {job_id} not found for stage completion check")
                return
            
            current_stage = job.get('current_stage_n', 1)
            total_stages = job.get('stages', 1)
            
            self.logger.debug(f"  Current stage: {current_stage}/{total_stages}")
            
            # Get all tasks for current stage
            stage_tasks = self._get_stage_tasks(job_id, current_stage)
            completed_tasks = [t for t in stage_tasks if t.get('status') == 'completed']
            
            self.logger.debug(f"  Stage {current_stage} tasks: {len(completed_tasks)}/{len(stage_tasks)} completed")
            
            # Check if current stage is complete
            if len(completed_tasks) == len(stage_tasks) and len(stage_tasks) > 0:
                self.logger.info(f"🎯 Stage {current_stage} completed for job {job_id} - all {len(stage_tasks)} tasks finished")
                
                # Record stage completion with actual timing
                self._record_stage_completion(job_id, current_stage, completed_tasks)
                
                if current_stage < total_stages:
                    # Advance to next stage
                    self._advance_to_next_stage(job_id, completed_tasks)
                else:
                    # All stages completed - finish sequential job
                    self._complete_sequential_job(job_id, completed_tasks)
            else:
                self.logger.debug(f"  Stage {current_stage} still processing: {len(completed_tasks)}/{len(stage_tasks)} tasks done")
                
        except Exception as e:
            self.logger.error(f"Failed to check stage completion for job {job_id}: {e}")
    
    def _get_stage_tasks(self, job_id: str, stage_n: int) -> List[Dict]:
        """
        Get all tasks for a specific stage of a job.
        
        Args:
            job_id: Job identifier
            stage_n: Stage number (1, 2, 3, etc.)
            
        Returns:
            List[Dict]: Tasks for the specified stage
        """
        try:
            # Get all tasks for this job
            all_tasks = self.task_repo.get_tasks_for_job(job_id)
            
            # Filter tasks by stage - check task_data for stage information
            stage_tasks = []
            for task in all_tasks:
                task_data = task.get('task_data', '{}')
                if isinstance(task_data, str):
                    try:
                        task_data = json.loads(task_data)
                    except:
                        task_data = {}
                
                # Check if task belongs to this stage
                task_stage = task_data.get('stage')
                if task_stage == stage_n:
                    stage_tasks.append(task)
                elif task.get('task_type', '').endswith(f'_stage{stage_n}'):
                    # Alternative: check task_type suffix (e.g., hello_world_stage1)
                    stage_tasks.append(task)
            
            return stage_tasks
            
        except Exception as e:
            self.logger.error(f"Failed to get stage {stage_n} tasks for job {job_id}: {e}")
            return []
    
    def _record_stage_completion(self, job_id: str, stage_n: int, completed_tasks: List[Dict]):
        """
        Record actual stage completion with real timing metrics.
        
        Args:
            job_id: Job identifier
            stage_n: Completed stage number
            completed_tasks: List of completed tasks from this stage
        """
        try:
            # Calculate real stage duration from task completion timestamps
            task_times = []
            for task in completed_tasks:
                updated_at = task.get('updated_at')
                if updated_at:
                    try:
                        task_times.append(datetime.fromisoformat(updated_at.replace('Z', '+00:00')))
                    except:
                        pass
            
            # Calculate actual duration (from first to last task completion)
            if len(task_times) > 1:
                stage_start = min(task_times)
                stage_end = max(task_times)
                actual_duration = (stage_end - stage_start).total_seconds()
            else:
                actual_duration = 0.0  # Single task or no timing data
            
            # Get stage name from job configuration
            job = self.job_repo.get_job(job_id)
            stage_sequence = json.loads(job.get('stage_sequence', '{}'))
            stage_name = stage_sequence.get(str(stage_n), f'stage_{stage_n}')
            
            # Create stage completion record
            stage_record = {
                'stage_n': stage_n,
                'stage': stage_name,
                'completed_at': datetime.utcnow().isoformat(),
                'duration_seconds': round(actual_duration, 3),  # Real measurement
                'task_count': len(completed_tasks),
                'successful_tasks': len(completed_tasks),  # All tasks in completed_tasks are successful
                'status': 'completed'
            }
            
            # Add to job's stage_history
            stage_history = json.loads(job.get('stage_history', '[]'))
            stage_history.append(stage_record)
            
            # Update job record
            self.job_repo.update_job_field(job_id, 'stage_history', json.dumps(stage_history))
            
            self.logger.info(f"📊 Recorded completion of stage {stage_n} ({stage_name}) for job {job_id}: {actual_duration:.3f}s, {len(completed_tasks)} tasks")
            
        except Exception as e:
            self.logger.error(f"Failed to record stage completion for job {job_id} stage {stage_n}: {e}")
    
    def _advance_to_next_stage(self, job_id: str, completed_tasks: List[Dict]):
        """
        Advance job to next stage and create appropriate tasks.
        
        Args:
            job_id: Job identifier
            completed_tasks: Tasks completed in current stage
        """
        try:
            # Get job configuration
            job = self.job_repo.get_job(job_id)
            current_stage = job.get('current_stage_n', 1)
            next_stage = current_stage + 1
            
            stage_sequence = json.loads(job.get('stage_sequence', '{}'))
            next_stage_name = stage_sequence.get(str(next_stage), f'stage_{next_stage}')
            
            self.logger.info(f"🚀 Advancing job {job_id} from stage {current_stage} to stage {next_stage} ({next_stage_name})")
            
            # Update job to next stage
            job_updates = {
                'current_stage_n': next_stage,
                'current_stage': next_stage_name,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            # Update stage_data with completed stage results
            stage_data = json.loads(job.get('stage_data', '{}'))
            stage_data[f'stage{current_stage}_results'] = [
                {
                    'task_id': task.get('task_id'),
                    'status': task.get('status'),
                    'result': task.get('result_data'),
                    'task_type': task.get('task_type')
                }
                for task in completed_tasks
            ]
            job_updates['stage_data'] = json.dumps(stage_data)
            
            # Apply updates to job
            for field, value in job_updates.items():
                self.job_repo.update_job_field(job_id, field, value)
            
            # Create tasks for next stage based on stage type
            self._create_next_stage_tasks(job_id, next_stage, next_stage_name, completed_tasks)
            
            self.logger.info(f"✅ Job {job_id} advanced to stage {next_stage} ({next_stage_name})")
            
        except Exception as e:
            self.logger.error(f"Failed to advance job {job_id} to next stage: {e}")
    
    def _create_next_stage_tasks(self, job_id: str, stage_n: int, stage_name: str, previous_stage_tasks: List[Dict]):
        """
        Create tasks for the next stage based on the stage type and previous results.
        
        Args:
            job_id: Job identifier
            stage_n: Stage number to create tasks for
            stage_name: Stage name
            previous_stage_tasks: Completed tasks from previous stage
        """
        try:
            # Get job configuration to understand the sequential workflow
            job = self.job_repo.get_job(job_id)
            stage_data = json.loads(job.get('stage_data', '{}'))
            
            # Create tasks based on stage type
            if stage_name == 'validation' and stage_n == 2:
                # Stage 2: Create single validation task
                self._create_validation_task(job_id, stage_data, previous_stage_tasks)
                
            elif stage_name == 'response' and stage_n == 3:
                # Stage 3: Create response tasks based on Stage 1 results
                self._create_response_tasks(job_id, stage_data, previous_stage_tasks)
                
            else:
                self.logger.warning(f"Unknown stage type: {stage_name} (stage {stage_n}) for job {job_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to create stage {stage_n} tasks for job {job_id}: {e}")
    
    def _create_validation_task(self, job_id: str, stage_data: Dict, stage1_tasks: List[Dict]):
        """
        Create Stage 2 validation task.
        
        Args:
            job_id: Job identifier
            stage_data: Job stage data
            stage1_tasks: Completed Stage 1 tasks
        """
        self.logger.info(f"🔍 DEBUG: Creating Stage 2 validation task for job {job_id}")
        self.logger.info(f"DEBUG: Stage 1 tasks count: {len(stage1_tasks)}")
        self.logger.info(f"DEBUG: Stage 1 task IDs: {[t.get('task_id')[:16] + '...' for t in stage1_tasks]}")
        
        task_data = {
            'job_id': job_id,
            'stage': 2,
            'validation_target': 'stage1_completion',
            'stage1_task_count': len(stage1_tasks),
            'stage1_task_ids': [t.get('task_id') for t in stage1_tasks]
        }
        
        self.logger.info(f"DEBUG: Stage 2 task_data: {task_data}")
        
        task_id = self.create_task(
            job_id=job_id,
            task_type='hello_world_stage2_validation',
            task_data=task_data,
            index=0
        )
        
        self.logger.info(f"DEBUG: create_task returned task_id: {task_id}")
        
        if task_id:
            # Queue the validation task
            from base_controller import BaseJobController
            controller = BaseJobController()  # Use base controller for queuing
            self.logger.info(f"DEBUG: About to queue Stage 2 validation task with ID: {task_id}")
            
            if controller.queue_task(task_id, task_data):
                self.logger.info(f"✅ Created and queued validation task for job {job_id}: {task_id[:16]}...")
            else:
                self.logger.error(f"❌ Failed to queue validation task {task_id[:16]}... for job {job_id}")
        else:
            self.logger.error(f"❌ Failed to create validation task for job {job_id}")
    
    def _create_response_tasks(self, job_id: str, stage_data: Dict, stage2_tasks: List[Dict]):
        """
        Create Stage 3 response tasks based on Stage 1 task mapping.
        
        Args:
            job_id: Job identifier 
            stage_data: Job stage data
            stage2_tasks: Completed Stage 2 validation tasks
        """
        try:
            # Get Stage 1 results from stage_data
            stage1_results = stage_data.get('stage1_results', [])
            
            # Extract task mapping from Stage 2 validation result
            task_mapping = {}
            if stage2_tasks:
                validation_task = stage2_tasks[0]  # Should be only one validation task
                validation_result = validation_task.get('result_data')
                if isinstance(validation_result, str):
                    try:
                        validation_result = json.loads(validation_result)
                    except:
                        validation_result = {}
                
                if isinstance(validation_result, dict):
                    task_mapping = validation_result.get('stage3_task_mapping', {})
            
            # Create response tasks based on mapping
            response_tasks_created = 0
            for mapping_key, mapping_data in task_mapping.items():
                responds_to_task_id = mapping_data.get('responds_to_task_id')
                original_hello_number = mapping_data.get('original_hello_number')
                original_message = mapping_data.get('original_message')
                
                if responds_to_task_id:
                    task_data = {
                        'job_id': job_id,
                        'stage': 3,
                        'response_number': int(mapping_key),
                        'responds_to_task_id': responds_to_task_id,
                        'original_hello_number': original_hello_number,
                        'original_message': original_message
                    }
                    
                    task_id = self.create_task(
                        job_id=job_id,
                        task_type='hello_world_stage3_response',
                        task_data=task_data,
                        index=response_tasks_created
                    )
                    
                    if task_id:
                        # Queue the response task
                        from base_controller import BaseJobController
                        controller = BaseJobController()  # Use base controller for queuing
                        if controller.queue_task(task_id, task_data):
                            response_tasks_created += 1
                            self.logger.debug(f"Created response task {response_tasks_created}: {task_id[:16]}...")
                        else:
                            self.logger.error(f"Failed to queue response task {task_id[:16]}...")
                    else:
                        self.logger.error(f"Failed to create response task {response_tasks_created + 1}")
            
            self.logger.info(f"✅ Created {response_tasks_created} Stage 3 response tasks for job {job_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to create response tasks for job {job_id}: {e}")
    
    def _complete_sequential_job(self, job_id: str, final_stage_tasks: List[Dict]):
        """
        Complete a sequential job after all stages are finished.
        
        Args:
            job_id: Job identifier
            final_stage_tasks: Tasks from the final stage
        """
        try:
            self.logger.info(f"🎉 Completing sequential job {job_id} - all stages finished")
            
            # Get all tasks from all stages for final aggregation
            all_tasks = self.task_repo.get_tasks_for_job(job_id)
            
            # Use the standard job completion flow with controller-specific aggregation
            # This will call aggregate_results on the appropriate controller
            self._check_job_completion(job_id)
            
            self.logger.info(f"✅ Sequential job {job_id} completed successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to complete sequential job {job_id}: {e}")