# ============================================================================
# CLAUDE CONTEXT - INGEST ZARR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job definition - Native Zarr store ingest pipeline
# PURPOSE: 3-stage pipeline: validate -> copy -> register for native Zarr stores
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: IngestZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
IngestZarrJob - Native Zarr store ingest pipeline.

Ingests pre-existing Zarr stores (as opposed to VirtualZarr which builds
virtual references from NetCDF files). The source Zarr is validated,
copied blob-by-blob to silver-zarr, then registered in STAC.

Three-Stage Workflow:
    Stage 1 (validate): Validate Zarr store structure and enumerate blobs
    Stage 2 (copy): Fan-out -- copy blobs from source to silver-zarr
    Stage 3 (register): Build STAC item and update release record

Exports:
    IngestZarrJob: Three-stage native Zarr ingest pipeline implementation
"""

import math
from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


# Maximum blobs per copy task for fan-out chunking
COPY_CHUNK_SIZE = 50


def _get_silver_zarr_container() -> str:
    """Get the silver-zarr container name from config."""
    from config import get_config
    return get_config().storage.silver.zarr


class IngestZarrJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Ingest native Zarr store using JobBaseMixin pattern.

    Three-Stage Workflow:
        1. Stage 1 (validate): Validate Zarr structure, enumerate blobs
        2. Stage 2 (copy): Fan-out -- copy blob chunks from source to silver-zarr
        3. Stage 3 (register): Build STAC item, update release record
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "ingest_zarr"
    description = "Ingest native Zarr store: validate, copy to silver, register"

    # Declarative ETL linkage -- unpublish_zarr reverses this job
    reversed_by = "unpublish_zarr"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "ingest_zarr_validate",
            "parallelism": "single",
        },
        {
            "number": 2,
            "name": "copy",
            "task_type": "ingest_zarr_copy",
            "parallelism": "fan_out",
            "depends_on": 1,
        },
        {
            "number": 3,
            "name": "register",
            "task_type": "ingest_zarr_register",
            "parallelism": "single",
            "depends_on": 2,
        },
    ]

    parameters_schema = {
        "source_url": {
            "type": "str",
            "required": True,
        },
        "source_account": {
            "type": "str",
            "required": True,
        },
        "stac_item_id": {
            "type": "str",
            "required": True,
        },
        "collection_id": {
            "type": "str",
            "required": True,
        },
        "dataset_id": {
            "type": "str",
            "required": True,
        },
        "resource_id": {
            "type": "str",
            "required": True,
        },
        "version_id": {
            "type": "str",
            "default": None,
        },
        "title": {
            "type": "str",
            "required": False,
        },
        "description": {
            "type": "str",
            "required": False,
        },
        "tags": {
            "type": "list",
            "required": False,
        },
        "access_level": {
            "type": "str",
            "required": True,
        },
    }

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Parameter Validation
    # ========================================================================
    @classmethod
    def validate_job_parameters(cls, params: dict) -> dict:
        """Validate job parameters with source_url prefix check."""
        validated = super().validate_job_parameters(params)
        source_url = validated.get("source_url", "")
        if not source_url.startswith("abfs://"):
            raise ValueError(
                f"source_url must start with 'abfs://', got: '{source_url}'"
            )
        return validated

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

        Args:
            stage: Stage number (1-3)
            job_params: Validated job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1 (validate): Single task to validate Zarr store and list blobs
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-validate",
                    "task_type": "ingest_zarr_validate",
                    "parameters": {
                        "source_url": job_params["source_url"],
                        "source_account": job_params["source_account"],
                        "dataset_id": job_params["dataset_id"],
                        "resource_id": job_params["resource_id"],
                    },
                }
            ]

        elif stage == 2:
            # Stage 2 (copy): Fan-out -- chunk blob list for parallel copy
            if not previous_results:
                raise ValueError(
                    "Stage 2 (copy) requires previous_results from validate stage"
                )

            # CoreMachine._get_completed_stage_results() unwraps the handler
            # envelope and returns the "result" payload directly.
            validate_result = previous_results[0] if previous_results else {}
            blob_list = validate_result.get("blob_list", [])
            if not blob_list:
                raise ValueError(
                    "Stage 2 (copy) requires non-empty blob_list from validate stage"
                )

            target_container = _get_silver_zarr_container()
            target_prefix = f"{job_params['dataset_id']}/{job_params['resource_id']}"

            # Chunk blob_list into groups for parallel copy tasks
            num_chunks = math.ceil(len(blob_list) / COPY_CHUNK_SIZE)
            tasks = []
            for i in range(num_chunks):
                chunk_start = i * COPY_CHUNK_SIZE
                chunk_end = chunk_start + COPY_CHUNK_SIZE
                chunk = blob_list[chunk_start:chunk_end]
                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-copy-{i}",
                    "task_type": "ingest_zarr_copy",
                    "parameters": {
                        "source_url": job_params["source_url"],
                        "source_account": job_params["source_account"],
                        "blob_list": chunk,
                        "target_container": target_container,
                        "target_prefix": target_prefix,
                    },
                })

            return tasks

        elif stage == 3:
            # Stage 3 (register): Single task with all metadata params
            if not previous_results:
                raise ValueError(
                    "Stage 3 (register) requires previous_results from copy stage"
                )

            target_container = _get_silver_zarr_container()
            target_prefix = f"{job_params['dataset_id']}/{job_params['resource_id']}"
            zarr_store_url = f"abfs://{target_container}/{target_prefix}"

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-register",
                    "task_type": "ingest_zarr_register",
                    "parameters": {
                        "release_id": job_params.get("release_id", job_id),
                        "zarr_store_url": zarr_store_url,
                        "stac_item_id": job_params["stac_item_id"],
                        "collection_id": job_params["collection_id"],
                        "dataset_id": job_params["dataset_id"],
                        "resource_id": job_params["resource_id"],
                        "version_id": job_params.get("version_id"),
                        "title": job_params.get("title"),
                        "description": job_params.get("description"),
                        "tags": job_params.get("tags", []),
                        "access_level": job_params["access_level"],
                    },
                }
            ]

        else:
            return []

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary.

        Args:
            context: JobExecutionContext (optional)

        Returns:
            Job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "IngestZarrJob.finalize_job"
        )

        if context:
            logger.info(
                f"IngestZarr job {context.job_id} completed "
                f"with {len(context.task_results)} tasks"
            )
        else:
            logger.info("IngestZarr job completed (no context provided)")

        return {
            "job_type": "ingest_zarr",
            "status": "completed",
        }
