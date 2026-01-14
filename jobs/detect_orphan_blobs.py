# ============================================================================
# DETECT ORPHAN BLOBS JOB
# ============================================================================
# STATUS: Jobs - Single-stage orphan blob detection
# PURPOSE: Find COGs in silver storage without app.cog_metadata entries
# CREATED: 14 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.11 STAC Catalog Self-Healing
# ============================================================================
"""
Detect Orphan Blobs Job.

Scans a silver storage container for COG files and compares against
app.cog_metadata to identify orphaned blobs (exist in storage but have
no metadata registration).

This is a detection-only job. Use register_silver_blobs to register
detected orphans.

Stages:
    1. inventory - Scan container, compare to cog_metadata, return orphan list

Parameters:
    container: Silver container to scan (required, e.g., "silver-cogs")
    zone: Storage zone - "silver" or "silverext" (default: "silver")
    prefix: Blob path prefix filter (optional)
    suffix: File extension filter (default: ".tif")
    limit: Maximum blobs to scan (default: 1000, max: 10000)

Usage:
    POST /api/jobs/submit/detect_orphan_blobs
    {
        "container": "silver-cogs",
        "suffix": ".tif",
        "limit": 500
    }

Exports:
    DetectOrphanBlobsJob: Job class for orphan blob detection
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class DetectOrphanBlobsJob(JobBaseMixin, JobBase):
    """
    Detect orphaned blobs in silver storage.

    Single-stage pipeline:
        1. inventory - Scan container and identify orphans

    Orphan Definition:
        A blob is considered orphaned if:
        - It exists in the specified silver container
        - It has no corresponding record in app.cog_metadata
    """

    job_type = "detect_orphan_blobs"
    description = "Detect COGs in silver storage without metadata registration"

    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "orphan_blob_inventory",
            "parallelism": "single"
        }
    ]

    parameters_schema = {
        'container': {
            'type': 'str',
            'required': True,
            'description': 'Silver container to scan (e.g., "silver-cogs", "silver-fathom")'
        },
        'zone': {
            'type': 'str',
            'required': False,
            'default': 'silver',
            'enum': ['silver', 'silverext'],
            'description': 'Storage zone for multi-account setup'
        },
        'prefix': {
            'type': 'str',
            'required': False,
            'default': '',
            'description': 'Blob path prefix filter'
        },
        'suffix': {
            'type': 'str',
            'required': False,
            'default': '.tif',
            'description': 'File extension filter (e.g., ".tif", ".cog")'
        },
        'limit': {
            'type': 'int',
            'required': False,
            'default': 1000,
            'min': 1,
            'max': 10000,
            'description': 'Maximum blobs to scan'
        }
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[Dict[str, Any]]:
        """
        Generate tasks for inventory stage.

        Stage 1: Single inventory task to scan container and compare to metadata.
        """
        if stage == 1:
            return [{
                "task_id": f"{job_id[:8]}-inventory",
                "task_type": "orphan_blob_inventory",
                "parameters": {
                    "container": job_params.get('container'),
                    "zone": job_params.get('zone', 'silver'),
                    "prefix": job_params.get('prefix', ''),
                    "suffix": job_params.get('suffix', '.tif'),
                    "limit": job_params.get('limit', 1000),
                    "job_id": job_id
                }
            }]

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "detect_orphan_blobs"
            }

        # Extract results from inventory task
        for task_result in context.task_results:
            result_data = task_result.result_data or {}
            result = result_data.get('result', {})

            if task_result.task_type == 'orphan_blob_inventory':
                return {
                    "status": "completed",
                    "job_type": "detect_orphan_blobs",
                    "summary": {
                        "container": result.get('container'),
                        "blobs_scanned": result.get('blobs_scanned', 0),
                        "registered_count": result.get('registered_count', 0),
                        "orphan_count": result.get('orphan_count', 0),
                        "orphan_total_mb": result.get('orphan_total_mb', 0)
                    },
                    "orphans": result.get('orphans', []),
                    "next_step": (
                        "Use register_silver_blobs job with orphan list to create STAC entries"
                        if result.get('orphan_count', 0) > 0
                        else "No orphans detected - all blobs are registered"
                    )
                }

        return {
            "status": "completed",
            "job_type": "detect_orphan_blobs",
            "summary": {"error": "No inventory results found"}
        }


# Module exports
__all__ = ['DetectOrphanBlobsJob']
