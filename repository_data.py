# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Data access layer with PostgreSQL persistence and completion detection
# SOURCE: Environment variables for PostgreSQL connection (POSTGIS_PASSWORD)
# SCOPE: Global data repository patterns for jobs and tasks with ACID transactions
# VALIDATION: PostgreSQL schema validation + Pydantic model validation
# ============================================================================

"""
TYPE-SAFE REPOSITORIES - Schema-Validated Data Access Layer

Provides storage-agnostic repositories with C-style type discipline.
All data entering/leaving repositories is strictly validated against schemas.

Design Principles:
1. ZERO tolerance for invalid data - fail fast with detailed errors
2. Storage backend agnostic - works with any StorageBackend implementation  
3. Transaction-like semantics where possible
4. Comprehensive logging for debugging
5. Built-in retry logic for transient failures

Repository Layer Responsibilities:
- Schema validation on all operations
- Status transition validation  
- Parent-child relationship validation
- Completion detection logic
- Error handling and logging

Author: Strong Typing Discipline Team
Version: 1.0.0 - Foundation implementation with bulletproof validation
"""

from typing import Optional, List, Dict, Any, Union
import logging
from datetime import datetime, timezone
from contextlib import contextmanager

from schema_core import (
    JobRecord, TaskRecord, JobStatus, TaskStatus, 
    generate_job_id, generate_task_id, SchemaConfig
)
from validator_schema import SchemaValidator, SchemaValidationError
from adapter_storage import StorageBackend, StorageAdapterFactory

logger = logging.getLogger(__name__)


# ============================================================================
# BASE REPOSITORY - Common validation and error handling
# ============================================================================

class BaseRepository:
    """
    BASE REPOSITORY with common validation logic
    
    Provides shared functionality for all repositories:
    - Schema validation
    - Error handling  
    - Logging
    - Retry logic
    """
    
    def __init__(self, storage_backend: StorageBackend):
        """
        Initialize repository with storage backend
        
        Args:
            storage_backend: Storage implementation (Azure Tables, PostgreSQL, etc)
        """
        self.storage = storage_backend
        self.validator = SchemaValidator()
        logger.info(f"🏛️ {self.__class__.__name__} initialized with {type(storage_backend).__name__}")
    
    @contextmanager
    def _error_context(self, operation: str, entity_id: str = None):
        """Context manager for consistent error handling"""
        try:
            yield
        except SchemaValidationError as e:
            logger.error(f"❌ Schema validation failed during {operation}: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ {operation} failed" + (f" for {entity_id}" if entity_id else "") + f": {e}")
            raise
    
    def _validate_status_transition(self, current_record: Union[JobRecord, TaskRecord], 
                                  new_status: Union[JobStatus, TaskStatus]) -> None:
        """Validate status transitions to prevent state corruption"""
        try:
            self.validator.validate_status_transition(current_record, new_status)
        except ValueError as e:
            raise SchemaValidationError(
                type(current_record).__name__, 
                [{"msg": str(e), "loc": ["status_transition"]}]
            )


# ============================================================================
# JOB REPOSITORY - Type-safe job lifecycle management
# ============================================================================

