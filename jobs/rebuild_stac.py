# ============================================================================
# REBUILD STAC JOB
# ============================================================================
# STATUS: Jobs - 2-stage STAC rebuild workflow
# PURPOSE: Regenerate STAC items from source data (PostGIS tables, COG blobs)
# CREATED: 10 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.11 STAC Catalog Self-Healing
# ============================================================================
"""
STAC Rebuild Job.

Regenerates STAC items from source data for items with broken backlinks
or missing STAC entries. Used by F7.10 Metadata Consistency to remediate
detected issues.

Stages:
    1. validate - Check each source exists, filter rebuildable items
    2. rebuild - Regenerate STAC item for each valid source (fan-out)

Parameters:
    data_type: 'vector' or 'raster' (required)
    items: List of table names (vector) or cog_ids (raster) (required)
    dry_run: If True, validate only without rebuilding (default: True)
    force_recreate: Delete existing STAC item before rebuild (default: False)
    collection_id: Override target collection (default: auto-detect)

Usage:
    POST /api/jobs/submit/rebuild_stac
    {
        "data_type": "vector",
        "items": ["curated_admin0", "system_ibat_kba"],
        "dry_run": false
    }

Exports:
    RebuildStacJob: Job class for STAC catalog rebuild
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class RebuildStacJob(JobBaseMixin, JobBase):
    """
    Rebuild STAC items from source data.

    Two-stage pipeline:
        1. validate - Check sources exist, build rebuild list
        2. rebuild - Regenerate STAC item per source (fan-out)

    Reuses existing handlers:
        - create_vector_stac for vectors
        - extract_stac_metadata for rasters (future)
    """

    job_type = "rebuild_stac"
    description = "Regenerate STAC items from source data (vectors/rasters)"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "stac_rebuild_validate",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "rebuild",
            "task_type": "stac_rebuild_item",
            "parallelism": "fan_out"
        }
    ]

    parameters_schema = {
        'data_type': {
            'type': 'str',
            'required': True,
            'enum': ['vector', 'raster']
        },
        'items': {
            'type': 'list',
            'required': True,
            'min_length': 1,
            'max_length': 100  # Reasonable batch size
        },
        'dry_run': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'force_recreate': {
            'type': 'bool',
            'required': False,
            'default': False
        },
        'collection_id': {
            'type': 'str',
            'required': False,
            'default': None
        },
        'schema': {
            'type': 'str',
            'required': False,
            'default': 'geo'  # For vectors
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
        Generate tasks for each stage.

        Stage 1: Single validate task to check all sources exist
        Stage 2: One rebuild task per valid source (fan-out)
        """
        if stage == 1:
            # Stage 1: Validate - single task to check all sources
            return [{
                "task_id": f"{job_id[:8]}-validate",
                "task_type": "stac_rebuild_validate",
                "parameters": {
                    "data_type": job_params.get('data_type'),
                    "items": job_params.get('items', []),
                    "schema": job_params.get('schema', 'geo'),
                    "collection_id": job_params.get('collection_id'),
                    "force_recreate": job_params.get('force_recreate', False)
                }
            }]

        elif stage == 2:
            # Stage 2: Rebuild - one task per valid source
            if not previous_results:
                return []

            validate_result = previous_results[0].get('result', {})
            valid_items = validate_result.get('valid_items', [])

            # If dry run, skip rebuild stage
            if job_params.get('dry_run', True):
                return []

            # Create rebuild task for each valid item
            rebuild_tasks = []
            data_type = job_params.get('data_type')
            schema = job_params.get('schema', 'geo')
            collection_id = job_params.get('collection_id')
            force_recreate = job_params.get('force_recreate', False)

            for idx, item_info in enumerate(valid_items):
                item_name = item_info.get('name') if isinstance(item_info, dict) else item_info

                rebuild_tasks.append({
                    "task_id": f"{job_id[:8]}-rebuild-{idx:04d}",
                    "task_type": "stac_rebuild_item",
                    "parameters": {
                        "data_type": data_type,
                        "item_name": item_name,
                        "schema": schema,
                        "collection_id": collection_id,
                        "force_recreate": force_recreate,
                        "job_id": job_id
                    }
                })

            return rebuild_tasks

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "rebuild_stac"
            }

        # Count results
        total_requested = 0
        valid_count = 0
        invalid_count = 0
        rebuilt_count = 0
        failed_count = 0
        dry_run = True

        for task_result in context.task_results:
            result = task_result.get('result', {})

            if task_result.get('task_type') == 'stac_rebuild_validate':
                total_requested = result.get('total_requested', 0)
                valid_count = len(result.get('valid_items', []))
                invalid_count = len(result.get('invalid_items', []))
                dry_run = result.get('dry_run', True)

            elif task_result.get('task_type') == 'stac_rebuild_item':
                if result.get('rebuilt', False):
                    rebuilt_count += 1
                elif not task_result.get('success', False):
                    failed_count += 1

        return {
            "status": "completed",
            "job_type": "rebuild_stac",
            "summary": {
                "total_requested": total_requested,
                "valid_sources": valid_count,
                "invalid_sources": invalid_count,
                "rebuilt": rebuilt_count,
                "failed": failed_count,
                "dry_run": dry_run
            }
        }


# Module exports
__all__ = ['RebuildStacJob']
