# ============================================================================
# CLAUDE CONTEXT - H3 DATASET REGISTRY API
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger - H3 Dataset Registration API
# PURPOSE: CRUD operations for h3.dataset_registry (dev/testing)
# LAST_REVIEWED: 05 JAN 2026
# EXPORTS: AdminH3DatasetsTrigger, admin_h3_datasets_trigger
# DEPENDENCIES: infrastructure.h3_repository
# ============================================================================
"""
H3 Dataset Registry API Trigger.

Development endpoint for managing h3.dataset_registry. For production use,
prefer the h3_register_dataset job which provides async processing and
validation workflows.

Endpoints:
    GET  /api/h3/datasets              - List all datasets
    GET  /api/h3/datasets?id={id}      - Get single dataset
    POST /api/h3/datasets              - Register new dataset (UPSERT)
    DELETE /api/h3/datasets?id={id}    - Delete dataset (requires confirm=yes)

Example POST body:
    {
        "id": "copdem_glo30",
        "display_name": "Copernicus DEM GLO-30",
        "theme": "terrain",
        "data_category": "elevation",
        "source_type": "planetary_computer",
        "source_config": {
            "collection": "cop-dem-glo-30",
            "item_pattern": "Copernicus_DSM_COG_10_N{lat}_00_E{lon}_00_DEM",
            "asset": "data"
        },
        "stat_types": ["mean", "min", "max", "std"],
        "unit": "meters"
    }
"""

import azure.functions as func
import json
import traceback
from datetime import datetime, timezone
from typing import Optional

from infrastructure.h3_repository import H3Repository
from util_logger import LoggerFactory, ComponentType
from triggers.http_base import parse_request_json

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminH3Datasets")


