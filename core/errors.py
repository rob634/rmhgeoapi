# ============================================================================
# ERROR CODE DEFINITIONS AND CLASSIFICATION
# ============================================================================
# STATUS: Core - Standardized error codes and retry logic
# PURPOSE: Centralized error management with HTTP status and retry classification
# LAST_REVIEWED: 06 FEB 2026
# REVIEW_STATUS: Phase 1+2 Complete (BUG_REFORM - Pydantic models)
# ============================================================================
"""
Error Code Definitions and Classification.

Centralized error code management with retry logic and consistent
error responses across all endpoints.

Key Features:
    - Explicit error codes for all failure modes (~45 codes)
    - Retry classification (PERMANENT, TRANSIENT, THROTTLING)
    - Error category (who's responsible for fixing)
    - Error scope (NODE vs WORKFLOW for DAG v0.9)
    - HTTP status code mapping (400, 404, 500, 503)
    - Pydantic models for type-safe error responses

Error Categories (Blame Assignment):
    - DATA_MISSING: User's file not found
    - DATA_QUALITY: User's file content is bad
    - DATA_INCOMPATIBLE: User's collection files don't match
    - PARAMETER_ERROR: User's request parameters are wrong
    - SYSTEM_ERROR: Our problem
    - SERVICE_UNAVAILABLE: Temporary, retry later
    - CONFIGURATION: Ops team problem

Error Scopes (DAG v0.9 Ready):
    - NODE: Error in single processing step
    - WORKFLOW: Error in orchestration/relationships

Exports:
    ErrorCode: Standardized error codes enum (~45 codes)
    ErrorClassification: Retry logic enum (PERMANENT, TRANSIENT, THROTTLING)
    ErrorCategory: Blame assignment enum (who fixes it)
    ErrorScope: DAG scope enum (NODE, WORKFLOW)
    ErrorResponse: Pydantic model for B2B error responses
    ErrorDebug: Pydantic model for debug info (stored in job record)
    ExceptionInfo: Pydantic model for exception details
    is_retryable(): Check if error should be retried
    get_error_classification(): Get classification for error code
    get_error_category(): Get category for error code (blame)
    get_error_scope(): Get DAG scope for error code
    get_http_status_code(): Get HTTP status for error code
    create_error_response(): Create ErrorResponse model
    create_error_response_v2(): Create (ErrorResponse, ErrorDebug) tuple
"""

from enum import Enum
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
import traceback as tb_module
import uuid

from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ============================================================================
# ENUMERATIONS
# ============================================================================

