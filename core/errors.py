"""
Error Code Definitions and Classification.

Centralized error code management with retry logic and consistent
error responses across all endpoints.

Key Features:
    - Explicit error codes for all failure modes
    - Retry classification (PERMANENT, TRANSIENT, THROTTLING)
    - Helper function to determine if error should retry

Exports:
    ErrorCode: Standardized error codes enum
    ErrorClassification: Error category enum
    is_retryable: Helper to check if error should be retried
"""

from enum import Enum
from typing import Dict, Any


class ErrorCode(str, Enum):
    """
    Standardized error codes for all application errors.

    These codes are returned in task results and API responses to provide
    explicit error classification for logging, monitoring, and retry logic.
    """

    # ========================================================================
    # VALIDATION ERRORS (Phase 1-2) - CLIENT ERRORS (HTTP 404/400)
    # ========================================================================

    # Resource not found errors (HTTP 404, NOT RETRYABLE)
    CONTAINER_NOT_FOUND = "CONTAINER_NOT_FOUND"  # Azure storage container doesn't exist
    FILE_NOT_FOUND = "FILE_NOT_FOUND"  # Blob doesn't exist in container
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"  # Generic resource not found

    # File/data errors (HTTP 400, MAYBE RETRYABLE)
    FILE_UNREADABLE = "FILE_UNREADABLE"  # File exists but GDAL/rasterio can't open
    CRS_MISSING = "CRS_MISSING"  # No CRS in file or parameters
    INVALID_FORMAT = "INVALID_FORMAT"  # File format not supported
    CORRUPTED_FILE = "CORRUPTED_FILE"  # File is corrupted or incomplete

    # Parameter validation errors (HTTP 400, NOT RETRYABLE)
    VALIDATION_ERROR = "VALIDATION_ERROR"  # Generic parameter validation failed
    INVALID_PARAMETER = "INVALID_PARAMETER"  # Specific parameter invalid
    MISSING_PARAMETER = "MISSING_PARAMETER"  # Required parameter missing

    # ========================================================================
    # PROCESSING ERRORS - SERVICE ERRORS (HTTP 500/503)
    # ========================================================================

    # Setup/configuration errors (HTTP 500, NOT RETRYABLE)
    SETUP_FAILED = "SETUP_FAILED"  # Failed to initialize components
    CONFIG_ERROR = "CONFIG_ERROR"  # Configuration error

    # CRS/projection errors (HTTP 400, NOT RETRYABLE)
    CRS_CHECK_FAILED = "CRS_CHECK_FAILED"  # CRS validation failed
    REPROJECTION_FAILED = "REPROJECTION_FAILED"  # Reprojection operation failed

    # Processing errors (HTTP 500, RETRYABLE)
    COG_TRANSLATE_FAILED = "COG_TRANSLATE_FAILED"  # COG translation failed
    COG_CREATION_FAILED = "COG_CREATION_FAILED"  # General COG creation error
    PROCESSING_FAILED = "PROCESSING_FAILED"  # Generic processing error

    # ========================================================================
    # INFRASTRUCTURE ERRORS (HTTP 500/503, RETRYABLE)
    # ========================================================================

    # Database errors (HTTP 500, RETRYABLE)
    DATABASE_ERROR = "DATABASE_ERROR"  # Database operation failed
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"  # Database query timeout
    DATABASE_CONNECTION_FAILED = "DATABASE_CONNECTION_FAILED"  # Can't connect to database

    # Storage errors (HTTP 503, RETRYABLE)
    STORAGE_ERROR = "STORAGE_ERROR"  # Azure storage error
    STORAGE_TIMEOUT = "STORAGE_TIMEOUT"  # Storage operation timeout
    UPLOAD_FAILED = "UPLOAD_FAILED"  # Failed to upload result
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"  # Failed to download input

    # Service Bus / Queue errors (HTTP 503, RETRYABLE)
    QUEUE_ERROR = "QUEUE_ERROR"  # Queue operation failed
    MESSAGE_ERROR = "MESSAGE_ERROR"  # Message processing error

    # Resource exhaustion (HTTP 503, THROTTLING)
    MEMORY_ERROR = "MEMORY_ERROR"  # Out of memory
    DISK_FULL = "DISK_FULL"  # Disk space exhausted
    TIMEOUT = "TIMEOUT"  # Operation timeout
    THROTTLED = "THROTTLED"  # Rate limited or throttled

    # ========================================================================
    # GENERIC ERRORS
    # ========================================================================

    UNKNOWN_ERROR = "UNKNOWN_ERROR"  # Unclassified error
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"  # Unexpected exception


class ErrorClassification(str, Enum):
    """
    Error classification for retry logic.

    Determines whether an error should trigger a retry or fail immediately.
    """

    PERMANENT = "PERMANENT"  # Never retry (client error, won't fix itself)
    TRANSIENT = "TRANSIENT"  # Retry with exponential backoff (temporary issue)
    THROTTLING = "THROTTLING"  # Retry with longer delay (rate limiting)


