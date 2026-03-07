# ============================================================================
# CLAUDE CONTEXT - NETCDF_TO_ZARR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - NetCDF to native Zarr conversion pipeline
# PURPOSE: Convert NetCDF files from bronze to native Zarr stores in silver
# LAST_REVIEWED: 03 MAR 2026
# EXPORTS: NetCDFToZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
NetCDF-to-Zarr Job - Real Zarr Conversion Pipeline.

Five-stage workflow that scans NetCDF files in bronze, copies them to
mounted temp storage for fast local processing, validates structure,
converts to native Zarr (writing to silver-zarr), and registers STAC
metadata pointing at the Zarr store.

Replaces the VirtualiZarr pipeline (virtualzarr job type) which used
kerchunk/virtualizarr references that are no longer compatible with TiTiler.

Five-Stage Workflow:
    Stage 1 (scan): List NetCDF files from bronze, build manifest
    Stage 2 (copy): Fan-out — copy each file from bronze → {etl_mount_path}/{job_id}/
    Stage 3 (validate): Fan-out — validate each file's structure with xarray
    Stage 4 (convert): xr.open_mfdataset() → ds.to_zarr() to silver-zarr
    Stage 5 (register): Build STAC item, update release record

Exports:
    NetCDFToZarrJob: Five-stage NetCDF-to-Zarr pipeline implementation
