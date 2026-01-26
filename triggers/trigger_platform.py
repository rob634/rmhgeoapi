# ============================================================================
# PLATFORM REQUEST HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/*
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine jobs
# LAST_REVIEWED: 21 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: platform_request_submit, platform_raster_submit, platform_raster_collection_submit, platform_unpublish, platform_unpublish_vector (deprecated), platform_unpublish_raster (deprecated)
# DEPENDENCIES: infrastructure.PlatformRepository, infrastructure.service_bus
# ============================================================================
"""
Platform Request HTTP Trigger.

Anti-Corruption Layer that translates DDH requests to CoreMachine jobs with 1:1 mapping.
Supports vector and raster data processing workflows with thin tracking pattern.

Exports:
    platform_request_submit: Generic HTTP trigger for POST /api/platform/submit
    platform_raster_submit: Raster HTTP trigger for POST /api/platform/raster
    platform_raster_collection_submit: Raster collection HTTP trigger for POST /api/platform/raster-collection
    platform_unpublish: Consolidated unpublish HTTP trigger for POST /api/platform/unpublish (21 JAN 2026)
    platform_unpublish_vector: DEPRECATED - Vector unpublish HTTP trigger
    platform_unpublish_raster: DEPRECATED - Raster unpublish HTTP trigger
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

import azure.functions as func

# Configure logging
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform")

# Import config
try:
    from config import get_config, generate_platform_request_id
    config = get_config()
    logger.info("Platform trigger: config loaded successfully")
except Exception as e:
    logger.error(f"CRITICAL: Failed to load config: {e}")
    raise

# Import infrastructure
try:
    from infrastructure import PlatformRepository, JobRepository
    from infrastructure.service_bus import ServiceBusRepository
    logger.info("Platform trigger: infrastructure modules loaded")
except Exception as e:
    logger.error(f"CRITICAL: Failed to import infrastructure: {e}")
    raise

# Import core
try:
    from core.models.job import JobRecord
    from core.models.enums import JobStatus
    from core.models import (
        ApiRequest,
        DataType,
        OperationType,
        PlatformRequest
    )
    from core.schema.queue import JobQueueMessage
    logger.info("Platform trigger: core modules loaded")
except Exception as e:
    logger.error(f"CRITICAL: Failed to import core: {e}")
    raise


# ============================================================================
# URL GENERATION HELPERS (14 JAN 2026)
# ============================================================================

def _generate_job_status_url(job_id: str) -> str:
    """
    Generate absolute URL for platform job status endpoint.

    Used in submission responses so users can click directly to see job status.
    Uses ETL_APP_URL from config for the base URL.

    Args:
        job_id: CoreMachine job ID

    Returns:
        Absolute URL like: https://app.azurewebsites.net/api/platform/jobs/{job_id}/status
    """
    base_url = config.etl_app_base_url.rstrip('/')
    return f"{base_url}/api/platform/jobs/{job_id}/status"


# ============================================================================
# OVERWRITE HELPER (21 JAN 2026)
# ============================================================================

def _handle_overwrite_unpublish(existing_request: ApiRequest, platform_repo: PlatformRepository) -> None:
    """
    Handle unpublish before overwrite reprocessing (21 JAN 2026).

    When processing_options.overwrite=true is specified and a request already exists,
    this function:
    1. Determines the data type from the existing request
    2. Submits an unpublish job (synchronous call, dry_run=False)
    3. Deletes the existing platform request record

    Args:
        existing_request: The existing ApiRequest record to overwrite
        platform_repo: PlatformRepository instance

    Raises:
        RuntimeError: If unpublish job creation fails
        Exception: Any error from unpublish process
    """
    from core.models.enums import JobStatus

    data_type = _normalize_data_type(existing_request.data_type)
    logger.info(f"Overwrite unpublish: data_type={data_type}, request_id={existing_request.request_id[:16]}")

    # Generate unpublish parameters based on data type
    if data_type == "vector":
        table_name = _generate_table_name(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        unpublish_request_id = _generate_unpublish_request_id("vector", table_name)

        # Submit unpublish job (NOT dry_run - we want to actually delete)
        job_params = {
            "table_name": table_name,
            "schema_name": "geo",
            "dry_run": False,
            "force_approved": True  # Allow unpublishing even if approved
        }
        job_id = _create_and_submit_job("unpublish_vector", job_params, unpublish_request_id)

        if not job_id:
            raise RuntimeError(f"Failed to create unpublish_vector job for overwrite")

        logger.info(f"Overwrite: submitted unpublish_vector job {job_id[:16]} for table {table_name}")

    elif data_type == "raster":
        stac_item_id = _generate_stac_item_id(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        collection_id = existing_request.dataset_id
        unpublish_request_id = _generate_unpublish_request_id("raster", stac_item_id)

        # Submit unpublish job (NOT dry_run - we want to actually delete)
        job_params = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "dry_run": False,
            "force_approved": True  # Allow unpublishing even if approved
        }
        job_id = _create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

        if not job_id:
            raise RuntimeError(f"Failed to create unpublish_raster job for overwrite")

        logger.info(f"Overwrite: submitted unpublish_raster job {job_id[:16]} for item {stac_item_id}")

    else:
        raise ValueError(f"Unknown data_type for overwrite unpublish: {data_type}")

    # Delete the existing platform request record so the new one can be created
    # This allows the new request to use the same request_id
    _delete_platform_request(existing_request.request_id, platform_repo)
    logger.info(f"Overwrite: deleted existing platform request {existing_request.request_id[:16]}")


def _delete_platform_request(request_id: str, platform_repo: PlatformRepository) -> None:
    """
    Delete a platform request record (for overwrite operations).

    Args:
        request_id: Platform request ID to delete
        platform_repo: PlatformRepository instance
    """
    from psycopg import sql

    query = sql.SQL("""
        DELETE FROM {}.{} WHERE request_id = %s
    """).format(
        sql.Identifier(platform_repo.schema_name),
        sql.Identifier("api_requests")
    )

    platform_repo._execute_query(query, (request_id,), fetch=None)
    logger.debug(f"Deleted platform request: {request_id[:16]}")


# ============================================================================
# HTTP HANDLER
# ============================================================================

def platform_request_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for Platform request submission.

    POST /api/platform/submit

    Accepts DDH request format and creates appropriate CoreMachine job.
    Returns request_id for status polling via /api/platform/status/{request_id}

    Request Body (DDH Format):
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "operation": "CREATE",
        "container_name": "bronze-rasters",
        "file_name": "aerial-alpha.tif",
        "title": "Aerial Imagery Site Alpha",
        "access_level": "OUO",
        "processing_options": {
            "overwrite": false  // Set to true to force reprocessing (21 JAN 2026)
        }
    }

    Overwrite Mode (21 JAN 2026):
    When processing_options.overwrite=true and a request with the same DDH identifiers
    already exists:
    1. Existing outputs are unpublished (STAC items, COGs, or PostGIS tables)
    2. Existing platform request record is deleted
    3. New job is submitted with fresh processing

    Response:
    {
        "success": true,
        "request_id": "a3f2c1b8e9d7f6a5...",
        "job_id": "abc123def456...",
        "job_type": "process_raster_v2",
        "monitor_url": "/api/platform/status/a3f2c1b8e9d7f6a5..."
    }
    """
    logger.info("Platform request submission endpoint called")

    try:
        # Parse and validate request
        req_body = req.get_json()
        platform_req = PlatformRequest(**req_body)

        # Validate expected_data_type if specified (21 JAN 2026)
        # Catches mismatches like submitting .geojson when expecting raster
        platform_req.validate_expected_data_type()

        # Generate deterministic request ID (idempotent)
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id
        )

        logger.info(f"Processing Platform request: {request_id[:16]}...")
        logger.info(f"  Dataset: {platform_req.dataset_id}")
        logger.info(f"  Resource: {platform_req.resource_id}")
        logger.info(f"  Version: {platform_req.version_id}")
        logger.info(f"  Data type: {platform_req.data_type.value}")
        logger.info(f"  Operation: {platform_req.operation.value}")

        # Check for existing request (idempotent)
        # If processing_options.overwrite=true, unpublish existing and reprocess (21 JAN 2026)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(request_id)
        overwrite = platform_req.processing_options.get('overwrite', False) if platform_req.processing_options else False

        if existing:
            if overwrite:
                # Overwrite mode: unpublish existing outputs and reprocess (21 JAN 2026)
                logger.warning(f"OVERWRITE: Unpublishing existing request {request_id[:16]} before reprocessing")
                try:
                    _handle_overwrite_unpublish(existing, platform_repo)
                except Exception as unpublish_err:
                    logger.error(f"Failed to unpublish before overwrite: {unpublish_err}")
                    return func.HttpResponse(
                        json.dumps({
                            "success": False,
                            "error": f"Overwrite failed: could not unpublish existing outputs. {unpublish_err}",
                            "error_type": "OverwriteError",
                            "existing_request_id": request_id,
                            "existing_job_id": existing.job_id
                        }),
                        status_code=500,
                        headers={"Content-Type": "application/json"}
                    )
            else:
                # Normal idempotent behavior: return existing request
                logger.info(f"Request already exists: {request_id[:16]} → job {existing.job_id[:16]}")
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "request_id": request_id,
                        "job_id": existing.job_id,
                        "message": "Request already submitted (idempotent)",
                        "monitor_url": f"/api/platform/status/{request_id}",
                        "job_status_url": _generate_job_status_url(existing.job_id),
                        "hint": "Use processing_options.overwrite=true to force reprocessing"
                    }),
                    status_code=200,
                    headers={"Content-Type": "application/json"}
                )

        # Translate DDH request to CoreMachine job parameters
        job_type, job_params = _translate_to_coremachine(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create CoreMachine job
        job_id = _create_and_submit_job(job_type, job_params, request_id)

        if not job_id:
            raise RuntimeError("Failed to create CoreMachine job")

        # Store thin tracking record (request_id → job_id)
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id,
            job_id=job_id,
            data_type=platform_req.data_type.value
        )
        platform_repo.create_request(api_request)

        logger.info(f"Platform request submitted: {request_id[:16]} → job {job_id[:16]}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "job_type": job_type,
                "message": f"Platform request submitted. CoreMachine job created.",
                "monitor_url": f"/api/platform/status/{request_id}",
                "job_status_url": _generate_job_status_url(job_id)
            }),
            status_code=202,
            headers={"Content-Type": "application/json"}
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except NotImplementedError as e:
        logger.warning(f"Not implemented: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "NotImplemented"
            }),
            status_code=501,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform request failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# DEDICATED RASTER ENDPOINTS (05 DEC 2025)
