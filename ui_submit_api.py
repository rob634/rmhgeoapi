"""
Submit Proxy API for DAG Brain Admin UI.

All endpoints use direct Python service calls (no HTTP proxy).

Endpoints:
    GET  /ui/api/containers   - List storage containers (direct BlobRepository)
    GET  /ui/api/files        - List files in container (direct BlobRepository)
    POST /ui/api/validate     - dry_run validation via direct service calls
    POST /ui/api/submit       - Job submission via direct service calls
"""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from infrastructure.blob import BlobRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["submit-proxy"])


@router.get("/containers")
async def list_containers(zone: str = "bronze"):
    """List storage containers for a zone."""
    try:
        repo = BlobRepository.for_zone(zone)
        containers = repo.list_containers()
        return JSONResponse(content={
            "zone": zone,
            "containers": containers or [],
        })
    except Exception as e:
        logger.warning(f"Container listing failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/files")
async def list_files(
    zone: str = "bronze",
    container: str = "",
    prefix: str = "",
    data_type: str = "raster",
    limit: int = 250,
):
    """List files in a container, filtered by data type extension."""
    if not container:
        return JSONResponse(content={"error": "container required"}, status_code=400)

    raster_exts = {'.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5'}
    vector_exts = {'.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip'}
    exts = vector_exts if data_type == "vector" else raster_exts

    try:
        repo = BlobRepository.for_zone(zone)
        blobs = repo.list_blobs(container, prefix=prefix, limit=limit * 2)

        filtered = []
        for blob in blobs:
            name = (blob.get("name") or "").lower()
            if any(name.endswith(ext) for ext in exts):
                filtered.append(blob)
                if len(filtered) >= limit:
                    break

        return JSONResponse(content={"files": filtered})
    except Exception as e:
        logger.warning(f"File listing failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/validate")
async def validate_submission(request: Request):
    """Validate a platform submission (dry_run only — no DB writes)."""
    try:
        body = await request.json()

        from config import generate_platform_request_id
        from core.models.platform import PlatformRequest
        from services.platform_translation import translate_to_coremachine

        # Pydantic validation
        platform_req = PlatformRequest(**body)

        # Translation validates that we can route this request
        job_type, _job_params = translate_to_coremachine(platform_req)

        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id,
        )

        return JSONResponse(content={
            "success": True,
            "valid": True,
            "dry_run": True,
            "request_id": request_id,
            "would_create_job_type": job_type,
            "data_type": platform_req.data_type.value,
        })

    except ValidationError as e:
        clean_errors = []
        for err in e.errors():
            msg = err.get('msg', '')
            loc = ' -> '.join(str(l) for l in err.get('loc', []))
            clean_errors.append(f"{loc}: {msg}" if loc else msg)
        error_msg = "; ".join(clean_errors)
        logger.warning(f"Validate: Pydantic error: {error_msg}")
        return JSONResponse(
            content={"success": False, "valid": False, "error": error_msg},
            status_code=400,
        )

    except (ValueError, NotImplementedError) as e:
        logger.warning(f"Validate: {e}")
        return JSONResponse(
            content={"success": False, "valid": False, "error": str(e)},
            status_code=400,
        )

    except Exception as e:
        logger.error(f"Validate failed: {e}", exc_info=True)
        return JSONResponse(
            content={"success": False, "valid": False, "error": str(e)},
            status_code=500,
        )


