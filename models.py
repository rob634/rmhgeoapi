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
    
    def __init__(self, dataset_id: str, resource_id: str, version_id: str, operation_type: str, system: bool = False, **kwargs):
        self.dataset_id = dataset_id
        self.resource_id = resource_id
        self.version_id = version_id
        self.operation_type = operation_type
        self.system = system
        
        # Store additional parameters (like processing_extent, tile_id, etc.)
        self.additional_params = kwargs
        
        self.job_id = self._generate_job_id()
        self.created_at = datetime.now(timezone.utc).isoformat()
    
    def _generate_job_id(self) -> str:
        """Generate deterministic job ID from parameters using JSON format"""
        import json
        
        # Build params dict with all fields
        params = {
            'operation_type': self.operation_type,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'system': self.system
        }
        
        # Include additional parameters for uniqueness
        if self.additional_params:
            params.update(self.additional_params)
        
        # Generate deterministic string using JSON (sorted for consistency)
        param_string = json.dumps(params, sort_keys=True)
        return hashlib.sha256(param_string.encode()).hexdigest()
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate required fields based on system parameter and DDH awareness"""
        from schema_enforcement import DDHParameterGuide
        
        # operation_type is always required
        if not self.operation_type or not self.operation_type.strip():
            return False, f"{APIParams.OPERATION_TYPE} is required"
        
        # DDH parameters are only required for silver layer ETL operations (and not system operations)
        silver_layer_etl_jobs = DDHParameterGuide.silver_layer_etl_jobs()
        requires_ddh = self.operation_type in silver_layer_etl_jobs and not self.system
        
        if requires_ddh:
            if not self.dataset_id or not self.dataset_id.strip():
                return False, f"{APIParams.DATASET_ID} is required for silver layer ETL operations (use 'system': true to bypass)"
            if not self.resource_id or not self.resource_id.strip():
                return False, f"{APIParams.RESOURCE_ID} is required for silver layer ETL operations (use 'system': true to bypass)"
            if not self.version_id or not self.version_id.strip():
                return False, f"{APIParams.VERSION_ID} is required for silver layer ETL operations (use 'system': true to bypass)"
            
            # Basic sanitization for DDH parameters
            if any(char in self.dataset_id for char in Validation.INVALID_DATASET_CHARS):
                return False, f"{APIParams.DATASET_ID} contains invalid characters"
            if any(char in self.resource_id for char in Validation.INVALID_RESOURCE_CHARS):
                return False, f"{APIParams.RESOURCE_ID} contains invalid characters"
        
        # For system requests or non-ETL operations, parameters are optional and used flexibly
        # They may contain container names, prefixes, etc. with more relaxed validation
        
        return True, None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization"""
        result = {
            APIParams.JOB_ID: self.job_id,
            APIParams.DATASET_ID: self.dataset_id,
            APIParams.RESOURCE_ID: self.resource_id,
            APIParams.VERSION_ID: self.version_id,
            APIParams.OPERATION_TYPE: self.operation_type,
            APIParams.SYSTEM: self.system,
            APIParams.CREATED_AT: self.created_at
        }
        
        # Include additional parameters in the serialized output
        result.update(self.additional_params)
        
        return result


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