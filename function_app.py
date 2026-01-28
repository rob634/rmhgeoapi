# ============================================================================
# AZURE FUNCTIONS ENTRY POINT
# ============================================================================
# STATUS: Core - Main application entry point
# PURPOSE: HTTP endpoints, Service Bus triggers, and CoreMachine orchestration
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 in CLAUDE.md deployment guide)
# ============================================================================
"""
Azure Functions entry point for Geospatial ETL Pipeline.

This module serves as the entry point for the Azure Functions-based geospatial
ETL pipeline. It provides HTTP endpoints for job submission and status checking,
queue-based asynchronous processing, and comprehensive health monitoring.

Architecture:
    HTTP API or Service Bus -> CoreMachine -> Workflow -> Tasks -> Service Bus
                                   |              |                    |
                              Job Record    Pydantic Validation    Task Records
                          (PostgreSQL)      (Strong Typing)    (Service Layer Execution)
                                                                        |
                                                               Storage/Database/STAC
                                                           (PostgreSQL/PostGIS/Blob)

Job -> Stage -> Task Pattern:
    - CoreMachine: Universal orchestrator (composition over inheritance)
    - Declarative workflow and task handler registration
    - Sequential stages with parallel tasks within each stage
    - Data-Behavior Separation: TaskData/JobData (data) + TaskExecutor/Workflow (behavior)
    - "Last task turns out the lights" completion pattern
    - Strong typing discipline with explicit error handling

Key Features:
    - Pydantic-based workflow definitions with strong typing discipline
    - Job->Task architecture with controller pattern
    - Idempotent job processing with SHA256-based deduplication
    - Service Bus async processing with dead-letter queue handling
    - Managed identity authentication with user delegation SAS
    - Support for files up to 20GB with smart metadata extraction
    - Comprehensive STAC cataloging with PostGIS integration

Exports:
    app: Azure Function App instance
    core_machine: CoreMachine orchestrator instance

Dependencies:
    azure.functions: Azure Functions SDK
    triggers/*: HTTP and queue trigger implementations
    core.machine: CoreMachine orchestrator
    infrastructure.*: Repository implementations

Endpoints:
    Core System:
        GET  /api/health - System health check with component status

    CoreMachine Layer:
        POST /api/jobs/submit/{job_type} - Submit processing job
        GET  /api/jobs/status/{job_id} - Get job status and results

    Platform Layer:
        POST /api/platform/submit - Submit Platform API request
        GET  /api/platform/status/{request_id} - Get Platform request status
        GET  /api/platform/health - Simplified system readiness (F7.12)
        GET  /api/platform/failures - Recent failures with sanitized errors (F7.12)
        GET  /api/platform/lineage/{request_id} - Data lineage trace (F7.12)
        POST /api/platform/validate - Pre-flight validation (F7.12)

    STAC API v1.0.0:
        GET  /api/stac_api - STAC landing page
        GET  /api/stac_api/conformance - STAC conformance classes
        GET  /api/stac_api/collections - STAC collections list
        GET  /api/stac_api/collections/{collection_id} - STAC collection detail
        GET  /api/stac_api/collections/{collection_id}/items - STAC items (paginated)
        GET  /api/stac_api/collections/{collection_id}/items/{item_id} - STAC item detail

    Database Queries (DEV/TEST):
        GET  /api/dbadmin/jobs?status=failed&limit=10 - Query jobs
        GET  /api/dbadmin/tasks/{job_id} - Query tasks for job
        GET  /api/dbadmin/stats - Database statistics

    Schema Management (DEV ONLY):
        POST /api/dbadmin/maintenance?action=rebuild&confirm=yes - Atomic schema rebuild (both app+pgstac)

    Geo Schema Management (DEV ONLY):
        GET  /api/dbadmin/geo/tables - List geo tables with tracking status
        GET  /api/dbadmin/geo/metadata - List geo.table_metadata records
        GET  /api/dbadmin/geo/orphans - Check for orphaned tables/metadata
        POST /api/dbadmin/geo/unpublish?table_name={name}&confirm=yes - Cascade delete table

Processing Pattern:
    1. HTTP Request Processing:
       - HTTP request triggers workflow definition validation
       - Controller creates job record and stages based on workflow definition
       - Each stage creates parallel tasks with parameter validation
       - Job queued to geospatial-jobs queue for asynchronous processing

    2. Queue-Based Task Execution (V0.8 - 26 JAN 2026):
       - geospatial-jobs queue: Job messages and stage_complete signals
       - functionapp-tasks queue: Lightweight operations (DB, STAC, inventory)
       - container-tasks queue: Heavy operations (GDAL, geopandas) - Docker worker
       - Tasks processed independently with strong typing discipline
       - Last completing task aggregates results into job result_data
       - All task types MUST be mapped in TaskRoutingDefaults (no fallback)

Environment Variables:
    STORAGE_ACCOUNT_NAME: Azure storage account name
    AzureWebJobsStorage: Connection string for Functions runtime
    ENABLE_DATABASE_CHECK: Enable PostgreSQL health checks (optional)
    POSTGIS_HOST: PostgreSQL host for STAC catalog
    POSTGIS_DATABASE: PostgreSQL database name
    POSTGIS_USER: PostgreSQL username
    POSTGIS_PASSWORD: PostgreSQL password
"""

# ========================================================================
# IMPORTS - Categorized by source for maintainability
# ========================================================================

# Native Python modules
import logging
import json
import os
import traceback
import uuid
import time
from datetime import datetime, timezone

# Azure SDK modules (3rd party - Microsoft)
import azure.functions as func

# Suppress Azure Identity and Azure SDK authentication/HTTP logging
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._internal").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.storage").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("msal").setLevel(logging.WARNING)  # Microsoft Authentication Library

# ============================================================================
# PHASE 1: PROBE ENDPOINTS (03 JAN 2026 - STARTUP_REFORM.md)
# ============================================================================
# Register Kubernetes-style health probes FIRST, before any validation.
# This ensures /api/livez and /api/readyz are ALWAYS available, even when
# startup validation fails. Enables diagnostics in VNet/ASE environments.
#
# See STARTUP_REFORM.md for full design documentation.
# ============================================================================

# Initialize function app EARLY - before any imports that might fail
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Import startup state (zero dependencies) and register probes IMMEDIATELY
from startup_state import STARTUP_STATE, ValidationResult
from triggers.probes import bp as probes_bp

# Register probes BEFORE any validation - they must always be available
app.register_functions(probes_bp)

_startup_logger = logging.getLogger("startup")
_startup_logger.info("✅ STARTUP: Phase 1 complete - Probe endpoints registered (/api/livez, /api/readyz)")

# ============================================================================
# PHASE 2: SOFT VALIDATION (Store errors, don't crash)
# ============================================================================
# All validation is wrapped in try/except. Results are stored in STARTUP_STATE
# for the readyz and health endpoints to report. The app continues even if
# validation fails - but Service Bus triggers are only registered if all pass.
# ============================================================================

_startup_logger.info("🔍 STARTUP: Phase 2 - Running soft validation...")

# --- IMPORT VALIDATION ---
# Validate that critical modules can be imported
_startup_logger.info("🔍 STARTUP: Checking import validation...")
try:
    from utils import validator
    validator.ensure_startup_ready()
    STARTUP_STATE.imports = ValidationResult(
        name="imports",
        passed=True,
        details={"message": "All critical imports successful"}
    )
    _startup_logger.info("✅ STARTUP: Import validation passed")
except Exception as _import_error:
    STARTUP_STATE.imports = ValidationResult(
        name="imports",
        passed=False,
        error_type="IMPORT_FAILED",
        error_message=str(_import_error),
        details={
            "exception_type": type(_import_error).__name__,
            "likely_causes": [
                "Missing Python package in requirements.txt",
                "Circular import issue",
                "Incompatible package version"
            ]
        }
    )
    _startup_logger.critical(f"❌ STARTUP: Import validation failed: {_import_error}")

# ========================================================================
# APPLICATION IMPORTS - Our modules (validated at startup)
# ========================================================================

# --- ENV VAR VALIDATION (08 JAN 2026 - Regex-based format validation) ---
# Check env vars with REGEX PATTERNS to catch format errors, not just missing vars.
# Example: SERVICE_BUS_FQDN must end in .servicebus.windows.net
# This ensures errors are LOGGED to Application Insights before the app fails.
# Goal: "If app 404s, check Application Insights for STARTUP_FAILED"
_startup_logger.info("🔍 STARTUP: Validating environment variables (format + presence)...")

try:
    from config.env_validation import validate_environment, get_validation_summary

    _validation_results = validate_environment()

    # Separate actual errors from warnings (12 JAN 2026)
    _validation_errors = [e for e in _validation_results if e.severity == "error"]
    _validation_warnings = [w for w in _validation_results if w.severity == "warning"]

    if _validation_errors:
        # Build detailed error message for actual errors only
        _error_details = []
        for err in _validation_errors:
            _error_details.append(f"  - {err.var_name}: {err.message}")
            if err.current_value and "MASKED" not in str(err.current_value):
                _error_details.append(f"    Current: '{err.current_value}'")
            _error_details.append(f"    Expected: {err.expected_pattern}")
            _error_details.append(f"    Fix: {err.fix_suggestion}")

        _error_msg = f"Environment variable validation failed ({len(_validation_errors)} errors):\n" + "\n".join(_error_details)

        STARTUP_STATE.env_vars = ValidationResult(
            name="env_vars",
            passed=False,
            error_type="ENV_VALIDATION_FAILED",
            error_message=f"{len(_validation_errors)} environment variable(s) invalid",
            details={
                "errors": [e.to_dict() for e in _validation_errors],
                "warnings": [w.to_dict() for w in _validation_warnings],
                "fix": "Review the errors above and update environment variables via Azure Portal → Function App → Configuration"
            }
        )
        _startup_logger.critical(f"❌ STARTUP: {_error_msg}")
    else:
        # No errors - validation passed (warnings are OK)
        _summary = get_validation_summary()
        STARTUP_STATE.env_vars = ValidationResult(
            name="env_vars",
            passed=True,
            details={
                "message": "All environment variables validated successfully",
                "required_vars_checked": _summary["required_vars"]["total"],
                "warning_count": len(_validation_warnings),
                "warnings": [w.to_dict() for w in _validation_warnings] if _validation_warnings else None,
                "all_vars_validated": True
            }
        )
        if _validation_warnings:
            _startup_logger.info(f"✅ STARTUP: Env vars validated ({_summary['required_vars']['total']} required, {len(_validation_warnings)} warnings for optional vars using defaults)")
        else:
            _startup_logger.info(f"✅ STARTUP: All environment variables validated ({_summary['required_vars']['total']} required vars checked)")

