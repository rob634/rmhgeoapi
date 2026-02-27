# ============================================================================
# PLATFORM SUBMIT HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/submit (unified endpoint)
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine jobs
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# UPDATED: 21 FEB 2026 - V0.9 Asset/Release two-entity architecture
# EXPORTS: platform_request_submit
# DEPENDENCIES: services.platform_translation, services.platform_job_submit,
#               services.asset_service
# ============================================================================
"""
Platform Submit HTTP Triggers.

Handles DDH request submission for vector and raster data processing.

All submissions now use the unified POST /api/platform/submit endpoint.
The separate /raster and /raster-collection endpoints were deprecated and
return 410 Gone (handlers in platform_bp.py).

V0.9 Architecture (21 FEB 2026):
    Asset = stable identity container (platform_id + dataset_id + resource_id)
    Release = versioned artifact with processing + approval lifecycle

    Submit flow:
    1. find_or_create_asset() - Get or create stable identity
    2. get_or_overwrite_release() - Create draft or return existing
    3. create_and_submit_job() - Create CoreMachine job
    4. link_job_to_release() - Link job to release

Exports:
    platform_request_submit: Generic POST /api/platform/submit
"""

import json
import logging
from typing import Dict, Any

import azure.functions as func
from triggers.http_base import parse_request_json

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "platform_submit")

# Import config
from config import get_config, generate_platform_request_id

# Import infrastructure
from infrastructure import PlatformRepository

# Import core models
from core.models import ApiRequest, DataType, PlatformRequest

# Import services (extracted from trigger_platform.py)
from services.platform_translation import (
    translate_to_coremachine,
    normalize_data_type,
    generate_table_name,
    generate_stac_item_id,
)
from services.platform_job_submit import (
    create_and_submit_job,
)
from services.platform_response import (
    success_response,
    error_response,
    validation_error,
    not_implemented_error,
    submit_accepted,
    idempotent_response,
)

