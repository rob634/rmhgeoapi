# ============================================================================
# CLAUDE CONTEXT - RASTER CHECK HOMOGENEITY HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 raster collection)
# STATUS: Atomic handler - Cross-compare validation results for collection homogeneity
# PURPOSE: Receive N validation results from fan-in, compare band count, dtype,
#          CRS, resolution, raster_type. Output file_specs[] for downstream fan-outs.
# CREATED: 01 APR 2026
# EXPORTS: raster_check_homogeneity
# DEPENDENCIES: None (pure comparison, no I/O)
# ============================================================================
"""
Raster Check Homogeneity — atomic handler for DAG workflows.

Receives fan-in collected validation and download results for N raster files in
a collection.  Cross-compares structural properties (band count, dtype, CRS,
resolution, raster type) to ensure the files are homogeneous — a prerequisite
for collection-level processing (tiling, mosaicking, etc.).

On success, produces ``file_specs[]`` — a correlated list bundling download +
validation info per file, ready for downstream fan-out nodes.

This handler performs NO I/O.  It is a pure comparison function on in-memory
results already collected by the DAG engine's fan-in mechanism.

Homogeneity rules (ported from Epoch 4):
  H-1  Band count: exact match against file[0]
  H-2  Data type (dtype): exact match
  H-3  CRS: exact EPSG string match
  H-4  Resolution: within configurable tolerance (default ±20%) on x_res
  H-5  Raster type: same detected_type category (no RGB + DEM mixing);
       "unknown" is always compatible

Single-file collections (N < 2) skip homogeneity checks but still build
file_specs for downstream consistency.
"""

import logging
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# HANDLER ENTRY POINT
# =============================================================================

