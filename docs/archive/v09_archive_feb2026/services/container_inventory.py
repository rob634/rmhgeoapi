# ============================================================================
# CONTAINER INVENTORY SERVICE
# ============================================================================
# STATUS: Services - Task handlers for inventory_container_contents job
# PURPOSE: List blobs with metadata, basic analysis, aggregation
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Container Inventory Services.

Task handlers for inventory_container_contents job.

Replaces (07 DEC 2025):
    - services/container_list.py handlers → ARCHIVED

Stages:
    list_blobs_with_metadata: Stage 1 - List blobs with full metadata
    analyze_blob_basic: Stage 2 - Basic per-blob analysis (fan-out)
    aggregate_blob_analysis: Stage 3 - Aggregate into summary (fan-in)

Exports:
    list_blobs_with_metadata: Stage 1 handler
    analyze_blob_basic: Stage 2 handler
    aggregate_blob_analysis: Stage 3 handler (imported from container_list for now)
"""

from typing import Any
from datetime import datetime, timezone
from collections import defaultdict
from infrastructure.blob import BlobRepository


def list_blobs_with_metadata(params: dict) -> dict[str, Any]:
    """
    Stage 1: List blobs with full metadata for fan-out processing.

    Returns list of blob dicts (not just names) so Stage 2 handlers
    can work without additional API calls.

    Args:
        params: {
            "container_name": str,
            "prefix": str | None,
            "suffix": str | None,
            "limit": int (default 500)
        }

    Returns:
        Dict with success status and blob list with metadata:
        {
            "success": True,
            "result": {
                "blobs": [
                    {"name": "...", "size": int, "last_modified": str, "content_type": str},
                    ...
                ],
                "count": int,
                "execution_info": {...}
            }
        }
    """
    try:
        container_name = params["container_name"]
        prefix = params.get("prefix") or ""
        suffix = params.get("suffix") or ""
        limit = params.get("limit", 500)

        # Get blob repository for bronze zone (source data)
        blob_repo = BlobRepository.for_zone("bronze")

        start_time = datetime.now(timezone.utc)

        # Get blobs with full metadata
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=prefix,
            limit=limit
        )

        # Filter by suffix if provided
        if suffix:
            suffix_lower = suffix.lower()
            if not suffix_lower.startswith('.'):
                suffix_lower = '.' + suffix_lower
            blobs = [b for b in blobs if b['name'].lower().endswith(suffix_lower)]

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        # SUCCESS - return full blob metadata for Stage 2
        return {
            "success": True,
            "result": {
                "blobs": blobs,  # Full metadata dicts
                "count": len(blobs),
                "execution_info": {
                    "container_name": container_name,
                    "prefix_filter": prefix if prefix else None,
                    "suffix_filter": suffix if suffix else None,
                    "limit_requested": limit,
                    "scan_duration_seconds": round(duration, 2)
                }
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__
        }


def analyze_blob_basic(params: dict) -> dict[str, Any]:
    """
    Stage 2: Basic blob analysis - extract metadata and extension.

    Receives full blob metadata from Stage 1, no additional API calls needed.

    Args:
        params: {
            "blob_name": str,
            "size_bytes": int,
            "last_modified": str | None,
            "content_type": str | None,
            "container_name": str,
            "job_parameters": dict  # Original job params for context
        }

    Returns:
        Dict with analyzed blob info:
        {
            "success": True,
            "result": {
                "blob_name": str,
                "size_bytes": int,
                "size_mb": float,
                "extension": str,
                "last_modified": str | None,
                "content_type": str | None
            }
        }
    """
    try:
        blob_name = params.get("blob_name", "")
        size_bytes = params.get("size_bytes", 0)
        last_modified = params.get("last_modified")
        content_type = params.get("content_type")

        # Extract extension
        extension = _get_extension(blob_name)

        # Calculate size in MB
        size_mb = round(size_bytes / (1024 * 1024), 4) if size_bytes else 0.0

        return {
            "success": True,
            "result": {
                "blob_name": blob_name,
                "size_bytes": size_bytes,
                "size_mb": size_mb,
                "extension": extension,
                "last_modified": last_modified,
                "content_type": content_type
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__,
            "blob_name": params.get("blob_name")
        }


def aggregate_blob_analysis(params: dict) -> dict[str, Any]:
    """
    Stage 3: Aggregate all blob analysis results into summary (FAN-IN).

    Receives ALL Stage 2 results and produces consolidated summary.

    Args:
        params: {
            "previous_results": [
                {"success": True, "result": {"blob_name": "...", "size_mb": ..., ...}},
                ...
            ],
            "job_parameters": {"container_name": str, ...}
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
                    "by_extension": {".tif": {"count": 5, "total_size_mb": ...}, ...},
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
        start_time = datetime.now(timezone.utc)

        # DATABASE REFERENCE PATTERN (05 JAN 2026): CoreMachine now passes fan_in_source
        # instead of embedding previous_results. Handler queries DB directly.
        if "fan_in_source" in params:
            from core.fan_in import load_fan_in_results
            previous_results = load_fan_in_results(params)
            logger.info(f"📊 Fan-in DB reference: loaded {len(previous_results)} results")
        else:
            previous_results = params.get("previous_results", [])
        job_params = params.get("job_parameters", {})

        if not previous_results:
            return {
                "success": False,
                "error": "No previous results to aggregate",
                "error_type": "ValidationError"
            }

        # Initialize accumulators
        total_files = 0
        total_size_bytes = 0
        extension_counts = defaultdict(int)
        extension_sizes = defaultdict(int)
        successful_results = []
        failed_results = []

        # Aggregate results from all Stage 2 tasks
        for task_result in previous_results:
            if not task_result.get('success'):
                failed_results.append(task_result)
                continue

            result_data = task_result.get('result', {})
            total_files += 1
            successful_results.append(result_data)

            # Sum sizes
            size_bytes = result_data.get('size_bytes', 0)
            total_size_bytes += size_bytes

            # Count by extension
            ext = result_data.get('extension', 'unknown')
            extension_counts[ext] += 1
            extension_sizes[ext] += size_bytes

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
                "extension": largest.get('extension')
            }
            smallest_file = {
                "name": smallest.get('blob_name'),
                "size_mb": smallest.get('size_mb'),
                "extension": smallest.get('extension')
            }

        # Build extension statistics
        by_extension = {}
        for ext, count in extension_counts.items():
            total_bytes = extension_sizes[ext]
            by_extension[ext] = {
                "count": count,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                "percentage": round((count / total_files) * 100, 1) if total_files > 0 else 0.0
            }

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        return {
            "success": True,
            "result": {
                "summary": {
                    "total_files": total_files,
                    "total_size_bytes": total_size_bytes,
                    "total_size_mb": total_size_mb,
                    "average_size_mb": average_size_mb,
                    "by_extension": dict(sorted(by_extension.items())),
                    "largest_file": largest_file,
                    "smallest_file": smallest_file,
                    "files_analyzed": len(successful_results),
                    "files_failed": len(failed_results),
                    "container_name": job_params.get("container_name"),
                    "aggregation_time_seconds": round(duration, 3)
                }
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__
        }


def _get_extension(filename: str) -> str:
    """Extract file extension (lowercase with dot)."""
    if "." not in filename:
        return "no_extension"
    return "." + filename.rsplit(".", 1)[-1].lower()