# V0.9 Entity Architecture - Asset/Release Service (21 FEB 2026)
from services.asset_service import AssetService, ReleaseStateError
from core.models.asset import ClearanceState


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
        req_body = parse_request_json(req)
        platform_req = PlatformRequest(**req_body)

        # Check dry_run parameter
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
        logger.info(f"  Version: {platform_req.version_id or '(draft)'}")
        logger.info(f"  Data type: {platform_req.data_type.value}")
        logger.info(f"  Operation: {platform_req.operation.value}")

        overwrite = platform_req.processing_options.overwrite

        # Extract optional clearance_state (V0.9 - 24 FEB 2026)
        # Most assets start UNCLEARED and are cleared at approval time.
        # Optional: specify clearance at submit for pre-approved data sources.
        clearance_level = None
        clearance_level_str = req_body.get('clearance_state') or req_body.get('clearance_level') or req_body.get('access_level')
        if clearance_level_str:
            try:
                clearance_level = ClearanceState(clearance_level_str.lower())
                logger.info(f"  Clearance state specified at submit: {clearance_level.value}")
            except ValueError:
                logger.warning(f"  Invalid clearance_state '{clearance_level_str}', ignoring")
                clearance_level = None

        # Translate DDH request to CoreMachine job parameters
        job_type, job_params = translate_to_coremachine(platform_req, config)

        # GPKG layer preflight warning (24 FEB 2026)
        submit_warnings = []
        if platform_req.data_type == DataType.VECTOR:
            file_name = platform_req.file_name
            if isinstance(file_name, list):
                file_name = file_name[0]
            file_ext = file_name.split('.')[-1].lower()

            if file_ext == 'csv':
                # CSV geometry parameter preflight (26 FEB 2026)
                # Reject early if no geometry pathway specified — saves time vs failing deep in ETL
                proc_opts = platform_req.processing_options
                has_wkt = getattr(proc_opts, 'wkt_column', None)
                has_lat = getattr(proc_opts, 'lat_column', None)
                has_lon = getattr(proc_opts, 'lon_column', None)

                if not has_wkt and not (has_lat and has_lon):
                    if has_lat and not has_lon:
                        return validation_error(
                            "CSV file requires both lat_column and lon_column, but only lat_column was provided. "
                            "Add lon_column to processing_options."
                        )
                    elif has_lon and not has_lat:
                        return validation_error(
                            "CSV file requires both lat_column and lon_column, but only lon_column was provided. "
                            "Add lat_column to processing_options."
                        )
                    else:
                        return validation_error(
                            "CSV file requires geometry parameters in processing_options. "
                            "Provide either: (1) wkt_column for WKT geometry, or "
                            "(2) both lat_column and lon_column for point coordinates."
                        )

            if file_ext == 'gpkg':
                requested_layer = getattr(platform_req.processing_options, 'layer_name', None)
                if not requested_layer:
                    submit_warnings.append({
                        "type": "GPKG_NO_LAYER_SPECIFIED",
                        "message": (
                            "No layer_name specified for GeoPackage file. "
                            "The first layer will be used. If your file contains multiple layers, "
                            "specify processing_options.layer_name to choose a specific layer."
                        )
                    })

        logger.info(f"  Translated to job_type: {job_type}")

        # Pre-flight STAC collection check (26 FEB 2026 — informational only)
        collection_id = job_params.get('collection_id')
        if collection_id:
            try:
                from infrastructure.pgstac_repository import PgStacRepository
                pgstac = PgStacRepository()
                if pgstac.collection_exists(collection_id):
                    logger.info(f"  Adding to existing STAC collection: {collection_id}")
                else:
                    logger.info(f"  Will create new STAC collection: {collection_id}")
            except Exception:
                pass  # Non-fatal: informational only

        # =====================================================================
        # V0.9 ENTITY ARCHITECTURE: Asset/Release (21 FEB 2026)
        # =====================================================================
        # 1. Asset = stable identity container (platform_id + dataset_id + resource_id)
        # 2. Release = versioned artifact with processing + approval lifecycle
        # 3. No lineage validation at submit — implicit in V0.9
        # 4. No revoke-first workflow — handled by get_or_overwrite_release()
        # =====================================================================
        try:
            asset_service = AssetService()

            # Step 1: Find or create Asset (stable identity container)
            asset, asset_op = asset_service.find_or_create_asset(
                platform_id="ddh",
                dataset_id=platform_req.dataset_id,
                resource_id=platform_req.resource_id,
                data_type=platform_req.data_type.value,
            )
            logger.info(f"  Asset {asset_op}: {asset.asset_id[:16]}")

            # Step 2: Handle dry_run — return validation result WITHOUT creating Release
            # dry_run only needs asset lookup + job_type translation to confirm validity.
            if dry_run:
                return func.HttpResponse(
                    json.dumps({
                        "valid": True,
                        "dry_run": True,
                        "request_id": request_id,
                        "would_create_job_type": job_type,
                        "asset_id": asset.asset_id,
                        "data_type": platform_req.data_type.value,
                    }),
                    status_code=200,
                    mimetype="application/json"
                )

            # Step 3: Get or overwrite Release
            try:
                release, release_op = asset_service.get_or_overwrite_release(
                    asset_id=asset.asset_id,
                    overwrite=overwrite,
                    stac_item_id=generate_stac_item_id(platform_req.dataset_id, platform_req.resource_id, platform_req.version_id),
                    stac_collection_id=job_params.get('collection_id', platform_req.dataset_id.lower()),
                    blob_path=None,  # Set by handler after COG is created (silver path, not bronze input)
                    # table_name removed (26 FEB 2026) → written to app.release_tables after ordinal finalization
                    request_id=request_id,
                    suggested_version_id=platform_req.version_id,
                )
            except ReleaseStateError as e:
                return error_response(str(e), "ReleaseStateError", status_code=409)

            logger.info(f"  Release {release_op}: {release.release_id[:16]}")

            # Step 4: Handle idempotent case (existing draft, no overwrite)
            if release_op == "existing":
                # Detect orphaned release: prior attempt created Release but job creation failed.
                # Return explicit error instead of "success" with empty job_id. (26 FEB 2026)
                if not release.job_id:
                    logger.warning(
                        f"Orphaned release {release.release_id[:16]} — "
                        f"no job_id, prior job creation likely failed"
                    )
                    return error_response(
                        "Prior submission created a release but job creation failed. "
                        "Resubmit with processing_options.overwrite=true to retry.",
                        "OrphanedReleaseError",
                        status_code=409
                    )
                return idempotent_response(
                    request_id=request_id,
                    job_id=release.job_id,
                    hint="Use processing_options.overwrite=true to force reprocessing"
                )

            # Step 5: Add release_id and asset_id to job params
            job_params['release_id'] = release.release_id
            job_params['asset_id'] = asset.asset_id  # Keep for backward compat during migration

            # Step 6: Override output_folder with version ordinal (22 FEB 2026)
            # Each ordinal gets its own folder — no collision between versions.
            # Before this fix, all drafts wrote to …/draft/… which meant v2
            # overwrote v1's COG when both existed as approved+draft.
            if 'output_folder' in job_params and release.version_ordinal:
                platform_cfg = get_config().platform
                job_params['output_folder'] = platform_cfg.generate_raster_output_folder(
                    platform_req.dataset_id,
                    platform_req.resource_id,
                    str(release.version_ordinal)
                )
                logger.info(f"  Output folder (ordinal): {job_params['output_folder']}")

            # Sync stac_item_id from release to job params (may be disambiguated for new versions)
            if release.stac_item_id and 'stac_item_id' in job_params:
                job_params['stac_item_id'] = release.stac_item_id

            # Update title to reflect ordinal instead of "(draft)"
            if 'title' in job_params:
                job_params['title'] = f"{platform_req.dataset_id} / {platform_req.resource_id} (ordinal {release.version_ordinal})"

            # Step 6b: Finalize ordinal-based names for drafts (22 FEB 2026)
            # Translation generates placeholder "draft" names (ordinal not yet known).
            # Now that the release exists with a reserved ordinal, overwrite with
            # stable ordinal-based names (e.g. *_ord1 instead of *_draft).
            if not platform_req.version_id and release.version_ordinal:
                ordinal = release.version_ordinal

                if (
                    platform_req.data_type.value == 'vector'
                    and not getattr(platform_req.processing_options, 'table_name', None)
                ):
                    # Vector: finalize table_name AND stac_item_id
                    final_table = generate_table_name(
                        platform_req.dataset_id, platform_req.resource_id,
                        version_ordinal=ordinal
                    )
                    final_stac = generate_stac_item_id(
                        platform_req.dataset_id, platform_req.resource_id,
                        version_ordinal=ordinal
                    )
                    job_params['table_name'] = final_table
                    job_params['stac_item_id'] = final_stac

                    # Write table name to junction table (single source of truth)
                    from infrastructure import ReleaseTableRepository
                    release_table_repo = ReleaseTableRepository()
                    release_table_repo.create(
                        release_id=release.release_id,
                        table_name=final_table,
                        geometry_type='UNKNOWN',  # Set by ETL handler after processing
                        table_role='primary',
                    )

                    # Still update stac_item_id on release (not a table field)
                    asset_service.update_physical_outputs(
                        release.release_id, stac_item_id=final_stac
                    )
                    logger.info(f"  Finalized vector names: table={final_table}, stac={final_stac} (ord={ordinal})")

                elif platform_req.data_type.value == 'raster':
                    # Raster: finalize stac_item_id (output_folder already handled in Step 6)
                    final_stac = generate_stac_item_id(
                        platform_req.dataset_id, platform_req.resource_id,
                        version_ordinal=ordinal
                    )
                    job_params['stac_item_id'] = final_stac

                    asset_service.update_physical_outputs(
                        release.release_id, stac_item_id=final_stac
                    )
                    logger.info(f"  Finalized raster stac_item_id: {final_stac} (ord={ordinal})")

        except ReleaseStateError:
            raise  # Already handled above, but guard against re-wrapping
        except Exception as asset_err:
            # FATAL: Asset/Release creation is required for platform jobs
            # Without release_id, approval/reject/revoke workflows fail with 404
            logger.error(f"Asset/Release creation failed: {asset_err}", exc_info=True)
            return error_response(
                f"Failed to create asset/release record: {asset_err}",
                "AssetCreationError",
                status_code=500
            )

        # Create CoreMachine job
        job_id = create_and_submit_job(job_type, job_params, request_id)

        if not job_id:
            raise RuntimeError("Failed to create CoreMachine job")

        # Link job to release (sets job_id and resets processing_status)
        asset_service.link_job_to_release(release.release_id, job_id)

        # Store thin tracking record (request_id -> job_id)
        platform_repo = PlatformRepository()
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id or "",  # Empty string for drafts (DB column NOT NULL)
            job_id=job_id,
            data_type=platform_req.data_type.value,
            asset_id=asset.asset_id,
            platform_id="ddh"
        )
        platform_repo.create_request(api_request)

        logger.info(f"Platform request submitted: {request_id[:16]} -> job {job_id[:16]}")

        return submit_accepted(
            request_id=request_id,
            job_id=job_id,
            job_type=job_type,
            message="Platform request submitted. CoreMachine job created.",
            **({"warnings": submit_warnings} if submit_warnings else {})
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
