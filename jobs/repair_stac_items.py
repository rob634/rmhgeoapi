# ============================================================================
# CLAUDE CONTEXT - STAC REPAIR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - Scan and repair STAC catalog items
# PURPOSE: Find and fix non-compliant STAC items in pgSTAC
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: RepairStacItemsJob
# DEPENDENCIES: jobs.base, jobs.mixins, services.stac_validation
# ============================================================================
"""
STAC Repair Job.

Scans the pgSTAC catalog for items with validation issues and repairs them.
Prioritizes promoted datasets when running repairs.

Stages:
    1. inventory - Query pgSTAC for all items, validate each, build repair list
    2. repair - Fix each item and update in database

Parameters:
    collection_id: Optional - limit to specific collection
    dry_run: If True, report issues without fixing (default: True)
    fix_version: Repair STAC version mismatches (default: True)
    fix_datetime: Add datetime if missing (default: True)
    fix_geometry: Derive geometry from bbox if missing (default: True)
    prioritize_promoted: Process promoted items first (default: True)
    limit: Maximum items to process (default: 1000)

Exports:
    RepairStacItemsJob: Job class for STAC catalog repair

Created: 22 DEC 2025
"""

from typing import List, Dict, Any, Optional

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class RepairStacItemsJob(JobBaseMixin, JobBase):
    """
    Scan and repair STAC catalog items.

    Two-stage pipeline:
        1. inventory - Find all items with issues
        2. repair - Fix each item and update database

    Prioritization:
        - Promoted datasets are repaired first (gallery-featured items matter more)
        - System collections before user collections
    """

    job_type = "repair_stac_items"
    description = "Scan and repair STAC catalog for non-compliant items"

    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "stac_repair_inventory",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "repair",
            "task_type": "stac_repair_item",
            "parallelism": "fan_out"
        }
    ]

    parameters_schema = {
        'collection_id': {
            'type': 'str',
            'required': False,
            'default': None
        },
        'dry_run': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'fix_version': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'fix_datetime': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'fix_geometry': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'prioritize_promoted': {
            'type': 'bool',
            'required': False,
            'default': True
        },
        'limit': {
            'type': 'int',
            'required': False,
            'default': 1000,
            'min': 1,
            'max': 10000
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

        Stage 1: Single inventory task
        Stage 2: One task per item that needs repair
        """
        if stage == 1:
            # Stage 1: Inventory - single task to scan catalog
            return [{
                "task_id": f"{job_id[:8]}-inventory",
                "task_type": "stac_repair_inventory",
                "parameters": {
                    "collection_id": job_params.get('collection_id'),
                    "prioritize_promoted": job_params.get('prioritize_promoted', True),
                    "limit": job_params.get('limit', 1000)
                }
            }]

        elif stage == 2:
            # Stage 2: Repair - one task per item with issues
            if not previous_results:
                return []

            inventory_result = previous_results[0].get('result', {})
            items_to_repair = inventory_result.get('items_with_issues', [])

            # If dry run, no repair tasks
            if job_params.get('dry_run', True):
                return []

            # Create repair task for each item
            repair_tasks = []
            for idx, item_info in enumerate(items_to_repair):
                repair_tasks.append({
                    "task_id": f"{job_id[:8]}-repair-{idx:04d}",
                    "task_type": "stac_repair_item",
                    "parameters": {
                        "item_id": item_info['item_id'],
                        "collection_id": item_info['collection_id'],
                        "issues": item_info['issues'],
                        "fix_version": job_params.get('fix_version', True),
                        "fix_datetime": job_params.get('fix_datetime', True),
                        "fix_geometry": job_params.get('fix_geometry', True)
                    }
                })

            return repair_tasks

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "repair_stac_items"
            }

        # Count results
        total_scanned = 0
        items_with_issues = 0
        items_repaired = 0

        for task_result in context.task_results:
            result = task_result.get('result', {})
            if task_result.get('task_type') == 'stac_repair_inventory':
                total_scanned = result.get('total_scanned', 0)
                items_with_issues = len(result.get('items_with_issues', []))
            elif task_result.get('task_type') == 'stac_repair_item':
                if result.get('repaired', False):
                    items_repaired += 1

        return {
            "status": "completed",
            "job_type": "repair_stac_items",
            "total_scanned": total_scanned,
            "items_with_issues": items_with_issues,
            "items_repaired": items_repaired
        }


# Module exports
__all__ = ['RepairStacItemsJob']
