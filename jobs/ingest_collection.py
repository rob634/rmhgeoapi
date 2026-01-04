# ============================================================================
# INGEST COLLECTION JOB
# ============================================================================
# STATUS: Jobs - 5-stage COG collection ingestion
# PURPOSE: Copy pre-processed COGs from bronze to silver and register in pgSTAC
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Ingest Collection Job - 5-Stage Workflow.

Ingests pre-processed COG collections with existing STAC metadata from bronze
storage to silver storage, registering in pgSTAC for discovery and visualization.

Use Case:
    Data already converted to COG with STAC JSON sidecars (like MapSPAM).
    No processing needed - just copy and register.

5-Stage Workflow:
    Stage 1: Inventory - Parse collection.json, count items, create batches
    Stage 2: Copy - Copy COG files from bronze to silver (parallel batches)
    Stage 3: Register Collection - Upsert collection to pgSTAC
    Stage 4: Register Items - Upsert items to pgSTAC (parallel batches)
    Stage 5: Finalize - Create source_catalog entry, update summaries

Features:
    - Reads existing collection.json and item JSONs
    - Parallel blob copy with batching
    - Updates asset hrefs to silver container
    - Creates h3.source_catalog entry for H3 pipeline integration
    - Preserves all dimension properties from source STAC

Usage:
    POST /api/jobs/submit/ingest_collection
    {
        "source_container": "bronzemapspam",
        "target_container": "silvermapspam",
        "batch_size": 100
    }

Exports:
    IngestCollectionJob: 5-stage ingest job
