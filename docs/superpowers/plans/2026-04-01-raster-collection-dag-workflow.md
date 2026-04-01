# Raster Collection DAG Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process N raster files into N COGs under a single STAC collection with pgSTAC mosaic search, using fully decomposed DAG fan-out/fan-in nodes.

**Architecture:** New workflow YAML with 4 fan-out/fan-in cycles reusing 6 existing handlers, plus 2 new handlers (homogeneity cross-check, collection persist). Files correlate across fan-outs via `blob_stem` key carried in DAG parameters. Existing handlers are NOT modified.

**Tech Stack:** YAML workflow definition, Python handler functions, rasterio, Azure Blob Storage, pgSTAC, psycopg

**Spec:** `docs/superpowers/specs/2026-04-01-raster-collection-dag-workflow-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/raster/handler_check_homogeneity.py` | Cross-compare validation results, output file_specs[] |
| Create | `services/raster/handler_persist_collection.py` | Write N cog_metadata rows from correlated fan-in results |
| Create | `workflows/process_raster_collection.yaml` | DAG workflow definition |
| Modify | `services/__init__.py` | Import + register 2 new handlers in ALL_HANDLERS |
| Modify | `config/defaults.py` | Add 2 new handler names to DOCKER_TASKS frozenset |

---

## Important Context for Implementer

### Existing Handler Outputs (DO NOT MODIFY these handlers)

**`raster_download_source`** result:
```python
{
    "source_path": "/mnt/etl/{_run_id}/{_run_id[:8]}_{basename(blob_name)}",
    "file_size_bytes": int,
    "transfer_duration_seconds": float,
    "content_type": str | None
}
```
Note: `source_path` uses `{run_id[:8]}_` prefix to prevent filename collisions.

**`raster_validate` (registered as `raster_validate_atomic`)** result:
```python
{
    "source_crs": "EPSG:32637",
    "crs_source": "file_metadata" | "user_override",
    "target_crs": "EPSG:4326",
    "needs_reprojection": True,
    "nodata": -9999.0,
    "raster_type": {"detected_type": "dem", "band_count": 1, ...},
    "source_bounds": [minx, miny, maxx, maxy],
    "band_count": 1,
    "dtype": "float32",
    "file_size_bytes": int
}
```
Note: Does NOT include `source_path` or `blob_name` in its result — only in its input params.

**`raster_create_cog_atomic`** requires params: `source_path`, `output_blob_name`, `source_crs`, `target_crs`, `needs_reprojection`, `raster_type`, `nodata`, plus `processing_options` (optional). Returns `cog_path`, `cog_blob`, `bounds_4326`, `shape`, `raster_bands`, etc.

**`raster_upload_cog`** requires params: `cog_path`, `source_path`, `blob_name`, `collection_id`, `output_blob_name` (optional). Returns `stac_item_id`, `silver_container`, `silver_blob_path`, `cog_url`, `cog_size_bytes`, `etag`.

### Handler Contract

All handlers follow: `def handler(params: Dict, context=None) -> Dict` returning `{"success": True, "result": {...}}` or `{"success": False, "error": "...", "error_type": "...", "retryable": bool}`.

### Fan-Out/Fan-In Mechanics

- `fan_out` `source` field resolves a dotted path (e.g. `"agg_downloads.items"`) to a list
- Each fan-out child gets `{{ item }}` (current element), `{{ index }}` (0-based), `{{ inputs.X }}` (workflow params), `{{ nodes.X.result.Y }}` (predecessor results)
- `fan_in` `collect` mode produces `{"items": [child0_result, child1_result, ...]}`
- Fan-in preserves order by `fan_out_index`

### Correlation Strategy

The download handler's `source_path` is threaded through DAG parameters where needed. The homogeneity handler joins download + validation results by index (fan-out preserves order) and emits `file_specs[]` with all data needed by downstream fan-outs. Each file_spec includes a `blob_stem` (filename without extension) used as the conceptual correlation key and for computing silver blob paths.

---

## Task 1: Create `raster_check_homogeneity` Handler

**Files:**
- Create: `services/raster/handler_check_homogeneity.py`

- [ ] **Step 1: Create the handler file**

