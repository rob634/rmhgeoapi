# ============================================================================
# EXECUTION RESULT DATA MODELS
# ============================================================================
# STATUS: Core - Pure result data structures
# PURPOSE: TaskResult, StageResultContract, and job completion models
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Execution Result Data Models.

Represents results of job, stage, and task execution.
No business logic - pure data structures.

Exports:
    TaskResult: Result from task execution
    StageResultContract: Contract for stage results
    StageAdvancementResult: Result of stage advancement
    JobCompletionResult: Result of job completion
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .enums import TaskStatus


class TaskResult(BaseModel):
    """
    Result from task execution.

    Pure data structure - success/failure logic is in core.logic.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    task_id: str = Field(..., description="Task identifier")
    task_type: str = Field(..., description="Type of task")
    status: TaskStatus = Field(..., description="Task execution status")
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Task output data")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time_ms: Optional[int] = Field(default=None, description="Execution time in milliseconds")
    timestamp: datetime = Field(..., description="Completion timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

    @property
    def success(self) -> bool:
        """Check if task completed successfully."""
        return self.status == TaskStatus.COMPLETED


class StageResultContract(BaseModel):
    """
    Contract for stage result data.

    Ensures consistent structure for stage results stored in the database.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    stage: int = Field(..., ge=1, description="Stage number")
    status: str = Field(..., description="Stage completion status")
    task_count: int = Field(..., ge=0, description="Total tasks in stage")
    successful_count: int = Field(..., ge=0, description="Successful tasks")
    failed_count: int = Field(..., ge=0, description="Failed tasks")
    task_results: List[Dict[str, Any]] = Field(default_factory=list, description="Individual task results")
    aggregated_data: Optional[Dict[str, Any]] = Field(default=None, description="Aggregated stage data")
    error_summary: Optional[List[str]] = Field(default=None, description="Summary of errors")
    completion_time: Optional[datetime] = Field(default=None, description="Stage completion time")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ['completed', 'failed', 'completed_with_errors', 'partial']
        if v not in valid_statuses:
            raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v

    @classmethod
    def from_task_results(
        cls,
        stage_number: int,
        task_results: List['TaskResult'],
        metadata: Optional[Dict[str, Any]] = None
    ) -> 'StageResultContract':
        """
        Aggregate individual task results into a stage result contract.

        Args:
            stage_number: The stage number
            task_results: List of TaskResult objects from the stage
            metadata: Optional additional metadata

        Returns:
            StageResultContract with aggregated results
        """
        from core.logic.calculations import get_error_summary

        successful = sum(1 for r in task_results if r.success)
        failed = len(task_results) - successful

        if failed == 0:
            status = 'completed'
        elif successful == 0:
            status = 'failed'
        else:
            status = 'completed_with_errors'

        return cls(
            stage=stage_number,
            status=status,
            task_count=len(task_results),
            successful_count=successful,
            failed_count=failed,
            task_results=[r.model_dump() for r in task_results],
            aggregated_data=metadata,
            error_summary=get_error_summary(task_results),
            completion_time=datetime.now(timezone.utc)
        )


