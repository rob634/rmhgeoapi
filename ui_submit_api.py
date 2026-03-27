"""
Submit Proxy API for DAG Brain Admin UI.

Storage endpoints use direct BlobRepository calls (no HTTP proxy).
Validate and submit endpoints proxy to the Function App (orchestrator).

Endpoints:
    GET  /ui/api/containers   - List storage containers (direct BlobRepository)
    GET  /ui/api/files        - List files in container (direct BlobRepository)
    POST /ui/api/validate     - dry_run validation via Platform API
    POST /ui/api/submit       - Job submission via Platform API
"""
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

from infrastructure.blob import BlobRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["submit-proxy"])

PROXY_TIMEOUT = 30.0


def _get_orchestrator_url() -> str:
    """Get orchestrator URL, raising if not configured."""
    url = os.environ.get("ORCHESTRATOR_URL", "").rstrip("/")
    if not url:
        raise ValueError("ORCHESTRATOR_URL not set — cannot proxy to orchestrator")
    return url


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
    """Proxy dry_run validation to Platform API."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()

        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(
                f"{orch_url}/api/platform/submit",
                params={"dry_run": "true"},
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Validate proxy failed: {e}")
        return JSONResponse(
            content={"error": str(e), "validation": {"valid": False, "warnings": [str(e)]}},
            status_code=502,
        )


@router.post("/submit")
async def submit_job(request: Request):
    """Proxy job submission to Platform API."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{orch_url}/api/platform/submit",
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Submit proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)