except ImportError as _import_err:
    # Fallback to basic check if validation module not found
    _startup_logger.warning(f"⚠️ STARTUP: env_validation module not found, using basic check: {_import_err}")
    _basic_required = ["POSTGIS_HOST", "POSTGIS_DATABASE", "POSTGIS_SCHEMA", "APP_SCHEMA", "PGSTAC_SCHEMA", "H3_SCHEMA"]
    _missing = [v for v in _basic_required if not os.environ.get(v)]
    if _missing:
        STARTUP_STATE.env_vars = ValidationResult(
            name="env_vars",
            passed=False,
            error_type="MISSING_ENV_VARS",
            error_message=f"Missing: {', '.join(_missing)}",
            details={"missing": _missing}
        )
        _startup_logger.critical(f"❌ STARTUP: Missing env vars: {', '.join(_missing)}")
    else:
        STARTUP_STATE.env_vars = ValidationResult(name="env_vars", passed=True)
        _startup_logger.info("✅ STARTUP: Basic env var check passed")

# ========================================================================
# EXPLICIT REGISTRIES - Epoch 4 (NO DECORATORS!)
# ========================================================================
# All jobs and handlers registered explicitly here at module level.
# No decorators, no auto-discovery, no import timing issues.
# Reference: Historical import timing failures (10 SEP 2025)
# ========================================================================
from jobs import ALL_JOBS, get_job_class
from services import ALL_HANDLERS, get_handler

# Application modules (our code) - Core schemas and logging
from core.schema.queue import JobQueueMessage, TaskQueueMessage
from core.models import JobStatus, TaskStatus
from core.schema.updates import TaskUpdateModel
from util_logger import LoggerFactory
from util_logger import ComponentType
from infrastructure import RepositoryFactory
from infrastructure import PostgreSQLRepository
from pydantic import ValidationError
import re
from typing import Optional

# App Mode Configuration (07 DEC 2025 - Multi-Function App Architecture)
# Evaluated at module load time to control which Service Bus triggers are registered
from config import get_app_mode_config, get_config
_app_mode = get_app_mode_config()

# CoreMachine - Universal orchestrator (Epoch 4)
# NOTE: CoreMachine import moved to core/machine_factory.py (APP_CLEANUP Phase 4)
# The factory function handles the import internally

# Import service modules - no longer needed for registration (Phase 4 complete)
# Services are now explicitly registered in initialize_catalogs()
# Auto-discovery no longer needed since we use explicit registration

# Auto-discover is deprecated after Phase 4 migration
# from task_factory import auto_discover_handlers
# auto_discover_handlers()

# Application modules (our code) - HTTP Trigger Classes
# Import directly from modules to control when instances are created
# NOTE: health_check_trigger moved to admin_system blueprint (12 JAN 2026)
# NOTE: livez is now provided by triggers/probes.py (registered in Phase 1)
from triggers.submit_job import submit_job_trigger
from triggers.get_job_status import get_job_status_trigger
from triggers.get_job_events import get_job_events_trigger  # Job event timeline (23 JAN 2026)
from triggers.get_job_logs import get_job_logs_trigger
from triggers.jobs.resubmit import job_resubmit
from triggers.jobs.delete import job_delete
from triggers.schema_pydantic_deploy import pydantic_deploy_trigger
# ⚠️ LEGACY IMPORTS - DEPRECATED (10 NOV 2025) - COMMENTED OUT 16 NOV 2025
# These imports are kept temporarily for backward compatibility
# All functionality has been migrated to triggers/admin/
# File triggers/db_query.py has been deleted - routes no longer needed
# from triggers.db_query import (
#     schema_nuke_trigger  # Still used temporarily by db_maintenance.py
# )

from triggers.analyze_container import analyze_container_trigger
# NOTE: All STAC triggers moved to triggers/stac/stac_bp.py (24 JAN 2026 - V0.8 Phase 17.3)
# stac_extract_trigger and stac_vector_trigger now called from blueprint

# STAC Blueprint - Unified STAC API & Admin (24 JAN 2026 - V0.8 Phase 17.3)
# All 19 stac/* endpoints now in triggers/stac/stac_bp.py

# ingest_vector REMOVED (27 NOV 2025) - Platform now uses process_vector
# test_raster_create excluded by funcignore (30 NOV 2025) - *test* files not deployed
# from triggers.test_raster_create import test_raster_create_trigger

# Admin API triggers (10 NOV 2025) - Consolidated under /api/admin/*
from triggers.admin.db_schemas import admin_db_schemas_trigger
from triggers.admin.db_tables import admin_db_tables_trigger
from triggers.admin.db_queries import admin_db_queries_trigger
from triggers.admin.db_health import admin_db_health_trigger
from triggers.admin.db_maintenance import admin_db_maintenance_trigger
from triggers.admin.db_data import admin_db_data_trigger
from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
from triggers.admin.servicebus import servicebus_admin_trigger
# NOTE: H3 admin triggers (h3_debug, h3_datasets) moved to admin_h3 blueprint (12 JAN 2026)

# Curated Dataset Admin (15 DEC 2025) - System-managed geospatial data
from triggers.curated.admin import curated_admin_trigger
# curated_scheduler_trigger import removed (23 JAN 2026 - APP_CLEANUP Phase 3)
# Timer trigger now in triggers/timers/timer_bp.py blueprint

# Platform Service Layer triggers moved to blueprint (23 JAN 2026 - APP_CLEANUP Phase 5)
# triggers/platform/platform_bp.py now contains all 17 platform endpoints
# Registered conditionally via app.register_functions(platform_bp) below

# OGC Features API - Standalone module (29 OCT 2025)
from ogc_features import get_ogc_triggers

# STAC API - Moved to triggers/stac/ blueprint (24 JAN 2026)

# Vector Viewer - Standalone module (13 NOV 2025) - OGC Features API
from vector_viewer import get_vector_viewer_triggers

# Raster Collection Viewer - STAC-integrated raster viewer (30 DEC 2025) - F2.9
from raster_collection_viewer import get_raster_collection_viewer_triggers

# Raster API - Service Layer convenience wrappers for TiTiler (18 DEC 2025)
from raster_api import get_raster_triggers

# xarray API - Direct Zarr access for time-series (18 DEC 2025)
from xarray_api import get_xarray_triggers

# OGC Styles API - CartoSym-JSON style storage and multi-format output (18 DEC 2025)
from ogc_styles import get_styles_triggers

# Raster Render Configs API - TiTiler parameter storage (22 JAN 2026 - F2.11)
from triggers.trigger_raster_renders import (
    list_renders, get_render, get_default_render,
    create_render, update_render, delete_render,
    set_default_render, create_default_render
)

# Map State API - Saveable web map configurations (23 JAN 2026)
from triggers.trigger_map_states import (
    list_maps, get_map, create_map, update_map, delete_map,
    list_snapshots, get_snapshot, restore_snapshot
)

# Pipeline Dashboard - Container blob browser (21 NOV 2025) - Read-only UI operations
from triggers.list_container_blobs import list_container_blobs_handler
from triggers.get_blob_metadata import get_blob_metadata_handler
from triggers.list_storage_containers import list_storage_containers_handler
from triggers.storage_upload import storage_upload_handler

# Janitor handler imports removed (23 JAN 2026 - APP_CLEANUP Phase 3)
# Timer triggers now in triggers/timers/timer_bp.py blueprint

# ========================================================================
# PHASE 2: EXPLICIT REGISTRATION PATTERN (Parallel with decorators)
# ========================================================================
# During migration, both decorator-based and explicit registration work
# simultaneously. This allows gradual migration without breaking changes.

# ============================================================================
# EPOCH 3 REGISTRATION REMOVED (1 OCT 2025)
# ============================================================================
# Previous imports removed:
#   - from registration import JobCatalog, TaskCatalog
#   - from controller_factories import JobFactory
#   - from task_factory import TaskHandlerFactory
#   - from controller_hello_world import HelloWorldController
#   - from controller_container import SummarizeContainerController, ListContainerController
#   - from controller_stac_setup import STACSetupController
#   - from controller_service_bus_hello import ServiceBusHelloWorldController
#   - from controller_service_bus_container import ServiceBusContainerController
#
# Reason: Epoch 3 controllers deprecated, CoreMachine handles all orchestration
# Migration: Use Epoch 4 @register_job and @register_task decorators instead
# ============================================================================

# ========================================================================
# EPOCH 4: INITIALIZE COREMACHINE (Universal Orchestrator with Explicit Registries)
# ========================================================================
# CoreMachine replaces the God Class pattern with composition-based coordination
# It works with ALL jobs via EXPLICIT registries (no decorator magic)
#
# CRITICAL: We pass ALL_JOBS and ALL_HANDLERS explicitly to avoid import timing issues
# Previous decorator-based approach failed because modules weren't imported (10 SEP 2025)
# ========================================================================

