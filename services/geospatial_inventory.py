"""
Geospatial Inventory Service.

Classification and collection grouping for container blobs.

Provides handlers for inventory_container_geospatial job:
    - classify_geospatial_file: Per-blob classification
    - aggregate_geospatial_inventory: Group into collections

Exports:
    classify_geospatial_file: Classify individual geospatial files
    aggregate_geospatial_inventory: Aggregate files into collections
"""

import re
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict
from datetime import datetime

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "geospatial_inventory")


# ============================================================================
# FILE TYPE REGISTRY (Extensible)
# ============================================================================

# Phase 1: Raster focus (current implementation)
RASTER_EXTENSIONS = {'.tif', '.tiff'}

# Raster sidecar files (metadata companions)
RASTER_SIDECAR_EXTENSIONS = {
    '.xml',   # GDAL/vendor metadata
    '.imd',   # Maxar image metadata
    '.rpb',   # Rational polynomial coefficients
    '.til',   # Tile manifest
    '.ovr',   # Overviews
    '.aux',   # Auxiliary data
    '.prj',   # Projection file
    '.tfw',   # World file
    '.wld',   # World file (alternate)
}

# Manifest files (vendor delivery descriptors)
MANIFEST_EXTENSIONS = {'.man', '.json', '.xml'}
MANIFEST_FILENAMES = {'delivery.json', 'manifest.json', 'delivery.xml', 'manifest.xml'}

# Phase 2+: Future extensions (placeholders for extensibility)
VECTOR_EXTENSIONS = {'.shp', '.gpkg', '.geojson', '.gdb', '.kml'}
VECTOR_SIDECAR_EXTENSIONS = {'.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx'}
CLOUD_NATIVE_EXTENSIONS = {'.parquet', '.geoparquet', '.zarr'}


# ============================================================================
# VENDOR PATTERN REGISTRY (Extensible)
# ============================================================================

VENDOR_PATTERNS = {
    'maxar_delivery': {
        'description': 'Maxar satellite imagery delivery',
        'folder_pattern': r'^\d{15,}$',  # 15+ digit numeric order ID
        'manifest_extensions': {'.man', '.xml'},
        'collection_id_template': 'maxar_{folder}',
        'priority': 1,  # Higher priority = checked first
    },
    'vivid_basemap': {
        'description': 'Maxar Vivid basemap tiles',
        'folder_pattern': r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',  # UUID
        'filename_pattern': r'Vivid_Standard',
        'collection_id_template': 'vivid_{region}_{quarter}',
        'priority': 2,
    },
    'tile_grid': {
        'description': 'Tile grid naming pattern',
        'filename_pattern': r'[Rr](\d+)[Cc](\d+)',  # R{row}C{col}
        'collection_id_template': '{prefix}_tiles',
        'priority': 3,
    },
    'xy_tiles': {
        'description': 'X/Y coordinate tiles',
        'filename_pattern': r'[Xx](\d+)[_-]?[Yy](\d+)',  # X{x}_Y{y} or X{x}Y{y}
        'collection_id_template': '{prefix}_tiles',
        'priority': 3,
    },
    'numbered_tiles': {
        'description': 'Sequentially numbered tiles',
        'filename_pattern': r'tile[_-]?(\d{3,})',  # tile_001, tile001, tile-001
        'collection_id_template': '{prefix}_tiles',
        'priority': 4,
    },
}


# ============================================================================
# STAGE 2 HANDLER: classify_geospatial_file (Fan-Out)
# ============================================================================

