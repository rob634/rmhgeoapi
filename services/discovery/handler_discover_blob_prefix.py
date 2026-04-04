# ============================================================================
# CLAUDE CONTEXT - DISCOVER BLOB PREFIX HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Scan blob prefix and categorize file inventory
# PURPOSE: List all blobs under a container+prefix, categorize by extension
#          into raster, archive, metadata, preview, shapefile, and other.
# CREATED: 03 APR 2026
# EXPORTS: discover_blob_prefix
# DEPENDENCIES: infrastructure.blob.BlobRepository
# ============================================================================
"""
Discover Blob Prefix -- scan a container prefix and return categorized inventory.

Pure listing operation -- no downloads, no mutations. Cross-container capable
via optional source_container param (defaults to container_name).
"""

import logging
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RASTER_EXTENSIONS = frozenset({".tif", ".tiff", ".geotiff", ".img", ".vrt", ".ecw", ".jp2", ".sid"})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".tar", ".gz", ".tar.gz", ".tgz"})
METADATA_EXTENSIONS = frozenset({".json", ".xml", ".imd", ".rpb", ".til", ".man", ".txt"})
PREVIEW_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
SHAPEFILE_EXTENSIONS = frozenset({".shp", ".shx", ".dbf", ".prj", ".cpg"})


def discover_blob_prefix(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Scan a container+prefix and return a categorized file inventory.

    Params:
        container_name (str, required): Target container for downstream processing.
        prefix (str, required): Blob prefix to scan.
        source_container (str, optional): Container to list from. Defaults to container_name.

    Returns:
        Success: {"success": True, "result": {"blobs": [...], "inventory": {...}, ...}}
    """
    container_name = params.get("container_name")
    prefix = params.get("prefix")
    source_container = params.get("source_container") or container_name

    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not prefix:
        return {"success": False, "error": "prefix is required",
                "error_type": "ValidationError", "retryable": False}

    from infrastructure.blob import BlobRepository

    blob_repo = BlobRepository.for_zone("bronze")
    raw_blobs = blob_repo.list_blobs(source_container, prefix=prefix)

    blobs = []
    inventory = {
        "raster_files": [],
        "archive_files": [],
        "metadata_files": [],
        "preview_files": [],
        "shapefile_groups": {},
        "other": [],
    }

    for blob in raw_blobs:
        name = blob.get("name", "")
        size = blob.get("size", 0) or 0
        path = PurePosixPath(name)
        ext = path.suffix.lower()
        stem = path.stem

        entry = {
            "name": name,
            "size_bytes": size,
            "extension": ext,
            "stem": stem,
        }
        blobs.append(entry)

        # Skip zero-length "directory" blobs (Azure flat-namespace markers)
        if size == 0 and ext == "":
            continue

        if ext in RASTER_EXTENSIONS:
            inventory["raster_files"].append(entry)
        elif ext in ARCHIVE_EXTENSIONS:
            inventory["archive_files"].append(entry)
        elif ext in METADATA_EXTENSIONS:
            inventory["metadata_files"].append(entry)
        elif ext in PREVIEW_EXTENSIONS:
            inventory["preview_files"].append(entry)
        elif ext in SHAPEFILE_EXTENSIONS:
            # Group shapefiles by stem
            # Use the full path minus extension as key to handle nested paths
            group_key = str(path.parent / stem)
            if group_key not in inventory["shapefile_groups"]:
                inventory["shapefile_groups"][group_key] = []
            inventory["shapefile_groups"][group_key].append(entry)
        else:
            inventory["other"].append(entry)

    total_size = sum(b["size_bytes"] for b in blobs)

    logger.info(
        "discover_blob_prefix: %s/%s — %d blobs, %d rasters, %d archives, "
        "%d metadata, %d previews, %d shapefile groups, %d other (%.1f MB total)",
        source_container, prefix, len(blobs),
        len(inventory["raster_files"]),
        len(inventory["archive_files"]),
        len(inventory["metadata_files"]),
        len(inventory["preview_files"]),
        len(inventory["shapefile_groups"]),
        len(inventory["other"]),
        total_size / (1024 * 1024),
    )

    return {
        "success": True,
        "result": {
            "blobs": blobs,
            "inventory": inventory,
            "source_container": source_container,
            "prefix": prefix,
            "total_count": len(blobs),
            "total_size_bytes": total_size,
        },
    }
