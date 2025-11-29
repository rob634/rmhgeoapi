# ============================================================================
# CLAUDE CONTEXT - PLATFORM API REQUEST HTTP TRIGGER (THIN TRACKING)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Platform Anti-Corruption Layer (simplified 22 NOV 2025)
# PURPOSE: Translate DDH requests to CoreMachine jobs (1:1 mapping, no orchestration)
# LAST_REVIEWED: 22 NOV 2025
# EXPORTS: platform_request_submit (HTTP trigger function)
# INTERFACES: None
# PYDANTIC_MODELS: PlatformRequest, ApiRequest
# DEPENDENCIES: azure-functions, psycopg, azure-servicebus, config
# SOURCE: HTTP requests from external applications (DDH)
# SCOPE: Platform layer - Anti-Corruption Layer between DDH and CoreMachine
# VALIDATION: Pydantic models + PlatformConfig validation
# PATTERNS: Anti-Corruption Layer, Thin Tracking, Parameter Translation
# ENTRY_POINTS: POST /api/platform/submit
# INDEX:
#   - Imports: Line 35
#   - HTTP Handler: Line 80
#   - Parameter Translation: Line 180
# ============================================================================

"""
Platform Request HTTP Trigger - Thin Tracking Pattern (22 NOV 2025)

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

Supported Workflows (CREATE operation):
    - VECTOR: process_vector (3-stage: prepare → upload → finalize) [28 NOV 2025]
    - RASTER (single): process_raster_v2 (3-stage: validate → COG → STAC) [28 NOV 2025]
    - RASTER (collection): process_raster_collection (4-stage: validate → COGs → MosaicJSON → STAC)
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
        "job_type": "process_raster",
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
    # VECTOR CREATE → ingest_vector
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
    # RASTER CREATE → process_raster_v2 or process_raster_collection
    # ========================================================================
    # Updated 28 NOV 2025: Single rasters now use process_raster_v2 (mixin pattern)
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
            # Multiple rasters → process_raster_collection
            return 'process_raster_collection', {
                # File location
                'container_name': request.container_name,
                'blob_list': request.file_name,  # Already a list

                # Output location
                'output_folder': output_folder,

                # STAC metadata
                'collection_id': collection_id,
                'stac_item_id': stac_item_id,
                'service_name': request.service_name,
                'description': request.description,
                'tags': request.tags,
                'access_level': request.access_level,

                # DDH identifiers
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,

                # Processing options
                'output_tier': opts.get('output_tier', 'analysis'),
                'target_crs': opts.get('crs'),
                'nodata_value': opts.get('nodata_value')
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


# ============================================================================
# JOB CREATION & SUBMISSION
# ============================================================================

def _create_and_submit_job(
    job_type: str,
    parameters: Dict[str, Any],
    platform_request_id: str
) -> Optional[str]:
    """
    Create CoreMachine job and submit to Service Bus queue.

    Args:
        job_type: CoreMachine job type (e.g., 'ingest_vector', 'process_raster')
        parameters: Job parameters translated from DDH request
        platform_request_id: Platform request ID for tracking

    Returns:
        job_id if successful, None if failed
    """
    import hashlib
    import uuid

    try:
        # Add platform tracking to parameters
        job_params = {
            **parameters,
            '_platform_request_id': platform_request_id
        }

        # Generate deterministic job ID
        # Remove platform metadata for ID generation (so same CoreMachine params = same job)
        clean_params = {k: v for k, v in job_params.items() if not k.startswith('_')}
        canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}"
        job_id = hashlib.sha256(canonical.encode()).hexdigest()

        # Create job record
        job_record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            parameters=job_params,
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
            job_type=job_type,
            parameters=job_params,
            stage=1,
            correlation_id=str(uuid.uuid4())[:8]
        )

        message_id = service_bus.send_message(
            config.service_bus_jobs_queue,
            queue_message
        )

        logger.info(f"Submitted job {job_id[:16]} to queue (message_id: {message_id})")
        return job_id

    except Exception as e:
        logger.error(f"Failed to create/submit job: {e}", exc_info=True)
        return None
