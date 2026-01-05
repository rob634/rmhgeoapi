# ============================================================================
# PLATFORM REQUEST HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/*
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine jobs
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: platform_request_submit, platform_raster_submit, platform_raster_collection_submit, platform_unpublish_vector, platform_unpublish_raster
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
    platform_unpublish_vector: Vector unpublish HTTP trigger for POST /api/platform/unpublish/vector
    platform_unpublish_raster: Raster unpublish HTTP trigger for POST /api/platform/unpublish/raster
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
        "service_name": "Aerial Imagery Site Alpha",
        "access_level": "OUO"
    }

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
                    "monitor_url": f"/api/platform/status/{request_id}"
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
                "monitor_url": f"/api/platform/status/{request_id}"
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
    Platform routes to process_raster_v2, with automatic fallback to
    process_large_raster_v2 if file exceeds size threshold.

    Request Body:
    {
        "dataset_id": "aerial-imagery-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "container_name": "bronze-rasters",
        "file_name": "aerial-alpha.tif",
        "service_name": "Aerial Imagery Site Alpha",
        "access_level": "OUO"
    }

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
                    "monitor_url": f"/api/platform/status/{request_id}"
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
                "monitor_url": f"/api/platform/status/{request_id}"
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
        "service_name": "Aerial Tiles Site Alpha",
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
                    "monitor_url": f"/api/platform/status/{request_id}"
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
                "monitor_url": f"/api/platform/status/{request_id}"
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
# Platform layer for unpublish operations - translates DDH identifiers to
# CoreMachine unpublish jobs. Supports three input modes:
#   1. By request_id (from original submission)
#   2. By DDH identifiers (dataset_id, resource_id, version_id)
#   3. Cleanup mode (direct table_name or stac_item_id)
# ============================================================================

def platform_unpublish_vector(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for vector unpublish via Platform layer.

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
    logger.info("Platform unpublish vector endpoint called")

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
                    "monitor_url": f"/api/platform/status/{unpublish_request_id}"
                }),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        # Submit unpublish_vector job
        job_params = {
            "table_name": table_name,
            "schema_name": req_body.get('schema_name', 'geo'),
            "dry_run": dry_run
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
                "monitor_url": f"/api/platform/status/{unpublish_request_id}"
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
    HTTP trigger for raster unpublish via Platform layer.

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
    logger.info("Platform unpublish raster endpoint called")

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
                        "monitor_url": f"/api/platform/status/{unpublish_request_id}"
                    }),
                    status_code=200,
                    headers={"Content-Type": "application/json"}
                )

        # Submit unpublish_raster job
        job_params = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "dry_run": dry_run
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
                "monitor_url": f"/api/platform/status/{unpublish_request_id}"
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
    platform_repo: 'PlatformRepository'
) -> func.HttpResponse:
    """
    Handle collection-level unpublish by submitting jobs for all items.

    Queries all items in the collection and submits an unpublish_raster job
    for each item. Jobs run in parallel via Service Bus.

    Args:
        collection_id: STAC collection ID to unpublish
        dry_run: If True, preview only (no deletions)
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
            "dry_run": dry_run
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
    # VECTOR CREATE → process_vector (idempotent DELETE+INSERT pattern)
    # ========================================================================
    if data_type == DataType.VECTOR:
        # Generate PostGIS table name from DDH IDs
        table_name = platform_cfg.generate_vector_table_name(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

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
        converter_params = {}
        opts = request.processing_options
        if opts.get('lon_column') or opts.get('lat_column') or opts.get('wkt_column'):
            converter_params = {
                'lon_column': opts.get('lon_column'),
                'lat_column': opts.get('lat_column'),
                'wkt_column': opts.get('wkt_column')
            }

        return 'process_vector', {
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
            'service_name': request.service_name,
            'description': request.description,
            'tags': request.tags,
            'access_level': request.access_level,

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
        # Generate output paths from DDH IDs
        output_folder = platform_cfg.generate_raster_output_folder(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        collection_id = platform_cfg.generate_stac_collection_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        opts = request.processing_options

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
                'access_level': request.access_level,

                # DDH identifiers (Platform passthrough)
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,

                # Processing options
                'output_tier': opts.get('output_tier', 'analysis'),
                'target_crs': opts.get('crs')
            }
        else:
            # Single raster → process_raster_v2 (mixin pattern, 28 NOV 2025)
            file_name = request.file_name
            if isinstance(file_name, list):
                file_name = file_name[0]

            return 'process_raster_v2', {
                # File location (required)
                'blob_name': file_name,
                'container_name': request.container_name,

                # Output location
                'output_folder': output_folder,

                # STAC metadata
                'collection_id': collection_id,
                'stac_item_id': stac_item_id,
                'access_level': request.access_level,

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
    Always returns process_raster_v2 (fallback to large handled by _create_and_submit_job).

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance

    Returns:
        Tuple of ('process_raster_v2', job_parameters)
    """
    platform_cfg = cfg.platform

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    collection_id = platform_cfg.generate_stac_collection_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    opts = request.processing_options

    # file_name is guaranteed to be a string by endpoint validation
    file_name = request.file_name
    if isinstance(file_name, list):
        file_name = file_name[0]

    return 'process_raster_v2', {
        # File location (required)
        'blob_name': file_name,
        'container_name': request.container_name,

        # Output location
        'output_folder': output_folder,

        # STAC metadata
        'collection_id': collection_id,
        'stac_item_id': stac_item_id,
        'access_level': request.access_level,

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

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    collection_id = platform_cfg.generate_stac_collection_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    opts = request.processing_options

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
        'access_level': request.access_level,

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

# Size-based job fallback routing (04 DEC 2025)
# When validator fails with size error, automatically try alternate job type
RASTER_JOB_FALLBACKS = {
    'process_raster_v2': 'process_large_raster_v2',
    'process_large_raster_v2': 'process_raster_v2',
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
