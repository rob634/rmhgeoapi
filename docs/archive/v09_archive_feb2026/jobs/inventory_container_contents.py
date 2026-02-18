# ============================================================================
# INVENTORY CONTAINER CONTENTS JOB
# ============================================================================
# STATUS: Jobs - 3-stage container inventory with analysis modes
# PURPOSE: Consolidated container inventory with basic or geospatial analysis
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Inventory Container Contents Job.

Consolidated container inventory with configurable analysis depth.

Replaces (07 DEC 2025):
    - jobs/container_list.py → ARCHIVED
    - jobs/container_list_diamond.py → ARCHIVED
    - jobs/inventory_container_geospatial.py → MERGED

Three-stage workflow:
    Stage 1: List blobs with full metadata (single task)
    Stage 2: Per-blob analysis (fan-out) - basic or geospatial mode
    Stage 3: Aggregate results (fan-in) - summary or collection grouping

Exports:
    InventoryContainerContentsJob: Consolidated container inventory job
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class InventoryContainerContentsJob(JobBaseMixin, JobBase):
    """
    Container inventory with configurable analysis depth.

    Two analysis modes:
        - basic: Extension counts, size totals, file statistics
        - geospatial: Pattern detection, sidecar association, collection grouping

    Stage 1 returns full blob metadata, enabling Stage 2 handlers to work
    without additional API calls.
    """

    job_type = "inventory_container_contents"
    description = "Container inventory with configurable analysis (basic or geospatial)"

    stages = [
        {
            "number": 1,
            "name": "list_blobs",
            "task_type": "inventory_list_blobs",
            "description": "Enumerate blobs with full metadata",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "analyze_blobs",
            "task_type": "inventory_analyze_blob",  # Dynamic: can be inventory_classify_geospatial
            "description": "Per-blob analysis (basic or geospatial)",
            "parallelism": "fan_out"
        },
        {
            "number": 3,
            "name": "aggregate",
            "task_type": "inventory_aggregate_analysis",  # Dynamic: can be inventory_aggregate_geospatial
            "description": "Aggregate results into summary",
            "parallelism": "fan_in"
        }
    ]

    parameters_schema = {
        # Required
        'container_name': {'type': 'str', 'required': True},

        # Filtering
        'prefix': {'type': 'str', 'default': None},
        'suffix': {'type': 'str', 'default': None},  # e.g., ".tif"
        'limit': {'type': 'int', 'default': 500, 'min': 1, 'max': 50000},

        # Analysis mode
        'analysis_mode': {
            'type': 'str',
            'default': 'basic',
            'allowed': ['basic', 'geospatial']
        },

        # Geospatial-specific (only used when analysis_mode="geospatial")
        'grouping_mode': {
            'type': 'str',
            'default': 'auto',
            'allowed': ['auto', 'folder', 'prefix', 'manifest', 'all_singles', 'all_collection']
        },
        'min_collection_size': {'type': 'int', 'default': 2, 'min': 2, 'max': 1000},
        'include_unrecognized': {'type': 'bool', 'default': True},
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Generate task parameters for each stage with dynamic handler selection."""
        from core.task_id import generate_deterministic_task_id

        analysis_mode = job_params.get('analysis_mode', 'basic')

        if stage == 1:
            # Stage 1: List blobs with full metadata
            return [{
                'task_id': generate_deterministic_task_id(job_id, 1, "list"),
                'task_type': 'inventory_list_blobs',
                'parameters': {
                    'container_name': job_params['container_name'],
                    'prefix': job_params.get('prefix'),
                    'suffix': job_params.get('suffix'),
                    'limit': job_params.get('limit', 500)
                }
            }]

        elif stage == 2:
            # Stage 2: Per-blob analysis (fan-out)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                error = stage_1_result.get('error', 'Unknown error')
                raise ValueError(f"Stage 1 failed: {error}")

            result_data = stage_1_result.get('result', {})
            blobs = result_data.get('blobs', [])

            if not blobs:
                raise ValueError("Stage 1 returned no blobs to analyze")

            # Select handler based on analysis mode
            if analysis_mode == 'geospatial':
                task_type = 'inventory_classify_geospatial'
            else:
                task_type = 'inventory_analyze_blob'

            tasks = []
            for i, blob in enumerate(blobs):
                task_id = generate_deterministic_task_id(job_id, 2, f"analyze-{i}")

                # Pass full blob metadata to handler
                tasks.append({
                    'task_id': task_id,
                    'task_type': task_type,
                    'parameters': {
                        'blob_name': blob.get('name'),
                        'size_bytes': blob.get('size', 0),
                        'last_modified': blob.get('last_modified'),
                        'content_type': blob.get('content_type'),
                        'container_name': job_params['container_name'],
                        'job_parameters': job_params  # For geospatial grouping context
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Aggregate results (fan-in)
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Select aggregation handler based on analysis mode
            if analysis_mode == 'geospatial':
                task_type = 'inventory_aggregate_geospatial'
            else:
                task_type = 'inventory_aggregate_analysis'

            return [{
                'task_id': generate_deterministic_task_id(job_id, 3, "aggregate"),
                'task_type': task_type,
                'parameters': {
                    'previous_results': previous_results,
                    'job_parameters': job_params
                }
            }]

        else:
            raise ValueError(f"InventoryContainerContentsJob has 3 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """Create final job summary from aggregated results."""
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters
        analysis_mode = params.get('analysis_mode', 'basic')

        # Find Stage 3 aggregation result
        if analysis_mode == 'geospatial':
            agg_task_type = "inventory_aggregate_geospatial"
        else:
            agg_task_type = "inventory_aggregate_analysis"

        stage_3_tasks = [t for t in task_results if t.task_type == agg_task_type]

        if not stage_3_tasks:
            return {
                "job_type": "inventory_container_contents",
                "status": "failed",
                "error": f"No aggregation task found (expected {agg_task_type})"
            }

        aggregation_task = stage_3_tasks[0]
        if aggregation_task.status != TaskStatus.COMPLETED:
            return {
                "job_type": "inventory_container_contents",
                "status": "failed",
                "error": f"Aggregation task status: {aggregation_task.status}"
            }

        # Extract aggregation result
        agg_result = aggregation_task.result_data
        if not agg_result or not agg_result.get("success"):
            return {
                "job_type": "inventory_container_contents",
                "status": "failed",
                "error": agg_result.get("error", "Aggregation failed") if agg_result else "No result"
            }

        # Get the aggregated data
        inventory = agg_result.get("result", {})

        # Build base result
        result = {
            "job_type": "inventory_container_contents",
            "container_name": params.get("container_name"),
            "prefix_scanned": params.get("prefix"),
            "suffix_filter": params.get("suffix"),
            "analysis_mode": analysis_mode,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }

        # Add mode-specific results
        if analysis_mode == 'geospatial':
            # Geospatial mode: collection grouping
            result.update({
                "scan_timestamp": inventory.get("scan_timestamp"),
                "grouping_mode": params.get("grouping_mode", "auto"),
                "summary": inventory.get("summary", {}),
                "raster_collections": inventory.get("raster_collections", []),
                "raster_singles": inventory.get("raster_singles", []),
                "unrecognized": inventory.get("unrecognized", []),
                "patterns_detected": inventory.get("patterns_detected", {}),
                "processing_recommendations": inventory.get("processing_recommendations", {})
            })
        else:
            # Basic mode: simple summary
            result.update({
                "summary": inventory.get("summary", {})
            })

        return result