# Initialize logger for CoreMachine initialization
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "function_app")

# ============================================================================
# COREMACHINE INITIALIZATION (23 JAN 2026 - APP_CLEANUP Phase 4)
# ============================================================================
# CoreMachine factory and callbacks moved to: core/machine_factory.py
#
# Features extracted:
#   - Platform orchestration callback (_default_platform_callback)
#   - STAC extraction helpers (extract_stac_item_id, etc.)
#   - Factory function (create_core_machine)
# ============================================================================

from core.machine_factory import create_core_machine

# Initialize CoreMachine at module level with EXPLICIT registries (reused across all triggers)
core_machine = create_core_machine(ALL_JOBS, ALL_HANDLERS)

# NOTE: app = func.FunctionApp() is now created at the TOP of the file (Phase 1)
# This ensures probe endpoints are registered BEFORE any validation runs.
# See STARTUP_REFORM.md for rationale.

# ============================================================================
# BLUEPRINT REGISTRATIONS (15 DEC 2025, updated 15 JAN 2026)
# ============================================================================
# Conditional registration based on APP_MODE (Gateway/Orchestrator separation)

# Admin blueprints - only for modes with admin endpoints
if _app_mode.has_admin_endpoints:
    from triggers.admin import admin_db_bp, admin_servicebus_bp, snapshot_bp
    from triggers.admin.admin_janitor import bp as admin_janitor_bp
    from triggers.stac import stac_bp  # Unified STAC blueprint (24 JAN 2026)
    from triggers.admin.admin_h3 import bp as admin_h3_bp
    from triggers.admin.admin_system import bp as admin_system_bp
    from triggers.admin.admin_approvals import bp as admin_approvals_bp  # Dataset approvals (16 JAN 2026)
    from triggers.admin.admin_external_db import bp as admin_external_db_bp  # External DB init (21 JAN 2026)
    from triggers.admin.admin_artifacts import bp as admin_artifacts_bp  # Artifact registry (22 JAN 2026)
    from triggers.admin.admin_external_services import bp as admin_external_services_bp  # External service registry (22 JAN 2026)
    from triggers.admin.admin_data_migration import bp as admin_data_migration_bp  # ADF data migration (22 JAN 2026)
    from web_interfaces.h3_sources import bp as h3_sources_bp

    app.register_functions(admin_db_bp)
    app.register_functions(admin_servicebus_bp)
    app.register_functions(admin_janitor_bp)
    app.register_functions(stac_bp)  # Unified STAC blueprint (24 JAN 2026)
    app.register_functions(admin_h3_bp)
    app.register_functions(admin_system_bp)
    app.register_functions(admin_approvals_bp)  # Dataset approvals (16 JAN 2026)
    app.register_functions(admin_external_db_bp)  # External DB init (21 JAN 2026)
    app.register_functions(admin_artifacts_bp)  # Artifact registry (22 JAN 2026)
    app.register_functions(admin_external_services_bp)  # External service registry (22 JAN 2026)
    app.register_functions(admin_data_migration_bp)  # ADF data migration (22 JAN 2026)
    app.register_functions(h3_sources_bp)
    app.register_functions(snapshot_bp)
    logger.info("✅ Admin blueprints registered (APP_MODE=%s)", _app_mode.mode.value)
else:
    logger.info("⏭️ SKIPPING admin blueprints (APP_MODE=%s)", _app_mode.mode.value)

# Platform blueprint - Anti-corruption layer for external apps (DDH)
# Contains all 17 platform endpoints (APP_CLEANUP Phase 5 - 23 JAN 2026)
if _app_mode.has_platform_endpoints:
    from triggers.platform import platform_bp
    app.register_functions(platform_bp)
    logger.info("✅ Platform blueprint registered (APP_MODE=%s)", _app_mode.mode.value)
else:
    logger.warning(
        "⚠️ Platform endpoints DISABLED (APP_MODE=%s). "
        "/api/platform/* endpoints (approve, approvals, submit) will return 404. "
        "To enable, set APP_MODE to standalone, platform, or orchestrator.",
        _app_mode.mode.value
    )


# NOTE: /api/health moved to triggers/admin/admin_system.py blueprint (12 JAN 2026)
# NOTE: /api/system/stats moved to triggers/admin/admin_system.py blueprint (12 JAN 2026)
# NOTE: /api/livez is registered in Phase 1 via triggers/probes.py


# ============================================================================
# DATABASE ADMIN + SERVICE BUS ENDPOINTS - MOVED TO BLUEPRINTS (15 DEC 2025)
# ============================================================================
# All dbadmin/* and servicebus/* routes moved to:
#   - routes/admin_db.py (19 routes)
#   - routes/admin_servicebus.py (2 routes)
# Registered via app.register_functions() above
# ============================================================================


# ============================================================================
# CURATED DATASET MANAGEMENT ENDPOINTS (15 DEC 2025)
# ============================================================================
# CRUD operations for curated (system-managed) datasets.
# These are official geospatial data sources that update automatically.
# Examples: WDPA, Admin0 boundaries, other authoritative sources.
# ============================================================================

@app.route(route="curated/datasets", methods=["GET", "POST"])
def curated_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """
    Curated datasets CRUD.

    GET /api/curated/datasets - List all curated datasets
    POST /api/curated/datasets - Create new dataset (body: JSON)
    """
    return curated_admin_trigger.handle_request(req)


@app.route(route="curated/datasets/{dataset_id}", methods=["GET", "PUT", "DELETE"])
def curated_dataset_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Single curated dataset operations.

    GET /api/curated/datasets/{id} - Get dataset
    PUT /api/curated/datasets/{id} - Update dataset
    DELETE /api/curated/datasets/{id}?confirm=yes - Delete registry entry
    """
    return curated_admin_trigger.handle_request(req)


# CONSOLIDATED (15 DEC 2025) - 4 action routes → 1 route
# Trigger routes internally based on action path segment
@app.route(route="curated/datasets/{dataset_id}/{action}", methods=["GET", "POST"])
def curated_dataset_action(req: func.HttpRequest) -> func.HttpResponse:
    """
    Consolidated curated dataset actions.

    Actions (via path):
        POST /api/curated/datasets/{id}/update  - Trigger manual update
        GET  /api/curated/datasets/{id}/history - Get update history
        POST /api/curated/datasets/{id}/enable  - Enable scheduled updates
        POST /api/curated/datasets/{id}/disable - Disable scheduled updates
    """
    return curated_admin_trigger.handle_request(req)


# ============================================================================
# END CURATED DATASET MANAGEMENT ENDPOINTS
# ============================================================================


# ============================================================================
# JOBS ENDPOINTS (conditional 15 JAN 2026)
# ============================================================================
# Only registered for modes with has_jobs_endpoints=True (orchestrator, standalone, platform_*)

def _jobs_endpoint_guard() -> Optional[func.HttpResponse]:
    """Return 404 response if jobs endpoints are disabled for this app mode."""
    if not _app_mode.has_jobs_endpoints:
        return func.HttpResponse(
            json.dumps({
                "error": "Jobs endpoints not available",
                "message": f"APP_MODE={_app_mode.mode.value} does not expose jobs/* endpoints",
                "hint": "Use orchestrator or standalone mode for jobs endpoints"
            }),
            status_code=404,
            mimetype="application/json"
        )
    return None


@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    if guard := _jobs_endpoint_guard():
        return guard
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/status/{job_id}", methods=["GET"])
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_status_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/events", methods=["GET"])
def get_job_events(req: func.HttpRequest) -> func.HttpResponse:
    """
    Job events timeline endpoint (23 JAN 2026).

    Returns execution events for job monitoring and debugging.
    Events are recorded by CoreMachine for both FunctionApp and Docker workers.

    Query params:
        - limit: Max events (default 50, max 500)
        - event_type: Filter by type (e.g., task_completed)
        - since: ISO timestamp to filter events after
        - include_task_events: Include task-level events (default true)
    """
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_events_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/events/latest", methods=["GET"])
def get_job_events_latest(req: func.HttpRequest) -> func.HttpResponse:
    """Get the most recent event for a job."""
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_events_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/events/summary", methods=["GET"])
def get_job_events_summary(req: func.HttpRequest) -> func.HttpResponse:
    """Get event summary statistics for a job."""
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_events_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/events/failure", methods=["GET"])
def get_job_events_failure(req: func.HttpRequest) -> func.HttpResponse:
    """Get failure context (failure event + preceding events) for debugging."""
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_events_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/logs", methods=["GET"])
def get_job_logs(req: func.HttpRequest) -> func.HttpResponse:
    """
    Job logs retrieval endpoint (12 JAN 2026).

    Fetches Application Insights logs filtered by job_id for display
    in workflow monitor.

    Query params:
        - level: Minimum level (DEBUG/INFO/WARNING/ERROR) - default INFO
        - limit: Max rows (default 100, max 500)
        - timespan: How far back (default PT24H)
        - component: Filter by component name
    """
    if guard := _jobs_endpoint_guard():
        return guard
    return get_job_logs_trigger.handle_request(req)


@app.route(route="jobs/{job_id}/resubmit", methods=["POST"])
def job_resubmit_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Job resubmit endpoint (12 JAN 2026).

    Performs "nuclear reset" - deletes all job artifacts and resubmits
    with the same parameters. Useful for failed/stuck jobs.

    Body params (all optional):
        - dry_run: Preview cleanup without executing (default: false)
        - delete_blobs: Also delete COG files (default: false)
        - force: Resubmit even if job is processing (default: false)
    """
    if guard := _jobs_endpoint_guard():
        return guard
    return job_resubmit(req)


