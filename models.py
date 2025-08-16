"""
Data models for geospatial ETL pipeline
No external dependencies - pure Python classes
"""
import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List
from config import APIParams, JobStatuses, Validation


class JobRequest:
    """Job submission request model"""
    
    def __init__(self, dataset_id: str, resource_id: str, version_id: str, operation_type: str, system: bool = False):
        self.dataset_id = dataset_id
        self.resource_id = resource_id
        self.version_id = version_id
        self.operation_type = operation_type
        self.system = system
        self.job_id = self._generate_job_id()
        self.created_at = datetime.now(timezone.utc).isoformat()
    
    def _generate_job_id(self) -> str:
        """Generate deterministic job ID from parameters"""
        content = f"{self.operation_type}:{self.dataset_id}:{self.resource_id}:{self.version_id}:{self.system}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate required fields based on system parameter"""
        # operation_type is always required
        if not self.operation_type or not self.operation_type.strip():
            return False, f"{APIParams.OPERATION_TYPE} is required"
        
        # For DDH application requests (system=False), all ETL parameters are mandatory
        if not self.system:
            if not self.dataset_id or not self.dataset_id.strip():
                return False, f"{APIParams.DATASET_ID} is required for DDH operations"
            if not self.resource_id or not self.resource_id.strip():
                return False, f"{APIParams.RESOURCE_ID} is required for DDH operations"
            if not self.version_id or not self.version_id.strip():
                return False, f"{APIParams.VERSION_ID} is required for DDH operations"
            
            # Basic sanitization for DDH parameters
            if any(char in self.dataset_id for char in Validation.INVALID_DATASET_CHARS):
                return False, f"{APIParams.DATASET_ID} contains invalid characters"
            if any(char in self.resource_id for char in Validation.INVALID_RESOURCE_CHARS):
                return False, f"{APIParams.RESOURCE_ID} contains invalid characters"
        
        # For system requests (system=True), parameters are optional and used differently
        # They may contain container names, prefixes, etc. with more relaxed validation
        
        return True, None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization"""
        return {
            APIParams.JOB_ID: self.job_id,
            APIParams.DATASET_ID: self.dataset_id,
            APIParams.RESOURCE_ID: self.resource_id,
            APIParams.VERSION_ID: self.version_id,
            APIParams.OPERATION_TYPE: self.operation_type,
            APIParams.SYSTEM: self.system,
            APIParams.CREATED_AT: self.created_at
        }


class JobStatus:
    """Job status tracking model"""
    
    # Status constants (using centralized constants)
    PENDING = JobStatuses.PENDING
    QUEUED = JobStatuses.QUEUED
    PROCESSING = JobStatuses.PROCESSING
    COMPLETED = JobStatuses.COMPLETED
    FAILED = JobStatuses.FAILED
    
    def __init__(self, job_id: str, status: str = PENDING):
        self.job_id = job_id
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.error_message = None
        self.result_data = None
    
    def update_status(self, status: str, error_message: str = None, result_data: Dict = None):
        """Update job status with optional error or result data"""
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.error_message = error_message
        self.result_data = result_data
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/API response"""
        result = {
            APIParams.JOB_ID: self.job_id,
            APIParams.STATUS: self.status,
            APIParams.UPDATED_AT: self.updated_at
        }
        if self.error_message:
            result[APIParams.ERROR_MESSAGE] = self.error_message
        if self.result_data:
            result[APIParams.RESULT_DATA] = self.result_data
        return result