```python
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
Raster Check Homogeneity — DAG handler for raster collection workflows.

Receives aggregated validation results and download results from fan-in,
cross-compares all files against file[0] as reference, and outputs
file_specs[] that bundles per-file metadata for downstream fan-outs.

No I/O — pure comparison function on in-memory results.

Ported from: Epoch 4 handler_raster_collection_complete.py
             _validate_collection_homogeneity() (lines 293-468)
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def raster_check_homogeneity(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Cross-compare validation results for collection homogeneity.

    Params:
        validation_results (list): Fan-in collected validation results.
            Each item is a dict with: source_crs, target_crs, needs_reprojection,
            raster_type, nodata, band_count, dtype, source_bounds, file_size_bytes.
        download_results (list): Fan-in collected download results.
            Each item is a dict with: source_path, file_size_bytes, blob_name.
        collection_id (str): For output_blob_name generation.
        tolerance_percent (float, optional): Resolution tolerance, default 20.0.

    Returns:
        Success: {"success": True, "result": {"homogeneous": True, "file_specs": [...]}}
        Failure: {"success": False, "error": "...", "mismatches": [...]}
    """
    validation_results = params.get("validation_results")
    download_results = params.get("download_results")
    collection_id = params.get("collection_id")
    blob_list = params.get("blob_list", [])
    tolerance_percent = float(params.get("tolerance_percent", 20.0))

    # --- Parameter validation ---
    if not validation_results or not isinstance(validation_results, list):
        return {
            "success": False,
            "error": "validation_results is required and must be a list",
            "error_type": "ValidationError",
            "retryable": False,
        }

    if not download_results or not isinstance(download_results, list):
        return {
            "success": False,
            "error": "download_results is required and must be a list",
            "error_type": "ValidationError",
            "retryable": False,
        }

    if len(validation_results) != len(download_results):
        return {
            "success": False,
            "error": (
                f"validation_results ({len(validation_results)}) and "
                f"download_results ({len(download_results)}) must have same length"
            ),
            "error_type": "ValidationError",
            "retryable": False,
        }

    if not collection_id:
        return {
            "success": False,
            "error": "collection_id is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # --- Unwrap fan-in results ---
    # Fan-in collect mode wraps each child's output; unwrap to get the result dict.
    validations = _unwrap_fan_in_results(validation_results)
    downloads = _unwrap_fan_in_results(download_results)

    if len(validations) < 2:
        # Single file — no homogeneity check needed, just build file_specs
        file_specs = _build_file_specs(validations, downloads, blob_list, collection_id)
        return {
            "success": True,
            "result": {
                "homogeneous": True,
                "message": "Single file, no homogeneity check needed",
                "file_count": len(validations),
                "reference": _extract_reference(validations[0]) if validations else {},
                "file_specs": file_specs,
            },
        }

    # --- Cross-compare against reference (file[0]) ---
    reference = validations[0]
    ref_props = _extract_reference(reference)
    mismatches = []

    for idx in range(1, len(validations)):
        file_val = validations[idx]
        blob_name = blob_list[idx] if idx < len(blob_list) else f"file_{idx}"
        file_mismatches = _compare_to_reference(
            ref_props, file_val, blob_name, idx, tolerance_percent
        )
        mismatches.extend(file_mismatches)

    if mismatches:
        mismatch_types = sorted(set(m["type"] for m in mismatches))
        return {
            "success": False,
            "error": f"Collection is not homogeneous: {', '.join(mismatch_types)} mismatch",
            "error_type": "HomogeneityError",
            "retryable": False,
            "mismatches": mismatches,
        }

    # --- Build file_specs for downstream fan-outs ---
    file_specs = _build_file_specs(validations, downloads, blob_list, collection_id)

    logger.info(
        "raster_check_homogeneity: %d files homogeneous — "
        "bands=%s, dtype=%s, crs=%s, type=%s",
        len(validations),
        ref_props["band_count"],
        ref_props["dtype"],
        ref_props["crs"],
        ref_props["raster_type"],
    )

    return {
        "success": True,
        "result": {
            "homogeneous": True,
            "file_count": len(validations),
            "reference": ref_props,
            "file_specs": file_specs,
        },
    }


# ==============================================================================
# PRIVATE HELPERS
# ==============================================================================


def _unwrap_fan_in_results(items: List[Dict]) -> List[Dict]:
    """Unwrap fan-in collect results to get the inner result dicts."""
    unwrapped = []
    for entry in items:
        if isinstance(entry, dict):
            # Fan-in wraps as {"success": True, "result": {...}}
            result = entry.get("result", entry)
            unwrapped.append(result)
        else:
            unwrapped.append({})
    return unwrapped


def _extract_reference(validation: Dict) -> Dict:
    """Extract the properties used for homogeneity comparison."""
    raster_type_info = validation.get("raster_type", {})
    return {
        "band_count": validation.get("band_count")
                      or raster_type_info.get("band_count"),
        "dtype": validation.get("dtype")
                 or raster_type_info.get("data_type"),
        "crs": validation.get("source_crs"),
        "resolution": validation.get("resolution"),
        "raster_type": raster_type_info.get("detected_type", "unknown"),
    }


def _compare_to_reference(
    ref: Dict, file_val: Dict, blob_name: str, idx: int, tolerance_pct: float
) -> List[Dict]:
    """Compare one file's validation result against the reference."""
    mismatches = []
    file_props = _extract_reference(file_val)

    # Band count — exact match
    if file_props["band_count"] != ref["band_count"]:
        mismatches.append({
            "type": "BAND_COUNT",
            "file": blob_name,
            "file_index": idx,
            "expected": ref["band_count"],
            "found": file_props["band_count"],
            "message": f"Expected {ref['band_count']} bands, found {file_props['band_count']}",
        })

    # Data type — exact match
    if file_props["dtype"] != ref["dtype"]:
        mismatches.append({
            "type": "DTYPE",
            "file": blob_name,
            "file_index": idx,
            "expected": ref["dtype"],
            "found": file_props["dtype"],
            "message": f"Expected {ref['dtype']}, found {file_props['dtype']}",
        })

    # CRS — exact match
    if file_props["crs"] != ref["crs"]:
        mismatches.append({
            "type": "CRS",
            "file": blob_name,
            "file_index": idx,
            "expected": ref["crs"],
            "found": file_props["crs"],
            "message": f"Expected CRS {ref['crs']}, found {file_props['crs']}",
        })

    # Resolution — within tolerance
    ref_res = ref.get("resolution")
    file_res = file_props.get("resolution")
    if ref_res and file_res:
        # resolution is typically a tuple/list (x_res, y_res)
        ref_val = ref_res[0] if isinstance(ref_res, (list, tuple)) else ref_res
        file_val_r = file_res[0] if isinstance(file_res, (list, tuple)) else file_res
        if ref_val and ref_val > 0:
            diff_pct = abs(file_val_r - ref_val) / ref_val * 100
            if diff_pct > tolerance_pct:
                mismatches.append({
                    "type": "RESOLUTION",
                    "file": blob_name,
                    "file_index": idx,
                    "expected": f"{ref_val:.6f}",
                    "found": f"{file_val_r:.6f}",
                    "difference_percent": round(diff_pct, 1),
                    "tolerance_percent": tolerance_pct,
                    "message": f"Resolution differs by {diff_pct:.1f}% (max {tolerance_pct}%)",
                })

    # Raster type — same category (unknown passes)
    if (
        file_props["raster_type"] != ref["raster_type"]
        and file_props["raster_type"] != "unknown"
        and ref["raster_type"] != "unknown"
    ):
        mismatches.append({
            "type": "RASTER_TYPE",
            "file": blob_name,
            "file_index": idx,
            "expected": ref["raster_type"],
            "found": file_props["raster_type"],
            "message": f"Expected {ref['raster_type']}, found {file_props['raster_type']}",
        })

    return mismatches


def _build_file_specs(
    validations: List[Dict],
    downloads: List[Dict],
    blob_list: List[str],
    collection_id: str,
) -> List[Dict]:
    """
    Build the file_specs list that downstream fan-outs consume.

    Each spec bundles download info + validation metadata + computed output name.
    The blob_stem is the correlation key used across all phases.
    blob_list provides the original blob names (download handler does not echo them).
    """
    file_specs = []

    for idx, (val, dl) in enumerate(zip(validations, downloads)):
        blob_name = blob_list[idx] if idx < len(blob_list) else f"file_{idx}"
        source_path = dl.get("source_path", "")
        blob_stem = Path(blob_name).stem

        raster_type_info = val.get("raster_type", {})

        file_specs.append({
            "blob_stem": blob_stem,
            "blob_name": blob_name,
            "source_path": source_path,
            "output_blob_name": f"{collection_id}/{blob_stem}.tif",
            "source_crs": val.get("source_crs"),
            "target_crs": val.get("target_crs", "EPSG:4326"),
            "needs_reprojection": val.get("needs_reprojection", False),
            "raster_type": raster_type_info,
            "nodata": val.get("nodata"),
            "band_count": val.get("band_count") or raster_type_info.get("band_count"),
            "dtype": val.get("dtype") or raster_type_info.get("data_type"),
            "source_bounds": val.get("source_bounds"),
        })

    return file_specs
```