class AdminH3DatasetsTrigger:
    """
    Admin trigger for H3 dataset registry CRUD operations.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminH3DatasetsTrigger'] = None

    def __new__(cls):
        """Singleton pattern - reuse instance across requests."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("Initializing AdminH3DatasetsTrigger")
        self._initialized = True
        logger.info("AdminH3DatasetsTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminH3DatasetsTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def h3_repo(self) -> H3Repository:
        """Lazy initialization of H3 repository."""
        if not hasattr(self, '_h3_repo'):
            logger.debug("Lazy loading H3 repository")
            self._h3_repo = H3Repository()
        return self._h3_repo

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route H3 dataset requests based on HTTP method.

        GET: List datasets or get single dataset
        POST: Register new dataset (UPSERT)
        DELETE: Delete dataset
        """
        try:
            method = req.method.upper()
            logger.info(f"H3 datasets request: {method}")

            if method == 'GET':
                return self._handle_get(req)
            elif method == 'POST':
                return self._handle_post(req)
            elif method == 'DELETE':
                return self._handle_delete(req)
            else:
                return func.HttpResponse(
                    json.dumps({
                        "error": f"Method {method} not allowed",
                        "allowed_methods": ["GET", "POST", "DELETE"]
                    }),
                    status_code=405,
                    mimetype="application/json"
                )

        except Exception as e:
            logger.error(f"H3 datasets error: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "error_type": type(e).__name__
                }),
                status_code=500,
                mimetype="application/json"
            )

    def _handle_get(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        GET /api/h3/datasets - List or get datasets.

        Query params:
            id: str - Get single dataset by ID
            theme: str - Filter by theme
            source_type: str - Filter by source type
        """
        dataset_id = req.params.get('id')

        if dataset_id:
            # Get single dataset
            dataset = self.h3_repo.get_dataset(dataset_id)
            if not dataset:
                return func.HttpResponse(
                    json.dumps({
                        "error": f"Dataset '{dataset_id}' not found",
                        "hint": "Use POST /api/h3/datasets to register"
                    }),
                    status_code=404,
                    mimetype="application/json"
                )

            # Convert datetime fields
            for field in ['created_at', 'updated_at', 'last_aggregation_at', 'temporal_start', 'temporal_end']:
                if dataset.get(field):
                    dataset[field] = dataset[field].isoformat()

            return func.HttpResponse(
                json.dumps(dataset, indent=2, default=str),
                mimetype="application/json"
            )
        else:
            # List datasets with optional filters
            theme = req.params.get('theme')
            source_type = req.params.get('source_type')

            datasets = self.h3_repo.list_datasets(theme=theme, source_type=source_type)

            # Convert datetime fields
            for ds in datasets:
                if ds.get('last_aggregation_at'):
                    ds['last_aggregation_at'] = ds['last_aggregation_at'].isoformat()

            result = {
                "total": len(datasets),
                "filters": {
                    "theme": theme,
                    "source_type": source_type
                },
                "datasets": datasets,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json"
            )

    def _handle_post(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        POST /api/h3/datasets - Register new dataset (UPSERT).

        Required fields:
            id, display_name, theme, data_category, source_type, source_config

        Optional fields:
            stat_types, unit, description, source_name, source_url,
            source_license, recommended_h3_res, nodata_value
        """
        try:
            body = parse_request_json(req)
        except ValueError:
            return func.HttpResponse(
                json.dumps({
                    "error": "Invalid JSON body",
                    "hint": "POST body must be valid JSON"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Validate required fields
        required_fields = ['id', 'display_name', 'theme', 'data_category', 'source_type', 'source_config']
        missing = [f for f in required_fields if not body.get(f)]
        if missing:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Missing required fields: {missing}",
                    "required": required_fields,
                    "example": {
                        "id": "copdem_glo30",
                        "display_name": "Copernicus DEM GLO-30",
                        "theme": "terrain",
                        "data_category": "elevation",
                        "source_type": "planetary_computer",
                        "source_config": {
                            "collection": "cop-dem-glo-30",
                            "asset": "data"
                        }
                    }
                }),
                status_code=400,
                mimetype="application/json"
            )

        try:
            result = self.h3_repo.register_dataset(
                id=body['id'],
                display_name=body['display_name'],
                theme=body['theme'],
                data_category=body['data_category'],
                source_type=body['source_type'],
                source_config=body['source_config'],
                stat_types=body.get('stat_types'),
                unit=body.get('unit'),
                description=body.get('description'),
                source_name=body.get('source_name'),
                source_url=body.get('source_url'),
                source_license=body.get('source_license'),
                recommended_h3_res=body.get('recommended_h3_res'),
                nodata_value=body.get('nodata_value')
            )

            # Convert datetime
            if result.get('updated_at'):
                result['updated_at'] = result['updated_at'].isoformat()

            status_code = 201 if result.get('created') else 200
            action = "registered" if result.get('created') else "updated"

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "action": action,
                    "dataset": result,
                    "message": f"Dataset '{body['id']}' {action} successfully"
                }, indent=2, default=str),
                status_code=status_code,
                mimetype="application/json"
            )

        except ValueError as e:
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "valid_themes": H3Repository.VALID_THEMES,
                    "valid_source_types": ["planetary_computer", "azure", "url"]
                }),
                status_code=400,
                mimetype="application/json"
            )

    def _handle_delete(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        DELETE /api/h3/datasets?id={id}&confirm=yes - Delete dataset.

        Query params:
            id: str - Required dataset ID
            confirm: str - Must be "yes" to actually delete
        """
        dataset_id = req.params.get('id')
        confirm = req.params.get('confirm', '').lower() == 'yes'

        if not dataset_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing 'id' parameter",
                    "usage": "DELETE /api/h3/datasets?id={dataset_id}&confirm=yes"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Check if dataset exists
        dataset = self.h3_repo.get_dataset(dataset_id)
        if not dataset:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Dataset '{dataset_id}' not found"
                }),
                status_code=404,
                mimetype="application/json"
            )

        if not confirm:
            return func.HttpResponse(
                json.dumps({
                    "dry_run": True,
                    "dataset_id": dataset_id,
                    "dataset_name": dataset.get('display_name'),
                    "theme": dataset.get('theme'),
                    "cells_aggregated": dataset.get('cells_aggregated', 0),
                    "message": "Add &confirm=yes to actually delete",
                    "warning": "This will NOT delete zonal_stats rows - only the registry entry"
                }),
                mimetype="application/json"
            )

        # Actually delete
        from psycopg import sql

        with self.h3_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("""
                    DELETE FROM {schema}.{table} WHERE id = %s
                """).format(
                    schema=sql.Identifier('h3'),
                    table=sql.Identifier('dataset_registry')
                ), (dataset_id,))
                deleted = cur.rowcount > 0
                conn.commit()

        if deleted:
            logger.info(f"Deleted dataset: {dataset_id}")
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "deleted": dataset_id,
                    "message": f"Dataset '{dataset_id}' deleted from registry"
                }),
                mimetype="application/json"
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Failed to delete dataset '{dataset_id}'"
                }),
                status_code=500,
                mimetype="application/json"
            )


# ============================================================================
# MODULE EXPORT (Singleton instance for function_app.py)
# ============================================================================
admin_h3_datasets_trigger = AdminH3DatasetsTrigger.instance()
