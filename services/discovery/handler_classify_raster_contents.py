# ============================================================================
# CLAUDE CONTEXT - CLASSIFY RASTER CONTENTS HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Classify extracted directory contents
# PURPOSE: Given a file listing from unzipped archive, classify as
#          maxar_tiled, single_geotiff, multi_geotiff, non_raster, or unclassifiable.
# CREATED: 03 APR 2026
# EXPORTS: classify_raster_contents
# DEPENDENCIES: None (pure logic, no I/O)
# ============================================================================
"""
Classify Raster Contents -- determine what type of raster data is in a directory.

Pure classification logic. No I/O -- operates on a pre-built file listing.
Used inside wbg_process_single_pair composite handler and available standalone
for future discovery workflows.

Classification priority:
  1. maxar_tiled  -- .TIL present AND R{n}C{n} pattern in TIFs
  2. single_geotiff -- exactly 1 raster file
  3. multi_geotiff -- 2+ raster files, no tiling pattern
  4. non_raster -- no recognized raster files (ECW/JP2 detected but flagged)
  5. unclassifiable -- empty or doesn't fit any pattern
"""

import logging
import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RASTER_EXTENSIONS = frozenset({".tif", ".tiff", ".geotiff", ".img", ".vrt"})
PROCESSABLE_NON_NATIVE = frozenset({".ecw", ".sid", ".jp2"})
SIDECAR_EXTENSIONS = frozenset({".xml", ".imd", ".rpb", ".til", ".tfw", ".prj", ".man", ".txt"})
ROW_COL_PATTERN = re.compile(r"R(\d+)C(\d+)", re.IGNORECASE)


def classify_raster_contents(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Classify extracted directory contents.

    Params:
        contents (list[dict], required): File listing from unzip_to_mount.
            Each dict has: relative_path, size_bytes, extension.
        extract_path (str, optional): Mount path where files were extracted.
        metadata_json (dict, optional): Pre-extracted JSON sidecar from WBG.

    Returns:
        Success: {"success": True, "result": {"classification": "...", ...}}
    """
    contents = params.get("contents")
    extract_path = params.get("extract_path", "")
    metadata_json = params.get("metadata_json")

    if not contents or not isinstance(contents, list):
        return {
            "success": True,
            "result": {
                "classification": "unclassifiable",
                "evidence": {"reason": "empty or missing contents list"},
                "raster_files": [],
                "sidecar_files": [],
                "recommended_workflow": None,
                "recommended_params": {},
            },
        }

    # Categorize files
    raster_files = []
    non_native_rasters = []
    sidecar_files = []
    til_files = []
    other_files = []

    for item in contents:
        rel_path = item.get("relative_path", "")
        ext = PurePosixPath(rel_path).suffix.lower()

        if ext in RASTER_EXTENSIONS:
            raster_files.append(item)
        elif ext in PROCESSABLE_NON_NATIVE:
            non_native_rasters.append(item)
        elif ext in SIDECAR_EXTENSIONS:
            sidecar_files.append(item)
            if ext == ".til":
                til_files.append(item)
        else:
            other_files.append(item)

    evidence = {
        "raster_count": len(raster_files),
        "non_native_raster_count": len(non_native_rasters),
        "sidecar_count": len(sidecar_files),
        "til_count": len(til_files),
        "other_count": len(other_files),
        "total_files": len(contents),
    }

    # --- Classification logic (priority order) ---

    # 1. maxar_tiled: .TIL present AND R{n}C{n} in TIF filenames
    if til_files and raster_files:
        tiled_rasters = [
            f for f in raster_files
            if ROW_COL_PATTERN.search(f.get("relative_path", ""))
        ]
        if tiled_rasters:
            coords = []
            for f in tiled_rasters:
                match = ROW_COL_PATTERN.search(f.get("relative_path", ""))
                if match:
                    coords.append({"row": int(match.group(1)), "col": int(match.group(2))})

            evidence["pattern"] = "row_col"
            evidence["tile_count"] = len(tiled_rasters)
            evidence["grid_rows"] = max(c["row"] for c in coords) if coords else 0
            evidence["grid_cols"] = max(c["col"] for c in coords) if coords else 0

            logger.info(
                "classify_raster_contents: maxar_tiled — %d tiles (%dx%d grid)",
                len(tiled_rasters), evidence["grid_rows"], evidence["grid_cols"],
            )

            return {
                "success": True,
                "result": {
                    "classification": "maxar_tiled",
                    "evidence": evidence,
                    "raster_files": [f["relative_path"] for f in tiled_rasters],
                    "sidecar_files": [f["relative_path"] for f in sidecar_files],
                    "recommended_workflow": "process_raster_collection",
                    "recommended_params": {
                        "blob_list": [f["relative_path"] for f in tiled_rasters],
                    },
                    "metadata": metadata_json,
                },
            }

    # 2. single_geotiff: exactly 1 raster file
    if len(raster_files) == 1:
        raster_path = raster_files[0]["relative_path"]
        logger.info("classify_raster_contents: single_geotiff — %s", raster_path)

        return {
            "success": True,
            "result": {
                "classification": "single_geotiff",
                "evidence": evidence,
                "raster_files": [raster_path],
                "sidecar_files": [f["relative_path"] for f in sidecar_files],
                "recommended_workflow": "process_raster",
                "recommended_params": {
                    "blob_name": raster_path,
                },
                "metadata": metadata_json,
            },
        }

    # 3. multi_geotiff: 2+ raster files, no tiling pattern
    if len(raster_files) >= 2:
        logger.info(
            "classify_raster_contents: multi_geotiff — %d rasters",
            len(raster_files),
        )

        return {
            "success": True,
            "result": {
                "classification": "multi_geotiff",
                "evidence": evidence,
                "raster_files": [f["relative_path"] for f in raster_files],
                "sidecar_files": [f["relative_path"] for f in sidecar_files],
                "recommended_workflow": "process_raster_collection",
                "recommended_params": {
                    "blob_list": [f["relative_path"] for f in raster_files],
                },
                "metadata": metadata_json,
            },
        }

    # 4. non_raster: ECW, MrSID, JP2 detected but not processable by current pipeline
    if non_native_rasters:
        evidence["non_native_formats"] = list(set(
            PurePosixPath(f["relative_path"]).suffix.lower()
            for f in non_native_rasters
        ))
        logger.info(
            "classify_raster_contents: non_raster — %d files (%s)",
            len(non_native_rasters), evidence["non_native_formats"],
        )

        return {
            "success": True,
            "result": {
                "classification": "non_raster",
                "evidence": evidence,
                "raster_files": [f["relative_path"] for f in non_native_rasters],
                "sidecar_files": [f["relative_path"] for f in sidecar_files],
                "recommended_workflow": None,
                "recommended_params": {},
                "metadata": metadata_json,
            },
        }

    # 5. unclassifiable: no rasters found at all
    evidence["reason"] = "no recognized raster files"
    evidence["file_extensions_found"] = list(set(
        PurePosixPath(item.get("relative_path", "")).suffix.lower()
        for item in contents if item.get("relative_path")
    ))
    logger.warning(
        "classify_raster_contents: unclassifiable — extensions: %s",
        evidence["file_extensions_found"],
    )

    return {
        "success": True,
        "result": {
            "classification": "unclassifiable",
            "evidence": evidence,
            "raster_files": [],
            "sidecar_files": [],
            "recommended_workflow": None,
            "recommended_params": {},
            "metadata": metadata_json,
        },
    }