def classify_geospatial_file(params: dict) -> Dict[str, Any]:
    """
    Stage 2 Handler: Classify a single blob as geospatial file type.

    Called once per blob in parallel (fan-out pattern).

    Args:
        params: {
            "blob_name": str,          # Full blob path
            "size_bytes": int,         # File size
            "last_modified": str,      # ISO timestamp
            "content_type": str,       # MIME type
            "container_name": str,     # For context
            "job_parameters": dict     # Original job params
        }

    Returns:
        {
            "success": True,
            "result": {
                "blob_name": str,
                "size_mb": float,
                "extension": str,
                "file_type": str,       # raster | vector | sidecar | manifest | unknown
                "folder_path": str,
                "base_name": str,
                "detected_pattern": str | None,
                "pattern_details": dict | None,
                "is_sidecar": bool,
                "metadata": dict
            }
        }
    """
    try:
        blob_name = params.get("blob_name", "")
        size_bytes = params.get("size_bytes", 0)
        last_modified = params.get("last_modified")
        content_type = params.get("content_type")

        # Parse blob path
        if "/" in blob_name:
            parts = blob_name.rsplit("/", 1)
            folder_path = parts[0] + "/"
            filename = parts[1]
        else:
            folder_path = ""
            filename = blob_name

        # Extract extension and base name
        if "." in filename:
            base_name, ext = filename.rsplit(".", 1)
            extension = "." + ext.lower()
        else:
            base_name = filename
            extension = ""

        # Calculate size in MB
        size_mb = round(size_bytes / (1024 * 1024), 4) if size_bytes else 0.0

        # Classify file type
        file_type = _classify_file_type(extension, filename)

        # Detect vendor pattern
        detected_pattern, pattern_details = _detect_vendor_pattern(folder_path, filename)

        # Check if this is a sidecar file
        is_sidecar = extension.lower() in RASTER_SIDECAR_EXTENSIONS

        result = {
            "blob_name": blob_name,
            "size_bytes": size_bytes,
            "size_mb": size_mb,
            "extension": extension,
            "file_type": file_type,
            "folder_path": folder_path,
            "base_name": base_name,
            "filename": filename,
            "detected_pattern": detected_pattern,
            "pattern_details": pattern_details,
            "is_sidecar": is_sidecar,
            "metadata": {
                "last_modified": last_modified,
                "content_type": content_type
            }
        }

        return {"success": True, "result": result}

    except Exception as e:
        logger.error(f"Classification failed for {params.get('blob_name')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "blob_name": params.get("blob_name")
        }


def _classify_file_type(extension: str, filename: str) -> str:
    """Classify file by extension into geospatial type."""
    ext_lower = extension.lower()
    filename_lower = filename.lower()

    # Check raster
    if ext_lower in RASTER_EXTENSIONS:
        return "raster"

    # Check manifest (by extension or filename)
    if ext_lower in MANIFEST_EXTENSIONS:
        if ext_lower == '.man':
            return "manifest"
        if filename_lower in MANIFEST_FILENAMES:
            return "manifest"
        # .json and .xml could be metadata too
        return "metadata"

    # Check sidecar
    if ext_lower in RASTER_SIDECAR_EXTENSIONS:
        return "sidecar"

    # Check vector (future)
    if ext_lower in VECTOR_EXTENSIONS:
        return "vector"

    # Check vector sidecar
    if ext_lower in VECTOR_SIDECAR_EXTENSIONS:
        return "sidecar"

    # Check cloud-native (future)
    if ext_lower in CLOUD_NATIVE_EXTENSIONS:
        return "cloud_native"

    return "unknown"


def _detect_vendor_pattern(folder_path: str, filename: str) -> tuple:
    """
    Detect vendor delivery pattern from folder structure and filename.

    Returns:
        (pattern_name, pattern_details) or (None, None)
    """
    # Get top-level folder
    if folder_path:
        top_folder = folder_path.split("/")[0]
    else:
        top_folder = ""

    # Check patterns in priority order
    sorted_patterns = sorted(
        VENDOR_PATTERNS.items(),
        key=lambda x: x[1].get('priority', 99)
    )

    for pattern_name, pattern_config in sorted_patterns:
        # Check folder pattern
        if 'folder_pattern' in pattern_config and top_folder:
            if re.match(pattern_config['folder_pattern'], top_folder):
                return pattern_name, {
                    "matched_by": "folder",
                    "folder": top_folder,
                    "description": pattern_config.get('description')
                }

        # Check filename pattern
        if 'filename_pattern' in pattern_config:
            match = re.search(pattern_config['filename_pattern'], filename)
            if match:
                return pattern_name, {
                    "matched_by": "filename",
                    "match_groups": match.groups(),
                    "description": pattern_config.get('description')
                }

    return None, None


# ============================================================================
# STAGE 3 HANDLER: aggregate_geospatial_inventory (Fan-In)
# ============================================================================