class ErrorCode(str, Enum):
    """
    Standardized error codes for all application errors.

    These codes are returned in task results and API responses to provide
    explicit error classification for logging, monitoring, and retry logic.

    Organized by:
    - SHARED: Apply to multiple workflows
    - RASTER_*: Raster-specific errors
    - VECTOR_*: Vector-specific errors
    - COLLECTION_*: Collection relationship errors (WORKFLOW scope)
    - Infrastructure errors
    """

    # ========================================================================
    # SHARED ERRORS - Apply to multiple workflows
    # ========================================================================

    # Resource not found errors (HTTP 404, NOT RETRYABLE)
    CONTAINER_NOT_FOUND = "CONTAINER_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    # File/data errors (HTTP 400)
    FILE_UNREADABLE = "FILE_UNREADABLE"
    CRS_MISSING = "CRS_MISSING"
    CRS_MISMATCH = "CRS_MISMATCH"  # Phase 2: File CRS != user CRS
    INVALID_FORMAT = "INVALID_FORMAT"
    CORRUPTED_FILE = "CORRUPTED_FILE"

    # Parameter validation errors (HTTP 400, NOT RETRYABLE)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    MISSING_PARAMETER = "MISSING_PARAMETER"

    # ========================================================================
    # RASTER-SPECIFIC ERRORS (Phase 2 - 06 FEB 2026)
    # ========================================================================

    RASTER_UNREADABLE = "RASTER_UNREADABLE"  # GDAL can't open
    RASTER_64BIT_REJECTED = "RASTER_64BIT_REJECTED"  # Policy: no float64/int64
    RASTER_EMPTY = "RASTER_EMPTY"  # 99%+ nodata pixels
    RASTER_NODATA_CONFLICT = "RASTER_NODATA_CONFLICT"  # Nodata value in real data
    RASTER_EXTREME_VALUES = "RASTER_EXTREME_VALUES"  # DEM with 1e38 values
    RASTER_BAND_INVALID = "RASTER_BAND_INVALID"  # 0 bands or >100 bands
    RASTER_TYPE_MISMATCH = "RASTER_TYPE_MISMATCH"  # User said RGB, detected DEM

    # ========================================================================
    # VECTOR-SPECIFIC ERRORS (Phase 2 - 06 FEB 2026)
    # ========================================================================

    VECTOR_UNREADABLE = "VECTOR_UNREADABLE"  # Can't parse file
    VECTOR_NO_FEATURES = "VECTOR_NO_FEATURES"  # Empty after filtering
    VECTOR_GEOMETRY_INVALID = "VECTOR_GEOMETRY_INVALID"  # Bad geometry
    VECTOR_GEOMETRY_EMPTY = "VECTOR_GEOMETRY_EMPTY"  # All null geometries
    VECTOR_COORDINATE_ERROR = "VECTOR_COORDINATE_ERROR"  # Can't parse lat/lon
    VECTOR_ENCODING_ERROR = "VECTOR_ENCODING_ERROR"  # Character encoding issue
    VECTOR_ATTRIBUTE_ERROR = "VECTOR_ATTRIBUTE_ERROR"  # Column type issue
    VECTOR_TABLE_NAME_INVALID = "VECTOR_TABLE_NAME_INVALID"  # Bad table name
    VECTOR_FORMAT_MISMATCH = "VECTOR_FORMAT_MISMATCH"  # Content doesn't match declared format
    VECTOR_MIXED_GEOMETRY = "VECTOR_MIXED_GEOMETRY"  # Multiple incompatible geometry types
    TABLE_EXISTS = "TABLE_EXISTS"  # Table already exists (overwrite=false)

    # ========================================================================
    # COLLECTION-SPECIFIC ERRORS (Phase 2 - 06 FEB 2026)
    # These are WORKFLOW scope - valid files, incompatible together
    # ========================================================================

    COLLECTION_BAND_MISMATCH = "COLLECTION_BAND_MISMATCH"
    COLLECTION_DTYPE_MISMATCH = "COLLECTION_DTYPE_MISMATCH"
    COLLECTION_CRS_MISMATCH = "COLLECTION_CRS_MISMATCH"
    COLLECTION_RESOLUTION_MISMATCH = "COLLECTION_RESOLUTION_MISMATCH"
    COLLECTION_TYPE_MISMATCH = "COLLECTION_TYPE_MISMATCH"  # RGB + DEM mixed
    COLLECTION_BOUNDS_DISJOINT = "COLLECTION_BOUNDS_DISJOINT"  # No spatial relationship

    # ========================================================================
    # PROCESSING ERRORS - SERVICE ERRORS (HTTP 500/503)
    # ========================================================================

    # Setup/configuration errors (HTTP 500, NOT RETRYABLE)
    SETUP_FAILED = "SETUP_FAILED"
    CONFIG_ERROR = "CONFIG_ERROR"

    # CRS/projection errors (HTTP 400, NOT RETRYABLE)
    CRS_CHECK_FAILED = "CRS_CHECK_FAILED"
    REPROJECTION_FAILED = "REPROJECTION_FAILED"

    # Processing errors (HTTP 500, RETRYABLE)
    COG_TRANSLATE_FAILED = "COG_TRANSLATE_FAILED"
    COG_CREATION_FAILED = "COG_CREATION_FAILED"
    PROCESSING_FAILED = "PROCESSING_FAILED"

    # ========================================================================
    # INFRASTRUCTURE ERRORS (HTTP 500/503, RETRYABLE)
    # ========================================================================

    # Database errors
    DATABASE_ERROR = "DATABASE_ERROR"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"
    DATABASE_CONNECTION_FAILED = "DATABASE_CONNECTION_FAILED"

    # Storage errors
    STORAGE_ERROR = "STORAGE_ERROR"
    STORAGE_TIMEOUT = "STORAGE_TIMEOUT"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"

    # Service Bus / Queue errors
    QUEUE_ERROR = "QUEUE_ERROR"
    MESSAGE_ERROR = "MESSAGE_ERROR"

    # Resource exhaustion
    MEMORY_ERROR = "MEMORY_ERROR"
    DISK_FULL = "DISK_FULL"
    TIMEOUT = "TIMEOUT"
    THROTTLED = "THROTTLED"

    # ========================================================================
    # GENERIC ERRORS
    # ========================================================================

    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class ErrorClassification(str, Enum):
    """Error classification for retry logic."""

    PERMANENT = "PERMANENT"  # Never retry (client error, won't fix itself)
    TRANSIENT = "TRANSIENT"  # Retry with exponential backoff (temporary issue)
    THROTTLING = "THROTTLING"  # Retry with longer delay (rate limiting)


