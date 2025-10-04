# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# CATEGORY: AZURE RESOURCE REPOSITORIES
# PURPOSE: Azure SDK wrapper providing data access abstraction
# EPOCH: Shared by all epochs (infrastructure layer)# PURPOSE: Business logic repository layer for job and task management with validation and orchestration
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
from core.models import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    TaskResult, TaskDefinition  # Added for contract enforcement
)
from core.utils import generate_job_id  # ID generation utility
from core.schema.updates import TaskUpdateModel, JobUpdateModel
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
            
            # Prepare updates using Pydantic model
            update = JobUpdateModel(status=new_status)

            # Add additional updates if provided
            if additional_updates:
                # Merge additional updates into the model
                if 'error_details' in additional_updates:
                    update.error_details = additional_updates['error_details']
                if 'stage' in additional_updates:
                    update.stage = additional_updates['stage']
                if 'stage_results' in additional_updates:
                    update.stage_results = additional_updates['stage_results']
                if 'result_data' in additional_updates:
                    update.result_data = additional_updates['result_data']
                if 'metadata' in additional_updates:
                    update.metadata = additional_updates['metadata']

            # Update in database
            return self.update_job(job_id, update)
    
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
            
            # Prepare updates using Pydantic model
            update = JobUpdateModel(stage=new_stage)

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
                update.stage_results = updated_stage_results

            return self.update_job(job_id, update)
    
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
            
            # Prepare updates using Pydantic model
            update = TaskUpdateModel(status=new_status)

            # Add additional updates if provided
            if additional_updates:
                # Merge additional updates into the model
                if 'error_details' in additional_updates:
                    update.error_details = additional_updates['error_details']
                if 'result_data' in additional_updates:
                    update.result_data = additional_updates['result_data']
                if 'heartbeat' in additional_updates:
                    update.heartbeat = additional_updates['heartbeat']
                if 'retry_count' in additional_updates:
                    update.retry_count = additional_updates['retry_count']
                if 'metadata' in additional_updates:
                    update.metadata = additional_updates['metadata']

            # Update in database
            return self.update_task(task_id, update)

    def increment_task_retry_count(self, task_id: str) -> bool:
        """
        Atomically increment retry count and reset status to QUEUED.

        Calls the PostgreSQL function increment_task_retry_count() for atomic operation.
        This is used when a task fails and needs to be retried with exponential backoff.

        Args:
            task_id: Task ID to increment retry count for

        Returns:
            True if updated successfully, False if task not found
        """
        from psycopg import sql

        with self._error_context("increment retry count", task_id):
            # Call PostgreSQL function for atomic increment + status reset
            query = sql.SQL("""
                SELECT * FROM {schema}.increment_task_retry_count(%s)
            """).format(schema=sql.Identifier(self.schema_name))

            result = self._execute_query(query, (task_id,), fetch='one')

            if result and result.get('new_retry_count') is not None:
                new_retry_count = result['new_retry_count']
                logger.info(f"🔄 Task {task_id[:16]} retry count → {new_retry_count}, status → QUEUED")
                return True
            else:
                logger.warning(f"⚠️ Cannot increment retry count - task not found: {task_id}")
                return False

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
    
    def update_task_with_model(self, task_id: str, update_model: TaskUpdateModel) -> bool:
        """
        Update task using Pydantic model.

        This is a wrapper method for API consistency with StateManager.
        Both this method and update_task accept TaskUpdateModel.

        Args:
            task_id: Task ID to update
            update_model: TaskUpdateModel with fields to update

        Returns:
            True if updated successfully
        """
        return self.update_task(task_id, update_model)

    def update_task_heartbeat(self, task_id: str) -> bool:
        """
        Update task heartbeat timestamp.

        Args:
            task_id: Task ID to update

        Returns:
            True if updated successfully
        """
        update = TaskUpdateModel(heartbeat=datetime.now(timezone.utc))
        return self.update_task(task_id, update)
    
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

            update = TaskUpdateModel(retry_count=task.retry_count + 1)
            return self.update_task(task_id, update)

    # ========================================================================
    # BATCH OPERATIONS - For Service Bus aligned batching
    # ========================================================================

    BATCH_SIZE = 100  # Aligned with Service Bus limit

    def batch_create_tasks(
        self,
        task_definitions: List[TaskDefinition],
        batch_id: Optional[str] = None,
        initial_status: str = 'pending_queue'
    ) -> List[TaskRecord]:
        """
        Batch create tasks using PostgreSQL executemany.
        Aligned to Service Bus batch size (100 tasks max).

        Args:
            task_definitions: List of TaskDefinition objects (max 100)
            batch_id: Optional batch identifier for tracking
            initial_status: Initial task status (default: pending_queue)

        Returns:
            List of created TaskRecord objects

        Raises:
            ValueError: If batch size exceeds limit
            RuntimeError: If database operation fails
        """
        if len(task_definitions) > self.BATCH_SIZE:
            raise ValueError(f"Batch too large: {len(task_definitions)} > {self.BATCH_SIZE}")

        logger.info(f"📦 Batch creating {len(task_definitions)} tasks with batch_id: {batch_id}")

        try:
            # Convert TaskDefinitions to tuples for executemany
            now = datetime.now(timezone.utc)
            data = []

            for td in task_definitions:
                # Convert TaskDefinition to TaskRecord
                task_record = td.to_task_record()

                # Prepare data tuple for SQL insert
                data.append((
                    task_record.task_id,
                    task_record.parent_job_id,
                    task_record.task_type,
                    initial_status,  # Use initial_status instead of task_record.status
                    task_record.stage_number,
                    json.dumps(task_record.parameters) if task_record.parameters else '{}',
                    batch_id,  # Add batch_id
                    0,  # retry_count
                    json.dumps(task_record.metadata) if task_record.metadata else '{}',
                    now,
                    now
                ))

            # Execute batch insert
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Use executemany for batch insert
                cursor.executemany(
                    f"""
                    INSERT INTO {self.schema_name}.tasks (
                        task_id, parent_job_id, task_type, status,
                        stage_number, parameters, batch_id, retry_count,
                        metadata, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    data
                )

                conn.commit()
                affected = cursor.rowcount

                logger.info(f"✅ Batch insert successful: {affected} tasks created")

            # Return TaskRecord objects
            return [td.to_task_record() for td in task_definitions]

        except Exception as e:
            logger.error(f"❌ Batch task creation failed: {e}")
            raise RuntimeError(f"Failed to batch create tasks: {e}")

    def batch_update_status(
        self,
        task_ids: List[str],
        new_status: str,
        additional_updates: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Batch update task status for multiple tasks.

        Args:
            task_ids: List of task IDs to update
            new_status: New status value
            additional_updates: Optional additional fields to update

        Returns:
            Number of tasks updated

        Example:
            # Mark batch as queued after successful Service Bus send
            task_repo.batch_update_status(
                task_ids=['task1', 'task2', ...],
                new_status='queued',
                additional_updates={'queued_at': datetime.now(timezone.utc)}
            )
        """
        if not task_ids:
            return 0

        logger.info(f"📝 Batch updating status for {len(task_ids)} tasks to: {new_status}")

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Build update query
                set_clauses = [f"status = %s", f"updated_at = %s"]
                params = [new_status, datetime.now(timezone.utc)]

                if additional_updates:
                    for key, value in additional_updates.items():
                        set_clauses.append(f"{key} = %s")
                        params.append(value)

                # Add task IDs to params
                params.append(tuple(task_ids))

                query = f"""
                    UPDATE {self.schema_name}.tasks
                    SET {', '.join(set_clauses)}
                    WHERE task_id = ANY(%s)
                """

                cursor.execute(query, params)
                conn.commit()

                updated = cursor.rowcount
                logger.info(f"✅ Batch status update successful: {updated} tasks updated")

                return updated

        except Exception as e:
            logger.error(f"❌ Batch status update failed: {e}")
            raise RuntimeError(f"Failed to batch update task status: {e}")

    def get_tasks_by_batch(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Get all tasks for a specific batch.

        Args:
            batch_id: Batch identifier

        Returns:
            List of task dictionaries

        Example:
            tasks = task_repo.get_tasks_by_batch('job123-b0')
        """
        from psycopg import sql

        query = sql.SQL("""
            SELECT * FROM {}.tasks
            WHERE batch_id = %s
            ORDER BY created_at
        """).format(sql.Identifier(self.schema_name))

        return self._execute_query(query, (batch_id,))

    def get_tasks_for_job(self, job_id: str) -> List['TaskRecord']:
        """
        Get all tasks for a specific job as TaskRecord objects.

        Args:
            job_id: Job identifier

        Returns:
            List of TaskRecord Pydantic objects

        Example:
            task_records = task_repo.get_tasks_for_job('job123')
        """
        from core.models import TaskRecord
        from psycopg import sql

        query = sql.SQL("""
            SELECT * FROM {}.tasks
            WHERE parent_job_id = %s
            ORDER BY stage, task_index
        """).format(sql.Identifier(self.schema_name))

        rows = self._execute_query(query, (job_id,), fetch='all')

        # Convert to TaskRecord objects
        task_records = []
        if rows:  # Defensive check - handle None or empty list
            for row in rows:
                task_records.append(TaskRecord(**row))

        return task_records

    def get_pending_retry_batches(
        self,
        max_age_minutes: int = 30,
        limit: int = 10
    ) -> List[str]:
        """
        Get batch IDs that have tasks pending retry.

        Args:
            max_age_minutes: Maximum age of tasks to retry
            limit: Maximum number of batches to return

        Returns:
            List of batch IDs needing retry
        """
        from psycopg import sql

        query = sql.SQL("""
            SELECT DISTINCT batch_id
            FROM {}.tasks
            WHERE status = 'pending_retry'
              AND batch_id IS NOT NULL
              AND created_at > NOW() - INTERVAL %s
            LIMIT %s
        """).format(sql.Identifier(self.schema_name))

        # Create proper interval string
        interval_str = f'{max_age_minutes} minutes'
        results = self._execute_query(query, (interval_str, limit))
        return [r['batch_id'] for r in results]


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