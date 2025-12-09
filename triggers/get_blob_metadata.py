"""
Get Blob Metadata HTTP Trigger.

Single-blob metadata endpoint for Pipeline Dashboard UI.

Updated (08 DEC 2025):
    - Added zone parameter for multi-account storage support (default: bronze)
    - Removed hardcoded container list

Exports:
    get_blob_metadata_handler: HTTP trigger function for GET /api/containers/{container_name}/blob
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
             Route params: container_name
             Query params:
                - path (required): Blob path within container
                - zone (optional): Storage zone - "bronze", "silver", "silverext" (default: bronze)

    Returns:
        JSON response with blob metadata
    """
    try:
        # Get container name from route
        container_name = req.route_params.get('container_name')
        # Get blob path from query parameter (not route, because Azure Functions v4
        # doesn't support the ':path' constraint for nested paths with slashes)
        blob_path = req.params.get('path')

        if not container_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing container_name parameter",
                    "usage": "/api/containers/{container_name}/blobs?path={blob_path}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        if not blob_path:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing 'path' query parameter",
                    "usage": "/api/containers/{container_name}/blobs?path=folder/file.tif&zone=bronze"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Get and validate zone parameter
        zone = req.params.get('zone', 'bronze').lower()
        valid_zones = ('bronze', 'silver', 'silverext')
        if zone not in valid_zones:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Invalid zone '{zone}'",
                    "valid_zones": list(valid_zones),
                    "hint": "Use zone=bronze for input data, zone=silver for processed data"
                }),
                status_code=400,
                mimetype="application/json"
            )

        logger.info(f"Getting blob metadata: zone={zone}, container={container_name}, blob={blob_path}")

        # Get blob repository for the specified zone
        blob_repo = BlobRepository.for_zone(zone)

        # Check if container exists
        if not blob_repo.container_exists(container_name):
            return func.HttpResponse(
                json.dumps({
                    "error": f"Container '{container_name}' not found in {zone} zone",
                    "zone": zone,
                    "hint": "Verify container exists and zone is correct"
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
            "zone": zone,
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
