# ============================================================================
# CURATED DATASET ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger layer - /api/curated/datasets/* endpoints
# PURPOSE: CRUD operations for curated dataset registry
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: CuratedAdminTrigger, curated_admin_trigger
# DEPENDENCIES: services.curated.registry_service
# ============================================================================
"""
Curated Dataset Admin Trigger.

HTTP endpoints for curated dataset registry CRUD operations.

Endpoints:
    GET    /api/curated/datasets           - List all curated datasets
    GET    /api/curated/datasets/{id}      - Get dataset by ID
    POST   /api/curated/datasets           - Create new dataset
    PUT    /api/curated/datasets/{id}      - Update dataset
    DELETE /api/curated/datasets/{id}      - Delete dataset (confirm=yes required)
    POST   /api/curated/datasets/{id}/update    - Trigger manual update
    GET    /api/curated/datasets/{id}/history   - Get update history

Exports:
    CuratedAdminTrigger: HTTP trigger class
    curated_admin_trigger: Singleton instance
"""

import azure.functions as func
import json
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from util_logger import LoggerFactory, ComponentType
from config import get_config
from triggers.http_base import parse_request_json
from services.curated.registry_service import CuratedRegistryService
from core.models import (
    CuratedDataset,
    CuratedSourceType,
    CuratedUpdateStrategy
)

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "CuratedAdmin")