"""

from typing import List, Dict, Any, Optional

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class IngestCollectionJob(JobBaseMixin, JobBase):
    """
    Ingest Collection Job - 5-stage workflow for pre-processed COGs.

    Stage 1: Inventory (parse collection.json, create batches)
    Stage 2: Copy blobs (parallel)
    Stage 3: Register collection
    Stage 4: Register items (parallel)
    Stage 5: Finalize (source_catalog entry)

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    job_type: str = "ingest_collection"
    description: str = "Ingest pre-processed COG collection from bronze to silver"

    # 5-stage workflow
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "ingest_inventory",
            "parallelism": "single",
            "description": "Parse collection.json, count items, create batch plan"
        },
        {
            "number": 2,
            "name": "copy",
            "task_type": "ingest_copy_batch",
            "parallelism": "fan_out",
            "description": "Copy COG files from bronze to silver"
        },
        {
            "number": 3,
            "name": "register_collection",
            "task_type": "ingest_register_collection",
            "parallelism": "single",
            "description": "Register collection in pgSTAC"
        },
        {
            "number": 4,
            "name": "register_items",
            "task_type": "ingest_register_items",
            "parallelism": "fan_out",
            "description": "Register items in pgSTAC"
        },
        {
            "number": 5,
            "name": "finalize",
            "task_type": "ingest_finalize",
            "parallelism": "single",
            "description": "Create source_catalog entry, finalize"
        }
    ]

    # Declarative parameter validation
    parameters_schema: Dict[str, Any] = {
        'source_container': {
            'type': 'str',
            'required': True,
            'description': 'Bronze container with COGs and STAC JSON'
        },
        'target_container': {
            'type': 'str',
            'required': True,
            'description': 'Silver container for ingested data'
        },
        'source_account': {
            'type': 'str',
            'default': None,
            'description': 'Source storage account (defaults to bronze account from config)'
        },
        'target_account': {
            'type': 'str',
            'default': None,
            'description': 'Target storage account (defaults to silver account from config)'
        },
        'collection_json_path': {
            'type': 'str',
            'default': 'collection.json',
            'description': 'Path to collection.json in source container'
        },
        'batch_size': {
            'type': 'int',
            'default': 100,
            'min': 10,
            'max': 500,
            'description': 'Items per batch for copy and register stages'
        },
        'overwrite': {
            'type': 'bool',
            'default': False,
            'description': 'Overwrite existing blobs in target container'
        },
        'skip_existing': {
            'type': 'bool',
            'default': True,
            'description': 'Skip copying blobs that already exist in target'
        },
        'h3_theme': {
            'type': 'str',
            'default': None,
            'description': 'H3 theme for source_catalog (inferred from collection if not set)'
        },
        'create_target_container': {
            'type': 'bool',
            'default': True,
            'description': 'Create target container if it does not exist'
        }
    }

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Task Creation
    # ========================================================================

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for each stage.

        Stage 1: Single inventory task
        Stage 2: Fan-out copy tasks (one per batch)
        Stage 3: Single register collection task
        Stage 4: Fan-out register items tasks (one per batch)
        Stage 5: Single finalize task
        """
        source_container = job_params.get('source_container')
        target_container = job_params.get('target_container')
        source_account = job_params.get('source_account')
        target_account = job_params.get('target_account')
        collection_json_path = job_params.get('collection_json_path', 'collection.json')
        batch_size = job_params.get('batch_size', 100)
        overwrite = job_params.get('overwrite', False)
        skip_existing = job_params.get('skip_existing', True)
        h3_theme = job_params.get('h3_theme')
        create_target_container = job_params.get('create_target_container', True)

        if stage == 1:
            # STAGE 1: Inventory
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-inventory",
                    "task_type": "ingest_inventory",
                    "parameters": {
                        "source_container": source_container,
                        "source_account": source_account,
                        "collection_json_path": collection_json_path,
                        "batch_size": batch_size,
                        "source_job_id": job_id
                    }
                }
            ]

        elif stage == 2:
            # STAGE 2: Copy blobs (fan-out)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            inventory_result = previous_results[0].get('result', {})
            batches = inventory_result.get('batches', [])
            collection_id = inventory_result.get('collection_id')

            if not batches:
                raise ValueError("No batches from inventory stage")

            tasks = []
            for i, batch in enumerate(batches):
                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-copy-{i:03d}",
                    "task_type": "ingest_copy_batch",
                    "parameters": {
                        "source_container": source_container,
                        "target_container": target_container,
                        "source_account": source_account,
                        "target_account": target_account,
                        "batch_index": i,
                        "items": batch,
                        "overwrite": overwrite,
                        "skip_existing": skip_existing,
                        "create_target_container": create_target_container,
                        "source_job_id": job_id
                    }
                })

            return tasks

        elif stage == 3:
            # STAGE 3: Register collection
            if not previous_results or len(previous_results) < 2:
                raise ValueError("Stage 3 requires Stage 1 and 2 results")

            # Get inventory result (first stage)
            inventory_result = None
            for pr in previous_results:
                if pr.get('result', {}).get('collection_id'):
                    inventory_result = pr.get('result', {})
                    break

            if not inventory_result:
                # Try to get from the stored stage 1 results
                inventory_result = previous_results[0].get('result', {}) if previous_results else {}

            collection_id = inventory_result.get('collection_id')
            collection_data = inventory_result.get('collection_data', {})

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-register-coll",
                    "task_type": "ingest_register_collection",
                    "parameters": {
                        "source_container": source_container,
                        "target_container": target_container,
                        "target_account": target_account,
                        "collection_id": collection_id,
                        "collection_json_path": collection_json_path,
                        "source_account": source_account,
                        "source_job_id": job_id
                    }
                }
            ]

        elif stage == 4:
            # STAGE 4: Register items (fan-out)
            # Reuse batches from inventory
            inventory_result = None
            for pr in previous_results:
                if pr.get('result', {}).get('batches'):
                    inventory_result = pr.get('result', {})
                    break

            if not inventory_result:
                raise ValueError("Stage 4 requires inventory batches")

            batches = inventory_result.get('batches', [])
            collection_id = inventory_result.get('collection_id')

            tasks = []
            for i, batch in enumerate(batches):
                tasks.append({
                    "task_id": f"{job_id[:8]}-s4-reg-{i:03d}",
                    "task_type": "ingest_register_items",
                    "parameters": {
                        "source_container": source_container,
                        "target_container": target_container,
                        "source_account": source_account,
                        "target_account": target_account,
                        "collection_id": collection_id,
                        "batch_index": i,
                        "items": batch,
                        "source_job_id": job_id
                    }
                })

            return tasks

        elif stage == 5:
            # STAGE 5: Finalize
            # Gather stats from previous stages
            inventory_result = None
            copy_stats = {"files_copied": 0, "bytes_copied": 0}
            register_stats = {"items_registered": 0}

            for pr in previous_results:
                result = pr.get('result', {})
                if result.get('collection_id') and result.get('batches'):
                    inventory_result = result
                elif result.get('files_copied'):
                    copy_stats["files_copied"] += result.get('files_copied', 0)
                    copy_stats["bytes_copied"] += result.get('bytes_copied', 0)
                elif result.get('items_registered'):
                    register_stats["items_registered"] += result.get('items_registered', 0)

            collection_id = inventory_result.get('collection_id') if inventory_result else None
            total_items = inventory_result.get('total_items', 0) if inventory_result else 0

            return [
                {
                    "task_id": f"{job_id[:8]}-s5-finalize",
                    "task_type": "ingest_finalize",
                    "parameters": {
                        "source_container": source_container,
                        "target_container": target_container,
                        "target_account": target_account,
                        "collection_id": collection_id,
                        "h3_theme": h3_theme,
                        "total_items": total_items,
                        "files_copied": copy_stats["files_copied"],
                        "bytes_copied": copy_stats["bytes_copied"],
                        "items_registered": register_stats["items_registered"],
                        "source_job_id": job_id
                    }
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for ingest_collection job (valid: 1-5)")

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary.
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "IngestCollectionJob.finalize_job")

        if not context:
            logger.warning("finalize_job called without context")
            return {
                "job_type": "ingest_collection",
                "status": "completed"
            }

        params = context.parameters
        source_container = params.get('source_container', 'unknown')
        target_container = params.get('target_container', 'unknown')

        # Extract results
        task_results = context.task_results
        collection_id = None
        total_items = 0
        files_copied = 0
        items_registered = 0

        for tr in task_results:
            if tr.result_data:
                result = tr.result_data.get('result', {})
                if result.get('collection_id'):
                    collection_id = result.get('collection_id')
                    total_items = result.get('total_items', total_items)
                files_copied += result.get('files_copied', 0)
                items_registered += result.get('items_registered', 0)

        logger.info(f"Ingest complete: {collection_id} ({files_copied} files, {items_registered} items)")

        return {
            "job_type": "ingest_collection",
            "job_id": context.job_id,
            "status": "completed",
            "collection_id": collection_id,
            "source_container": source_container,
            "target_container": target_container,
            "results": {
                "total_items": total_items,
                "files_copied": files_copied,
                "items_registered": items_registered
            }
        }
