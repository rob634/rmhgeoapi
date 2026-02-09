# ============================================================================
# JOB AND TASK REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Core job/task persistence with business logic
# PURPOSE: Extended repositories for job/task CRUD, status, and completion
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Job and Task Repository Implementation.

Business logic repositories for job and task management, extending PostgreSQL
base implementations with validation and orchestration.

Architecture:
    PostgreSQLJobRepository → JobRepository (adds business logic)
    PostgreSQLTaskRepository → TaskRepository (adds business logic)
    PostgreSQLStageCompletionRepository → StageCompletionRepository

Handles all job and task persistence operations including idempotency checks,
status transitions, and completion detection.

Exports:
    JobRepository: Extended job repository with business logic
    TaskRepository: Extended task repository with business logic
    StageCompletionRepository: Atomic stage completion operations
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
from config import __version__ as etl_version  # V0.8.12: ETL version tracking
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
            # V0.8.12: Add etl_version tracking (08 FEB 2026)
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
                etl_version=etl_version,  # Track which ETL version ran this job
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

    def reset_failed_job(self, job_id: str, preserve_error: bool = True) -> Dict[str, Any]:
        """
        Reset a failed job for re-processing (09 DEC 2025).

        This method is used for failed job re-submission. It:
        1. Optionally preserves error history in job metadata
        2. Resets job state to stage 1 with status QUEUED
        3. Clears error_details and result_data for fresh start

        Args:
            job_id: Job ID to reset
            preserve_error: If True, append current error to metadata.error_history[]

        Returns:
            Dict with reset results:
            {
                "reset": True/False,
                "attempt": int (new attempt number),
                "previous_stage": int,
                "previous_error": str or None
            }

        Raises:
            ValueError: If job not found or not in failed status

        Example:
            result = job_repo.reset_failed_job("abc123...")
            # result = {"reset": True, "attempt": 2, "previous_stage": 3, "previous_error": "..."}
        """
        import json
        from psycopg import sql

        with self._error_context("reset failed job", job_id):
            # Get current job
            current_job = self.get_job(job_id)

            if not current_job:
                raise ValueError(f"Job not found: {job_id}")

            # Verify job is in failed status
            job_status = current_job.status.value if hasattr(current_job.status, 'value') else str(current_job.status)
            if job_status != 'failed':
                raise ValueError(
                    f"Cannot reset job with status '{job_status}'. "
                    f"Only failed jobs can be reset for re-submission."
                )

            # Prepare error history preservation
            previous_stage = current_job.stage
            previous_error = current_job.error_details

            # Get existing metadata (may be None or {})
            existing_metadata = current_job.metadata if hasattr(current_job, 'metadata') and current_job.metadata else {}
            error_history = existing_metadata.get('error_history', [])
            new_attempt = len(error_history) + 2  # +2 because original was attempt 1

            if preserve_error and previous_error:
                # Append current error to history
                error_entry = {
                    "attempt": new_attempt - 1,  # This was the failed attempt
                    "failed_at": current_job.updated_at.isoformat() if current_job.updated_at else None,
                    "failed_stage": previous_stage,
                    "error": previous_error
                }
                error_history.append(error_entry)
                existing_metadata['error_history'] = error_history

            # Update job to reset state
            query = sql.SQL("""
                UPDATE {schema}.{table}
                SET status = 'queued',
                    stage = 1,
                    error_details = NULL,
                    result_data = NULL,
                    stage_results = '{{}}',
                    metadata = %s,
                    updated_at = NOW()
                WHERE job_id = %s AND status = 'failed'
                RETURNING job_id
            """).format(
                schema=sql.Identifier(self.schema_name),
                table=sql.Identifier("jobs")
            )

            result = self._execute_query(
                query,
                (json.dumps(existing_metadata), job_id),
                fetch='one'
            )

            if result:
                logger.info(
                    f"🔄 Reset failed job {job_id[:16]}... for attempt #{new_attempt} "
                    f"(was at stage {previous_stage})"
                )
                return {
                    "reset": True,
                    "attempt": new_attempt,
                    "previous_stage": previous_stage,
                    "previous_error": previous_error
                }
            else:
                logger.warning(f"⚠️ Failed to reset job {job_id[:16]}... (concurrent modification?)")
                return {
                    "reset": False,
                    "attempt": new_attempt - 1,
                    "previous_stage": previous_stage,
                    "previous_error": previous_error
                }

    # ========================================================================
    # CENTRALIZED QUERY METHODS (09 FEB 2026)
    # These methods replace hardcoded SQL in admin endpoints and web interfaces
    # ========================================================================

    def list_jobs_with_filters(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[str] = None,
        hours: Optional[int] = None,
        limit: int = 100
    ) -> List[JobRecord]:
        """
        List jobs with flexible filtering options.

        Replaces hardcoded queries in:
        - triggers/admin/db_data.py:_get_jobs()
        - web_interfaces/execution/interface.py:_query_jobs()

        Args:
            status: Filter by job status (optional)
            job_type: Filter by job type (optional)
            hours: Only include jobs from last N hours (optional, None=all)
            limit: Maximum results (default 100)

        Returns:
            List of JobRecord objects
        """
        from psycopg import sql

        with self._error_context("list jobs with filters"):
            # Build dynamic query
            query_parts = [
                sql.SQL("""
                    SELECT job_id, job_type, status, stage, total_stages,
                           parameters, stage_results, result_data, error_details,
                           asset_id, platform_id, request_id, etl_version,
                           created_at, updated_at
                    FROM {}.{}
                    WHERE 1=1
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs")
                )
            ]
            params = []

            if hours is not None:
                query_parts.append(sql.SQL(" AND created_at >= NOW() - INTERVAL '{} hours'").format(
                    sql.Literal(hours)
                ))

            if status is not None:
                query_parts.append(sql.SQL(" AND status = %s"))
                params.append(status.value if hasattr(status, 'value') else status)

            if job_type is not None:
                query_parts.append(sql.SQL(" AND job_type = %s"))
                params.append(job_type)

            query_parts.append(sql.SQL(" ORDER BY created_at DESC LIMIT %s"))
            params.append(limit)

            query = sql.Composed(query_parts)
            rows = self._execute_query(query, tuple(params) if params else None, fetch='all')

            jobs = []
            for row in rows:
                job_data = self._row_to_job_record(row)
                jobs.append(JobRecord(**job_data))

            logger.debug(f"📋 Listed {len(jobs)} jobs with filters")
            return jobs

    def list_jobs_with_task_counts(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[str] = None,
        hours: Optional[int] = 168,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List jobs with aggregated task status counts.

        Replaces hardcoded queries in:
        - triggers/admin/db_data.py:_get_jobs() (with task_counts)
        - web_interfaces/jobs/interface.py:_query_jobs_with_task_counts()

        Args:
            status: Filter by job status (optional)
            job_type: Filter by job type (optional)
            hours: Only include jobs from last N hours (default 168/7 days, None=all)
            limit: Maximum results (default 100)

        Returns:
            List of dicts with job data + task_counts
        """
        from psycopg import sql

        with self._error_context("list jobs with task counts"):
            # Build query with task counts subquery
            base_query = sql.SQL("""
                SELECT j.job_id, j.job_type, j.status::text as status, j.stage, j.total_stages,
                       j.parameters, j.result_data, j.error_details,
                       j.asset_id, j.platform_id, j.request_id, j.etl_version,
                       j.created_at, j.updated_at,
                       COALESCE(tc.queued, 0) as task_queued,
                       COALESCE(tc.processing, 0) as task_processing,
                       COALESCE(tc.completed, 0) as task_completed,
                       COALESCE(tc.failed, 0) as task_failed
                FROM {schema}.jobs j
                LEFT JOIN (
                    SELECT parent_job_id,
                           COUNT(*) FILTER (WHERE status::text = 'queued') as queued,
                           COUNT(*) FILTER (WHERE status::text = 'processing') as processing,
                           COUNT(*) FILTER (WHERE status::text = 'completed') as completed,
                           COUNT(*) FILTER (WHERE status::text = 'failed') as failed
                    FROM {schema}.tasks
                    GROUP BY parent_job_id
                ) tc ON j.job_id = tc.parent_job_id
                WHERE 1=1
            """).format(schema=sql.Identifier(self.schema_name))

            query_parts = [base_query]
            params = []

            if hours is not None:
                query_parts.append(sql.SQL(" AND j.created_at >= NOW() - INTERVAL '{} hours'").format(
                    sql.Literal(hours)
                ))

            if status is not None:
                query_parts.append(sql.SQL(" AND j.status::text = %s"))
                params.append(status.value if hasattr(status, 'value') else status)

            if job_type is not None:
                query_parts.append(sql.SQL(" AND j.job_type = %s"))
                params.append(job_type)

            query_parts.append(sql.SQL(" ORDER BY j.created_at DESC LIMIT %s"))
            params.append(limit)

            query = sql.Composed(query_parts)
            rows = self._execute_query(query, tuple(params) if params else None, fetch='all')

            jobs = []
            for row in rows:
                jobs.append({
                    'job_id': row['job_id'],
                    'job_type': row['job_type'],
                    'status': row['status'],
                    'stage': row['stage'],
                    'total_stages': row['total_stages'],
                    'parameters': row['parameters'],
                    'result_data': row['result_data'],
                    'error_details': row['error_details'],
                    'asset_id': row['asset_id'],
                    'platform_id': row['platform_id'],
                    'request_id': row['request_id'],
                    'etl_version': row['etl_version'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                    'task_counts': {
                        'queued': row['task_queued'],
                        'processing': row['task_processing'],
                        'completed': row['task_completed'],
                        'failed': row['task_failed']
                    }
                })

            logger.debug(f"📋 Listed {len(jobs)} jobs with task counts")
            return jobs

    def get_job_summary(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get lightweight job info without heavy JSONB fields.

        Replaces hardcoded queries in:
        - web_interfaces/execution/interface.py:_get_job_info()

        Args:
            job_id: Job ID to retrieve

        Returns:
            Dict with job summary (no parameters/results), or None
        """
        from psycopg import sql

        with self._error_context("get job summary", job_id):
            query = sql.SQL("""
                SELECT job_id, job_type, status::text as status, stage, total_stages,
                       asset_id, platform_id, request_id, etl_version,
                       created_at, updated_at
                FROM {}.{}
                WHERE job_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs")
            )

            row = self._execute_query(query, (job_id,), fetch='one')

            if not row:
                return None

            return {
                'job_id': row['job_id'],
                'job_type': row['job_type'],
                'status': row['status'],
                'stage': row['stage'],
                'total_stages': row['total_stages'],
                'asset_id': row['asset_id'],
                'platform_id': row['platform_id'],
                'request_id': row['request_id'],
                'etl_version': row['etl_version'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
            }

    def _row_to_job_record(self, row) -> Dict[str, Any]:
        """Convert database row to JobRecord-compatible dict."""
        from infrastructure.postgresql import _parse_jsonb_column

        job_id = row['job_id']
        return {
            'job_id': job_id,
            'job_type': row['job_type'],
            'status': row['status'],
            'stage': row['stage'],
            'total_stages': row['total_stages'],
            'parameters': _parse_jsonb_column(row['parameters'], 'parameters', job_id, default={}),
            'stage_results': _parse_jsonb_column(row.get('stage_results'), 'stage_results', job_id, default={}),
            'result_data': _parse_jsonb_column(row.get('result_data'), 'result_data', job_id, default=None),
            'error_details': row.get('error_details'),
            'asset_id': row.get('asset_id'),
            'platform_id': row.get('platform_id'),
            'request_id': row.get('request_id'),
            'etl_version': row.get('etl_version'),
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }


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
                if 'last_pulse' in additional_updates:
                    update.last_pulse = additional_updates['last_pulse']
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

    def update_task_pulse(self, task_id: str) -> bool:
        """
        Update task pulse timestamp (for long-running Docker tasks).

        Args:
            task_id: Task ID to update

        Returns:
            True if updated successfully
        """
        update = TaskUpdateModel(last_pulse=datetime.now(timezone.utc))
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
        initial_status: TaskStatus = TaskStatus.PENDING
    ) -> List[TaskRecord]:
        """
        Batch create tasks using PostgreSQL executemany.
        Aligned to Service Bus batch size (100 tasks max).

        Args:
            task_definitions: List of TaskDefinition objects (max 100)
            batch_id: Optional batch identifier for tracking
            initial_status: Initial task status (default: PENDING - 16 DEC 2025)

        Returns:
            List of created TaskRecord objects

        Raises:
            ValueError: If batch size exceeds limit
            RuntimeError: If database operation fails

        Note (16 DEC 2025): Changed from raw string 'pending_queue' to TaskStatus.PENDING.
        Tasks start as PENDING until trigger confirms receipt (QUEUED).
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
                # 16 DEC 2025: Use initial_status.value for enum compatibility
                data.append((
                    task_record.task_id,
                    task_record.parent_job_id,
                    task_record.task_type,
                    initial_status.value,  # 16 DEC 2025: Use enum value, not raw string
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

    def delete_tasks_for_job(self, job_id: str) -> int:
        """
        Delete all tasks for a job (09 DEC 2025).

        Used during failed job re-submission to clear old tasks before
        creating new ones. Tasks will be recreated when the job is re-queued.

        Args:
            job_id: Job identifier

        Returns:
            Number of tasks deleted

        Example:
            deleted_count = task_repo.delete_tasks_for_job('job123...')
            # deleted_count = 6
        """
        from psycopg import sql

        with self._error_context("delete tasks for job", job_id):
            query = sql.SQL("""
                DELETE FROM {schema}.{table}
                WHERE parent_job_id = %s
                RETURNING task_id
            """).format(
                schema=sql.Identifier(self.schema_name),
                table=sql.Identifier("tasks")
            )

            # Execute and count deleted rows
            result = self._execute_query(query, (job_id,), fetch='all')

            deleted_count = len(result) if result else 0

            if deleted_count > 0:
                logger.info(f"🗑️ Deleted {deleted_count} tasks for job {job_id[:16]}...")
            else:
                logger.debug(f"📋 No tasks to delete for job {job_id[:16]}...")

            return deleted_count

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
              AND created_at > NOW() - make_interval(mins => %s)
            LIMIT %s
        """).format(sql.Identifier(self.schema_name))

        results = self._execute_query(query, (max_age_minutes, limit))
        return [r['batch_id'] for r in results]

    # ========================================================================
    # TASK METADATA OPERATIONS - For progress tracking (24 OCT 2025)
    # ========================================================================

    def update_task_metadata(
        self,
        task_id: str,
        metadata: Dict[str, Any],
        merge: bool = True
    ) -> bool:
        """
        Update task metadata (for progress tracking during long-running tasks).

        Used by services like tiling_extraction to report progress back to the
        orchestration layer without changing task status.

        Args:
            task_id: Task ID to update
            metadata: Metadata dict to set or merge
            merge: If True, merge with existing metadata; if False, replace entirely

        Returns:
            True if updated successfully

        Example:
            # Sequential extraction progress (Stage 2)
            repo.update_task_metadata(task_id, {
                "extraction_progress": {
                    "tiles_extracted": 42,
                    "total_tiles": 204,
                    "current_tile": "tile_5_7",
                    "elapsed_seconds": 95.3,
                    "percent_complete": 20.6
                }
            }, merge=True)
        """
        with self._error_context("update task metadata", task_id):
            # Get current task to preserve existing metadata if merging
            if merge:
                current_task = self.get_task(task_id)
                if not current_task:
                    logger.warning(f"📋 Cannot update metadata - task not found: {task_id}")
                    return False

                # Merge metadata (deep merge for nested dicts)
                merged_metadata = current_task.metadata.copy() if current_task.metadata else {}
                merged_metadata.update(metadata)
                final_metadata = merged_metadata
            else:
                final_metadata = metadata

            # Update using Pydantic model
            update = TaskUpdateModel(metadata=final_metadata)
            success = self.update_task(task_id, update)

            if success:
                logger.debug(f"📋 Updated metadata for task {task_id[:16]}... (merge={merge})")
            else:
                logger.warning(f"⚠️ Failed to update metadata for task {task_id[:16]}...")

            return success

    def get_task_metadata(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task metadata only (without fetching entire TaskRecord).

        Args:
            task_id: Task ID to query

        Returns:
            Task metadata dict, or None if task not found
        """
        from psycopg import sql

        with self._error_context("get task metadata", task_id):
            query = sql.SQL("""
                SELECT metadata
                FROM {schema}.tasks
                WHERE task_id = %s
            """).format(schema=sql.Identifier(self.schema_name))

            result = self._execute_query(query, (task_id,), fetch='one')

            if result:
                return result.get('metadata', {})
            else:
                logger.debug(f"📋 Task not found: {task_id[:16]}...")
                return None

    def get_task_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task progress from metadata (convenience method).

        Returns progress data if it exists in metadata, otherwise None.
        This is a convenience wrapper around get_task_metadata that extracts
        common progress-related fields.

        Args:
            task_id: Task ID to query

        Returns:
            Dict with progress fields, or None if no progress data

        Example returned dict (from tiling extraction):
            {
                "tiles_extracted": 42,
                "total_tiles": 204,
                "current_tile": "tile_5_7",
                "elapsed_seconds": 95.3,
                "percent_complete": 20.6
            }
        """
        metadata = self.get_task_metadata(task_id)

        if not metadata:
            return None

        # Check for various progress field patterns
        # (different services may use different field names)
        progress_patterns = [
            'extraction_progress',
            'conversion_progress',
            'processing_progress',
            'progress'
        ]

        for pattern in progress_patterns:
            if pattern in metadata:
                return metadata[pattern]

        # No recognized progress data found
        return None

    # ========================================================================
    # CENTRALIZED QUERY METHODS (09 FEB 2026)
    # These methods replace hardcoded SQL in admin endpoints and web interfaces
    # ========================================================================

    def get_task_counts_for_job(self, job_id: str) -> Dict[str, int]:
        """
        Get aggregated task counts by status for a job.

        Replaces hardcoded queries in:
        - web_interfaces/execution/interface.py:_get_task_counts()

        Args:
            job_id: Job ID to get task counts for

        Returns:
            Dict with status -> count mapping
        """
        from psycopg import sql

        with self._error_context("get task counts for job", job_id):
            query = sql.SQL("""
                SELECT status::text as status, COUNT(*) as count
                FROM {schema}.tasks
                WHERE parent_job_id = %s
                GROUP BY status
            """).format(schema=sql.Identifier(self.schema_name))

            rows = self._execute_query(query, (job_id,), fetch='all')

            counts = {'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}
            for row in rows:
                status = row['status']
                if status in counts:
                    counts[status] = row['count']

            return counts

    def get_task_counts_by_stage(self, job_id: str) -> List[Dict[str, Any]]:
        """
        Get task counts grouped by stage and status for a job.

        Replaces hardcoded queries in:
        - web_interfaces/execution/interface.py:_get_task_counts_by_stage()

        Args:
            job_id: Job ID to get task counts for

        Returns:
            List of dicts with stage, status, count
        """
        from psycopg import sql

        with self._error_context("get task counts by stage", job_id):
            query = sql.SQL("""
                SELECT stage, status::text as status, COUNT(*) as count
                FROM {schema}.tasks
                WHERE parent_job_id = %s
                GROUP BY stage, status
                ORDER BY stage, status
            """).format(schema=sql.Identifier(self.schema_name))

            rows = self._execute_query(query, (job_id,), fetch='all')

            return [
                {
                    'stage': row['stage'],
                    'status': row['status'],
                    'count': row['count']
                }
                for row in rows
            ]

    def list_tasks_with_filters(
        self,
        job_id: Optional[str] = None,
        status: Optional[str] = None,
        stage: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List tasks with flexible filtering options.

        Replaces hardcoded queries in:
        - triggers/admin/db_data.py:_get_tasks()
        - triggers/admin/db_data.py:_get_tasks_for_job()
        - web_interfaces/execution/interface.py:_query_tasks()

        Args:
            job_id: Filter by parent job ID (optional)
            status: Filter by task status (optional)
            stage: Filter by stage number (optional)
            limit: Maximum results (default 100)

        Returns:
            List of task dicts
        """
        from psycopg import sql

        with self._error_context("list tasks with filters"):
            query_parts = [
                sql.SQL("""
                    SELECT task_id, parent_job_id, job_type, task_type,
                           status::text as status, stage, task_index,
                           parameters, result_data, error_details,
                           retry_count, created_at, updated_at
                    FROM {schema}.tasks
                    WHERE 1=1
                """).format(schema=sql.Identifier(self.schema_name))
            ]
            params = []

            if job_id is not None:
                query_parts.append(sql.SQL(" AND parent_job_id = %s"))
                params.append(job_id)

            if status is not None:
                query_parts.append(sql.SQL(" AND status::text = %s"))
                params.append(status)

            if stage is not None:
                query_parts.append(sql.SQL(" AND stage = %s"))
                params.append(stage)

            query_parts.append(sql.SQL(" ORDER BY created_at DESC LIMIT %s"))
            params.append(limit)

            query = sql.Composed(query_parts)
            rows = self._execute_query(query, tuple(params), fetch='all')

            return [
                {
                    'task_id': row['task_id'],
                    'parent_job_id': row['parent_job_id'],
                    'job_type': row['job_type'],
                    'task_type': row['task_type'],
                    'status': row['status'],
                    'stage': row['stage'],
                    'task_index': row['task_index'],
                    'parameters': row['parameters'],
                    'result_data': row['result_data'],
                    'error_details': row['error_details'],
                    'retry_count': row['retry_count'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                }
                for row in rows
            ]


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