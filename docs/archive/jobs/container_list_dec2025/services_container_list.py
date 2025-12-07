"""
Container List Services - Three-Stage Diamond Pattern.

Task handlers for list_container_contents job.

Stages:
    list_container_blobs: Returns list of blob names
    analyze_single_blob: Analyzes individual blob metadata (fan-out)
    aggregate_blob_analysis: Aggregates all metadata into summary (fan-in)

Exports:
    list_container_blobs: Stage 1 handler
    analyze_single_blob: Stage 2 handler
    aggregate_blob_analysis: Stage 3 handler
"""

from typing import Any
from datetime import datetime
from collections import defaultdict
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


def aggregate_blob_analysis(params: dict) -> dict[str, Any]:
    """
    Stage 3: Aggregate all blob analysis results into summary (FAN-IN).

    This is a fan-in aggregation handler - CoreMachine automatically creates
    one task of this type when stage has parallelism="fan_in".

    Receives ALL Stage 2 results and produces consolidated summary.

    Args:
        params: {
            "previous_results": [
                {"task_id": "...", "result": {"blob_name": "...", "size_mb": ..., ...}},
                {"task_id": "...", "result": {"blob_name": "...", "size_mb": ..., ...}},
                # ... N results
            ],
            "job_parameters": {"container_name": str, ...},
            "aggregation_metadata": {
                "stage": 3,
                "previous_stage": 2,
                "result_count": N,
                "pattern": "fan_in"
            }
        }

    Returns:
        Dict with aggregated summary:
        {
            "success": True,
            "result": {
                "summary": {
                    "total_files": int,
                    "total_size_bytes": int,
                    "total_size_mb": float,
                    "by_extension": {".tif": 5, ".shp": 3, ...},
                    "largest_file": {"name": "...", "size_mb": ...},
                    "smallest_file": {"name": "...", "size_mb": ...},
                    "average_size_mb": float,
                    "files_analyzed": int,
                    "files_failed": int
                }
            }
        }
    """
    try:
        start_time = datetime.utcnow()

        # Extract previous results from params
        previous_results = params.get("previous_results", [])
        job_params = params.get("job_parameters", {})
        agg_metadata = params.get("aggregation_metadata", {})

        # Validate inputs
        if not previous_results:
            return {
                "success": False,
                "error": "No previous results to aggregate",
                "error_type": "ValidationError"
            }

        # Initialize aggregation accumulators
        total_files = 0
        total_size_bytes = 0
        extension_counts = defaultdict(int)
        extension_sizes = defaultdict(int)  # Total bytes per extension
        successful_results = []
        failed_results = []

        # Aggregate results from all Stage 2 tasks
        for task_result in previous_results:
            if not task_result.get('success'):
                failed_results.append(task_result)
                continue

            result_data = task_result.get('result', {})

            # Count files
            total_files += 1
            successful_results.append(result_data)

            # Sum sizes
            size_bytes = result_data.get('size_bytes', 0)
            total_size_bytes += size_bytes

            # Count by extension
            file_ext = result_data.get('file_extension', 'unknown')
            extension_counts[file_ext] += 1
            extension_sizes[file_ext] += size_bytes

        # Calculate derived metrics
        total_size_mb = round(total_size_bytes / (1024 * 1024), 2) if total_size_bytes else 0.0
        average_size_mb = round(total_size_mb / total_files, 4) if total_files > 0 else 0.0

        # Find largest and smallest files
        largest_file = None
        smallest_file = None
        if successful_results:
            largest = max(successful_results, key=lambda x: x.get('size_bytes', 0))
            smallest = min(successful_results, key=lambda x: x.get('size_bytes', 0))

            largest_file = {
                "name": largest.get('blob_name'),
                "size_mb": largest.get('size_mb'),
                "extension": largest.get('file_extension')
            }
            smallest_file = {
                "name": smallest.get('blob_name'),
                "size_mb": smallest.get('size_mb'),
                "extension": smallest.get('file_extension')
            }

        # Calculate extension statistics
        by_extension = {}
        for ext, count in extension_counts.items():
            total_bytes = extension_sizes[ext]
            by_extension[ext] = {
                "count": count,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                "percentage": round((count / total_files) * 100, 1) if total_files > 0 else 0.0
            }

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS - return aggregated summary
        return {
            "success": True,
            "result": {
                "summary": {
                    "total_files": total_files,
                    "total_size_bytes": total_size_bytes,
                    "total_size_mb": total_size_mb,
                    "average_size_mb": average_size_mb,
                    "by_extension": dict(sorted(by_extension.items())),  # Sort for readability
                    "largest_file": largest_file,
                    "smallest_file": smallest_file,
                    "files_analyzed": len(successful_results),
                    "files_failed": len(failed_results),
                    "container_name": job_params.get("container_name"),
                    "aggregation_metadata": {
                        "stage": agg_metadata.get("stage"),
                        "results_aggregated": agg_metadata.get("result_count"),
                        "pattern": agg_metadata.get("pattern"),
                        "execution_time_seconds": round(duration, 3)
                    }
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


def _get_extension(filename: str) -> str:
    """Extract file extension (lowercase)."""
    if "." not in filename:
        return "no_extension"
    return "." + filename.rsplit(".", 1)[-1].lower()
