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

Five-stage workflow that scans NetCDF files, copies them to silver-netcdf,
validates HDF5 structure, combines virtual Zarr references, and registers
STAC metadata.

Five-Stage Workflow:
    Stage 1 (scan): List NetCDF files from source, build source→silver manifest
    Stage 2 (copy): Fan-out — copy each file from bronze → silver-netcdf
    Stage 3 (validate): Fan-out — validate each file's HDF5 structure
    Stage 4 (combine): Combine virtual datasets into single Zarr reference
    Stage 5 (register): Build STAC item and update release record

Exports:
    VirtualZarrJob: Five-stage VirtualiZarr pipeline implementation
"""

import json
from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


def _get_silver_netcdf_container() -> str:
    """Get the silver-netcdf container name from config."""
    from config import get_config
    return get_config().storage.silver.netcdf


def _read_manifest(manifest_url: str) -> list:
    """
    Read nc_files list from blob manifest JSON via BlobRepository.

    Args:
        manifest_url: abfs:// URL to the manifest.json blob

    Returns:
        List of NetCDF file URLs (silver paths) from the manifest
    """
    from infrastructure import BlobRepository

    blob_path = manifest_url.replace("abfs://", "")
    parts = blob_path.split("/", 1)
    container = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    silver_repo = BlobRepository.for_zone("silver")
    data = silver_repo.read_blob(container, blob_name)
    manifest = json.loads(data)
    return manifest.get('nc_files', [])


def _read_manifest_full(manifest_url: str) -> dict:
    """
    Read the full manifest dict from blob JSON via BlobRepository.

    Used by Stage 2 (copy) to access the files[] array with source→silver mapping.

    Args:
        manifest_url: abfs:// URL to the manifest.json blob

    Returns:
        Full manifest dict including files[], nc_files[], silver_container, etc.
    """
    from infrastructure import BlobRepository

    blob_path = manifest_url.replace("abfs://", "")
    parts = blob_path.split("/", 1)
    container = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    silver_repo = BlobRepository.for_zone("silver")
    data = silver_repo.read_blob(container, blob_name)
    return json.loads(data)


class VirtualZarrJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    VirtualZarr job using JobBaseMixin pattern.

    Five-Stage Workflow:
        1. Stage 1 (scan): List NetCDF files, build source→silver manifest
        2. Stage 2 (copy): Fan-out — copy each file bronze → silver-netcdf
        3. Stage 3 (validate): Fan-out per file, validate HDF5 headers
        4. Stage 4 (combine): Combine virtual datasets, export reference JSON
        5. Stage 5 (register): Build STAC item, update release record
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
            "name": "copy",
            "task_type": "virtualzarr_copy",
            "parallelism": "fan_out",
            "depends_on": 1,
        },
        {
            "number": 3,
            "name": "validate",
            "task_type": "virtualzarr_validate",
            "parallelism": "fan_out",
            "depends_on": 2,
        },
        {
            "number": 4,
            "name": "combine",
            "task_type": "virtualzarr_combine",
            "parallelism": "single",
            "depends_on": 3,
        },
        {
            "number": 5,
            "name": "register",
            "task_type": "virtualzarr_register",
            "parallelism": "single",
            "depends_on": 4,
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
            stage: Stage number (1-5)
            job_params: Validated job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1 (scan): Single task to list NetCDF files and build manifest
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
            # Stage 2 (copy): Fan-out — one copy task per file from manifest
            if not previous_results:
                raise ValueError(
                    "Stage 2 (copy) requires previous_results from scan stage"
                )

            # Extract manifest_url from stage 1 result
            scan_result = previous_results[0] if previous_results else {}
            result_data = scan_result.get("result", {})
            manifest_url = result_data.get("manifest_url")
            if not manifest_url:
                raise ValueError(
                    "Stage 2 requires manifest_url from scan stage result"
                )

            # Read full manifest to get files[] array
            manifest = _read_manifest_full(manifest_url)
            files = manifest.get("files", [])
            if not files:
                raise ValueError(
                    f"Manifest at {manifest_url} contains no files"
                )

            silver_container = manifest.get("silver_container", _get_silver_netcdf_container())

            return [
                {
                    "task_id": f"{job_id[:8]}-s2-copy-{i}",
                    "task_type": "virtualzarr_copy",
                    "parameters": {
                        "source_url": f_entry["source_url"],
                        "silver_container": silver_container,
                        "silver_path": f_entry["silver_path"],
                        "size_bytes": f_entry["size_bytes"],
                    },
                }
                for i, f_entry in enumerate(files)
            ]

        elif stage == 3:
            # Stage 3 (validate): Fan-out — one task per file (now in silver)
            if not previous_results:
                raise ValueError(
                    "Stage 3 (validate) requires previous_results from copy stage"
                )

            # Reconstruct manifest path from ref_output_prefix
            silver_container = _get_silver_netcdf_container()
            ref_prefix = job_params["ref_output_prefix"]
            manifest_url = f"abfs://{silver_container}/{ref_prefix}/manifest.json"

            # Read nc_files from manifest — these are silver URLs
            nc_files = _read_manifest(manifest_url)
            if not nc_files:
                raise ValueError(
                    f"Manifest at {manifest_url} contains no files"
                )

            fail_on_warnings = job_params.get("fail_on_chunking_warnings", False)

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-val-{i}",
                    "task_type": "virtualzarr_validate",
                    "parameters": {
                        "nc_url": nc_url,
                        "fail_on_warnings": fail_on_warnings,
                    },
                }
                for i, nc_url in enumerate(nc_files)
            ]

        elif stage == 4:
            # Stage 4 (combine): Single task to merge virtual datasets
            if not previous_results:
                raise ValueError(
                    "Stage 4 (combine) requires previous_results from validate stage"
                )

            silver_container = _get_silver_netcdf_container()
            ref_prefix = job_params["ref_output_prefix"]
            manifest_url = f"abfs://{silver_container}/{ref_prefix}/manifest.json"
            combined_ref_url = f"abfs://{silver_container}/{ref_prefix}/combined_ref.json"

            return [
                {
                    "task_id": f"{job_id[:8]}-s4-combine",
                    "task_type": "virtualzarr_combine",
                    "parameters": {
                        "manifest_url": manifest_url,
                        "combined_ref_url": combined_ref_url,
                        "concat_dim": job_params.get("concat_dim", "time"),
                        "dataset_id": job_params["dataset_id"],
                    },
                }
            ]

        elif stage == 5:
            # Stage 5 (register): Single task to build STAC + update release
            if not previous_results:
                raise ValueError(
                    "Stage 5 (register) requires previous_results from combine stage"
                )

            combine_result = previous_results[0] if previous_results else {}
            result_data = combine_result.get("result", {})

            silver_container = _get_silver_netcdf_container()
            ref_prefix = job_params["ref_output_prefix"]
            combined_ref_url = result_data.get(
                "combined_ref_url",
                f"abfs://{silver_container}/{ref_prefix}/combined_ref.json"
            )

            return [
                {
                    "task_id": f"{job_id[:8]}-s5-register",
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
