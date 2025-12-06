# ============================================================================
# CLAUDE CONTEXT - PLATFORM API REQUEST HTTP TRIGGER (THIN TRACKING)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Platform Anti-Corruption Layer (updated 05 DEC 2025)
# PURPOSE: Translate DDH requests to CoreMachine jobs (1:1 mapping, no orchestration)
# LAST_REVIEWED: 05 DEC 2025
# EXPORTS: platform_request_submit, platform_raster_submit, platform_raster_collection_submit
# INTERFACES: None
# PYDANTIC_MODELS: PlatformRequest, ApiRequest
# DEPENDENCIES: azure-functions, psycopg, azure-servicebus, config
# SOURCE: HTTP requests from external applications (DDH)
# SCOPE: Platform layer - Anti-Corruption Layer between DDH and CoreMachine
# VALIDATION: Pydantic models + PlatformConfig validation
# PATTERNS: Anti-Corruption Layer, Thin Tracking, Parameter Translation
# ENTRY_POINTS:
#   - POST /api/platform/submit (generic - detects data type)
#   - POST /api/platform/raster (single raster with size-based fallback)
#   - POST /api/platform/raster-collection (multiple rasters → MosaicJSON)
# INDEX:
#   - Imports: Line 45
#   - Generic HTTP Handler: Line 96
#   - Raster Endpoints: Line 238
#   - Parameter Translation: Line 526
#   - Job Creation: Line 850
# ============================================================================

"""
Platform Request HTTP Trigger - Thin Tracking Pattern (Updated 05 DEC 2025)

SIMPLIFIED ARCHITECTURE:
    Platform is an Anti-Corruption Layer (ACL) that:
    1. Accepts DDH requests (dataset_id, resource_id, version_id, etc.)
    2. Translates DDH params → CoreMachine job params
    3. Creates ONE CoreMachine job per request (1:1 mapping)
    4. Stores thin tracking record (request_id → job_id)
    5. Returns request_id for DDH status polling

    NO orchestration logic - CoreMachine handles job stages/tasks.
    NO job chaining - each Platform request = one CoreMachine job.
    NO callbacks - status delegated to CoreMachine.

ENDPOINTS:
    Generic (auto-detects data type):
        POST /api/platform/submit

    Dedicated Raster Endpoints (05 DEC 2025):
        POST /api/platform/raster            → Single file (size-based fallback)
        POST /api/platform/raster-collection → Multiple files (MosaicJSON pipeline)

    DDH explicitly chooses raster endpoint based on single vs multiple files.
    Platform handles size-based routing (small vs large) via fallback pattern.

Supported Workflows (CREATE operation):
    - VECTOR: process_vector (3-stage: prepare → upload → finalize) [28 NOV 2025]
    - RASTER (single): process_raster_v2 (3-stage: validate → COG → STAC) [28 NOV 2025]
    - RASTER (single, large): process_large_raster_v2 (auto-fallback for >1GB) [04 DEC 2025]
    - RASTER (collection): process_raster_collection_v2 (4-stage: validate → COGs → MosaicJSON → STAC) [04 DEC 2025]
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

            # Create job record
            job_record = JobRecord(
                job_id=job_id,
                job_type=current_job_type,
                status=JobStatus.QUEUED,
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