def aggregate_geospatial_inventory(params: dict) -> Dict[str, Any]:
    """
    Stage 3 Handler: Aggregate classifications into grouped inventory.

    Receives ALL Stage 2 results and produces final inventory report.

    Args:
        params: {
            "previous_results": [
                {"success": True, "result": {...}},
                ...
            ],
            "job_parameters": {
                "container_name": str,
                "grouping_mode": str,
                "min_collection_size": int,
                "include_unrecognized": bool
            }
        }

    Returns:
        {
            "success": True,
            "result": {
                "summary": {...},
                "raster_collections": [...],
                "raster_singles": [...],
                "unrecognized": [...],
                "patterns_detected": {...}
            }
        }
    """
    try:
        previous_results = params.get("previous_results", [])
        job_params = params.get("job_parameters", {})

        container_name = job_params.get("container_name", "unknown")
        grouping_mode = job_params.get("grouping_mode", "auto")
        min_collection_size = job_params.get("min_collection_size", 2)
        include_unrecognized = job_params.get("include_unrecognized", True)

        logger.info(f"Aggregating {len(previous_results)} classifications (mode={grouping_mode})")

        # Extract successful classifications
        classifications = []
        failed_count = 0
        for pr in previous_results:
            if pr.get("success") and pr.get("result"):
                classifications.append(pr["result"])
            else:
                failed_count += 1

        if failed_count > 0:
            logger.warning(f"{failed_count} classifications failed")

        # Separate by file type
        rasters = [c for c in classifications if c["file_type"] == "raster"]
        sidecars = [c for c in classifications if c["file_type"] == "sidecar"]
        manifests = [c for c in classifications if c["file_type"] == "manifest"]
        metadata_files = [c for c in classifications if c["file_type"] == "metadata"]
        vectors = [c for c in classifications if c["file_type"] == "vector"]
        unknown = [c for c in classifications if c["file_type"] == "unknown"]

        logger.info(f"File types: {len(rasters)} rasters, {len(sidecars)} sidecars, "
                   f"{len(manifests)} manifests, {len(vectors)} vectors, {len(unknown)} unknown")

        # Group rasters into collections
        collections, singles = _group_rasters(
            rasters=rasters,
            sidecars=sidecars,
            manifests=manifests,
            grouping_mode=grouping_mode,
            min_collection_size=min_collection_size
        )

        # Associate sidecars with their parent files
        singles_with_sidecars = _associate_sidecars(singles, sidecars)

        # Calculate pattern statistics
        patterns_detected = _calculate_pattern_stats(rasters)

        # Build summary
        total_size_bytes = sum(c.get("size_bytes", 0) for c in classifications)
        summary = {
            "total_blobs_scanned": len(classifications),
            "total_size_gb": round(total_size_bytes / (1024**3), 3),
            "raster_files": len(rasters),
            "sidecar_files": len(sidecars),
            "manifest_files": len(manifests),
            "metadata_files": len(metadata_files),
            "vector_files": len(vectors),
            "unrecognized_files": len(unknown),
            "failed_classifications": failed_count,
            "collections_detected": len(collections),
            "singles_detected": len(singles_with_sidecars)
        }

        # Build unrecognized list (if requested)
        unrecognized_list = []
        if include_unrecognized:
            unrecognized_list = [
                {
                    "blob_name": u["blob_name"],
                    "size_mb": u["size_mb"],
                    "extension": u["extension"]
                }
                for u in unknown
            ]

        # Processing recommendations
        processing_recommendations = {
            "collection_jobs": len(collections),
            "single_file_jobs": len(singles_with_sidecars),
            "estimated_total_tasks": len(collections) + len(singles_with_sidecars),
            "total_raster_tiles": sum(c["tile_count"] for c in collections) + len(singles_with_sidecars)
        }

        result = {
            "container_name": container_name,
            "prefix_scanned": job_params.get("prefix"),
            "scan_timestamp": datetime.utcnow().isoformat() + "Z",
            "grouping_mode": grouping_mode,
            "summary": summary,
            "raster_collections": collections,
            "raster_singles": singles_with_sidecars,
            "unrecognized": unrecognized_list,
            "patterns_detected": patterns_detected,
            "processing_recommendations": processing_recommendations
        }

        logger.info(f"Inventory complete: {len(collections)} collections, "
                   f"{len(singles_with_sidecars)} singles")

        return {"success": True, "result": result}

    except Exception as e:
        logger.error(f"Aggregation failed: {e}")
        import traceback
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }


# ============================================================================
# GROUPING HELPERS
# ============================================================================

