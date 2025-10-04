"""
Container List Services - Two-Stage Pattern

Stage 1: list_container_blobs - Returns list of blob names
Stage 2: analyze_single_blob - Analyzes and stores individual blob metadata

Author: Robert and Geospatial Claude Legion
Date: 4 OCT 2025
"""

from typing import Any
from datetime import datetime
from infrastructure.blob import BlobRepository


def list_container_blobs(params: dict) -> dict[str, Any]:
    """
    Stage 1: List all blobs in container.

    Returns list of blob names for Stage 2 fan-out.

    Args:
        params: {
            "container_name": str,
            "file_limit": int | None,
            "filter": dict | None
        }

    Returns:
        Dict with success status and blob list:
        {
            "success": True,
            "result": {
                "blob_names": [list of blob names],
                "total_count": int,
                "execution_info": {...}
            }
        }
    """
    try:
        container_name = params["container_name"]
        file_limit = params.get("file_limit")
        filter_criteria = params.get("filter", {})

        blob_repo = BlobRepository()

        start_time = datetime.utcnow()

        # Get all blobs
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=filter_criteria.get("prefix", ""),
            limit=file_limit
        )

        # Apply filters
        filtered_blobs = []
        for blob in blobs:
            if _matches_filter(blob, filter_criteria):
                filtered_blobs.append(blob['name'])

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS - return blob names for Stage 2
        return {
            "success": True,
            "result": {
                "blob_names": filtered_blobs,
                "total_count": len(filtered_blobs),
                "execution_info": {
                    "scan_duration_seconds": round(duration, 2),
                    "blobs_filtered": len(blobs) - len(filtered_blobs)
                }
            }
        }

    except Exception as e:
        # FAILURE - return error
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__
        }


def analyze_single_blob(params: dict) -> dict[str, Any]:
    """
    Stage 2: Analyze a single blob and store metadata.

    This function is called once per blob in parallel.
    Result is automatically stored in task.result_data by CoreMachine.

    Args:
        params: {
            "container_name": str,
            "blob_name": str
        }

    Returns:
        Dict with success status and blob metadata:
        {
            "success": True,
            "result": {
                "blob_name": str,
                "blob_path": str,
                "size_bytes": int,
                "size_mb": float,
                "file_extension": str,
                "content_type": str,
                "last_modified": str,
                "metadata": dict
            }
        }
    """
    try:
        container_name = params["container_name"]
        blob_name = params["blob_name"]

        blob_repo = BlobRepository()

        # Get blob properties
        props = blob_repo.get_blob_properties(container_name, blob_name)

        # Calculate derived fields
        size_bytes = props['size']
        size_mb = round(size_bytes / (1024 * 1024), 4) if size_bytes else 0.0
        file_ext = _get_extension(blob_name)

        # SUCCESS - return blob metadata
        # CoreMachine will store this in task.result_data automatically
        return {
            "success": True,
            "result": {
                "blob_name": blob_name,
                "blob_path": f"{container_name}/{blob_name}",
                "container_name": container_name,
                "size_bytes": size_bytes,
                "size_mb": size_mb,
                "file_extension": file_ext,
                "content_type": props.get('content_type'),
                "last_modified": props.get('last_modified'),
                "etag": props.get('etag'),
                "metadata": props.get('metadata', {})
            }
        }

    except Exception as e:
        # FAILURE - return error
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__,
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name")
        }


def _matches_filter(blob: dict, filter_criteria: dict) -> bool:
    """Check if blob matches filter criteria."""
    if not filter_criteria:
        return True

    # Extension filter
    if "extensions" in filter_criteria:
        ext = _get_extension(blob['name'])
        if ext not in filter_criteria["extensions"]:
            return False

    # Size filters
    size_mb = blob['size'] / (1024 * 1024) if blob['size'] else 0
    if "min_size_mb" in filter_criteria:
        if size_mb < filter_criteria["min_size_mb"]:
            return False
    if "max_size_mb" in filter_criteria:
        if size_mb > filter_criteria["max_size_mb"]:
            return False

    # Date filters (last_modified is ISO string)
    if "modified_after" in filter_criteria:
        after = datetime.fromisoformat(filter_criteria["modified_after"])
        if blob['last_modified']:
            blob_dt = datetime.fromisoformat(blob['last_modified'])
            if blob_dt < after:
                return False
    if "modified_before" in filter_criteria:
        before = datetime.fromisoformat(filter_criteria["modified_before"])
        if blob['last_modified']:
            blob_dt = datetime.fromisoformat(blob['last_modified'])
            if blob_dt > before:
                return False

    return True


def _get_extension(filename: str) -> str:
    """Extract file extension (lowercase)."""
    if "." not in filename:
        return "no_extension"
    return "." + filename.rsplit(".", 1)[-1].lower()
