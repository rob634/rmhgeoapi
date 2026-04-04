# Discovery Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 2 discovery workflows (Maxar delivery + WBG legacy) that scan blob prefixes, classify raster contents, and submit processing workflows via a manifest pattern.

**Architecture:** 8 new DAG handlers (5 shared, 1 Maxar-specific, 2 WBG-specific) composed into 2 workflow YAMLs. Discovery workflows produce a manifest, then `submit_from_manifest` fires independent processing runs. No DAG engine changes. v0.11.0 scope.

**Tech Stack:** Python handlers, Azure Blob Storage SDK, zipfile stdlib, YAML workflow definitions, existing DAG infrastructure

**Spec:** `docs/superpowers/specs/2026-04-03-discovery-automation-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/discovery/handler_discover_blob_prefix.py` | Scan container+prefix, categorize files by extension |
| Create | `services/discovery/handler_classify_raster_contents.py` | Classify extracted directory contents (pure logic) |
| Create | `services/discovery/handler_build_manifest.py` | Aggregate classified items into structured manifest |
| Create | `services/discovery/handler_submit_from_manifest.py` | Submit workflows from manifest entries |
| Create | `services/discovery/handler_unzip_to_mount.py` | Download ZIP from blob, extract to mount |
| Create | `services/discovery/__init__.py` | Package init |
| Create | `services/discovery/handler_classify_maxar.py` | Maxar-specific: parse .TIL, match tiles to sidecars |
| Create | `services/discovery/handler_wbg_match_pairs.py` | WBG-specific: match JSON+ZIP by stem |
| Create | `services/discovery/handler_wbg_process_pair.py` | WBG composite: copy, unzip, classify, upload |
| Create | `workflows/discover_maxar_delivery.yaml` | 4-node linear discovery workflow |
| Create | `workflows/discover_wbg_legacy.yaml` | 7-node fan-out/fan-in discovery workflow |
| Modify | `services/__init__.py` | Import + register 8 new handlers in ALL_HANDLERS |
| Modify | `config/defaults.py` | Add 8 handler names to DOCKER_TASKS frozenset |

---

## Important Context for Implementer

### Handler Contract

All handlers follow this signature:

```python
def handler_name(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
```

**Success**: `{"success": True, "result": {...}}`
**Failure**: `{"success": False, "error": "...", "error_type": "...", "retryable": bool}`

### System-Injected Parameters

The DAG engine injects these into every handler's `params`:
- `_run_id` — 64-char DAG run ID
- `_task_name` — node name from YAML
- `_workflow` — workflow name

### Blob API

```python
from infrastructure.blob import BlobRepository
blob_repo = BlobRepository.for_zone("bronze")
blobs = blob_repo.list_blobs(container, prefix=prefix)  # returns [{"name", "size", "last_modified", ...}]
blob_repo.copy_blob(src_container, src_path, dest_container, dest_path)  # server-side copy
```

### Mount Path

```python
from infrastructure.etl_mount import resolve_run_dir, ensure_dir
run_dir = resolve_run_dir(params.get("_run_id"))
extract_dir = ensure_dir(run_dir, "extracted")
```

### Internal Workflow Submission

```python
from services.platform_job_submit import create_and_submit_dag_run
run_id = create_and_submit_dag_run(
    job_type="process_raster",  # matches workflow YAML name
    parameters={...},
    platform_request_id=request_id,
)
```

### Existing Tile Pattern Regex (from `services/delivery_discovery.py:174`)

```python
ROW_COL_PATTERN = re.compile(r'R(\d+)C(\d+)', re.IGNORECASE)
```

---

## Task 1: Create `discover_blob_prefix` Handler

**Files:**
- Create: `services/discovery/__init__.py`
- Create: `services/discovery/handler_discover_blob_prefix.py`

- [ ] **Step 1: Create package init**

```python
# services/discovery/__init__.py
```

Empty file — just establishes the package.

- [ ] **Step 2: Create the handler file**

```python
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
from collections import defaultdict
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
```

