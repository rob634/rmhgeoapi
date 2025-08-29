"""
Job Status HTTP Trigger - Job Management

Concrete implementation of job status retrieval endpoint using BaseHttpTrigger.
Retrieves detailed job information including status, progress, and results.

Usage:
    GET /api/jobs/{job_id}
    
Response:
    {
        "job_id": "SHA256_hash",
        "job_type": "operation_type",
        "status": "queued" | "processing" | "completed" | "failed",
        "stage": 1,
        "total_stages": 2,
        "parameters": {...},
        "stage_results": {...},
        "result_data": {...},
        "created_at": "ISO-8601",
        "updated_at": "ISO-8601",
        "request_id": "uuid",
        "timestamp": "ISO-8601"
    }

Author: Azure Geospatial ETL Team
"""

from typing import Dict, Any, List, Optional

import azure.functions as func
from trigger_http_base import JobManagementTrigger
from schema_core import JobRecord


class JobStatusTrigger(JobManagementTrigger):
    """Job status retrieval HTTP trigger implementation."""
    
    def __init__(self):
        super().__init__("get_job_status")
    
    def get_allowed_methods(self) -> List[str]:
        """Job status only supports GET."""
        return ["GET"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job status retrieval request.
        
        Args:
            req: HTTP request with job_id in path
            
        Returns:
            Job status response data
            
        Raises:
            FileNotFoundError: If job is not found
            ValueError: If job_id is invalid
        """
        # Extract and validate job ID from path
        path_params = self.extract_path_params(req, ["job_id"])
        job_id = self.validate_job_id(path_params["job_id"])
        
        self.logger.debug(f"🔍 Retrieving job status for: {job_id}")
        
        # Retrieve job record
        job_record = self.job_repository.get_job(job_id)
        
        if not job_record:
            raise FileNotFoundError(f"Job not found: {job_id}")
        
        self.logger.debug(f"📋 Job found: {job_id[:16]}... status={job_record.status}")
        
        # Convert job record to response format
        response_data = self._format_job_response(job_record)
        
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
            "status": job_record.status,
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


# Create singleton instance for use in function_app.py
get_job_status_trigger = JobStatusTrigger()