@app.route(route="jobs/{job_id}", methods=["DELETE"])
def job_delete_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Job delete endpoint (14 JAN 2026).

    Deletes job and all artifacts without resubmitting.
    Same cleanup as resubmit but stops after cleanup.

    Query params:
        - confirm=yes (required): Explicit confirmation
        - dry_run=true: Preview cleanup without executing
        - delete_blobs=true: Also delete COG files
        - force=true: Delete even if job is processing
    """
    if guard := _jobs_endpoint_guard():
        return guard
    return job_delete(req)


# ============================================================================
# DATABASE ADMIN DATA/DIAGNOSTICS - MOVED TO BLUEPRINTS (15 DEC 2025)
# ============================================================================
# Routes moved to routes/admin_db.py:
#   - dbadmin/jobs, dbadmin/jobs/{job_id}
#   - dbadmin/tasks, dbadmin/tasks/{job_id}
#   - dbadmin/platform/requests, dbadmin/platform/requests/{request_id}
#   - dbadmin/platform/orchestration, dbadmin/platform/orchestration/{request_id}
#   - dbadmin/diagnostics?type={stats|enums|functions|all|config|errors|lineage}
# ============================================================================


# NOTE: H3 routes moved to triggers/admin/admin_h3.py blueprint (12 JAN 2026)
# - /api/h3/debug
# - /api/h3/datasets
# - /api/h3/admin/stats


# NOTE: Data Migration routes moved to triggers/admin/admin_data_migration.py blueprint (22 JAN 2026)
# - /api/data-migration/trigger
# - /api/data-migration/status/{run_id}
# - /api/data-migration/cancel/{run_id}


# ============================================================================
# PROMOTE API - Dataset Promotion System (22 DEC 2025)
# ============================================================================
# These endpoints manage the promoted datasets system:
# - POST/GET /api/promote - Create promoted dataset or list all
# - GET/PUT/DELETE /api/promote/{promoted_id} - CRUD for specific dataset
# - POST/DELETE /api/promote/{promoted_id}/gallery - Gallery management
# - GET /api/promote/gallery - List gallery items
# - GET /api/promote/system - List system-reserved datasets (23 DEC 2025)

from triggers.promote import (
    handle_promote,
    handle_promote_item,
    handle_gallery,
    handle_gallery_list,
    handle_system_reserved
)


@app.route(route="promote", methods=["GET", "POST"])
def promote_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Promote a STAC collection/item or list all promoted datasets.

    POST /api/promote - Create promoted dataset
    GET /api/promote - List all promoted datasets
    """
    return handle_promote(req)


@app.route(route="promote/gallery", methods=["GET"])
def promote_gallery_list_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    List gallery items in display order: GET /api/promote/gallery
    """
    return handle_gallery_list(req)


@app.route(route="promote/system", methods=["GET"])
def promote_system_reserved_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    List system-reserved datasets: GET /api/promote/system

    Query Parameters:
        role: Filter by system_role (e.g., 'admin0_boundaries')
    """
    return handle_system_reserved(req)


@app.route(route="promote/{promoted_id}", methods=["GET", "PUT", "DELETE"])
def promote_item_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get, update, or demote a promoted dataset.

    GET /api/promote/{promoted_id} - Get details
    PUT /api/promote/{promoted_id} - Update
    DELETE /api/promote/{promoted_id}?confirm_system=true - Demote
    """
    return handle_promote_item(req)


@app.route(route="promote/{promoted_id}/gallery", methods=["POST", "DELETE"])
def promote_gallery_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Add or remove a promoted dataset from the gallery.

    POST /api/promote/{promoted_id}/gallery - Add to gallery
    DELETE /api/promote/{promoted_id}/gallery - Remove from gallery
    """
    return handle_gallery(req)


# 🚨 NUCLEAR RED BUTTON - DEVELOPMENT ONLY (⚠️ DEPRECATED - COMMENTED OUT 16 NOV 2025)
# Use /api/dbadmin/maintenance/nuke instead
# @app.route(route="db/schema/nuke", methods=["POST"])
# def nuclear_schema_reset(req: func.HttpRequest) -> func.HttpResponse:
#     """⚠️ DEPRECATED: Use /api/dbadmin/maintenance/nuke instead. POST /api/db/schema/nuke?confirm=yes"""
#     return admin_db_maintenance_trigger.handle_request(req)


# 🔄 CONSOLIDATED REBUILD - DEVELOPMENT ONLY (⚠️ DEPRECATED - COMMENTED OUT 16 NOV 2025)
# Use /api/dbadmin/maintenance/redeploy instead
# @app.route(route="db/schema/redeploy", methods=["POST"])
# def redeploy_schema(req: func.HttpRequest) -> func.HttpResponse:
#     """⚠️ DEPRECATED: Use /api/dbadmin/maintenance/redeploy instead. POST /api/db/schema/redeploy?confirm=yes"""
#     return admin_db_maintenance_trigger.handle_request(req)


# Note: Legacy inline redeploy code (150+ lines) has been removed (10 NOV 2025)
# It has been migrated to triggers/admin/db_maintenance.py AdminDbMaintenanceTrigger._redeploy_schema()
# Old routes /api/db/schema/nuke and /api/db/schema/redeploy commented out (16 NOV 2025)


# ============================================================================
# CONTAINER ANALYSIS ENDPOINT - Post-processing for list_container_contents jobs
# ============================================================================

@app.route(route="analysis/container/{job_id}", methods=["GET"])
def analyze_container(req: func.HttpRequest) -> func.HttpResponse:
    """
    Analyze a list_container_contents job: GET /api/analysis/container/{job_id}?save=true

    Provides comprehensive analysis of blob container contents including:
    - File categorization (vector, raster, metadata)
    - Pattern detection (Maxar orders, Vivid basemaps, etc.)
    - Duplicate file detection
    - Size distribution and statistics
    - Execution timing analysis

    Query Parameters:
        save: If 'true', saves results to inventory container (silver zone)
    """
    return analyze_container_trigger.handle_request(req)


@app.route(route="analysis/delivery", methods=["POST"])
def discover_delivery_structure(req: func.HttpRequest) -> func.HttpResponse:
    """
    Discover vendor delivery structure: POST /api/analysis/delivery

    Analyzes a folder to detect:
    - Manifest files (.MAN, .json, .xml, .til)
    - Tile patterns (R{row}C{col}, X{x}_Y{y})
    - Delivery type (Maxar, Vivid, simple folder)
    - Recommended processing workflow

    Request Body:
        {
            "blob_list": ["path/file1.tif", "path/file2.tif", ...],
            "folder_path": "optional/folder/path/"
        }

    Returns:
        {
            "delivery_type": "maxar_tiles" | "vivid_basemap" | "simple_folder",
            "manifest": {...},
            "tile_pattern": {...},
            "recommended_workflow": {...}
        }
    """
    from services.delivery_discovery import analyze_delivery_structure
    import json

    try:
        # Parse request body
        req_body = req.get_json()

        if not req_body or 'blob_list' not in req_body:
            return func.HttpResponse(
                json.dumps({"error": "blob_list required in request body"}),
                mimetype="application/json",
                status_code=400
            )

        blob_list = req_body['blob_list']
        folder_path = req_body.get('folder_path')

        # Analyze delivery structure
        result = analyze_delivery_structure(blob_list, folder_path)

        return func.HttpResponse(
            json.dumps(result, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        import traceback
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            }),
            mimetype="application/json",
            status_code=500
        )


# ============================================================================
# STAC API v1.0.0 PORTABLE MODULE (10 NOV 2025)
# ============================================================================
# Specification: https://api.stacspec.org/v1.0.0/core
# Portable module pattern - mirrors ogc_features/ architecture
# Can be moved to separate Function App for APIM routing
# ============================================================================

# ============================================================================
# STAC ENDPOINTS - MOVED TO BLUEPRINT (24 JAN 2026 - V0.8 Phase 17.3)
# ============================================================================
# All 19 stac/* endpoints consolidated into triggers/stac/stac_bp.py
# Blueprint registered conditionally above via: app.register_functions(stac_bp)
#
# Categories:
#   STAC API v1.0.0 Core (6): /stac, /stac/conformance, /stac/collections, etc.
#   Admin - Initialization (3): /stac/init, /stac/collections/{tier}, /stac/nuke
#   Admin - Repair (3): /stac/repair/test, /stac/repair/inventory, /stac/repair/item
#   Admin - Catalog Ops (2): /stac/extract, /stac/vector
#   Admin - Inspection (5): /stac/schema/info, /stac/collections/summary, etc.
# ============================================================================


# ============================================================================
# PLATFORM SERVICE LAYER ENDPOINTS - MOVED TO BLUEPRINT (23 JAN 2026)
# ============================================================================
# Platform orchestration layer moved to: triggers/platform/platform_bp.py
# All 17 platform endpoints registered via blueprint below.
# See APP_CLEANUP Phase 5 for details.
# ============================================================================




# NOTE: stac/vector moved to triggers/stac/stac_bp.py (24 JAN 2026)

# NOTE: pgstac inspection endpoints moved to triggers/stac/stac_bp.py (24 JAN 2026)



# ============================================================================
# OGC FEATURES API - Direct PostGIS Vector Access (29 OCT 2025)
# ============================================================================
# Standards-compliant OGC API - Features Core 1.0 implementation
# Provides direct feature-level querying with spatial/temporal/attribute filters
# Base: /api/features
# Documentation: ogc_features/README.md
#
# Endpoints (6 total):
#   GET  /api/features                              - Landing page
#   GET  /api/features/conformance                  - Conformance classes
#   GET  /api/features/collections                  - List collections
#   GET  /api/features/collections/{id}             - Collection metadata
#   GET  /api/features/collections/{id}/items       - Query features (main)
#   GET  /api/features/collections/{id}/items/{fid} - Single feature
#
# Query Parameters:
#   ?bbox=minx,miny,maxx,maxy  - Spatial filter
#   ?datetime=2024-01-01/..    - Temporal filter
#   ?limit=100                 - Pagination
#   ?sortby=+field,-field      - Sorting
#   ?simplify=100              - Geometry simplification (meters)
#   ?precision=6               - Coordinate precision (decimals)

