# ============================================================================
# ARTIFACT ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for artifact registry admin routes
# PURPOSE: Internal artifact tracking, revision history, supersession chains
# CREATED: 22 JAN 2026
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Artifact Admin Blueprint - Internal artifact registry administration.

Routes (7 total):
    Lookup (3):
        GET  /api/admin/artifacts/{artifact_id}      - Get artifact by UUID
        GET  /api/admin/artifacts/stac               - Get artifact by STAC item
        GET  /api/admin/artifacts/job/{job_id}       - Get artifacts by job

    History & Lineage (2):
        GET  /api/admin/artifacts/history            - Get revision history
        GET  /api/admin/artifacts/{artifact_id}/chain - Get supersession chain

    Management (1):
        DELETE /api/admin/artifacts/{artifact_id}    - Mark artifact as deleted

    Statistics (1):
        GET  /api/admin/artifacts/stats              - Get artifact statistics

NOTE: These are INTERNAL admin endpoints, not public platform endpoints.
Artifact tracking is for internal audit/lineage - not exposed to external clients.
"""

import json
import azure.functions as func
from azure.functions import Blueprint
from typing import Optional
from uuid import UUID

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "admin_artifacts")

bp = Blueprint()


def _artifact_to_dict(artifact) -> dict:
    """Convert Artifact model to JSON-serializable dict."""
    return artifact.to_dict() if artifact else None


def _make_json_response(data: dict, status_code: int = 200) -> func.HttpResponse:
    """Create a JSON HTTP response."""
    return func.HttpResponse(
        body=json.dumps(data, default=str),
        status_code=status_code,
        mimetype="application/json"
    )


def _make_error_response(message: str, status_code: int = 400) -> func.HttpResponse:
    """Create an error HTTP response."""
    return _make_json_response({"error": message}, status_code)


# ============================================================================
# LOOKUP ENDPOINTS (3 routes)
# ============================================================================

@bp.route(route="admin/artifacts/{artifact_id}", methods=["GET"])
def admin_artifact_get(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get artifact by internal UUID.

    GET /api/admin/artifacts/{artifact_id}

    Path Parameters:
        artifact_id: UUID of the artifact

    Returns:
        Artifact details or 404 if not found
    """
    try:
        artifact_id_str = req.route_params.get("artifact_id")
        if not artifact_id_str:
            return _make_error_response("artifact_id is required", 400)

        try:
            artifact_id = UUID(artifact_id_str)
        except ValueError:
            return _make_error_response(f"Invalid UUID format: {artifact_id_str}", 400)

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        artifact = service.get_by_id(artifact_id)

        if not artifact:
            return _make_error_response(f"Artifact not found: {artifact_id}", 404)

        return _make_json_response({
            "artifact": _artifact_to_dict(artifact)
        })

    except Exception as e:
        logger.error(f"Error getting artifact: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="admin/artifacts/stac", methods=["GET"])
def admin_artifact_get_by_stac(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get artifact by STAC collection and item ID.

    GET /api/admin/artifacts/stac?collection_id=xxx&item_id=yyy

    Query Parameters:
        collection_id: STAC collection ID (required)
        item_id: STAC item ID (required)

    Returns:
        Artifact that created this STAC item, or 404 if not found
    """
    try:
        collection_id = req.params.get("collection_id")
        item_id = req.params.get("item_id")

        if not collection_id:
            return _make_error_response("collection_id is required", 400)
        if not item_id:
            return _make_error_response("item_id is required", 400)

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        artifact = service.get_by_stac(collection_id, item_id)

        if not artifact:
            return _make_error_response(
                f"No artifact found for STAC item {collection_id}/{item_id}", 404
            )

        return _make_json_response({
            "artifact": _artifact_to_dict(artifact)
        })

    except Exception as e:
        logger.error(f"Error getting artifact by STAC: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="admin/artifacts/job/{job_id}", methods=["GET"])
def admin_artifacts_by_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get all artifacts created by a job.

    GET /api/admin/artifacts/job/{job_id}

    Path Parameters:
        job_id: CoreMachine job ID

    Returns:
        List of artifacts created by this job
    """
    try:
        job_id = req.route_params.get("job_id")
        if not job_id:
            return _make_error_response("job_id is required", 400)

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        artifacts = service.get_by_job(job_id)

        return _make_json_response({
            "job_id": job_id,
            "count": len(artifacts),
            "artifacts": [_artifact_to_dict(a) for a in artifacts]
        })

    except Exception as e:
        logger.error(f"Error getting artifacts by job: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# HISTORY & LINEAGE ENDPOINTS (2 routes)
# ============================================================================

@bp.route(route="admin/artifacts/history", methods=["GET"])
def admin_artifact_history(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get full revision history for client refs.

    GET /api/admin/artifacts/history?client_type=ddh&dataset_id=xxx&resource_id=yyy&version_id=zzz

    Query Parameters:
        client_type: Client identifier (required, e.g., 'ddh')
        dataset_id: DDH dataset ID (for ddh client_type)
        resource_id: DDH resource ID (for ddh client_type)
        version_id: DDH version ID (for ddh client_type)
        ... any other client_refs as query params

    Returns:
        List of all revisions ordered by revision desc
    """
    try:
        client_type = req.params.get("client_type")
        if not client_type:
            return _make_error_response("client_type is required", 400)

        # Build client_refs from remaining query params
        client_refs = {}
        known_params = {"client_type"}  # Params that aren't client_refs

        for key, value in req.params.items():
            if key not in known_params:
                client_refs[key] = value

        if not client_refs:
            return _make_error_response(
                "At least one client_ref parameter is required (e.g., dataset_id, resource_id)", 400
            )

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        history = service.get_history(client_type, client_refs)

        return _make_json_response({
            "client_type": client_type,
            "client_refs": client_refs,
            "revision_count": len(history),
            "history": [_artifact_to_dict(a) for a in history]
        })

    except Exception as e:
        logger.error(f"Error getting artifact history: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="admin/artifacts/{artifact_id}/chain", methods=["GET"])
def admin_artifact_chain(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get supersession chain for an artifact.

    GET /api/admin/artifacts/{artifact_id}/chain?direction=both

    Path Parameters:
        artifact_id: UUID of the starting artifact

    Query Parameters:
        direction: Traversal direction (default: "both")
            - "forward": What replaced this? (follow superseded_by)
            - "backward": What did this replace? (follow supersedes)
            - "both": Full chain

    Returns:
        List of artifacts in the supersession chain
    """
    try:
        artifact_id_str = req.route_params.get("artifact_id")
        if not artifact_id_str:
            return _make_error_response("artifact_id is required", 400)

        try:
            artifact_id = UUID(artifact_id_str)
        except ValueError:
            return _make_error_response(f"Invalid UUID format: {artifact_id_str}", 400)

        direction = req.params.get("direction", "both")
        if direction not in ("forward", "backward", "both"):
            return _make_error_response(
                f"Invalid direction: {direction}. Must be 'forward', 'backward', or 'both'", 400
            )

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        chain = service.get_supersession_chain(artifact_id, direction)

        return _make_json_response({
            "artifact_id": str(artifact_id),
            "direction": direction,
            "chain_length": len(chain),
            "chain": [_artifact_to_dict(a) for a in chain]
        })

    except Exception as e:
        logger.error(f"Error getting supersession chain: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# MANAGEMENT ENDPOINTS (1 route)
# ============================================================================

@bp.route(route="admin/artifacts/{artifact_id}", methods=["DELETE"])
def admin_artifact_delete(req: func.HttpRequest) -> func.HttpResponse:
    """
    Mark artifact as deleted (soft delete).

    DELETE /api/admin/artifacts/{artifact_id}?confirm=yes

    Path Parameters:
        artifact_id: UUID of the artifact

    Query Parameters:
        confirm: Must be "yes" to confirm deletion (required)

    Returns:
        Success message or 404 if not found

    NOTE: This is a soft delete - the artifact record is preserved
    with status=DELETED for audit/lineage purposes.
    """
    try:
        artifact_id_str = req.route_params.get("artifact_id")
        if not artifact_id_str:
            return _make_error_response("artifact_id is required", 400)

        try:
            artifact_id = UUID(artifact_id_str)
        except ValueError:
            return _make_error_response(f"Invalid UUID format: {artifact_id_str}", 400)

        confirm = req.params.get("confirm")
        if confirm != "yes":
            return _make_error_response(
                "Deletion requires confirm=yes query parameter", 400
            )

        from services.artifact_service import ArtifactService
        service = ArtifactService()

        # First check if artifact exists
        artifact = service.get_by_id(artifact_id)
        if not artifact:
            return _make_error_response(f"Artifact not found: {artifact_id}", 404)

        success = service.mark_deleted(artifact_id)

        if success:
            return _make_json_response({
                "message": f"Artifact {artifact_id} marked as deleted",
                "artifact_id": str(artifact_id),
                "previous_status": artifact.status.value if hasattr(artifact.status, 'value') else artifact.status
            })
        else:
            return _make_error_response(f"Failed to delete artifact: {artifact_id}", 500)

    except Exception as e:
        logger.error(f"Error deleting artifact: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# STATISTICS ENDPOINT (1 route)
# ============================================================================

@bp.route(route="admin/artifacts/stats", methods=["GET"])
def admin_artifact_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get artifact statistics.

    GET /api/admin/artifacts/stats?client_type=ddh

    Query Parameters:
        client_type: Optional filter by client type

    Returns:
        Statistics including counts by status, total size, etc.
    """
    try:
        client_type = req.params.get("client_type")

        from services.artifact_service import ArtifactService
        service = ArtifactService()
        stats = service.get_stats(client_type)

        return _make_json_response({
            "client_type": client_type,
            "stats": stats
        })

    except Exception as e:
        logger.error(f"Error getting artifact stats: {e}")
        return _make_error_response(f"Internal error: {e}", 500)
