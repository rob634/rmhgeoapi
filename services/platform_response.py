# ============================================================================
# PLATFORM RESPONSE BUILDERS
# ============================================================================
# STATUS: Service layer - HTTP response construction helpers
# PURPOSE: Reduce duplication in platform trigger response building
# CREATED: 27 JAN 2026 (Phase 4 of trigger_platform.py refactor)
# EXPORTS: success_response, error_response, validation_error, submit_accepted, idempotent_response
# ============================================================================
"""
Platform Response Builders.

Provides consistent HTTP response construction for platform triggers.
Reduces code duplication across submit and unpublish handlers.

Exports:
    success_response: Generic success response
    error_response: Generic error response
    validation_error: 400 Bad Request for validation failures
    not_implemented_error: 501 Not Implemented
    submit_accepted: 202 Accepted for job submissions
    idempotent_response: 200 OK for already-submitted requests
"""

import json
from typing import Dict, Any, Optional

import azure.functions as func

from config import get_config

# Cache config for URL generation
_config = None


def _get_config():
    """Lazy-load config to avoid import-time errors."""
    global _config
    if _config is None:
        _config = get_config()
    return _config


def _generate_job_status_url(job_id: str) -> str:
    """Generate absolute URL for platform job status endpoint."""
    config = _get_config()
    base_url = config.etl_app_base_url.rstrip('/')
    return f"{base_url}/api/platform/jobs/{job_id}/status"


# ============================================================================
# RESPONSE BUILDERS
# ============================================================================

def success_response(
    data: Dict[str, Any],
    status_code: int = 200,
    message: Optional[str] = None
) -> func.HttpResponse:
    """
    Build a success HTTP response.

    Args:
        data: Response payload (will be merged with success=True)
        status_code: HTTP status code (default 200)
        message: Optional message to include

    Returns:
        Azure Functions HttpResponse
    """
    payload = {"success": True, **data}
    if message:
        payload["message"] = message

    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )


def error_response(
    error: str,
    error_type: str,
    status_code: int = 500,
    **extra_fields
) -> func.HttpResponse:
    """
    Build an error HTTP response.

    Args:
        error: Error message
        error_type: Error type/category (e.g., "ValidationError", "RuntimeError")
        status_code: HTTP status code (default 500)
        **extra_fields: Additional fields to include in response

    Returns:
        Azure Functions HttpResponse
    """
    payload = {
        "success": False,
        "error": error,
        "error_type": error_type,
        **extra_fields
    }

    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )


def validation_error(error: str, **extra_fields) -> func.HttpResponse:
    """
    Build a 400 Bad Request response for validation errors.

    Args:
        error: Validation error message
        **extra_fields: Additional fields to include

    Returns:
        Azure Functions HttpResponse with status 400
    """
    return error_response(error, "ValidationError", status_code=400, **extra_fields)


def not_implemented_error(error: str) -> func.HttpResponse:
    """
    Build a 501 Not Implemented response.

    Args:
        error: Description of what's not implemented

    Returns:
        Azure Functions HttpResponse with status 501
    """
    return error_response(error, "NotImplemented", status_code=501)


def submit_accepted(
    request_id: str,
    job_id: str,
    job_type: str,
    message: str = "Request submitted.",
    **extra_fields
) -> func.HttpResponse:
    """
    Build a 202 Accepted response for successful job submission.

    Includes standard fields: request_id, job_id, job_type, monitor_url, job_status_url

    Args:
        request_id: Platform request ID
        job_id: CoreMachine job ID
        job_type: Job type (e.g., 'process_raster_docker')
        message: Success message
        **extra_fields: Additional fields (e.g., file_count, data_type)

    Returns:
        Azure Functions HttpResponse with status 202
    """
    return success_response(
        data={
            "request_id": request_id,
            "job_id": job_id,
            "job_type": job_type,
            "monitor_url": f"/api/platform/status/{request_id}",
            "job_status_url": _generate_job_status_url(job_id),
            **extra_fields
        },
        status_code=202,
        message=message
    )


def idempotent_response(
    request_id: str,
    job_id: str,
    message: str = "Request already submitted (idempotent)",
    hint: Optional[str] = None,
    **extra_fields
) -> func.HttpResponse:
    """
    Build a 200 OK response for already-submitted (idempotent) requests.

    Args:
        request_id: Platform request ID
        job_id: CoreMachine job ID
        message: Idempotent message
        hint: Optional hint (e.g., "Use overwrite=true to force reprocessing")
        **extra_fields: Additional fields

    Returns:
        Azure Functions HttpResponse with status 200
    """
    data = {
        "request_id": request_id,
        "job_id": job_id,
        "monitor_url": f"/api/platform/status/{request_id}",
        "job_status_url": _generate_job_status_url(job_id),
        **extra_fields
    }
    if hint:
        data["hint"] = hint

    return success_response(data, status_code=200, message=message)


def unpublish_accepted(
    request_id: str,
    job_id: str,
    data_type: str,
    dry_run: bool,
    message: Optional[str] = None,
    **extra_fields
) -> func.HttpResponse:
    """
    Build a 202 Accepted response for unpublish job submission.

    Args:
        request_id: Unpublish request ID
        job_id: CoreMachine job ID
        data_type: 'vector' or 'raster'
        dry_run: Whether this is a dry run
        message: Optional custom message
        **extra_fields: Additional fields (e.g., table_name, stac_item_id)

    Returns:
        Azure Functions HttpResponse with status 202
    """
    job_type = f"unpublish_{data_type}"
    if message is None:
        message = f"{data_type.title()} unpublish job submitted (dry_run={dry_run})"

    return success_response(
        data={
            "request_id": request_id,
            "job_id": job_id,
            "job_type": job_type,
            "data_type": data_type,
            "dry_run": dry_run,
            "monitor_url": f"/api/platform/status/{request_id}",
            "job_status_url": _generate_job_status_url(job_id),
            **extra_fields
        },
        status_code=202,
        message=message
    )