# Error code to classification mapping
_ERROR_CLASSIFICATION: Dict[ErrorCode, ErrorClassification] = {
    # PERMANENT - Never retry (client errors, user must fix)
    ErrorCode.CONTAINER_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.FILE_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorClassification.PERMANENT,
    ErrorCode.CRS_MISSING: ErrorClassification.PERMANENT,
    ErrorCode.VALIDATION_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.INVALID_PARAMETER: ErrorClassification.PERMANENT,
    ErrorCode.MISSING_PARAMETER: ErrorClassification.PERMANENT,
    ErrorCode.SETUP_FAILED: ErrorClassification.PERMANENT,
    ErrorCode.CONFIG_ERROR: ErrorClassification.PERMANENT,
    ErrorCode.CRS_CHECK_FAILED: ErrorClassification.PERMANENT,
    ErrorCode.INVALID_FORMAT: ErrorClassification.PERMANENT,

    # TRANSIENT - Retry with exponential backoff (temporary issues)
    ErrorCode.FILE_UNREADABLE: ErrorClassification.TRANSIENT,  # Might be temporary
    ErrorCode.CORRUPTED_FILE: ErrorClassification.TRANSIENT,  # Might be upload in progress
    ErrorCode.REPROJECTION_FAILED: ErrorClassification.TRANSIENT,  # Might be resource issue
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

    # UNKNOWN - Default to transient (retry a few times)
    ErrorCode.UNKNOWN_ERROR: ErrorClassification.TRANSIENT,
    ErrorCode.UNEXPECTED_ERROR: ErrorClassification.TRANSIENT,
}


def is_retryable(error_code: ErrorCode) -> bool:
    """
    Determine if an error code should trigger a retry.

    Args:
        error_code: ErrorCode enum value

    Returns:
        True if error should be retried, False otherwise

    Example:
        >>> is_retryable(ErrorCode.FILE_NOT_FOUND)
        False
        >>> is_retryable(ErrorCode.DATABASE_TIMEOUT)
        True
    """
    classification = _ERROR_CLASSIFICATION.get(error_code, ErrorClassification.TRANSIENT)
    return classification != ErrorClassification.PERMANENT


def get_error_classification(error_code: ErrorCode) -> ErrorClassification:
    """
    Get the classification for an error code.

    Args:
        error_code: ErrorCode enum value

    Returns:
        ErrorClassification enum value

    Example:
        >>> get_error_classification(ErrorCode.CONTAINER_NOT_FOUND)
        ErrorClassification.PERMANENT
    """
    return _ERROR_CLASSIFICATION.get(error_code, ErrorClassification.TRANSIENT)


def get_http_status_code(error_code: ErrorCode) -> int:
    """
    Get the appropriate HTTP status code for an error code.

    Args:
        error_code: ErrorCode enum value

    Returns:
        HTTP status code (400, 404, 500, 503)

    Example:
        >>> get_http_status_code(ErrorCode.FILE_NOT_FOUND)
        404
        >>> get_http_status_code(ErrorCode.VALIDATION_ERROR)
        400
    """
    # Resource not found errors → 404
    if error_code in {ErrorCode.CONTAINER_NOT_FOUND, ErrorCode.FILE_NOT_FOUND, ErrorCode.RESOURCE_NOT_FOUND}:
        return 404

    # Client/validation errors → 400
    if error_code in {
        ErrorCode.FILE_UNREADABLE,
        ErrorCode.CRS_MISSING,
        ErrorCode.INVALID_FORMAT,
        ErrorCode.CORRUPTED_FILE,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.INVALID_PARAMETER,
        ErrorCode.MISSING_PARAMETER,
        ErrorCode.CRS_CHECK_FAILED,
    }:
        return 400

    # Service unavailable (retryable infrastructure) → 503
    if error_code in {
        ErrorCode.STORAGE_TIMEOUT,
        ErrorCode.DATABASE_TIMEOUT,
        ErrorCode.QUEUE_ERROR,
        ErrorCode.THROTTLED,
        ErrorCode.DISK_FULL,
    }:
        return 503

    # All other errors → 500 (internal server error)
    return 500


def create_error_response(
    error_code: ErrorCode,
    message: str,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Create a standardized error response dictionary.

    Args:
        error_code: ErrorCode enum value
        message: Human-readable error message
        **kwargs: Additional fields to include in response

    Returns:
        Dict with standardized error response structure

    Example:
        >>> create_error_response(
        ...     ErrorCode.FILE_NOT_FOUND,
        ...     "File 'test.tif' not found in container 'bronze'",
        ...     blob_name="test.tif",
        ...     container_name="bronze"
        ... )
        {
            "success": False,
            "error": "FILE_NOT_FOUND",
            "error_type": "ResourceNotFoundError",
            "message": "File 'test.tif' not found in container 'bronze'",
            "retryable": False,
            "http_status": 404,
            "blob_name": "test.tif",
            "container_name": "bronze"
        }
    """
    response = {
        "success": False,
        "error": error_code.value,
        "error_type": kwargs.pop("error_type", "ValidationError"),
        "message": message,
        "retryable": is_retryable(error_code),
        "http_status": get_http_status_code(error_code),
        **kwargs  # Additional context fields
    }

    return response
