# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# PURPOSE: Business logic repository layer for job and task management with validation and orchestration
# EXPORTS: JobRepository, TaskRepository, CompletionDetector
# INTERFACES: Extends PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLCompletionDetector
# PYDANTIC_MODELS: JobRecord, TaskRecord, JobStatus, TaskStatus (from schema_base)
# DEPENDENCIES: repository_postgresql, schema_base, util_logger, typing, datetime
# SOURCE: PostgreSQL database via inherited base classes, business logic layer
# SCOPE: Business-level job and task operations with validation and workflow orchestration
# VALIDATION: Business rule validation, idempotency checks, status transition validation
# PATTERNS: Repository pattern, Template Method, Facade (for complex workflows)
# ENTRY_POINTS: from repository_jobs_tasks import JobRepository; job_repo = JobRepository()
# INDEX: JobRepository:64, TaskRepository:235, CompletionDetector:404
# ============================================================================

"""
Job and Task Repository Implementation

This module provides business logic repositories for job and task management,
extending the PostgreSQL base implementations with validation and orchestration:

    PostgreSQLJobRepository (from repository_postgresql.py)
        ↓
    JobRepository (this file - adds business logic)
    
    PostgreSQLTaskRepository (from repository_postgresql.py)
        ↓
    TaskRepository (this file - adds business logic)
    
    PostgreSQLCompletionDetector (from repository_postgresql.py)
        ↓
    CompletionDetector (this file - adds business logic)

These repositories handle all job and task persistence operations,
including idempotency checks, status transitions, and completion detection.

Author: Robert and Geospatial Claude Legion
Date: 10 September 2025
"""

# Imports at top for fast failure
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from util_logger import LoggerFactory, ComponentType, LogLevel, LogContext
from schema_base import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    TaskResult, TaskDefinition,  # Added for contract enforcement
    generate_job_id
)
# Task ID generation moved to Controller layer (hierarchically correct)
# Repository no longer generates IDs - Controller provides them
from .postgresql import (
    PostgreSQLRepository,
    PostgreSQLJobRepository,
    PostgreSQLTaskRepository,
    PostgreSQLStageCompletionRepository
)
from utils import enforce_contract

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "JobsTasksRepository")


# ============================================================================
# EXTENDED JOB REPOSITORY - Business logic on top of PostgreSQL
# ============================================================================

