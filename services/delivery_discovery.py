# ============================================================================
# DELIVERY DISCOVERY SERVICE
# ============================================================================
# STATUS: Services - Vendor delivery folder structure analysis
# PURPOSE: Detect manifests, tile patterns, vendor types (Maxar, Vivid)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Vendor Delivery Discovery Service.

Analyzes vendor delivery folder structures to detect:
    - Manifest files (.MAN, .json, .xml, delivery.txt, .til)
    - Tile patterns (R{row}C{col}, X{x}_Y{y}, tile_0001)
    - Vendor delivery types (Maxar, Vivid, custom)

Pure Python functions (no I/O) returning structured dicts.

Exports:
    detect_manifest_files: Find manifest files in blob list
    detect_tile_pattern: Analyze tile naming conventions
    analyze_delivery_structure: Full delivery analysis
"""

from typing import Dict, List, Any, Optional, Tuple
import re
from collections import defaultdict
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "DeliveryDiscovery")


# =============================================================================
# MANIFEST FILE DETECTION
# =============================================================================

def detect_manifest_files(blob_list: List[str]) -> Dict[str, Any]:
    """
    Scan blob list for manifest files.

    Detects common manifest file patterns:
    - .MAN files (Maxar/vendor manifests)
    - delivery.json, manifest.json
    - delivery.xml, manifest.xml
    - README.txt, delivery.txt, DELIVERY.txt
    - .til files (tile manifests)

    Args:
        blob_list: List of blob paths (strings)

    Returns:
        {
            "manifest_found": bool,
            "manifest_type": "maxar_man" | "json" | "xml" | "text" | "til" | None,
            "manifest_path": str | None,
            "additional_manifests": [str, ...],
            "total_manifests": int
        }

    Examples:
        >>> blobs = ["folder/data.tif", "folder/delivery.MAN", "folder/R1C1.tif"]
        >>> result = detect_manifest_files(blobs)
        >>> result['manifest_found']
        True
        >>> result['manifest_type']
        'maxar_man'
    """
    logger.info(f"🔍 Scanning {len(blob_list)} blobs for manifest files...")

    manifest_patterns = {
        'maxar_man': re.compile(r'\.MAN$', re.IGNORECASE),
        'json': re.compile(r'(delivery|manifest)\.json$', re.IGNORECASE),
        'xml': re.compile(r'(delivery|manifest)\.xml$', re.IGNORECASE),
        'text': re.compile(r'(README|delivery|DELIVERY)\.txt$', re.IGNORECASE),
        'til': re.compile(r'\.til$', re.IGNORECASE)
    }

    found_manifests = defaultdict(list)

    for blob_path in blob_list:
        # Check each pattern
        for manifest_type, pattern in manifest_patterns.items():
            if pattern.search(blob_path):
                found_manifests[manifest_type].append(blob_path)
                logger.info(f"✅ Found {manifest_type} manifest: {blob_path}")

    # Determine primary manifest (priority order)
    primary_type = None
    primary_path = None
    priority_order = ['maxar_man', 'json', 'xml', 'til', 'text']

    for manifest_type in priority_order:
        if found_manifests[manifest_type]:
            primary_type = manifest_type
            primary_path = found_manifests[manifest_type][0]  # First one found
            break

    # Collect additional manifests
    additional = []
    for manifest_type, paths in found_manifests.items():
        if manifest_type == primary_type:
            additional.extend(paths[1:])  # Skip first (primary)
        else:
            additional.extend(paths)

    result = {
        "manifest_found": primary_type is not None,
        "manifest_type": primary_type,
        "manifest_path": primary_path,
        "additional_manifests": additional,
        "total_manifests": sum(len(paths) for paths in found_manifests.values())
    }

    if result['manifest_found']:
        logger.info(f"✅ Manifest detection complete: {result['manifest_type']} - {result['manifest_path']}")
    else:
        logger.warning(f"⚠️ No manifest files found in {len(blob_list)} blobs")

    return result


# =============================================================================
# TILE PATTERN DETECTION
# =============================================================================

def detect_tile_pattern(raster_files: List[str]) -> Dict[str, Any]:
    """
    Detect tiling pattern from raster filenames.

    Supported patterns:
    - Maxar: R{row}C{col} (e.g., R1C1, R2C3, R10C25)
    - Generic XY: X{x}_Y{y} (e.g., X100_Y200, X0_Y0)
    - TMS: {z}/{x}/{y}.tif (e.g., 12/1024/2048.tif)
    - Sequential: tile_0001.tif, tile_0002.tif

    Args:
        raster_files: List of raster file paths (filtered for .tif, .tiff)

    Returns:
        {
            "pattern_detected": bool,
            "pattern_type": "row_col" | "xy_coord" | "tms" | "sequential" | None,
            "pattern_regex": str,
            "total_tiles": int,
            "grid_dimensions": {"rows": int, "cols": int} | None,
            "examples": [str, ...],
            "tile_coordinates": [{"file": str, "row": int, "col": int}, ...]
        }

    Examples:
        >>> files = ["R1C1.tif", "R1C2.tif", "R2C1.tif"]
        >>> result = detect_tile_pattern(files)
        >>> result['pattern_type']
        'row_col'
        >>> result['grid_dimensions']
        {'rows': 2, 'cols': 2}
    """
    logger.info(f"🔍 Analyzing {len(raster_files)} raster files for tile patterns...")

    if not raster_files:
        return {
            "pattern_detected": False,
            "pattern_type": None,
            "pattern_regex": None,
            "total_tiles": 0,
            "grid_dimensions": None,
            "examples": [],
            "tile_coordinates": []
        }

    # Pattern definitions with regex
    patterns = {
        'row_col': {
            'regex': re.compile(r'R(\d+)C(\d+)', re.IGNORECASE),
            'description': 'Maxar R{row}C{col} pattern',
            'extract': lambda m: {'row': int(m.group(1)), 'col': int(m.group(2))}
        },
        'xy_coord': {
            'regex': re.compile(r'X(\d+)_Y(\d+)', re.IGNORECASE),
            'description': 'Generic X{x}_Y{y} pattern',
            'extract': lambda m: {'x': int(m.group(1)), 'y': int(m.group(2))}
        },
        'tms': {
            'regex': re.compile(r'(\d+)/(\d+)/(\d+)\.tif', re.IGNORECASE),
            'description': 'TMS {z}/{x}/{y}.tif pattern',
            'extract': lambda m: {'z': int(m.group(1)), 'x': int(m.group(2)), 'y': int(m.group(3))}
        },
        'sequential': {
            'regex': re.compile(r'tile_(\d{4,})', re.IGNORECASE),
            'description': 'Sequential tile_NNNN pattern',
            'extract': lambda m: {'index': int(m.group(1))}
        }
    }

    # Try each pattern
    for pattern_type, pattern_def in patterns.items():
        matches = []
        tile_coords = []

        for file_path in raster_files:
            match = pattern_def['regex'].search(file_path)
            if match:
                matches.append(file_path)
                coords = pattern_def['extract'](match)
                coords['file'] = file_path
                tile_coords.append(coords)

        # If majority of files match this pattern, consider it detected
        match_percentage = len(matches) / len(raster_files) if raster_files else 0

        if match_percentage >= 0.5:  # 50% threshold
            logger.info(f"✅ Pattern detected: {pattern_type} ({len(matches)}/{len(raster_files)} files)")

            # Calculate grid dimensions (for row_col pattern)
            grid_dims = None
            if pattern_type == 'row_col' and tile_coords:
                rows = [coord['row'] for coord in tile_coords]
                cols = [coord['col'] for coord in tile_coords]
                grid_dims = {
                    'rows': max(rows) if rows else 0,
                    'cols': max(cols) if cols else 0,
                    'min_row': min(rows) if rows else 0,
                    'min_col': min(cols) if cols else 0
                }

            return {
                "pattern_detected": True,
                "pattern_type": pattern_type,
                "pattern_regex": pattern_def['regex'].pattern,
                "pattern_description": pattern_def['description'],
                "total_tiles": len(matches),
                "match_percentage": round(match_percentage * 100, 1),
                "grid_dimensions": grid_dims,
                "examples": matches[:5],  # First 5 examples
                "tile_coordinates": tile_coords[:20]  # First 20 for analysis
            }

    logger.warning(f"⚠️ No recognized tile pattern found in {len(raster_files)} files")

    return {
        "pattern_detected": False,
        "pattern_type": None,
        "pattern_regex": None,
        "total_tiles": len(raster_files),
        "grid_dimensions": None,
        "examples": raster_files[:5],
        "tile_coordinates": []
    }


# =============================================================================
# DELIVERY STRUCTURE ANALYSIS
# =============================================================================

def analyze_delivery_structure(blob_list: List[str], folder_path: str = None) -> Dict[str, Any]:
    """
    Analyze vendor delivery folder structure.

    Combines manifest detection and tile pattern analysis to identify
    delivery type and provide processing recommendations.

    Args:
        blob_list: List of blob paths to analyze
        folder_path: Optional folder path being analyzed (for context)

    Returns:
        {
            "folder_path": str,
            "total_files": int,
            "delivery_type": "maxar_tiles" | "vivid_basemap" | "simple_folder" | "unknown",
            "manifest": {...},  # From detect_manifest_files()
            "tile_pattern": {...},  # From detect_tile_pattern()
            "file_inventory": {
                "raster_files": [str, ...],
                "metadata_files": [str, ...],
                "other_files": [str, ...],
                "total_rasters": int,
                "total_size_estimate": str
            },
            "recommended_workflow": {
                "job_type": "process_raster_collection",
                "parameters": {...}
            }
        }

    Examples:
        >>> blobs = ["folder/R1C1.tif", "folder/R1C2.tif", "folder/delivery.MAN"]
        >>> result = analyze_delivery_structure(blobs, "folder/")
        >>> result['delivery_type']
        'maxar_tiles'
        >>> result['recommended_workflow']['job_type']
        'process_raster_collection'
    """
    logger.info(f"🔍 Analyzing delivery structure: {len(blob_list)} files in {folder_path or 'unknown path'}")

    # Categorize files
    raster_extensions = {'.tif', '.tiff', '.img', '.vrt'}
    metadata_extensions = {'.xml', '.json', '.txt', '.man', '.til'}

    raster_files = []
    metadata_files = []
    other_files = []

    for blob_path in blob_list:
        ext = blob_path[blob_path.rfind('.'):].lower() if '.' in blob_path else ''

        if ext in raster_extensions:
            raster_files.append(blob_path)
        elif ext in metadata_extensions:
            metadata_files.append(blob_path)
        else:
            other_files.append(blob_path)

    logger.info(f"📊 File inventory: {len(raster_files)} rasters, {len(metadata_files)} metadata, {len(other_files)} other")

    # Detect manifest
    manifest_result = detect_manifest_files(blob_list)

    # Detect tile pattern
    tile_pattern = detect_tile_pattern(raster_files)

    # Determine delivery type
    delivery_type = "unknown"

    if manifest_result['manifest_type'] == 'maxar_man' and tile_pattern['pattern_type'] == 'row_col':
        delivery_type = "maxar_tiles"
    elif tile_pattern['pattern_type'] == 'tms':
        delivery_type = "vivid_basemap"
    elif tile_pattern['pattern_detected']:
        delivery_type = "tiled_delivery"
    elif len(raster_files) == 1:
        delivery_type = "single_file"
    elif len(raster_files) > 0:
        delivery_type = "simple_folder"

    logger.info(f"✅ Delivery type detected: {delivery_type}")

    # Build recommended workflow
    recommended_workflow = None

    if delivery_type in ['maxar_tiles', 'tiled_delivery', 'vivid_basemap']:
        recommended_workflow = {
            "job_type": "process_raster_collection",
            "parameters": {
                "blob_list": raster_files,
                "collection_id": f"{folder_path.replace('/', '_')}" if folder_path else "delivery",
                "output_tier": "analysis",
                "create_mosaicjson": True,
                "output_folder": f"cogs/{folder_path}" if folder_path else "cogs/delivery"
            },
            "description": f"Process {len(raster_files)} tiles as collection with MosaicJSON"
        }
    elif delivery_type == 'single_file':
        recommended_workflow = {
            "job_type": "process_raster",
            "parameters": {
                "blob_name": raster_files[0],
                "output_tier": "analysis",
                "output_folder": f"cogs/{folder_path}" if folder_path else "cogs"
            },
            "description": "Process single raster file"
        }
    elif delivery_type == 'simple_folder':
        recommended_workflow = {
            "job_type": "process_raster_collection",
            "parameters": {
                "blob_list": raster_files,
                "output_tier": "analysis",
                "output_folder": f"cogs/{folder_path}" if folder_path else "cogs"
            },
            "description": f"Process {len(raster_files)} rasters individually"
        }

    return {
        "folder_path": folder_path,
        "total_files": len(blob_list),
        "delivery_type": delivery_type,
        "manifest": manifest_result,
        "tile_pattern": tile_pattern,
        "file_inventory": {
            "raster_files": raster_files[:20],  # First 20 for preview
            "metadata_files": metadata_files,
            "other_files": other_files,
            "total_rasters": len(raster_files),
            "total_metadata": len(metadata_files),
            "total_other": len(other_files)
        },
        "recommended_workflow": recommended_workflow,
        "analysis_timestamp": datetime.now(timezone.utc).isoformat() + 'Z'
    }


# Import datetime for timestamp
from datetime import datetime, timezone
