# ============================================================================
# PLATFORM UNPUBLISH HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - POST /api/platform/unpublish
# PURPOSE: Consolidated unpublish endpoint for vector and raster data
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# EXPORTS: platform_unpublish
# DEPENDENCIES: services.platform_translation, services.platform_job_submit
# ============================================================================
"""
Platform Unpublish HTTP Triggers.

Handles unpublish requests for vector (PostGIS tables) and raster (STAC items).
Auto-detects data type from platform request record.

Exports:
    platform_unpublish: Consolidated POST /api/platform/unpublish
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

import azure.functions as func
from triggers.http_base import parse_request_json

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "platform_unpublish")

# Import config
from config import get_config
config = get_config()

# Import infrastructure
from infrastructure import PlatformRepository, JobRepository
from infrastructure.pgstac_repository import PgStacRepository

# Import core models
from core.models import ApiRequest
from core.models.enums import JobStatus

# Import services (extracted from trigger_platform.py)
from services.platform_translation import (
    normalize_data_type,
    generate_table_name,
    generate_stac_item_id,
    get_unpublish_params_from_request,
)
from services.platform_job_submit import (
    create_and_submit_job,
    generate_unpublish_request_id,
)
from services.platform_response import (
    success_response,
    error_response,
    validation_error,
    idempotent_response,
    unpublish_accepted,
)

# V0.9 Entity Architecture - Asset/Release split (21 FEB 2026)
# Release revocation uses inline imports in the unpublish block below


# ============================================================================
# CONSOLIDATED UNPUBLISH ENDPOINT (21 JAN 2026)
# ============================================================================

def platform_unpublish(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for consolidated unpublish via Platform layer (21 JAN 2026).

    POST /api/platform/unpublish

    Auto-detects data type (vector or raster) from platform request record or
    direct parameters. Consolidates /unpublish/vector and /unpublish/raster.

    Parameters:
        dry_run (bool): Preview mode. Defaults to true if omitted — no data
            is deleted. Set dry_run=false explicitly to perform actual deletion.

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
        req_body = parse_request_json(req)
        dry_run = req_body.get('dry_run', True)  # Defaults to preview mode — caller must set false to delete

        # Resolve data type and parameters
        data_type, resolved_params, original_request = _resolve_unpublish_data_type(req_body)

        if not data_type:
            return validation_error(
                "Could not determine data type. Provide: request_id, job_id, DDH identifiers (dataset_id, resource_id, version_id), or explicit data_type with identifiers."
            )

        logger.info(f"Unpublish: data_type={data_type}, dry_run={dry_run}, params={resolved_params}")

        # Delegate to appropriate handler based on data type.
        # data_type is a normalized string from normalize_data_type(), not a
        # DataType enum — string comparison is intentional here (V-11).
        if data_type == "vector":
            response = _execute_vector_unpublish(
                table_name=resolved_params.get('table_name'),
                schema_name=req_body.get('schema_name', 'geo'),
                dry_run=dry_run,
                force_approved=req_body.get('force_approved', False),
                original_request=original_request
            )
        elif data_type == "raster":
            # Check for collection mode
            if req_body.get('delete_collection') and resolved_params.get('collection_id'):
                response = _handle_collection_unpublish(
                    collection_id=resolved_params['collection_id'],
                    dry_run=dry_run,
                    force_approved=req_body.get('force_approved', False),
                    platform_repo=PlatformRepository()
                )
            else:
                response = _execute_raster_unpublish(
                    stac_item_id=resolved_params.get('stac_item_id'),
                    collection_id=resolved_params.get('collection_id'),
                    dry_run=dry_run,
                    force_approved=req_body.get('force_approved', False),
                    original_request=original_request
                )
        elif data_type == "zarr":
            response = _execute_zarr_unpublish(
                stac_item_id=resolved_params.get('stac_item_id'),
                collection_id=resolved_params.get('collection_id'),
                dry_run=dry_run,
                force_approved=req_body.get('force_approved', False),
                delete_data_files=req_body.get('delete_data_files', True),
                original_request=original_request
            )
        else:
            return validation_error(f"Unknown data type: {data_type}. Must be 'vector', 'raster', or 'zarr'.")

        # =====================================================================
        # V0.9: Revoke release AFTER successful job submission (28 FEB 2026)
        # =====================================================================
        # Moved from before delegation to after — COMPETE Fix 2.
        # Previous location revoked the release before job submission,
        # meaning if job submission failed, the release was revoked but
        # artifacts (blobs, tables) remained orphaned with no cleanup path.
        # Now revocation only happens after the job is confirmed submitted
        # (HTTP 202). Stage 3 also revokes atomically with STAC delete
        # as defense-in-depth (services/unpublish_handlers.py:765-780).
        # =====================================================================
        if response.status_code == 202 and original_request and not dry_run:
            _try_revoke_release(original_request, req_body)

        return response

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return validation_error(str(e))

    except Exception as e:
        logger.error(f"Platform unpublish failed: {e}", exc_info=True)
        return error_response(str(e), type(e).__name__)


# ============================================================================
# RELEASE REVOCATION HELPER (28 FEB 2026 — COMPETE Fix 2)
# ============================================================================

def _try_revoke_release(original_request: ApiRequest, req_body: dict) -> None:
    """
    Revoke an approved release after successful job submission.

    Called AFTER the unpublish job is confirmed submitted (HTTP 202).
    Non-fatal: logs warning and continues if revocation fails, because
    Stage 3 (delete_stac_and_audit) also revokes atomically with STAC
    delete as defense-in-depth.

    Args:
        original_request: The original platform request (has job_id)
        req_body: HTTP request body (for deleted_by field)
    """
    try:
        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()

        release = None
        if original_request.job_id:
            release = release_repo.get_by_job_id(original_request.job_id)

        if release and release.approval_state.value == 'approved':
            deleted_by = req_body.get('deleted_by', 'platform_unpublish')
            from services.asset_approval_service import AssetApprovalService
            approval_svc = AssetApprovalService()
            approval_svc.revoke_release(
                release_id=release.release_id,
                revoker=deleted_by or 'system',
                reason='Unpublished via platform endpoint'
            )
            logger.info(f"Revoked release {release.release_id[:16]}...")
    except Exception as e:
        # Non-fatal: Stage 3 handler will revoke atomically with STAC delete
        logger.warning(f"Eager release revocation failed (Stage 3 will handle): {e}")


# ============================================================================
# RESOLUTION HELPERS
# ============================================================================

def _resolve_unpublish_data_type(req_body: dict) -> Tuple[Optional[str], dict, Optional[ApiRequest]]:
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
            data_type = normalize_data_type(original_request.data_type)
            resolved_params = get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 2: By job_id
    job_id = req_body.get('job_id')
    if job_id:
        original_request = platform_repo.get_request_by_job(job_id)
        if original_request:
            data_type = normalize_data_type(original_request.data_type)
            resolved_params = get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 3: By DDH identifiers
    dataset_id = req_body.get('dataset_id')
    resource_id = req_body.get('resource_id')
    version_id = req_body.get('version_id')
    if dataset_id and resource_id and version_id is not None:
        original_request = platform_repo.get_request_by_ddh_ids(dataset_id, resource_id, version_id)
        if original_request:
            data_type = normalize_data_type(original_request.data_type)
            resolved_params = get_unpublish_params_from_request(original_request, data_type)
            return data_type, resolved_params, original_request

    # Option 4: Explicit data_type with direct identifiers (cleanup mode)
    explicit_data_type = req_body.get('data_type')
    if explicit_data_type:
        data_type = normalize_data_type(explicit_data_type)
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
        elif data_type == "zarr":
            stac_item_id = req_body.get('stac_item_id')
            collection_id = req_body.get('collection_id')
            if stac_item_id and collection_id:
                resolved_params = {'stac_item_id': stac_item_id, 'collection_id': collection_id}
                return data_type, resolved_params, None

    # Fallback: Try to infer from direct parameters
    if req_body.get('table_name'):
        return "vector", {'table_name': req_body['table_name']}, None
    if req_body.get('stac_item_id') and req_body.get('collection_id'):
        return "raster", {'stac_item_id': req_body['stac_item_id'], 'collection_id': req_body['collection_id']}, None

    return None, {}, None


# ============================================================================
# EXECUTION HELPERS
# ============================================================================

def _execute_vector_unpublish(
    table_name: str,
    schema_name: str,
    dry_run: bool,
    force_approved: bool,
    original_request: Optional[ApiRequest]
) -> func.HttpResponse:
    """Execute vector unpublish job."""
    if not table_name:
        return validation_error("table_name is required for vector unpublish")

    # Dry run: preview only — no job, no tracking record (20 FEB 2026)
    if dry_run:
        logger.info(f"Vector unpublish dry_run: table={schema_name}.{table_name}")
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "dry_run": True,
                "data_type": "vector",
                "would_delete": {
                    "table": f"{schema_name}.{table_name}",
                },
                "dataset_id": original_request.dataset_id if original_request else None,
                "resource_id": original_request.resource_id if original_request else None,
                "message": "Dry run - no changes made. Set dry_run=false to execute."
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    platform_repo = PlatformRepository()
    unpublish_request_id = generate_unpublish_request_id("vector", table_name)

    # Check for existing with retry support (matches raster pattern)
    existing = platform_repo.get_request(unpublish_request_id)
    is_retry = False
    if existing:
        job_repo = JobRepository()
        existing_job = job_repo.get_job(existing.job_id)

        if existing_job and existing_job.status == JobStatus.FAILED:
            is_retry = True
            logger.info(f"Previous vector unpublish failed, allowing retry: {unpublish_request_id[:16]}")
        else:
            job_status = existing_job.status.value if existing_job else "unknown"
            return idempotent_response(
                request_id=unpublish_request_id,
                job_id=existing.job_id,
                job_status=job_status,
                data_type="vector"
            )

    # Submit job
    job_params = {
        "table_name": table_name,
        "schema_name": schema_name,
        "dry_run": dry_run,
        "force_approved": force_approved
    }
    job_id = create_and_submit_job("unpublish_vector", job_params, unpublish_request_id)

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
    created_request = platform_repo.create_request(api_request, is_retry=is_retry)

    retry_msg = f" (retry #{created_request.retry_count})" if is_retry else ""
    logger.info(f"Vector unpublish submitted{retry_msg}: {unpublish_request_id[:16]} → job {job_id[:16]}")

    return unpublish_accepted(
        request_id=unpublish_request_id,
        job_id=job_id,
        data_type="vector",
        dry_run=dry_run,
        message=f"Vector unpublish job submitted{retry_msg} (dry_run={dry_run})",
        is_retry=is_retry,
        table_name=table_name
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
        return validation_error("stac_item_id and collection_id are required for raster unpublish")

    # Dry run: preview only — no job, no tracking record (20 FEB 2026)
    if dry_run:
        logger.info(f"Raster unpublish dry_run: item={stac_item_id}, collection={collection_id}")
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "dry_run": True,
                "data_type": "raster",
                "would_delete": {
                    "stac_item_id": stac_item_id,
                    "collection_id": collection_id,
                },
                "dataset_id": original_request.dataset_id if original_request else None,
                "resource_id": original_request.resource_id if original_request else None,
                "message": "Dry run - no changes made. Set dry_run=false to execute."
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    platform_repo = PlatformRepository()
    unpublish_request_id = generate_unpublish_request_id("raster", stac_item_id)

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
            return idempotent_response(
                request_id=unpublish_request_id,
                job_id=existing.job_id,
                job_status=job_status,
                data_type="raster"
            )

    # Submit job
    job_params = {
        "stac_item_id": stac_item_id,
        "collection_id": collection_id,
        "dry_run": dry_run,
        "force_approved": force_approved
    }
    job_id = create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

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

    return unpublish_accepted(
        request_id=unpublish_request_id,
        job_id=job_id,
        data_type="raster",
        dry_run=dry_run,
        message=f"Raster unpublish job submitted{retry_msg} (dry_run={dry_run})",
        is_retry=is_retry,
        stac_item_id=stac_item_id,
        collection_id=collection_id
    )


def _execute_zarr_unpublish(
    stac_item_id: str,
    collection_id: str,
    dry_run: bool,
    force_approved: bool,
    delete_data_files: bool,
    original_request: Optional[ApiRequest]
) -> func.HttpResponse:
    """
    Execute zarr unpublish job.

    Implements spec Component 5: _execute_zarr_unpublish.
    Follows the raster pattern exactly:
    - Dry-run (dry_run=True): Return HTTP 200 with preview. NO job created.
    - Live (dry_run=False): Generate request_id, check existing (allow retry on FAILED),
      create_and_submit_job, track ApiRequest, return HTTP 202.

    Args:
        stac_item_id: STAC item to unpublish
        collection_id: STAC collection the item belongs to
        dry_run: If True, preview only (no deletions)
        force_approved: If True, allow unpublishing approved items
        delete_data_files: If True, also delete copied NetCDF data files
        original_request: Original platform request (if resolved from DDH identifiers)

    Returns:
        Azure Functions HttpResponse (200 for dry_run, 202 for live)
    """
    if not stac_item_id or not collection_id:
        return validation_error("stac_item_id and collection_id are required for zarr unpublish")

    # Dry run: preview only -- no job, no tracking record
    if dry_run:
        logger.info(f"Zarr unpublish dry_run: item={stac_item_id}, collection={collection_id}")
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "dry_run": True,
                "data_type": "zarr",
                "would_delete": {
                    "stac_item_id": stac_item_id,
                    "collection_id": collection_id,
                    "delete_data_files": delete_data_files,
                },
                "dataset_id": original_request.dataset_id if original_request else None,
                "resource_id": original_request.resource_id if original_request else None,
                "message": "Dry run - no changes made. Set dry_run=false to execute."
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    platform_repo = PlatformRepository()
    unpublish_request_id = generate_unpublish_request_id("zarr", stac_item_id)

    # Check for existing with retry support (follows raster pattern)
    existing = platform_repo.get_request(unpublish_request_id)
    is_retry = False
    if existing:
        job_repo = JobRepository()
        existing_job = job_repo.get_job(existing.job_id)

        if existing_job and existing_job.status == JobStatus.FAILED:
            is_retry = True
            logger.info(f"Previous zarr unpublish job failed, allowing retry: {unpublish_request_id[:16]}")
        else:
            job_status = existing_job.status.value if existing_job else "unknown"
            return idempotent_response(
                request_id=unpublish_request_id,
                job_id=existing.job_id,
                job_status=job_status,
                data_type="zarr"
            )

    # Submit job
    job_params = {
        "stac_item_id": stac_item_id,
        "collection_id": collection_id,
        "dry_run": dry_run,
        "delete_data_files": delete_data_files,
        "force_approved": force_approved
    }
    job_id = create_and_submit_job("unpublish_zarr", job_params, unpublish_request_id)

    if not job_id:
        raise RuntimeError("Failed to create unpublish_zarr job")

    # Track request
    api_request = ApiRequest(
        request_id=unpublish_request_id,
        dataset_id=original_request.dataset_id if original_request else collection_id,
        resource_id=original_request.resource_id if original_request else stac_item_id,
        version_id=original_request.version_id if original_request else "cleanup",
        job_id=job_id,
        data_type="unpublish_zarr"
    )
    created_request = platform_repo.create_request(api_request, is_retry=is_retry)

    retry_msg = f" (retry #{created_request.retry_count})" if is_retry else ""
    logger.info(f"Zarr unpublish submitted{retry_msg}: {unpublish_request_id[:16]} -> job {job_id[:16]}")

    return unpublish_accepted(
        request_id=unpublish_request_id,
        job_id=job_id,
        data_type="zarr",
        dry_run=dry_run,
        message=f"Zarr unpublish job submitted{retry_msg} (dry_run={dry_run})",
        is_retry=is_retry,
        stac_item_id=stac_item_id,
        collection_id=collection_id
    )


def _handle_collection_unpublish(
    collection_id: str,
    dry_run: bool,
    force_approved: bool,
    platform_repo: PlatformRepository
) -> func.HttpResponse:
    """
    Handle collection-level unpublish by submitting jobs for all items.

    Queries all items in the collection and submits an unpublish_raster job
    for each item. Jobs run in parallel via Service Bus.

    Args:
        collection_id: STAC collection ID to unpublish
        dry_run: If True, preview only (no deletions)
        force_approved: If True, revoke approvals and unpublish approved items
        platform_repo: PlatformRepository instance

    Returns:
        HttpResponse with summary of submitted jobs
    """
    logger.info(f"Collection-level unpublish: {collection_id} (dry_run={dry_run})")

    # Query all items in the collection
    pgstac_repo = PgStacRepository()
    item_ids = pgstac_repo.get_collection_item_ids(collection_id)

    if not item_ids:
        logger.warning(f"Collection '{collection_id}' has no items to unpublish")
        return validation_error(
            f"Collection '{collection_id}' has no items to unpublish",
            collection_id=collection_id
        )

    logger.info(f"Found {len(item_ids)} items in collection '{collection_id}'")

    # Dry run: preview only — no jobs, no tracking records (20 FEB 2026)
    if dry_run:
        logger.info(f"Collection unpublish dry_run: {len(item_ids)} items in '{collection_id}'")
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "dry_run": True,
                "mode": "collection",
                "collection_id": collection_id,
                "total_items": len(item_ids),
                "would_delete": {
                    "stac_item_ids": item_ids[:50],
                    "collection_id": collection_id,
                },
                "message": f"Dry run - would unpublish {len(item_ids)} items from '{collection_id}'. Set dry_run=false to execute."
            }),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    # Revoke individual releases before submitting cleanup jobs
    from infrastructure import ReleaseRepository
    from core.models.asset import ApprovalState
    release_repo = ReleaseRepository()
    revoked_count = 0

    for stac_item_id in item_ids:
        release = release_repo.get_by_stac_item_id(stac_item_id)
        if release and release.approval_state == ApprovalState.APPROVED:
            success = release_repo.update_revocation(
                release_id=release.release_id,
                revoked_by='system:collection_unpublish',
                revocation_reason=f'Collection-level unpublish of {collection_id}'
            )
            if success:
                revoked_count += 1

    if revoked_count > 0:
        logger.info(f"Revoked {revoked_count} releases for collection '{collection_id}'")

    # Submit unpublish job for each item
    submitted_jobs = []
    skipped_jobs = []
    retried_jobs = []
    job_repo = JobRepository()

    for stac_item_id in item_ids:
        unpublish_request_id = generate_unpublish_request_id("raster", stac_item_id)

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
            "force_approved": force_approved
        }

        job_id = create_and_submit_job("unpublish_raster", job_params, unpublish_request_id)

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