# ============================================================================
# DDH explicitly chooses endpoint based on single vs multiple files:
#   - /api/platform/raster → single file (with size-based fallback)
#   - /api/platform/raster-collection → multiple files
# ============================================================================

def platform_raster_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for single raster submission.

    POST /api/platform/raster

    DDH uses this endpoint when submitting a single raster file.
    Platform routes to process_raster_v2 by default, with automatic fallback to
    process_large_raster_v2 if file exceeds size threshold.

    Use processing_mode="docker" for large/heavy rasters that require
    Docker-based processing (longer timeouts, more memory).

    Request Body:
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "container_name": "bronze-rasters",
        "file_name": "aerial-alpha.tif",
        "title": "Aerial Imagery Site Alpha",
        "access_level": "OUO",
        "processing_options": {
            "processing_mode": "docker"  // Optional: "function" (default) or "docker"
        }
    }

    Processing Modes:
        - "function" (default): Azure Function processing (process_raster_v2)
        - "docker": Docker container processing (process_raster_docker)
          Use for large files, complex projections, or when Function times out

    Note: file_name must be a string (single file), not a list.
    """
    logger.info("Platform single raster endpoint called")

    try:
        req_body = req.get_json()

        # Validate file_name is a single file, not a list
        file_name = req_body.get('file_name')
        if isinstance(file_name, list):
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "file_name must be a string for single raster endpoint. Use /api/platform/raster-collection for multiple files.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Force data_type to RASTER
        req_body['data_type'] = 'raster'

        platform_req = PlatformRequest(**req_body)

        # Generate deterministic request ID
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id
        )

        logger.info(f"Processing single raster request: {request_id[:16]}...")

        # Check for existing request (idempotent)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(request_id)
        if existing:
            logger.info(f"Request already exists: {request_id[:16]} → job {existing.job_id[:16]}")
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "request_id": request_id,
                    "job_id": existing.job_id,
                    "message": "Request already submitted (idempotent)",
                    "monitor_url": f"/api/platform/status/{request_id}",
                    "job_status_url": _generate_job_status_url(existing.job_id)
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        # Translate to CoreMachine job (always single raster path)
        job_type, job_params = _translate_single_raster(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create job (with fallback for large files)
        job_id = _create_and_submit_job(job_type, job_params, request_id)

        if not job_id:
            raise RuntimeError("Failed to create CoreMachine job")

        # Store tracking record
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id,
            job_id=job_id,
            data_type='raster'
        )
        platform_repo.create_request(api_request)

        logger.info(f"Single raster request submitted: {request_id[:16]} → job {job_id[:16]}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "job_type": job_type,
                "message": "Single raster request submitted.",
                "monitor_url": f"/api/platform/status/{request_id}",
                "job_status_url": _generate_job_status_url(job_id)
            }),
            status_code=202,
            headers={"Content-Type": "application/json"}
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Single raster request failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_raster_collection_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for raster collection submission.

    POST /api/platform/raster-collection

    DDH uses this endpoint when submitting multiple raster files as a collection.
    Platform routes to process_raster_collection_v2 (MosaicJSON pipeline).

    Request Body:
    {
        "dataset_id": "aerial-tiles-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "container_name": "bronze-rasters",
        "file_name": ["tile1.tif", "tile2.tif", "tile3.tif"],
        "title": "Aerial Tiles Site Alpha",
        "access_level": "OUO"
    }

    Note: file_name must be a list (multiple files), not a string.
    """
    logger.info("Platform raster collection endpoint called")

    try:
        req_body = req.get_json()

        # Validate file_name is a list
        file_name = req_body.get('file_name')
        if not isinstance(file_name, list):
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "file_name must be a list for raster collection endpoint. Use /api/platform/raster for single files.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        if len(file_name) < 2:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Raster collection requires at least 2 files. Use /api/platform/raster for single files.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Force data_type to RASTER
        req_body['data_type'] = 'raster'

        platform_req = PlatformRequest(**req_body)

        # Generate deterministic request ID
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id
        )

        logger.info(f"Processing raster collection request: {request_id[:16]}...")
        logger.info(f"  Collection size: {len(file_name)} files")

        # Check for existing request (idempotent)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(request_id)
        if existing:
            logger.info(f"Request already exists: {request_id[:16]} → job {existing.job_id[:16]}")
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "request_id": request_id,
                    "job_id": existing.job_id,
                    "message": "Request already submitted (idempotent)",
                    "monitor_url": f"/api/platform/status/{request_id}",
                    "job_status_url": _generate_job_status_url(existing.job_id)
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        # Translate to CoreMachine job (always collection path)
        job_type, job_params = _translate_raster_collection(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create job
        job_id = _create_and_submit_job(job_type, job_params, request_id)

        if not job_id:
            raise RuntimeError("Failed to create CoreMachine job")

        # Store tracking record
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id,
            job_id=job_id,
            data_type='raster'
        )
        platform_repo.create_request(api_request)

        logger.info(f"Raster collection request submitted: {request_id[:16]} → job {job_id[:16]}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "job_type": job_type,
                "file_count": len(file_name),
                "message": f"Raster collection request submitted ({len(file_name)} files).",
                "monitor_url": f"/api/platform/status/{request_id}",
                "job_status_url": _generate_job_status_url(job_id)
            }),
            status_code=202,
            headers={"Content-Type": "application/json"}
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Raster collection request failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# UNPUBLISH ENDPOINTS (17 DEC 2025)
# ============================================================================
# DEPRECATED (21 JAN 2026): Use /api/platform/unpublish instead.
# These endpoints are maintained for backward compatibility but will be removed.
# The consolidated endpoint auto-detects data type from the platform request.
# ============================================================================