class JobRepository(PostgreSQLJobRepository):
    """
    Extended job repository with business logic.
    
    Inherits PostgreSQL operations and adds business-specific methods.
    """
    
    @enforce_contract(
        params={
            'job_type': str,
            'parameters': dict,
            'total_stages': int
        },
        returns=JobRecord
    )
    def create_job_from_params(
        self,
        job_type: str,
        parameters: Dict[str, Any],
        total_stages: int = 1
    ) -> JobRecord:
        """
        Create new job with automatic ID generation and validation.
        CONTRACT: Returns JobRecord, never dict.

        Business logic wrapper around create_job.

        Args:
            job_type: Type of job (snake_case format)
            parameters: Job parameters dictionary
            total_stages: Total number of stages in job

        Returns:
            Created JobRecord

        Raises:
            TypeError: If parameters are not a dict
            ValueError: If job_type is invalid
        """
        # CONTRACT ENFORCEMENT: Validate inputs
        if not isinstance(parameters, dict):
            raise TypeError(
                f"Parameters must be dict, got {type(parameters).__name__}. "
                f"This is a contract violation - controller must pass dict."
            )

        if not job_type or not isinstance(job_type, str):
            raise ValueError(
                f"job_type must be non-empty string, got {job_type!r}. "
                f"This is a contract violation - controller must pass valid job_type."
            )

        with self._error_context("job creation from params"):
            # Generate deterministic job ID
            job_id = generate_job_id(job_type, parameters)

            # Check if job already exists (idempotency)
            existing_job = self.get_job(job_id)
            if existing_job:
                # CONTRACT: get_job returns JobRecord, not dict
                if not isinstance(existing_job, JobRecord):
                    raise TypeError(
                        f"get_job returned {type(existing_job).__name__}, expected JobRecord. "
                        f"Repository contract violation detected."
                    )
                logger.info(f"📋 Job already exists (idempotent): {job_id[:16]}...")
                return existing_job

            # Create job record using Pydantic model
            now = datetime.now(timezone.utc)
            job = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=JobStatus.QUEUED,  # Enum, not string
                stage=1,
                total_stages=total_stages,
                parameters=parameters.copy(),  # Defensive copy
                stage_results={},  # Will have string keys per contract
                metadata={},  # Required by database NOT NULL constraint
                created_at=now,
                updated_at=now
            )

            # Create in database
            created = self.create_job(job)

            return job
    
    @enforce_contract(
        params={
            'job_id': str,
            'new_status': JobStatus,
            'additional_updates': (dict, type(None))
        },
        returns=bool
    )
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
                # === STAGE RESULTS STORAGE WITH STRING KEY ===
                #
                # CRITICAL BOUNDARY CONTRACT:
                #
                # current_job.stage is an INTEGER (e.g., 2)
                # But we MUST use STRING key for storage because:
                # 1. This will be serialized to JSON for PostgreSQL
                # 2. JSON spec requires object keys to be strings
                # 3. PostgreSQL JSONB will convert integer keys to strings anyway
                #
                # EXAMPLE:
                # - current_job.stage = 2 (integer)
                # - str(current_job.stage) = "2" (string key)
                # - updated_stage_results["2"] = {...stage 2 results...}
                #
                # RETRIEVAL:
                # Later, when retrieving: stage_results["2"] or stage_results[str(2)]
                # Never: stage_results[2] (would fail with KeyError)
                #
                updated_stage_results = current_job.stage_results.copy()
                updated_stage_results[str(current_job.stage)] = stage_results  # STRING KEY!
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
    
    @enforce_contract(
        params={'task_def': TaskDefinition},
        returns=TaskRecord
    )
    def create_task_from_definition(
        self,
        task_def: TaskDefinition
    ) -> TaskRecord:
        """
        Create task from TaskDefinition using factory method.
        CONTRACT: Uses factory method, returns TaskRecord.

        This is the ONLY method for task creation as of 20 SEP 2025.
        Enforces contract pattern - controllers MUST use TaskDefinition.

        Args:
            task_def: TaskDefinition with all task parameters

        Returns:
            Created TaskRecord

        Raises:
            TypeError: If task_def is not a TaskDefinition
        """
        # CONTRACT ENFORCEMENT: Must be TaskDefinition
        if not isinstance(task_def, TaskDefinition):
            raise TypeError(
                f"Expected TaskDefinition, got {type(task_def).__name__}. "
                f"Controller must use TaskDefinition.to_task_record() factory method."
            )

        # Use factory method to create TaskRecord
        task_record = task_def.to_task_record()

        # Check if task already exists (idempotency)
        existing_task = self.get_task(task_record.task_id)
        if existing_task:
            # CONTRACT: get_task returns TaskRecord, not dict
            if not isinstance(existing_task, TaskRecord):
                raise TypeError(
                    f"get_task returned {type(existing_task).__name__}, expected TaskRecord. "
                    f"Repository contract violation detected."
                )
            logger.info(f"📋 Task already exists (idempotent): {task_record.task_id}")
            return existing_task

        # Create in database
        created = self.create_task(task_record)
        return task_record
    
    @enforce_contract(
        params={
            'task_id': str,
            'new_status': TaskStatus,
            'additional_updates': (dict, type(None))
        },
        returns=bool
    )
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
            
            # Prepare updates (ensure enum is converted to string value)
            updates = {'status': new_status.value}
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

class StageCompletionRepository(PostgreSQLStageCompletionRepository):
    """
    Stage completion repository providing atomic data operations.

    This repository provides atomic database queries for stage completion detection
    using PostgreSQL advisory locks to prevent race conditions. It inherits three
    critical atomic operations from PostgreSQLStageCompletionRepository:

    1. complete_task_and_check_stage() - Atomically completes task and checks if stage done
    2. advance_job_stage() - Atomically advances job to next stage
    3. check_job_completion() - Atomically checks if all job tasks complete

    All orchestration logic (deciding what to do with these atomic results) belongs
    in the Controller layer, not here in the Repository layer.
    """
    
    # REMOVED: handle_task_completion() method - Orchestration belongs in Controller layer
    # The CompletionDetector should only provide atomic database operations via inherited
    # PostgreSQL functions. All business logic and orchestration has been moved to
    # BaseController._handle_stage_completion() where it architecturally belongs.
    #
    # This class now only inherits atomic operations:
    # - complete_task_and_check_stage() - Atomic task completion with stage check
    # - advance_job_stage() - Atomic stage advancement
    # - check_job_completion() - Atomic job completion check
    #
    # Date: 20 SEP 2025
    # Reason: Separation of concerns - Repository provides data operations,
    #         Controller handles orchestration

    pass  # This class only inherits atomic operations, no additional methods


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'JobRepository',
    'TaskRepository', 
    'CompletionDetector'
]