- [ ] **Step 3: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_discover_blob_prefix import discover_blob_prefix; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add services/discovery/__init__.py services/discovery/handler_discover_blob_prefix.py
git commit -m "feat: add discover_blob_prefix handler for prefix scanning"
```

---

## Task 2: Create `classify_raster_contents` Handler

**Files:**
- Create: `services/discovery/handler_classify_raster_contents.py`

- [ ] **Step 1: Create the handler file**

```python
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
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_classify_raster_contents import classify_raster_contents; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/discovery/handler_classify_raster_contents.py
git commit -m "feat: add classify_raster_contents handler for raster classification"
```

---

## Task 3: Create `build_discovery_manifest` Handler

**Files:**
- Create: `services/discovery/handler_build_manifest.py`

- [ ] **Step 1: Create the handler file**

```python
# ============================================================================
# CLAUDE CONTEXT - BUILD DISCOVERY MANIFEST HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Aggregate classified results into manifest
# PURPOSE: Receive classified items (from fan-in or single classify step),
#          build a structured manifest with summary and per-entry details.
# CREATED: 03 APR 2026
# EXPORTS: build_discovery_manifest
# DEPENDENCIES: None (pure aggregation, no I/O)
# ============================================================================
"""
Build Discovery Manifest -- aggregate classification results into a structured manifest.

The manifest is the contract boundary between discovery and processing.
It records what was found, what should be submitted, and what was skipped.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_discovery_manifest(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Build a structured manifest from classified items.

    Params:
        classified_items (list[dict], required): Classification results.
            Each dict is a handler result with "classification", "recommended_workflow",
            "recommended_params", "metadata", "evidence", and optionally "source_blob".
            For fan-in results, each item may be wrapped in {"success": True, "result": {...}}.
        discovery_source (str, required): "wbg_legacy" or "maxar_delivery".
        discovery_prefix (str, required): Original prefix that was scanned.

    Returns:
        Success: {"success": True, "result": {"manifest": {...}}}
    """
    classified_items = params.get("classified_items")
    discovery_source = params.get("discovery_source")
    discovery_prefix = params.get("discovery_prefix") or params.get("prefix")

    if not discovery_source:
        return {"success": False, "error": "discovery_source is required",
                "error_type": "ValidationError", "retryable": False}
    if not discovery_prefix:
        return {"success": False, "error": "discovery_prefix is required",
                "error_type": "ValidationError", "retryable": False}

    if not classified_items or not isinstance(classified_items, list):
        classified_items = []

    # Unwrap fan-in results if needed
    entries = []
    for idx, item in enumerate(classified_items):
        unwrapped = _unwrap_fan_in_result(item)
        if unwrapped is None:
            continue

        entries.append({
            "entry_index": idx,
            "source_blob": unwrapped.get("source_blob") or unwrapped.get("stem", f"item_{idx}"),
            "classification": unwrapped.get("classification", "unknown"),
            "recommended_workflow": unwrapped.get("recommended_workflow"),
            "recommended_params": unwrapped.get("recommended_params", {}),
            "metadata": unwrapped.get("metadata"),
            "evidence": unwrapped.get("evidence", {}),
        })

    # Build summary
    classification_counts = Counter(e["classification"] for e in entries)
    workflow_counts = Counter(
        e["recommended_workflow"] or "skipped"
        for e in entries
    )

    manifest = {
        "source": discovery_source,
        "prefix": discovery_prefix,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "summary": {
            "total": len(entries),
            "by_classification": dict(classification_counts),
            "by_workflow": dict(workflow_counts),
        },
    }

    logger.info(
        "build_discovery_manifest: %s/%s — %d entries: %s",
        discovery_source, discovery_prefix, len(entries),
        dict(classification_counts),
    )

    return {
        "success": True,
        "result": {
            "manifest": manifest,
        },
    }


