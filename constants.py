"""
API Constants for Geospatial ETL Pipeline
Centralizes parameter names and other constants for easy modification
"""

# API Parameter Names - Change these to update across entire application
class APIParams:
    """HTTP API parameter names"""
    DATASET_ID = "dataset_id"
    RESOURCE_ID = "resource_id"
    VERSION_ID = "version_id"
    OPERATION_TYPE = "operation_type"
    SYSTEM = "system"
    
    # Job tracking parameters
    JOB_ID = "job_id"
    STATUS = "status"
    MESSAGE = "message"
    IS_DUPLICATE = "is_duplicate"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    ERROR_MESSAGE = "error_message"
    RESULT_DATA = "result_data"

# Operation Types
class Operations:
    """Supported operation types"""
    HELLO_WORLD = "hello_world"
    LIST_CONTAINER = "list_container"
    COG_CONVERSION = "cog_conversion"
    VECTOR_UPLOAD = "vector_upload"
    STAC_GENERATION = "stac_generation"

# Job Status Values
class JobStatuses:
    """Job status constants"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# Default Values
class Defaults:
    """Default parameter values"""
    SYSTEM_FLAG = False
    NO_FILTER = "none"
    DEFAULT_VERSION = "v1.0.0"
    
# Validation Constants
class Validation:
    """Validation rules and patterns"""
    INVALID_DATASET_CHARS = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    INVALID_RESOURCE_CHARS = [':', '*', '?', '"', '<', '>', '|']
    
# Azure Configuration
class Azure:
    """Azure-specific constants"""
    QUEUE_NAME = "job-processing"
    FUNCTIONS_KEY_HEADER = "x-functions-key"
    STORAGE_CONNECTION = "AzureWebJobsStorage"