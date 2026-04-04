# ============================================================================
# CLAUDE CONTEXT - SUBMIT FROM MANIFEST HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Submit workflows from manifest entries
# PURPOSE: Read a discovery manifest, submit appropriate processing workflows,
#          record results per entry. dry_run=true by default.
# CREATED: 03 APR 2026
# EXPORTS: submit_from_manifest
# DEPENDENCIES: services.platform_job_submit.create_and_submit_dag_run
# ============================================================================
"""
Submit From Manifest -- translate manifest entries into workflow submissions.

Reads a manifest produced by build_discovery_manifest, submits processing
workflows for entries with a recommended_workflow, skips entries without one.

dry_run=true by default (project convention). Caller must explicitly set
dry_run=false to actually submit. Submissions are sequential — the Brain
picks up runs asynchronously so there is no benefit to batching.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def submit_from_manifest(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Submit workflows from manifest entries.

    Params:
        manifest (dict, required): Discovery manifest from build_discovery_manifest.
        dry_run (bool, optional): Default true. Set false to actually submit.
        spawned_by_run_id (str, optional): Discovery run ID for traceability.
            Falls back to _run_id (system-injected).

    Returns:
        Success: {"success": True, "result": {"submitted": [...], "skipped": [...], ...}}
    """
    manifest = params.get("manifest")
    dry_run = params.get("dry_run", True)
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