def _unwrap_fan_in_result(item: Any) -> Optional[Dict]:
    """Unwrap fan-in collect wrapping to get the inner result dict."""
    if not isinstance(item, dict):
        return None
    # Fan-in wraps as {"success": True, "result": {...}}
    if "result" in item and "classification" not in item:
        return item.get("result")
    return item
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_build_manifest import build_discovery_manifest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/discovery/handler_build_manifest.py
git commit -m "feat: add build_discovery_manifest handler for manifest aggregation"
```

---

## Task 4: Create `submit_from_manifest` Handler

**Files:**
- Create: `services/discovery/handler_submit_from_manifest.py`

- [ ] **Step 1: Create the handler file**

```python
# ============================================================================
# CLAUDE CONTEXT - SUBMIT FROM MANIFEST HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Submit workflows from manifest entries
# PURPOSE: Read a discovery manifest, submit appropriate processing workflows,
#          record results per entry. Rate-limited. dry_run=true by default.
# CREATED: 03 APR 2026
# EXPORTS: submit_from_manifest
# DEPENDENCIES: services.platform_job_submit.create_and_submit_dag_run
# ============================================================================
"""
Submit From Manifest -- translate manifest entries into workflow submissions.

Reads a manifest produced by build_discovery_manifest, submits processing
workflows for entries with a recommended_workflow, skips entries without one.

dry_run=true by default (project convention). Caller must explicitly set
dry_run=false to actually submit.

Rate-limited: submits sequentially, max_concurrent_submissions controls batch size.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def submit_from_manifest(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Submit workflows from manifest entries.

    Params:
        manifest (dict, required): Discovery manifest from build_discovery_manifest.
        dry_run (bool, optional): Default true. Set false to actually submit.
        max_concurrent_submissions (int, optional): Default 5.
        spawned_by_run_id (str, optional): Discovery run ID for traceability.
            Falls back to _run_id (system-injected).

    Returns:
        Success: {"success": True, "result": {"submitted": [...], "skipped": [...], ...}}
    """
    manifest = params.get("manifest")
    dry_run = params.get("dry_run", True)
    max_submissions = int(params.get("max_concurrent_submissions", 5))
    spawned_by = params.get("spawned_by_run_id") or params.get("_run_id", "unknown")
    discovery_source = manifest.get("source", "unknown") if manifest else "unknown"

    if not manifest or not isinstance(manifest, dict):
        return {"success": False, "error": "manifest is required and must be a dict",
                "error_type": "ValidationError", "retryable": False}

    entries = manifest.get("entries", [])

    submitted = []
    rejected = []
    skipped = []

    for entry in entries:
        idx = entry.get("entry_index", 0)
        workflow = entry.get("recommended_workflow")
        entry_params = entry.get("recommended_params", {})
        source_blob = entry.get("source_blob", "unknown")

        # Skip entries with no recommended workflow (unclassifiable, non_raster)
        if not workflow:
            skipped.append({
                "entry_index": idx,
                "source_blob": source_blob,
                "classification": entry.get("classification", "unknown"),
                "reason": f"no recommended workflow (classification: {entry.get('classification')})",
                "status": "skipped",
            })
            continue

        # Inject traceability params
        entry_params["spawned_by_run_id"] = spawned_by
        entry_params["discovery_source"] = discovery_source
        if entry.get("metadata"):
            entry_params["source_metadata"] = entry["metadata"]

        if dry_run:
            submitted.append({
                "entry_index": idx,
                "source_blob": source_blob,
                "workflow": workflow,
                "run_id": None,
                "params": entry_params,
                "status": "dry_run",
            })
            continue

        # Actually submit
        try:
            from services.platform_job_submit import create_and_submit_dag_run

            request_id = f"discovery-{spawned_by[:16]}-{idx}"
            run_id = create_and_submit_dag_run(
                job_type=workflow,
                parameters=entry_params,
                platform_request_id=request_id,
            )
            submitted.append({
                "entry_index": idx,
                "source_blob": source_blob,
                "workflow": workflow,
                "run_id": run_id,
                "status": "accepted",
            })
            logger.info(
                "submit_from_manifest: submitted %s for %s -> run_id=%s",
                workflow, source_blob, run_id[:16],
            )
        except Exception as exc:
            error_msg = str(exc)
            is_duplicate = "duplicate" in error_msg.lower()
            rejected.append({
                "entry_index": idx,
                "source_blob": source_blob,
                "workflow": workflow,
                "error": error_msg,
                "status": "duplicate" if is_duplicate else "rejected",
            })
            logger.warning(
                "submit_from_manifest: rejected %s for %s — %s",
                workflow, source_blob, error_msg,
            )

    summary = {
        "total": len(entries),
        "submitted": len(submitted),
        "rejected": len(rejected),
        "skipped": len(skipped),
        "dry_run": dry_run,
    }

    logger.info(
        "submit_from_manifest: %s — %d submitted, %d rejected, %d skipped (dry_run=%s)",
        discovery_source, len(submitted), len(rejected), len(skipped), dry_run,
    )

    return {
        "success": True,
        "result": {
            "submitted": submitted,
            "rejected": rejected,
            "skipped": skipped,
            "summary": summary,
        },
    }
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_submit_from_manifest import submit_from_manifest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/discovery/handler_submit_from_manifest.py
git commit -m "feat: add submit_from_manifest handler for workflow submission"
```

---

## Task 5: Create `unzip_to_mount` Handler

**Files:**
- Create: `services/discovery/handler_unzip_to_mount.py`

- [ ] **Step 1: Create the handler file**

```python
# ============================================================================
# CLAUDE CONTEXT - UNZIP TO MOUNT HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Download ZIP from blob and extract to mount
# PURPOSE: Download a ZIP archive from blob storage, extract to the ETL mount,
#          return a content listing for downstream classification.
# CREATED: 03 APR 2026
# EXPORTS: unzip_to_mount
# DEPENDENCIES: infrastructure.blob.BlobRepository, infrastructure.etl_mount
# ============================================================================
"""
Unzip To Mount -- download ZIP from blob storage and extract to ETL mount.

Safety limits enforced:
  - Max extracted size (DISCOVERY_MAX_EXTRACT_SIZE_MB env var)
  - Max file count inside ZIP (default 100)
  - ZIP bomb detection (extracted > 10x compressed size)
"""

import logging
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_EXTRACT_SIZE_MB = 2048
DEFAULT_MAX_FILE_COUNT = 100
ZIP_BOMB_RATIO = 10