class ErrorCategory(str, Enum):
    """
    Error category for blame assignment (06 FEB 2026 - BUG_REFORM).

    B2B API consumers use this to determine:
    - Should they fix their input and retry?
    - Should they contact support?
    - Should they just retry later?
    """

    # USER'S PROBLEM - They need to fix their input
    DATA_MISSING = "DATA_MISSING"
    DATA_QUALITY = "DATA_QUALITY"
    DATA_INCOMPATIBLE = "DATA_INCOMPATIBLE"
    PARAMETER_ERROR = "PARAMETER_ERROR"

    # OUR PROBLEM - We need to fix or they should retry
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # CONFIGURATION - Ops team problem
    CONFIGURATION = "CONFIGURATION"


class ErrorScope(str, Enum):
    """
    Error scope for DAG classification (06 FEB 2026 - BUG_REFORM, v0.9 Ready).

    Used for:
    - Retry strategy (node errors can retry single step)
    - Error aggregation (workflow errors affect entire job)
    - Future DAG visualization (highlight failed node vs failed edge)
    """

    NODE = "node"  # Error in single processing step (bad input data)
    WORKFLOW = "workflow"  # Error in orchestration (nodes don't fit together)


# ============================================================================
# PYDANTIC MODELS (Phase 1 Revision - 06 FEB 2026)
# ============================================================================

