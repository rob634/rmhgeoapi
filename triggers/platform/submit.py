# ============================================================================
# PLATFORM SUBMIT HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/submit (unified endpoint)
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine jobs
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# UPDATED: 09 FEB 2026 - Approval-aware overwrite validation
# EXPORTS: platform_request_submit
# DEPENDENCIES: services.platform_translation, services.platform_job_submit
# ============================================================================
"""
Platform Submit HTTP Triggers.

Handles DDH request submission for vector and raster data processing.

All submissions now use the unified POST /api/platform/submit endpoint.
The separate /raster and /raster-collection endpoints were deprecated and
return 410 Gone (handlers in platform_bp.py).

Exports:
    platform_request_submit: Generic POST /api/platform/submit
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

# V0.8 Entity Architecture - Asset Service (29 JAN 2026)
from services.asset_service import AssetService, AssetExistsError
from core.models.asset import ClearanceState

# V0.8 Release Control - Version validation (31 JAN 2026)
from services.platform_validation import validate_version_lineage


# ============================================================================
# OVERWRITE HELPER
# ============================================================================

def _handle_overwrite_unpublish(existing_request: ApiRequest, platform_repo: PlatformRepository) -> None:
    """
    Handle overwrite for platform requests (28 JAN 2026 - no async unpublish).

    When processing_options.overwrite=true is specified and a request already exists,
    this function deletes the platform request record. The handler manages cleanup.

    ARCHITECTURE (28 JAN 2026):
    Both vector and raster handlers now handle overwrite internally:
    - Vector: Handler drops table directly when overwrite=true
    - Raster: Handler compares source checksums and handles cleanup

    This eliminates race conditions where async unpublish jobs could delete
    STAC items AFTER new ETL jobs created them.

    Args:
        existing_request: The existing ApiRequest record to overwrite
        platform_repo: PlatformRepository instance
    """
    data_type = normalize_data_type(existing_request.data_type)
    logger.info(f"Overwrite: data_type={data_type}, request_id={existing_request.request_id[:16]}")

    # Log what the handler will do (informational only)
    if data_type == "vector":
        table_name = generate_table_name(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        logger.info(f"Overwrite vector: handler will drop table {table_name} directly")

    elif data_type == "raster":
        stac_item_id = generate_stac_item_id(
            existing_request.dataset_id,
            existing_request.resource_id,
            existing_request.version_id
        )
        logger.info(f"Overwrite raster: handler will compare checksums for {stac_item_id}")
        # Handler will:
        # - Same checksum + metadata changes → update STAC only
        # - Same checksum + no changes → no-op
        # - Different checksum → full reprocess, delete old COG

    else:
        raise ValueError(f"Unknown data_type for overwrite: {data_type}")

    # Delete the existing platform request record so the new one can be created
    _delete_platform_request(existing_request.request_id, platform_repo)
    logger.info(f"Overwrite: deleted platform request {existing_request.request_id[:16]} (handler manages cleanup)")


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

        # V0.8 Release Control: Check dry_run parameter (31 JAN 2026)
        dry_run = req.params.get('dry_run', '').lower() == 'true'
        if dry_run:
            logger.info("  dry_run=true: Validation-only mode")

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

        # Extract optional clearance_level (V0.8 - 29 JAN 2026)
        # Most assets start UNCLEARED and are cleared at approval time.
        # Optional: specify clearance at submit for pre-approved data sources.
        clearance_level = None
        clearance_level_str = req_body.get('clearance_level') or req_body.get('access_level')
        if clearance_level_str:
            try:
                clearance_level = ClearanceState(clearance_level_str.lower())
                logger.info(f"  Clearance level specified at submit: {clearance_level.value}")
            except ValueError:
                logger.warning(f"  Invalid clearance_level '{clearance_level_str}', ignoring")
                clearance_level = None

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

        # =====================================================================
        # V0.8 ENTITY ARCHITECTURE: Create/Update GeospatialAsset (29 JAN 2026)
        # V0.8 DDH Migration (30 JAN 2026): Uses platform_id + platform_refs
        # =====================================================================
        # Asset is created BEFORE job runs. This ensures:
        # 1. Asset exists for all requests (even failed jobs)
        # 2. Deterministic asset_id for concurrent request handling
        # 3. Advisory locks prevent race conditions
        # =====================================================================
        try:
            asset_service = AssetService()
            # Get submitter for audit trail (optional - from request or B2B app header)
            submitted_by = req_body.get('submitted_by') or req.headers.get('X-Submitted-By')

            # Build platform_refs from DDH request fields
            platform_refs = {
                "dataset_id": platform_req.dataset_id,
                "resource_id": platform_req.resource_id,
                "version_id": platform_req.version_id
            }

            # =====================================================================
            # V0.8 RELEASE CONTROL: Version Lineage Validation (31 JAN 2026)
            # V0.8.16: Approval-aware overwrite validation (09 FEB 2026)
            # Validate previous_version_id before allowing job creation.
            # Prevents race conditions where two clients submit v2.0 concurrently.
            # Blocks overwrite if asset is APPROVED (must revoke first).
            # =====================================================================
            validation_result = validate_version_lineage(
                platform_id="ddh",
                platform_refs=platform_refs,
                previous_version_id=platform_req.previous_version_id,
                asset_service=asset_service,
                overwrite=overwrite  # V0.8.16: Pass overwrite for approval check
            )

            if dry_run:
                # Return validation result without creating job
                # job_type already translated above (line 264)
                return func.HttpResponse(
                    json.dumps({
                        "valid": validation_result.valid,
                        "dry_run": True,
                        "request_id": request_id,
                        "would_create_job_type": job_type,
                        "lineage_state": {
                            "lineage_id": validation_result.lineage_id,
                            "lineage_exists": validation_result.lineage_exists,
                            "current_latest": validation_result.current_latest
                        },
                        "validation": {
                            "data_type_detected": platform_req.data_type.value,
                            "previous_version_valid": validation_result.valid
                        },
                        "warnings": validation_result.warnings,
                        "suggested_params": validation_result.suggested_params
                    }),
                    status_code=200,
                    mimetype="application/json"
                )

            # Not dry_run - enforce validation before creating job
            if not validation_result.valid:
                logger.warning(f"Version validation failed: {validation_result.warnings}")
                return validation_error(validation_result.warnings[0])

            # =====================================================================
            # V0.8.4.1 RELEASE CONTROL: Lineage wiring (30 JAN 2026)
            # Use lineage state from validation result
            # =====================================================================
            lineage_id = validation_result.lineage_id
            version_ordinal = validation_result.suggested_params.get('version_ordinal', 1)
            previous_asset_id = None

            # Get previous_asset_id from current_latest if exists
            if validation_result.current_latest:
                previous_asset_id = validation_result.current_latest.get('asset_id')

            logger.info(f"  Lineage: {lineage_id[:16]}... ordinal={version_ordinal}, prev={previous_asset_id[:16] if previous_asset_id else 'None'}")

            asset, asset_operation = asset_service.create_or_update_asset(
                platform_id="ddh",
                platform_refs=platform_refs,
                data_type=platform_req.data_type.value,
                stac_item_id=job_params.get('stac_item_id', generate_stac_item_id(
                    platform_req.dataset_id,
                    platform_req.resource_id,
                    platform_req.version_id
                )),
                stac_collection_id=job_params.get('collection_id', platform_req.dataset_id.lower()),
                table_name=job_params.get('table_name') if platform_req.data_type.value == 'vector' else None,
                blob_path=job_params.get('blob_name') if platform_req.data_type.value == 'raster' else None,
                overwrite=overwrite,
                clearance_level=clearance_level,
                submitted_by=submitted_by,
                # V0.8.4.1 Release Control - lineage parameters
                lineage_id=lineage_id,
                version_ordinal=version_ordinal,
                previous_asset_id=previous_asset_id,
                is_latest=True
            )
            logger.info(f"  Asset {asset_operation}: {asset.asset_id[:16]} (revision {asset.revision}, lineage ordinal {version_ordinal})")

            # Add asset_id to job params for handler to link back
            job_params['asset_id'] = asset.asset_id

        except AssetExistsError as asset_err:
            # Asset exists and overwrite=False - this shouldn't happen if we handled
            # overwrite above, but log and continue with existing asset
            logger.warning(f"Asset exists (continuing with existing): {asset_err}")
            job_params['asset_id'] = asset_err.asset_id

        except Exception as asset_err:
            # Non-fatal: log warning but continue with job creation
            # Asset linking can be retried later
            logger.warning(f"Failed to create asset (continuing without): {asset_err}")

        # Create CoreMachine job
        job_id = create_and_submit_job(job_type, job_params, request_id)

        if not job_id:
            raise RuntimeError("Failed to create CoreMachine job")

        # Store thin tracking record (request_id → job_id)
        # V0.8.11: Include asset_id and platform_id FKs (08 FEB 2026)
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id,
            job_id=job_id,
            data_type=platform_req.data_type.value,
            asset_id=job_params.get('asset_id'),  # FK to GeospatialAsset
            platform_id="ddh"  # FK to Platform registry
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
# DEPRECATED ENDPOINTS REMOVED (09 FEB 2026)
# ============================================================================
# The following endpoints have been consolidated into /api/platform/submit:
#   - platform_raster_submit (POST /api/platform/raster)
#   - platform_raster_collection_submit (POST /api/platform/raster-collection)
#
# These routes now return 410 Gone with migration instructions.
# See platform_bp.py for the deprecation handlers.
# ============================================================================
