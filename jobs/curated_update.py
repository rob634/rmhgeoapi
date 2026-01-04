# ============================================================================
# CURATED DATASET UPDATE JOB
# ============================================================================
# STATUS: Jobs - 4-stage curated dataset update workflow
# PURPOSE: Update curated datasets from external sources (WDPA, Admin0, etc.)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Curated Dataset Update Job.

Four-stage workflow for updating curated datasets from external sources.
Uses JobBaseMixin for declarative configuration.

Four-Stage Workflow:
    Stage 1 (check_source): Check if source has new data
    Stage 2 (fetch_data): Download data if update needed
    Stage 3 (etl_process): Process and load to PostGIS
    Stage 4 (finalize): Update registry and log results

Exports:
    CuratedDatasetUpdateJob: Update workflow for curated datasets
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.JOB, "CuratedUpdate")


class CuratedDatasetUpdateJob(JobBaseMixin, JobBase):
    """
    Curated dataset update job using JobBaseMixin pattern.

    Four-Stage Workflow:
    1. CHECK_SOURCE: Check if source has new version
    2. FETCH_DATA: Download data if update needed
    3. ETL_PROCESS: Process and load to PostGIS
    4. FINALIZE: Update registry, log results, create STAC

    Supports multiple dataset types (WDPA, Admin0, etc.)
    via the dataset_id parameter.
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "curated_dataset_update"
    description = "Update curated dataset from external source"

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "check_source",
            "task_type": "curated_check_source",
            "parallelism": "single",  # Only one check task
        },
        {
            "number": 2,
            "name": "fetch_data",
            "task_type": "curated_fetch_data",
            "parallelism": "single",  # One download task
            "depends_on": 1,
            "uses_lineage": True,  # Needs download URL from stage 1
            "skip_if": "no_update_needed"  # Skip if source unchanged
        },
        {
            "number": 3,
            "name": "etl_process",
            "task_type": "curated_etl_process",
            "parallelism": "single",  # Process entire file
            "depends_on": 2,
            "uses_lineage": True,  # Needs file path from stage 2
        },
        {
            "number": 4,
            "name": "finalize",
            "task_type": "curated_finalize",
            "parallelism": "single",
            "depends_on": 3,
            "uses_lineage": True,  # Needs record counts from stage 3
        }
    ]

    # Declarative parameter validation
    parameters_schema = {
        "dataset_id": {
            "type": "str",
            "required": True,
            "description": "Curated dataset registry ID (e.g., 'wdpa', 'admin0')"
        },
        "update_type": {
            "type": "str",
            "default": "manual",
            "allowed": ["manual", "scheduled", "triggered"],
            "description": "What triggered this update"
        },
        "force_update": {
            "type": "bool",
            "default": False,
            "description": "Force update even if source unchanged"
        },
        "dry_run": {
            "type": "bool",
            "default": False,
            "description": "Simulate update without writing data"
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

        Args:
            stage: Stage number (1-4)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        dataset_id = job_params.get('dataset_id')
        update_type = job_params.get('update_type', 'manual')
        force_update = job_params.get('force_update', False)
        dry_run = job_params.get('dry_run', False)

        if stage == 1:
            # Stage 1: Check source for updates
            return [{
                "task_id": f"{job_id[:8]}-check",
                "task_type": "curated_check_source",
                "parameters": {
                    "dataset_id": dataset_id,
                    "force_update": force_update
                }
            }]

        elif stage == 2:
            # Stage 2: Fetch data (if update needed)
            # Get download URL from stage 1 results
            download_url = None
            needs_update = True

            if previous_results:
                for result in previous_results:
                    if result.get("success"):
                        download_url = result.get("result", {}).get("download_url")
                        needs_update = result.get("result", {}).get("needs_update", True)
                        break

            if not needs_update and not force_update:
                logger.info(f"Dataset {dataset_id} is up to date - skipping fetch")
                return [{
                    "task_id": f"{job_id[:8]}-fetch-skip",
                    "task_type": "curated_fetch_data",
                    "parameters": {
                        "dataset_id": dataset_id,
                        "skip": True,
                        "reason": "No update needed"
                    }
                }]

            return [{
                "task_id": f"{job_id[:8]}-fetch",
                "task_type": "curated_fetch_data",
                "parameters": {
                    "dataset_id": dataset_id,
                    "download_url": download_url,
                    "dry_run": dry_run
                }
            }]

        elif stage == 3:
            # Stage 3: ETL process
            file_path = None
            skipped = False

            if previous_results:
                for result in previous_results:
                    if result.get("success"):
                        result_data = result.get("result", {})
                        file_path = result_data.get("file_path")
                        skipped = result_data.get("skip", False)
                        break

            if skipped:
                return [{
                    "task_id": f"{job_id[:8]}-etl-skip",
                    "task_type": "curated_etl_process",
                    "parameters": {
                        "dataset_id": dataset_id,
                        "skip": True,
                        "reason": "Previous stage skipped"
                    }
                }]

            return [{
                "task_id": f"{job_id[:8]}-etl",
                "task_type": "curated_etl_process",
                "parameters": {
                    "dataset_id": dataset_id,
                    "file_path": file_path,
                    "dry_run": dry_run
                }
            }]

        elif stage == 4:
            # Stage 4: Finalize - update registry and log
            records_loaded = 0
            source_version = None
            skipped = False

            if previous_results:
                for result in previous_results:
                    if result.get("success"):
                        result_data = result.get("result", {})
                        records_loaded = result_data.get("records_loaded", 0)
                        source_version = result_data.get("source_version")
                        skipped = result_data.get("skip", False)
                        break

            return [{
                "task_id": f"{job_id[:8]}-finalize",
                "task_type": "curated_finalize",
                "parameters": {
                    "dataset_id": dataset_id,
                    "job_id": job_id,
                    "update_type": update_type,
                    "records_loaded": records_loaded,
                    "source_version": source_version,
                    "skipped": skipped,
                    "dry_run": dry_run
                }
            }]

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
            context: JobExecutionContext with all stage results

        Returns:
            Final job summary
        """
        summary = {
            "status": "completed",
            "job_type": "curated_dataset_update",
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        if context:
            # Extract key info from context
            params = getattr(context, 'job_params', {})
            summary["dataset_id"] = params.get("dataset_id")
            summary["update_type"] = params.get("update_type", "manual")

        return summary


# ============================================================================
# TASK HANDLERS
# ============================================================================
# These handlers are registered in services/__init__.py

def curated_check_source(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Stage 1: Check source for updates.

    Queries the dataset's source API to check for new versions.
    """
    try:
        dataset_id = params.get('dataset_id')
        force_update = params.get('force_update', False)

        logger.info(f"Checking source for curated dataset: {dataset_id}")

        # Get dataset from registry
        from services.curated.registry_service import CuratedRegistryService
        service = CuratedRegistryService.instance()
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return {
                "success": False,
                "error": f"Dataset not found: {dataset_id}",
                "error_type": "NotFoundError"
            }

        # Route to appropriate handler based on dataset
        if dataset_id == "wdpa":
            from services.curated.wdpa_handler import WDPAHandler
            handler = WDPAHandler()
            result = handler.check_for_updates()

            if result.get("success"):
                return {
                    "success": True,
                    "result": {
                        "dataset_id": dataset_id,
                        "needs_update": result.get("needs_update", True) or force_update,
                        "download_url": result.get("download_url"),
                        "source_version": result.get("wdpa_version"),
                        "download_format": result.get("download_format"),
                        "checked_at": result.get("checked_at")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error"),
                    "error_type": result.get("error_type")
                }

        elif dataset_id == "admin0":
            # Admin0 is manual update only
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "needs_update": force_update,
                    "message": "Admin0 is manual update only"
                }
            }

        else:
            # Generic handler - just mark as needing update if forced
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "needs_update": force_update,
                    "message": f"No specific handler for {dataset_id}"
                }
            }

    except Exception as e:
        logger.error(f"Check source failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def curated_fetch_data(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Stage 2: Fetch data from source.

    Downloads the dataset from the source URL.
    """
    try:
        dataset_id = params.get('dataset_id')
        download_url = params.get('download_url')
        dry_run = params.get('dry_run', False)
        skip = params.get('skip', False)

        if skip:
            logger.info(f"Skipping fetch for {dataset_id}: {params.get('reason')}")
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "skip": True,
                    "reason": params.get('reason')
                }
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would fetch {dataset_id} from {download_url}")
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "dry_run": True,
                    "download_url": download_url
                }
            }

        if not download_url:
            return {
                "success": False,
                "error": "No download URL provided",
                "error_type": "ValidationError"
            }

        logger.info(f"Fetching data for {dataset_id} from {download_url}")

        # Route to appropriate handler
        if dataset_id == "wdpa":
            from services.curated.wdpa_handler import WDPAHandler
            handler = WDPAHandler()
            result = handler.download_dataset(download_url)

            if result.get("success"):
                return {
                    "success": True,
                    "result": {
                        "dataset_id": dataset_id,
                        "file_path": result.get("file_path"),
                        "file_size": result.get("file_size"),
                        "filename": result.get("filename")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error"),
                    "error_type": result.get("error_type", "DownloadError")
                }
        else:
            return {
                "success": False,
                "error": f"No fetch handler for dataset: {dataset_id}",
                "error_type": "NotImplementedError"
            }

    except Exception as e:
        logger.error(f"Fetch data failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def curated_etl_process(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Stage 3: ETL process - load data to PostGIS.

    Extracts, transforms, and loads the data.
    """
    try:
        dataset_id = params.get('dataset_id')
        file_path = params.get('file_path')
        dry_run = params.get('dry_run', False)
        skip = params.get('skip', False)

        if skip:
            logger.info(f"Skipping ETL for {dataset_id}: {params.get('reason')}")
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "skip": True,
                    "reason": params.get('reason')
                }
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would process {dataset_id} from {file_path}")
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "dry_run": True,
                    "file_path": file_path
                }
            }

        if not file_path:
            return {
                "success": False,
                "error": "No file path provided",
                "error_type": "ValidationError"
            }

        logger.info(f"Processing ETL for {dataset_id} from {file_path}")

        # Get dataset config from registry
        from services.curated.registry_service import CuratedRegistryService
        service = CuratedRegistryService.instance()
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return {
                "success": False,
                "error": f"Dataset not found: {dataset_id}",
                "error_type": "NotFoundError"
            }

        # Route to appropriate handler
        if dataset_id == "wdpa":
            from services.curated.wdpa_handler import WDPAHandler
            handler = WDPAHandler()
            result = handler.extract_and_load(
                file_path=file_path,
                target_table=dataset.target_table_name,
                target_schema=dataset.target_schema
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": {
                        "dataset_id": dataset_id,
                        "records_loaded": result.get("records_loaded"),
                        "table_name": result.get("table_name"),
                        "schema_name": result.get("schema_name"),
                        "source_file": result.get("source_file")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error"),
                    "error_type": result.get("error_type", "ETLError")
                }
        else:
            return {
                "success": False,
                "error": f"No ETL handler for dataset: {dataset_id}",
                "error_type": "NotImplementedError"
            }

    except Exception as e:
        logger.error(f"ETL process failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def curated_finalize(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Stage 4: Finalize - update registry and log.

    Updates the curated_datasets registry and creates update log entry.
    """
    try:
        dataset_id = params.get('dataset_id')
        job_id = params.get('job_id')
        update_type = params.get('update_type', 'manual')
        records_loaded = params.get('records_loaded', 0)
        source_version = params.get('source_version')
        skipped = params.get('skipped', False)
        dry_run = params.get('dry_run', False)

        logger.info(f"Finalizing update for {dataset_id}")

        if dry_run:
            logger.info(f"[DRY-RUN] Would finalize {dataset_id}")
            return {
                "success": True,
                "result": {
                    "dataset_id": dataset_id,
                    "dry_run": True
                }
            }

        from services.curated.registry_service import CuratedRegistryService
        from core.models import CuratedUpdateType, CuratedUpdateStatus

        service = CuratedRegistryService.instance()

        # Update registry with last_updated_at
        if not skipped and records_loaded > 0:
            from infrastructure import CuratedDatasetRepository
            repo = CuratedDatasetRepository()
            repo.update_last_updated(
                dataset_id=dataset_id,
                job_id=job_id,
                source_version=source_version
            )
            logger.info(f"Updated registry for {dataset_id}: {records_loaded} records")

        # Create update log entry
        update_type_enum = CuratedUpdateType(update_type)

        if skipped:
            # Log as skipped
            from core.models import CuratedUpdateLog
            log_entry = CuratedUpdateLog(
                dataset_id=dataset_id,
                job_id=job_id,
                update_type=update_type_enum,
                source_version=source_version,
                status=CuratedUpdateStatus.SKIPPED
            )
            from infrastructure import CuratedUpdateLogRepository
            log_repo = CuratedUpdateLogRepository()
            log_repo.create(log_entry)
            logger.info(f"Logged skipped update for {dataset_id}")
        else:
            # Log as completed
            from core.models import CuratedUpdateLog
            log_entry = CuratedUpdateLog(
                dataset_id=dataset_id,
                job_id=job_id,
                update_type=update_type_enum,
                source_version=source_version,
                records_total=records_loaded,
                records_added=records_loaded,  # For full_replace, all are "added"
                status=CuratedUpdateStatus.COMPLETED,
                completed_at=datetime.now(timezone.utc)
            )
            from infrastructure import CuratedUpdateLogRepository
            log_repo = CuratedUpdateLogRepository()
            log_repo.create(log_entry)
            logger.info(f"Logged completed update for {dataset_id}")

        return {
            "success": True,
            "result": {
                "dataset_id": dataset_id,
                "records_loaded": records_loaded,
                "source_version": source_version,
                "skipped": skipped,
                "update_logged": True
            }
        }

    except Exception as e:
        logger.error(f"Finalize failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


__all__ = [
    'CuratedDatasetUpdateJob',
    'curated_check_source',
    'curated_fetch_data',
    'curated_etl_process',
    'curated_finalize'
]
