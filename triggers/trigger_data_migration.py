# ============================================================================
# DATA MIGRATION HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/data-migration/trigger
# PURPOSE: Trigger ADF pipeline to migrate data from internal to external env
# CREATED: 13 JAN 2026
# EXPORTS: handle_data_migration_trigger, handle_data_migration_status, handle_data_migration_cancel
# DEPENDENCIES: azure-mgmt-datafactory, azure-identity
# ============================================================================
"""Data Migration HTTP Trigger.

Triggers Azure Data Factory pipeline to copy data from internal to external environment.

Endpoints:
    POST /api/data-migration/trigger - Trigger migration pipeline
    GET  /api/data-migration/status/{run_id} - Get migration status
    POST /api/data-migration/cancel/{run_id} - Cancel migration

Request Body:
    {
        "pipeline_type": "blob",
        "parameters": {}
    }

Response:
    {
        "success": true,
        "run_id": "abc123...",
        "message": "Migration pipeline triggered",
        "monitor_url": "/api/data-migration/status/abc123..."
    }
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.mgmt.datafactory import DataFactoryManagementClient

from util_logger import ComponentType, LoggerFactory

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_data_migration")

ADF_SUBSCRIPTION_ID = os.environ.get("ADF_SUBSCRIPTION_ID")
ADF_RESOURCE_GROUP = os.environ.get("ADF_RESOURCE_GROUP", "itses-gddatahub-qa-rg")
ADF_FACTORY_NAME = os.environ.get("ADF_FACTORY_NAME", "itses-gddatahub-adf-qa")

ADF_BLOB_PIPELINE_NAME = os.environ.get("ADF_BLOB_PIPELINE_NAME", "blob_internal_to_external")
ADF_VECTOR_PIPELINE_NAME = os.environ.get("ADF_VECTOR_PIPELINE_NAME", "Postgresql_internal_to_external")


def get_adf_client() -> DataFactoryManagementClient:
    if not ADF_SUBSCRIPTION_ID:
        raise ValueError(
            "ADF_SUBSCRIPTION_ID environment variable is not set. "
            "Please configure it in Function App settings."
        )

    credential = DefaultAzureCredential()
    return DataFactoryManagementClient(credential, ADF_SUBSCRIPTION_ID)


def trigger_migration_pipeline(
    pipeline_type: str = "blob",
    parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pipeline_name = ADF_VECTOR_PIPELINE_NAME if pipeline_type.lower() == "vector" else ADF_BLOB_PIPELINE_NAME

    logger.info(f"Triggering ADF pipeline: {pipeline_name} (type: {pipeline_type})")

    client = get_adf_client()

    if parameters:
        run_response = client.pipelines.create_run(
            resource_group_name=ADF_RESOURCE_GROUP,
            factory_name=ADF_FACTORY_NAME,
            pipeline_name=pipeline_name,
            parameters=parameters,
        )
    else:
        run_response = client.pipelines.create_run(
            resource_group_name=ADF_RESOURCE_GROUP,
            factory_name=ADF_FACTORY_NAME,
            pipeline_name=pipeline_name,
        )

    return {
        "run_id": run_response.run_id,
        "status": "Triggered",
        "pipeline_name": pipeline_name,
        "pipeline_type": pipeline_type,
        "factory_name": ADF_FACTORY_NAME,
    }


def get_pipeline_status(run_id: str) -> Dict[str, Any]:
    client = get_adf_client()

    run = client.pipeline_runs.get(
        resource_group_name=ADF_RESOURCE_GROUP,
        factory_name=ADF_FACTORY_NAME,
        run_id=run_id,
    )

    activity_runs = []
    try:
        from datetime import timedelta

        filter_params = {
            "lastUpdatedAfter": datetime.utcnow() - timedelta(days=1),
            "lastUpdatedBefore": datetime.utcnow() + timedelta(days=1),
        }
        activities = client.activity_runs.query_by_pipeline_run(
            resource_group_name=ADF_RESOURCE_GROUP,
            factory_name=ADF_FACTORY_NAME,
            run_id=run_id,
            filter_parameters=filter_params,
        )
        for activity in activities.value:
            activity_runs.append(
                {
                    "activity_name": activity.activity_name,
                    "activity_type": activity.activity_type,
                    "status": activity.status,
                    "started_on": activity.activity_run_start.isoformat() if activity.activity_run_start else None,
                    "ended_on": activity.activity_run_end.isoformat() if activity.activity_run_end else None,
                    "error": activity.error if hasattr(activity, "error") else None,
                }
            )
    except Exception as e:  # best-effort
        logger.warning(f"Could not get activity runs: {e}")

    return {
        "run_id": run_id,
        "pipeline_name": run.pipeline_name,
        "status": run.status,
        "started_on": run.run_start.isoformat() if run.run_start else None,
        "ended_on": run.run_end.isoformat() if run.run_end else None,
        "duration_ms": run.duration_in_ms,
        "message": run.message,
        "parameters": run.parameters,
        "activities": activity_runs,
    }


def cancel_pipeline_run(run_id: str) -> Dict[str, Any]:
    client = get_adf_client()

    client.pipeline_runs.cancel(
        resource_group_name=ADF_RESOURCE_GROUP,
        factory_name=ADF_FACTORY_NAME,
        run_id=run_id,
    )

    return {
        "run_id": run_id,
        "status": "Cancellation requested",
    }


def handle_data_migration_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Data migration trigger endpoint called")

    try:
        try:
            req_body = req.get_json()
        except ValueError as e:
            raw_body = req.get_body().decode("utf-8", errors="replace")
            logger.error(f"JSON parse error: {e}, raw body: {raw_body!r}")
            return func.HttpResponse(
                json.dumps(
                    {
                        "success": False,
                        "error": "Invalid JSON in request body",
                        "debug_raw_body": raw_body[:200] if raw_body else "(empty)",
                        "debug_content_type": req.headers.get("Content-Type", "(not set)"),
                    },
                    indent=2,
                ),
                mimetype="application/json",
                status_code=400,
            )

        pipeline_type = req_body.get("pipeline_type", "blob")

        if pipeline_type.lower() not in ["blob", "vector"]:
            return func.HttpResponse(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Invalid pipeline_type: '{pipeline_type}'. Must be 'blob' or 'vector'",
                    },
                    indent=2,
                ),
                mimetype="application/json",
                status_code=400,
            )

        parameters = req_body.get("parameters")

        result = trigger_migration_pipeline(pipeline_type, parameters)

        response_data: Dict[str, Any] = {
            "success": True,
            "run_id": result["run_id"],
            "pipeline_type": pipeline_type,
            "pipeline_name": result["pipeline_name"],
            "factory_name": result["factory_name"],
            "message": f"{pipeline_type.capitalize()} migration pipeline triggered successfully",
            "monitor_url": f"/api/data-migration/status/{result['run_id']}",
            "triggered_at": datetime.utcnow().isoformat() + "Z",
        }

        if parameters:
            response_data["parameters"] = parameters

        return func.HttpResponse(
            json.dumps(response_data, indent=2),
            mimetype="application/json",
            status_code=202,
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return func.HttpResponse(
            json.dumps({"success": False, "error": str(e)}, indent=2),
            mimetype="application/json",
            status_code=500,
        )

    except Exception as e:
        logger.error(f"Error triggering migration: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"success": False, "error": f"Failed to trigger migration pipeline: {str(e)}"}, indent=2),
            mimetype="application/json",
            status_code=500,
        )


def handle_data_migration_status(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Data migration status endpoint called")

    try:
        run_id = req.route_params.get("run_id")

        if not run_id:
            return func.HttpResponse(
                json.dumps(
                    {"success": False, "error": "Missing run_id in URL path", "usage": "GET /api/data-migration/status/{run_id}"},
                    indent=2,
                ),
                mimetype="application/json",
                status_code=400,
            )

        status = get_pipeline_status(run_id)

        return func.HttpResponse(
            json.dumps({"success": True, "data": status}, indent=2, default=str),
            mimetype="application/json",
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Error getting migration status: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"success": False, "error": f"Failed to get pipeline status: {str(e)}"}, indent=2),
            mimetype="application/json",
            status_code=500,
        )


def handle_data_migration_cancel(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Data migration cancel endpoint called")

    try:
        run_id = req.route_params.get("run_id")

        if not run_id:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Missing run_id in URL path"}, indent=2),
                mimetype="application/json",
                status_code=400,
            )

        result = cancel_pipeline_run(run_id)

        return func.HttpResponse(
            json.dumps({"success": True, "run_id": result["run_id"], "message": "Cancellation requested"}, indent=2),
            mimetype="application/json",
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Error cancelling migration: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"success": False, "error": f"Failed to cancel pipeline: {str(e)}"}, indent=2),
            mimetype="application/json",
            status_code=500,
        )
