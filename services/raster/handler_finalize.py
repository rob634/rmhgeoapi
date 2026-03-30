# ============================================================================
# CLAUDE CONTEXT - RASTER FINALIZE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Atomic handler - Clean up ETL mount directory after raster workflow
# PURPOSE: Remove intermediate files (COGs, temp rasters) from mount
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: raster_finalize
# DEPENDENCIES: config, shutil
# ============================================================================
"""
Raster Finalize — mount cleanup handler for DAG workflows.

Runs as the finalize step in process_raster workflow. Removes the
run's ETL mount directory (/mount/etl-temp/{run_id}/) to prevent
disk space accumulation from intermediate COG and raster files.

Must run on both success and failure paths (always_run: true in YAML).
"""

import os
import shutil
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_raster_finalize")


def raster_finalize(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Clean up ETL mount directory for a raster workflow run.

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
        logger.info(f"Raster finalize: mount dir does not exist (already cleaned?): {mount_dir}")
        return {"success": True, "result": {"cleaned": False, "path": mount_dir, "reason": "Directory does not exist"}}

    try:
        # Count files before cleanup for reporting
        file_count = sum(len(files) for _, _, files in os.walk(mount_dir))
        dir_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(mount_dir) for f in fn)

        shutil.rmtree(mount_dir, ignore_errors=True)

        logger.info(f"Raster finalize: cleaned mount dir {mount_dir} ({file_count} files, {dir_size / 1024 / 1024:.1f} MB)")

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
        logger.warning(f"Raster finalize: failed to clean mount dir {mount_dir}: {e}")
        return {
            "success": True,
            "result": {
                "cleaned": False,
                "path": mount_dir,
                "error": str(e),
                "warning": "Mount cleanup failed — manual cleanup may be needed",
            },
        }
