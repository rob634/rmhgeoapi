# ============================================================================
# PLATFORM RESPONSE BUILDERS
# ============================================================================
# STATUS: Service layer - HTTP response construction helpers
# PURPOSE: Reduce duplication in platform trigger response building
# CREATED: 27 JAN 2026 (Phase 4 of trigger_platform.py refactor)
# EXPORTS: success_response, error_response, validation_error, submit_accepted, idempotent_response, check_accept_header
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
    check_accept_header: 406 guard for content negotiation (ADV-21)
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


def _generate_monitor_url(request_id: str) -> str:
    """Generate absolute URL for platform status endpoint."""
    config = _get_config()
    base_url = config.etl_app_base_url.rstrip('/')
    return f"{base_url}/api/platform/status/{request_id}"


# ============================================================================
# RESPONSE BUILDERS
# ============================================================================

def success_response(
    data: Dict[str, Any],
    status_code: int = 200,
    message: Optional[str] = None,
    cache_control: Optional[str] = None
) -> func.HttpResponse:
    """
    Build a success HTTP response.

    Args:
        data: Response payload (will be merged with success=True)
        status_code: HTTP status code (default 200)
        message: Optional message to include
        cache_control: Optional Cache-Control header value (ADV-20)

    Returns:
        Azure Functions HttpResponse
    """
    payload = {"success": True, **data}
    if message:
        payload["message"] = message

    headers = {"Content-Type": "application/json"}
    if cache_control:
        headers["Cache-Control"] = cache_control

    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        headers=headers
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
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
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

    Includes standard fields: request_id, job_id, job_type, monitor_url

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
            "monitor_url": _generate_monitor_url(request_id),
            **extra_fields
        },
        status_code=202,
        message=message,
        cache_control="no-store"
    )


def idempotent_response(
    request_id: str,
    job_id: str,
    message: str = "Request already submitted (idempotent)",
    hint: Optional[str] = None,
    job_type: Optional[str] = None,
    **extra_fields
) -> func.HttpResponse:
    """
    Build a 200 OK response for already-submitted (idempotent) requests.

    Args:
        request_id: Platform request ID
        job_id: CoreMachine job ID
        message: Idempotent message
        hint: Optional hint (e.g., "Use overwrite=true to force reprocessing")
        job_type: Job type (e.g., 'process_raster_docker') — matches fresh submit shape
        **extra_fields: Additional fields

    Returns:
        Azure Functions HttpResponse with status 200
    """
    data = {
        "request_id": request_id,
        "job_id": job_id,
        "monitor_url": _generate_monitor_url(request_id),
        **extra_fields
    }
    if job_type:
        data["job_type"] = job_type
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
            "monitor_url": _generate_monitor_url(request_id),
            **extra_fields
        },
        status_code=202,
        message=message,
        cache_control="no-store"
    )


# ============================================================================
# CONTENT NEGOTIATION (ADV-21)
# ============================================================================

def check_accept_header(req: func.HttpRequest) -> Optional[func.HttpResponse]:
    """
    Return 406 Not Acceptable if the client explicitly requests a non-JSON media type.

    Returns None when the request is acceptable (no Accept header, or Accept
    includes application/json or */*).  Returns an HttpResponse(406) otherwise.
    """
    accept = req.headers.get("Accept", "")
    if not accept or "application/json" in accept or "*/*" in accept:
        return None

    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": "This API only supports application/json responses.",
            "error_type": "NotAcceptable"
        }),
        status_code=406,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"}
    )
