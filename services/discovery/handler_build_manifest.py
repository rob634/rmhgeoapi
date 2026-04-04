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

    # Normalize: if single item (not from fan-in), wrap in list
    if isinstance(classified_items, dict):
        classified_items = [classified_items]

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
