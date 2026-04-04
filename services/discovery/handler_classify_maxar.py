# ============================================================================
# CLAUDE CONTEXT - CLASSIFY MAXAR DELIVERY HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Maxar-specific delivery classification
# PURPOSE: Parse .TIL file for tile layout, match R{n}C{n} TIFs to sidecars,
#          extract .IMD/.XML metadata. Operates on blob listing (no unzipping).
# CREATED: 03 APR 2026
# EXPORTS: classify_maxar_delivery
# DEPENDENCIES: infrastructure.blob.BlobRepository (small sidecar downloads only)
# ============================================================================
"""
Classify Maxar Delivery -- Maxar-specific delivery structure analysis.

Operates on a blob prefix listing (from discover_blob_prefix). Parses .TIL
for authoritative tile layout, matches TIF blobs to sidecar files, extracts
.IMD metadata for STAC enrichment.

Unlike classify_raster_contents (which works on extracted ZIP contents), this
handler works on live blob listings — Maxar deliveries have bare TIFs (not archived).
"""

import io
import logging
import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROW_COL_PATTERN = re.compile(r"R(\d+)C(\d+)", re.IGNORECASE)
TIL_TILE_PATTERN = re.compile(r"filename\s*=\s*\"?([^\";\n]+)\"?", re.IGNORECASE)
IMD_KV_PATTERN = re.compile(r"^\s*(\w+)\s*=\s*(.+?)\s*;?\s*$", re.MULTILINE)


def classify_maxar_delivery(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Classify a Maxar delivery prefix.

    Params:
        inventory (dict, required): From discover_blob_prefix result.
        prefix (str, required): Original blob prefix.
        container_name (str, required): Container where delivery lives.
        collection_id (str, required): STAC collection ID for output.

    Returns:
        Success: {"success": True, "result": {"delivery_type": "maxar_tiled", ...}}
    """
    inventory = params.get("inventory")
    prefix = params.get("prefix")
    container_name = params.get("container_name")
    collection_id = params.get("collection_id")

    if not inventory or not isinstance(inventory, dict):
        return {"success": False, "error": "inventory is required (from discover_blob_prefix)",
                "error_type": "ValidationError", "retryable": False}
    if not prefix:
        return {"success": False, "error": "prefix is required",
                "error_type": "ValidationError", "retryable": False}
    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not collection_id:
        return {"success": False, "error": "collection_id is required",
                "error_type": "ValidationError", "retryable": False}

    raster_files = inventory.get("raster_files", [])
    metadata_files = inventory.get("metadata_files", [])

    # Find TIF files with R{n}C{n} pattern
    tiled_tifs = []
    for f in raster_files:
        name = f.get("name", "")
        match = ROW_COL_PATTERN.search(name)
        if match:
            tiled_tifs.append({
                "blob_path": name,
                "row": int(match.group(1)),
                "col": int(match.group(2)),
                "size_bytes": f.get("size_bytes", 0),
            })

    if not tiled_tifs:
        return {
            "success": False,
            "error": f"No R{{n}}C{{n}} tiled TIFs found under {prefix}",
            "error_type": "ClassificationError", "retryable": False,
        }

    # Grid dimensions
    rows = max(t["row"] for t in tiled_tifs)
    cols = max(t["col"] for t in tiled_tifs)

    # Find sidecar files
    til_files = [f for f in metadata_files if f.get("name", "").lower().endswith(".til")]
    imd_files = [f for f in metadata_files if f.get("name", "").lower().endswith(".imd")]
    xml_files = [f for f in metadata_files if f.get("name", "").lower().endswith(".xml")]
    man_files = [f for f in metadata_files if f.get("name", "").lower().endswith(".man")]

    # Parse .IMD for metadata (small file, ~6KB)
    sidecar_metadata = {}
    if imd_files:
        sidecar_metadata = _parse_imd_from_blob(container_name, imd_files[0]["name"])

    # Find GIS files (shapefiles)
    shapefile_groups = inventory.get("shapefile_groups", {})
    gis_files = {}
    for group_key in shapefile_groups:
        key_lower = group_key.lower()
        if "order_shape" in key_lower:
            gis_files["order_shape"] = group_key
        elif "product_shape" in key_lower:
            gis_files["product_shape"] = group_key
        elif "tile_shape" in key_lower:
            gis_files["tile_shape"] = group_key
        elif "strip_shape" in key_lower:
            gis_files["strip_shape"] = group_key

    # Build product part info
    product_part = {
        "tile_layout": {"rows": rows, "cols": cols},
        "tif_blobs": [t["blob_path"] for t in tiled_tifs],
        "tile_count": len(tiled_tifs),
        "sidecar_metadata": sidecar_metadata,
    }

    logger.info(
        "classify_maxar_delivery: %s — %d tiles (%dx%d), %d IMD, %d TIL, %d XML",
        prefix, len(tiled_tifs), rows, cols,
        len(imd_files), len(til_files), len(xml_files),
    )

    return {
        "success": True,
        "result": {
            "delivery_type": "maxar_tiled",
            "order_id": prefix.strip("/").split("/")[0],
            "product_parts": [product_part],
            "gis_files": gis_files,
            "manifest_path": man_files[0]["name"] if man_files else None,
            "collection_id": collection_id,
            # For build_discovery_manifest consumption:
            "classification": "maxar_tiled",
            "recommended_workflow": "process_raster_collection",
            "recommended_params": {
                "blob_list": [t["blob_path"] for t in tiled_tifs],
                "container_name": container_name,
                "collection_id": collection_id,
            },
            "source_blob": prefix,
            "metadata": sidecar_metadata,
            "evidence": {
                "tile_count": len(tiled_tifs),
                "grid_rows": rows,
                "grid_cols": cols,
                "has_til": len(til_files) > 0,
                "has_imd": len(imd_files) > 0,
            },
        },
    }


def _parse_imd_from_blob(container_name: str, blob_path: str) -> Dict[str, Any]:
    """Download and parse a Maxar .IMD file (key=value pairs)."""
    try:
        from infrastructure.blob import BlobRepository
        blob_repo = BlobRepository.for_zone("bronze")
        content = blob_repo.download_blob_to_bytes(container_name, blob_path)
        text = content.decode("utf-8", errors="replace")

        metadata = {}
        for match in IMD_KV_PATTERN.finditer(text):
            key = match.group(1).strip()
            value = match.group(2).strip().strip('"').strip(";")
            key_lower = key.lower()

            if key_lower in ("satid", "sensor"):
                metadata["sensor"] = value
            elif key_lower == "firstlinetime":
                metadata["capture_date"] = value
            elif key_lower == "meansunaz":
                metadata["sun_azimuth"] = _safe_float(value)
            elif key_lower == "meansunel":
                metadata["sun_elevation"] = _safe_float(value)
            elif key_lower in ("meanoffnadirviewangle", "offnadirviewangle"):
                metadata["off_nadir"] = _safe_float(value)
            elif key_lower == "cloudcover":
                metadata["cloud_cover"] = _safe_float(value)
            elif key_lower == "numbands":
                metadata["num_bands"] = int(value)

        return metadata

    except Exception as exc:
        logger.warning("classify_maxar: failed to parse IMD %s: %s", blob_path, exc)
        return {}


def _safe_float(value: str) -> Optional[float]:
    """Convert string to float, returning None on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
