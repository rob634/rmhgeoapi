# ============================================================================
# EXTERNAL DATABASE ADMIN BLUEPRINT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Controller - Blueprint for /api/admin/external/* routes
# PURPOSE: Initialize target databases with pgstac and geo schemas
# CREATED: 21 JAN 2026
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
External Database Administration Blueprint.

Provides endpoints for DevOps to initialize external databases with
pgstac and geo schemas using a temporary admin managed identity.

Routes:
    POST /api/admin/external/initialize - Initialize external database
    GET  /api/admin/external/prereqs    - Check DBA prerequisites

Security:
    - These endpoints should be protected by RBAC/authentication
    - Only DevOps/admin users should have access
    - Admin UMI is temporary - revoked after setup

Usage:
    # Check prerequisites first
    curl -X GET ".../api/admin/external/prereqs?target_host=...&target_database=...&admin_umi_client_id=..."

    # Dry run
    curl -X POST ".../api/admin/external/initialize" \
        -H "Content-Type: application/json" \
        -d '{
            "target_host": "external-db.postgres.database.azure.com",
            "target_database": "geodb",
            "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "dry_run": true
        }'

    # Actual execution
    curl -X POST ".../api/admin/external/initialize" \
        -H "Content-Type: application/json" \
        -d '{
            "target_host": "external-db.postgres.database.azure.com",
            "target_database": "geodb",
            "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "dry_run": false
        }'
"""

import json
import azure.functions as func
from azure.functions import Blueprint
from typing import Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "AdminExternalDb")

bp = Blueprint()


@bp.route(route="admin/external/initialize", methods=["POST"])
def external_db_initialize(req: func.HttpRequest) -> func.HttpResponse:
    """
    Initialize external database with pgstac and geo schemas.

    POST /api/admin/external/initialize

    Request body:
    {
        "target_host": "external-db.postgres.database.azure.com",
        "target_database": "geodb",
        "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "admin_umi_name": "external-db-admin-umi",  // Required: UMI display name (PostgreSQL username)
        "dry_run": false,  // Optional: default false
        "schemas": ["geo", "pgstac"]  // Optional: default both
    }

    Response:
    {
        "success": true,
        "target_host": "...",
        "target_database": "...",
        "steps": [...],
        "summary": {...}
    }
    """
    try:
        # Parse request body
        try:
            body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({
                    "error": "Invalid JSON body",
                    "hint": "Request body must be valid JSON"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Validate required fields
        required_fields = ["target_host", "target_database", "admin_umi_client_id", "admin_umi_name"]
        missing = [f for f in required_fields if not body.get(f)]
        if missing:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Missing required fields: {missing}",
                    "required": required_fields,
                    "received": list(body.keys())
                }),
                status_code=400,
                mimetype="application/json"
            )

        target_host = body["target_host"]
        target_database = body["target_database"]
        admin_umi_client_id = body["admin_umi_client_id"]
        admin_umi_name = body["admin_umi_name"]
        dry_run = body.get("dry_run", False)
        schemas = body.get("schemas", ["geo", "pgstac"])

        logger.info(f"📦 External DB initialization request")
        logger.info(f"   Target: {target_host}/{target_database}")
        logger.info(f"   Admin UMI: {admin_umi_client_id[:8]}... ({admin_umi_name})")
        logger.info(f"   Dry run: {dry_run}")
        logger.info(f"   Schemas: {schemas}")

        # Create initializer
        from services.external_db_initializer import ExternalDatabaseInitializer

        initializer = ExternalDatabaseInitializer(
            target_host=target_host,
            target_database=target_database,
            admin_umi_client_id=admin_umi_client_id,
            admin_umi_name=admin_umi_name
        )

        # Run initialization
        result = initializer.initialize(dry_run=dry_run, schemas=schemas)

        # Return result
        status_code = 200 if result.success else 500

        return func.HttpResponse(
            json.dumps(result.to_dict(), indent=2, default=str),
            status_code=status_code,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"❌ External DB initialization failed: {e}")
        import traceback
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(route="admin/external/prereqs", methods=["GET"])
def external_db_prereqs(req: func.HttpRequest) -> func.HttpResponse:
    """
    Check DBA prerequisites for external database initialization.

    GET /api/admin/external/prereqs?target_host=...&target_database=...&admin_umi_client_id=...

    Query parameters:
        target_host: External database hostname
        target_database: External database name
        admin_umi_client_id: Client ID of admin UMI

    Response:
    {
        "ready": true/false,
        "checks": {
            "connection": true,
            "postgis_extension": true,
            "role_pgstac_admin": true,
            ...
        },
        "missing": [...],
        "dba_sql": [...]
    }
    """
    try:
        # Get query parameters
        target_host = req.params.get("target_host")
        target_database = req.params.get("target_database")
        admin_umi_client_id = req.params.get("admin_umi_client_id")
        admin_umi_name = req.params.get("admin_umi_name")

        # Validate required params
        if not all([target_host, target_database, admin_umi_client_id, admin_umi_name]):
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required query parameters",
                    "required": ["target_host", "target_database", "admin_umi_client_id", "admin_umi_name"],
                    "received": {
                        "target_host": bool(target_host),
                        "target_database": bool(target_database),
                        "admin_umi_client_id": bool(admin_umi_client_id),
                        "admin_umi_name": bool(admin_umi_name)
                    }
                }),
                status_code=400,
                mimetype="application/json"
            )

        logger.info(f"🔍 Checking prerequisites for {target_host}/{target_database}")

        # Create initializer
        from services.external_db_initializer import ExternalDatabaseInitializer

        initializer = ExternalDatabaseInitializer(
            target_host=target_host,
            target_database=target_database,
            admin_umi_client_id=admin_umi_client_id,
            admin_umi_name=admin_umi_name
        )

        # Check prerequisites
        prereqs = initializer.check_prerequisites()

        return func.HttpResponse(
            json.dumps(prereqs, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"❌ Prerequisite check failed: {e}")
        import traceback
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )
