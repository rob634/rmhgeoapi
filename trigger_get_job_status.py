# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Job status retrieval HTTP endpoint with real-time progress tracking
# SOURCE: Environment variables for repository access and logging configuration
# SCOPE: HTTP-specific job status queries with formatted response transformation
# VALIDATION: Job ID validation + repository data integrity validation
# ============================================================================

"""
Job Status HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint implementation for job status retrieval using BaseHttpTrigger pattern.
Provides detailed job information including current status, processing stage, parameters,
results, and comprehensive metadata for the Job→Stage→Task architecture.

Key Features:
- Real-time job status and progress tracking
- Stage-based progress reporting with current/total stages
- Complete job parameter and result data retrieval
- Snake_case to camelCase field transformation for JavaScript compatibility
- Enhanced metadata including architecture information
- Comprehensive error handling for missing or invalid jobs

Job Status Flow:
1. Extract and validate job_id from URL path parameter
2. Retrieve job record from repository using validated ID
3. Format internal job record for API response
4. Transform field names for frontend compatibility
5. Add enhanced metadata and architecture information
6. Return comprehensive job status response

Job Status States:
- queued: Job created and waiting for processing
- processing: Job currently being processed (may include stage info)
- completed: All stages completed successfully with results
- failed: Job failed with error details
- completed_with_errors: Partial success with some task failures

Response Data Categories:
- Basic Information: job_id, job_type, status, timestamps
- Progress Tracking: stage, total_stages, stage_results
- Input Data: parameters (original job submission parameters)
- Output Data: result_data (aggregated results from completed tasks)
- Error Information: error_details (when status is failed)
- Metadata: Architecture pattern and validation information

Integration Points:
- Uses JobManagementTrigger base class for repository access
- Reads from job storage via RepositoryFactory
- Formats JobRecord schema objects for API consumption
- Provides data for frontend dashboards and monitoring

API Endpoint:
    GET /api/jobs/{job_id}
    
Path Parameters:
    job_id: SHA256 hash of job parameters (validates format)
    
Response:
    {
        "jobId": "sha256_hash_of_parameters",
        "jobType": "operation_name",
        "status": "queued|processing|completed|failed",
        "stage": 2,                           # Current stage (1-indexed)
        "totalStages": 3,                     # Total stages in workflow
        "parameters": {...original_params},    # Job submission parameters
        "stageResults": {...},                # Results from completed stages
        "resultData": {...},                  # Final aggregated results
        "errorDetails": {...},                # Error information if failed
        "createdAt": "2025-01-30T12:34:56.789Z",
        "updatedAt": "2025-01-30T12:45:12.123Z",
        "architecture": "strong_typing_discipline",
        "pattern": "Job→Stage→Task with Pydantic validation"
    }

Error Responses:
- 400: Invalid job_id format
- 404: Job not found
- 500: Internal server error during retrieval

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