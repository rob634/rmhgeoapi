# ============================================================================
# EXTERNAL DATABASE ADMIN BLUEPRINT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Controller - Blueprint for /api/dbadmin/external/* routes
# PURPOSE: Initialize target databases with pgstac and geo schemas
# CREATED: 21 JAN 2026
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
External Database Administration Blueprint.

Provides endpoints for DevOps to initialize external databases with
pgstac and geo schemas using a temporary admin managed identity.

Routes:
    POST /api/dbadmin/external/initialize - Initialize external database
    POST /api/dbadmin/external/prereqs    - Check DBA prerequisites

Security:
    - These endpoints should be protected by RBAC/authentication
    - Only DevOps/admin users should have access
    - Admin UMI is temporary - revoked after setup

Usage:
    # Check prerequisites first
    curl -X POST ".../api/dbadmin/external/prereqs" \
        -H "Content-Type: application/json" \
        -d '{"target_host": "...", "target_database": "...", "admin_umi_client_id": "...", "admin_umi_name": "..."}'

    # Dry run
    curl -X POST ".../api/dbadmin/external/initialize" \
        -H "Content-Type: application/json" \
        -d '{
            "target_host": "external-db.postgres.database.azure.com",
            "target_database": "geodb",
            "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "dry_run": true
        }'

    # Actual execution
    curl -X POST ".../api/dbadmin/external/initialize" \
        -H "Content-Type: application/json" \
        -d '{
            "target_host": "external-db.postgres.database.azure.com",
            "target_database": "geodb",
            "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "dry_run": false
        }'
"""

import json
import os
import uuid
import azure.functions as func
from azure.functions import Blueprint
from typing import Optional

from util_logger import LoggerFactory, ComponentType
from triggers.http_base import parse_request_json

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "AdminExternalDb")

bp = Blueprint()


@bp.route(route="dbadmin/external/initialize", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def external_db_initialize(req: func.HttpRequest) -> func.HttpResponse:
    """
    Initialize external database with pgstac and geo schemas.

    POST /api/dbadmin/external/initialize

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
            body = parse_request_json(req)
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
        drop_existing = body.get("drop_existing", False)
        schemas = body.get("schemas", ["geo", "pgstac"])

        # Host allowlist check (13 MAR 2026 - COMPETE security fix)
        allowed_hosts_str = os.environ.get("EXTERNAL_DB_ALLOWED_HOSTS", "")
        if allowed_hosts_str:
            allowed_hosts = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]
            if target_host not in allowed_hosts:
                return func.HttpResponse(
                    json.dumps({
                        "error": "target_host not in allowed hosts",
                        "hint": "Set EXTERNAL_DB_ALLOWED_HOSTS env var with comma-separated allowed hostnames"
                    }),
                    status_code=403,
                    mimetype="application/json"
                )

        logger.info(f"📦 External DB initialization request")
        logger.info(f"   Target: {target_host}/{target_database}")
        logger.info(f"   Admin UMI: {admin_umi_client_id[:8]}... ({admin_umi_name})")
        logger.info(f"   Dry run: {dry_run}, Drop existing: {drop_existing}")
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
        result = initializer.initialize(
            dry_run=dry_run,
            schemas=schemas,
            drop_existing=drop_existing
        )

        # Return result
        status_code = 200 if result.success else 500

        return func.HttpResponse(
            json.dumps(result.to_dict(), indent=2, default=str),
            status_code=status_code,
            mimetype="application/json"
        )

    except Exception as e:
        correlation_id = str(uuid.uuid4())
        logger.error(f"❌ External DB initialization failed (correlation_id={correlation_id}): {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "External DB initialization failed",
                "correlation_id": correlation_id
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(route="dbadmin/external/prereqs", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def external_db_prereqs(req: func.HttpRequest) -> func.HttpResponse:
    """
    Check DBA prerequisites for external database initialization.

    POST /api/dbadmin/external/prereqs

    Request body:
    {
        "target_host": "external-db.postgres.database.azure.com",
        "target_database": "geodb",
        "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "admin_umi_name": "external-db-admin-umi"
    }

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
        # Parse request body
        try:
            body = parse_request_json(req)
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

        # Host allowlist check (13 MAR 2026 - COMPETE security fix)
        allowed_hosts_str = os.environ.get("EXTERNAL_DB_ALLOWED_HOSTS", "")
        if allowed_hosts_str:
            allowed_hosts = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]
            if target_host not in allowed_hosts:
                return func.HttpResponse(
                    json.dumps({
                        "error": "target_host not in allowed hosts",
                        "hint": "Set EXTERNAL_DB_ALLOWED_HOSTS env var with comma-separated allowed hostnames"
                    }),
                    status_code=403,
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
        correlation_id = str(uuid.uuid4())
        logger.error(f"❌ Prerequisite check failed (correlation_id={correlation_id}): {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Prerequisite check failed",
                "correlation_id": correlation_id
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )
