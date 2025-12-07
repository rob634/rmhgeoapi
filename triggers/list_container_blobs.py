"""
List Container Blobs HTTP Trigger.

Synchronous blob listing endpoint - direct results, no CoreMachine orchestration.

Features (07 DEC 2025):
    - suffix filter: e.g., ?suffix=.tif
    - metadata toggle: ?metadata=true returns full dict, false returns just names
    - limit default: 500 (was 50)

Exports:
    list_container_blobs_handler: HTTP trigger function for GET /api/containers/{container_name}/blobs
"""

import azure.functions as func
import json
import logging

from infrastructure.blob import BlobRepository

logger = logging.getLogger(__name__)


def list_container_blobs_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    List blobs in a container with filtering options.

    Synchronous endpoint - returns results directly, no job/task creation.
    Uses BlobRepository.list_blobs() which returns full metadata.

    Args:
        req: Azure Functions HTTP request
             Route params: container_name
             Query params:
                - prefix (optional): Path prefix filter
                - suffix (optional): Extension filter, e.g., ".tif"
                - metadata (optional): "true" returns full dict, "false" returns just names (default: true)
                - limit (optional): Max blobs to return (default: 500, max: 10000)

    Returns:
        JSON response with blob listing

    Examples:
        GET /api/containers/bronze-rasters/blobs
        GET /api/containers/bronze-rasters/blobs?suffix=.tif&limit=100
        GET /api/containers/bronze-rasters/blobs?prefix=maxar/&metadata=false
    """
    try:
        # Get container name from route
        container_name = req.route_params.get('container_name')

        if not container_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing container_name parameter",
                    "usage": "/api/containers/{container_name}/blobs?prefix=&suffix=.tif&metadata=true&limit=500"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Get query parameters
        prefix = req.params.get('prefix', '')
        suffix = req.params.get('suffix', '')
        metadata_str = req.params.get('metadata', 'true').lower()
        limit_str = req.params.get('limit', '500')

        # Parse metadata flag
        include_metadata = metadata_str in ('true', '1', 'yes')

        # Parse and validate limit
        try:
            limit = int(limit_str)
            limit = max(1, min(limit, 10000))  # Clamp between 1 and 10000
        except ValueError:
            limit = 500

        logger.info(f"Listing blobs: container={container_name}, prefix='{prefix}', suffix='{suffix}', metadata={include_metadata}, limit={limit}")

        # Get blob repository instance
        blob_repo = BlobRepository.instance()

        # Check if container exists
        if not blob_repo.container_exists(container_name):
            return func.HttpResponse(
                json.dumps({
                    "error": f"Container '{container_name}' not found",
                    "hint": "Check container name spelling or verify access permissions"
                }),
                status_code=404,
                mimetype="application/json"
            )

        # List blobs with metadata
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=prefix,
            limit=limit
        )

        # Filter by suffix if provided
        if suffix:
            suffix_lower = suffix.lower()
            # Handle both ".tif" and "tif" formats
            if not suffix_lower.startswith('.'):
                suffix_lower = '.' + suffix_lower
            blobs = [b for b in blobs if b['name'].lower().endswith(suffix_lower)]

        # Format response based on metadata flag
        if include_metadata:
            # Full metadata - add size_mb for convenience
            for blob in blobs:
                if blob.get('size'):
                    blob['size_mb'] = round(blob['size'] / (1024 * 1024), 2)
            blob_output = blobs
        else:
            # Just names
            blob_output = [b['name'] for b in blobs]

        response = {
            "container": container_name,
            "prefix": prefix if prefix else None,
            "suffix": suffix if suffix else None,
            "metadata": include_metadata,
            "limit": limit,
            "count": len(blob_output),
            "blobs": blob_output
        }

        logger.info(f"Listed {len(blob_output)} blobs from {container_name}")

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
