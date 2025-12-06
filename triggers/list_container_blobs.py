"""
List Container Blobs HTTP Trigger.

Lightweight blob listing endpoint for Pipeline Dashboard UI.

Exports:
    list_container_blobs_handler: HTTP trigger function for GET /api/containers/{container_name}/blobs
"""

import azure.functions as func
import json
import logging
from typing import Optional

from infrastructure.blob import BlobRepository

logger = logging.getLogger(__name__)


def list_container_blobs_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    List blobs in a container with optional prefix filter.

    This is a lightweight, read-only endpoint for UI file browsing.
    Uses BlobRepository.list_blobs() directly - no job/task creation.

    Args:
        req: Azure Functions HTTP request
             Route params: container_name
             Query params: prefix (optional), limit (optional, default 50)

    Returns:
        JSON response with blob listing
    """
    try:
        # Get container name from route
        container_name = req.route_params.get('container_name')

        if not container_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing container_name parameter",
                    "usage": "/api/containers/{container_name}/blobs?prefix=&limit=50"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Get query parameters
        prefix = req.params.get('prefix', '')
        limit_str = req.params.get('limit', '50')

        # Parse and validate limit
        try:
            limit = int(limit_str)
            limit = max(1, min(limit, 1000))  # Clamp between 1 and 1000
        except ValueError:
            limit = 50

        logger.info(f"Listing blobs: container={container_name}, prefix='{prefix}', limit={limit}")

        # Get blob repository instance
        blob_repo = BlobRepository.instance()

        # Check if container exists
        if not blob_repo.container_exists(container_name):
            return func.HttpResponse(
                json.dumps({
                    "error": f"Container '{container_name}' not found",
                    "available_containers": ["rmhazuregeobronze", "rmhazuregeosilver", "rmhazuregeogold", "silver-cogs", "source-data"]
                }),
                status_code=404,
                mimetype="application/json"
            )

        # List blobs
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=prefix,
            limit=limit
        )

        # Format response
        response = {
            "container": container_name,
            "prefix": prefix,
            "limit": limit,
            "count": len(blobs),
            "blobs": blobs
        }

        logger.info(f"Listed {len(blobs)} blobs from {container_name}")

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Error listing blobs: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "type": type(e).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )
