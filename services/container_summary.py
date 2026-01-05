# ============================================================================
# CONTAINER SUMMARY SERVICE
# ============================================================================
# STATUS: Services - Memory-efficient container statistics
# PURPOSE: Generate aggregate stats using streaming generator pattern
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Container Summary Service - Container Statistics.

Scans a blob container and generates aggregate statistics.
Memory-efficient streaming implementation using generator pattern.

Features:
    - File type distribution (by extension)
    - Size distribution buckets
    - Date range analysis (oldest/newest files)
    - Largest/smallest file tracking
    - Flexible filtering (extension, size, date range, prefix)

Exports:
    analyze_container_summary: Generate container statistics
"""

from typing import Any
from datetime import datetime
from collections import defaultdict
from infrastructure.blob import BlobRepository


def analyze_container_summary(params: dict) -> dict[str, Any]:
    """
    Scan container and generate summary statistics.

    Args:
        params: {
            "container_name": str,
            "file_limit": int | None,
            "filter": dict | None
        }

    Returns:
        Dict with success status and result data:
        {
            "success": True/False,
            "result": {...statistics...} OR "error": "error message"
        }
    """
    try:
        container_name = params["container_name"]
        file_limit = params.get("file_limit")
        filter_criteria = params.get("filter", {})
        zone = params.get("zone", "bronze")  # Default to bronze for container analysis

        blob_repo = BlobRepository.for_zone(zone)  # Use specified zone

        # Initialize accumulators
        total_files = 0
        total_size = 0
        largest_file = None
        smallest_file = None
        file_types = defaultdict(lambda: {"count": 0, "total_size_gb": 0.0})
        size_buckets = {
            "0-10MB": 0,
            "10-100MB": 0,
            "100MB-1GB": 0,
            "1GB-10GB": 0,
            "10GB+": 0
        }
        oldest_date = None
        newest_date = None

        start_time = datetime.utcnow()
        files_filtered = 0

        # Stream blob list (memory efficient)
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=filter_criteria.get("prefix", ""),
            limit=file_limit
        )

        for blob in blobs:
            # Apply filters
            if not _matches_filter(blob, filter_criteria):
                files_filtered += 1
                continue

            # Update statistics
            blob_size = blob['size']
            blob_name = blob['name']
            blob_modified = blob['last_modified']

            total_files += 1
            total_size += blob_size

            # Track largest/smallest
            if largest_file is None or blob_size > largest_file["size_bytes"]:
                largest_file = {
                    "name": blob_name,
                    "size_bytes": blob_size,
                    "size_mb": round(blob_size / (1024 * 1024), 2),
                    "last_modified": blob_modified
                }

            if smallest_file is None or blob_size < smallest_file["size_bytes"]:
                smallest_file = {
                    "name": blob_name,
                    "size_bytes": blob_size,
                    "last_modified": blob_modified
                }

            # Track by extension
            ext = _get_extension(blob_name)
            file_types[ext]["count"] += 1
            file_types[ext]["total_size_gb"] += blob_size / (1024**3)

            # Size distribution
            size_mb = blob_size / (1024 * 1024)
            if size_mb < 10:
                size_buckets["0-10MB"] += 1
            elif size_mb < 100:
                size_buckets["10-100MB"] += 1
            elif size_mb < 1024:
                size_buckets["100MB-1GB"] += 1
            elif size_mb < 10240:
                size_buckets["1GB-10GB"] += 1
            else:
                size_buckets["10GB+"] += 1

            # Date tracking (last_modified is already ISO string)
            if blob_modified:
                modified_dt = datetime.fromisoformat(blob_modified)
                if oldest_date is None or modified_dt < oldest_date:
                    oldest_date = modified_dt
                if newest_date is None or modified_dt > newest_date:
                    newest_date = modified_dt

            # Respect file limit
            if file_limit and total_files >= file_limit:
                break

        duration = (datetime.utcnow() - start_time).total_seconds()

        # Round file type sizes
        for ext in file_types:
            file_types[ext]["total_size_gb"] = round(file_types[ext]["total_size_gb"], 4)

        # SUCCESS - return wrapped result
        return {
            "success": True,
            "result": {
                "container_name": container_name,
                "analysis_timestamp": datetime.utcnow().isoformat(),
                "filter_applied": filter_criteria if filter_criteria else None,
                "statistics": {
                    "total_files": total_files,
                    "total_size_bytes": total_size,
                    "total_size_gb": round(total_size / (1024**3), 2),
                    "largest_file": largest_file,
                    "smallest_file": smallest_file,
                    "file_types": dict(file_types),
                    "size_distribution": size_buckets,
                    "date_range": {
                        "oldest_file": oldest_date.isoformat() if oldest_date else None,
                        "newest_file": newest_date.isoformat() if newest_date else None
                    }
                },
                "execution_info": {
                    "files_scanned": total_files + files_filtered,
                    "files_filtered": files_filtered,
                    "scan_duration_seconds": round(duration, 2),
                    "hit_file_limit": file_limit is not None and total_files >= file_limit
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


def _matches_filter(blob, filter_criteria: dict) -> bool:
    """Check if blob matches filter criteria."""
    if not filter_criteria:
        return True

    # Extension filter
    if "extensions" in filter_criteria:
        ext = _get_extension(blob['name'])
        if ext not in filter_criteria["extensions"]:
            return False

    # Size filters
    size_mb = blob['size'] / (1024 * 1024)
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
