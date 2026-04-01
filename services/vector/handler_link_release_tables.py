# ============================================================================
# CLAUDE CONTEXT - VECTOR LINK RELEASE TABLES HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9.10)
# STATUS: Atomic handler - Link PostGIS tables to release for preview URLs
# PURPOSE: Write release_tables entries and set processing_status=COMPLETED
#          so platform/status can build TiPG preview URLs for reviewers.
#          Runs PRE-GATE — data is browsable by admins before approval.
# LAST_REVIEWED: 01 APR 2026
# EXPORTS: release_link_tables
# DEPENDENCIES: infrastructure.release_repository, infrastructure.release_table_repository
# ============================================================================
"""
Release Link Tables — write table names to release record.

Extracted from vector_register_catalog (which runs post-gate for rich metadata).
This handler runs pre-gate so that platform/status can build preview URLs
for the approval reviewer. Without this, the release has no table_names
and the viewer_url is null.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def release_link_tables(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Link PostGIS table names to a release record.

    Params:
        release_id (str, required): Release to update.
        tables_created (list, required): From create_and_load_tables result.
            Each entry: {table_name, geometry_type, row_count, ...}
        _run_id (str): System-injected DAG run ID.

    Returns:
        {"success": True, "result": {tables_linked, release_id}}
    """
    release_id = params.get('release_id')
    tables_created = params.get('tables_created', [])
    _run_id = params.get('_run_id', 'unknown')

    if not release_id:
        # No release context (e.g. direct DAG submit without platform).
        # Not an error — just nothing to link.
        return {
            "success": True,
            "result": {"tables_linked": 0, "skipped": "no release_id"},
        }

    if not tables_created:
        return {
            "success": False,
            "error": "tables_created is required (list of table results)",
            "error_type": "ValidationError",
            "retryable": False,
        }

    log_prefix = f"[{_run_id[:8]}]"

    try:
        from infrastructure.release_table_repository import ReleaseTableRepository
        from infrastructure.release_repository import ReleaseRepository
        from core.models.asset import ProcessingStatus
        from datetime import datetime, timezone

        release_table_repo = ReleaseTableRepository()
        release_repo = ReleaseRepository()

        # Write release_tables junction entries
        linked = 0
        for entry in tables_created:
            t_name = entry.get('table_name')
            if not t_name:
                continue
            release_table_repo.create(
                release_id=release_id,
                table_name=t_name,
                geometry_type=entry.get('geometry_type', 'unknown'),
                feature_count=entry.get('row_count', 0),
                table_role="primary" if len(tables_created) == 1 else "geometry_split",
            )
            linked += 1

        # Set processing_status=COMPLETED so platform/status shows outputs
        release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

        logger.info(
            "%s release_link_tables: linked %d table(s) to release %s",
            log_prefix, linked, release_id[:16],
        )

        return {
            "success": True,
            "result": {
                "tables_linked": linked,
                "release_id": release_id,
            },
        }

    except Exception as exc:
        logger.error(
            "%s release_link_tables failed: %s", log_prefix, exc, exc_info=True,
        )
        return {
            "success": False,
            "error": f"Failed to link tables to release: {exc}",
            "error_type": "DatabaseError",
            "retryable": True,
        }