@router.post("/submit")
async def submit_job(request: Request):
    """Submit a platform job via direct service calls."""
    try:
        body = await request.json()

        from config import get_config, generate_platform_request_id
        from infrastructure import PlatformRepository
        from core.models import ApiRequest
        from core.models.platform import PlatformRequest
        from services.platform_translation import translate_to_coremachine, generate_stac_item_id
        from services.platform_job_submit import create_and_submit_job
        from services.asset_service import AssetService, ReleaseStateError

        # Pydantic validation
        platform_req = PlatformRequest(**body)

        # Generate deterministic request ID (idempotent)
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id,
        )

        # Check for existing request (idempotent guard)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(request_id)
        if existing:
            return JSONResponse(
                content={
                    "success": True,
                    "request_id": request_id,
                    "job_id": existing.job_id,
                    "message": "Submission already processed for these parameters.",
                    "hint": "Use processing_options.overwrite=true to force reprocessing",
                },
                status_code=200,
            )

        # Translate DDH request to CoreMachine job type + parameters
        job_type, job_params = translate_to_coremachine(platform_req)

        # Resolve overwrite flag (processing_options may be dict or Pydantic model)
        proc_opts = platform_req.processing_options
        if isinstance(proc_opts, dict):
            overwrite = bool(proc_opts.get('overwrite', False))
        else:
            overwrite = bool(getattr(proc_opts, 'overwrite', False))

        # V0.9 Asset/Release flow
        asset_service = AssetService()

        # Step 1: Find or create Asset (stable identity container)
        asset, asset_op = asset_service.find_or_create_asset(
            platform_id=platform_req.client_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            data_type=platform_req.data_type.value,
        )
        logger.info(f"Asset {asset_op}: {asset.asset_id[:16]}")

        # Step 2: Get or overwrite Release
        try:
            release, release_op = asset_service.get_or_overwrite_release(
                asset_id=asset.asset_id,
                overwrite=overwrite,
                stac_item_id=generate_stac_item_id(
                    platform_req.dataset_id,
                    platform_req.resource_id,
                    platform_req.version_id,
                ),
                stac_collection_id=job_params.get('collection_id', platform_req.dataset_id.lower()),
                blob_path=None,
                request_id=request_id,
                suggested_version_id=platform_req.version_id,
            )
        except ReleaseStateError as e:
            return JSONResponse(
                content={"success": False, "error": str(e), "error_type": "ReleaseStateError"},
                status_code=409,
            )

        logger.info(f"Release {release_op}: {release.release_id[:16]}")

        # Step 3: Handle idempotent case (existing draft, no overwrite)
        if release_op == "existing" and release.job_id:
            return JSONResponse(
                content={
                    "success": True,
                    "request_id": request_id,
                    "job_id": release.job_id,
                    "message": "Submission already processed for these parameters.",
                    "hint": "Use processing_options.overwrite=true to force reprocessing",
                },
                status_code=200,
            )

        # Step 4: Attach release_id and asset_id to job params
        job_params['release_id'] = release.release_id
        job_params['asset_id'] = asset.asset_id

        # Step 5: Submit job
        try:
            job_id = create_and_submit_job(job_type, job_params, request_id)
        except (ValueError, RuntimeError) as job_err:
            # Compensating action: clean up orphaned release
            try:
                asset_service.cleanup_orphaned_release(release.release_id, asset.asset_id)
            except Exception as cleanup_err:
                logger.critical(
                    f"ORPHAN_CLEANUP_FAILED: release {release.release_id[:16]}...: {cleanup_err}"
                )
            raise

        # Step 6: Link job to release
        try:
            asset_service.link_job_to_release(release.release_id, job_id)
        except Exception as link_err:
            logger.critical(
                f"LINK_JOB_FAILED: job {job_id[:16]}... created but link to "
                f"release {release.release_id[:16]}... failed: {link_err}. "
                f"MANUAL: UPDATE app.asset_releases SET job_id='{job_id}' "
                f"WHERE release_id='{release.release_id}'"
            )
            # Fall through — job IS running

        # Step 7: Store thin tracking record
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id or "",
            job_id=job_id,
            data_type=platform_req.data_type.value,
            asset_id=asset.asset_id,
            platform_id=platform_req.client_id,
        )
        platform_repo.create_request(api_request)

        logger.info(f"Platform request submitted: {request_id[:16]} -> job {job_id[:16]}")

        return JSONResponse(
            content={
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "job_type": job_type,
                "monitor_url": f"/api/platform/status/{request_id}",
                "message": "Platform request submitted. Job created.",
            },
            status_code=202,
        )

    except ValidationError as e:
        clean_errors = []
        for err in e.errors():
            msg = err.get('msg', '')
            loc = ' -> '.join(str(l) for l in err.get('loc', []))
            clean_errors.append(f"{loc}: {msg}" if loc else msg)
        error_msg = "; ".join(clean_errors)
        logger.warning(f"Submit: Pydantic error: {error_msg}")
        return JSONResponse(
            content={"success": False, "error": error_msg},
            status_code=400,
        )

    except (ValueError, NotImplementedError) as e:
        logger.warning(f"Submit: {e}")
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=400,
        )

    except Exception as e:
        logger.error(f"Submit failed: {e}", exc_info=True)
        return JSONResponse(
            content={"success": False, "error": "An internal error occurred. Check server logs."},
            status_code=500,
        )
