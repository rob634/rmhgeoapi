# ============================================================================
# SYSTEM SNAPSHOT ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger - Admin endpoint for system configuration snapshots
# PURPOSE: HTTP endpoints for manual snapshot capture and drift queries
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: New file - part of system diagnostics enhancement
# ============================================================================
"""
System Snapshot Admin Trigger.

Blueprint providing HTTP endpoints for system configuration snapshot
management. Allows manual snapshot capture and drift history queries.

Endpoints:
    POST /api/admin/snapshot - Capture manual snapshot
    GET  /api/admin/snapshot - Get latest snapshot summary
    GET  /api/admin/snapshot/drift - Get drift history

Exports:
    bp: Blueprint with snapshot routes
    SnapshotAdminTrigger: Trigger class
    snapshot_admin_trigger: Singleton instance
"""

import json
import traceback
from datetime import datetime, timezone
from typing import Optional

import azure.functions as func
from azure.functions import Blueprint

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "SnapshotAdmin")

# Create Blueprint for snapshot admin endpoints
bp = Blueprint()


class SnapshotAdminTrigger:
    """
    Admin trigger for system snapshot operations.

    Provides HTTP endpoints for manual snapshot capture and
    drift history queries.

    Singleton pattern for consistent configuration.
    """

    _instance: Optional['SnapshotAdminTrigger'] = None

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

        logger.info("Initializing SnapshotAdminTrigger")
        self._initialized = True
        logger.info("SnapshotAdminTrigger initialized")

    @classmethod
    def instance(cls) -> 'SnapshotAdminTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def service(self):
        """Lazy initialization of snapshot service."""
        if not hasattr(self, '_service'):
            from services.snapshot_service import snapshot_service
            self._service = snapshot_service
        return self._service

    def handle_capture(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle POST /api/admin/snapshot - Capture manual snapshot.

        Query Parameters:
            notes: Optional notes to include with snapshot

        Returns:
            JSON with snapshot result
        """
        start_time = datetime.now(timezone.utc)
        logger.info("Manual snapshot capture requested")

        try:
            # Get optional notes from query or body
            notes = req.params.get('notes')
            if not notes:
                try:
                    body = req.get_json()
                    notes = body.get('notes') if body else None
                except ValueError:
                    pass

            # Capture snapshot
            result = self.service.capture_manual_snapshot(notes=notes)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            result["request_duration_seconds"] = round(duration, 3)

            status_code = 200 if result.get("success") else 500

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=status_code,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"Snapshot capture failed: {e}")
            logger.error(traceback.format_exc())

            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    def handle_get_latest(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle GET /api/admin/snapshot - Get latest snapshot summary.

        Returns:
            JSON with latest snapshot summary or null if none exists
        """
        logger.info("Latest snapshot requested")

        try:
            result = self.service.get_latest_snapshot()

            if result:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "snapshot": result
                    }, indent=2, default=str),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "snapshot": None,
                        "message": "No snapshots found"
                    }, indent=2),
                    status_code=200,
                    mimetype="application/json"
                )

        except Exception as e:
            logger.error(f"Get latest snapshot failed: {e}")
            logger.error(traceback.format_exc())

            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": str(e)
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    def handle_get_drift(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle GET /api/admin/snapshot/drift - Get drift history.

        Query Parameters:
            limit: Maximum records to return (default 50)

        Returns:
            JSON with list of snapshots where drift was detected
        """
        logger.info("Drift history requested")

        try:
            limit = int(req.params.get('limit', '50'))
            limit = min(limit, 500)  # Cap at 500

            drift_history = self.service.get_drift_history(limit=limit)

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "count": len(drift_history),
                    "drift_events": drift_history
                }, indent=2, default=str),
                status_code=200,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"Get drift history failed: {e}")
            logger.error(traceback.format_exc())

            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": str(e)
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )


# Singleton instance
snapshot_admin_trigger = SnapshotAdminTrigger.instance()


# ============================================================================
# BLUEPRINT ROUTES
# ============================================================================

@bp.route(
    route="system/snapshot",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def admin_snapshot_capture(req: func.HttpRequest) -> func.HttpResponse:
    """
    Capture a manual system configuration snapshot.

    POST /api/system/snapshot
    POST /api/system/snapshot?notes=Reason+for+snapshot

    Captures current system configuration including:
        - Network environment (VNet, DNS, ASE)
        - Instance information (worker config)
        - Platform configuration (SKU, region)
        - Config sources (env vs defaults)

    Compares against previous snapshot and reports drift if detected.

    Returns:
        200: {"success": true, "snapshot_id": 123, "has_drift": false, ...}
        500: {"success": false, "error": "..."}
    """
    return snapshot_admin_trigger.handle_capture(req)


@bp.route(
    route="system/snapshot",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def admin_snapshot_latest(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get the latest system configuration snapshot summary.

    GET /api/system/snapshot

    Returns summary of most recent snapshot including:
        - snapshot_id
        - captured_at
        - config_hash (truncated)
        - has_drift
        - environment_type

    Returns:
        200: {"success": true, "snapshot": {...}}
        200: {"success": true, "snapshot": null, "message": "No snapshots found"}
        500: {"success": false, "error": "..."}
    """
    return snapshot_admin_trigger.handle_get_latest(req)


@bp.route(
    route="system/snapshot/drift",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def admin_snapshot_drift(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get history of configuration drift events.

    GET /api/system/snapshot/drift
    GET /api/system/snapshot/drift?limit=100

    Returns list of snapshots where configuration drift was detected,
    including what changed from the previous snapshot.

    Query Parameters:
        limit: Maximum records to return (default 50, max 500)

    Returns:
        200: {"success": true, "count": N, "drift_events": [...]}
        500: {"success": false, "error": "..."}
    """
    return snapshot_admin_trigger.handle_get_drift(req)


__all__ = [
    'bp',
    'SnapshotAdminTrigger',
    'snapshot_admin_trigger'
]