class StageAdvancementResult(BaseModel):
    """
    Result from stage advancement operation.

    Returned by PostgreSQL function or stage advancement logic.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    job_updated: bool = Field(..., description="Whether job was updated")
    new_stage: int = Field(..., description="New stage number")
    is_final_stage: bool = Field(..., description="Whether this is the final stage")
    all_tasks_complete: Optional[bool] = Field(default=None, description="Whether all tasks completed")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Advancement timestamp")


class TaskCompletionResult(BaseModel):
    """
    Result from PostgreSQL complete_task_and_check_stage() function.

    Represents the contract between SQL and Python layers.
    """

    model_config = ConfigDict(extra="forbid")

    task_updated: bool = Field(..., description="Whether task was updated")
    stage_complete: bool = Field(..., description="Whether stage is complete")
    job_id: Optional[str] = Field(default=None, description="Job ID")
    stage_number: Optional[int] = Field(default=None, description="Stage number")
    remaining_tasks: int = Field(default=0, description="Remaining tasks in stage")


class JobCompletionResult(BaseModel):
    """
    Result from job completion check.

    Used to track final job state and aggregated results.
    """

    model_config = ConfigDict(extra="forbid")

    job_complete: bool = Field(..., description="Whether job is complete")
    final_stage: int = Field(..., description="Final stage number")
    total_tasks: int = Field(..., description="Total tasks across all stages")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    task_results: Optional[Dict[str, Any]] = Field(default=None, description="Aggregated task results")


# ============================================================================
# PROCESS_VECTOR STAGE RESULT MODELS (GAP-006 FIX - 15 DEC 2025)
# ============================================================================


class ProcessVectorStage1Data(BaseModel):
    """
    Validated structure for process_vector Stage 1 result data.

    GAP-006 FIX: Ensures Stage 2 receives well-formed data from Stage 1.
    Prevents KeyError, AttributeError, or silent empty values.

    This is the 'result' field inside the task result wrapper.
    """

    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compat

    chunk_paths: List[str] = Field(
        ...,
        min_length=1,
        description="Paths to pickled chunk files in Silver zone"
    )
    total_features: int = Field(
        ...,
        gt=0,
        description="Total features loaded from source file"
    )
    num_chunks: int = Field(
        ...,
        gt=0,
        description="Number of chunks created"
    )
    table_name: str = Field(
        ...,
        min_length=1,
        description="Target PostGIS table name"
    )
    schema: str = Field(
        default="geo",
        description="Target PostGIS schema"
    )
    columns: List[str] = Field(
        default_factory=list,
        description="Column names (excluding reserved: id, geom, etl_batch_id)"
    )
    geometry_type: str = Field(
        default="GEOMETRY",
        description="PostGIS geometry type (POINT, POLYGON, MULTIPOLYGON, etc.)"
    )
    srid: int = Field(
        default=4326,
        description="Spatial Reference ID (always 4326 after reprojection)"
    )
    chunk_size_used: Optional[int] = Field(
        default=None,
        description="Actual rows per chunk"
    )
    source_file: Optional[str] = Field(
        default=None,
        description="Original source file path"
    )
    source_crs: Optional[str] = Field(
        default=None,
        description="Original CRS before reprojection"
    )


class ProcessVectorStage1Result(BaseModel):
    """
    Full task result wrapper for process_vector Stage 1.

    GAP-006 FIX: Validates the complete task result structure.

    Example input:
        {
            "success": True,
            "result": {
                "chunk_paths": ["pickles/abc123/chunk_0.pkl", ...],
                "total_features": 50000,
                "num_chunks": 5,
                "table_name": "my_table",
                ...
            }
        }
    """

    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Whether Stage 1 succeeded")
    result: ProcessVectorStage1Data = Field(
        ...,
        description="Stage 1 output data"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if success=False"
    )

    @field_validator('result', mode='before')
    @classmethod
    def validate_result_on_success(cls, v, info):
        """Ensure result is present when success=True."""
        # This runs before the model validates 'result' itself
        # info.data contains already-validated fields
        return v


class ProcessVectorStage2Result(BaseModel):
    """
    Validated structure for process_vector Stage 2 (upload) result.

    Used for aggregating upload results in finalize_job().
    """

    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Whether chunk upload succeeded")
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Upload result data"
    )
    rows_inserted: int = Field(default=0, ge=0, description="Rows inserted in this chunk")
    rows_deleted: int = Field(default=0, ge=0, description="Rows deleted (idempotency)")
    batch_id: Optional[str] = Field(default=None, description="Idempotency batch ID")
    chunk_index: Optional[int] = Field(default=None, ge=0, description="Chunk number")
    error: Optional[str] = Field(default=None, description="Error if failed")