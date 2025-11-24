# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP Trigger - List blobs in container (read-only UI operation)
# PURPOSE: Provide lightweight blob listing for Pipeline Dashboard browser
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: list_container_blobs_handler
# INTERFACES: Azure Functions HTTP handler
# PYDANTIC_MODELS: None (simple JSON response)
# DEPENDENCIES: infrastructure.blob.BlobRepository
# SOURCE: HTTP GET requests to /api/containers/{container_name}/blobs
# SCOPE: Read-only blob listing (NO JOBS, NO TASKS - UI operation only)
# VALIDATION: Container name validation, limit bounds
# PATTERNS: Direct repository access, read-only
# ENTRY_POINTS: GET /api/containers/{container_name}/blobs
# INDEX: list_container_blobs_handler:50
# ============================================================================

"""
List Container Blobs HTTP Trigger

Lightweight blob listing endpoint for Pipeline Dashboard UI.
This is a READ-ONLY operation that directly queries Azure Blob Storage.
Does NOT create jobs, tasks, or any database records.

API Endpoint:
    GET /api/containers/{container_name}/blobs?prefix={prefix}&limit={limit}

Path Parameters:
    container_name: Azure Blob Storage container name (e.g., 'bronze-rasters')

Query Parameters:
    prefix: Optional path prefix filter (e.g., 'maxar/', 'data/2025/')
    limit: Maximum number of blobs to return (default: 50, max: 1000)

Returns:
    {
        "container": "bronze-rasters",
        "prefix": "maxar/",
        "count": 50,
        "blobs": [
            {
                "name": "maxar/file1.tif",
                "size": 12500000,
                "last_modified": "2025-11-20T14:30:00Z",
                "content_type": "image/tiff"
            },
            ...
        ]
    }

Last Updated: 21 NOV 2025
Author: Robert and Geospatial Claude Legion
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