def platform_unpublish_vector(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: HTTP trigger for vector unpublish via Platform layer.

    ⚠️ DEPRECATED (21 JAN 2026): Use POST /api/platform/unpublish instead.
    The consolidated endpoint auto-detects data type.

    POST /api/platform/unpublish/vector

    Accepts DDH identifiers, request_id, or direct table_name (cleanup mode).
    Translates to CoreMachine unpublish_vector job.

    Request Body Options:

    Option 1 - By DDH Identifiers (Preferred):
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "dry_run": true
    }

    Option 2 - By Request ID:
    {
        "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
        "dry_run": true
    }

    Option 3 - Cleanup Mode (direct table_name):
    {
        "table_name": "aerial_imagery_2024_site_alpha_v1_0",
        "dry_run": true
    }

    Response:
    {
        "success": true,
        "request_id": "unpublish-abc123...",
        "job_id": "def456...",
        "job_type": "unpublish_vector",
        "mode": "platform",  // or "cleanup"
        "message": "Vector unpublish job submitted (dry_run=true)",
        "monitor_url": "/api/platform/status/unpublish-abc123..."
    }
    """
    # Log deprecation warning (21 JAN 2026)
    logger.warning("DEPRECATED: /api/platform/unpublish/vector called - use /api/platform/unpublish instead")

    try:
        req_body = req.get_json()
        dry_run = req_body.get('dry_run', True)  # Safety default

        # Resolve internal parameters (table_name)
        table_name, mode, original_request = _resolve_vector_unpublish_params(req_body)

        if not table_name:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Could not resolve table_name. Provide: request_id, DDH identifiers (dataset_id, resource_id, version_id), or direct table_name.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.info(f"Unpublish vector: table_name={table_name}, mode={mode}, dry_run={dry_run}")

        # Generate unpublish request ID (different from create to avoid collision)
        unpublish_request_id = _generate_unpublish_request_id("vector", table_name)

        # Check for existing unpublish request (idempotent)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(unpublish_request_id)
        if existing:
            logger.info(f"Unpublish request already exists: {unpublish_request_id[:16]} → job {existing.job_id[:16]}")
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "request_id": unpublish_request_id,
                    "job_id": existing.job_id,
                    "mode": mode,
                    "message": "Unpublish request already submitted (idempotent)",
                    "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                    "job_status_url": _generate_job_status_url(existing.job_id)
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        # Submit unpublish_vector job
        force_approved = req_body.get('force_approved', False)  # 16 JAN 2026
        job_params = {
            "table_name": table_name,
            "schema_name": req_body.get('schema_name', 'geo'),
            "dry_run": dry_run,
            "force_approved": force_approved
        }

        job_id = _create_and_submit_job("unpublish_vector", job_params, unpublish_request_id)

        if not job_id:
            raise RuntimeError("Failed to create unpublish_vector job")

        # Track unpublish request in Platform layer
        api_request = ApiRequest(
            request_id=unpublish_request_id,
            dataset_id=original_request.dataset_id if original_request else "cleanup",
            resource_id=original_request.resource_id if original_request else table_name,
            version_id=original_request.version_id if original_request else "cleanup",
            job_id=job_id,
            data_type="unpublish_vector"
        )
        platform_repo.create_request(api_request)

        logger.info(f"Vector unpublish request submitted: {unpublish_request_id[:16]} → job {job_id[:16]}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": unpublish_request_id,
                "job_id": job_id,
                "job_type": "unpublish_vector",
                "mode": mode,
                "dry_run": dry_run,
                "table_name": table_name,
                "message": f"Vector unpublish job submitted (dry_run={dry_run})",
                "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                "job_status_url": _generate_job_status_url(job_id)
            }),
            status_code=202,
            headers={"Content-Type": "application/json"}
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform unpublish vector failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def platform_unpublish_raster(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: HTTP trigger for raster unpublish via Platform layer.

    ⚠️ DEPRECATED (21 JAN 2026): Use POST /api/platform/unpublish instead.
    The consolidated endpoint auto-detects data type.

    POST /api/platform/unpublish/raster

    Accepts DDH identifiers, request_id, direct STAC identifiers, or collection_id
    for collection-level deletion. Translates to CoreMachine unpublish_raster job(s).

    Request Body Options:

    Option 1 - By DDH Identifiers (Preferred):
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "dry_run": true
    }

    Option 2 - By Request ID:
    {
        "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
        "dry_run": true
    }

    Option 3 - Cleanup Mode (direct STAC identifiers for single item):
    {
        "stac_item_id": "aerial-imagery-2024-site-alpha-v1-0",
        "collection_id": "aerial-imagery-2024",
        "dry_run": true
    }

    Option 4 - Collection Mode (delete entire collection):
    {
        "collection_id": "aerial-imagery-2024",
        "delete_collection": true,
        "dry_run": false
    }
    Submits one unpublish job per item in the collection.

    Response (single item):
    {
        "success": true,
        "request_id": "unpublish-abc123...",
        "job_id": "def456...",
        "job_type": "unpublish_raster",
        "mode": "platform",  // or "cleanup"
        "message": "Raster unpublish job submitted (dry_run=true)",
        "monitor_url": "/api/platform/status/unpublish-abc123..."
    }

    Response (collection mode):
    {
        "success": true,
        "mode": "collection",
        "collection_id": "aerial-imagery-2024",
        "total_items": 5,
        "jobs_submitted": 5,
        "jobs_skipped": 0,
        "message": "Submitted 5 unpublish jobs..."
    }
    """
    # Log deprecation warning (21 JAN 2026)
    logger.warning("DEPRECATED: /api/platform/unpublish/raster called - use /api/platform/unpublish instead")

    try:
        req_body = req.get_json()
        dry_run = req_body.get('dry_run', True)  # Safety default

        # Resolve internal parameters (stac_item_id, collection_id)
        stac_item_id, collection_id, mode, original_request = _resolve_raster_unpublish_params(req_body)

        if not stac_item_id or not collection_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Could not resolve STAC identifiers. Provide: request_id, DDH identifiers (dataset_id, resource_id, version_id), or direct stac_item_id and collection_id.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.info(f"Unpublish raster: stac_item_id={stac_item_id}, collection_id={collection_id}, mode={mode}, dry_run={dry_run}")

        platform_repo = PlatformRepository()

        # Handle collection-level deletion
        if mode == "collection":
            return _handle_collection_unpublish(
                collection_id=collection_id,
                dry_run=dry_run,
                force_approved=req_body.get('force_approved', False),  # 16 JAN 2026
                platform_repo=platform_repo
            )

        # Single item deletion (existing behavior)
        # Generate unpublish request ID (different from create to avoid collision)
        unpublish_request_id = _generate_unpublish_request_id("raster", stac_item_id)

        # Check for existing unpublish request (idempotent with retry support - 01 JAN 2026)
        existing = platform_repo.get_request(unpublish_request_id)
        is_retry = False
        if existing:
            # Check job status - allow resubmission if job failed
            job_repo = JobRepository()
            existing_job = job_repo.get_job(existing.job_id)

            if existing_job and existing_job.status == JobStatus.FAILED:
                # Job failed - allow retry (01 JAN 2026)
                logger.info(
                    f"Previous job failed, allowing retry: {unpublish_request_id[:16]} "
                    f"(job {existing.job_id[:16]} status={existing_job.status.value})"
                )
                is_retry = True
            else:
                # Job is still running or completed - return idempotent
                job_status = existing_job.status.value if existing_job else "unknown"
                logger.info(f"Unpublish request already exists: {unpublish_request_id[:16]} → job {existing.job_id[:16]} (status={job_status})")
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "request_id": unpublish_request_id,
                        "job_id": existing.job_id,
                        "job_status": job_status,
                        "mode": mode,
                        "retry_count": existing.retry_count,
                        "message": "Unpublish request already submitted (idempotent)",
                        "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                        "job_status_url": _generate_job_status_url(existing.job_id)
                    }),
                    status_code=200,
                    headers={"Content-Type": "application/json"}
                )

        # Submit unpublish_raster job
        force_approved = req_body.get('force_approved', False)  # 16 JAN 2026
        job_params = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "dry_run": dry_run,
            "force_approved": force_approved
        }

        job_id = _create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

        if not job_id:
            raise RuntimeError("Failed to create unpublish_raster job")

        # Track unpublish request in Platform layer
        api_request = ApiRequest(
            request_id=unpublish_request_id,
            dataset_id=original_request.dataset_id if original_request else collection_id,
            resource_id=original_request.resource_id if original_request else stac_item_id,
            version_id=original_request.version_id if original_request else "cleanup",
            job_id=job_id,
            data_type="unpublish_raster"
        )
        created_request = platform_repo.create_request(api_request, is_retry=is_retry)

        retry_msg = f" (retry #{created_request.retry_count})" if is_retry else ""
        logger.info(f"Raster unpublish request submitted{retry_msg}: {unpublish_request_id[:16]} → job {job_id[:16]}")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": unpublish_request_id,
                "job_id": job_id,
                "job_type": "unpublish_raster",
                "mode": mode,
                "dry_run": dry_run,
                "is_retry": is_retry,
                "retry_count": created_request.retry_count,
                "stac_item_id": stac_item_id,
                "collection_id": collection_id,
                "message": f"Raster unpublish job submitted{retry_msg} (dry_run={dry_run})",
                "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                "job_status_url": _generate_job_status_url(job_id)
            }),
            status_code=202,
            headers={"Content-Type": "application/json"}
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform unpublish raster failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# CONSOLIDATED UNPUBLISH ENDPOINT (21 JAN 2026)
# ============================================================================
# Single endpoint that auto-detects data type from platform request record.
# Replaces separate /unpublish/vector and /unpublish/raster endpoints.
# ============================================================================