def raster_check_homogeneity(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Cross-compare raster validation results and build file_specs[].

    Params (all from ``params`` dict):
        validation_results (list, required): Fan-in collected validation results.
            Each item wraps as ``{"success": True, "result": {...}}``.
        download_results (list, required): Fan-in collected download results.
            Each item wraps as ``{"success": True, "result": {...}}``.
        blob_list (list[str], required): Original blob paths from workflow params.
            Correlated by position with validation_results and download_results.
        collection_id (str, required): Used to compute output_blob_name per file.
        tolerance_percent (float, optional): Resolution tolerance. Default 20.0.

    Returns (success — homogeneous):
        {
            "success": True,
            "result": {
                "homogeneous": True,
                "file_count": N,
                "reference": {"band_count": ..., "dtype": ..., "crs": ...,
                              "resolution": ..., "raster_type": ...},
                "file_specs": [...]
            }
        }

    Returns (failure — heterogeneous):
        {
            "success": False,
            "error": "Collection is not homogeneous: ...",
            "error_type": "HomogeneityError",
            "retryable": False,
            "mismatches": [...]
        }
    """
    # ------------------------------------------------------------------
    # 1. PARAMETER EXTRACTION
    # ------------------------------------------------------------------
    validation_results: Optional[List] = params.get('validation_results')
    if validation_results is None:
        return {
            "success": False,
            "error": "validation_results is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    download_results: Optional[List] = params.get('download_results')
    if download_results is None:
        return {
            "success": False,
            "error": "download_results is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    blob_list: Optional[List[str]] = params.get('blob_list')
    if blob_list is None:
        return {
            "success": False,
            "error": "blob_list is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    collection_id: Optional[str] = params.get('collection_id')
    if not collection_id:
        return {
            "success": False,
            "error": "collection_id is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    tolerance_percent: float = float(params.get('tolerance_percent', 20.0))

    # System-injected params (optional for this handler — used for log prefix only)
    run_id: str = params.get('_run_id', '')
    node_name: str = params.get('_node_name', '')
    log_prefix = f"[{run_id[:8]}][{node_name}]" if run_id else "[check_homogeneity]"

    try:  # Outer try/except — guarantees handler contract on unexpected errors.

        # ------------------------------------------------------------------
        # 2. LENGTH CONSISTENCY CHECK
        # ------------------------------------------------------------------
        n_val = len(validation_results)
        n_dl = len(download_results)
        n_blob = len(blob_list)

        if not (n_val == n_dl == n_blob):
            return {
                "success": False,
                "error": (
                    f"List length mismatch: validation_results={n_val}, "
                    f"download_results={n_dl}, blob_list={n_blob}. "
                    f"All three must have the same length."
                ),
                "error_type": "ValidationError",
                "retryable": False,
            }

        if n_val == 0:
            return {
                "success": False,
                "error": "validation_results is empty — nothing to compare",
                "error_type": "ValidationError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 3. UNWRAP FAN-IN RESULTS
        # ------------------------------------------------------------------
        # Fan-in collect mode wraps each child as {"success": True, "result": {...}}.
        # Unwrap to get the inner result dicts.
        validations = _unwrap_fan_in_results(validation_results, "validation", log_prefix)
        if validations is None:
            return {
                "success": False,
                "error": "One or more validation results indicate failure — cannot check homogeneity",
                "error_type": "UpstreamFailureError",
                "retryable": False,
            }

        downloads = _unwrap_fan_in_results(download_results, "download", log_prefix)
        if downloads is None:
            return {
                "success": False,
                "error": "One or more download results indicate failure — cannot check homogeneity",
                "error_type": "UpstreamFailureError",
                "retryable": False,
            }

        file_count = len(validations)
        logger.info(f"{log_prefix} Checking homogeneity for {file_count} file(s)")

        # ------------------------------------------------------------------
        # 4. EXTRACT COMPARABLE PROPERTIES FROM REFERENCE (file[0])
        # ------------------------------------------------------------------
        ref = validations[0]
        ref_props = _extract_comparable_props(ref)

        # ------------------------------------------------------------------
        # 5. HOMOGENEITY COMPARISON (skip for single-file collections)
        # ------------------------------------------------------------------
        mismatches: List[Dict[str, Any]] = []

        if file_count >= 2:
            for idx in range(1, file_count):
                file_props = _extract_comparable_props(validations[idx])
                blob_name = blob_list[idx]
                file_label = PurePosixPath(blob_name).name

                # H-1: Band count — exact match
                if file_props["band_count"] != ref_props["band_count"]:
                    mismatches.append({
                        "type": "BAND_COUNT",
                        "file": file_label,
                        "file_index": idx,
                        "expected": ref_props["band_count"],
                        "found": file_props["band_count"],
                        "message": (
                            f"File '{file_label}' has band_count={file_props['band_count']}, "
                            f"expected {ref_props['band_count']}"
                        ),
                    })

                # H-2: Data type — exact match
                if file_props["dtype"] != ref_props["dtype"]:
                    mismatches.append({
                        "type": "DTYPE",
                        "file": file_label,
                        "file_index": idx,
                        "expected": ref_props["dtype"],
                        "found": file_props["dtype"],
                        "message": (
                            f"File '{file_label}' has dtype='{file_props['dtype']}', "
                            f"expected '{ref_props['dtype']}'"
                        ),
                    })

                # H-3: CRS — exact string match
                if file_props["crs"] != ref_props["crs"]:
                    mismatches.append({
                        "type": "CRS",
                        "file": file_label,
                        "file_index": idx,
                        "expected": ref_props["crs"],
                        "found": file_props["crs"],
                        "message": (
                            f"File '{file_label}' has CRS='{file_props['crs']}', "
                            f"expected '{ref_props['crs']}'"
                        ),
                    })

                # H-4: Resolution — within tolerance on x_res
                if not _resolution_within_tolerance(
                    ref_props["resolution"], file_props["resolution"], tolerance_percent
                ):
                    mismatches.append({
                        "type": "RESOLUTION",
                        "file": file_label,
                        "file_index": idx,
                        "expected": ref_props["resolution"],
                        "found": file_props["resolution"],
                        "tolerance_percent": tolerance_percent,
                        "message": (
                            f"File '{file_label}' resolution {file_props['resolution']} "
                            f"exceeds {tolerance_percent}% tolerance from reference "
                            f"{ref_props['resolution']}"
                        ),
                    })

                # H-5: Raster type — same category ("unknown" always compatible)
                if not _raster_type_compatible(
                    ref_props["raster_type"], file_props["raster_type"]
                ):
                    mismatches.append({
                        "type": "RASTER_TYPE",
                        "file": file_label,
                        "file_index": idx,
                        "expected": ref_props["raster_type"],
                        "found": file_props["raster_type"],
                        "message": (
                            f"File '{file_label}' has raster_type='{file_props['raster_type']}', "
                            f"expected '{ref_props['raster_type']}' (no mixing allowed)"
                        ),
                    })

        # ------------------------------------------------------------------
        # 6. FAIL ON MISMATCHES
        # ------------------------------------------------------------------
        if mismatches:
            mismatch_types = sorted(set(m["type"] for m in mismatches))
            error_summary = ", ".join(mismatch_types)
            logger.warning(
                f"{log_prefix} Homogeneity FAILED: {len(mismatches)} mismatch(es) — "
                f"{error_summary}"
            )
            return {
                "success": False,
                "error": f"Collection is not homogeneous: {error_summary} mismatch",
                "error_type": "HomogeneityError",
                "retryable": False,
                "mismatches": mismatches,
            }

        # ------------------------------------------------------------------
        # 7. BUILD file_specs[]
        # ------------------------------------------------------------------
        file_specs: List[Dict[str, Any]] = []
        for idx in range(file_count):
            val = validations[idx]
            dl = downloads[idx]
            blob_name = blob_list[idx]
            blob_stem = PurePosixPath(blob_name).stem
            output_blob_name = f"{collection_id}/{blob_stem}.tif"

            file_specs.append({
                "blob_stem": blob_stem,
                "blob_name": blob_name,
                "source_path": dl.get("source_path"),
                "output_blob_name": output_blob_name,
                "source_crs": val.get("source_crs"),
                "target_crs": val.get("target_crs"),
                "needs_reprojection": val.get("needs_reprojection"),
                "raster_type": val.get("raster_type"),
                "nodata": val.get("nodata"),
                "band_count": val.get("band_count", _extract_band_count(val)),
                "dtype": val.get("dtype", _extract_dtype(val)),
                "source_bounds": val.get("source_bounds"),
            })

        logger.info(
            f"{log_prefix} Homogeneity PASSED: {file_count} file(s), "
            f"reference={{band_count={ref_props['band_count']}, "
            f"dtype='{ref_props['dtype']}', crs='{ref_props['crs']}', "
            f"resolution={ref_props['resolution']}, "
            f"raster_type='{ref_props['raster_type']}'}}"
        )

        return {
            "success": True,
            "result": {
                "homogeneous": True,
                "file_count": file_count,
                "reference": {
                    "band_count": ref_props["band_count"],
                    "dtype": ref_props["dtype"],
                    "crs": ref_props["crs"],
                    "resolution": ref_props["resolution"],
                    "raster_type": ref_props["raster_type"],
                },
                "file_specs": file_specs,
            },
        }

    except Exception as exc:
        import traceback
        logger.error(
            f"{log_prefix} Unexpected error in raster_check_homogeneity: {exc}\n"
            f"{traceback.format_exc()}"
        )
        return {
            "success": False,
            "error": f"Unexpected error in raster_check_homogeneity: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _unwrap_fan_in_results(
    wrapped_results: List[Dict[str, Any]],
    label: str,
    log_prefix: str,
) -> Optional[List[Dict[str, Any]]]:
    """
    Unwrap fan-in collected results.

    Each entry is expected as ``{"success": True, "result": {...}}``.
    Returns the list of inner result dicts, or None if any entry failed.
    """
    unwrapped: List[Dict[str, Any]] = []
    for idx, entry in enumerate(wrapped_results):
        if not isinstance(entry, dict):
            logger.error(
                f"{log_prefix} {label}[{idx}] is not a dict: {type(entry).__name__}"
            )
            return None

        if entry.get("success") is False:
            error_msg = entry.get("error", "unknown error")
            logger.error(
                f"{log_prefix} {label}[{idx}] failed upstream: {error_msg}"
            )
            return None

        # Unwrap: fan-in wraps as {"success": True, "result": {...}}
        inner = entry.get("result", entry)
        unwrapped.append(inner)

    return unwrapped


def _extract_comparable_props(validation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the five comparable properties from a single validation result.

    Handles the nested raster_type structure where band_count and dtype may
    live inside the raster_type dict or at the top level.
    """
    raster_type_info = validation.get("raster_type", {})
    detected_type = raster_type_info.get("detected_type", "unknown") if isinstance(raster_type_info, dict) else "unknown"

    return {
        "band_count": _extract_band_count(validation),
        "dtype": _extract_dtype(validation),
        "crs": validation.get("source_crs", ""),
        "resolution": _extract_resolution(validation),
        "raster_type": detected_type,
    }


def _extract_band_count(validation: Dict[str, Any]) -> Optional[int]:
    """
    Extract band_count from validation result.

    Checks top-level first, then falls back to raster_type.band_count.
    """
    band_count = validation.get("band_count")
    if band_count is not None:
        return band_count
    raster_type_info = validation.get("raster_type", {})
    if isinstance(raster_type_info, dict):
        return raster_type_info.get("band_count")
    return None


def _extract_dtype(validation: Dict[str, Any]) -> Optional[str]:
    """
    Extract dtype from validation result.

    Checks top-level first, then falls back to raster_type.data_type.
    """
    dtype = validation.get("dtype")
    if dtype is not None:
        return dtype
    raster_type_info = validation.get("raster_type", {})
    if isinstance(raster_type_info, dict):
        return raster_type_info.get("data_type")
    return None


def _extract_resolution(validation: Dict[str, Any]) -> Optional[tuple]:
    """
    Extract resolution tuple from validation result.

    Looks for ``resolution`` key. If it's a list, converts to tuple for
    consistent comparison.
    """
    res = validation.get("resolution")
    if res is None:
        return None
    if isinstance(res, (list, tuple)):
        return tuple(res)
    # Scalar resolution — treat as (res, res)
    return (res, res)


def _resolution_within_tolerance(
    ref_resolution: Optional[tuple],
    file_resolution: Optional[tuple],
    tolerance_percent: float,
) -> bool:
    """
    Check whether file resolution is within tolerance of reference resolution.

    Compares x_res (first element of tuple). If either resolution is None,
    returns True (skip check — cannot compare unknown resolutions).
    """
    if ref_resolution is None or file_resolution is None:
        return True

    try:
        ref_x = abs(float(ref_resolution[0]))
        file_x = abs(float(file_resolution[0]))
    except (IndexError, TypeError, ValueError):
        # Cannot parse resolutions — skip check rather than false-fail
        return True

    if ref_x == 0:
        # Zero reference resolution is nonsensical — skip check
        return True

    percent_diff = abs(file_x - ref_x) / ref_x * 100.0
    return percent_diff <= tolerance_percent


def _raster_type_compatible(ref_type: str, file_type: str) -> bool:
    """
    Check raster type compatibility.

    "unknown" is always compatible with any type. Otherwise, types must
    match exactly (no RGB + DEM mixing).
    """
    if ref_type == "unknown" or file_type == "unknown":
        return True
    return ref_type == file_type
