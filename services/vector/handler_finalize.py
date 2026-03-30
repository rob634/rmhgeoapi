# ============================================================================
# CLAUDE CONTEXT - VECTOR FINALIZE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Clean up ETL mount directory after workflow completion
# PURPOSE: Remove intermediate files (GeoParquet, extracted archives) from mount
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: vector_finalize
# DEPENDENCIES: config, shutil
# ============================================================================
"""
Vector Finalize — mount cleanup handler for DAG workflows.

Runs as the finalize step in vector_docker_etl workflow. Removes the
run's ETL mount directory (/mount/etl-temp/{run_id}/) to prevent
disk space accumulation from intermediate GeoParquet files.

Must run on both success and failure paths (always_run: true in YAML).
"""

import os
import shutil
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_vector_finalize")


def vector_finalize(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Clean up ETL mount directory for a workflow run.

    Params:
        _run_id: DAG run ID (system-injected) — used to construct mount path

    Returns:
        {"success": True, "result": {cleaned_path, files_removed}}
    """
    run_id = params.get('_run_id') or params.get('_job_id', '')

    if not run_id:
        return {"success": True, "result": {"cleaned": False, "reason": "No _run_id available"}}

    from config import get_config
    config = get_config()
    etl_mount_root = config.docker.etl_mount_path if config.docker and config.docker.etl_mount_path else "/mnt/etl"
    mount_dir = os.path.join(etl_mount_root, run_id)

    if not os.path.exists(mount_dir):
        logger.info(f"Finalize: mount dir does not exist (already cleaned?): {mount_dir}")
        return {"success": True, "result": {"cleaned": False, "path": mount_dir, "reason": "Directory does not exist"}}

    try:
        # Count files before cleanup for reporting
        file_count = sum(len(files) for _, _, files in os.walk(mount_dir))
        dir_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(mount_dir) for f in fn)

        shutil.rmtree(mount_dir, ignore_errors=True)

        logger.info(f"Finalize: cleaned mount dir {mount_dir} ({file_count} files, {dir_size / 1024 / 1024:.1f} MB)")

        return {
            "success": True,
            "result": {
                "cleaned": True,
                "path": mount_dir,
                "files_removed": file_count,
                "bytes_freed": dir_size,
            },
        }

    except Exception as e:
        # Cleanup failure is non-fatal — log and return success
        logger.warning(f"Finalize: failed to clean mount dir {mount_dir}: {e}")
        return {
            "success": True,
            "result": {
                "cleaned": False,
                "path": mount_dir,
                "error": str(e),
                "warning": "Mount cleanup failed — manual cleanup may be needed",
            },
        }
