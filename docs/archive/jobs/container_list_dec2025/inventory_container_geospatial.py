"""
Inventory Container Geospatial Job.

Discovery-only geospatial inventory with pattern detection.

Three-stage workflow:
    1. List blobs: Enumerate all blobs in container
    2. Classify files: Per-file geospatial classification (fan-out)
    3. Group inventory: Aggregate into collections and singles (fan-in)

Exports:
    InventoryContainerGeospatialJob: Main job class for container inventory
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class InventoryContainerGeospatialJob(JobBaseMixin, JobBase):
    """
    Geospatial container inventory with pattern detection and collection grouping.

    Discovery-only job that:
    - Scans container for all blobs
    - Classifies each file by geospatial type (raster, vector, sidecar, manifest)
    - Detects vendor patterns (Maxar, Vivid, tile grids)
    - Groups rasters into collections or singles based on folder/prefix/manifest
    - Returns structured report ready for future processing orchestration

    Output designed for fire-and-forget orchestration:
    - raster_collections[]: Ready for process_raster_collection_v2
    - raster_singles[]: Ready for process_raster_v2
    """

    job_type = "inventory_container_geospatial"
    description = "Inventory container, classify geospatial files, detect patterns, group collections"

    stages = [
        {
            "number": 1,
            "name": "list_blobs",
            "task_type": "list_container_blobs",
            "description": "Enumerate all blobs in container with metadata",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "classify_files",
            "task_type": "classify_geospatial_file",
            "description": "Classify each file by geospatial type and detect patterns",
            "parallelism": "fan_out"
        },
        {
            "number": 3,
            "name": "group_inventory",
            "task_type": "aggregate_geospatial_inventory",
            "description": "Group rasters into collections and generate inventory report",
            "parallelism": "fan_in"
        }
    ]

    parameters_schema = {
        # Required
        'container_name': {'type': 'str', 'required': True},

        # Scan scope
        'prefix': {'type': 'str', 'default': None},  # Scan subset of container
        'file_limit': {'type': 'int', 'default': None, 'max': 50000},

        # Grouping behavior
        'grouping_mode': {
            'type': 'str',
            'default': 'auto',
            'allowed': ['auto', 'folder', 'prefix', 'manifest', 'all_singles', 'all_collection']
        },
        'min_collection_size': {'type': 'int', 'default': 2, 'min': 2, 'max': 1000},

        # Output options
        'include_unrecognized': {'type': 'bool', 'default': True},

        # Future: custom pattern support
        # 'custom_patterns': {'type': 'list', 'default': []},
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Generate task parameters for each stage."""
        from core.task_id import generate_deterministic_task_id

        if stage == 1:
            # Stage 1: List all blobs in container
            # Reuses existing list_container_blobs handler from container_list.py
            return [{
                'task_id': generate_deterministic_task_id(job_id, 1, "list"),
                'task_type': 'list_container_blobs',
                'parameters': {
                    'container_name': job_params['container_name'],
                    'file_limit': job_params.get('file_limit'),
                    'filter': {
                        'prefix': job_params.get('prefix')
                    } if job_params.get('prefix') else {}
                }
            }]

        elif stage == 2:
            # Stage 2: Classify each blob (fan-out)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                error = stage_1_result.get('error', 'Unknown error')
                raise ValueError(f"Stage 1 failed: {error}")

            result_data = stage_1_result.get('result', {})
            blob_names = result_data.get('blob_names', [])

            if not blob_names:
                raise ValueError("Stage 1 returned no blobs to classify")

            # Get blob details from Stage 1 if available
            # list_container_blobs returns blob_names, but we need more details
            # We'll need to fetch blob properties in the classify handler
            # For now, create tasks with just blob names

            tasks = []
            for i, blob_name in enumerate(blob_names):
                task_id = generate_deterministic_task_id(job_id, 2, f"classify-{i}")
                tasks.append({
                    'task_id': task_id,
                    'task_type': 'classify_geospatial_file',
                    'parameters': {
                        'blob_name': blob_name,
                        'container_name': job_params['container_name'],
                        'job_parameters': job_params  # Pass for context in aggregation
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Aggregate classifications (fan-in)
            # CoreMachine auto-creates this task for fan_in parallelism
            # Handler receives previous_results automatically
            return [{
                'task_id': generate_deterministic_task_id(job_id, 3, "aggregate"),
                'task_type': 'aggregate_geospatial_inventory',
                'parameters': {
                    'previous_results': previous_results,
                    'job_parameters': job_params
                }
            }]

        else:
            raise ValueError(f"InventoryContainerGeospatialJob has 3 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """Create final job summary from aggregated inventory."""
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Find Stage 3 aggregation result
        stage_3_tasks = [t for t in task_results if t.task_type == "aggregate_geospatial_inventory"]

        if not stage_3_tasks:
            return {
                "job_type": "inventory_container_geospatial",
                "status": "failed",
                "error": "No aggregation task found"
            }

        aggregation_task = stage_3_tasks[0]
        if aggregation_task.status != TaskStatus.COMPLETED:
            return {
                "job_type": "inventory_container_geospatial",
                "status": "failed",
                "error": f"Aggregation task status: {aggregation_task.status}"
            }

        # Extract aggregation result
        agg_result = aggregation_task.result_data
        if not agg_result or not agg_result.get("success"):
            return {
                "job_type": "inventory_container_geospatial",
                "status": "failed",
                "error": agg_result.get("error", "Aggregation failed") if agg_result else "No result"
            }

        inventory = agg_result.get("result", {})

        # Build final job output
        return {
            "job_type": "inventory_container_geospatial",
            "container_name": params.get("container_name"),
            "prefix_scanned": params.get("prefix"),
            "scan_timestamp": inventory.get("scan_timestamp"),
            "grouping_mode": params.get("grouping_mode", "auto"),

            # Summary statistics
            "summary": inventory.get("summary", {}),

            # Grouped results
            "raster_collections": inventory.get("raster_collections", []),
            "raster_singles": inventory.get("raster_singles", []),
            "unrecognized": inventory.get("unrecognized", []),

            # Pattern analysis
            "patterns_detected": inventory.get("patterns_detected", {}),

            # Processing recommendations
            "processing_recommendations": inventory.get("processing_recommendations", {}),

            # Job execution stats
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