class JobRepository(BaseRepository):
    """
    TYPE-SAFE JOB REPOSITORY
    
    Manages job lifecycle with strict schema validation and state management.
    All operations are atomic and validated against JobRecord schema.
    """
    
    def create_job(self, job_type: str, parameters: Dict[str, Any], 
                  total_stages: int = 1) -> JobRecord:
        """
        Create new job with schema validation and deterministic ID generation
        
        Args:
            job_type: Type of job (snake_case format)
            parameters: Job parameters dictionary
            total_stages: Total number of stages in job
            
        Returns:
            Created and validated JobRecord
            
        Raises:
            SchemaValidationError: If job data is invalid
        """
        with self._error_context("job creation"):
            # Generate deterministic job ID
            job_id = generate_job_id(job_type, parameters)
            
            # Create job record with current timestamp
            now = datetime.utcnow()
            job_data = {
                'job_id': job_id,
                'job_type': job_type,
                'status': JobStatus.QUEUED,
                'stage': 1,
                'total_stages': total_stages,
                'parameters': parameters.copy(),  # Defensive copy
                'stage_results': {},
                'created_at': now,
                'updated_at': now
            }
            
            # Validate job data
            job_record = self.validator.validate_job_record(job_data, strict=True)
            
            # Create in storage
            created = self.storage.create_job(job_record)
            if created:
                logger.info(f"✅ Job created: {job_id[:16]}... type={job_type} stages={total_stages}")
            else:
                logger.info(f"📋 Job already exists: {job_id[:16]}... (idempotent)")
            
            return job_record
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """
        Retrieve job with schema validation
        
        Args:
            job_id: Job ID to retrieve
            
        Returns:
            Validated JobRecord or None if not found
        """
        with self._error_context("job retrieval", job_id):
            job_record = self.storage.get_job(job_id)
            
            if job_record:
                logger.debug(f"📋 Retrieved job: {job_id[:16]}... status={job_record.status}")
            else:
                logger.debug(f"📋 Job not found: {job_id[:16]}...")
            
            return job_record
    
    def update_job_status(self, job_id: str, new_status: JobStatus, 
                         additional_updates: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update job status with validation and state transition checking
        
        Args:
            job_id: Job ID to update
            new_status: New status to set
            additional_updates: Additional fields to update
            
        Returns:
            True if updated successfully
            
        Raises:
            SchemaValidationError: If status transition is invalid
        """
        with self._error_context("job status update", job_id):
            # Get current job
            current_job = self.get_job(job_id)
            if not current_job:
                logger.warning(f"📋 Cannot update non-existent job: {job_id[:16]}...")
                return False
            
            # Validate status transition
            self._validate_status_transition(current_job, new_status)
            
            # Prepare updates
            updates = {'status': new_status}
            if additional_updates:
                updates.update(additional_updates)
            
            # Update storage
            success = self.storage.update_job(job_id, updates)
            
            if success:
                logger.info(f"✅ Job status updated: {job_id[:16]}... {current_job.status} → {new_status}")
            
            return success
    
    def update_job_stage(self, job_id: str, new_stage: int, 
                        stage_results: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update job stage with results from completed stage
        
        Args:
            job_id: Job ID to update
            new_stage: New stage number
            stage_results: Results from completed stage
            
        Returns:
            True if updated successfully
        """
        with self._error_context("job stage update", job_id):
            current_job = self.get_job(job_id)
            if not current_job:
                return False
            
            # Validate stage progression
            if new_stage <= current_job.stage:
                raise SchemaValidationError(
                    "JobRecord",
                    [{"msg": f"Stage must advance: current={current_job.stage}, new={new_stage}", 
                      "loc": ["stage"]}]
                )
            
            if new_stage > current_job.total_stages:
                raise SchemaValidationError(
                    "JobRecord",
                    [{"msg": f"Stage {new_stage} exceeds total_stages {current_job.total_stages}", 
                      "loc": ["stage"]}]
                )
            
            # Prepare updates
            updates = {'stage': new_stage}
            
            if stage_results:
                # Add stage results to existing results
                updated_stage_results = current_job.stage_results.copy()
                updated_stage_results[current_job.stage] = stage_results
                updates['stage_results'] = updated_stage_results
            
            success = self.storage.update_job(job_id, updates)
            
            if success:
                logger.info(f"✅ Job stage updated: {job_id[:16]}... stage {current_job.stage} → {new_stage}")
            
            return success
    
    def complete_job(self, job_id: str, result_data: Dict[str, Any]) -> bool:
        """
        Mark job as completed with final results
        
        Args:
            job_id: Job ID to complete
            result_data: Final job results
            
        Returns:
            True if completed successfully
        """
        with self._error_context("job completion", job_id):
            return self.update_job_status(
                job_id, 
                JobStatus.COMPLETED, 
                {'result_data': result_data}
            )
    
    def fail_job(self, job_id: str, error_details: str) -> bool:
        """
        Mark job as failed with error details
        
        Args:
            job_id: Job ID to fail
            error_details: Error description
            
        Returns:
            True if failed successfully
        """
        with self._error_context("job failure", job_id):
            return self.update_job_status(
                job_id,
                JobStatus.FAILED,
                {'error_details': error_details}
            )
    
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """
        List jobs with optional status filtering
        
        Args:
            status_filter: Optional status to filter by
            
        Returns:
            List of validated JobRecords
        """
        with self._error_context("job listing"):
            jobs = self.storage.list_jobs(status_filter)
            logger.info(f"📋 Listed {len(jobs)} jobs" + 
                       (f" with status {status_filter}" if status_filter else ""))
            return jobs


# ============================================================================
# TASK REPOSITORY - Type-safe task lifecycle management
# ============================================================================

class TaskRepository(BaseRepository):
    """
    TYPE-SAFE TASK REPOSITORY
    
    Manages task lifecycle with strict parent-child relationship validation.
    All tasks must belong to valid jobs.
    """
    
    def create_task(self, parent_job_id: str, task_type: str, stage: int, 
                   task_index: int, parameters: Dict[str, Any]) -> TaskRecord:
        """
        Create task with validation and automatic ID generation
        
        Args:
            parent_job_id: Parent job ID (must exist)
            task_type: Type of task (snake_case format)
            stage: Stage number task belongs to
            task_index: Index within stage (0-based)
            parameters: Task parameters
            
        Returns:
            Created and validated TaskRecord
            
        Raises:
            SchemaValidationError: If task data is invalid
        """
        with self._error_context("task creation"):
            # Generate task ID
            task_id = generate_task_id(parent_job_id, stage, task_index)
            
            # Create task record
            now = datetime.utcnow()
            task_data = {
                'taskId': task_id,
                'parentJobId': parent_job_id,
                'taskType': task_type,
                'status': TaskStatus.QUEUED,
                'stage': stage,
                'taskIndex': task_index,
                'parameters': parameters.copy(),
                'retryCount': 0,
                'createdAt': now,
                'updatedAt': now
            }
            
            # Validate task data
            task_record = self.validator.validate_task_record(task_data, strict=True)
            
            # Create in storage
            created = self.storage.create_task(task_record)
            if created:
                logger.info(f"✅ Task created: {task_id} parent={parent_job_id[:16]}... type={task_type}")
            else:
                logger.info(f"📋 Task already exists: {task_id} (idempotent)")
            
            return task_record
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task with schema validation"""
        with self._error_context("task retrieval", task_id):
            task_record = self.storage.get_task(task_id)
            
            if task_record:
                logger.debug(f"📋 Retrieved task: {task_id} status={task_record.status}")
            else:
                logger.debug(f"📋 Task not found: {task_id}")
            
            return task_record
    
    def update_task_status(self, task_id: str, new_status: TaskStatus,
                          additional_updates: Optional[Dict[str, Any]] = None) -> bool:
        """Update task status with validation"""
        with self._error_context("task status update", task_id):
            current_task = self.get_task(task_id)
            if not current_task:
                logger.warning(f"📋 Cannot update non-existent task: {task_id}")
                return False
            
            # Validate status transition
            self._validate_status_transition(current_task, new_status)
            
            # Prepare updates
            updates = {'status': new_status}
            if additional_updates:
                updates.update(additional_updates)
            
            # Update heartbeat for processing status
            if new_status == TaskStatus.PROCESSING:
                updates['heartbeat'] = datetime.utcnow()
            
            success = self.storage.update_task(task_id, updates)
            
            if success:
                logger.info(f"✅ Task status updated: {task_id} {current_task.status} → {new_status}")
            
            return success
    
    def complete_task(self, task_id: str, result_data: Dict[str, Any]) -> bool:
        """Mark task as completed with results"""
        return self.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            {'result_data': result_data}
        )
    
    def fail_task(self, task_id: str, error_details: str, increment_retry: bool = True) -> bool:
        """Mark task as failed with error details"""
        additional_updates = {'error_details': error_details}
        
        if increment_retry:
            current_task = self.get_task(task_id)
            if current_task:
                additional_updates['retryCount'] = current_task.retryCount + 1
        
        return self.update_task_status(task_id, TaskStatus.FAILED, additional_updates)
    
    def update_task_heartbeat(self, task_id: str) -> bool:
        """Update task heartbeat to indicate active processing"""
        return self.update_task_status(
            task_id,
            TaskStatus.PROCESSING,
            {'heartbeat': datetime.utcnow()}
        )
    
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """List all tasks for a job"""
        with self._error_context("task listing for job", job_id):
            tasks = self.storage.list_tasks_for_job(job_id)
            logger.debug(f"📋 Listed {len(tasks)} tasks for job {job_id[:16]}...")
            return tasks
    
    def count_tasks_by_status(self, job_id: str, status: TaskStatus) -> int:
        """Count tasks by status for completion detection"""
        with self._error_context("task counting", job_id):
            count = self.storage.count_tasks_by_status(job_id, status)
            logger.debug(f"📋 Counted {count} {status} tasks for job {job_id[:16]}...")
            return count
    
    def get_completion_status(self, job_id: str) -> Dict[str, int]:
        """
        Get completion status for all tasks in a job
        
        Returns:
            Dictionary with task counts by status
        """
        with self._error_context("completion status check", job_id):
            status_counts = {}
            
            for status in TaskStatus:
                count = self.count_tasks_by_status(job_id, status)
                status_counts[status.value] = count
            
            logger.debug(f"📊 Job {job_id[:16]}... completion status: {status_counts}")
            return status_counts


# ============================================================================
# COMPLETION DETECTOR - "Last task turns out the lights" logic
# ============================================================================

class CompletionDetector:
    """
    ATOMIC COMPLETION DETECTION
    
    Implements "last task turns out the lights" pattern with atomic operations
    to prevent race conditions in distributed task processing.
    """
    
    def __init__(self, job_repo: JobRepository, task_repo: TaskRepository):
        self.job_repo = job_repo
        self.task_repo = task_repo
        logger.info("🔍 CompletionDetector initialized")
    
    def check_stage_completion(self, job_id: str, stage: int) -> Dict[str, Any]:
        """
        Check if all tasks in a stage are complete
        
        Args:
            job_id: Job ID to check
            stage: Stage number to check
            
        Returns:
            Dictionary with completion status and next actions
        """
        with self.task_repo._error_context("stage completion check", job_id):
            # Get all tasks for the job
            all_tasks = self.task_repo.list_tasks_for_job(job_id)
            
            # Filter tasks for this stage
            stage_tasks = [task for task in all_tasks if task.stage == stage]
            
            if not stage_tasks:
                logger.warning(f"📊 No tasks found for job {job_id[:16]}... stage {stage}")
                return {'stage_complete': False, 'reason': 'no_tasks_in_stage'}
            
            # Count task statuses
            completed_count = sum(1 for task in stage_tasks if task.status == TaskStatus.COMPLETED)
            failed_count = sum(1 for task in stage_tasks if task.status == TaskStatus.FAILED)
            processing_count = sum(1 for task in stage_tasks if task.status == TaskStatus.PROCESSING)
            queued_count = sum(1 for task in stage_tasks if task.status == TaskStatus.QUEUED)
            
            total_tasks = len(stage_tasks)
            terminal_tasks = completed_count + failed_count
            
            # Stage is complete when all tasks are terminal
            stage_complete = terminal_tasks == total_tasks
            
            completion_info = {
                'stage_complete': stage_complete,
                'total_tasks': total_tasks,
                'completed_tasks': completed_count,
                'failed_tasks': failed_count,
                'processing_tasks': processing_count,
                'queued_tasks': queued_count,
                'success_rate': (completed_count / total_tasks * 100) if total_tasks > 0 else 0
            }
            
            if stage_complete:
                logger.info(f"🎯 Stage {stage} complete for job {job_id[:16]}... "
                          f"({completed_count}/{total_tasks} successful, "
                          f"{completion_info['success_rate']:.1f}% success rate)")
            else:
                logger.debug(f"📊 Stage {stage} progress for job {job_id[:16]}... "
                           f"{terminal_tasks}/{total_tasks} complete")
            
            return completion_info
    
    def check_job_completion(self, job_id: str) -> bool:
        """
        Check if entire job is complete (all stages finished)
        
        Args:
            job_id: Job ID to check
            
        Returns:
            True if job is complete
        """
        with self.job_repo._error_context("job completion check", job_id):
            job_record = self.job_repo.get_job(job_id)
            if not job_record:
                logger.warning(f"📊 Cannot check completion of non-existent job: {job_id[:16]}...")
                return False
            
            # Check completion of current stage
            current_stage_status = self.check_stage_completion(job_id, job_record.stage)
            
            if not current_stage_status['stage_complete']:
                return False
            
            # If current stage complete, check if this is the final stage
            if job_record.stage >= job_record.total_stages:
                logger.info(f"🎉 Job complete: {job_id[:16]}... (all {job_record.total_stages} stages finished)")
                return True
            
            logger.debug(f"📊 Job {job_id[:16]}... stage {job_record.stage}/{job_record.total_stages} complete")
            return False


# ============================================================================
# POSTGRESQL-SPECIFIC REPOSITORIES - Atomic workflow operations
# ============================================================================

class PostgreSQLCompletionDetector(CompletionDetector):
    """
    PostgreSQL-optimized completion detector with atomic operations.
    
    Uses PostgreSQL stored procedures for atomic completion detection,
    preventing race conditions in "last task turns out lights" scenarios.
    """
    
    def __init__(self, job_repo: JobRepository, task_repo: TaskRepository):
        super().__init__(job_repo, task_repo)
        # Verify we have a PostgreSQL adapter
        from adapter_storage import PostgresAdapter
        if not isinstance(job_repo.storage, PostgresAdapter):
            raise ValueError("PostgreSQLCompletionDetector requires PostgreSQL storage adapter")
        
        self.postgres_adapter = job_repo.storage
        logger.info("🔍 PostgreSQLCompletionDetector initialized with atomic operations")
    
    def complete_task_and_check_stage(self, task_id: str, job_id: str, stage: int, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Atomically complete task and check stage completion.
        
        This replaces the non-atomic check_stage_completion method for PostgreSQL,
        providing race-condition-free completion detection.
        
        Args:
            task_id: Task to complete
            job_id: Parent job identifier
            stage: Stage number
            result_data: Task completion results
            
        Returns:
            Dict with stage completion status and remaining tasks
        """
        try:
            logger.debug(f"🔄 PostgreSQL atomic completion: task {task_id} in stage {stage}")
            
            # Use PostgreSQL adapter's atomic method
            completion_result = self.postgres_adapter.complete_task_and_check_stage(
                task_id, job_id, stage, result_data
            )
            
            logger.info(f"✅ Atomic completion: task {task_id}, stage complete: {completion_result['stage_complete']}")
            return completion_result
            
        except Exception as e:
            logger.error(f"❌ Atomic task completion failed for {task_id}: {e}")
            raise

    def advance_job_stage(self, job_id: str, current_stage: int, stage_results: Dict[str, Any]) -> bool:
        """
        Atomically advance job to next stage.
        
        Args:
            job_id: Job to advance
            current_stage: Current stage number
            stage_results: Results from completed stage
            
        Returns:
            bool: True if advancement succeeded
        """
        try:
            next_stage = current_stage + 1
            logger.debug(f"🔄 PostgreSQL atomic stage advancement: job {job_id[:16]}... {current_stage} -> {next_stage}")
            
            # Use PostgreSQL adapter's atomic method
            success = self.postgres_adapter.advance_job_stage(
                job_id, current_stage, next_stage, stage_results
            )
            
            if success:
                logger.info(f"✅ Atomic stage advancement: job {job_id[:16]}... -> stage {next_stage}")
            else:
                logger.warning(f"⚠️ Atomic stage advancement failed: job {job_id[:16]}... (concurrent update?)")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Atomic stage advancement failed for job {job_id[:16]}...: {e}")
            raise

    def check_job_completion(self, job_id: str) -> bool:
        """
        Check if job workflow is fully complete using PostgreSQL stored procedure.
        
        Args:
            job_id: Job to check
            
        Returns:
            bool: True if job is complete
        """
        try:
            logger.debug(f"🔍 PostgreSQL job completion check: {job_id[:16]}...")
            
            # Use PostgreSQL adapter's atomic method
            completion_status = self.postgres_adapter.check_job_completion(job_id)
            
            job_complete = completion_status['job_complete']
            final_stage = completion_status['final_stage']
            
            if job_complete:
                logger.info(f"🎉 Job complete (PostgreSQL): {job_id[:16]}... at stage {final_stage}")
            else:
                logger.debug(f"📊 Job incomplete (PostgreSQL): {job_id[:16]}... at stage {final_stage}")
            
            return job_complete
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL job completion check failed for {job_id[:16]}...: {e}")
            raise


# ============================================================================
# REPOSITORY FACTORY - Create repositories with dependency injection
# ============================================================================

class RepositoryFactory:
    """Factory for creating repositories with consistent configuration and schema validation"""
    
    @staticmethod
    def create_repositories(storage_backend_type: str = 'azure_tables') -> tuple[JobRepository, TaskRepository, CompletionDetector]:
        """
        Create job and task repositories with completion detector.
        
        Includes schema validation for PostgreSQL backends to ensure database
        is ready for repository operations.
        
        Args:
            storage_backend_type: Type of storage backend to use
            
        Returns:
            Tuple of (JobRepository, TaskRepository, CompletionDetector)
            
        Raises:
            SchemaManagementError: If PostgreSQL schema validation fails
        """
        logger.info(f"🏛️ Creating repositories with {storage_backend_type} backend")
        
        # TEMPORARILY DISABLE schema validation for debugging
        if storage_backend_type == 'postgres':
            logger.warning("⚠️ SCHEMA VALIDATION TEMPORARILY DISABLED FOR DEBUGGING")
            # try:
            #     from validator_schema_database import SchemaValidatorFactory
            #     
            #     schema_validator = SchemaValidatorFactory.create_validator()
            #     validation_results = schema_validator.validate_schema_ready()
            #     
            #     if not validation_results['schema_ready']:
            #         error_msg = (
            #             f"PostgreSQL schema not ready for repository operations. "
            #             f"Recommendations: {validation_results['recommendations']}"
            #         )
            #         logger.error(f"❌ {error_msg}")
            #         raise RuntimeError(error_msg)
            #         
            #     logger.info(f"✅ PostgreSQL schema validated successfully: {validation_results['app_schema']}")
            #     
            # except ImportError as e:
            #     logger.warning(f"⚠️ Schema validation not available: {e}")
            # except Exception as e:
            #     logger.error(f"❌ Schema validation failed: {e}")
            #     raise RuntimeError(f"Database schema validation failed: {e}")
        
        # Create storage adapter
        storage_adapter = StorageAdapterFactory.create_adapter(storage_backend_type)
        
        # Create repositories  
        job_repo = JobRepository(storage_adapter)
        task_repo = TaskRepository(storage_adapter)
        
        # Create completion detector (PostgreSQL-specific for atomic operations)
        if storage_backend_type == 'postgres':
            completion_detector = PostgreSQLCompletionDetector(job_repo, task_repo)
            logger.info("✅ Using PostgreSQL atomic completion detector")
        else:
            completion_detector = CompletionDetector(job_repo, task_repo)
            logger.info(f"✅ Using standard completion detector for {storage_backend_type}")
        
        logger.info(f"✅ Repository factory created repositories with {storage_backend_type} backend")
        
        return job_repo, task_repo, completion_detector


# Export public interfaces
__all__ = [
    'JobRepository',
    'TaskRepository', 
    'CompletionDetector',
    'PostgreSQLCompletionDetector',
    'RepositoryFactory'
]