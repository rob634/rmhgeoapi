# ============================================================================
# JOB RESUBMIT HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/jobs/{job_id}/resubmit
# PURPOSE: Clean reset and resubmit of a job with same parameters
# CREATED: 12 JAN 2026
# ============================================================================
"""
Job Resubmit HTTP Trigger.

Provides a "nuclear reset" capability for jobs - cleans up all artifacts
and resubmits with the same parameters. Useful for:
- Failed jobs that need retry
- Orphaned jobs stuck in processing
- Jobs that completed but need to be re-run

Cleanup includes:
- Delete task records (app.tasks)
- Delete job record (app.jobs)
- Drop PostGIS tables (vector jobs)
- Delete STAC items (raster jobs)
- Optionally delete blob artifacts (COGs)

Orphaned queue messages are handled gracefully by CoreMachine
(they fail silently when task record not found).
"""

import json
import logging
import traceback
from typing import Dict, Any, Optional, List

import azure.functions as func

from util_logger import LoggerFactory, ComponentType
from triggers.http_base import parse_request_json

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "job_resubmit")


class JobResubmitHandler:
    """
    Handler for job resubmit operations.

    Performs cleanup of existing job artifacts and resubmits
    with the same parameters.
    """

    def __init__(self):
        """Initialize with repository access."""
        from infrastructure import RepositoryFactory
        self.repos = RepositoryFactory.create_repositories()
        self.job_repo = self.repos['job_repo']
        self.task_repo = self.repos['task_repo']

    def handle(self, req: func.HttpRequest, job_id: str) -> func.HttpResponse:
        """
        Handle job resubmit request.

        Args:
            req: HTTP request
            job_id: Job ID to resubmit

        Returns:
            HTTP response with resubmit result
        """
        logger.info(f"Job resubmit requested: {job_id[:16]}...")

        try:
            # Parse options from request body (optional)
            options = self._parse_options(req)
            dry_run = options.get('dry_run', False)
            delete_blobs = options.get('delete_blobs', False)
            force = options.get('force', False)

            # Step 1: Get existing job
            job = self.job_repo.get_job(job_id)
            if not job:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Job not found: {job_id}",
                        "error_type": "NotFound"
                    }),
                    status_code=404,
                    mimetype="application/json"
                )

            # Check if job is currently processing (unless force=True)
            if job.status.value == 'processing' and not force:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Job is currently processing. Use force=true to resubmit anyway.",
                        "job_status": job.status.value,
                        "error_type": "JobInProgress"
                    }),
                    status_code=409,
                    mimetype="application/json"
                )

            # Extract job info for resubmission
            job_type = job.job_type
            parameters = job.parameters.copy() if job.parameters else {}

            # Remove internal parameters that shouldn't be reused
            internal_keys = [k for k in parameters.keys() if k.startswith('_')]
            for key in internal_keys:
                del parameters[key]

            logger.info(f"  Job type: {job_type}")
            logger.info(f"  Current status: {job.status.value}")
            logger.info(f"  Parameters: {list(parameters.keys())}")

            # Step 2: Determine cleanup actions based on job type
            cleanup_plan = self._plan_cleanup(job, parameters)

            if dry_run:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "dry_run": True,
                        "job_id": job_id,
                        "job_type": job_type,
                        "job_status": job.status.value,
                        "cleanup_plan": cleanup_plan,
                        "parameters": parameters,
                        "message": "Dry run - no changes made"
                    }, default=str),
                    status_code=200,
                    mimetype="application/json"
                )

            # Step 3: Execute cleanup
            cleanup_result = self._execute_cleanup(job, cleanup_plan, delete_blobs)

            # Step 4: Resubmit job
            new_job_id = self._resubmit_job(job_type, parameters)

            logger.info(f"✅ Job resubmitted: {job_id[:16]}... → {new_job_id[:16]}...")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "original_job_id": job_id,
                    "new_job_id": new_job_id,
                    "job_type": job_type,
                    "cleanup_summary": cleanup_result,
                    "message": "Job resubmitted successfully"
                }, default=str),
                status_code=202,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"Job resubmit failed: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__
                }),
                status_code=500,
                mimetype="application/json"
            )

    def _parse_options(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Parse options from request body."""
        try:
            return parse_request_json(req, required=False) or {}
        except ValueError:
            return {}

    def _plan_cleanup(self, job, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Plan cleanup actions based on job type.

        Returns dict describing what will be cleaned up.
        """
        job_type = job.job_type
        plan = {
            "tasks_to_delete": 0,
            "job_to_delete": True,
            "tables_to_drop": [],
            "stac_items_to_delete": [],
            "blobs_to_delete": []
        }

        # Count tasks
        tasks = self.task_repo.get_tasks_for_job(job.job_id)
        plan["tasks_to_delete"] = len(tasks) if tasks else 0

        # Determine artifacts based on job type
        if 'vector' in job_type.lower():
            # Vector job - check for table_name
            table_name = parameters.get('table_name')
            schema = parameters.get('schema', 'geo')
            if table_name:
                plan["tables_to_drop"].append(f"{schema}.{table_name}")

            # Check for STAC item
            stac_item_id = parameters.get('stac_item_id')
            if stac_item_id:
                plan["stac_items_to_delete"].append({
                    "item_id": stac_item_id,
                    "collection_id": parameters.get('collection_id', 'system-vectors')
                })

        elif 'raster' in job_type.lower():
            # Raster job - check for STAC item and COG
            stac_item_id = parameters.get('stac_item_id')
            collection_id = parameters.get('collection_id')  # No default (14 JAN 2026)

            if stac_item_id and collection_id:
                plan["stac_items_to_delete"].append({
                    "item_id": stac_item_id,
                    "collection_id": collection_id
                })

            # Check result_data for output paths
            if job.result_data:
                cog_info = job.result_data.get('cog', {})
                output_path = cog_info.get('output_path') or cog_info.get('cog_path')
                if output_path:
                    plan["blobs_to_delete"].append(output_path)

        return plan

    def _execute_cleanup(
        self,
        job,
        plan: Dict[str, Any],
        delete_blobs: bool = False
    ) -> Dict[str, Any]:
        """
        Execute the cleanup plan.

        Returns summary of what was cleaned up.
        """
        result = {
            "tasks_deleted": 0,
            "job_deleted": False,
            "tables_dropped": [],
            "stac_items_deleted": [],
            "blobs_deleted": [],
            "errors": []
        }

        job_id = job.job_id

        # 1. Delete tasks
        try:
            deleted = self.task_repo.delete_tasks_for_job(job_id)
            result["tasks_deleted"] = deleted or plan["tasks_to_delete"]
            logger.info(f"  Deleted {result['tasks_deleted']} tasks")
        except Exception as e:
            result["errors"].append(f"Failed to delete tasks: {e}")
            logger.error(f"  Failed to delete tasks: {e}")

        # 2. Drop PostGIS tables
        for table_fqn in plan.get("tables_to_drop", []):
            try:
                self._drop_table(table_fqn)
                result["tables_dropped"].append(table_fqn)
                logger.info(f"  Dropped table: {table_fqn}")
            except Exception as e:
                result["errors"].append(f"Failed to drop table {table_fqn}: {e}")
                logger.warning(f"  Failed to drop table {table_fqn}: {e}")

        # 3. Delete STAC items
        for stac_info in plan.get("stac_items_to_delete", []):
            try:
                self._delete_stac_item(stac_info["item_id"], stac_info["collection_id"])
                result["stac_items_deleted"].append(stac_info["item_id"])
                logger.info(f"  Deleted STAC item: {stac_info['item_id']}")
            except Exception as e:
                result["errors"].append(f"Failed to delete STAC item {stac_info['item_id']}: {e}")
                logger.warning(f"  Failed to delete STAC item: {e}")

        # 4. Delete blobs (only if explicitly requested)
        if delete_blobs:
            for blob_path in plan.get("blobs_to_delete", []):
                try:
                    self._delete_blob(blob_path)
                    result["blobs_deleted"].append(blob_path)
                    logger.info(f"  Deleted blob: {blob_path}")
                except Exception as e:
                    result["errors"].append(f"Failed to delete blob {blob_path}: {e}")
                    logger.warning(f"  Failed to delete blob: {e}")

        # 5. Delete job record (last - after all cleanup)
        try:
            self.job_repo.delete_job(job_id)
            result["job_deleted"] = True
            logger.info(f"  Deleted job record: {job_id[:16]}...")
        except Exception as e:
            result["errors"].append(f"Failed to delete job: {e}")
            logger.error(f"  Failed to delete job: {e}")

        return result

    def _drop_table(self, table_fqn: str) -> None:
        """Drop a PostGIS table."""
        from infrastructure.postgresql import PostgreSQLAdapter

        # Parse schema.table
        if '.' in table_fqn:
            schema, table = table_fqn.split('.', 1)
        else:
            schema, table = 'geo', table_fqn

        adapter = PostgreSQLAdapter()
        # Use parameterized identifiers safely
        query = f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'
        adapter.execute_non_query(query)

    def _delete_stac_item(self, item_id: str, collection_id: str) -> None:
        """Delete a STAC item from pgSTAC."""
        from infrastructure.pgstac_repository import PgStacRepository

        pgstac_repo = PgStacRepository()
        pgstac_repo.delete_item(collection_id, item_id)

    def _delete_blob(self, blob_path: str) -> None:
        """Delete a blob from storage."""
        from infrastructure.storage import BlobStorageAdapter
        from config import get_config

        config = get_config()

        # Parse container/blob from path
        # Expected format: container/path/to/blob.tif or just path/to/blob.tif
        parts = blob_path.split('/', 1)
        if len(parts) == 2 and parts[0] in ['silver-cogs', 'bronze-rasters', 'gold-exports']:
            container, blob_name = parts
        else:
            # Assume silver-cogs container
            container = 'silver-cogs'
            blob_name = blob_path

        # Determine storage account based on container
        if container.startswith('bronze'):
            account = config.storage.bronze_account
        elif container.startswith('gold'):
            account = config.storage.gold_account
        else:
            account = config.storage.silver_account

        adapter = BlobStorageAdapter(account)
        adapter.delete_blob(container, blob_name)

    def _resubmit_job(self, job_type: str, parameters: Dict[str, Any]) -> str:
        """
        Resubmit the job with the same parameters.

        Returns new job_id.
        """
        import hashlib
        import uuid
        from jobs import ALL_JOBS
        from core.models.job import JobRecord
        from core.models.enums import JobStatus
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config

        config = get_config()

        # Get job class
        job_class = ALL_JOBS.get(job_type)
        if not job_class:
            raise ValueError(f"Unknown job type: {job_type}")

        # For vector jobs, force overwrite=True since we're resubmitting after cleanup
        # This prevents the pre-flight validation from failing if the table was only
        # partially dropped or exists from a previous failed attempt (12 JAN 2026)
        if 'vector' in job_type.lower():
            parameters['overwrite'] = True
            logger.info("  Set overwrite=True for vector job resubmission")

        # Validate parameters
        validated_params = job_class.validate_job_parameters(parameters)

        # Generate job ID (deterministic based on params)
        clean_params = {k: v for k, v in validated_params.items() if not k.startswith('_')}
        canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}"
        job_id = hashlib.sha256(canonical.encode()).hexdigest()

        # Create job record
        job_record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=len(job_class.stages),
            parameters=validated_params,
            metadata={
                'resubmitted': True,
                'resubmit_timestamp': str(uuid.uuid4())[:8]  # Make unique for idempotency
            }
        )

        # Store in database
        self.job_repo.create_job(job_record)

        # Submit to Service Bus
        service_bus = ServiceBusRepository()
        queue_message = JobQueueMessage(
            job_id=job_id,
            job_type=job_type,
            parameters=validated_params,
            stage=1,
            correlation_id=str(uuid.uuid4())[:8]
        )

        service_bus.send_message(
            config.queues.jobs_queue,
            queue_message
        )

        logger.info(f"  Resubmitted job {job_id[:16]}... to queue")
        return job_id


# Create singleton handler
_handler = None


def get_handler() -> JobResubmitHandler:
    """Get or create handler instance."""
    global _handler
    if _handler is None:
        _handler = JobResubmitHandler()
    return _handler


def job_resubmit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for job resubmit.

    POST /api/jobs/{job_id}/resubmit

    Request Body (optional):
    {
        "dry_run": false,      // Preview cleanup without executing
        "delete_blobs": false, // Also delete COG files
        "force": false         // Resubmit even if job is processing
    }

    Response:
    {
        "success": true,
        "original_job_id": "abc123...",
        "new_job_id": "abc123...",
        "job_type": "process_raster_v2",
        "cleanup_summary": {
            "tasks_deleted": 5,
            "job_deleted": true,
            "tables_dropped": [],
            "stac_items_deleted": ["item-123"],
            "blobs_deleted": []
        },
        "message": "Job resubmitted successfully"
    }
    """
    # Extract job_id from route
    job_id = req.route_params.get('job_id')
    if not job_id:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "job_id is required",
                "error_type": "ValidationError"
            }),
            status_code=400,
            mimetype="application/json"
        )

    handler = get_handler()
    return handler.handle(req, job_id)