- [ ] **Step 2: Verify the file was created correctly**

Run: `python -c "from services.raster.handler_check_homogeneity import raster_check_homogeneity; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/raster/handler_check_homogeneity.py
git commit -m "feat: add raster_check_homogeneity handler for collection workflows"
```

---

## Task 2: Create `raster_persist_collection` Handler

**Files:**
- Create: `services/raster/handler_persist_collection.py`

- [ ] **Step 1: Create the handler file**

```python
# ============================================================================
# CLAUDE CONTEXT - RASTER PERSIST COLLECTION HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 raster collection)
# STATUS: Atomic handler - Write N cog_metadata rows for a raster collection
# PURPOSE: Receive correlated upload + COG + validation results from fan-ins,
#          build stac_item_json per file, upsert N cog_metadata rows.
# CREATED: 01 APR 2026
# EXPORTS: raster_persist_collection
# DEPENDENCIES: infrastructure.raster_metadata_repository, services.stac.stac_item_builder
# ============================================================================
"""
Raster Persist Collection — DAG handler for raster collection workflows.

After all files are downloaded, validated, COG-created, and uploaded,
this single-task handler receives the three fan-in result lists plus
the file_specs from homogeneity check and writes N cog_metadata rows.

Pattern follows raster_persist_tiled (writes N rows, returns cog_ids).
Correlation is by blob_stem key across all three input lists.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def raster_persist_collection(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Write N cog_metadata rows for a raster collection.

    Params:
        upload_results (list): Fan-in collected upload results.
            Each: {stac_item_id, silver_container, silver_blob_path, cog_url,
                   cog_size_bytes, etag}
        cog_results (list): Fan-in collected COG creation results.
            Each: {cog_path, cog_blob, bounds_4326, shape, raster_bands,
                   rescale_range, transform, resolution, crs, compression,
                   tile_size, overview_levels}
        file_specs (list): From homogeneity check.
            Each: {blob_stem, blob_name, source_crs, raster_type, band_count,
                   dtype, nodata, source_bounds}
        collection_id (str): STAC collection ID.
        Platform metadata: dataset_id, resource_id, version_id, stac_item_id,
                          access_level, title, tags, release_id, asset_id.

    Returns:
        {"success": True, "result": {"cog_ids": [...], "collection_id", "item_count"}}
    """
    upload_results = params.get("upload_results")
    cog_results = params.get("cog_results")
    file_specs = params.get("file_specs")
    collection_id = params.get("collection_id")

    # Parameter validation
    missing = []
    if not upload_results:
        missing.append("upload_results")
    if not cog_results:
        missing.append("cog_results")
    if not file_specs:
        missing.append("file_specs")
    if not collection_id:
        missing.append("collection_id")
    if missing:
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # Unwrap fan-in results
    uploads = _unwrap_fan_in(upload_results)
    cogs = _unwrap_fan_in(cog_results)

    if len(uploads) != len(cogs) or len(uploads) != len(file_specs):
        return {
            "success": False,
            "error": (
                f"Result list length mismatch: uploads={len(uploads)}, "
                f"cogs={len(cogs)}, file_specs={len(file_specs)}"
            ),
            "error_type": "ValidationError",
            "retryable": False,
        }

    # Platform metadata (shared across all items)
    dataset_id = params.get("dataset_id")
    resource_id = params.get("resource_id")
    version_id = params.get("version_id")
    access_level = params.get("access_level")
    title = params.get("title")
    tags = params.get("tags")
    release_id = params.get("release_id")
    asset_id = params.get("asset_id")
    job_id = params.get("_run_id", "unknown")

    try:
        from infrastructure.raster_metadata_repository import RasterMetadataRepository
        from services.stac_renders import recommend_colormap
        from services.stac.stac_item_builder import build_stac_item

        cog_repo = RasterMetadataRepository.instance()
        persisted_ids = []
        errors = []

        for idx, (upload, cog, spec) in enumerate(zip(uploads, cogs, file_specs)):
            stac_item_id = upload.get("stac_item_id")
            if not stac_item_id:
                errors.append(f"file[{idx}] ({spec.get('blob_name')}): missing stac_item_id")
                continue

            blob_path = upload.get("silver_blob_path", "")
            container = upload.get("silver_container", "silver-cogs")
            cog_url = upload.get("cog_url", "")
            bounds = cog.get("bounds_4326", [])
            detected_type = spec.get("raster_type", {}).get("detected_type", "unknown")
            band_count = spec.get("band_count", 1)
            data_type = spec.get("dtype", "float32")
            nodata_val = spec.get("nodata")
            source_crs = spec.get("source_crs")
            blob_name = spec.get("blob_name", "")

            if len(bounds) < 4:
                errors.append(f"file[{idx}] ({blob_name}): missing bounds_4326")
                continue

            # Build stac_item_json for cog_metadata cache
            stac_item_json = build_stac_item(
                item_id=stac_item_id,
                collection_id=collection_id,
                bbox=bounds,
                asset_href=cog_url,
                asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
                crs=cog.get("crs", "EPSG:4326"),
                detected_type=detected_type,
                band_count=band_count,
                data_type=data_type,
                job_id=job_id,
                epoch=5,
                dataset_id=dataset_id,
                resource_id=resource_id,
                version_id=version_id,
            )

            colormap = recommend_colormap(detected_type)

            try:
                cog_repo.upsert(
                    cog_id=stac_item_id,
                    container=container,
                    blob_path=blob_path,
                    cog_url=cog_url,
                    width=cog.get("shape", [0, 0])[1] if cog.get("shape") else 0,
                    height=cog.get("shape", [0, 0])[0] if cog.get("shape") else 0,
                    band_count=band_count,
                    dtype=data_type,
                    nodata=nodata_val,
                    crs=cog.get("crs", "EPSG:4326"),
                    is_cog=True,
                    bbox_minx=bounds[0],
                    bbox_miny=bounds[1],
                    bbox_maxx=bounds[2],
                    bbox_maxy=bounds[3],
                    colormap=colormap,
                    stac_item_id=stac_item_id,
                    stac_collection_id=collection_id,
                    etl_job_id=job_id,
                    source_file=blob_name,
                    source_crs=source_crs,
                    custom_properties={
                        "raster_type": detected_type,
                        "collection_member": True,
                    },
                    stac_item_json=stac_item_json,
                )
                persisted_ids.append(stac_item_id)
            except Exception as row_err:
                logger.warning(
                    "persist_collection: failed to upsert cog_metadata for %s: %s",
                    stac_item_id, row_err,
                )
                errors.append(f"{stac_item_id}: {row_err}")

        if not persisted_ids:
            return {
                "success": False,
                "error": f"All {len(uploads)} persists failed: {'; '.join(errors[:3])}",
                "error_type": "DatabaseError",
                "retryable": True,
            }

        # Update release if present
        if release_id:
            _update_release(release_id, persisted_ids, collection_id)

        logger.info(
            "raster_persist_collection: %d/%d items persisted for %s",
            len(persisted_ids), len(uploads), collection_id,
        )

        return {
            "success": True,
            "result": {
                "cog_ids": persisted_ids,
                "collection_id": collection_id,
                "item_count": len(persisted_ids),
                "errors": errors if errors else None,
            },
        }

    except Exception as exc:
        import traceback
        logger.error(
            "raster_persist_collection failed: %s\n%s", exc, traceback.format_exc()
        )
        return {
            "success": False,
            "error": f"Collection persist failed: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }


# ==============================================================================
# PRIVATE HELPERS
# ==============================================================================


def _unwrap_fan_in(items: list) -> list:
    """Unwrap fan-in collect results to get inner result dicts."""
    unwrapped = []
    for entry in items:
        if isinstance(entry, dict):
            result = entry.get("result", entry)
            unwrapped.append(result)
        else:
            unwrapped.append({})
    return unwrapped


def _update_release(release_id: str, cog_ids: list, collection_id: str) -> None:
    """Update release record with collection outputs (non-fatal)."""
    try:
        from infrastructure.release_repository import ReleaseRepository
        from core.models.asset import ProcessingStatus

        release_repo = ReleaseRepository()
        release_repo.update_physical_outputs(
            release_id=release_id,
            blob_path=f"cogs/{collection_id}/",
            stac_item_id=collection_id,
            output_mode="collection",
            tile_count=len(cog_ids),
        )
        release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info(
            "Updated release %s with collection outputs (%d items)",
            release_id[:16], len(cog_ids),
        )
    except Exception as rel_err:
        logger.warning(
            "Failed to update release %s: %s (non-fatal)",
            release_id[:16] if release_id else "unknown", rel_err,
        )
```

