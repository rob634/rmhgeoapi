"""
Data models for geospatial ETL pipeline
No external dependencies - pure Python classes
"""
import hashlib
from datetime import datetime
from typing import Dict, Optional, Tuple, List


class JobRequest:
    """Job submission request model"""
    
    def __init__(self, dataset_id: str, resource_id: str, version_id: str, operation_type: str):
        self.dataset_id = dataset_id
        self.resource_id = resource_id
        self.version_id = version_id
        self.operation_type = operation_type
        self.job_id = self._generate_job_id()
        self.created_at = datetime.utcnow().isoformat()
    
    def _generate_job_id(self) -> str:
        """Generate deterministic job ID from parameters"""
        content = f"{self.operation_type}:{self.dataset_id}:{self.resource_id}:{self.version_id}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate required fields"""
        if not self.dataset_id or not self.dataset_id.strip():
            return False, "dataset_id is required"
        if not self.resource_id or not self.resource_id.strip():
            return False, "resource_id is required"
        if not self.version_id or not self.version_id.strip():
            return False, "version_id is required"
        if not self.operation_type or not self.operation_type.strip():
            return False, "operation_type is required"
        
        # Basic sanitization
        if any(char in self.dataset_id for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
            return False, "dataset_id contains invalid characters"
        if any(char in self.resource_id for char in [':', '*', '?', '"', '<', '>', '|']):
            return False, "resource_id contains invalid characters"
            
        return True, None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization"""
        return {
            'job_id': self.job_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'operation_type': self.operation_type,
            'created_at': self.created_at
        }


class JobStatus:
    """Job status tracking model"""
    
    # Status constants
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    
    def __init__(self, job_id: str, status: str = PENDING):
        self.job_id = job_id
        self.status = status
        self.updated_at = datetime.utcnow().isoformat()
        self.error_message = None
        self.result_data = None
    
    def update_status(self, status: str, error_message: str = None, result_data: Dict = None):
        """Update job status with optional error or result data"""
        self.status = status
        self.updated_at = datetime.utcnow().isoformat()
        self.error_message = error_message
        self.result_data = result_data
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/API response"""
        result = {
            'job_id': self.job_id,
            'status': self.status,
            'updated_at': self.updated_at
        }
        if self.error_message:
            result['error_message'] = self.error_message
        if self.result_data:
            result['result_data'] = self.result_data
        return result