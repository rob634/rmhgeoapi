# ============================================================================
# PLATFORM SUBMIT HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/submit, /raster, /raster-collection
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine jobs
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# EXPORTS: platform_request_submit, platform_raster_submit, platform_raster_collection_submit
# DEPENDENCIES: services.platform_translation, services.platform_job_submit
# ============================================================================
"""
Platform Submit HTTP Triggers.

Handles DDH request submission for vector and raster data processing.

Exports:
    platform_request_submit: Generic POST /api/platform/submit
    platform_raster_submit: Single raster POST /api/platform/raster
    platform_raster_collection_submit: Collection POST /api/platform/raster-collection
"""

import json
import logging
from typing import Dict, Any

import azure.functions as func

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "platform_submit")

# Import config
from config import get_config, generate_platform_request_id
config = get_config()

# Import infrastructure
from infrastructure import PlatformRepository

# Import core models
from core.models import ApiRequest, PlatformRequest

# Import services (extracted from trigger_platform.py)
from services.platform_translation import (
    translate_to_coremachine,
    translate_single_raster,
    translate_raster_collection,
    normalize_data_type,
    generate_table_name,
    generate_stac_item_id,
)
from services.platform_job_submit import (
    create_and_submit_job,
    generate_unpublish_request_id,
)
from services.platform_response import (
    success_response,
    error_response,
    validation_error,
    not_implemented_error,
    submit_accepted,
    idempotent_response,
)


# ============================================================================
# OVERWRITE HELPER
# ============================================================================

def _handle_overwrite_unpublish(existing_request: ApiRequest, platform_repo: PlatformRepository) -> None:
    """
    Handle unpublish before overwrite reprocessing (21 JAN 2026, fixed 29 JAN 2026).

    When processing_options.overwrite=true is specified and a request already exists,
    this function:
    1. Determines the data type from the existing request
    2. For RASTER: Submits an unpublish job (async) to delete COG blobs
    3. For VECTOR: Just deletes platform request - handler does table drop directly
    4. Deletes the existing platform request record

    IMPORTANT (29 JAN 2026): Vector overwrite does NOT submit unpublish job.
    The vector_docker_etl handler drops the table directly when overwrite=true.
    Submitting an async unpublish job creates a race condition where the unpublish
    job can delete the STAC item AFTER the new ETL job creates it.

    Args:
        existing_request: The existing ApiRequest record to overwrite
        platform_repo: PlatformRepository instance

    Raises:
        RuntimeError: If unpublish job creation fails (raster only)
        Exception: Any error from unpublish process
    """
    data_type = normalize_data_type(existing_request.data_type)
    logger.info(f"Overwrite: data_type={data_type}, request_id={existing_request.request_id[:16]}")

    # Generate unpublish parameters based on data type
    if data_type == "vector":
        # VECTOR: Do NOT submit unpublish job - handler drops table directly (29 JAN 2026)
        # This avoids race condition where unpublish job deletes STAC after new ETL creates it
        table_name = generate_table_name(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        logger.info(f"Overwrite vector: skipping unpublish job - handler will drop table {table_name} directly")

    elif data_type == "raster":
        stac_item_id = generate_stac_item_id(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        collection_id = existing_request.dataset_id
        unpublish_request_id = generate_unpublish_request_id("raster", stac_item_id)

        # Submit unpublish job (NOT dry_run - we want to actually delete)
        job_params = {
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "dry_run": False,
            "force_approved": True  # Allow unpublishing even if approved
        }
        job_id = create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

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
# HTTP HANDLERS
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
                    return error_response(
                        f"Overwrite failed: could not unpublish existing outputs. {unpublish_err}",
                        "OverwriteError",
                        status_code=500,
                        existing_request_id=request_id,
                        existing_job_id=existing.job_id
                    )
            else:
                # Normal idempotent behavior: return existing request
                logger.info(f"Request already exists: {request_id[:16]} → job {existing.job_id[:16]}")
                return idempotent_response(
                    request_id=request_id,
                    job_id=existing.job_id,
                    hint="Use processing_options.overwrite=true to force reprocessing"
                )

        # Translate DDH request to CoreMachine job parameters
        job_type, job_params = translate_to_coremachine(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create CoreMachine job
        job_id = create_and_submit_job(job_type, job_params, request_id)

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

        return submit_accepted(
            request_id=request_id,
            job_id=job_id,
            job_type=job_type,
            message="Platform request submitted. CoreMachine job created."
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return validation_error(str(e))

    except NotImplementedError as e:
        logger.warning(f"Not implemented: {e}")
        return not_implemented_error(str(e))

    except Exception as e:
        logger.error(f"Platform request failed: {e}", exc_info=True)
        return error_response(str(e), type(e).__name__)


# ============================================================================
# DEDICATED RASTER ENDPOINTS (05 DEC 2025)
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
            return validation_error(
                "file_name must be a string for single raster endpoint. Use /api/platform/raster-collection for multiple files."
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
            return idempotent_response(request_id=request_id, job_id=existing.job_id)

        # Translate to CoreMachine job (always single raster path)
        job_type, job_params = translate_single_raster(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create job (with fallback for large files)
        job_id = create_and_submit_job(job_type, job_params, request_id)

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

        return submit_accepted(
            request_id=request_id,
            job_id=job_id,
            job_type=job_type,
            message="Single raster request submitted."
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return validation_error(str(e))

    except Exception as e:
        logger.error(f"Single raster request failed: {e}", exc_info=True)
        return error_response(str(e), type(e).__name__)


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
            return validation_error(
                "file_name must be a list for raster collection endpoint. Use /api/platform/raster for single files."
            )

        if len(file_name) < 2:
            return validation_error(
                "Raster collection requires at least 2 files. Use /api/platform/raster for single files."
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
            return idempotent_response(request_id=request_id, job_id=existing.job_id)

        # Translate to CoreMachine job (always collection path)
        job_type, job_params = translate_raster_collection(platform_req, config)

        logger.info(f"  Translated to job_type: {job_type}")

        # Create job
        job_id = create_and_submit_job(job_type, job_params, request_id)

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

        return submit_accepted(
            request_id=request_id,
            job_id=job_id,
            job_type=job_type,
            message=f"Raster collection request submitted ({len(file_name)} files).",
            file_count=len(file_name)
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return validation_error(str(e))

    except Exception as e:
        logger.error(f"Raster collection request failed: {e}", exc_info=True)
        return error_response(str(e), type(e).__name__)