class CuratedAdminTrigger:
    """
    Admin trigger for curated dataset CRUD operations.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['CuratedAdminTrigger'] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("Initializing CuratedAdminTrigger")
        self.config = get_config()
        self._initialized = True
        logger.info("CuratedAdminTrigger initialized")

    @classmethod
    def instance(cls) -> 'CuratedAdminTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def service(self) -> CuratedRegistryService:
        """Lazy initialization of registry service."""
        if not hasattr(self, '_service'):
            self._service = CuratedRegistryService.instance()
        return self._service

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route curated dataset requests.

        Routes:
            GET  /api/curated/datasets - List all
            GET  /api/curated/datasets/{id} - Get one
            POST /api/curated/datasets - Create
            PUT  /api/curated/datasets/{id} - Update
            DELETE /api/curated/datasets/{id}?confirm=yes - Delete
            POST /api/curated/datasets/{id}/update - Manual update
            GET  /api/curated/datasets/{id}/history - Update history

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response
        """
        try:
            url = req.url
            method = req.method

            # Extract path after /curated/
            if '/curated/' in url:
                path = url.split('/curated/')[-1].strip('/')
            else:
                path = ''

            # Strip query string
            if '?' in path:
                path = path.split('?')[0].strip('/')

            path_parts = path.split('/') if path else []

            logger.info(f"Curated admin request: method={method}, path={path}, parts={path_parts}")

            # Route to appropriate handler
            if not path_parts or path_parts[0] != 'datasets':
                return self._error_response("Invalid path", 404)

            # /api/curated/datasets
            if len(path_parts) == 1:
                if method == 'GET':
                    return self._list_datasets(req)
                elif method == 'POST':
                    return self._create_dataset(req)
                else:
                    return self._error_response(f"Method {method} not allowed", 405)

            # /api/curated/datasets/{id}
            dataset_id = path_parts[1]

            if len(path_parts) == 2:
                if method == 'GET':
                    return self._get_dataset(dataset_id)
                elif method == 'PUT':
                    return self._update_dataset(req, dataset_id)
                elif method == 'DELETE':
                    return self._delete_dataset(req, dataset_id)
                else:
                    return self._error_response(f"Method {method} not allowed", 405)

            # /api/curated/datasets/{id}/{action}
            action = path_parts[2]

            if action == 'update' and method == 'POST':
                return self._trigger_update(req, dataset_id)
            elif action == 'history' and method == 'GET':
                return self._get_history(req, dataset_id)
            elif action == 'enable' and method == 'POST':
                return self._enable_dataset(dataset_id)
            elif action == 'disable' and method == 'POST':
                return self._disable_dataset(dataset_id)
            else:
                return self._error_response(f"Unknown action: {action}", 404)

        except Exception as e:
            logger.error(f"Error in CuratedAdminTrigger: {e}")
            logger.error(traceback.format_exc())
            return self._error_response(str(e), 500)

    def _list_datasets(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all curated datasets.

        GET /api/curated/datasets?enabled_only=true

        Query Parameters:
            enabled_only: If "true", only return enabled datasets
        """
        logger.info("Listing curated datasets")

        enabled_only = req.params.get('enabled_only', '').lower() == 'true'
        datasets = self.service.list_datasets(enabled_only=enabled_only)

        result = {
            'datasets': [self.service.to_dict(d) for d in datasets],
            'total': len(datasets),
            'enabled_only': enabled_only,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        logger.info(f"Found {len(datasets)} curated datasets")

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _get_dataset(self, dataset_id: str) -> func.HttpResponse:
        """
        Get a curated dataset by ID.

        GET /api/curated/datasets/{id}
        """
        logger.info(f"Getting curated dataset: {dataset_id}")

        dataset = self.service.get_dataset(dataset_id)

        if not dataset:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        result = {
            'dataset': self.service.to_dict(dataset),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _create_dataset(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Create a new curated dataset.

        POST /api/curated/datasets
        Body: JSON with dataset fields
        """
        logger.info("Creating curated dataset")

        try:
            body = parse_request_json(req)
        except ValueError:
            return self._error_response("Invalid JSON body", 400)

        # Validate required fields
        required = ['dataset_id', 'name', 'source_type', 'source_url',
                    'job_type', 'update_strategy', 'target_table_name']
        missing = [f for f in required if f not in body]
        if missing:
            return self._error_response(f"Missing required fields: {missing}", 400)

        try:
            # Parse enums
            source_type = CuratedSourceType(body['source_type'])
            update_strategy = CuratedUpdateStrategy(body['update_strategy'])

            # Create dataset model
            dataset = CuratedDataset(
                dataset_id=body['dataset_id'],
                name=body['name'],
                description=body.get('description'),
                source_type=source_type,
                source_url=body['source_url'],
                source_config=body.get('source_config', {}),
                job_type=body['job_type'],
                update_strategy=update_strategy,
                update_schedule=body.get('update_schedule'),
                credential_key=body.get('credential_key'),
                target_table_name=body['target_table_name'],
                target_schema=body.get('target_schema', 'geo'),
                enabled=body.get('enabled', True)
            )

            created = self.service.create_dataset(dataset)

            result = {
                'message': 'Dataset created successfully',
                'dataset': self.service.to_dict(created),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"Created curated dataset: {created.dataset_id}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=201,
                mimetype='application/json'
            )

        except ValueError as e:
            return self._error_response(str(e), 400)

    def _update_dataset(self, req: func.HttpRequest, dataset_id: str) -> func.HttpResponse:
        """
        Update a curated dataset.

        PUT /api/curated/datasets/{id}
        Body: JSON with fields to update
        """
        logger.info(f"Updating curated dataset: {dataset_id}")

        try:
            body = parse_request_json(req)
        except ValueError:
            return self._error_response("Invalid JSON body", 400)

        if not body:
            return self._error_response("Empty update body", 400)

        # Convert string enum values to enum objects
        if 'source_type' in body:
            try:
                body['source_type'] = CuratedSourceType(body['source_type'])
            except ValueError as e:
                return self._error_response(f"Invalid source_type: {e}", 400)

        if 'update_strategy' in body:
            try:
                body['update_strategy'] = CuratedUpdateStrategy(body['update_strategy'])
            except ValueError as e:
                return self._error_response(f"Invalid update_strategy: {e}", 400)

        try:
            updated = self.service.update_dataset(dataset_id, body)

            if not updated:
                return self._error_response(f"Dataset not found: {dataset_id}", 404)

            result = {
                'message': 'Dataset updated successfully',
                'dataset': self.service.to_dict(updated),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"Updated curated dataset: {dataset_id}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ValueError as e:
            return self._error_response(str(e), 400)

    def _delete_dataset(self, req: func.HttpRequest, dataset_id: str) -> func.HttpResponse:
        """
        Delete a curated dataset registry entry.

        DELETE /api/curated/datasets/{id}?confirm=yes

        Query Parameters:
            confirm: Must be "yes" to confirm deletion
        """
        logger.warning(f"Delete request for curated dataset: {dataset_id}")

        confirm = req.params.get('confirm', '').lower()
        if confirm != 'yes':
            return self._error_response(
                "Deletion requires confirm=yes query parameter. "
                "Note: This only deletes the registry entry, not the data table.",
                400
            )

        deleted = self.service.delete_dataset(dataset_id)

        if not deleted:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        result = {
            'message': 'Dataset registry entry deleted',
            'dataset_id': dataset_id,
            'note': 'The actual data table was NOT deleted. Use database admin endpoints to drop the table.',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        logger.warning(f"Deleted curated dataset registry: {dataset_id}")

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _trigger_update(self, req: func.HttpRequest, dataset_id: str) -> func.HttpResponse:
        """
        Trigger a manual update for a curated dataset.

        POST /api/curated/datasets/{id}/update

        This will submit a CoreMachine job to update the dataset.
        """
        logger.info(f"Manual update triggered for: {dataset_id}")

        dataset = self.service.get_dataset(dataset_id)

        if not dataset:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        # TODO: Submit CoreMachine job (Phase 5)
        # For now, return a placeholder response

        result = {
            'message': 'Update job submission not yet implemented',
            'dataset_id': dataset_id,
            'job_type': dataset.job_type,
            'note': 'Phase 5 will implement CuratedDatasetUpdateJob',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=202,
            mimetype='application/json'
        )

    def _get_history(self, req: func.HttpRequest, dataset_id: str) -> func.HttpResponse:
        """
        Get update history for a curated dataset.

        GET /api/curated/datasets/{id}/history?limit=20

        Query Parameters:
            limit: Maximum entries to return (default: 20)
        """
        logger.info(f"Getting update history for: {dataset_id}")

        # Validate dataset exists
        dataset = self.service.get_dataset(dataset_id)
        if not dataset:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        limit_str = req.params.get('limit', '20')
        try:
            limit = min(int(limit_str), 100)  # Cap at 100
        except ValueError:
            limit = 20

        history = self.service.get_update_history(dataset_id, limit=limit)

        result = {
            'dataset_id': dataset_id,
            'history': [self.service.log_to_dict(log) for log in history],
            'total': len(history),
            'limit': limit,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _enable_dataset(self, dataset_id: str) -> func.HttpResponse:
        """Enable a curated dataset for scheduled updates."""
        logger.info(f"Enabling curated dataset: {dataset_id}")

        updated = self.service.enable_dataset(dataset_id)

        if not updated:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        result = {
            'message': 'Dataset enabled',
            'dataset': self.service.to_dict(updated),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _disable_dataset(self, dataset_id: str) -> func.HttpResponse:
        """Disable a curated dataset from scheduled updates."""
        logger.info(f"Disabling curated dataset: {dataset_id}")

        updated = self.service.disable_dataset(dataset_id)

        if not updated:
            return self._error_response(f"Dataset not found: {dataset_id}", 404)

        result = {
            'message': 'Dataset disabled',
            'dataset': self.service.to_dict(updated),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            body=json.dumps(result, indent=2),
            status_code=200,
            mimetype='application/json'
        )

    def _error_response(self, message: str, status_code: int) -> func.HttpResponse:
        """Create an error response."""
        return func.HttpResponse(
            body=json.dumps({
                'error': message,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }),
            status_code=status_code,
            mimetype='application/json'
        )


# Create singleton instance
curated_admin_trigger = CuratedAdminTrigger.instance()

__all__ = [
    'CuratedAdminTrigger',
    'curated_admin_trigger'
]
