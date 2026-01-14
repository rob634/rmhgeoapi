# ============================================================================
# JOB DELETE HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - DELETE /api/jobs/{job_id}
# PURPOSE: Clean delete of a job and all its artifacts without resubmitting
# CREATED: 14 JAN 2026
# ============================================================================
"""
Job Delete HTTP Trigger.

Provides cleanup capability for jobs - deletes all artifacts without resubmitting.
Uses the same cleanup logic as resubmit but stops after cleanup.

Cleanup includes:
- Delete task records (app.tasks)
- Delete job record (app.jobs)
- Drop PostGIS tables (vector jobs)
- Delete STAC items (raster jobs)
- Optionally delete blob artifacts (COGs)
"""

import json
import logging
import traceback
from typing import Dict, Any

import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "job_delete")


def job_delete(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for job deletion.

    DELETE /api/jobs/{job_id}

    Query Parameters:
        confirm=yes (required) - Explicit confirmation
        delete_blobs=true - Also delete COG files
        force=true - Delete even if job is processing

    Response:
    {
        "success": true,
        "job_id": "abc123...",
        "job_type": "process_raster_v2",
        "cleanup_summary": {
            "tasks_deleted": 5,
            "job_deleted": true,
            "tables_dropped": [],
            "stac_items_deleted": ["item-123"],
            "blobs_deleted": []
        },
        "message": "Job deleted successfully"
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

    # Require explicit confirmation
    confirm = req.params.get('confirm', '').lower()
    if confirm != 'yes':
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Delete requires confirmation: ?confirm=yes",
                "error_type": "ConfirmationRequired",
                "usage": f"DELETE /api/jobs/{job_id}?confirm=yes"
            }),
            status_code=400,
            mimetype="application/json"
        )

    # Parse options
    delete_blobs = req.params.get('delete_blobs', '').lower() == 'true'
    force = req.params.get('force', '').lower() == 'true'
    dry_run = req.params.get('dry_run', '').lower() == 'true'

    logger.info(f"Job delete requested: {job_id[:16]}... (dry_run={dry_run})")

    try:
        from infrastructure import RepositoryFactory

        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']

        # Get existing job
        job = job_repo.get_job(job_id)
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
                    "error": f"Job is currently processing. Use force=true to delete anyway.",
                    "job_status": job.status.value,
                    "error_type": "JobInProgress"
                }),
                status_code=409,
                mimetype="application/json"
            )

        job_type = job.job_type
        parameters = job.parameters.copy() if job.parameters else {}

        logger.info(f"  Job type: {job_type}")
        logger.info(f"  Current status: {job.status.value}")

        # Plan cleanup
        cleanup_plan = _plan_cleanup(job, parameters, task_repo)

        if dry_run:
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "dry_run": True,
                    "job_id": job_id,
                    "job_type": job_type,
                    "job_status": job.status.value,
                    "cleanup_plan": cleanup_plan,
                    "message": "Dry run - no changes made"
                }, default=str),
                status_code=200,
                mimetype="application/json"
            )

        # Execute cleanup (reuse logic from resubmit)
        cleanup_result = _execute_cleanup(job, cleanup_plan, delete_blobs, job_repo, task_repo)

        logger.info(f"✅ Job deleted: {job_id[:16]}...")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "job_id": job_id,
                "job_type": job_type,
                "cleanup_summary": cleanup_result,
                "message": "Job deleted successfully"
            }, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Job delete failed: {e}")
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


def _plan_cleanup(job, parameters: Dict[str, Any], task_repo) -> Dict[str, Any]:
    """Plan cleanup actions based on job type."""
    job_type = job.job_type
    plan = {
        "tasks_to_delete": 0,
        "job_to_delete": True,
        "tables_to_drop": [],
        "stac_items_to_delete": [],
        "blobs_to_delete": []
    }

    # Count tasks
    tasks = task_repo.get_tasks_for_job(job.job_id)
    plan["tasks_to_delete"] = len(tasks) if tasks else 0

    # Determine artifacts based on job type
    if 'vector' in job_type.lower():
        table_name = parameters.get('table_name')
        schema = parameters.get('schema', 'geo')
        if table_name:
            plan["tables_to_drop"].append(f"{schema}.{table_name}")

        stac_item_id = parameters.get('stac_item_id')
        if stac_item_id:
            plan["stac_items_to_delete"].append({
                "item_id": stac_item_id,
                "collection_id": parameters.get('collection_id', 'system-vectors')
            })

    elif 'raster' in job_type.lower():
        stac_item_id = parameters.get('stac_item_id')
        collection_id = parameters.get('collection_id')  # No default (14 JAN 2026)

        if stac_item_id and collection_id:
            plan["stac_items_to_delete"].append({
                "item_id": stac_item_id,
                "collection_id": collection_id
            })

        if job.result_data:
            cog_info = job.result_data.get('cog', {})
            output_path = cog_info.get('output_path') or cog_info.get('cog_path')
            if output_path:
                plan["blobs_to_delete"].append(output_path)

    return plan


