# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP Trigger - Get single blob metadata (read-only UI operation)
# PURPOSE: Provide blob details for Pipeline Dashboard file detail view
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: get_blob_metadata_handler
# INTERFACES: Azure Functions HTTP handler
# PYDANTIC_MODELS: None (simple JSON response)
# DEPENDENCIES: infrastructure.blob.BlobRepository
# SOURCE: HTTP GET requests to /api/containers/{container_name}/blobs/{blob_path}
# SCOPE: Read-only blob metadata (NO JOBS, NO TASKS - UI operation only)
# VALIDATION: Container/blob existence validation
# PATTERNS: Direct repository access, read-only
# ENTRY_POINTS: GET /api/containers/{container_name}/blobs/{blob_path}
# INDEX: get_blob_metadata_handler:50
# ============================================================================

"""
Get Blob Metadata HTTP Trigger

Lightweight single-blob metadata endpoint for Pipeline Dashboard UI.
This is a READ-ONLY operation that directly queries Azure Blob Storage.
Does NOT create jobs, tasks, or any database records.

API Endpoint:
    GET /api/containers/{container_name}/blobs/{blob_path}

Path Parameters:
    container_name: Azure Blob Storage container name (e.g., 'bronze-rasters')
    blob_path: Full path to blob within container (e.g., 'maxar/tile_001.tif')

Returns:
    {
        "container": "bronze-rasters",
        "name": "maxar/tile_001.tif",
        "size": 12500000,
        "size_mb": 11.92,
        "last_modified": "2025-11-20T14:30:00Z",
        "content_type": "image/tiff",
        "etag": "0x8DC1234567890AB",
        "metadata": {...}
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


def get_blob_metadata_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get metadata for a single blob.

    This is a lightweight, read-only endpoint for UI file details.
    Uses BlobRepository.get_blob_properties() directly - no job/task creation.

    Args:
        req: Azure Functions HTTP request
             Route params: container_name, blob_path

    Returns:
        JSON response with blob metadata
    """
    try:
        # Get container name from route
        container_name = req.route_params.get('container_name')
        blob_path = req.route_params.get('blob_path')

        if not container_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing container_name parameter",
                    "usage": "/api/containers/{container_name}/blobs/{blob_path}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        if not blob_path:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing blob_path parameter",
                    "usage": "/api/containers/{container_name}/blobs/{blob_path}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        logger.info(f"Getting blob metadata: container={container_name}, blob={blob_path}")

        # Get blob repository instance
        blob_repo = BlobRepository.instance()

        # Check if container exists
        if not blob_repo.container_exists(container_name):
            return func.HttpResponse(
                json.dumps({
                    "error": f"Container '{container_name}' not found",
                    "available_containers": ["bronze-rasters", "bronze-vectors"]
                }),
                status_code=404,
                mimetype="application/json"
            )

        # Check if blob exists
        if not blob_repo.blob_exists(container_name, blob_path):
            return func.HttpResponse(
                json.dumps({
                    "error": f"Blob '{blob_path}' not found in container '{container_name}'"
                }),
                status_code=404,
                mimetype="application/json"
            )

        # Get blob properties
        props = blob_repo.get_blob_properties(
            container=container_name,
            blob_path=blob_path
        )

        # Enhance response with additional fields
        response = {
            "container": container_name,
            **props,
            "size_mb": round(props.get('size', 0) / (1024 * 1024), 2) if props.get('size') else 0,
            "extension": blob_path.split('.')[-1].lower() if '.' in blob_path else None,
            "folder": '/'.join(blob_path.split('/')[:-1]) if '/' in blob_path else None,
            "filename": blob_path.split('/')[-1]
        }

        logger.info(f"Retrieved metadata for {blob_path} ({response.get('size_mb', 0)} MB)")

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Error getting blob metadata: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "type": type(e).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )
