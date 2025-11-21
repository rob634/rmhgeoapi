# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Job status retrieval endpoint for Job→Stage→Task architecture
# PURPOSE: Job status retrieval HTTP trigger handling GET /api/jobs/{job_id} requests
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: JobStatusTrigger, get_job_status_trigger (singleton instance)
# INTERFACES: JobManagementTrigger (inherited from http_base)
# PYDANTIC_MODELS: JobRecord (from core.models)
# DEPENDENCIES: http_base.JobManagementTrigger, core.models.JobRecord, azure.functions
# SOURCE: HTTP GET requests with job_id path parameter, job records from PostgreSQL via JobRepository
# SCOPE: HTTP endpoint for retrieving real-time job status, progress, stage results, and final results
# VALIDATION: Job ID format validation (SHA256), job existence validation, enum value extraction
# PATTERNS: Template Method (base class), Adapter (snake_case to camelCase transformation for JavaScript)
# ENTRY_POINTS: GET /api/jobs/{job_id} - Used by function_app.py via get_job_status_trigger singleton
# INDEX: JobStatusTrigger:102, process_request:112, _format_job_response:152
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
- Enum value extraction (JobStatus.COMPLETED → "completed")

Job Status Flow:
1. Extract and validate job_id from URL path parameter (SHA256 format validation)
2. Retrieve job record from JobRepository using validated ID
3. Format internal JobRecord (snake_case) for API response
4. Transform field names to camelCase for frontend compatibility
5. Extract enum values (status.value) for JSON serialization
6. Add enhanced metadata (architecture pattern, schema validation)
7. Return comprehensive job status response

Job Status States (JobStatus enum):
- queued: Job created and waiting for CoreMachine processing
- processing: Job currently being processed (includes stage/total_stages)
- completed: All stages completed successfully with results
- failed: Job failed with error details
- completed_with_errors: Partial success with some task failures

Response Data Categories:
- Basic Information: jobId, jobType, status, timestamps
- Progress Tracking: stage (current), totalStages, stageResults
- Input Data: parameters (original job submission parameters)
- Output Data: resultData (aggregated results from completed tasks)
- Error Information: errorDetails (when status is failed)
- Metadata: architecture, pattern, schema_validated

Integration Points:
- JobManagementTrigger base class (http_base.py) - Common repository access patterns
- JobRepository (infrastructure.jobs_tasks) - Database access via job_repository property
- JobRecord (core.models) - Pydantic model with JobStatus enum
- RepositoryFactory - Lazy initialization of repositories
- Frontend dashboards and monitoring tools

API Endpoint:
    GET /api/jobs/{job_id}

Path Parameters:
    job_id: SHA256 hash of job parameters (64 hex characters)

Response (Processing):
    {
        "jobId": "sha256_hash_of_parameters",
        "jobType": "process_large_raster",
        "status": "processing",
        "stage": 2,                           # Current stage (1-indexed)
        "totalStages": 5,                     # Total stages in workflow
        "parameters": {
            "dataset_id": "bronze-rasters",
            "resource_id": "large_file.tif",
            "version_id": "v1.0"
        },
        "stageResults": {
            "stage_1": {"status": "completed", "tiles_created": 100},
            "stage_2": {"status": "processing", "tiles_processed": 45}
        },
        "createdAt": "2025-10-29T12:00:00.000Z",
        "updatedAt": "2025-10-29T12:05:30.123Z",
        "architecture": "strong_typing_discipline",
        "pattern": "Job→Stage→Task with Pydantic validation",
        "schema_validated": true
    }

Response (Completed):
    {
        "jobId": "sha256_hash_of_parameters",
        "jobType": "hello_world",
        "status": "completed",
        "stage": 2,
        "totalStages": 2,
        "parameters": {"message": "test"},
        "stageResults": {
            "stage_1": {"status": "completed", "greeting": "Hello"},
            "stage_2": {"status": "completed", "farewell": "Goodbye"}
        },
        "resultData": {
            "final_message": "Hello and Goodbye",
            "execution_time_seconds": 5.2
        },
        "createdAt": "2025-10-29T12:00:00.000Z",
        "updatedAt": "2025-10-29T12:05:05.200Z",
        "architecture": "strong_typing_discipline",
        "pattern": "Job→Stage→Task with Pydantic validation",
        "schema_validated": true
    }

Response (Failed):
    {
        "jobId": "sha256_hash_of_parameters",
        "jobType": "ingest_vector",
        "status": "failed",
        "stage": 1,
        "totalStages": 2,
        "parameters": {...},
        "errorDetails": {
            "error": "PostGIS connection failed",
            "error_type": "DatabaseError",
            "stage": 1,
            "task_id": "task_xyz",
            "timestamp": "2025-10-29T12:01:00.000Z"
        },
        "createdAt": "2025-10-29T12:00:00.000Z",
        "updatedAt": "2025-10-29T12:01:00.500Z",
        "architecture": "strong_typing_discipline",
        "pattern": "Job→Stage→Task with Pydantic validation",
        "schema_validated": true
    }

Error Responses:
- 400 Bad Request: Invalid job_id format (not SHA256 hex)
- 404 Not Found: Job does not exist in database
- 500 Internal Server Error: Database error or unexpected failure

Field Name Transformation:
- Internal (Python): snake_case (job_id, created_at, stage_results)
- API (JavaScript): camelCase (jobId, createdAt, stageResults)
- Preserves Python conventions internally while supporting frontend standards

Last Updated: 29 OCT 2025
"""

from typing import Dict, Any, List, Optional

import azure.functions as func
from .http_base import JobManagementTrigger
from core.models import JobRecord


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


# Create singleton instance for use in function_app.py
get_job_status_trigger = JobStatusTrigger()