def _execute_cleanup(job, plan: Dict[str, Any], delete_blobs: bool, job_repo, task_repo) -> Dict[str, Any]:
    """Execute the cleanup plan."""
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
        deleted = task_repo.delete_tasks_for_job(job_id)
        result["tasks_deleted"] = deleted or plan["tasks_to_delete"]
        logger.info(f"  Deleted {result['tasks_deleted']} tasks")
    except Exception as e:
        result["errors"].append(f"Failed to delete tasks: {e}")
        logger.error(f"  Failed to delete tasks: {e}")

    # 2. Drop PostGIS tables
    for table_fqn in plan.get("tables_to_drop", []):
        try:
            _drop_table(table_fqn)
            result["tables_dropped"].append(table_fqn)
            logger.info(f"  Dropped table: {table_fqn}")
        except Exception as e:
            result["errors"].append(f"Failed to drop table {table_fqn}: {e}")
            logger.warning(f"  Failed to drop table {table_fqn}: {e}")

    # 3. Delete STAC items
    for stac_info in plan.get("stac_items_to_delete", []):
        try:
            _delete_stac_item(stac_info["item_id"], stac_info["collection_id"])
            result["stac_items_deleted"].append(stac_info["item_id"])
            logger.info(f"  Deleted STAC item: {stac_info['item_id']}")
        except Exception as e:
            result["errors"].append(f"Failed to delete STAC item {stac_info['item_id']}: {e}")
            logger.warning(f"  Failed to delete STAC item: {e}")

    # 4. Delete blobs (only if explicitly requested)
    if delete_blobs:
        for blob_path in plan.get("blobs_to_delete", []):
            try:
                _delete_blob(blob_path)
                result["blobs_deleted"].append(blob_path)
                logger.info(f"  Deleted blob: {blob_path}")
            except Exception as e:
                result["errors"].append(f"Failed to delete blob {blob_path}: {e}")
                logger.warning(f"  Failed to delete blob: {e}")

    # 5. Delete job record (last - after all cleanup)
    try:
        job_repo.delete_job(job_id)
        result["job_deleted"] = True
        logger.info(f"  Deleted job record: {job_id[:16]}...")
    except Exception as e:
        result["errors"].append(f"Failed to delete job: {e}")
        logger.error(f"  Failed to delete job: {e}")

    return result


def _drop_table(table_fqn: str) -> None:
    """Drop a PostGIS table."""
    from infrastructure.postgresql import PostgreSQLAdapter

    if '.' in table_fqn:
        schema, table = table_fqn.split('.', 1)
    else:
        schema, table = 'geo', table_fqn

    adapter = PostgreSQLAdapter()
    query = f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'
    adapter.execute_non_query(query)


def _delete_stac_item(item_id: str, collection_id: str) -> None:
    """Delete a STAC item from pgSTAC."""
    from infrastructure.pgstac_repository import PgStacRepository

    pgstac_repo = PgStacRepository()
    pgstac_repo.delete_item(collection_id, item_id)


def _delete_blob(blob_path: str) -> None:
    """Delete a blob from storage."""
    from infrastructure.storage import BlobStorageAdapter
    from config import get_config

    config = get_config()

    parts = blob_path.split('/', 1)
    if len(parts) == 2 and parts[0] in ['silver-cogs', 'bronze-rasters', 'gold-exports']:
        container, blob_name = parts
    else:
        container = 'silver-cogs'
        blob_name = blob_path

    if container.startswith('bronze'):
        account = config.storage.bronze_account
    elif container.startswith('gold'):
        account = config.storage.gold_account
    else:
        account = config.storage.silver_account

    adapter = BlobStorageAdapter(account)
    adapter.delete_blob(container, blob_name)