def platform_unpublish(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for consolidated unpublish via Platform layer (21 JAN 2026).

    POST /api/platform/unpublish

    Auto-detects data type (vector or raster) from platform request record or
    direct parameters. Consolidates /unpublish/vector and /unpublish/raster.

    Request Body Options:

    Option 1 - By DDH Identifiers (Preferred):
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "dry_run": true
    }

    Option 2 - By Request ID:
    {
        "request_id": "a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6",
        "dry_run": true
    }

    Option 3 - By Job ID:
    {
        "job_id": "abc123...",
        "dry_run": true
    }

    Option 4 - Cleanup Mode (explicit data_type required):
    {
        "data_type": "vector",
        "table_name": "my_table",
        "dry_run": true
    }
    OR
    {
        "data_type": "raster",
        "stac_item_id": "my-item",
        "collection_id": "my-collection",
        "dry_run": true
    }

    Response:
    {
        "success": true,
        "request_id": "unpublish-abc123...",
        "job_id": "def456...",
        "job_type": "unpublish_vector" or "unpublish_raster",
        "data_type": "vector" or "raster",
        "dry_run": true,
        "message": "Unpublish job submitted (dry_run=true)",
        "monitor_url": "/api/platform/status/unpublish-abc123..."
    }
    """
    logger.info("Platform consolidated unpublish endpoint called")

    try:
        req_body = req.get_json()
        dry_run = req_body.get('dry_run', True)  # Safety default

        # Resolve data type and parameters
        data_type, resolved_params, original_request = _resolve_unpublish_data_type(req_body)

        if not data_type:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "Could not determine data type. Provide: request_id, job_id, DDH identifiers (dataset_id, resource_id, version_id), or explicit data_type with identifiers.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.info(f"Unpublish: data_type={data_type}, dry_run={dry_run}, params={resolved_params}")

        # Delegate to appropriate handler based on data type
        if data_type == "vector":
            return _execute_vector_unpublish(
                table_name=resolved_params.get('table_name'),
                schema_name=req_body.get('schema_name', 'geo'),
                dry_run=dry_run,
                force_approved=req_body.get('force_approved', False),
                original_request=original_request
            )
        elif data_type == "raster":
            # Check for collection mode
            if req_body.get('delete_collection') and resolved_params.get('collection_id'):
                return _handle_collection_unpublish(
                    collection_id=resolved_params['collection_id'],
                    dry_run=dry_run,
                    force_approved=req_body.get('force_approved', False),
                    platform_repo=PlatformRepository()
                )
            return _execute_raster_unpublish(
                stac_item_id=resolved_params.get('stac_item_id'),
                collection_id=resolved_params.get('collection_id'),
                dry_run=dry_run,
                force_approved=req_body.get('force_approved', False),
                original_request=original_request
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Unknown data type: {data_type}. Must be 'vector' or 'raster'.",
                    "error_type": "ValidationError"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform unpublish failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def _resolve_unpublish_data_type(req_body: dict) -> tuple:
    """
    Auto-detect data type and resolve parameters for unpublish (21 JAN 2026).

    Resolution order:
    1. request_id → lookup platform request, get data_type
    2. job_id → lookup platform request by job, get data_type
    3. DDH identifiers → lookup platform request, get data_type
    4. Explicit data_type parameter → use direct identifiers

    Args:
        req_body: Request body dict

    Returns:
        Tuple of (data_type, resolved_params, original_request)
        - data_type: "vector" or "raster" (or None if can't determine)
        - resolved_params: Dict with identifiers (table_name or stac_item_id/collection_id)
        - original_request: ApiRequest if found, None otherwise
    """
    platform_repo = PlatformRepository()
    original_request = None
    data_type = None
    resolved_params = {}

    # Option 1: By request_id
    request_id = req_body.get('request_id')
    if request_id:
        original_request = platform_repo.get_request(request_id)
        if original_request:
            data_type = _normalize_data_type(original_request.data_type)
            resolved_params = _get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 2: By job_id
    job_id = req_body.get('job_id')
    if job_id:
        original_request = platform_repo.get_request_by_job(job_id)
        if original_request:
            data_type = _normalize_data_type(original_request.data_type)
            resolved_params = _get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 3: By DDH identifiers
    dataset_id = req_body.get('dataset_id')
    resource_id = req_body.get('resource_id')
    version_id = req_body.get('version_id')
    if dataset_id and resource_id and version_id:
        original_request = platform_repo.get_request_by_ddh_ids(dataset_id, resource_id, version_id)
        if original_request:
            data_type = _normalize_data_type(original_request.data_type)
            resolved_params = _get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 4: Explicit data_type with direct identifiers (cleanup mode)
    explicit_data_type = req_body.get('data_type')
    if explicit_data_type:
        data_type = _normalize_data_type(explicit_data_type)
        if data_type == "vector":
            table_name = req_body.get('table_name')
            if table_name:
                resolved_params = {'table_name': table_name}
                return data_type, resolved_params, None
        elif data_type == "raster":
            stac_item_id = req_body.get('stac_item_id')
            collection_id = req_body.get('collection_id')
            if stac_item_id and collection_id:
                resolved_params = {'stac_item_id': stac_item_id, 'collection_id': collection_id}
                return data_type, resolved_params, None
            elif collection_id and req_body.get('delete_collection'):
                resolved_params = {'collection_id': collection_id}
                return data_type, resolved_params, None

    # Fallback: Try to infer from direct parameters
    if req_body.get('table_name'):
        return "vector", {'table_name': req_body['table_name']}, None
    if req_body.get('stac_item_id') and req_body.get('collection_id'):
        return "raster", {'stac_item_id': req_body['stac_item_id'], 'collection_id': req_body['collection_id']}, None

    return None, {}, None


def _normalize_data_type(data_type: str) -> str:
    """Normalize data_type to 'vector' or 'raster'."""
    if not data_type:
        return None
    dt_lower = data_type.lower()
    if dt_lower in ('vector', 'unpublish_vector', 'process_vector'):
        return 'vector'
    if dt_lower in ('raster', 'unpublish_raster', 'process_raster', 'process_raster_v2', 'process_raster_docker'):
        return 'raster'
    return dt_lower


def _generate_table_name(dataset_id: str, resource_id: str, version_id: str) -> str:
    """
    Generate PostGIS table name from DDH identifiers.

    Uses PlatformConfig.generate_vector_table_name() for consistency.

    Args:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier

    Returns:
        URL-safe table name
    """
    return config.platform.generate_vector_table_name(dataset_id, resource_id, version_id)


def _generate_stac_item_id(dataset_id: str, resource_id: str, version_id: str) -> str:
    """
    Generate STAC item ID from DDH identifiers.

    Uses PlatformConfig.generate_stac_item_id() for consistency.

    Args:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier

    Returns:
        URL-safe STAC item ID
    """
    return config.platform.generate_stac_item_id(dataset_id, resource_id, version_id)


def _get_unpublish_params_from_request(request: ApiRequest, data_type: str) -> dict:
    """Extract unpublish parameters from a platform request."""
    if data_type == "vector":
        # Generate table_name from DDH identifiers
        table_name = _generate_table_name(request.dataset_id, request.resource_id, request.version_id)
        return {'table_name': table_name}
    elif data_type == "raster":
        # Generate STAC identifiers from DDH identifiers
        stac_item_id = _generate_stac_item_id(request.dataset_id, request.resource_id, request.version_id)
        collection_id = request.dataset_id
        return {'stac_item_id': stac_item_id, 'collection_id': collection_id}
    return {}


def _execute_vector_unpublish(
    table_name: str,
    schema_name: str,
    dry_run: bool,
    force_approved: bool,
    original_request: Optional[ApiRequest]
) -> func.HttpResponse:
    """Execute vector unpublish job."""
    if not table_name:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "table_name is required for vector unpublish",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    platform_repo = PlatformRepository()
    unpublish_request_id = _generate_unpublish_request_id("vector", table_name)

    # Check for existing (idempotent)
    existing = platform_repo.get_request(unpublish_request_id)
    if existing:
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": unpublish_request_id,
                "job_id": existing.job_id,
                "data_type": "vector",
                "message": "Unpublish request already submitted (idempotent)",
                "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                "job_status_url": _generate_job_status_url(existing.job_id)
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    # Submit job
    job_params = {
        "table_name": table_name,
        "schema_name": schema_name,
        "dry_run": dry_run,
        "force_approved": force_approved
    }
    job_id = _create_and_submit_job("unpublish_vector", job_params, unpublish_request_id)

    if not job_id:
        raise RuntimeError("Failed to create unpublish_vector job")

    # Track request
    api_request = ApiRequest(
        request_id=unpublish_request_id,
        dataset_id=original_request.dataset_id if original_request else "cleanup",
        resource_id=original_request.resource_id if original_request else table_name,
        version_id=original_request.version_id if original_request else "cleanup",
        job_id=job_id,
        data_type="unpublish_vector"
    )
    platform_repo.create_request(api_request)

    logger.info(f"Vector unpublish submitted: {unpublish_request_id[:16]} → job {job_id[:16]}")

    return func.HttpResponse(
        json.dumps({
            "success": True,
            "request_id": unpublish_request_id,
            "job_id": job_id,
            "job_type": "unpublish_vector",
            "data_type": "vector",
            "dry_run": dry_run,
            "table_name": table_name,
            "message": f"Vector unpublish job submitted (dry_run={dry_run})",
            "monitor_url": f"/api/platform/status/{unpublish_request_id}",
            "job_status_url": _generate_job_status_url(job_id)
        }),
        status_code=202,
        headers={"Content-Type": "application/json"}
    )


def _execute_raster_unpublish(
    stac_item_id: str,
    collection_id: str,
    dry_run: bool,
    force_approved: bool,
    original_request: Optional[ApiRequest]
) -> func.HttpResponse:
    """Execute raster unpublish job."""
    if not stac_item_id or not collection_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "stac_item_id and collection_id are required for raster unpublish",
                "error_type": "ValidationError"
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    platform_repo = PlatformRepository()
    unpublish_request_id = _generate_unpublish_request_id("raster", stac_item_id)

    # Check for existing with retry support
    existing = platform_repo.get_request(unpublish_request_id)
    is_retry = False
    if existing:
        job_repo = JobRepository()
        existing_job = job_repo.get_job(existing.job_id)

        if existing_job and existing_job.status == JobStatus.FAILED:
            is_retry = True
            logger.info(f"Previous job failed, allowing retry: {unpublish_request_id[:16]}")
        else:
            job_status = existing_job.status.value if existing_job else "unknown"
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "request_id": unpublish_request_id,
                    "job_id": existing.job_id,
                    "job_status": job_status,
                    "data_type": "raster",
                    "message": "Unpublish request already submitted (idempotent)",
                    "monitor_url": f"/api/platform/status/{unpublish_request_id}",
                    "job_status_url": _generate_job_status_url(existing.job_id)
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

    # Submit job
    job_params = {
        "stac_item_id": stac_item_id,
        "collection_id": collection_id,
        "dry_run": dry_run,
        "force_approved": force_approved
    }
    job_id = _create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

    if not job_id:
        raise RuntimeError("Failed to create unpublish_raster job")

    # Track request
    api_request = ApiRequest(
        request_id=unpublish_request_id,
        dataset_id=original_request.dataset_id if original_request else collection_id,
        resource_id=original_request.resource_id if original_request else stac_item_id,
        version_id=original_request.version_id if original_request else "cleanup",
        job_id=job_id,
        data_type="unpublish_raster"
    )
    created_request = platform_repo.create_request(api_request, is_retry=is_retry)

    retry_msg = f" (retry #{created_request.retry_count})" if is_retry else ""
    logger.info(f"Raster unpublish submitted{retry_msg}: {unpublish_request_id[:16]} → job {job_id[:16]}")

    return func.HttpResponse(
        json.dumps({
            "success": True,
            "request_id": unpublish_request_id,
            "job_id": job_id,
            "job_type": "unpublish_raster",
            "data_type": "raster",
            "dry_run": dry_run,
            "is_retry": is_retry,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "message": f"Raster unpublish job submitted{retry_msg} (dry_run={dry_run})",
            "monitor_url": f"/api/platform/status/{unpublish_request_id}",
            "job_status_url": _generate_job_status_url(job_id)
        }),
        status_code=202,
        headers={"Content-Type": "application/json"}
    )


# ============================================================================
# UNPUBLISH HELPER FUNCTIONS
# ============================================================================

def _resolve_vector_unpublish_params(req_body: dict) -> tuple:
    """
    Resolve table_name from request body for vector unpublish.

    Supports three input modes:
    1. By request_id → lookup original request, generate table_name from DDH IDs
    2. By DDH identifiers → generate table_name directly
    3. Cleanup mode → use direct table_name parameter

    Args:
        req_body: Request body dict

    Returns:
        Tuple of (table_name, mode, original_request)
        - table_name: PostGIS table name to unpublish
        - mode: "platform" (from request lookup) or "cleanup" (direct params)
        - original_request: ApiRequest if found, None otherwise
    """
    platform_repo = PlatformRepository()

    # Option 1: By request_id
    if 'request_id' in req_body:
        original = platform_repo.get_request(req_body['request_id'])
        if original:
            table_name = config.platform.generate_vector_table_name(
                original.dataset_id, original.resource_id, original.version_id
            )
            logger.info(f"Resolved via request_id: {req_body['request_id'][:16]}... → {table_name}")
            return table_name, "platform", original
        else:
            logger.warning(f"Request ID not found: {req_body['request_id']}")

    # Option 2: By DDH identifiers
    if all(k in req_body for k in ['dataset_id', 'resource_id', 'version_id']):
        # Generate table name from DDH identifiers
        table_name = config.platform.generate_vector_table_name(
            req_body['dataset_id'], req_body['resource_id'], req_body['version_id']
        )

        # Try to find original request
        original = platform_repo.get_request_by_ddh_ids(
            req_body['dataset_id'], req_body['resource_id'], req_body['version_id']
        )

        if original:
            logger.info(f"Resolved via DDH IDs → {table_name} (original request found)")
            return table_name, "platform", original
        else:
            logger.warning(f"No platform request found for DDH IDs - entering cleanup mode")
            return table_name, "cleanup", None

    # Option 3: Direct table_name (cleanup mode)
    if 'table_name' in req_body:
        logger.warning(f"Direct table_name provided - cleanup mode: {req_body['table_name']}")
        return req_body['table_name'], "cleanup", None

    return None, None, None


def _resolve_raster_unpublish_params(req_body: dict) -> tuple:
    """
    Resolve STAC identifiers from request body for raster unpublish.

    Supports three input modes:
    1. By request_id → lookup original request, generate STAC IDs from DDH IDs
    2. By DDH identifiers → generate STAC IDs directly
    3. Cleanup mode → use direct stac_item_id and collection_id parameters

    Args:
        req_body: Request body dict

    Returns:
        Tuple of (stac_item_id, collection_id, mode, original_request)
        - stac_item_id: STAC item ID to unpublish
        - collection_id: STAC collection ID
        - mode: "platform" (from request lookup) or "cleanup" (direct params)
        - original_request: ApiRequest if found, None otherwise
    """
    platform_repo = PlatformRepository()

    # Option 1: By request_id
    if 'request_id' in req_body:
        original = platform_repo.get_request(req_body['request_id'])
        if original:
            stac_item_id = config.platform.generate_stac_item_id(
                original.dataset_id, original.resource_id, original.version_id
            )
            collection_id = config.platform.generate_stac_collection_id(
                original.dataset_id, original.resource_id, original.version_id
            )
            logger.info(f"Resolved via request_id: {req_body['request_id'][:16]}... → {stac_item_id}")
            return stac_item_id, collection_id, "platform", original
        else:
            logger.warning(f"Request ID not found: {req_body['request_id']}")

    # Option 2: By DDH identifiers
    if all(k in req_body for k in ['dataset_id', 'resource_id', 'version_id']):
        # Generate STAC IDs from DDH identifiers
        stac_item_id = config.platform.generate_stac_item_id(
            req_body['dataset_id'], req_body['resource_id'], req_body['version_id']
        )
        collection_id = config.platform.generate_stac_collection_id(
            req_body['dataset_id'], req_body['resource_id'], req_body['version_id']
        )

        # Try to find original request
        original = platform_repo.get_request_by_ddh_ids(
            req_body['dataset_id'], req_body['resource_id'], req_body['version_id']
        )

        if original:
            logger.info(f"Resolved via DDH IDs → {stac_item_id} (original request found)")
            return stac_item_id, collection_id, "platform", original
        else:
            logger.warning(f"No platform request found for DDH IDs - entering cleanup mode")
            return stac_item_id, collection_id, "cleanup", None

    # Option 3: Direct STAC identifiers (cleanup mode)
    if 'stac_item_id' in req_body and 'collection_id' in req_body:
        logger.warning(f"Direct STAC IDs provided - cleanup mode: {req_body['stac_item_id']}")
        return req_body['stac_item_id'], req_body['collection_id'], "cleanup", None

    # Option 4: Collection-only mode (delete entire collection)
    # Returns special marker for collection-level deletion
    if 'collection_id' in req_body and req_body.get('delete_collection', False):
        collection_id = req_body['collection_id']
        logger.info(f"Collection-level unpublish requested: {collection_id}")
        # Return special marker "__COLLECTION__" as stac_item_id
        return "__COLLECTION__", collection_id, "collection", None

    return None, None, None, None


def _generate_unpublish_request_id(data_type: str, internal_id: str) -> str:
    """
    Generate deterministic request ID for unpublish operations.

    Uses different hash input than create operations to avoid collision.
    Same unpublish parameters will always generate same request ID (idempotent).

    Args:
        data_type: "vector" or "raster"
        internal_id: table_name (vector) or stac_item_id (raster)

    Returns:
        32-character hex string (SHA256 prefix)
    """
    import hashlib

    # Include "unpublish" prefix to avoid collision with create request IDs
    combined = f"unpublish-{data_type}|{internal_id}"
    hash_hex = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    return hash_hex[:32]


def _handle_collection_unpublish(
    collection_id: str,
    dry_run: bool,
    force_approved: bool,  # 16 JAN 2026
    platform_repo: 'PlatformRepository'
) -> func.HttpResponse:
    """
    Handle collection-level unpublish by submitting jobs for all items.

    Queries all items in the collection and submits an unpublish_raster job
    for each item. Jobs run in parallel via Service Bus.

    Args:
        collection_id: STAC collection ID to unpublish
        dry_run: If True, preview only (no deletions)
        force_approved: If True, revoke approvals and unpublish approved items (16 JAN 2026)
        platform_repo: PlatformRepository instance

    Returns:
        HttpResponse with summary of submitted jobs
    """
    from infrastructure.pgstac_repository import PgStacRepository

    logger.info(f"Collection-level unpublish: {collection_id} (dry_run={dry_run})")

    # Query all items in the collection
    pgstac_repo = PgStacRepository()
    item_ids = pgstac_repo.get_collection_item_ids(collection_id)

    if not item_ids:
        logger.warning(f"Collection '{collection_id}' has no items to unpublish")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"Collection '{collection_id}' has no items to unpublish",
                "error_type": "ValidationError",
                "collection_id": collection_id
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    logger.info(f"Found {len(item_ids)} items in collection '{collection_id}'")

    # Submit unpublish job for each item
    submitted_jobs = []
    skipped_jobs = []
    retried_jobs = []
    job_repo = JobRepository()

    for stac_item_id in item_ids:
        unpublish_request_id = _generate_unpublish_request_id("raster", stac_item_id)

        # Check for existing request (idempotent with retry support - 01 JAN 2026)
        existing = platform_repo.get_request(unpublish_request_id)
        is_retry = False

        if existing:
            # Check job status - allow resubmission if job failed
            existing_job = job_repo.get_job(existing.job_id)

            if existing_job and existing_job.status == JobStatus.FAILED:
                # Job failed - allow retry
                is_retry = True
                logger.info(f"Previous job failed, retrying: {stac_item_id}")
            else:
                # Job is still running or completed - skip
                job_status = existing_job.status.value if existing_job else "unknown"
                skipped_jobs.append({
                    "stac_item_id": stac_item_id,
                    "request_id": unpublish_request_id,
                    "job_id": existing.job_id,
                    "job_status": job_status,
                    "status": "already_submitted"
                })
                continue

        # Submit job
        job_params = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "dry_run": dry_run,
            "force_approved": force_approved  # 16 JAN 2026
        }

        job_id = _create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

        if job_id:
            # Track in Platform layer
            api_request = ApiRequest(
                request_id=unpublish_request_id,
                dataset_id=collection_id,
                resource_id=stac_item_id,
                version_id="collection_unpublish",
                job_id=job_id,
                data_type="unpublish_raster"
            )
            created_request = platform_repo.create_request(api_request, is_retry=is_retry)

            job_info = {
                "stac_item_id": stac_item_id,
                "request_id": unpublish_request_id,
                "job_id": job_id,
                "retry_count": created_request.retry_count
            }

            if is_retry:
                retried_jobs.append(job_info)
            else:
                submitted_jobs.append(job_info)
        else:
            logger.error(f"Failed to submit unpublish job for item: {stac_item_id}")

    logger.info(
        f"Collection unpublish submitted: {len(submitted_jobs)} new jobs, "
        f"{len(retried_jobs)} retried, {len(skipped_jobs)} skipped"
    )

    return func.HttpResponse(
        json.dumps({
            "success": True,
            "mode": "collection",
            "collection_id": collection_id,
            "dry_run": dry_run,
            "total_items": len(item_ids),
            "jobs_submitted": len(submitted_jobs),
            "jobs_retried": len(retried_jobs),
            "jobs_skipped": len(skipped_jobs),
            "message": f"Submitted {len(submitted_jobs)} new + {len(retried_jobs)} retried unpublish jobs for collection '{collection_id}' (dry_run={dry_run})",
            "submitted_jobs": submitted_jobs[:10],  # Limit to first 10 for response size
            "retried_jobs": retried_jobs[:10],
            "skipped_jobs": skipped_jobs[:10]
        }),
        status_code=202,
        headers={"Content-Type": "application/json"}
    )


# ============================================================================
# PARAMETER TRANSLATION (DDH → CoreMachine)
# ============================================================================

def _translate_to_coremachine(
    request: PlatformRequest,
    cfg
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH PlatformRequest to CoreMachine job_type + parameters.

    This is the core of the Anti-Corruption Layer - it isolates DDH API
    from CoreMachine internals. If DDH changes their API, we update this
    function, not CoreMachine jobs.

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance

    Returns:
        Tuple of (job_type, job_parameters)

    Raises:
        ValueError: If data type or operation not supported
        NotImplementedError: If operation is UPDATE/DELETE (Phase 2)
    """
    operation = request.operation
    data_type = request.data_type

    # Only CREATE is implemented (Phase 1)
    if operation != OperationType.CREATE:
        raise NotImplementedError(f"{operation.value} operation coming in Phase 2")

    # Use PlatformConfig for output naming
    platform_cfg = cfg.platform

    # ========================================================================
    # VECTOR CREATE → vector_docker_etl (V0.8) or process_vector (fallback)
    # ========================================================================
    # V0.8 (24 JAN 2026): Routes to Docker by default for performance.
    # Set docker=false in processing_options to use Function App worker.
    if data_type == DataType.VECTOR:
        # Table name: use override from processing_options if provided (26 JAN 2026)
        # Otherwise auto-generate from DDH identifiers
        # This allows human-readable names when DDH IDs are numeric (e.g., "552342_2342345_v2")
        opts = request.processing_options
        table_name = opts.get('table_name')
        if not table_name:
            table_name = platform_cfg.generate_vector_table_name(
                request.dataset_id,
                request.resource_id,
                request.version_id
            )
        else:
            # Sanitize user-provided table name for PostgreSQL
            from config.platform_config import _slugify_for_postgres
            table_name = _slugify_for_postgres(table_name)
            logger.info(f"  Using table_name override: {table_name}")

        # Generate STAC item ID
        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Detect file extension
        file_name = request.file_name
        if isinstance(file_name, list):
            file_name = file_name[0]
        file_ext = file_name.split('.')[-1].lower()

        # Build converter params if CSV/lon-lat columns specified
        # Note: Use 'lat_name'/'lon_name' keys to match job validator expectations
        converter_params = {}
        if opts.get('lon_column') or opts.get('lat_column') or opts.get('wkt_column'):
            converter_params = {
                'lon_name': opts.get('lon_column'),
                'lat_name': opts.get('lat_column'),
                'wkt_column': opts.get('wkt_column')
            }

        # V0.8: Docker routing parameter (default: true)
        # Set docker=false to use Function App worker (retained for future size-based routing)
        use_docker = opts.get('docker', True)

        if use_docker:
            job_type = 'vector_docker_etl'
            logger.info(f"[PLATFORM] Routing vector ETL to Docker worker (docker=true)")
        else:
            job_type = 'process_vector'
            logger.info(f"[PLATFORM] Routing vector ETL to Function App (docker=false)")

        return job_type, {
            # File location
            'blob_name': request.file_name,
            'file_extension': file_ext,
            'container_name': request.container_name,

            # PostGIS target
            'table_name': table_name,
            'schema': cfg.vector.target_schema,

            # DDH identifiers (for STAC metadata)
            'dataset_id': request.dataset_id,
            'resource_id': request.resource_id,
            'version_id': request.version_id,

            # STAC metadata
            'stac_item_id': stac_item_id,
            'title': request.generated_title,
            'description': request.description,
            'tags': request.tags,
            'access_level': request.access_level.value,  # E4 Phase 1: enum → string

            # Processing options
            'converter_params': converter_params,
            'overwrite': opts.get('overwrite', False)
        }

    # ========================================================================
    # RASTER CREATE → process_raster_v2 or process_raster_collection_v2
    # ========================================================================
    # Updated 04 DEC 2025: All raster jobs now use v2 mixin pattern
    # - Single raster: process_raster_v2 (with auto-fallback to process_large_raster_v2)
    # - Collection: process_raster_collection_v2
    elif data_type == DataType.RASTER:
        opts = request.processing_options

        # Generate output paths from DDH IDs
        output_folder = platform_cfg.generate_raster_output_folder(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Collection ID: use override from processing_options if provided (22 JAN 2026)
        # Otherwise auto-generate from DDH identifiers
        collection_id = opts.get('collection_id')
        if not collection_id:
            collection_id = platform_cfg.generate_stac_collection_id(
                request.dataset_id,
                request.resource_id,
                request.version_id
            )
        else:
            logger.info(f"  Using collection_id override: {collection_id}")

        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Check if this is a raster collection (multiple files)
        if request.is_raster_collection:
            # Multiple rasters → process_raster_collection_v2 (mixin pattern, 04 DEC 2025)
            return 'process_raster_collection_v2', {
                # File location (required)
                'container_name': request.container_name,
                'blob_list': request.file_name,  # Already a list

                # Output location
                'output_folder': output_folder,

                # STAC metadata (MosaicJSON schema)
                'collection_id': collection_id,
                'stac_item_id': stac_item_id,
                'collection_description': request.description,
                'access_level': request.access_level.value,  # E4 Phase 1: enum → string

                # DDH identifiers (Platform passthrough)
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,

                # Processing options
                'output_tier': opts.get('output_tier', 'analysis'),
                'target_crs': opts.get('crs')
            }
        else:
            # Single raster → process_raster_v2 or process_raster_docker (12 JAN 2026)
            file_name = request.file_name
            if isinstance(file_name, list):
                file_name = file_name[0]

            # Determine processing mode (21 JAN 2026)
            # Default to Docker if docker_worker_enabled, else Function App
            # Explicit processing_mode in options overrides the default
            from config import get_app_mode_config
            app_mode_config = get_app_mode_config()

            processing_mode = opts.get('processing_mode')
            if processing_mode:
                # Explicit override from client
                processing_mode = processing_mode.lower()
            elif app_mode_config.docker_worker_enabled:
                # Default to Docker when worker is enabled (phasing out Function App raster processing)
                processing_mode = 'docker'
            else:
                # Fallback to Function App when no Docker worker
                processing_mode = 'function'

            if processing_mode == 'docker':
                job_type = 'process_raster_docker'
            else:
                job_type = 'process_raster_v2'

            logger.info(f"  Raster processing mode: {processing_mode} → {job_type}")

            return job_type, {
                # File location (required)
                'blob_name': file_name,
                'container_name': request.container_name,

                # Output location
                'output_folder': output_folder,

                # STAC metadata
                'collection_id': collection_id,
                'stac_item_id': stac_item_id,
                'access_level': request.access_level.value,  # E4 Phase 1: enum → string

                # DDH identifiers (Platform passthrough)
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,

                # Processing options
                'output_tier': opts.get('output_tier', 'analysis'),
                'target_crs': opts.get('crs'),
                'raster_type': opts.get('raster_type', 'auto')
            }

    # ========================================================================
    # POINTCLOUD, MESH_3D, TABULAR - Phase 2
    # ========================================================================
    elif data_type in [DataType.POINTCLOUD, DataType.MESH_3D, DataType.TABULAR]:
        raise NotImplementedError(f"{data_type.value} processing coming in Phase 2")

    else:
        raise ValueError(f"Unsupported data type: {data_type}")


def _translate_single_raster(
    request: PlatformRequest,
    cfg
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH request to single raster job parameters.

    Used by /api/platform/raster endpoint.
    Returns process_raster_v2 by default, or process_raster_docker if
    processing_mode="docker" is specified.

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance

    Returns:
        Tuple of (job_type, job_parameters)
        - job_type: 'process_raster_v2' or 'process_raster_docker'
    """
    platform_cfg = cfg.platform
    opts = request.processing_options

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # Collection ID: use override from processing_options if provided (22 JAN 2026)
    # Otherwise auto-generate from DDH identifiers
    collection_id = opts.get('collection_id')
    if not collection_id:
        collection_id = platform_cfg.generate_stac_collection_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )
    else:
        logger.info(f"  Using collection_id override: {collection_id}")

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # file_name is guaranteed to be a string by endpoint validation
    file_name = request.file_name
    if isinstance(file_name, list):
        file_name = file_name[0]

    # Determine processing mode (21 JAN 2026)
    # Default to Docker if docker_worker_enabled, else Function App
    # Explicit processing_mode in options overrides the default
    from config import get_app_mode_config
    app_mode_config = get_app_mode_config()

    processing_mode = opts.get('processing_mode')
    if processing_mode:
        # Explicit override from client
        processing_mode = processing_mode.lower()
        if processing_mode not in ('docker', 'function'):
            logger.warning(f"  Unknown processing_mode '{processing_mode}', using default")
            processing_mode = None

    if not processing_mode:
        if app_mode_config.docker_worker_enabled:
            # Default to Docker when worker is enabled (phasing out Function App raster processing)
            processing_mode = 'docker'
        else:
            # Fallback to Function App when no Docker worker
            processing_mode = 'function'

    if processing_mode == 'docker':
        job_type = 'process_raster_docker'
    else:
        job_type = 'process_raster_v2'

    logger.info(f"  Raster processing mode: {processing_mode} → {job_type}")

    return job_type, {
        # File location (required)
        'blob_name': file_name,
        'container_name': request.container_name,

        # Output location
        'output_folder': output_folder,

        # STAC metadata
        'collection_id': collection_id,
        'stac_item_id': stac_item_id,
        'access_level': request.access_level.value,  # E4 Phase 1: enum → string

        # DDH identifiers (Platform passthrough)
        'dataset_id': request.dataset_id,
        'resource_id': request.resource_id,
        'version_id': request.version_id,

        # Processing options
        'output_tier': opts.get('output_tier', 'analysis'),
        'target_crs': opts.get('crs'),
        'raster_type': opts.get('raster_type', 'auto')
    }


def _translate_raster_collection(
    request: PlatformRequest,
    cfg
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH request to raster collection job parameters.

    Used by /api/platform/raster-collection endpoint.
    Always returns process_raster_collection_v2 (MosaicJSON pipeline).

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance

    Returns:
        Tuple of ('process_raster_collection_v2', job_parameters)
    """
    platform_cfg = cfg.platform
    opts = request.processing_options

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # Collection ID: use override from processing_options if provided (22 JAN 2026)
    # Otherwise auto-generate from DDH identifiers
    collection_id = opts.get('collection_id')
    if not collection_id:
        collection_id = platform_cfg.generate_stac_collection_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )
    else:
        logger.info(f"  Using collection_id override: {collection_id}")

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    return 'process_raster_collection_v2', {
        # File location (required)
        'container_name': request.container_name,
        'blob_list': request.file_name,  # Already validated as list by endpoint

        # Output location
        'output_folder': output_folder,

        # STAC metadata (MosaicJSON schema)
        'collection_id': collection_id,
        'stac_item_id': stac_item_id,
        'collection_description': request.description,
        'access_level': request.access_level.value,  # E4 Phase 1: enum → string

        # DDH identifiers (Platform passthrough)
        'dataset_id': request.dataset_id,
        'resource_id': request.resource_id,
        'version_id': request.version_id,

        # Processing options
        'output_tier': opts.get('output_tier', 'analysis'),
        'target_crs': opts.get('crs')
    }


# ============================================================================
# JOB CREATION & SUBMISSION
# ============================================================================

# Size-based job fallback routing (04 DEC 2025, updated 12 JAN 2026)
# When validator fails with size error, automatically try alternate job type
# process_raster_docker has no fallback - it handles all sizes
RASTER_JOB_FALLBACKS = {
    'process_raster_v2': 'process_large_raster_v2',
    'process_large_raster_v2': 'process_raster_v2',
    # Docker job handles all sizes - no automatic fallback needed
    # 'process_raster_docker': None,
}


def _create_and_submit_job(
    job_type: str,
    parameters: Dict[str, Any],
    platform_request_id: str
) -> Optional[str]:
    """
    Create CoreMachine job and submit to Service Bus queue.

    Uses the job class's validation method to:
    1. Validate parameters against schema
    2. Run pre-flight resource validators (e.g., blob_exists_with_size)
    3. Generate deterministic job ID
    4. Create job record and queue message

    Supports automatic fallback for size-based routing (04 DEC 2025):
    If validator fails with size-related error (too_large/too_small),
    automatically retries with fallback job type from RASTER_JOB_FALLBACKS.

    Args:
        job_type: CoreMachine job type (e.g., 'process_vector', 'process_raster_v2')
        parameters: Job parameters translated from DDH request
        platform_request_id: Platform request ID for tracking

    Returns:
        job_id if successful, None if failed

    Raises:
        ValueError: If pre-flight validation fails (e.g., blob doesn't exist)
    """
    import hashlib
    import uuid
    from jobs import ALL_JOBS

    def _try_create_job(current_job_type: str, job_params: Dict[str, Any], allow_fallback: bool = True) -> str:
        """
        Attempt to create and submit job, with optional fallback on size validation failure.

        Args:
            current_job_type: Job type to attempt
            job_params: Parameters including platform tracking
            allow_fallback: Whether to try fallback job on size error (prevents infinite recursion)

        Returns:
            job_id if successful

        Raises:
            ValueError: If validation fails and no fallback available/applicable
        """
        job_class = ALL_JOBS.get(current_job_type)
        if not job_class:
            raise ValueError(f"Unknown job type: {current_job_type}")

        try:
            # Run validation (includes resource validators like blob_exists_with_size)
            # This will raise ValueError if validation fails
            validated_params = job_class.validate_job_parameters(job_params)
            logger.info(f"✅ Pre-flight validation passed for {current_job_type}")

            # Generate deterministic job ID
            # Remove platform metadata for ID generation (so same CoreMachine params = same job)
            clean_params = {k: v for k, v in validated_params.items() if not k.startswith('_')}
            canonical = f"{current_job_type}:{json.dumps(clean_params, sort_keys=True)}"
            job_id = hashlib.sha256(canonical.encode()).hexdigest()

            # Create job record with correct total_stages from job class
            job_record = JobRecord(
                job_id=job_id,
                job_type=current_job_type,
                status=JobStatus.QUEUED,
                stage=1,
                total_stages=len(job_class.stages),  # FIX: Set from job class stages definition
                parameters=validated_params,
                metadata={
                    'platform_request': platform_request_id,
                    'created_by': 'platform_trigger'
                }
            )

            # Store in database
            job_repo = JobRepository()
            job_repo.create_job(job_record)

            # Record JOB_CREATED event (25 JAN 2026 - Job Monitor Interface)
            try:
                from infrastructure import JobEventRepository
                from core.models.job_event import JobEventType, JobEventStatus

                event_repo = JobEventRepository()
                event_repo.record_job_event(
                    job_id=job_id,
                    event_type=JobEventType.JOB_CREATED,
                    event_status=JobEventStatus.SUCCESS,
                    event_data={
                        'job_type': current_job_type,
                        'total_stages': len(job_class.stages),
                        'platform_request_id': platform_request_id
                    }
                )
            except Exception as event_err:
                logger.warning(f"⚠️ Failed to record JOB_CREATED event: {event_err}")

            # Submit to Service Bus
            service_bus = ServiceBusRepository()
            queue_message = JobQueueMessage(
                job_id=job_id,
                job_type=current_job_type,
                parameters=validated_params,
                stage=1,
                correlation_id=str(uuid.uuid4())[:8]
            )

            message_id = service_bus.send_message(
                config.service_bus_jobs_queue,
                queue_message
            )

            logger.info(f"Submitted job {job_id[:16]} to queue (message_id: {message_id})")
            return job_id

        except ValueError as e:
            error_msg = str(e).lower()

            # Check if this is a size-related validation failure
            is_size_error = any(pattern in error_msg for pattern in [
                'too_large', 'too large', 'exceeds maximum size',
                'too_small', 'too small', '< 100mb'
            ])

            fallback_job = RASTER_JOB_FALLBACKS.get(current_job_type)

            if is_size_error and fallback_job and allow_fallback:
                logger.info(f"📐 Size validation failed for {current_job_type}, trying fallback: {fallback_job}")
                # Retry with fallback job type (allow_fallback=False prevents infinite loop)
                return _try_create_job(fallback_job, job_params, allow_fallback=False)

            # Re-raise if not a size error, no fallback available, or already tried fallback
            raise

    try:
        # Add platform tracking to parameters
        job_params = {
            **parameters,
            '_platform_request_id': platform_request_id
        }

        return _try_create_job(job_type, job_params, allow_fallback=True)

    except ValueError as e:
        # Re-raise validation errors - caller will handle as 400 Bad Request
        logger.warning(f"Pre-flight validation failed: {e}")
        raise

    except Exception as e:
        logger.error(f"Failed to create/submit job: {e}", exc_info=True)
        return None
