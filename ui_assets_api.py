"""
Assets Proxy API for DAG Brain Admin UI.

Proxies asset management calls to the Function App (orchestrator).

Endpoints:
    GET  /ui/api/assets/stats              - Approval state counts
    GET  /ui/api/assets/by-state           - List releases by approval state
    GET  /ui/api/assets/{asset_id}         - Single asset with releases
    POST /ui/api/assets/{asset_id}/approve - Approve a release
    POST /ui/api/assets/{asset_id}/reject  - Reject a release
    POST /ui/api/assets/{asset_id}/revoke  - Revoke an approval
"""
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api/assets", tags=["assets-proxy"])

PROXY_TIMEOUT = 30.0


def _get_orchestrator_url() -> str:
    url = os.environ.get("ORCHESTRATOR_URL", "").rstrip("/")
    if not url:
        raise ValueError("ORCHESTRATOR_URL not set")
    return url


@router.get("/stats")
async def approval_stats():
    """Proxy GET /api/assets/approval-stats."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(f"{orch_url}/api/assets/approval-stats")
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Assets stats proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/by-state")
async def list_by_state(state: str = "pending_review", limit: int = 100):
    """Proxy GET /api/assets/by-approval-state?state=X."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/assets/by-approval-state",
                params={"state": state, "limit": limit},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Assets by-state proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/{asset_id}")
async def get_asset(asset_id: str):
    """Proxy GET /api/assets/{asset_id}/approval."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(f"{orch_url}/api/assets/{asset_id}/approval")
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        try:
            content = e.response.json()
        except Exception:
            content = {"error": str(e)}
        return JSONResponse(content=content, status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Asset detail proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/approve")
async def approve_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/approve."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(f"{orch_url}/api/assets/{asset_id}/approve", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        try:
            content = e.response.json()
        except Exception:
            content = {"error": str(e)}
        return JSONResponse(content=content, status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Approve proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/reject")
async def reject_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/reject."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(f"{orch_url}/api/assets/{asset_id}/reject", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        try:
            content = e.response.json()
        except Exception:
            content = {"error": str(e)}
        return JSONResponse(content=content, status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Reject proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/revoke")
async def revoke_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/revoke."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(f"{orch_url}/api/assets/{asset_id}/revoke", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        try:
            content = e.response.json()
        except Exception:
            content = {"error": str(e)}
        return JSONResponse(content=content, status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Revoke proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)