"""

import json
from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


def _get_silver_zarr_container() -> str:
    """Get the silver-zarr container name from config."""
    from config import get_config
    return get_config().storage.silver.zarr


# Manifest filename — single source of truth shared with handler_netcdf_to_zarr.py
MANIFEST_FILENAME = "manifest.json"


def _manifest_blob_path(output_folder: str) -> str:
    """
    Build the blob path for the pipeline manifest.

    Shared with handler_netcdf_to_zarr.py to prevent path drift between
    the scan handler (which writes the manifest) and later stages
    (which reconstruct the URL to read it).

    Args:
        output_folder: Output folder path (e.g. "zarr/dataset_id/resource_id/ord1")

    Returns:
        Blob path like "zarr/dataset_id/resource_id/ord1/manifest.json"
    """
    return f"{output_folder}/{MANIFEST_FILENAME}"


def _read_manifest(manifest_url: str) -> list:
    """
    Read nc_files list from blob manifest JSON via BlobRepository.

    Args:
        manifest_url: abfs:// URL to the manifest.json blob

    Returns:
        List of local file paths from the manifest
    """
    from infrastructure import BlobRepository

    blob_path = manifest_url.replace("abfs://", "")
    parts = blob_path.split("/", 1)
    container = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    silver_repo = BlobRepository.for_zone("silver")
    data = silver_repo.read_blob(container, blob_name)
    manifest = json.loads(data)
    return manifest.get('local_files', [])


def _read_manifest_full(manifest_url: str) -> dict:
    """
    Read the full manifest dict from blob JSON via BlobRepository.

    Used by Stage 2 (copy) to access the files[] array with source mapping.

    Args:
        manifest_url: abfs:// URL to the manifest.json blob

    Returns:
        Full manifest dict including files[], local_files[], etc.
    """
    from infrastructure import BlobRepository

    blob_path = manifest_url.replace("abfs://", "")
    parts = blob_path.split("/", 1)
    container = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    silver_repo = BlobRepository.for_zone("silver")
    data = silver_repo.read_blob(container, blob_name)
    return json.loads(data)


class NetCDFToZarrJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    NetCDF-to-Zarr job using JobBaseMixin pattern.

    Five-Stage Workflow:
        1. Stage 1 (scan): List NetCDF files in bronze, build manifest
        2. Stage 2 (copy): Fan-out — copy each file bronze → /mounts/etl-temp/{job_id}/
        3. Stage 3 (validate): Fan-out per file, validate with xarray
        4. Stage 4 (convert): open_mfdataset → to_zarr to silver-zarr
        5. Stage 5 (register): Build STAC item, update release record
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "netcdf_to_zarr"
    description = "Convert NetCDF files to native Zarr store"

    # ETL linkage — reuse existing unpublish_zarr pipeline
    reversed_by = "unpublish_zarr"

    stages = [
        {
            "number": 1,
            "name": "scan",
            "task_type": "netcdf_scan",
            "parallelism": "single",
        },
        {
            "number": 2,
            "name": "copy",
            "task_type": "netcdf_copy",
            "parallelism": "fan_out",
            "depends_on": 1,
        },
        {
            "number": 3,
            "name": "validate",
            "task_type": "netcdf_validate",
            "parallelism": "fan_out",
            "depends_on": 2,
        },
        {
            "number": 4,
            "name": "convert",
            "task_type": "netcdf_convert",
            "parallelism": "single",
            "depends_on": 3,
        },
        {
            "number": 5,
            "name": "register",
            "task_type": "netcdf_register",
            "parallelism": "single",
            "depends_on": 4,
        },
    ]

    parameters_schema = {
        "source_url": {
            "type": "str",
            "required": True,
        },
        "source_account": {
            "type": "str",
        },
        "file_pattern": {
            "type": "str",
            "default": "*.nc",
        },
        "concat_dim": {
            "type": "str",
            "default": "time",
        },
        "max_files": {
            "type": "int",
            "min": 1,
            "max": 5000,
            "default": 500,
        },
        "output_folder": {
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
        # Chunking optimization (05 MAR 2026)
        "spatial_chunk_size": {
            "type": "int",
            "min": 64,
            "max": 1024,
            "default": 256,
        },
        "time_chunk_size": {
            "type": "int",
            "min": 1,
            "max": 100,
            "default": 1,
        },
        "compressor": {
            "type": "str",
            "default": "lz4",
        },
        "compression_level": {
            "type": "int",
            "min": 1,
            "max": 9,
            "default": 5,
        },
        "zarr_format": {
            "type": "int",
            "min": 2,
            "max": 3,
            "default": 3,
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
                    "task_type": "netcdf_scan",
                    "parameters": {
                        "source_url": job_params["source_url"],
                        "source_account": job_params.get("source_account"),
                        "file_pattern": job_params.get("file_pattern", "*.nc"),
                        "max_files": job_params.get("max_files", 500),
                        "output_folder": job_params["output_folder"],
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
            # CoreMachine unwraps the handler envelope — we get the payload directly.
            scan_result = previous_results[0] if previous_results else {}
            manifest_url = scan_result.get("manifest_url")
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

            return [
                {
                    "task_id": f"{job_id[:8]}-s2-copy-{i}",
                    "task_type": "netcdf_copy",
                    "parameters": {
                        "source_url": f_entry["source_url"],
                        "source_account": job_params.get("source_account"),
                        "job_id": job_id,
                        "filename": f_entry["relative_path"],
                        "size_bytes": f_entry["size_bytes"],
                    },
                }
                for i, f_entry in enumerate(files)
            ]

        elif stage == 3:
            # Stage 3 (validate): Fan-out — one task per local file
            if not previous_results:
                raise ValueError(
                    "Stage 3 (validate) requires previous_results from copy stage"
                )

            # Reconstruct manifest URL from output_folder.
            # CoreMachine only passes the previous stage's results, so Stage 3
            # cannot read manifest_url from Stage 1 (scan).
            zarr_container = _get_silver_zarr_container()
            output_folder = job_params["output_folder"]
            manifest_url = f"abfs://{zarr_container}/{_manifest_blob_path(output_folder)}"

            # Read local_files (relative paths) from manifest
            relative_files = _read_manifest(manifest_url)
            if not relative_files:
                raise ValueError(
                    f"Manifest at {manifest_url} contains no local_files"
                )

            fail_on_warnings = job_params.get("fail_on_chunking_warnings", False)

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-val-{i}",
                    "task_type": "netcdf_validate",
                    "parameters": {
                        "job_id": job_id,
                        "relative_path": rel_path,
                        "fail_on_warnings": fail_on_warnings,
                    },
                }
                for i, rel_path in enumerate(relative_files)
            ]

        elif stage == 4:
            # Stage 4 (convert): Single task — open_mfdataset → to_zarr
            if not previous_results:
                raise ValueError(
                    "Stage 4 (convert) requires previous_results from validate stage"
                )

            zarr_container = _get_silver_zarr_container()
            output_folder = job_params["output_folder"]

            return [
                {
                    "task_id": f"{job_id[:8]}-s4-convert",
                    "task_type": "netcdf_convert",
                    "parameters": {
                        "job_id": job_id,
                        "file_pattern": job_params.get("file_pattern", "*.nc"),
                        "concat_dim": job_params.get("concat_dim", "time"),
                        "output_folder": output_folder,
                        "zarr_container": zarr_container,
                        "dataset_id": job_params["dataset_id"],
                        "resource_id": job_params["resource_id"],
                        # Chunking optimization
                        "spatial_chunk_size": job_params.get("spatial_chunk_size", 256),
                        "time_chunk_size": job_params.get("time_chunk_size", 1),
                        "compressor": job_params.get("compressor", "lz4"),
                        "compression_level": job_params.get("compression_level", 5),
                        "zarr_format": job_params.get("zarr_format", 3),
                    },
                }
            ]

        elif stage == 5:
            # Stage 5 (register): Single task to build STAC + update release
            if not previous_results:
                raise ValueError(
                    "Stage 5 (register) requires previous_results from convert stage"
                )

            # CoreMachine unwraps the handler envelope — we get the payload directly.
            convert_result = previous_results[0] if previous_results else {}

            zarr_container = _get_silver_zarr_container()
            output_folder = job_params["output_folder"]
            zarr_store_url = convert_result.get(
                "zarr_store_url",
                f"abfs://{zarr_container}/{output_folder}"
            )

            return [
                {
                    "task_id": f"{job_id[:8]}-s5-register",
                    "task_type": "netcdf_register",
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
                        "access_level": job_params.get("access_level"),
                        "spatial_extent": convert_result.get("spatial_extent"),
                        "time_range": convert_result.get("time_range"),
                        "variables": convert_result.get("variables", []),
                        "dimensions": convert_result.get("dimensions", {}),
                        "source_file_count": convert_result.get("source_file_count", 0),
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
            "NetCDFToZarrJob.finalize_job"
        )

        if context:
            logger.info(
                f"NetCDF-to-Zarr job {context.job_id} completed "
                f"with {len(context.task_results)} tasks"
            )
        else:
            logger.info("NetCDF-to-Zarr job completed (no context provided)")

        return {
            "job_type": "netcdf_to_zarr",
            "status": "completed",
        }
