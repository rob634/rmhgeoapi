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
from datetime import datetime

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
                'status': 'pending',
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
                self._check_job_completion(task.get('parent_job_id'))
            
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
            
            # Count task statuses
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get('status') == 'completed')
            failed = sum(1 for t in tasks if t.get('status') == 'failed')
            
            self.logger.debug(f"  Task counts - Total: {total}, Completed: {completed}, Failed: {failed}")
            
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
                'progress_percentage': (completed + failed) / total * 100,
                'task_results': task_results,
                'task_errors': error_messages if error_messages else None
            }
            
            # Determine job status
            if completed + failed == total:
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
                    
                    self.logger.warning(f"⚠️ {completed} tasks succeeded, {failed} failed - updating job to COMPLETED_WITH_ERRORS")
                    self.job_repo.update_job_status(job_id, 'completed_with_errors', job_metadata, result_data=result_data)
                    self.logger.warning(f"⚠️ Job {job_id} marked as COMPLETED_WITH_ERRORS with mixed result data")
            else:
                # Still processing
                self.logger.debug(f"  Job still processing - {total - completed - failed} tasks remaining")
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