# ============================================================================
# CLAUDE CONTEXT - VIRTUALZARR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - VirtualiZarr NetCDF reference pipeline
# PURPOSE: Generate virtual Zarr references from NetCDF files via kerchunk
# LAST_REVIEWED: 27 FEB 2026
# EXPORTS: VirtualZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
VirtualZarr Job - NetCDF Virtual Reference Pipeline.

Four-stage workflow that scans NetCDF files, validates HDF5 structure,
combines virtual Zarr references, and registers STAC metadata.

Four-Stage Workflow:
    Stage 1 (scan): List NetCDF files from source container, write manifest
    Stage 2 (validate): Fan-out - validate each file's HDF5 structure
    Stage 3 (combine): Combine virtual datasets into single Zarr reference
    Stage 4 (register): Build STAC item and update release record

Exports:
    VirtualZarrJob: Four-stage VirtualiZarr pipeline implementation
"""

import json
from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


def _get_storage_account():
    """Get the silver storage account name from config."""
    from config import get_config
    return get_config().storage.silver.account_name


def _read_manifest(manifest_url: str) -> list:
    """
    Read file list from blob manifest JSON.

    Args:
        manifest_url: abfs:// URL to the manifest.json blob

    Returns:
        List of NetCDF file URLs from the manifest
    """
    import fsspec
    fs = fsspec.filesystem("abfs", account_name=_get_storage_account())
    blob_path = manifest_url.replace("abfs://", "")
    with fs.open(blob_path, 'r') as f:
        manifest = json.load(f)
    return manifest.get('nc_files', [])


class VirtualZarrJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    VirtualZarr job using JobBaseMixin pattern.

    Four-Stage Workflow:
        1. Stage 1 (scan): List NetCDF files, write manifest to blob
        2. Stage 2 (validate): Fan-out per file, validate HDF5 headers
        3. Stage 3 (combine): Combine virtual datasets, export reference JSON
        4. Stage 4 (register): Build STAC item, update release record
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "virtualzarr"
    description = "Generate virtual Zarr references from NetCDF files"

    stages = [
        {
            "number": 1,
            "name": "scan",
            "task_type": "virtualzarr_scan",
            "parallelism": "single",
        },
        {
            "number": 2,
            "name": "validate",
            "task_type": "virtualzarr_validate",
            "parallelism": "fan_out",
            "depends_on": 1,
        },
        {
            "number": 3,
            "name": "combine",
            "task_type": "virtualzarr_combine",
            "parallelism": "single",
            "depends_on": 2,
        },
        {
            "number": 4,
            "name": "register",
            "task_type": "virtualzarr_register",
            "parallelism": "single",
            "depends_on": 3,
        },
    ]

    parameters_schema = {
        "source_url": {
            "type": "str",
            "required": True,
        },
        "file_pattern": {
            "type": "str",
            "default": "*.nc",
        },
        "concat_dim": {
            "type": "str",
            "default": "time",
        },
        "fail_on_chunking_warnings": {
            "type": "bool",
            "default": False,
        },
        "max_files": {
            "type": "int",
            "min": 1,
            "max": 10000,
            "default": 500,
        },
        "ref_output_prefix": {
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

        Args:
            stage: Stage number (1-4)
            job_params: Validated job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1 (scan): Single task to list NetCDF files
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-scan",
                    "task_type": "virtualzarr_scan",
                    "parameters": {
                        "source_url": job_params["source_url"],
                        "file_pattern": job_params.get("file_pattern", "*.nc"),
                        "max_files": job_params.get("max_files", 500),
                        "ref_output_prefix": job_params["ref_output_prefix"],
                    },
                }
            ]

        elif stage == 2:
            # Stage 2 (validate): Fan-out - one task per file from manifest
            if not previous_results:
                raise ValueError(
                    "Stage 2 (validate) requires previous_results from scan stage"
                )

            # Extract manifest_url from stage 1 result
            scan_result = previous_results[0] if previous_results else {}
            result_data = scan_result.get("result", {})
            manifest_url = result_data.get("manifest_url")
            if not manifest_url:
                raise ValueError(
                    "Stage 2 requires manifest_url from scan stage result"
                )

            # Read manifest to get file list
            nc_files = _read_manifest(manifest_url)
            if not nc_files:
                raise ValueError(
                    f"Manifest at {manifest_url} contains no files"
                )

            fail_on_warnings = job_params.get("fail_on_chunking_warnings", False)

            return [
                {
                    "task_id": f"{job_id[:8]}-s2-val-{i}",
                    "task_type": "virtualzarr_validate",
                    "parameters": {
                        "nc_url": nc_url,
                        "fail_on_warnings": fail_on_warnings,
                    },
                }
                for i, nc_url in enumerate(nc_files)
            ]

        elif stage == 3:
            # Stage 3 (combine): Single task to merge virtual datasets
            if not previous_results:
                raise ValueError(
                    "Stage 3 (combine) requires previous_results from validate stage"
                )

            # Get manifest_url from stage 1 (available via job context)
            # Stage 3 needs: manifest for file list, concat_dim, output path
            scan_result = None
            # previous_results at stage 3 contains stage 2 results
            # We need the manifest_url which was produced in stage 1.
            # CoreMachine passes all previous results; the scan result
            # is typically accessed via job-level context or re-derived.
            # The ref_output_prefix lets us reconstruct manifest path.
            ref_prefix = job_params["ref_output_prefix"]
            manifest_url = f"abfs://rmhazuregeosilver/{ref_prefix}/manifest.json"
            combined_ref_url = f"abfs://rmhazuregeosilver/{ref_prefix}/combined_ref.json"

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-combine",
                    "task_type": "virtualzarr_combine",
                    "parameters": {
                        "manifest_url": manifest_url,
                        "combined_ref_url": combined_ref_url,
                        "concat_dim": job_params.get("concat_dim", "time"),
                        "dataset_id": job_params["dataset_id"],
                    },
                }
            ]

        elif stage == 4:
            # Stage 4 (register): Single task to build STAC + update release
            if not previous_results:
                raise ValueError(
                    "Stage 4 (register) requires previous_results from combine stage"
                )

            combine_result = previous_results[0] if previous_results else {}
            result_data = combine_result.get("result", {})

            ref_prefix = job_params["ref_output_prefix"]
            combined_ref_url = result_data.get(
                "combined_ref_url",
                f"abfs://rmhazuregeosilver/{ref_prefix}/combined_ref.json"
            )

            return [
                {
                    "task_id": f"{job_id[:8]}-s4-register",
                    "task_type": "virtualzarr_register",
                    "parameters": {
                        "release_id": job_params.get("release_id", job_id),
                        "stac_item_id": job_params["stac_item_id"],
                        "collection_id": job_params["collection_id"],
                        "dataset_id": job_params["dataset_id"],
                        "resource_id": job_params["resource_id"],
                        "combined_ref_url": combined_ref_url,
                        "spatial_extent": result_data.get("spatial_extent"),
                        "time_range": result_data.get("time_range"),
                        "variables": result_data.get("variables", []),
                        "dimensions": result_data.get("dimensions", {}),
                        "source_files": result_data.get("source_files", 0),
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
            "VirtualZarrJob.finalize_job"
        )

        if context:
            logger.info(
                f"VirtualZarr job {context.job_id} completed "
                f"with {len(context.task_results)} tasks"
            )
        else:
            logger.info("VirtualZarr job completed (no context provided)")

        return {
            "job_type": "virtualzarr",
            "status": "completed",
        }
