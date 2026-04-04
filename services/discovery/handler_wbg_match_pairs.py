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
