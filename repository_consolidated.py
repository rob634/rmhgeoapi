# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# PURPOSE: Business logic repository layer extending PostgreSQL implementations with validation and orchestration
# EXPORTS: JobRepository, TaskRepository, CompletionDetector, RepositoryFactory
# INTERFACES: Extends PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLCompletionDetector
# PYDANTIC_MODELS: JobRecord, TaskRecord, JobStatus, TaskStatus (from schema_core)
# DEPENDENCIES: repository_postgresql, schema_core, util_logger, typing, datetime
# SOURCE: PostgreSQL database via inherited base classes, business logic layer
# SCOPE: Business-level repository operations with validation and workflow orchestration
# VALIDATION: Business rule validation, idempotency checks, status transition validation
# PATTERNS: Repository pattern, Factory pattern, Template Method, Facade (for complex workflows)
# ENTRY_POINTS: repos = RepositoryFactory.create_repositories(); job = repos['job_repo'].create_job_from_params()
# INDEX: JobRepository:47, TaskRepository:216, CompletionDetector:385, RepositoryFactory:521
# ============================================================================

"""
Business Logic Repository Implementation

This module provides business logic repositories that extend the PostgreSQL
implementations with additional validation and workflow orchestration:

    PostgreSQLJobRepository (from repository_postgresql.py)
        ↓
    JobRepository (this file - adds business logic)
    
    PostgreSQLTaskRepository (from repository_postgresql.py)
        ↓
    TaskRepository (this file - adds business logic)
    
    PostgreSQLCompletionDetector (from repository_postgresql.py)
        ↓
    CompletionDetector (this file - adds business logic)

The RepositoryFactory creates these business logic repositories
which are used throughout the application.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext
from schema_base import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    generate_job_id
)
# Task ID generation moved to Controller layer (hierarchically correct)
# Repository no longer generates IDs - Controller provides them
from repository_postgresql import (
    PostgreSQLRepository,
    PostgreSQLJobRepository,
    PostgreSQLTaskRepository,
    PostgreSQLCompletionDetector
)

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ConsolidatedRepository")


# ============================================================================
# EXTENDED JOB REPOSITORY - Business logic on top of PostgreSQL
# ============================================================================

class JobRepository(PostgreSQLJobRepository):
    """
    Extended job repository with business logic.
    
    Inherits PostgreSQL operations and adds business-specific methods.
    """
    
    def create_job_from_params(
        self,
        job_type: str,
        parameters: Dict[str, Any],
        total_stages: int = 1
    ) -> JobRecord:
        """
        Create new job with automatic ID generation and validation.
        
        Business logic wrapper around create_job.
        
        Args:
            job_type: Type of job (snake_case format)
            parameters: Job parameters dictionary
            total_stages: Total number of stages in job
            
        Returns:
            Created JobRecord
        """
        with self._error_context("job creation from params"):
            # Generate deterministic job ID
            job_id = generate_job_id(job_type, parameters)
            
            # Check if job already exists (idempotency)
            existing_job = self.get_job(job_id)
            if existing_job:
                logger.info(f"📋 Job already exists (idempotent): {job_id[:16]}...")
                return existing_job
            
            # Create job record
            now = datetime.now(timezone.utc)
            job = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=JobStatus.QUEUED,
                stage=1,
                total_stages=total_stages,
                parameters=parameters.copy(),  # Defensive copy
                stage_results={},
                metadata={},  # Required by database NOT NULL constraint
                created_at=now,
                updated_at=now
            )
            
            # Create in database
            created = self.create_job(job)
            
            return job
    
    def update_job_status_with_validation(
        self,
        job_id: str,
        new_status: JobStatus,
        additional_updates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update job status with transition validation.
        
        Args:
            job_id: Job ID to update
            new_status: New status to set
            additional_updates: Additional fields to update
            
        Returns:
            True if updated successfully
        """
        with self._error_context("job status update", job_id):
            # Get current job
            logger.debug(f"🔍 Getting current job for status update: {job_id[:16]}...")
            current_job = self.get_job(job_id)
            if not current_job:
                logger.warning(f"📋 Cannot update non-existent job: {job_id[:16]}...")
                return False
            
            logger.debug(f"🔍 Current job retrieved: status={current_job.status}, type={type(current_job)}")
            logger.debug(f"🔍 Target status: {new_status}, type={type(new_status)}")
            logger.debug(f"🔍 Checking if current job has can_transition_to method: {hasattr(current_job, 'can_transition_to')}")
            
            # Validate status transition
            logger.debug(f"🔍 About to validate status transition: {current_job.status} -> {new_status}")
            try:
                self._validate_status_transition(current_job, new_status)
                logger.debug(f"✅ Status transition validation passed")
            except Exception as validation_error:
                logger.error(f"❌ Status transition validation failed: {validation_error}")
                logger.error(f"🔍 Validation error type: {type(validation_error).__name__}")
                logger.error(f"🔍 Validation error args: {validation_error.args}")
                raise
            
            # Prepare updates
            updates = {'status': new_status}
            if additional_updates:
                updates.update(additional_updates)
            
            # Update in database
            return self.update_job(job_id, updates)
    
    def update_job_stage_with_validation(
        self,
        job_id: str,
        new_stage: int,
        stage_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update job stage with validation and results.
        
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
            self._validate_stage_progression(
                current_job.stage,
                new_stage,
                current_job.total_stages
            )
            
            # Prepare updates
            updates = {'stage': new_stage}
            
            if stage_results:
                # Add stage results to existing results
                updated_stage_results = current_job.stage_results.copy()
                updated_stage_results[current_job.stage] = stage_results
                updates['stage_results'] = updated_stage_results
            
            return self.update_job(job_id, updates)
    
    def complete_job(self, job_id: str, result_data: Dict[str, Any]) -> bool:
        """
        Mark job as completed with final results.
        
        Args:
            job_id: Job ID to complete
            result_data: Final job results
            
        Returns:
            True if completed successfully
        """
        return self.update_job_status_with_validation(
            job_id,
            JobStatus.COMPLETED,
            {'result_data': result_data}
        )
    
    def fail_job(self, job_id: str, error_details: str) -> bool:
        """
        Mark job as failed with error details.
        
        Args:
            job_id: Job ID to fail
            error_details: Error description
            
        Returns:
            True if failed successfully
        """
        return self.update_job_status_with_validation(
            job_id,
            JobStatus.FAILED,
            {'error_details': error_details}
        )


# ============================================================================
# EXTENDED TASK REPOSITORY - Business logic on top of PostgreSQL
# ============================================================================

class TaskRepository(PostgreSQLTaskRepository):
    """
    Extended task repository with business logic.
    
    Inherits PostgreSQL operations and adds business-specific methods.
    """
    
    def create_task_from_params(
        self,
        task_id: str,  # Controller provides pre-generated semantic task ID
        parent_job_id: str,
        task_type: str,
        stage: int,
        task_index: str,  # Semantic task index from Controller
        parameters: Dict[str, Any]
    ) -> TaskRecord:
        """
        Create task with Controller-provided task ID.
        
        HIERARCHICALLY CORRECT: Repository stores what Controller provides.
        Controller generates semantic task IDs for cross-stage lineage.
        
        Args:
            task_id: Pre-generated semantic task ID from Controller
            parent_job_id: Parent job ID (must exist)
            task_type: Type of task (snake_case format)
            stage: Stage number task belongs to
            task_index: Semantic task index (e.g., 'greet_0', 'tile_x5_y10')
            parameters: Task parameters
            
        Returns:
            Created TaskRecord
        """
        with self._error_context("task creation from params"):
            # Use Controller-provided task ID (no generation in Repository layer)
            
            # Validate parent-child relationship
            self._validate_parent_child_relationship(task_id, parent_job_id)
            
            # Check if task already exists (idempotency)
            existing_task = self.get_task(task_id)
            if existing_task:
                logger.info(f"📋 Task already exists (idempotent): {task_id}")
                return existing_task
            
            # Create task record
            now = datetime.now(timezone.utc)
            task = TaskRecord(
                task_id=task_id,
                parent_job_id=parent_job_id,
                task_type=task_type,
                status=TaskStatus.QUEUED,
                stage=stage,
                task_index=task_index,
                parameters=parameters.copy(),  # Defensive copy
                metadata={},  # Required by database NOT NULL constraint
                retry_count=0,
                created_at=now,
                updated_at=now
            )
            
            # Create in database
            created = self.create_task(task)
            
            return task
    
    def update_task_status_with_validation(
        self,
        task_id: str,
        new_status: TaskStatus,
        additional_updates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update task status with transition validation.
        
        Args:
            task_id: Task ID to update
            new_status: New status to set
            additional_updates: Additional fields to update
            
        Returns:
            True if updated successfully
        """
        with self._error_context("task status update", task_id):
            # Get current task
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
            
            # Update in database
            return self.update_task(task_id, updates)
    
    def complete_task(self, task_id: str, result_data: Dict[str, Any]) -> bool:
        """
        Mark task as completed with results.
        
        Args:
            task_id: Task ID to complete
            result_data: Task results
            
        Returns:
            True if completed successfully
        """
        return self.update_task_status_with_validation(
            task_id,
            TaskStatus.COMPLETED,
            {'result_data': result_data}
        )
    
    def fail_task(self, task_id: str, error_details: str) -> bool:
        """
        Mark task as failed with error details.
        
        Args:
            task_id: Task ID to fail
            error_details: Error description
            
        Returns:
            True if failed successfully
        """
        return self.update_task_status_with_validation(
            task_id,
            TaskStatus.FAILED,
            {'error_details': error_details}
        )
    
    def update_task_heartbeat(self, task_id: str) -> bool:
        """
        Update task heartbeat timestamp.
        
        Args:
            task_id: Task ID to update
            
        Returns:
            True if updated successfully
        """
        return self.update_task(task_id, {'heartbeat': datetime.now(timezone.utc)})
    
    def increment_retry_count(self, task_id: str) -> bool:
        """
        Increment task retry count.
        
        Args:
            task_id: Task ID to update
            
        Returns:
            True if incremented successfully
        """
        with self._error_context("retry count increment", task_id):
            task = self.get_task(task_id)
            if not task:
                return False
            
            return self.update_task(
                task_id,
                {'retry_count': task.retry_count + 1}
            )


# ============================================================================
# EXTENDED COMPLETION DETECTOR - Business logic wrapper
# ============================================================================

class CompletionDetector(PostgreSQLCompletionDetector):
    """
    Extended completion detector with business logic.
    
    Inherits atomic PostgreSQL operations and adds business-specific methods.
    """
    
    def handle_task_completion(
        self,
        task_id: str,
        parent_job_id: str,
        stage: int,
        result_data: Dict[str, Any],
        job_repository: JobRepository,
        task_repository: TaskRepository
    ) -> Dict[str, Any]:
        """
        Handle complete task completion workflow.
        
        This is the main entry point for task completion that orchestrates:
        1. Task completion and stage checking
        2. Stage advancement if needed
        3. Job completion if final stage
        
        Args:
            task_id: Task to complete
            parent_job_id: Parent job ID
            stage: Current stage number
            result_data: Task results
            job_repository: Job repository for updates
            task_repository: Task repository for updates
            
        Returns:
            Dictionary with completion status and next steps
        """
        result = {
            'task_completed': False,
            'stage_completed': False,
            'job_completed': False,
            'next_stage': None,
            'error': None
        }
        
        try:
            # Complete task and check stage
            completion_result = self.complete_task_and_check_stage(
                task_id=task_id,
                job_id=parent_job_id,
                stage=stage,
                result_data=result_data
            )
            
            if not completion_result.task_updated:
                result['error'] = "Task was not in processing state or already completed"
                return result
            
            result['task_completed'] = True
            
            # Check if stage is complete
            if completion_result.stage_complete:
                result['stage_completed'] = True
                logger.info(f"🎯 Stage {stage} complete for job {parent_job_id[:16]}...")
                
                # Get job to check if more stages
                job = job_repository.get_job(parent_job_id)
                if not job:
                    result['error'] = f"Job {parent_job_id} not found"
                    return result
                
                # Advance to next stage if not final
                if stage < job.total_stages:
                    advancement_result = self.advance_job_stage(
                        job_id=parent_job_id,
                        current_stage=stage,
                        stage_results=self._gather_stage_results(
                            parent_job_id,
                            stage,
                            task_repository
                        )
                    )
                    
                    if advancement_result.job_updated:
                        result['next_stage'] = advancement_result.new_stage
                        
                        if advancement_result.is_final_stage:
                            # Check if job is complete
                            completion_check = self.check_job_completion(parent_job_id)
                            if completion_check.job_complete:
                                result['job_completed'] = True
                                logger.info(f"🏁 Job {parent_job_id[:16]}... completed successfully")
                else:
                    # Already at final stage, check completion
                    completion_check = self.check_job_completion(parent_job_id)
                    if completion_check.job_complete:
                        result['job_completed'] = True
                        logger.info(f"🏁 Job {parent_job_id[:16]}... completed successfully")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in task completion workflow: {e}")
            result['error'] = str(e)
            return result
    
    def _gather_stage_results(
        self,
        job_id: str,
        stage: int,
        task_repository: TaskRepository
    ) -> Dict[str, Any]:
        """
        Gather results from all tasks in a stage.
        
        Args:
            job_id: Parent job ID
            stage: Stage number
            task_repository: Repository to query tasks
            
        Returns:
            Dictionary of task results keyed by task_id
        """
        tasks = task_repository.list_tasks_for_job(job_id)
        stage_tasks = [t for t in tasks if t.stage == stage]
        
        results = {}
        for task in stage_tasks:
            if task.result_data:
                results[task.task_id] = task.result_data
        
        return results


# ============================================================================
# REPOSITORY FACTORY - Creates repository instances
# ============================================================================

class RepositoryFactory:
    """
    Factory for creating repository instances.
    
    This replaces the old factory that required storage_backend_type parameter.
    Now it directly creates PostgreSQL repositories.
    """
    
    @staticmethod
    def create_repositories(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> Dict[str, Any]:
        """
        Create all repository instances.
        
        Args:
            connection_string: PostgreSQL connection string (uses env if not provided)
            schema_name: Database schema name
            
        Returns:
            Dictionary with job_repo, task_repo, and completion_detector
        """
        logger.info("🏭 Creating PostgreSQL repositories")
        logger.debug(f"  Connection string provided: {connection_string is not None}")
        logger.debug(f"  Schema name: {schema_name}")
        
        # Create repositories
        logger.debug("📦 Creating JobRepository...")
        job_repo = JobRepository(connection_string, schema_name)
        logger.debug("📦 Creating TaskRepository...")
        task_repo = TaskRepository(connection_string, schema_name)
        logger.debug("📦 Creating CompletionDetector...")
        completion_detector = CompletionDetector(connection_string, schema_name)
        
        logger.info("✅ All repositories created successfully")
        
        return {
            'job_repo': job_repo,
            'task_repo': task_repo,
            'completion_detector': completion_detector
        }
    
    @staticmethod
    def create_job_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> JobRepository:
        """Create job repository instance."""
        return JobRepository(connection_string, schema_name)
    
    @staticmethod
    def create_task_repository(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> TaskRepository:
        """Create task repository instance."""
        return TaskRepository(connection_string, schema_name)
    
    @staticmethod
    def create_completion_detector(
        connection_string: Optional[str] = None,
        schema_name: str = "app"
    ) -> CompletionDetector:
        """Create completion detector instance."""
        return CompletionDetector(connection_string, schema_name)