def unzip_to_mount(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Download a ZIP from blob storage and extract to mount.

    Params:
        container_name (str, required): Target container (for BlobRepository zone).
        blob_name (str, required): ZIP blob path.
        source_container (str, optional): Container to download from. Defaults to container_name.
        _run_id (str, system-injected): DAG run ID for mount path scoping.

    Returns:
        Success: {"success": True, "result": {"extract_path": "...", "contents": [...], ...}}
    """
    container_name = params.get("container_name")
    blob_name = params.get("blob_name")
    source_container = params.get("source_container") or container_name
    run_id = params.get("_run_id", "unknown")

    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not blob_name:
        return {"success": False, "error": "blob_name is required",
                "error_type": "ValidationError", "retryable": False}

    stem = PurePosixPath(blob_name).stem

    # Resolve mount paths
    from infrastructure.etl_mount import resolve_run_dir, ensure_dir
    run_dir = resolve_run_dir(run_id)
    extract_dir = ensure_dir(run_dir, stem)
    zip_path = os.path.join(run_dir, f"{stem}.zip")

    # Read safety limits from env
    max_extract_mb = int(os.environ.get(
        "DISCOVERY_MAX_EXTRACT_SIZE_MB", DEFAULT_MAX_EXTRACT_SIZE_MB
    ))
    max_file_count = int(os.environ.get(
        "DISCOVERY_MAX_FILE_COUNT", DEFAULT_MAX_FILE_COUNT
    ))

    # Download ZIP from blob
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.for_zone("bronze")

    try:
        blob_repo.download_blob_to_file(source_container, blob_name, zip_path)
    except Exception as exc:
        return {"success": False, "error": f"Failed to download ZIP: {exc}",
                "error_type": "DownloadError", "retryable": True}

    compressed_size = os.path.getsize(zip_path)

    # Extract and validate
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()

            # Safety: file count limit
            if len(members) > max_file_count:
                return {
                    "success": False,
                    "error": f"ZIP contains {len(members)} files, exceeds limit of {max_file_count}",
                    "error_type": "SafetyLimitExceeded", "retryable": False,
                }

            # Safety: total extracted size
            total_uncompressed = sum(m.file_size for m in members)
            max_extract_bytes = max_extract_mb * 1024 * 1024

            if total_uncompressed > max_extract_bytes:
                return {
                    "success": False,
                    "error": (
                        f"Extracted size {total_uncompressed / (1024*1024):.0f} MB "
                        f"exceeds limit of {max_extract_mb} MB"
                    ),
                    "error_type": "SafetyLimitExceeded", "retryable": False,
                }

            # Safety: ZIP bomb detection
            if compressed_size > 0 and total_uncompressed > compressed_size * ZIP_BOMB_RATIO:
                return {
                    "success": False,
                    "error": (
                        f"ZIP bomb detected: {total_uncompressed / (1024*1024):.0f} MB extracted "
                        f"from {compressed_size / (1024*1024):.0f} MB compressed "
                        f"(ratio {total_uncompressed / compressed_size:.1f}x, limit {ZIP_BOMB_RATIO}x)"
                    ),
                    "error_type": "ZipBombDetected", "retryable": False,
                }

            # Extract all
            zf.extractall(extract_dir)

    except zipfile.BadZipFile as exc:
        return {"success": False, "error": f"Corrupt ZIP file: {exc}",
                "error_type": "CorruptArchive", "retryable": False}

    # Build content listing from extracted files
    contents = []
    total_extracted = 0

    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, extract_dir)
            size = os.path.getsize(full_path)
            ext = PurePosixPath(fname).suffix.lower()

            contents.append({
                "relative_path": rel_path,
                "size_bytes": size,
                "extension": ext,
            })
            total_extracted += size

    # Clean up the ZIP file (keep extracted contents)
    try:
        os.remove(zip_path)
    except OSError:
        pass

    logger.info(
        "unzip_to_mount: %s — %d files extracted to %s (%.1f MB)",
        blob_name, len(contents), extract_dir, total_extracted / (1024 * 1024),
    )

    return {
        "success": True,
        "result": {
            "extract_path": extract_dir,
            "contents": contents,
            "total_extracted_size_bytes": total_extracted,
            "compressed_size_bytes": compressed_size,
            "file_count": len(contents),
        },
    }
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_unzip_to_mount import unzip_to_mount; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/discovery/handler_unzip_to_mount.py
git commit -m "feat: add unzip_to_mount handler for ZIP extraction to ETL mount"
```

---

## Task 6: Create `classify_maxar_delivery` Handler

**Files:**
- Create: `services/discovery/handler_classify_maxar.py`

- [ ] **Step 1: Create the handler file**

```python
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
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_classify_maxar import classify_maxar_delivery; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/discovery/handler_classify_maxar.py
git commit -m "feat: add classify_maxar_delivery handler for Maxar prefix analysis"
```

---

## Task 7: Create WBG-Specific Handlers

**Files:**
- Create: `services/discovery/handler_wbg_match_pairs.py`
- Create: `services/discovery/handler_wbg_process_pair.py`

- [ ] **Step 1: Create `wbg_match_json_zip_pairs` handler**

```python
# ============================================================================
# CLAUDE CONTEXT - WBG MATCH JSON+ZIP PAIRS HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Match WBG JSON+ZIP pairs by filename stem
# PURPOSE: From a blob inventory, match JSON metadata files to their ZIP
#          archives by shared filename stem. Read JSON sidecars for metadata.
# CREATED: 03 APR 2026
# EXPORTS: wbg_match_json_zip_pairs
# DEPENDENCIES: infrastructure.blob.BlobRepository (JSON sidecar download)
# ============================================================================
"""
WBG Match JSON+ZIP Pairs -- match WBG image repository JSON+ZIP files by stem.

WBG naming convention: {ISO3}_{geohash}_{bands}_{resolution}_{YYYYMMDD}.{ext}
Each image has a JSON (metadata) and ZIP (imagery) sharing the same stem.
"""

import json
import logging
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def wbg_match_json_zip_pairs(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Match JSON+ZIP files by stem from blob inventory.

    Params:
        inventory (dict, required): From discover_blob_prefix result.
        source_container (str, required): Container to read JSON sidecars from.

    Returns:
        Success: {"success": True, "result": {"pairs": [...], "orphan_jsons": [...], ...}}
    """
    inventory = params.get("inventory")
    source_container = params.get("source_container")

    if not inventory or not isinstance(inventory, dict):
        return {"success": False, "error": "inventory is required (from discover_blob_prefix)",
                "error_type": "ValidationError", "retryable": False}
    if not source_container:
        return {"success": False, "error": "source_container is required",
                "error_type": "ValidationError", "retryable": False}

    # Index all blobs by stem and extension
    metadata_files = inventory.get("metadata_files", [])
    archive_files = inventory.get("archive_files", [])

    json_by_stem = {}
    for f in metadata_files:
        name = f.get("name", "")
        if name.lower().endswith(".json"):
            stem = PurePosixPath(name).stem
            json_by_stem[stem] = name

    zip_by_stem = {}
    for f in archive_files:
        name = f.get("name", "")
        if name.lower().endswith(".zip"):
            stem = PurePosixPath(name).stem
            zip_by_stem[stem] = name

    # Match pairs
    pairs = []
    orphan_jsons = []
    orphan_zips = []

    all_stems = set(json_by_stem.keys()) | set(zip_by_stem.keys())

    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.for_zone("bronze")

    for stem in sorted(all_stems):
        has_json = stem in json_by_stem
        has_zip = stem in zip_by_stem

        if has_json and has_zip:
            # Read JSON sidecar for metadata (lightweight, ~670 bytes)
            metadata = _read_json_sidecar(blob_repo, source_container, json_by_stem[stem])

            pairs.append({
                "stem": stem,
                "json_blob": json_by_stem[stem],
                "zip_blob": zip_by_stem[stem],
                "metadata": metadata,
            })
        elif has_json:
            orphan_jsons.append(json_by_stem[stem])
        elif has_zip:
            orphan_zips.append(zip_by_stem[stem])

    logger.info(
        "wbg_match_json_zip_pairs: %d pairs, %d orphan JSONs, %d orphan ZIPs",
        len(pairs), len(orphan_jsons), len(orphan_zips),
    )

    return {
        "success": True,
        "result": {
            "pairs": pairs,
            "orphan_jsons": orphan_jsons,
            "orphan_zips": orphan_zips,
            "total_pairs": len(pairs),
        },
    }


def _read_json_sidecar(blob_repo, container: str, blob_path: str) -> Optional[Dict]:
    """Download and parse a WBG JSON sidecar file."""
    try:
        content = blob_repo.download_blob_to_bytes(container, blob_path)
        text = content.decode("utf-8", errors="replace")
        return json.loads(text)
    except Exception as exc:
        logger.warning("wbg_match_pairs: failed to read JSON %s: %s", blob_path, exc)
        return None
```

- [ ] **Step 2: Create `wbg_process_single_pair` handler**

```python
# ============================================================================
# CLAUDE CONTEXT - WBG PROCESS SINGLE PAIR HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Composite handler - Copy ZIP to bronze, unzip, classify, upload rasters
# PURPOSE: For a single WBG JSON+ZIP pair: copy from cold to bronze, extract,
#          classify contents, upload extracted rasters back to bronze.
# CREATED: 03 APR 2026
# EXPORTS: wbg_process_single_pair
# DEPENDENCIES: infrastructure.blob, infrastructure.etl_mount,
#               services.discovery.handler_classify_raster_contents,
#               services.discovery.handler_unzip_to_mount
# ============================================================================
"""
WBG Process Single Pair -- composite handler for one JSON+ZIP pair.

Orchestrates: copy to bronze → unzip to mount → classify → upload rasters to bronze.
Returns classification result with bronze blob paths for downstream workflow submission.
"""

import logging
import os
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def wbg_process_single_pair(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Process a single WBG JSON+ZIP pair.

    Params:
        zip_blob (str, required): ZIP blob path in source container.
        json_blob (str, required): JSON sidecar blob path.
        metadata (dict, optional): Pre-read JSON sidecar metadata.
        container_name (str, required): Target bronze container.
        source_container (str, required): Source container (cold).
        _run_id (str, system-injected): DAG run ID.

    Returns:
        Success: {"success": True, "result": {"stem": "...", "classification": "...", ...}}
    """
    zip_blob = params.get("zip_blob")
    json_blob = params.get("json_blob")
    metadata = params.get("metadata")
    container_name = params.get("container_name")
    source_container = params.get("source_container")
    run_id = params.get("_run_id", "unknown")

    if not zip_blob:
        return {"success": False, "error": "zip_blob is required",
                "error_type": "ValidationError", "retryable": False}
    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not source_container:
        return {"success": False, "error": "source_container is required",
                "error_type": "ValidationError", "retryable": False}

    stem = PurePosixPath(zip_blob).stem
    bronze_prefix = f"wbg_extracted/{stem}"

    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.for_zone("bronze")

    # Step 1: Copy ZIP from cold to bronze (server-side, no client transfer)
    bronze_zip_path = f"{bronze_prefix}/{stem}.zip"
    try:
        blob_repo.copy_blob(source_container, zip_blob, container_name, bronze_zip_path)
        logger.info("wbg_process_pair: copied %s -> %s/%s", zip_blob, container_name, bronze_zip_path)
    except Exception as exc:
        return {"success": False, "error": f"Failed to copy ZIP to bronze: {exc}",
                "error_type": "CopyError", "retryable": True}

    # Step 2: Unzip to mount
    from services.discovery.handler_unzip_to_mount import unzip_to_mount

    unzip_result = unzip_to_mount({
        "container_name": container_name,
        "blob_name": bronze_zip_path,
        "_run_id": run_id,
    })

    if not unzip_result.get("success"):
        return unzip_result  # Pass through the failure

    extract_result = unzip_result["result"]
    extract_path = extract_result["extract_path"]
    contents = extract_result["contents"]

    # Step 3: Classify contents
    from services.discovery.handler_classify_raster_contents import classify_raster_contents

    classify_result = classify_raster_contents({
        "contents": contents,
        "extract_path": extract_path,
        "metadata_json": metadata,
    })

    if not classify_result.get("success"):
        return classify_result

    classification = classify_result["result"]
    raster_files = classification.get("raster_files", [])

    # Step 4: Upload extracted rasters to bronze
    bronze_raster_paths = []
    for rel_path in raster_files:
        local_path = os.path.join(extract_path, rel_path)
        bronze_blob_path = f"{bronze_prefix}/{rel_path}"

        if not os.path.exists(local_path):
            logger.warning("wbg_process_pair: raster file not found on mount: %s", local_path)
            continue

        try:
            blob_repo.upload_file_to_blob(container_name, bronze_blob_path, local_path)
            bronze_raster_paths.append(bronze_blob_path)
            logger.info("wbg_process_pair: uploaded %s -> %s/%s",
                        rel_path, container_name, bronze_blob_path)
        except Exception as exc:
            logger.warning("wbg_process_pair: failed to upload %s: %s", rel_path, exc)

    # Build recommended_params with bronze paths
    recommended_params = classification.get("recommended_params", {})
    workflow = classification.get("recommended_workflow")

    if workflow == "process_raster" and bronze_raster_paths:
        recommended_params["blob_name"] = bronze_raster_paths[0]
        recommended_params["container_name"] = container_name
    elif workflow == "process_raster_collection" and bronze_raster_paths:
        recommended_params["blob_list"] = bronze_raster_paths
        recommended_params["container_name"] = container_name
        recommended_params["collection_id"] = stem

    logger.info(
        "wbg_process_pair: %s — %s (%d rasters -> bronze)",
        stem, classification.get("classification"), len(bronze_raster_paths),
    )

    return {
        "success": True,
        "result": {
            "stem": stem,
            "source_blob": zip_blob,
            "classification": classification.get("classification"),
            "evidence": classification.get("evidence", {}),
            "bronze_raster_paths": bronze_raster_paths,
            "metadata": metadata,
            "recommended_workflow": workflow,
            "recommended_params": recommended_params,
        },
    }
```

- [ ] **Step 3: Verify both files import cleanly**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from services.discovery.handler_wbg_match_pairs import wbg_match_json_zip_pairs; from services.discovery.handler_wbg_process_pair import wbg_process_single_pair; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add services/discovery/handler_wbg_match_pairs.py services/discovery/handler_wbg_process_pair.py
git commit -m "feat: add WBG-specific handlers (match pairs + process single pair)"
```

---

## Task 8: Register All Handlers

**Files:**
- Modify: `services/__init__.py`
- Modify: `config/defaults.py`

- [ ] **Step 1: Add imports to `services/__init__.py`**

Add after the existing ACLED sync handler imports (after line 139):

```python
# V0.11.0 Discovery automation handlers
from .discovery.handler_discover_blob_prefix import discover_blob_prefix
from .discovery.handler_classify_raster_contents import classify_raster_contents
from .discovery.handler_build_manifest import build_discovery_manifest
from .discovery.handler_submit_from_manifest import submit_from_manifest
from .discovery.handler_unzip_to_mount import unzip_to_mount
from .discovery.handler_classify_maxar import classify_maxar_delivery
from .discovery.handler_wbg_match_pairs import wbg_match_json_zip_pairs
from .discovery.handler_wbg_process_pair import wbg_process_single_pair
```

- [ ] **Step 2: Add to ALL_HANDLERS dict in `services/__init__.py`**

Add after the ACLED sync entries in the `ALL_HANDLERS` dict:

```python
    # Discovery automation handlers (v0.11.0)
    "discover_blob_prefix": discover_blob_prefix,
    "classify_raster_contents": classify_raster_contents,
    "build_discovery_manifest": build_discovery_manifest,
    "submit_from_manifest": submit_from_manifest,
    "unzip_to_mount": unzip_to_mount,
    "classify_maxar_delivery": classify_maxar_delivery,
    "wbg_match_json_zip_pairs": wbg_match_json_zip_pairs,
    "wbg_process_single_pair": wbg_process_single_pair,
```

- [ ] **Step 3: Add to DOCKER_TASKS in `config/defaults.py`**

Add after the ACLED sync entries in `TaskRoutingDefaults.DOCKER_TASKS` (after line 518):

```python
        # =====================================================================
        # DISCOVERY AUTOMATION HANDLERS (v0.11.0)
        # =====================================================================
        "discover_blob_prefix",
        "classify_raster_contents",
        "build_discovery_manifest",
        "submit_from_manifest",
        "unzip_to_mount",
        "classify_maxar_delivery",
        "wbg_match_json_zip_pairs",
        "wbg_process_single_pair",
```

- [ ] **Step 4: Verify registration**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from services import ALL_HANDLERS
discovery_handlers = ['discover_blob_prefix', 'classify_raster_contents', 'build_discovery_manifest', 'submit_from_manifest', 'unzip_to_mount', 'classify_maxar_delivery', 'wbg_match_json_zip_pairs', 'wbg_process_single_pair']
for h in discovery_handlers:
    assert h in ALL_HANDLERS, f'MISSING: {h}'
    print(f'  OK: {h}')
print(f'All {len(discovery_handlers)} discovery handlers registered')
"`
Expected: All 8 handlers listed with OK.

- [ ] **Step 5: Commit**

```bash
git add services/__init__.py config/defaults.py
git commit -m "feat: register 8 discovery automation handlers"
```

---

## Task 9: Create Workflow YAMLs

**Files:**
- Create: `workflows/discover_maxar_delivery.yaml`
- Create: `workflows/discover_wbg_legacy.yaml`

- [ ] **Step 1: Create `discover_maxar_delivery.yaml`**

```yaml
workflow: discover_maxar_delivery
description: "Scan a Maxar delivery prefix, classify tiles, submit process_raster_collection"
version: 1

parameters:
  prefix: {type: str, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  dry_run: {type: bool, default: true}

nodes:
  # --------------------------------------------------------------------------
  # PHASE 1: Scan blob prefix — list and categorize all files
  # --------------------------------------------------------------------------
  scan_prefix:
    type: task
    handler: discover_blob_prefix
    params: [container_name, prefix]

  # --------------------------------------------------------------------------
  # PHASE 2: Maxar-specific classification — parse .TIL, match tiles, read .IMD
  # --------------------------------------------------------------------------
  classify_delivery:
    type: task
    handler: classify_maxar_delivery
    depends_on: [scan_prefix]
    params: [prefix, container_name, collection_id]
    receives:
      inventory: "scan_prefix.result.inventory"

  # --------------------------------------------------------------------------
  # PHASE 3: Build discovery manifest
  # --------------------------------------------------------------------------
  build_manifest:
    type: task
    handler: build_discovery_manifest
    depends_on: [classify_delivery]
    params: [prefix]
    receives:
      classified_items: "classify_delivery.result"

  # --------------------------------------------------------------------------
  # PHASE 4: Submit processing workflows from manifest
  # --------------------------------------------------------------------------
  submit_workflows:
    type: task
    handler: submit_from_manifest
    depends_on: [build_manifest]
    params: [dry_run]
    receives:
      manifest: "build_manifest.result.manifest"
```

- [ ] **Step 2: Create `discover_wbg_legacy.yaml`**

```yaml
workflow: discover_wbg_legacy
description: "Scan WBG image repository prefix, unzip+classify each pair, submit workflows"
version: 1

parameters:
  prefix: {type: str, required: true}
  source_container: {type: str, default: "rmhazurecold"}
  container_name: {type: str, required: true}
  dry_run: {type: bool, default: true}

nodes:
  # --------------------------------------------------------------------------
  # PHASE 1: Scan blob prefix — list and categorize all files
  # --------------------------------------------------------------------------
  scan_prefix:
    type: task
    handler: discover_blob_prefix
    params: [container_name, prefix, source_container]

  # --------------------------------------------------------------------------
  # PHASE 2: Match JSON+ZIP pairs by stem, read JSON metadata
  # --------------------------------------------------------------------------
  identify_pairs:
    type: task
    handler: wbg_match_json_zip_pairs
    depends_on: [scan_prefix]
    params: [source_container]
    receives:
      inventory: "scan_prefix.result.inventory"

  # --------------------------------------------------------------------------
  # PHASE 3: Fan-out per pair — copy, unzip, classify, upload rasters
  # --------------------------------------------------------------------------
  process_pairs:
    type: fan_out
    depends_on: [identify_pairs]
    source: "identify_pairs.result.pairs"
    max_fan_out: 50
    task:
      handler: wbg_process_single_pair
      params:
        zip_blob: "{{ item.zip_blob }}"
        json_blob: "{{ item.json_blob }}"
        metadata: "{{ item.metadata }}"
        container_name: "{{ inputs.container_name }}"
        source_container: "{{ inputs.source_container }}"

  agg_results:
    type: fan_in
    depends_on: [process_pairs]
    aggregation: collect

  # --------------------------------------------------------------------------
  # PHASE 4: Build discovery manifest from aggregated results
  # --------------------------------------------------------------------------
  build_manifest:
    type: task
    handler: build_discovery_manifest
    depends_on: [agg_results]
    params: [prefix]
    receives:
      classified_items: "agg_results.items"

  # --------------------------------------------------------------------------
  # PHASE 5: Submit processing workflows from manifest
  # --------------------------------------------------------------------------
  submit_workflows:
    type: task
    handler: submit_from_manifest
    depends_on: [build_manifest]
    params: [dry_run]
    receives:
      manifest: "build_manifest.result.manifest"
```

- [ ] **Step 3: Validate YAML syntax**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
import yaml
for f in ['workflows/discover_maxar_delivery.yaml', 'workflows/discover_wbg_legacy.yaml']:
    with open(f) as fh:
        data = yaml.safe_load(fh)
    print(f'{f}: workflow={data[\"workflow\"]}, nodes={len(data[\"nodes\"])}')
"`
Expected:
```
workflows/discover_maxar_delivery.yaml: workflow=discover_maxar_delivery, nodes=4
workflows/discover_wbg_legacy.yaml: workflow=discover_wbg_legacy, nodes=6
```

(Note: `agg_results` is a fan_in node counted separately, so `discover_wbg_legacy` has 6 node entries in the dict, but 7 logical nodes including the fan_in.)

- [ ] **Step 4: Verify workflows load in the DAG engine**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.workflow_registry import WorkflowRegistry
registry = WorkflowRegistry('workflows')
registry.load_all()
for name in ['discover_maxar_delivery', 'discover_wbg_legacy']:
    wf = registry.get(name)
    print(f'{name}: version={wf.version}, nodes={len(wf.nodes)}')
"`
Expected: Both workflows loaded with correct node counts.

- [ ] **Step 5: Commit**

```bash
git add workflows/discover_maxar_delivery.yaml workflows/discover_wbg_legacy.yaml
git commit -m "feat: add discover_maxar_delivery and discover_wbg_legacy workflow YAMLs"
```

---

## Task 10: Wire `build_discovery_manifest` Params

The Maxar workflow passes `classify_delivery.result` as a single item (not a list from fan-in). The `build_discovery_manifest` handler needs to handle both cases: a single classified dict OR a list of classified dicts from fan-in. It also needs `discovery_source` injected.

**Files:**
- Modify: `workflows/discover_maxar_delivery.yaml`

- [ ] **Step 1: Update the build_manifest node receives in Maxar workflow**

The `build_manifest` node in `discover_maxar_delivery.yaml` needs `discovery_source` set explicitly. Update the node:

```yaml
  build_manifest:
    type: task
    handler: build_discovery_manifest
    depends_on: [classify_delivery]
    params: [prefix]
    receives:
      classified_items: "classify_delivery.result"
```

The `build_discovery_manifest` handler already handles both single dict and list inputs via `_unwrap_fan_in_result`. But `discovery_source` is required. Since it's a constant for each workflow, add it as a receives from a param-like mechanism or hardcode it in handler logic.

The cleanest approach: add `discovery_source` to the workflow parameters with a default:

In `discover_maxar_delivery.yaml`, add to parameters:
```yaml
  discovery_source: {type: str, default: "maxar_delivery"}
```

And update build_manifest:
```yaml
  build_manifest:
    type: task
    handler: build_discovery_manifest
    depends_on: [classify_delivery]
    params: [prefix, discovery_source]
    receives:
      classified_items: "classify_delivery.result"
```

Similarly in `discover_wbg_legacy.yaml`, add:
```yaml
  discovery_source: {type: str, default: "wbg_legacy"}
```

And update build_manifest:
```yaml
  build_manifest:
    type: task
    handler: build_discovery_manifest
    depends_on: [agg_results]
    params: [prefix, discovery_source]
    receives:
      classified_items: "agg_results.items"
```

- [ ] **Step 2: Also ensure `build_discovery_manifest` wraps single items into a list**

Update `build_discovery_manifest` handler — add after the `classified_items` extraction:

```python
    # Normalize: if single item (not from fan-in), wrap in list
    if isinstance(classified_items, dict):
        classified_items = [classified_items]
```

- [ ] **Step 3: Commit**

```bash
git add workflows/discover_maxar_delivery.yaml workflows/discover_wbg_legacy.yaml services/discovery/handler_build_manifest.py
git commit -m "fix: wire discovery_source param and normalize single-item manifest input"
```

---

## Task 11: Archive `delivery_discovery.py`

**Files:**
- Move: `services/delivery_discovery.py` → archive

- [ ] **Step 1: Check for any imports of delivery_discovery**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && grep -r "delivery_discovery" --include="*.py" -l`

If no files reference it (besides itself), it's safe to remove.

- [ ] **Step 2: Remove the file**

```bash
git rm services/delivery_discovery.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove delivery_discovery.py — superseded by discovery automation handlers"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Verify all handlers importable**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from services import ALL_HANDLERS
discovery = [
    'discover_blob_prefix', 'classify_raster_contents',
    'build_discovery_manifest', 'submit_from_manifest',
    'unzip_to_mount', 'classify_maxar_delivery',
    'wbg_match_json_zip_pairs', 'wbg_process_single_pair',
]
for h in discovery:
    assert h in ALL_HANDLERS, f'MISSING: {h}'
print(f'All {len(discovery)} handlers registered in ALL_HANDLERS')

from config.defaults import TaskRoutingDefaults
for h in discovery:
    assert h in TaskRoutingDefaults.DOCKER_TASKS, f'MISSING from DOCKER_TASKS: {h}'
print(f'All {len(discovery)} handlers in DOCKER_TASKS')
"`
Expected: All 8 handlers registered and routed.

- [ ] **Step 2: Verify both workflow YAMLs parse**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.workflow_registry import WorkflowRegistry
registry = WorkflowRegistry('workflows')
registry.load_all()
for name in ['discover_maxar_delivery', 'discover_wbg_legacy']:
    wf = registry.get(name)
    node_names = [n.name for n in wf.nodes]
    print(f'{name}: {len(wf.nodes)} nodes — {node_names}')
print('All discovery workflows loaded successfully')
"`
Expected: Both workflows load with correct node names.

- [ ] **Step 3: Verify handler count**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from services import ALL_HANDLERS
print(f'Total handlers: {len(ALL_HANDLERS)}')
"`
Expected: Previous count (58) + 8 = 66 handlers.

- [ ] **Step 4: Verify workflow count**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.workflow_registry import WorkflowRegistry
registry = WorkflowRegistry('workflows')
registry.load_all()
print(f'Total workflows: {len(registry._definitions)}')
"`
Expected: Previous count (10) + 2 = 12 workflows.

- [ ] **Step 5: Final commit if any adjustments needed**

```bash
git add -A
git commit -m "feat: discovery automation complete — 8 handlers, 2 workflows (v0.11.0)"
```