def _group_rasters(
    rasters: List[Dict],
    sidecars: List[Dict],
    manifests: List[Dict],
    grouping_mode: str,
    min_collection_size: int
) -> tuple:
    """
    Group rasters into collections based on grouping mode.

    Returns:
        (collections_list, singles_list)
    """
    if grouping_mode == "all_singles":
        # Force all as singles
        return [], rasters

    if grouping_mode == "all_collection":
        # Force all as one collection
        if len(rasters) >= min_collection_size:
            collection = _build_collection(
                collection_id="all_rasters",
                pattern_type="all_collection",
                rasters=rasters,
                manifests=[],
                sidecars=sidecars
            )
            return [collection], []
        else:
            return [], rasters

    # Build manifest lookup
    manifest_by_folder = defaultdict(list)
    for m in manifests:
        manifest_by_folder[m["folder_path"]].append(m)

    # Group by folder
    rasters_by_folder = defaultdict(list)
    for r in rasters:
        rasters_by_folder[r["folder_path"]].append(r)

    collections = []
    singles = []

    for folder_path, folder_rasters in rasters_by_folder.items():
        # Check for manifest-based grouping
        folder_manifests = manifest_by_folder.get(folder_path, [])

        if grouping_mode in ("auto", "manifest") and folder_manifests:
            # Manifest-defined collection
            if len(folder_rasters) >= min_collection_size:
                collection = _build_collection_from_manifest(
                    folder_path=folder_path,
                    rasters=folder_rasters,
                    manifests=folder_manifests,
                    sidecars=sidecars
                )
                collections.append(collection)
            else:
                singles.extend(folder_rasters)

        elif grouping_mode in ("auto", "folder") and len(folder_rasters) >= min_collection_size:
            # Folder-based collection
            collection = _build_collection_from_folder(
                folder_path=folder_path,
                rasters=folder_rasters,
                sidecars=sidecars
            )
            collections.append(collection)

        elif grouping_mode in ("auto", "prefix"):
            # Try prefix-based grouping within folder
            prefix_groups = _group_by_prefix(folder_rasters)
            for prefix, group_rasters in prefix_groups.items():
                if len(group_rasters) >= min_collection_size:
                    collection = _build_collection(
                        collection_id=f"{prefix}_tiles",
                        pattern_type="prefix_grouped",
                        rasters=group_rasters,
                        manifests=[],
                        sidecars=sidecars
                    )
                    collections.append(collection)
                else:
                    singles.extend(group_rasters)

        else:
            # All become singles
            singles.extend(folder_rasters)

    return collections, singles


def _build_collection_from_manifest(
    folder_path: str,
    rasters: List[Dict],
    manifests: List[Dict],
    sidecars: List[Dict]
) -> Dict[str, Any]:
    """Build collection from manifest-defined delivery."""
    # Detect pattern from first raster
    pattern_type = "manifest_defined"
    if rasters and rasters[0].get("detected_pattern"):
        pattern_type = rasters[0]["detected_pattern"]

    # Generate collection ID
    folder_name = folder_path.rstrip("/").split("/")[-1] if folder_path else "root"
    collection_id = f"{pattern_type}_{folder_name}"

    # Find manifest file
    manifest_file = manifests[0]["blob_name"] if manifests else None

    return _build_collection(
        collection_id=collection_id,
        pattern_type=pattern_type,
        rasters=rasters,
        manifests=manifests,
        sidecars=sidecars,
        folder_path=folder_path,
        manifest_file=manifest_file
    )


def _build_collection_from_folder(
    folder_path: str,
    rasters: List[Dict],
    sidecars: List[Dict]
) -> Dict[str, Any]:
    """Build collection from folder grouping."""
    folder_name = folder_path.rstrip("/").split("/")[-1] if folder_path else "root"

    # Check if rasters have detected pattern
    pattern_type = "folder_grouped"
    if rasters and rasters[0].get("detected_pattern"):
        pattern_type = rasters[0]["detected_pattern"]

    collection_id = f"{folder_name}_tiles"

    return _build_collection(
        collection_id=collection_id,
        pattern_type=pattern_type,
        rasters=rasters,
        manifests=[],
        sidecars=sidecars,
        folder_path=folder_path
    )


