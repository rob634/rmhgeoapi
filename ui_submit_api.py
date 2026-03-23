"""
Submit Proxy API for DAG Brain Admin UI.

Proxies storage browsing and Platform API calls to the Function App (orchestrator).
The DAG Brain doesn't have direct blob access — it delegates to the orchestrator.

Endpoints:
    GET  /ui/api/containers   - List bronze containers (proxied)
    GET  /ui/api/files        - List files in container (proxied)
    POST /ui/api/validate     - dry_run validation via Platform API
    POST /ui/api/submit       - Job submission via Platform API
"""
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

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
    """
    Proxy container listing from orchestrator's storage API.

    Orchestrator endpoint: GET /api/storage/containers?zone=bronze
    Response shape: {"zone": "bronze", "containers": [{"name": "wargames", ...}, ...]}
    """
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/storage/containers",
                params={"zone": zone},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content={"error": f"Orchestrator returned {e.response.status_code}"},
            status_code=502,
        )
    except Exception as e:
        logger.warning(f"Container proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/files")
async def list_files(
    zone: str = "bronze",
    container: str = "",
    prefix: str = "",
    data_type: str = "raster",
    limit: int = 250,
):
    """
    Proxy file listing from orchestrator's storage API, filtered by data type.

    The orchestrator endpoint is: GET /api/storage/{container_name}/blobs
    Query params: zone, prefix, suffix, limit
    Response: {"blobs": [{"name": "...", "size": 12345, "last_modified": "..."}, ...]}
    """
    if not container:
        return JSONResponse(content={"error": "container required"}, status_code=400)

    raster_exts = {'.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5'}
    vector_exts = {'.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip'}
    exts = vector_exts if data_type == "vector" else raster_exts

    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/storage/{container}/blobs",
                params={"zone": zone, "prefix": prefix, "limit": limit * 2},
            )
            resp.raise_for_status()
            data = resp.json()

        # Response shape: {"blobs": [...]} or list directly
        blobs = data.get("blobs", data) if isinstance(data, dict) else data
        if not isinstance(blobs, list):
            blobs = []

        # Filter by extension
        filtered = []
        for blob in blobs:
            name = (blob.get("name") or "").lower()
            if any(name.endswith(ext) for ext in exts):
                filtered.append(blob)
                if len(filtered) >= limit:
                    break

        return JSONResponse(content={"files": filtered})
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content={"error": f"Orchestrator returned {e.response.status_code}"},
            status_code=502,
        )
    except Exception as e:
        logger.warning(f"Files proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


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