- [ ] **Step 2: Verify the file was created correctly**

Run: `python -c "from services.raster.handler_persist_collection import raster_persist_collection; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/raster/handler_persist_collection.py
git commit -m "feat: add raster_persist_collection handler for collection workflows"
```

---

## Task 3: Register New Handlers

**Files:**
- Modify: `services/__init__.py` (around line 110, after persist_tiled import)
- Modify: `config/defaults.py` (around line 501, in DOCKER_TASKS frozenset)

- [ ] **Step 1: Add imports to `services/__init__.py`**

After line 109 (`from .raster.handler_persist_tiled import raster_persist_tiled`), add:

```python
from .raster.handler_check_homogeneity import raster_check_homogeneity
from .raster.handler_persist_collection import raster_persist_collection
```

- [ ] **Step 2: Add to ALL_HANDLERS dict in `services/__init__.py`**

After the `"raster_persist_tiled": raster_persist_tiled,` entry (around line 184), add:

```python
    "raster_check_homogeneity": raster_check_homogeneity,
    "raster_persist_collection": raster_persist_collection,
```

- [ ] **Step 3: Add to DOCKER_TASKS in `config/defaults.py`**

After line 501 (`"raster_finalize",`), add:

```python
        "raster_check_homogeneity",       # V0.10.10: Collection homogeneity cross-check
        "raster_persist_collection",      # V0.10.10: Collection N-row persist
```