def _build_collection(
    collection_id: str,
    pattern_type: str,
    rasters: List[Dict],
    manifests: List[Dict],
    sidecars: List[Dict],
    folder_path: str = None,
    manifest_file: str = None
) -> Dict[str, Any]:
    """Build a collection object."""
    blob_list = [r["blob_name"] for r in rasters]
    total_size_mb = sum(r.get("size_mb", 0) for r in rasters)

    # Find related sidecars
    raster_basenames = {r["base_name"] for r in rasters}
    related_sidecars = [
        s["blob_name"] for s in sidecars
        if s["base_name"] in raster_basenames
    ]

    # Find metadata files (sidecars in same folder)
    folder_sidecars = [s for s in sidecars if s.get("folder_path") == folder_path]
    metadata_files = [s["blob_name"] for s in folder_sidecars]

    return {
        "collection_id": collection_id,
        "pattern_type": pattern_type,
        "folder_path": folder_path,
        "blob_list": blob_list,
        "tile_count": len(blob_list),
        "total_size_mb": round(total_size_mb, 2),
        "manifest_file": manifest_file,
        "metadata_files": metadata_files,
        "recommended_job": "process_raster_collection_v2"
    }


def _group_by_prefix(rasters: List[Dict]) -> Dict[str, List[Dict]]:
    """Group rasters by common filename prefix."""
    # Extract potential prefixes (everything before last underscore/dash + numbers)
    prefix_groups = defaultdict(list)

    for r in rasters:
        base_name = r.get("base_name", "")

        # Try to extract prefix (remove trailing numbers/tile identifiers)
        prefix = re.sub(r'[_-]?\d+$', '', base_name)
        prefix = re.sub(r'[_-]?tile[_-]?\d*$', '', prefix, flags=re.IGNORECASE)
        prefix = re.sub(r'[_-]?[Rr]\d+[Cc]\d+$', '', prefix)
        prefix = re.sub(r'[_-]?[Xx]\d+[_-]?[Yy]\d+$', '', prefix)

        if prefix:
            prefix_groups[prefix].append(r)
        else:
            # No prefix detected, use full base_name
            prefix_groups[base_name].append(r)

    return dict(prefix_groups)


def _associate_sidecars(singles: List[Dict], sidecars: List[Dict]) -> List[Dict]:
    """Associate sidecar files with their parent raster files."""
    # Build sidecar lookup by base_name and folder
    sidecar_lookup = defaultdict(list)
    for s in sidecars:
        key = (s.get("folder_path", ""), s.get("base_name", ""))
        sidecar_lookup[key].append(s["blob_name"])

    result = []
    for single in singles:
        key = (single.get("folder_path", ""), single.get("base_name", ""))
        related_sidecars = sidecar_lookup.get(key, [])

        result.append({
            "blob_name": single["blob_name"],
            "size_mb": single.get("size_mb", 0),
            "detected_type": _guess_raster_type(single),
            "sidecar_files": related_sidecars,
            "detected_pattern": single.get("detected_pattern"),
            "recommended_job": "process_raster_v2"
        })

    return result


def _guess_raster_type(raster: Dict) -> str:
    """Guess raster type from filename heuristics."""
    filename_lower = raster.get("filename", "").lower()
    base_name_lower = raster.get("base_name", "").lower()

    # DEM detection
    if any(term in filename_lower for term in ['dem', 'dtm', 'dsm', 'elevation', 'height']):
        return "likely_dem"

    # RGB/imagery detection
    if any(term in filename_lower for term in ['rgb', 'ortho', 'aerial', 'satellite', 'imagery']):
        return "likely_rgb"

    # Multispectral detection
    if any(term in filename_lower for term in ['multi', 'spectral', 'landsat', 'sentinel']):
        return "likely_multispectral"

    # Large files are often imagery
    size_mb = raster.get("size_mb", 0)
    if size_mb > 100:
        return "likely_imagery"

    return "unknown"


def _calculate_pattern_stats(rasters: List[Dict]) -> Dict[str, Dict]:
    """Calculate statistics for detected patterns."""
    pattern_stats = defaultdict(lambda: {"count": 0, "total_tiles": 0, "total_size_mb": 0})

    for r in rasters:
        pattern = r.get("detected_pattern") or "no_pattern"
        pattern_stats[pattern]["count"] += 1
        pattern_stats[pattern]["total_tiles"] += 1
        pattern_stats[pattern]["total_size_mb"] += r.get("size_mb", 0)

    # Round sizes
    for stats in pattern_stats.values():
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)

    return dict(pattern_stats)