class ExceptionInfo(BaseModel):
    """Exception details for debug storage."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="Exception class name")
    message: str = Field(..., description="Exception message")
    file: Optional[str] = Field(None, description="Source file where error occurred")
    line: Optional[int] = Field(None, description="Line number")
    function: Optional[str] = Field(None, description="Function name")


class ErrorDebug(BaseModel):
    """
    Debug information for error storage (06 FEB 2026 - BUG_REFORM).

    Always stored in job record error_details for support tickets.
    Only included in B2B response when debug mode is enabled.
    """

    model_config = ConfigDict(
        extra="allow",  # Forward compatibility for new fields
    )

    @field_serializer('timestamp')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Identity
    error_id: str = Field(..., description="Unique error ID for support tickets")
    timestamp: datetime = Field(..., description="When the error occurred")

    # Classification
    error_code: str = Field(..., description="ErrorCode value")
    error_category: str = Field(..., description="ErrorCategory value")
    error_scope: str = Field(..., description="ErrorScope value (node/workflow)")

    # Message
    message: str = Field(..., description="User-friendly error message")
    remediation: str = Field(..., description="How to fix this error")

    # Execution context (optional)
    job_id: Optional[str] = Field(None, description="Parent job ID")
    task_id: Optional[str] = Field(None, description="Task ID if applicable")
    stage: Optional[int] = Field(None, description="Pipeline stage number")
    handler: Optional[str] = Field(None, description="Handler function name")

    # Error details
    details: Optional[Dict[str, Any]] = Field(None, description="Structured error details")
    exception: Optional[ExceptionInfo] = Field(None, description="Exception info")
    traceback: Optional[str] = Field(None, description="Full Python traceback")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")


class ErrorResponse(BaseModel):
    """
    Standardized error response for B2B API (06 FEB 2026 - BUG_REFORM).

    Matches the pattern of TaskResult, StageResultContract for consistency.
    Used for all error responses to external callers.
    """

    model_config = ConfigDict(
        use_enum_values=True,
        extra="forbid",  # Strict schema for API responses
    )

    # Status
    success: bool = Field(default=False, description="Always False for errors")

    # Classification (machine-readable)
    error_code: str = Field(..., description="Specific error code")
    error_category: ErrorCategory = Field(..., description="Who's responsible")
    error_scope: ErrorScope = Field(..., description="DAG scope (node/workflow)")

    # Retry guidance
    retryable: bool = Field(..., description="Whether automatic retry might succeed")
    user_fixable: bool = Field(..., description="Whether user can fix by correcting input")
    http_status: int = Field(..., description="HTTP status code")

    # Human-readable
    message: str = Field(..., description="User-friendly error description")
    remediation: Optional[str] = Field(None, description="How to fix this error")

    # Details
    details: Optional[Dict[str, Any]] = Field(None, description="Structured error context")

    # Support reference (always included)
    error_id: str = Field(..., description="Unique error ID for support tickets")

    # Debug section (conditional - only in debug mode)
    debug: Optional[ErrorDebug] = Field(None, description="Debug info (only in debug mode)")


# ============================================================================
# MAPPINGS
# ============================================================================

# Error code to classification mapping
_ERROR_CLASSIFICATION: Dict[ErrorCode, ErrorClassification] = {
    # PERMANENT - Never retry (client errors, user must fix)
    ErrorCode.CONTAINER_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.FILE_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.CRS_MISSING: ErrorClassification.PERMANENT,
    ErrorCode.CRS_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.VALIDATION_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.INVALID_PARAMETER: ErrorClassification.PERMANENT,
    ErrorCode.MISSING_PARAMETER: ErrorClassification.PERMANENT,
    ErrorCode.SETUP_FAILED: ErrorClassification.PERMANENT,
    ErrorCode.CONFIG_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.CRS_CHECK_FAILED: ErrorClassification.PERMANENT,
    ErrorCode.INVALID_FORMAT: ErrorClassification.PERMANENT,

    # Raster-specific (PERMANENT - user must fix data)
    ErrorCode.RASTER_UNREADABLE: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_64BIT_REJECTED: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_EMPTY: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_NODATA_CONFLICT: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_EXTREME_VALUES: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_BAND_INVALID: ErrorClassification.PERMANENT,
    ErrorCode.RASTER_TYPE_MISMATCH: ErrorClassification.PERMANENT,

    # Vector-specific (PERMANENT - user must fix data)
    ErrorCode.VECTOR_UNREADABLE: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_NO_FEATURES: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_GEOMETRY_INVALID: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_GEOMETRY_EMPTY: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_COORDINATE_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_ENCODING_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_ATTRIBUTE_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_TABLE_NAME_INVALID: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorClassification.PERMANENT,
    ErrorCode.TABLE_EXISTS: ErrorClassification.PERMANENT,

    # Collection-specific (PERMANENT - user must fix collection)
    ErrorCode.COLLECTION_BAND_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.COLLECTION_DTYPE_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.COLLECTION_CRS_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.COLLECTION_RESOLUTION_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.COLLECTION_TYPE_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.COLLECTION_BOUNDS_DISJOINT: ErrorClassification.PERMANENT,

    # TRANSIENT - Retry with exponential backoff (temporary issues)
    ErrorCode.FILE_UNREADABLE: ErrorClassification.TRANSIENT,
    ErrorCode.CORRUPTED_FILE: ErrorClassification.TRANSIENT,
    ErrorCode.REPROJECTION_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.COG_TRANSLATE_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.COG_CREATION_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.PROCESSING_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.DATABASE_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.DATABASE_TIMEOUT: ErrorClassification.TRANSIENT,
    ErrorCode.DATABASE_CONNECTION_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.STORAGE_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.STORAGE_TIMEOUT: ErrorClassification.TRANSIENT,
    ErrorCode.UPLOAD_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.DOWNLOAD_FAILED: ErrorClassification.TRANSIENT,
    ErrorCode.QUEUE_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.MESSAGE_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.TIMEOUT: ErrorClassification.TRANSIENT,

    # THROTTLING - Retry with longer delay (rate limiting)
    ErrorCode.MEMORY_ERROR: ErrorClassification.THROTTLING,
    ErrorCode.DISK_FULL: ErrorClassification.THROTTLING,
    ErrorCode.THROTTLED: ErrorClassification.THROTTLING,

    # UNKNOWN - Default to transient
    ErrorCode.UNKNOWN_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.UNEXPECTED_ERROR: ErrorClassification.TRANSIENT,
}


# Error code to category mapping (blame assignment)
_ERROR_CATEGORY: Dict[ErrorCode, ErrorCategory] = {
    # DATA_MISSING - User's file not found
    ErrorCode.CONTAINER_NOT_FOUND: ErrorCategory.DATA_MISSING,
    ErrorCode.FILE_NOT_FOUND: ErrorCategory.DATA_MISSING,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorCategory.DATA_MISSING,

    # DATA_QUALITY - User's file content is bad
    ErrorCode.FILE_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.CORRUPTED_FILE: ErrorCategory.DATA_QUALITY,
    ErrorCode.INVALID_FORMAT: ErrorCategory.DATA_QUALITY,
    ErrorCode.CRS_MISSING: ErrorCategory.DATA_QUALITY,
    ErrorCode.CRS_MISMATCH: ErrorCategory.DATA_QUALITY,
    ErrorCode.CRS_CHECK_FAILED: ErrorCategory.DATA_QUALITY,

    # Raster-specific DATA_QUALITY
    ErrorCode.RASTER_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_64BIT_REJECTED: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_EMPTY: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_NODATA_CONFLICT: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_EXTREME_VALUES: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_BAND_INVALID: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_TYPE_MISMATCH: ErrorCategory.DATA_QUALITY,

    # Vector-specific DATA_QUALITY
    ErrorCode.VECTOR_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_NO_FEATURES: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_GEOMETRY_INVALID: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_GEOMETRY_EMPTY: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_COORDINATE_ERROR: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_ENCODING_ERROR: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_ATTRIBUTE_ERROR: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorCategory.DATA_QUALITY,

    # DATA_INCOMPATIBLE - Collection files don't match (WORKFLOW errors)
    ErrorCode.COLLECTION_BAND_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_DTYPE_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_CRS_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_RESOLUTION_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_TYPE_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_BOUNDS_DISJOINT: ErrorCategory.DATA_INCOMPATIBLE,

    # PARAMETER_ERROR - User's request is wrong
    ErrorCode.VALIDATION_ERROR: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.INVALID_PARAMETER: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.MISSING_PARAMETER: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.VECTOR_TABLE_NAME_INVALID: ErrorCategory.PARAMETER_ERROR,

    # SYSTEM_ERROR - Our problem
    ErrorCode.REPROJECTION_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.COG_TRANSLATE_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.COG_CREATION_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.PROCESSING_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DATABASE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DATABASE_CONNECTION_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.STORAGE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.UPLOAD_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DOWNLOAD_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.QUEUE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.MESSAGE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.MEMORY_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DISK_FULL: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.UNKNOWN_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.UNEXPECTED_ERROR: ErrorCategory.SYSTEM_ERROR,

    # SERVICE_UNAVAILABLE - Temporary, retry later
    ErrorCode.DATABASE_TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.STORAGE_TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.THROTTLED: ErrorCategory.SERVICE_UNAVAILABLE,

    # CONFIGURATION - Ops team problem
    ErrorCode.SETUP_FAILED: ErrorCategory.CONFIGURATION,
    ErrorCode.CONFIG_ERROR: ErrorCategory.CONFIGURATION,
}


# Error code to scope mapping (DAG v0.9)
_ERROR_SCOPE: Dict[ErrorCode, ErrorScope] = {
    # NODE errors - Single input/step failures
    ErrorCode.CONTAINER_NOT_FOUND: ErrorScope.NODE,
    ErrorCode.FILE_NOT_FOUND: ErrorScope.NODE,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorScope.NODE,
    ErrorCode.FILE_UNREADABLE: ErrorScope.NODE,
    ErrorCode.CORRUPTED_FILE: ErrorScope.NODE,
    ErrorCode.INVALID_FORMAT: ErrorScope.NODE,
    ErrorCode.CRS_MISSING: ErrorScope.NODE,
    ErrorCode.CRS_MISMATCH: ErrorScope.NODE,
    ErrorCode.CRS_CHECK_FAILED: ErrorScope.NODE,
    ErrorCode.VALIDATION_ERROR: ErrorScope.NODE,
    ErrorCode.INVALID_PARAMETER: ErrorScope.NODE,
    ErrorCode.MISSING_PARAMETER: ErrorScope.NODE,
    ErrorCode.SETUP_FAILED: ErrorScope.NODE,
    ErrorCode.CONFIG_ERROR: ErrorScope.NODE,
    ErrorCode.REPROJECTION_FAILED: ErrorScope.NODE,
    ErrorCode.COG_TRANSLATE_FAILED: ErrorScope.NODE,
    ErrorCode.COG_CREATION_FAILED: ErrorScope.NODE,
    ErrorCode.PROCESSING_FAILED: ErrorScope.NODE,
    ErrorCode.DATABASE_ERROR: ErrorScope.NODE,
    ErrorCode.DATABASE_TIMEOUT: ErrorScope.NODE,
    ErrorCode.DATABASE_CONNECTION_FAILED: ErrorScope.NODE,
    ErrorCode.STORAGE_ERROR: ErrorScope.NODE,
    ErrorCode.STORAGE_TIMEOUT: ErrorScope.NODE,
    ErrorCode.UPLOAD_FAILED: ErrorScope.NODE,
    ErrorCode.DOWNLOAD_FAILED: ErrorScope.NODE,
    ErrorCode.QUEUE_ERROR: ErrorScope.NODE,
    ErrorCode.MESSAGE_ERROR: ErrorScope.NODE,
    ErrorCode.MEMORY_ERROR: ErrorScope.NODE,
    ErrorCode.DISK_FULL: ErrorScope.NODE,
    ErrorCode.TIMEOUT: ErrorScope.NODE,
    ErrorCode.THROTTLED: ErrorScope.NODE,
    ErrorCode.UNKNOWN_ERROR: ErrorScope.NODE,
    ErrorCode.UNEXPECTED_ERROR: ErrorScope.NODE,

    # Raster-specific NODE errors
    ErrorCode.RASTER_UNREADABLE: ErrorScope.NODE,
    ErrorCode.RASTER_64BIT_REJECTED: ErrorScope.NODE,
    ErrorCode.RASTER_EMPTY: ErrorScope.NODE,
    ErrorCode.RASTER_NODATA_CONFLICT: ErrorScope.NODE,
    ErrorCode.RASTER_EXTREME_VALUES: ErrorScope.NODE,
    ErrorCode.RASTER_BAND_INVALID: ErrorScope.NODE,
    ErrorCode.RASTER_TYPE_MISMATCH: ErrorScope.NODE,

    # Vector-specific NODE errors
    ErrorCode.VECTOR_UNREADABLE: ErrorScope.NODE,
    ErrorCode.VECTOR_NO_FEATURES: ErrorScope.NODE,
    ErrorCode.VECTOR_GEOMETRY_INVALID: ErrorScope.NODE,
    ErrorCode.VECTOR_GEOMETRY_EMPTY: ErrorScope.NODE,
    ErrorCode.VECTOR_COORDINATE_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_ENCODING_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_ATTRIBUTE_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_TABLE_NAME_INVALID: ErrorScope.NODE,
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorScope.NODE,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorScope.NODE,

    # WORKFLOW errors - Collection relationship failures
    ErrorCode.COLLECTION_BAND_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_DTYPE_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_CRS_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_RESOLUTION_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_TYPE_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_BOUNDS_DISJOINT: ErrorScope.WORKFLOW,
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_retryable(error_code: ErrorCode) -> bool:
    """Check if error should trigger a retry."""
    classification = _ERROR_CLASSIFICATION.get(error_code, ErrorClassification.TRANSIENT)
    return classification != ErrorClassification.PERMANENT


def get_error_classification(error_code: ErrorCode) -> ErrorClassification:
    """Get retry classification for error code."""
    return _ERROR_CLASSIFICATION.get(error_code, ErrorClassification.TRANSIENT)


def get_error_category(error_code: ErrorCode) -> ErrorCategory:
    """Get blame assignment category for error code."""
    return _ERROR_CATEGORY.get(error_code, ErrorCategory.SYSTEM_ERROR)


def get_error_scope(error_code: ErrorCode) -> ErrorScope:
    """Get DAG scope for error code (v0.9 ready)."""
    return _ERROR_SCOPE.get(error_code, ErrorScope.NODE)


def is_user_fixable(error_code: ErrorCode) -> bool:
    """Check if user can fix this error by correcting their input."""
    category = get_error_category(error_code)
    return category in {
        ErrorCategory.DATA_MISSING,
        ErrorCategory.DATA_QUALITY,
        ErrorCategory.DATA_INCOMPATIBLE,
        ErrorCategory.PARAMETER_ERROR,
    }


def get_http_status_code(error_code: ErrorCode) -> int:
    """Get appropriate HTTP status code for error."""
    # Resource not found → 404
    if error_code in {
        ErrorCode.CONTAINER_NOT_FOUND,
        ErrorCode.FILE_NOT_FOUND,
        ErrorCode.RESOURCE_NOT_FOUND
    }:
        return 404

    # Client/validation errors → 400
    if get_error_category(error_code) in {
        ErrorCategory.DATA_QUALITY,
        ErrorCategory.DATA_INCOMPATIBLE,
        ErrorCategory.PARAMETER_ERROR,
    }:
        return 400

    # Service unavailable → 503
    if get_error_category(error_code) == ErrorCategory.SERVICE_UNAVAILABLE:
        return 503

    # All other errors → 500
    return 500


def generate_error_id() -> str:
    """Generate unique error ID for support ticket correlation."""
    now = datetime.now(timezone.utc)
    return f"ERR-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


# ============================================================================
# ERROR RESPONSE FACTORIES
# ============================================================================

def create_error_response(
    error_code: ErrorCode,
    message: str,
    remediation: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> ErrorResponse:
    """
    Create a standardized ErrorResponse model.

    Args:
        error_code: ErrorCode enum value
        message: Human-readable error message
        remediation: How user can fix this error
        details: Structured error context

    Returns:
        ErrorResponse Pydantic model

    Example:
        >>> resp = create_error_response(
        ...     ErrorCode.FILE_NOT_FOUND,
        ...     "File 'test.tif' not found",
        ...     remediation="Verify file path and ensure upload completed."
        ... )
        >>> resp.error_category
        <ErrorCategory.DATA_MISSING: 'DATA_MISSING'>
        >>> resp.model_dump_json()
    """
    return ErrorResponse(
        error_code=error_code.value,
        error_category=get_error_category(error_code),
        error_scope=get_error_scope(error_code),
        retryable=is_retryable(error_code),
        user_fixable=is_user_fixable(error_code),
        http_status=get_http_status_code(error_code),
        message=message,
        remediation=remediation,
        details=details,
        error_id=generate_error_id(),
    )


def create_error_response_v2(
    error_code: ErrorCode,
    message: str,
    remediation: str,
    details: Optional[Dict[str, Any]] = None,
    exception: Optional[Exception] = None,
    context: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    stage: Optional[int] = None,
    handler: Optional[str] = None,
    include_debug: Optional[bool] = None,
) -> Tuple[ErrorResponse, ErrorDebug]:
    """
    Create enhanced error response with debug information.

    Returns TWO Pydantic models:
    1. ErrorResponse - For B2B client (debug conditionally included)
    2. ErrorDebug - Always store in job record error_details

    Args:
        error_code: ErrorCode enum value
        message: User-friendly error message
        remediation: How user can fix this error
        details: Structured error details
        exception: Python exception if available
        context: Additional context (file info, etc.)
        job_id, task_id, stage, handler: Execution context
        include_debug: Whether to include debug in ErrorResponse

    Returns:
        Tuple of (ErrorResponse, ErrorDebug)

    Example:
        >>> response, debug = create_error_response_v2(
        ...     ErrorCode.RASTER_64BIT_REJECTED,
        ...     "File uses 64-bit float",
        ...     "Re-export as 32-bit float.",
        ...     job_id="abc123"
        ... )
        >>> # Store debug in job record
        >>> job_repo.update(job_id, error_details=debug.model_dump_json())
        >>> # Return response to client
        >>> return response.model_dump()
    """
    error_id = generate_error_id()
    now = datetime.now(timezone.utc)

    # Build exception info if provided
    exception_info = None
    traceback_str = None

    if exception:
        tb = tb_module.extract_tb(exception.__traceback__) if exception.__traceback__ else []
        last_frame = tb[-1] if tb else None

        exception_info = ExceptionInfo(
            type=type(exception).__name__,
            message=str(exception),
            file=last_frame.filename.split("/")[-1] if last_frame else None,
            line=last_frame.lineno if last_frame else None,
            function=last_frame.name if last_frame else None,
        )

        traceback_str = "".join(tb_module.format_exception(
            type(exception), exception, exception.__traceback__
        ))

    # Create ErrorDebug (always created for storage)
    debug = ErrorDebug(
        error_id=error_id,
        timestamp=now,
        error_code=error_code.value,
        error_category=get_error_category(error_code).value,
        error_scope=get_error_scope(error_code).value,
        message=message,
        remediation=remediation,
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        handler=handler,
        details=details,
        exception=exception_info,
        traceback=traceback_str,
        context=context,
    )

    # Create ErrorResponse
    response = ErrorResponse(
        error_code=error_code.value,
        error_category=get_error_category(error_code),
        error_scope=get_error_scope(error_code),
        retryable=is_retryable(error_code),
        user_fixable=is_user_fixable(error_code),
        http_status=get_http_status_code(error_code),
        message=message,
        remediation=remediation,
        details=details,
        error_id=error_id,
        debug=debug if include_debug else None,
    )

    return response, debug