- [ ] **Step 4: Verify registration**

Run: `python -c "from services import ALL_HANDLERS; assert 'raster_check_homogeneity' in ALL_HANDLERS; assert 'raster_persist_collection' in ALL_HANDLERS; print(f'OK — {len(ALL_HANDLERS)} handlers')"`
Expected: `OK — 60 handlers` (58 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add services/__init__.py config/defaults.py
git commit -m "feat: register raster_check_homogeneity and raster_persist_collection handlers"
```

---

## Task 4: Create Workflow YAML

**Files:**
- Create: `workflows/process_raster_collection.yaml`

- [ ] **Step 1: Create the workflow file**

```yaml
workflow: process_raster_collection
description: "Process N raster files into N COGs under a single STAC collection with pgSTAC mosaic search"
version: 1
reversed_by: unpublish_raster

parameters:
  blob_list: {type: list, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  processing_options:
    type: dict
    default: {}
  # Platform metadata passthrough
  dataset_id: {type: str, required: false}
  resource_id: {type: str, required: false}
  version_id: {type: str, required: false}
  access_level: {type: str, required: false}
  title: {type: str, required: false}
  tags: {type: list, required: false}
  release_id: {type: str, required: false}
  asset_id: {type: str, required: false}

validators:
  - type: blob_list_exists_with_max_size
    container_param: container_name
    blob_list_param: blob_list
    zone: bronze
    max_individual_size_mb_env: RASTER_COLLECTION_MAX_FILE_SIZE_MB
    max_collection_count_env: RASTER_COLLECTION_MAX_FILES
    error_raster_too_large: "Individual file exceeds per-file size limit (default 2 GB). Use tiled collection workflow for larger files."
    error_collection_too_large: "Collection exceeds maximum file count (default 20)."

nodes:
  # ==========================================================================
  # PHASE 1: DOWNLOAD (fan-out per blob)
  # ==========================================================================
  download_files:
    type: fan_out
    source: "inputs.blob_list"
    task:
      handler: raster_download_source
      params:
        blob_name: "{{ item }}"
        container_name: "{{ inputs.container_name }}"

  agg_downloads:
    type: fan_in
    depends_on: [download_files]
    aggregation: collect

  # ==========================================================================
  # PHASE 2: VALIDATE (fan-out per downloaded file)
  # ==========================================================================
  validate_files:
    type: fan_out
    depends_on: [agg_downloads]
    source: "agg_downloads.items"
    task:
      handler: raster_validate_atomic
      params:
        # source_path comes from the download result; blob_name comes from the
        # original blob_list (download handler does not echo blob_name in result)
        source_path: "{{ item.result.source_path }}"
        blob_name: "{{ inputs.blob_list[index] }}"
        container_name: "{{ inputs.container_name }}"
        input_crs: "{{ inputs.processing_options.input_crs }}"
        target_crs: "{{ inputs.processing_options.target_crs }}"
        raster_type: "{{ inputs.processing_options.raster_type }}"

  agg_validations:
    type: fan_in
    depends_on: [validate_files]
    aggregation: collect

  # ==========================================================================
  # PHASE 3: HOMOGENEITY CROSS-CHECK (single task)
  # ==========================================================================
  check_homogeneity:
    type: task
    handler: raster_check_homogeneity
    depends_on: [agg_validations]
    params: [collection_id, blob_list]
    receives:
      validation_results: "agg_validations.items"
      download_results: "agg_downloads.items"

  # ==========================================================================
  # PHASE 4: COG CREATION (fan-out per file_spec)
  # ==========================================================================
  create_cogs:
    type: fan_out
    depends_on: [check_homogeneity]
    source: "check_homogeneity.result.file_specs"
    task:
      handler: raster_create_cog_atomic
      params:
        source_path: "{{ item.source_path }}"
        output_blob_name: "{{ item.output_blob_name }}"
        source_crs: "{{ item.source_crs }}"
        target_crs: "{{ item.target_crs }}"
        needs_reprojection: "{{ item.needs_reprojection }}"
        raster_type: "{{ item.raster_type }}"
        nodata: "{{ item.nodata }}"
        processing_options: "{{ inputs.processing_options }}"

  agg_cogs:
    type: fan_in
    depends_on: [create_cogs]
    aggregation: collect

  # ==========================================================================
  # PHASE 5: UPLOAD (fan-out per COG)
  # ==========================================================================
  upload_cogs:
    type: fan_out
    depends_on: [agg_cogs]
    source: "agg_cogs.items"
    task:
      handler: raster_upload_cog
      params:
        cog_path: "{{ item.result.cog_path }}"
        source_path: "{{ item.result.source_path }}"
        collection_id: "{{ inputs.collection_id }}"
        blob_name: "{{ nodes.check_homogeneity.result.file_specs[index].blob_name }}"
        output_blob_name: "{{ nodes.check_homogeneity.result.file_specs[index].output_blob_name }}"

  agg_uploads:
    type: fan_in
    depends_on: [upload_cogs]
    aggregation: collect

  # ==========================================================================
  # PHASE 6: PERSIST (single task writes N cog_metadata rows)
  # ==========================================================================
  persist_collection:
    type: task
    handler: raster_persist_collection
    depends_on: [agg_uploads]
    params: [collection_id, dataset_id, resource_id, version_id, access_level, title, tags, release_id, asset_id]
    receives:
      upload_results: "agg_uploads.items"
      cog_results: "agg_cogs.items"
      file_specs: "check_homogeneity.result.file_specs"

  # ==========================================================================
  # PHASE 7: APPROVAL GATE
  # ==========================================================================
  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [persist_collection]

  # ==========================================================================
  # PHASE 8: STAC MATERIALIZATION (fan-out per cog_id)
  # ==========================================================================
  materialize_items:
    type: fan_out
    depends_on: [approval_gate]
    source: "persist_collection.result.cog_ids"
    task:
      handler: stac_materialize_item
      params:
        item_id: "{{ item }}"
        collection_id: "{{ inputs.collection_id }}"

  agg_materializations:
    type: fan_in
    depends_on: [materialize_items]
    aggregation: collect

  # ==========================================================================
  # PHASE 9: COLLECTION (extent + pgSTAC search registration)
  # ==========================================================================
  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [agg_materializations]
    params: [collection_id]

finalize:
  handler: raster_finalize
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('workflows/process_raster_collection.yaml')); print('YAML valid')"`
Expected: `YAML valid`

- [ ] **Step 3: Verify workflow loads in the DAG engine**

Run: `python -c "from core.models.workflow_definition import WorkflowDefinition; import yaml; data = yaml.safe_load(open('workflows/process_raster_collection.yaml')); wd = WorkflowDefinition.from_dict(data); print(f'OK — {len(wd.nodes)} nodes, workflow={wd.name}')"`
Expected: `OK — 13 nodes, workflow=process_raster_collection` (approximate — depends on how the model counts fan-out/fan-in)

- [ ] **Step 4: Commit**

```bash
git add workflows/process_raster_collection.yaml
git commit -m "feat: add process_raster_collection DAG workflow (4 fan-out/fan-in cycles)"
```

---

## Task 5: Verify Fan-Out Template Syntax

The YAML uses template expressions that may need adjustment based on how the DAG engine resolves fan-in results and `{{ index }}` access. This task verifies and fixes any template issues.

**Files:**
- Possibly modify: `workflows/process_raster_collection.yaml`

- [ ] **Step 1: Check if `inputs.blob_list` is valid as fan-out source**

The existing `process_raster.yaml` uses `"generate_tiling_scheme.result.tile_specs"` as a fan-out source (a node result). Our workflow uses `"inputs.blob_list"` (a workflow parameter). Verify the DAG engine supports this.

Run: `grep -n "inputs\." workflows/*.yaml` to see if any existing workflow uses `inputs.X` in a fan-out source.

If no workflow does this, check the param resolver: `grep -n "inputs" core/param_resolver.py` to see if `inputs.X` is a supported namespace.

If `inputs.blob_list` is not supported as a fan-out source, the workflow needs a small entrypoint task node that reads `blob_list` from params and returns it, so the fan-out can use `"entrypoint.result.blob_list"`.

- [ ] **Step 2: Check if `{{ index }}` is available in fan-out templates**

The upload_cogs fan-out uses `{{ nodes.check_homogeneity.result.file_specs[index].blob_name }}`. Verify the template engine supports `[index]` array access with the current fan-out index.

Run: `grep -rn "index" core/param_resolver.py core/dag_fan_engine.py | head -20`

If `{{ index }}` is not in the template context or `[index]` subscript is not supported, replace the upload_cogs fan-out with an alternative: have the COG handler pass through `blob_name` and `output_blob_name` in its result dict, so the upload fan-out can use `{{ item.result.blob_name }}`.

- [ ] **Step 3: Check fan-in result wrapping**

The validate fan-out accesses `{{ item.result.source_path }}` from `agg_downloads.items`. Verify that fan-in collect mode wraps each child as `{"success": True, "result": {...}}` (meaning we need `.result.`) or as a flat result dict (meaning we access `{{ item.source_path }}` directly).

Run: `grep -A 10 "collect" core/dag_fan_engine.py | head -20` to find how collect mode packages results.

Adjust the YAML template expressions accordingly.

- [ ] **Step 4: Fix any template issues found**

Apply fixes to `workflows/process_raster_collection.yaml` based on findings from steps 1-3.

- [ ] **Step 5: Commit if changes were needed**

```bash
git add workflows/process_raster_collection.yaml
git commit -m "fix: adjust fan-out template syntax for collection workflow"
```

---

## Task 6: Set Environment Variable Defaults

**Files:**
- Modify: `config/defaults.py` (add constants to RasterDefaults class, around line 559)

- [ ] **Step 1: Add defaults to RasterDefaults**

After `RASTER_TILING_THRESHOLD_MB = 2000` (line 559), add:

```python
    # ==========================================================================
    # COLLECTION SETTINGS (V0.10.10 — 01 APR 2026)
    # ==========================================================================
    # process_raster_collection workflow limits.
    # Hard per-file limit prevents OOM; matches tiling threshold.
    # Max files prevents fan-out explosion and mount disk exhaustion.

    RASTER_COLLECTION_MAX_FILE_SIZE_MB = 2048   # Per-file cap (env: RASTER_COLLECTION_MAX_FILE_SIZE_MB)
    RASTER_COLLECTION_MAX_FILES = 20            # Max files per collection (env: RASTER_COLLECTION_MAX_FILES)
```

- [ ] **Step 2: Commit**

```bash
git add config/defaults.py
git commit -m "feat: add RASTER_COLLECTION_MAX_FILE_SIZE_MB and RASTER_COLLECTION_MAX_FILES defaults"
```

---

## Task 7: Integration Smoke Test

This task verifies the full workflow can be loaded, validated, and (if a dev environment is available) submitted via `platform/submit`.

**Files:** None modified — read-only verification.

- [ ] **Step 1: Verify all handlers importable**

Run:
```bash
python -c "
from services import ALL_HANDLERS
required = [
    'raster_download_source', 'raster_validate_atomic',
    'raster_create_cog_atomic', 'raster_upload_cog',
    'raster_check_homogeneity', 'raster_persist_collection',
    'stac_materialize_item', 'stac_materialize_collection',
    'raster_finalize',
]
for h in required:
    assert h in ALL_HANDLERS, f'{h} not registered'
print(f'All {len(required)} handlers registered. Total: {len(ALL_HANDLERS)}')
"
```

- [ ] **Step 2: Verify workflow YAML loads and parses**

Run:
```bash
python -c "
from core.models.workflow_definition import WorkflowDefinition
import yaml
data = yaml.safe_load(open('workflows/process_raster_collection.yaml'))
wd = WorkflowDefinition.from_dict(data)
print(f'Workflow: {wd.name}')
print(f'Nodes: {len(wd.nodes)}')
print(f'Validators: {len(wd.validators) if wd.validators else 0}')
print(f'Parameters: {list(data.get(\"parameters\", {}).keys())}')
print(f'Finalize: {data.get(\"finalize\", {}).get(\"handler\")}')
"
```

- [ ] **Step 3: Verify DOCKER_TASKS includes new handlers**

Run:
```bash
python -c "
from config.defaults import QueueDefaults
assert 'raster_check_homogeneity' in QueueDefaults.DOCKER_TASKS
assert 'raster_persist_collection' in QueueDefaults.DOCKER_TASKS
print(f'DOCKER_TASKS count: {len(QueueDefaults.DOCKER_TASKS)}')
"
```

- [ ] **Step 4: Final commit (version bump if needed)**

```bash
git add -A
git commit -m "feat: raster collection DAG workflow — all handlers, YAML, and registration complete"
```

---

## Summary

| Task | What | New Files | Commits |
|------|------|-----------|---------|
| 1 | Homogeneity handler | `services/raster/handler_check_homogeneity.py` | 1 |
| 2 | Persist handler | `services/raster/handler_persist_collection.py` | 1 |
| 3 | Handler registration | Modify `services/__init__.py`, `config/defaults.py` | 1 |
| 4 | Workflow YAML | `workflows/process_raster_collection.yaml` | 1 |
| 5 | Template syntax verification | Possibly modify YAML | 0-1 |
| 6 | Env var defaults | Modify `config/defaults.py` | 1 |
| 7 | Integration smoke test | None | 1 |

**Total: 3 new files, 2 modified files, 5-7 commits**