# Get trigger configurations (contains handler references)
_ogc_triggers = get_ogc_triggers()
_ogc_landing = _ogc_triggers[0]['handler']
_ogc_conformance = _ogc_triggers[1]['handler']
_ogc_collections = _ogc_triggers[2]['handler']
_ogc_collection = _ogc_triggers[3]['handler']
_ogc_items = _ogc_triggers[4]['handler']
_ogc_feature = _ogc_triggers[5]['handler']


@app.route(route="features", methods=["GET"])
def ogc_features_landing(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features API landing page: GET /api/features"""
    return _ogc_landing(req)


@app.route(route="features/conformance", methods=["GET"])
def ogc_features_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features conformance: GET /api/features/conformance"""
    return _ogc_conformance(req)


@app.route(route="features/collections", methods=["GET"])
def ogc_features_collections(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features collections list: GET /api/features/collections"""
    return _ogc_collections(req)


@app.route(route="features/collections/{collection_id}", methods=["GET"])
def ogc_features_collection(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features collection metadata: GET /api/features/collections/{collection_id}"""
    return _ogc_collection(req)


@app.route(route="features/collections/{collection_id}/items", methods=["GET"])
def ogc_features_items(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features items query: GET /api/features/collections/{collection_id}/items"""
    return _ogc_items(req)


@app.route(route="features/collections/{collection_id}/items/{feature_id}", methods=["GET"])
def ogc_features_feature(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features single feature: GET /api/features/collections/{collection_id}/items/{feature_id}"""
    return _ogc_feature(req)


# ============================================================================
# OGC API - STYLES ENDPOINTS (18 DEC 2025)
# ============================================================================
#
# OGC API - Styles extension for OGC Features collections.
# Stores styles in CartoSym-JSON format with multi-format output.
#
# Standards Compliance:
#   - OGC API - Styles: https://docs.ogc.org/DRAFTS/20-009.html
#   - CartoSym-JSON: OGC canonical style format
#
# Output Formats (via ?f= parameter):
#   - ?f=cartosym  - CartoSym-JSON (canonical storage format)
#   - ?f=leaflet   - Leaflet style object (default for web clients)
#   - ?f=mapbox    - Mapbox GL style layers
#
# Available Endpoints:
#   GET  /api/features/collections/{id}/styles       - List styles
#   GET  /api/features/collections/{id}/styles/{sid} - Get style (multi-format)

# Get trigger configurations (contains handler references)
_styles_triggers = get_styles_triggers()
_styles_list = _styles_triggers[0]['handler']
_styles_item = _styles_triggers[1]['handler']


@app.route(route="features/collections/{collection_id}/styles", methods=["GET"])
def ogc_styles_list(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Styles list: GET /api/features/collections/{collection_id}/styles"""
    return _styles_list(req)


@app.route(route="features/collections/{collection_id}/styles/{style_id}", methods=["GET"])
def ogc_styles_item(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Styles get: GET /api/features/collections/{collection_id}/styles/{style_id}?f=leaflet|mapbox|cartosym"""
    return _styles_item(req)


# ============================================================================
# RASTER RENDER CONFIG ENDPOINTS (22 JAN 2026 - F2.11)
# ============================================================================
#
# TiTiler render configuration storage for raster COG visualization.
# Source of truth for STAC Renders Extension embedding.
#
# Standards:
#   - STAC Renders Extension: https://github.com/stac-extensions/render
#   - TiTiler: https://developmentseed.org/titiler
#
# Endpoints:
#   GET    /api/raster/{cog_id}/renders              - List render configs
#   GET    /api/raster/{cog_id}/renders/default      - Get default render
#   GET    /api/raster/{cog_id}/renders/{render_id}  - Get specific render
#   POST   /api/raster/{cog_id}/renders              - Create render config
#   PUT    /api/raster/{cog_id}/renders/{render_id}  - Update render config
#   DELETE /api/raster/{cog_id}/renders/{render_id}  - Delete render config
#   POST   /api/raster/{cog_id}/renders/{render_id}/default - Set as default
#   POST   /api/raster/{cog_id}/renders/auto-default - Auto-generate default


@app.route(route="raster/{cog_id}/renders", methods=["GET"])
def raster_renders_list(req: func.HttpRequest) -> func.HttpResponse:
    """List render configs: GET /api/raster/{cog_id}/renders"""
    return list_renders(req)


@app.route(route="raster/{cog_id}/renders/default", methods=["GET"])
def raster_renders_default(req: func.HttpRequest) -> func.HttpResponse:
    """Get default render: GET /api/raster/{cog_id}/renders/default"""
    return get_default_render(req)


@app.route(route="raster/{cog_id}/renders/auto-default", methods=["POST"])
def raster_renders_auto_default(req: func.HttpRequest) -> func.HttpResponse:
    """Auto-generate default render: POST /api/raster/{cog_id}/renders/auto-default"""
    return create_default_render(req)


@app.route(route="raster/{cog_id}/renders/{render_id}", methods=["GET"])
def raster_renders_get(req: func.HttpRequest) -> func.HttpResponse:
    """Get render config: GET /api/raster/{cog_id}/renders/{render_id}"""
    return get_render(req)


@app.route(route="raster/{cog_id}/renders", methods=["POST"])
def raster_renders_create(req: func.HttpRequest) -> func.HttpResponse:
    """Create render config: POST /api/raster/{cog_id}/renders"""
    return create_render(req)


@app.route(route="raster/{cog_id}/renders/{render_id}", methods=["PUT"])
def raster_renders_update(req: func.HttpRequest) -> func.HttpResponse:
    """Update render config: PUT /api/raster/{cog_id}/renders/{render_id}"""
    return update_render(req)


@app.route(route="raster/{cog_id}/renders/{render_id}", methods=["DELETE"])
def raster_renders_delete(req: func.HttpRequest) -> func.HttpResponse:
    """Delete render config: DELETE /api/raster/{cog_id}/renders/{render_id}"""
    return delete_render(req)


@app.route(route="raster/{cog_id}/renders/{render_id}/default", methods=["POST"])
def raster_renders_set_default(req: func.HttpRequest) -> func.HttpResponse:
    """Set as default: POST /api/raster/{cog_id}/renders/{render_id}/default"""
    return set_default_render(req)


# ============================================================================
# MAP STATE API ENDPOINTS (23 JAN 2026)
# ============================================================================
#
# Saveable web map configurations with layer management and version history.
#
# Features:
#   - Save/restore map states (center, zoom, layers)
#   - Layer symbology references (STAC renders, OGC styles)
#   - Automatic snapshot versioning on updates
#   - Support for multiple map container types (MapLibre, Leaflet, OpenLayers)
#
# Available Endpoints:
#   GET    /api/maps                              - List maps
#   GET    /api/maps/{map_id}                     - Get map
#   POST   /api/maps                              - Create map
#   PUT    /api/maps/{map_id}                     - Update map
#   DELETE /api/maps/{map_id}                     - Delete map
#   GET    /api/maps/{map_id}/snapshots           - List snapshots
#   GET    /api/maps/{map_id}/snapshots/{version} - Get snapshot
#   POST   /api/maps/{map_id}/restore/{version}   - Restore from snapshot


@app.route(route="maps", methods=["GET"])
def maps_list(req: func.HttpRequest) -> func.HttpResponse:
    """List maps: GET /api/maps"""
    return list_maps(req)


@app.route(route="maps", methods=["POST"])
def maps_create(req: func.HttpRequest) -> func.HttpResponse:
    """Create map: POST /api/maps"""
    return create_map(req)


@app.route(route="maps/{map_id}", methods=["GET"])
def maps_get(req: func.HttpRequest) -> func.HttpResponse:
    """Get map: GET /api/maps/{map_id}"""
    return get_map(req)


@app.route(route="maps/{map_id}", methods=["PUT"])
def maps_update(req: func.HttpRequest) -> func.HttpResponse:
    """Update map: PUT /api/maps/{map_id}"""
    return update_map(req)


@app.route(route="maps/{map_id}", methods=["DELETE"])
def maps_delete(req: func.HttpRequest) -> func.HttpResponse:
    """Delete map: DELETE /api/maps/{map_id}"""
    return delete_map(req)


@app.route(route="maps/{map_id}/snapshots", methods=["GET"])
def maps_snapshots_list(req: func.HttpRequest) -> func.HttpResponse:
    """List snapshots: GET /api/maps/{map_id}/snapshots"""
    return list_snapshots(req)


@app.route(route="maps/{map_id}/snapshots/{version}", methods=["GET"])
def maps_snapshot_get(req: func.HttpRequest) -> func.HttpResponse:
    """Get snapshot: GET /api/maps/{map_id}/snapshots/{version}"""
    return get_snapshot(req)


@app.route(route="maps/{map_id}/restore/{version}", methods=["POST"])
def maps_restore(req: func.HttpRequest) -> func.HttpResponse:
    """Restore from snapshot: POST /api/maps/{map_id}/restore/{version}"""
    return restore_snapshot(req)


# ============================================================================
# STAC API v1.0.0 ENDPOINTS - MOVED TO BLUEPRINT (24 JAN 2026 - V0.8 Phase 17.3)
# ============================================================================
# All STAC endpoints consolidated into triggers/stac/stac_bp.py
# Registered via: app.register_functions(stac_bp)
# ============================================================================


# ============================================================================
# VECTOR VIEWER - QA Preview for Data Curators (13 NOV 2025)
# ============================================================================
# Simple HTML viewer for visual validation of PostGIS vector collections
# Uses OGC Features API for geometry and metadata
# Provides minimal Leaflet map with load buttons for QA purposes
# ============================================================================

# Get trigger configuration
_vector_viewer_triggers = get_vector_viewer_triggers()
_vector_viewer_handler = _vector_viewer_triggers[0]['handler']


@app.route(route="vector/viewer", methods=["GET"])
def vector_collection_viewer(req: func.HttpRequest) -> func.HttpResponse:
    """
    Vector collection preview viewer for data curators.

    GET /api/vector/viewer?collection={collection_id}

    Query Parameters:
        collection (required): Collection ID (PostGIS table name)

    Returns:
        HTML page with Leaflet map showing vector features and metadata

    Use Case:
        Data curators can quickly validate vector ETL output by opening
        this URL in a browser to see if geometry and metadata are correct.
        Uses OGC Features API to fetch collection metadata and features.

    Example:
        https://rmhazuregeoapi-.../api/vector/viewer?collection=qa_test_chunk_5000
    """
    return _vector_viewer_handler(req)


# ============================================================================
# RASTER COLLECTION VIEWER (30 DEC 2025) - F2.9
# ============================================================================
# STAC-integrated raster viewer with TiTiler XYZ tiles
# Provides interactive Leaflet map for browsing STAC raster collections
# with smart TiTiler URL generation based on raster metadata (app:*)
# ============================================================================

# Get trigger configuration
_raster_collection_viewer_triggers = get_raster_collection_viewer_triggers()
_raster_collection_viewer_handler = _raster_collection_viewer_triggers[0]['handler']


@app.route(route="raster/viewer", methods=["GET"])
def raster_collection_viewer(req: func.HttpRequest) -> func.HttpResponse:
    """
    Raster collection viewer for data curators.

    GET /api/raster/viewer?collection={collection_id}

    Query Parameters:
        collection (required): STAC collection ID

    Returns:
        HTML page with Leaflet map showing raster items via TiTiler XYZ tiles.
        Includes band selection, rescale, and colormap controls.

    Use Case:
        Data curators can browse STAC raster collections with proper
        visualization based on raster type (DEM, RGB, multi-band).
        Uses app:* STAC properties for smart TiTiler URL generation.

    Example:
        https://rmhazuregeoapi-.../api/raster/viewer?collection=aerial-2024
    """
    return _raster_collection_viewer_handler(req)


# QA Status endpoint for raster items
_raster_qa_handler = _raster_collection_viewer_triggers[1]['handler']


@app.route(route="raster/qa", methods=["POST"])
def raster_qa_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update QA status for STAC raster items.

    POST /api/raster/qa

    Request Body:
        {
            "item_id": "item-123",
            "collection_id": "collection-abc",
            "status": "approved" | "rejected" | "pending"
        }

    Returns:
        JSON response with:
        - success: boolean
        - item_id: string
        - collection_id: string
        - status: string
        - message: string

    Use Case:
        Data curators can approve or reject raster items from the viewer.
        Sets app:qa_status and app:qa_updated properties on STAC item.
    """
    return _raster_qa_handler(req)


# ============================================================================
# PIPELINE DASHBOARD - CONTAINER BLOB BROWSER (21 NOV 2025)
# ============================================================================
# Read-only UI operations - NO JOBS, NO TASKS, NO SERVICE BUS
# Direct Azure Blob Storage queries for Pipeline Dashboard interface

# V0.8 Phase 17.2: Consolidated to /storage/{container}/... (24 JAN 2026)
@app.route(route="storage/{container_name}/blobs", methods=["GET"])
def list_container_blobs(req: func.HttpRequest) -> func.HttpResponse:
    """
    List blobs in a container (read-only UI operation).

    GET /api/storage/{container_name}/blobs?prefix={prefix}&limit={limit}

    Path Parameters:
        container_name: Azure Blob Storage container (e.g., 'bronze-rasters')

    Query Parameters:
        prefix: Optional folder filter (e.g., 'maxar/', 'data/2025/')
        limit: Max results (default: 50, max: 1000)

    Returns:
        JSON list of blob metadata (name, size, last_modified, content_type)

    Note: This is a lightweight UI endpoint, NOT a job submission endpoint.
    """
    return list_container_blobs_handler(req)


@app.route(route="storage/{container_name}/blob", methods=["GET"])
def get_blob_metadata(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get metadata for a single blob (read-only UI operation).

    GET /api/storage/{container_name}/blob?path=maxar/tile_001.tif

    Path Parameters:
        container_name: Azure Blob Storage container (e.g., 'bronze-rasters')

    Query Parameters:
        path: Full path to blob (e.g., 'maxar/tile_001.tif')

    Returns:
        JSON blob metadata (name, size, last_modified, content_type, etag, etc.)

    Note: This is a lightweight UI endpoint, NOT a job submission endpoint.
          Uses singular 'blob' route (vs plural 'blobs' for listing).
    """
    return get_blob_metadata_handler(req)


@app.route(route="storage/containers", methods=["GET"])
def list_storage_containers(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all containers across all storage zones (read-only UI operation).

    GET /api/storage/containers
    GET /api/storage/containers?zone=bronze
    GET /api/storage/containers?prefix=silver-

    Query Parameters:
        zone (optional): Filter to specific zone (bronze, silver, silverext, gold)
        prefix (optional): Container name prefix filter

    Returns:
        JSON with containers grouped by zone, storage account info, and counts

    Note: This is a lightweight UI endpoint for discovering available containers.
    """
    return list_storage_containers_handler(req)


@app.route(route="storage/upload", methods=["POST"])
def storage_upload(req: func.HttpRequest) -> func.HttpResponse:
    """
    Upload file to bronze storage via multipart/form-data.

    POST /api/storage/upload

    Form Fields:
        file: The file to upload (required)
        container: Target container (required)
        path: Blob path within container (optional, defaults to filename)

    Returns:
        JSON with upload result including container, path, size, etag

    Security:
        Uploads restricted to bronze storage account.
        Maximum file size: 100MB

    Example:
        curl -X POST "https://rmhazuregeoapi-.../api/storage/upload" \\
            -F "file=@myfile.gpkg" \\
            -F "container=source-data" \\
            -F "path=uploads/myfile.gpkg"
    """
    return storage_upload_handler(req)


# ============================================================================
# UNIFIED WEB INTERFACES (14 NOV 2025)
# ============================================================================

from web_interfaces import unified_interface_handler


@app.route(route="interface", methods=["GET"])
def web_interface_redirect(req: func.HttpRequest) -> func.HttpResponse:
    """Redirect /api/interface to /api/interface/home."""
    return func.HttpResponse(
        body="",
        status_code=302,
        headers={"Location": "/api/interface/home"}
    )


@app.route(route="interface/{name}", methods=["GET", "POST"])
def web_interface_unified(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified web interface handler - dynamic module loading.

    GET /api/interface/{name}
    POST /api/interface/{name}?fragment=submit  (HTMX form submissions)

    Route Parameters:
        name: Interface name (stac, vector, jobs, docs)

    Examples:
        /api/interface/stac - STAC collections dashboard
        /api/interface/vector?collection=test_geojson_fresh - Vector viewer
        /api/interface/jobs - Job monitor dashboard
        /api/interface/docs - API explorer

    How It Works:
        1. InterfaceRegistry maintains map of name -> Interface class
        2. Each interface registers itself with @InterfaceRegistry.register('name')
        3. Unified handler looks up interface by name and calls .render(request)
        4. Interface returns complete HTML page

    Benefits:
        - Single route handles all web interfaces
        - Easy to add new interfaces (just register, no function_app.py changes)
        - Shared navigation bar across all interfaces
        - Auto-discovery of available interfaces
    """
    return unified_interface_handler(req)


# ============================================================================
# OPENAPI SPEC ENDPOINT
# ============================================================================

@app.route(route="openapi.json", methods=["GET"])
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    """
    Serve OpenAPI 3.0 specification as JSON.

    GET /api/openapi.json

    Returns the Platform API OpenAPI spec with the server URL
    dynamically set to the current deployment.
    """
    import json
    from pathlib import Path

    try:
        spec_path = Path(__file__).parent / "openapi" / "platform-api-v1.json"
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)

        # Update server URL to current deployment
        host = req.headers.get('Host', 'localhost')
        scheme = 'https' if 'azurewebsites.net' in host else 'http'
        base_url = f"{scheme}://{host}"

        spec['servers'] = [
            {'url': base_url, 'description': 'Current deployment'}
        ]

        return func.HttpResponse(
            json.dumps(spec, indent=2),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": f"Failed to load OpenAPI spec: {str(e)}"}),
            mimetype="application/json",
            status_code=500
        )


# =============================================================================
# API DOCUMENTATION (F12.8)
# =============================================================================
# Documentation endpoints are served via the web_interfaces pattern:
#   /api/interface/swagger  - Swagger UI (interactive, inlined assets)
#   /api/interface/redoc    - ReDoc (clean three-panel docs, CDN-loaded)
#   /api/interface/docs     - Platform documentation (static)
#   /api/openapi.json       - Raw OpenAPI spec (below)
# =============================================================================


# ingest_vector HTTP endpoint REMOVED (27 NOV 2025)
# Platform layer now routes vector requests to process_vector (idempotent DELETE+INSERT)
# Direct vector job submission should use: POST /api/jobs/submit/process_vector


# ============================================================================
# TEST UTILITIES - DEVELOPMENT ONLY
# ============================================================================
# test/create-rasters endpoint DISABLED (30 NOV 2025)
# test_raster_create trigger excluded by funcignore (*test* pattern)
# Uncomment locally if needed for development testing
#
# @app.route(route="test/create-rasters", methods=["POST"])
# def test_create_rasters(req: func.HttpRequest) -> func.HttpResponse:
#     """Create test raster files in Azure Blob Storage for pipeline testing."""
#     return test_raster_create_trigger.handle_request(req)




# dbadmin/debug/all - MOVED TO routes/admin_db.py (15 DEC 2025)


# ============================================================================
# DUPLICATE SERVICE BUS TRIGGERS REMOVED (2 OCT 2025)
# Removed duplicate process_job_service_bus() and process_task_service_bus()
# Keeping process_service_bus_job() and process_service_bus_task() below
# ============================================================================


# ============================================================================
# SERVICE BUS TRIGGERS - Conditional Registration (11 DEC 2025)
# ============================================================================
# Multi-Function App Architecture: Triggers are conditionally registered based
# on APP_MODE environment variable. This allows identical code to be deployed
# to multiple Function Apps with different queue listening configurations.
#
# V0.8 QUEUE ARCHITECTURE (24 JAN 2026):
# - geospatial-jobs: Job orchestration + stage_complete signals
# - functionapp-tasks: Lightweight operations (DB queries, inventory, STAC)
# - container-tasks: Heavy operations (GDAL, geopandas) - Docker worker handles this
#
# All task types MUST be explicitly mapped in TaskRoutingDefaults (DOCKER_TASKS or FUNCTIONAPP_TASKS).
# Unmapped task types raise ContractViolationError (no fallback queue).
#
# See config/app_mode_config.py for mode definitions and queue mappings.
# ============================================================================

# ============================================================================
# STARTUP QUEUE VALIDATION (29 DEC 2025, refactored 23 JAN 2026 - APP_CLEANUP Phase 1)
# ============================================================================
# Validate that required Service Bus queues exist BEFORE registering triggers.
# This catches missing queue errors at deployment time, not 30 seconds later
# when the first message arrives and the trigger silently fails.
#
# SOFT VALIDATION: Store results in STARTUP_STATE, don't crash.
# Service Bus triggers only register if STARTUP_STATE.all_passed is True.
#
# Query failures with: GET /api/readyz or /api/health
#
# REFACTORED: Logic moved to startup/service_bus_validator.py (APP_CLEANUP Phase 1)
# ============================================================================
_startup_logger.info("🔍 STARTUP: Validating Service Bus (DNS + queues)...")

from startup.service_bus_validator import validate_service_bus
_dns_result, _queue_result = validate_service_bus(_app_mode, get_config())
STARTUP_STATE.service_bus_dns = _dns_result
STARTUP_STATE.service_bus_queues = _queue_result

if _dns_result.passed and _queue_result.passed:
    _startup_logger.info("✅ STARTUP: Service Bus validation passed")
else:
    if not _dns_result.passed:
        _startup_logger.critical(f"❌ STARTUP: Service Bus DNS validation failed: {_dns_result.error_message}")
    if not _queue_result.passed:
        _startup_logger.critical(f"❌ STARTUP: Service Bus queue validation failed: {_queue_result.error_message}")

# ============================================================================
# PHASE 2 COMPLETE: Finalize Startup State
# ============================================================================
STARTUP_STATE.finalize()

# Detect env vars using defaults (for readyz warnings - not errors, just informational)
STARTUP_STATE.detect_default_env_vars()

# Log observability mode status (10 JAN 2026 - F7.12)
try:
    from config import get_config
    _obs_config = get_config().observability
    if _obs_config.enabled:
        _startup_logger.info(
            f"✅ STARTUP: OBSERVABILITY_MODE=true "
            f"(app={_obs_config.app_name}, env={_obs_config.environment})"
        )
    else:
        _startup_logger.warning(
            "⚠️ STARTUP: OBSERVABILITY_MODE not set or false - "
            "debug instrumentation disabled (memory tracking, latency logging, blob metrics)"
        )
except Exception as _obs_error:
    _startup_logger.debug(f"Observability config check skipped: {_obs_error}")

# Initialize metrics blob container if OBSERVABILITY_MODE is enabled
try:
    from infrastructure.metrics_blob_logger import init_metrics_container
    if init_metrics_container():
        _startup_logger.info("✅ STARTUP: Metrics container 'applogs' initialized")
except Exception as _metrics_init_error:
    _startup_logger.debug(f"Metrics container init skipped: {_metrics_init_error}")

if STARTUP_STATE.all_passed:
    _startup_logger.info("✅ STARTUP: Phase 2 complete - All validations PASSED")

    # ========================================================================
    # STARTUP SNAPSHOT CAPTURE (04 JAN 2026)
    # ========================================================================
    # Capture system configuration snapshot on cold start for drift detection.
    # This runs after all validations pass to capture baseline config state.
    # Wrapped in try/except to ensure startup continues even if snapshot fails.
    # ========================================================================
    try:
        from services.snapshot_service import snapshot_service
        _snapshot_result = snapshot_service.capture_startup_snapshot()
        if _snapshot_result.get("success"):
            _startup_logger.info(
                f"✅ STARTUP: Snapshot captured (id={_snapshot_result.get('snapshot_id')}, "
                f"drift={_snapshot_result.get('has_drift')})"
            )
            if _snapshot_result.get("has_drift"):
                _startup_logger.warning("⚠️ STARTUP: Configuration drift detected since last snapshot!")
        else:
            _startup_logger.warning(f"⚠️ STARTUP: Snapshot capture failed: {_snapshot_result.get('error')}")
    except Exception as _snapshot_error:
        _startup_logger.warning(f"⚠️ STARTUP: Snapshot capture skipped (non-critical): {_snapshot_error}")

else:
    _failed_checks = STARTUP_STATE.get_failed_checks()
    _startup_logger.warning(
        f"⚠️ STARTUP: Phase 2 complete - {len(_failed_checks)} validation(s) FAILED: "
        f"{[f.name for f in _failed_checks]}"
    )
    _startup_logger.warning("   ⚠️ Service Bus triggers will NOT be registered")
    _startup_logger.warning("   ℹ️ App will respond to /api/livez, /api/readyz, /api/health only")

# ============================================================================
# PHASE 3: CONDITIONAL TRIGGER REGISTRATION (03 JAN 2026 - STARTUP_REFORM.md)
# ============================================================================
# Service Bus triggers are ONLY registered if all startup validations passed.
# This ensures we don't register triggers for queues that are inaccessible.
# ============================================================================

logger.info("=" * 70)
logger.info("🔌 SERVICE BUS TRIGGER REGISTRATION STARTING")
logger.info("=" * 70)
logger.info(f"   APP_MODE: {_app_mode.mode.value}")
logger.info(f"   APP_NAME: {_app_mode.app_name}")
logger.info(f"   STARTUP_STATE.all_passed: {STARTUP_STATE.all_passed}")
logger.info("-" * 70)
logger.info("   HTTP ENDPOINTS:")
logger.info(f"      has_platform_endpoints: {_app_mode.has_platform_endpoints}")
logger.info(f"      has_jobs_endpoints: {_app_mode.has_jobs_endpoints}")
logger.info(f"      has_admin_endpoints: {_app_mode.has_admin_endpoints}")
logger.info("-" * 70)
logger.info("   QUEUE LISTENERS (V0.8):")
logger.info(f"      listens_to_jobs_queue: {_app_mode.listens_to_jobs_queue}")
logger.info(f"      listens_to_functionapp_tasks: {_app_mode.listens_to_functionapp_tasks}")
logger.info(f"      listens_to_container_tasks: {_app_mode.listens_to_container_tasks}")
logger.info("-" * 70)

# CRITICAL: Only register Service Bus triggers if startup validation passed
if not STARTUP_STATE.all_passed:
    logger.warning("⏭️ SKIPPING ALL SERVICE BUS TRIGGERS - Startup validation failed")
    logger.warning("   App will only respond to: /api/livez, /api/readyz, /api/health")
    _failed = STARTUP_STATE.get_failed_checks()
    logger.warning(f"   Failed checks: {[f.name for f in _failed]}")

# Jobs Queue Trigger - Platform modes only (job orchestration + stage_complete signals)
if STARTUP_STATE.all_passed and _app_mode.listens_to_jobs_queue:
    logger.info("✅ REGISTERING: geospatial-jobs queue trigger (job orchestration)")
elif _app_mode.listens_to_jobs_queue:
    logger.warning("⏭️ SKIPPING: geospatial-jobs queue trigger (validation failed)")
else:
    logger.warning("⏭️ SKIPPING: geospatial-jobs queue trigger (APP_MODE=%s)", _app_mode.mode.value)

if STARTUP_STATE.all_passed and _app_mode.listens_to_jobs_queue:
    # APP_CLEANUP Phase 2: Handler logic moved to triggers/service_bus/job_handler.py
    from triggers.service_bus import handle_job_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
        """Process job messages from Service Bus using CoreMachine."""
        handle_job_message(msg, core_machine)


# =============================================================================
# V0.8: CONSOLIDATED TASK QUEUES (24 JAN 2026)
# =============================================================================
# - functionapp-tasks: Lightweight operations (DB queries, inventory, STAC)
# - container-tasks: Heavy operations (GDAL, geopandas) - only in standalone without Docker
# =============================================================================

# FunctionApp Tasks Queue Trigger - worker_functionapp/standalone modes
if STARTUP_STATE.all_passed and _app_mode.listens_to_functionapp_tasks:
    logger.info("✅ REGISTERING: functionapp-tasks queue trigger (lightweight DB ops)")
elif _app_mode.listens_to_functionapp_tasks:
    logger.warning("⏭️ SKIPPING: functionapp-tasks queue trigger (validation failed)")
else:
    logger.warning("⏭️ SKIPPING: functionapp-tasks queue trigger (APP_MODE=%s)", _app_mode.mode.value)

if STARTUP_STATE.all_passed and _app_mode.listens_to_functionapp_tasks:
    from triggers.service_bus import handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="functionapp-tasks",
        connection="ServiceBusConnection"
    )
    def process_functionapp_task(msg: func.ServiceBusMessage) -> None:
        """Process task messages from functionapp-tasks queue (V0.8)."""
        handle_task_message(msg, core_machine, queue_name="functionapp-tasks")


# Container Tasks Queue Trigger - Only standalone mode with DOCKER_WORKER_ENABLED=false
# When Docker worker is deployed, it handles container-tasks, not the Function App
if STARTUP_STATE.all_passed and _app_mode.listens_to_container_tasks:
    logger.info("✅ REGISTERING: container-tasks queue trigger (standalone dev mode)")
elif _app_mode.listens_to_container_tasks:
    logger.warning("⏭️ SKIPPING: container-tasks queue trigger (validation failed)")
else:
    if _app_mode.docker_worker_enabled:
        logger.info("⏭️ SKIPPING: container-tasks queue trigger (Docker worker handles this)")
    else:
        logger.warning("⏭️ SKIPPING: container-tasks queue trigger (APP_MODE=%s)", _app_mode.mode.value)

if STARTUP_STATE.all_passed and _app_mode.listens_to_container_tasks:
    if 'handle_task_message' not in dir():
        from triggers.service_bus import handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="container-tasks",
        connection="ServiceBusConnection"
    )
    def process_container_task(msg: func.ServiceBusMessage) -> None:
        """Process task messages from container-tasks queue (dev only - no Docker worker)."""
        handle_task_message(msg, core_machine, queue_name="container-tasks")


# Summary of trigger registration (V0.8 - 24 JAN 2026)
_registered_triggers = []
if STARTUP_STATE.all_passed and _app_mode.listens_to_jobs_queue:
    _registered_triggers.append("geospatial-jobs")
if STARTUP_STATE.all_passed and _app_mode.listens_to_functionapp_tasks:
    _registered_triggers.append("functionapp-tasks")
if STARTUP_STATE.all_passed and _app_mode.listens_to_container_tasks:
    _registered_triggers.append("container-tasks")

# Calculate expected triggers based on mode
_expected_triggers = sum([
    _app_mode.listens_to_jobs_queue,
    _app_mode.listens_to_functionapp_tasks,
    _app_mode.listens_to_container_tasks,
])

logger.info("-" * 70)
logger.info(f"🔌 SERVICE BUS TRIGGER REGISTRATION COMPLETE (V0.8)")
logger.info(f"   Triggers registered: {len(_registered_triggers)}/{_expected_triggers}")
logger.info(f"   Queues: {_registered_triggers}")
if not STARTUP_STATE.all_passed:
    logger.warning("⚠️ NO TRIGGERS REGISTERED - Startup validation failed")
    logger.warning("   Use GET /api/readyz to see validation errors")
elif len(_registered_triggers) == 0:
    logger.warning("⚠️ NO TRIGGERS REGISTERED - APP_MODE doesn't listen to any queues")
elif len(_registered_triggers) < _expected_triggers:
    logger.warning(f"⚠️ Partial trigger registration (APP_MODE={_app_mode.mode.value})")
else:
    logger.info(f"✅ All expected triggers registered (APP_MODE={_app_mode.mode.value})")
logger.info("=" * 70)


# ============================================================================
# QUEUE ERROR HANDLING HELPER FUNCTIONS
# ============================================================================
# APP_CLEANUP Phase 2 (23 JAN 2026): Helper functions moved to:
#   triggers/service_bus/error_handler.py
#
# Available via import:
#   from triggers.service_bus import (
#       extract_job_id_from_raw_message,
#       extract_task_id_from_raw_message,
#       mark_job_failed,
#       mark_task_failed,
#   )
# ============================================================================


# ============================================================================
# TIMER TRIGGERS BLUEPRINT (23 JAN 2026 - APP_CLEANUP Phase 3)
# ============================================================================
# All timer triggers moved to triggers/timers/timer_bp.py blueprint.
#
# Includes:
# - Janitor timers: task_watchdog, job_health, orphan_detector
# - Geo maintenance: geo_orphan_check, metadata_consistency, geo_integrity_check
# - Scheduled operations: curated_dataset_scheduler
# - System monitoring: system_snapshot, log_cleanup, external_service_health
#
# Timer Schedule Overview:
#   - janitor_task_watchdog: Every 5 minutes
#   - janitor_job_health: :15 and :45 past each hour
#   - janitor_orphan_detector: Every hour
#   - geo_orphan_check_timer: Every 6 hours
#   - metadata_consistency_timer: 03:00, 09:00, 15:00, 21:00 UTC
#   - geo_integrity_check_timer: 02:00, 08:00, 14:00, 20:00 UTC
#   - curated_dataset_scheduler: Daily 2 AM UTC
#   - system_snapshot_timer: Every hour
#   - log_cleanup_timer: Daily 3 AM UTC
#   - external_service_health_timer: Every hour
# ============================================================================

from triggers.timers import timer_bp
app.register_functions(timer_bp)


# NOTE: Cleanup/janitor routes in triggers/admin/admin_janitor.py blueprint (12 JAN 2026)


# ============================================================================
# RASTER API - Service Layer Convenience Wrappers (18 DEC 2025)
# ============================================================================
# Convenience endpoints that look up STAC items and proxy to TiTiler.
# Simplifies raster access by accepting collection/item IDs instead of URLs.
#
# Endpoints:
#   GET /api/raster/extract/{collection}/{item}  - Extract bbox as image
#   GET /api/raster/point/{collection}/{item}    - Point value query
#   GET /api/raster/clip/{collection}/{item}     - Clip to geometry (POST supported)
#   GET /api/raster/preview/{collection}/{item}  - Quick preview image
# ============================================================================

# Get trigger configurations
_raster_triggers = get_raster_triggers()
_raster_extract = _raster_triggers[0]['handler']
_raster_point = _raster_triggers[1]['handler']
_raster_clip = _raster_triggers[2]['handler']
_raster_preview = _raster_triggers[3]['handler']


@app.route(route="raster/extract/{collection}/{item}", methods=["GET"])
def raster_api_extract(req: func.HttpRequest) -> func.HttpResponse:
    """
    Extract bbox from raster as image.

    GET /api/raster/extract/{collection}/{item}?bbox={minx},{miny},{maxx},{maxy}
        &format=tif|png|npy
        &asset=data
        &time_index=1
        &colormap=viridis
        &rescale=0,100
    """
    return _raster_extract(req)


@app.route(route="raster/point/{collection}/{item}", methods=["GET"])
def raster_api_point(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get raster value at a point.

    GET /api/raster/point/{collection}/{item}?location={name}|{lon},{lat}
        &asset=data
        &time_index=1
    """
    return _raster_point(req)


@app.route(route="raster/clip/{collection}/{item}", methods=["GET", "POST"])
def raster_api_clip(req: func.HttpRequest) -> func.HttpResponse:
    """
    Clip raster to geometry.

    GET /api/raster/clip/{collection}/{item}?boundary_type=state&boundary_id=VA
        &format=tif|png
        &time_index=1

    POST /api/raster/clip/{collection}/{item}
        Body: GeoJSON geometry
        ?format=tif|png
    """
    return _raster_clip(req)


@app.route(route="raster/preview/{collection}/{item}", methods=["GET"])
def raster_api_preview(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get preview image of raster.

    GET /api/raster/preview/{collection}/{item}?format=png|jpeg|webp
        &asset=data
        &time_index=1
        &max_size=512
        &colormap=viridis
    """
    return _raster_preview(req)


# ============================================================================
# XARRAY API - Direct Zarr Access for Time-Series (18 DEC 2025)
# ============================================================================
# Direct xarray access to Zarr datasets for time-series operations.
# More efficient than TiTiler for multi-timestep queries (single read vs N requests).
#
# Endpoints:
#   GET /api/xarray/point/{collection}/{item}       - Time-series at a point
#   GET /api/xarray/statistics/{collection}/{item}  - Regional stats over time
#   GET /api/xarray/aggregate/{collection}/{item}   - Temporal aggregation export
# ============================================================================

# Get trigger configurations
_xarray_triggers = get_xarray_triggers()
_xarray_point = _xarray_triggers[0]['handler']
_xarray_statistics = _xarray_triggers[1]['handler']
_xarray_aggregate = _xarray_triggers[2]['handler']


@app.route(route="xarray/point/{collection}/{item}", methods=["GET"])
def xarray_api_point(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get time-series at a point.

    GET /api/xarray/point/{collection}/{item}?location={name}|{lon},{lat}
        &start_time=2015-01-01
        &end_time=2015-12-31
        &aggregation=none|daily|monthly|yearly
    """
    return _xarray_point(req)


@app.route(route="xarray/statistics/{collection}/{item}", methods=["GET"])
def xarray_api_statistics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get regional statistics over time.

    GET /api/xarray/statistics/{collection}/{item}?bbox={minx},{miny},{maxx},{maxy}
        &start_time=2015-01-01
        &end_time=2015-12-31
        &temporal_resolution=daily|monthly|yearly
    """
    return _xarray_statistics(req)


@app.route(route="xarray/aggregate/{collection}/{item}", methods=["GET"])
def xarray_api_aggregate(req: func.HttpRequest) -> func.HttpResponse:
    """
    Compute temporal aggregation and export.

    GET /api/xarray/aggregate/{collection}/{item}?bbox={minx},{miny},{maxx},{maxy}
        &start_time=2015-01-01
        &end_time=2015-12-31
        &aggregation=mean|max|min|sum
        &format=json|tif|png|npy
    """
    return _xarray_aggregate(req)


# NOTE: STAC repair routes moved to triggers/admin/admin_stac.py blueprint (12 JAN 2026)
# - /api/stac/repair/test
# - /api/stac/repair/inventory
# - /api/stac/repair/item
