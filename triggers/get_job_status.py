"""
Job Status HTTP Trigger.

HTTP endpoint for GET /api/jobs/status/{job_id} requests.

Key Features:
    - Real-time job status and progress tracking
    - Stage-based progress reporting
    - Complete job parameter and result data
    - Task summary with counts by status and stage (09 DEC 2025)

Query Parameters:
    - verbose=true: Include full task details in response

Exports:
    JobStatusTrigger: Job status trigger class
    get_job_status_trigger: Singleton trigger instance
"""

from typing import Dict, Any, List, Optional

import azure.functions as func
from .http_base import JobManagementTrigger
from core.models import JobRecord
from infrastructure import TaskRepository


class JobStatusTrigger(JobManagementTrigger):
    """Job status retrieval HTTP trigger implementation."""

    def __init__(self):
        super().__init__("get_job_status")
        self.task_repository = TaskRepository()

    def get_allowed_methods(self) -> List[str]:
        """Job status only supports GET."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job status retrieval request.

        Args:
            req: HTTP request with job_id in path
            Query params:
                - verbose=true: Include full task details

        Returns:
            Job status response data with task summary

        Raises:
            FileNotFoundError: If job is not found
            ValueError: If job_id is invalid
        """
        # Extract and validate job ID from path
        path_params = self.extract_path_params(req, ["job_id"])
        job_id = self.validate_job_id(path_params["job_id"])
        verbose = req.params.get('verbose', 'false').lower() == 'true'

        self.logger.debug(f"🔍 Retrieving job status for: {job_id}")

        # Retrieve job record
        job_record = self.job_repository.get_job(job_id)

        if not job_record:
            raise FileNotFoundError(f"Job not found: {job_id}")

        self.logger.debug(f"📋 Job found: {job_id[:16]}... status={job_record.status}")

        # Convert job record to response format
        response_data = self._format_job_response(job_record)

        # Add task summary (09 DEC 2025)
        task_summary = self._get_task_summary(job_id, verbose=verbose)
        response_data["taskSummary"] = task_summary

        # Add enhanced metadata
        response_data.update({
            "architecture": "strong_typing_discipline",
            "pattern": "Job→Stage→Task with Pydantic validation",
            "schema_validated": True
        })

        return response_data
    
    def _format_job_response(self, job_record: JobRecord) -> Dict[str, Any]:
        """
        Format job record for API response.
        
        Converts internal snake_case fields to camelCase for JavaScript compatibility
        while preserving internal Python conventions.
        
        Args:
            job_record: Internal job record with snake_case fields
            
        Returns:
            API response dictionary with camelCase fields
        """
        # Basic job information (camelCase for API compatibility)
        response = {
            "jobId": job_record.job_id,
            "jobType": job_record.job_type,
            "status": job_record.status.value if hasattr(job_record.status, 'value') else str(job_record.status),  # FIX: Extract enum value
            "stage": job_record.stage,
            "totalStages": job_record.total_stages,
            "parameters": job_record.parameters,
            "stageResults": job_record.stage_results,
            "createdAt": job_record.created_at.isoformat() if job_record.created_at else None,
            "updatedAt": job_record.updated_at.isoformat() if job_record.updated_at else None
        }
        
        # Optional fields
        if job_record.result_data:
            response["resultData"] = job_record.result_data
        
        if job_record.error_details:
            response["errorDetails"] = job_record.error_details

        return response

    def _get_task_summary(self, job_id: str, verbose: bool = False) -> Dict[str, Any]:
        """
        Get task summary for a job (09 DEC 2025).

        Args:
            job_id: Job identifier
            verbose: If True, include full task details

        Returns:
            Dictionary with task counts and optional task details:
            {
                "total": 6,
                "completed": 6,
                "failed": 0,
                "processing": 0,
                "pending": 0,
                "queued": 0,
                "byStage": {
                    "1": {"total": 3, "completed": 3, "taskTypes": ["hello_world_greeting"]},
                    "2": {"total": 3, "completed": 3, "taskTypes": ["hello_world_reply"]}
                },
                "tasks": [...]  # Only if verbose=True
            }
        """
        try:
            tasks = self.task_repository.get_tasks_for_job(job_id)

            if not tasks:
                return {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "processing": 0,
                    "pending": 0,
                    "queued": 0,
                    "byStage": {}
                }

            # Count by status
            status_counts = {
                "total": len(tasks),
                "completed": 0,
                "failed": 0,
                "processing": 0,
                "pending": 0,
                "queued": 0
            }

            # Group by stage
            by_stage = {}

            for task in tasks:
                # Get status string
                status = task.status.value if hasattr(task.status, 'value') else str(task.status)

                # Update overall counts
                if status == "completed":
                    status_counts["completed"] += 1
                elif status == "failed":
                    status_counts["failed"] += 1
                elif status == "processing":
                    status_counts["processing"] += 1
                elif status == "pending":
                    status_counts["pending"] += 1
                elif status == "queued":
                    status_counts["queued"] += 1

                # Update stage counts
                stage_key = str(task.stage)
                if stage_key not in by_stage:
                    by_stage[stage_key] = {
                        "total": 0,
                        "completed": 0,
                        "failed": 0,
                        "processing": 0,
                        "pending": 0,
                        "queued": 0,
                        "taskTypes": set()
                    }

                by_stage[stage_key]["total"] += 1
                by_stage[stage_key]["taskTypes"].add(task.task_type)

                if status == "completed":
                    by_stage[stage_key]["completed"] += 1
                elif status == "failed":
                    by_stage[stage_key]["failed"] += 1
                elif status == "processing":
                    by_stage[stage_key]["processing"] += 1
                elif status == "pending":
                    by_stage[stage_key]["pending"] += 1
                elif status == "queued":
                    by_stage[stage_key]["queued"] += 1

            # Convert taskTypes sets to lists and remove zero counts
            for stage_key in by_stage:
                by_stage[stage_key]["taskTypes"] = list(by_stage[stage_key]["taskTypes"])
                # Remove zero counts for cleaner output
                by_stage[stage_key] = {
                    k: v for k, v in by_stage[stage_key].items()
                    if v != 0 or k in ["total", "taskTypes"]
                }

            result = {
                **status_counts,
                "byStage": by_stage
            }

            # Add verbose task details if requested
            if verbose:
                result["tasks"] = [
                    {
                        "taskId": task.task_id,
                        "taskType": task.task_type,
                        "stage": task.stage,
                        "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                        "createdAt": task.created_at.isoformat() if task.created_at else None,
                        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
                        "error": task.result_data.get("error") if task.result_data else None
                    }
                    for task in tasks
                ]

            return result

        except Exception as e:
            self.logger.warning(f"Failed to get task summary for job {job_id}: {e}")
            return {
                "error": str(e),
                "total": 0
            }


# Create singleton instance for use in function_app.py
get_job_status_trigger = JobStatusTrigger()