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
    - Queue-based async processing with poison queue monitoring
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
        GET  /api/platform/health - Simplified health for DDH (07 DEC 2025)
        GET  /api/platform/stats - Job statistics for DDH (07 DEC 2025)
        GET  /api/platform/failures - Recent failures for DDH (07 DEC 2025)

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

    Monitoring:
        GET  /api/monitor/poison - Check poison queue status

    Schema Management (DEV ONLY):
        POST /api/dbadmin/maintenance/full-rebuild?confirm=yes - Atomic schema rebuild

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

    2. Queue-Based Task Execution (11 DEC 2025 - No Legacy Fallbacks):
       - geospatial-jobs queue: Job messages and stage_complete signals
       - raster-tasks queue: Memory-intensive GDAL operations (low concurrency)
       - vector-tasks queue: DB-bound and lightweight operations (high concurrency)
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

# ========================================================================
# STARTUP VALIDATION - Fail-fast import validation for critical dependencies
# ========================================================================
# FIXED: util_logger now uses dataclasses instead of Pydantic (stdlib only)

# Application modules (our code) - Utilities
from utils import validator

# Perform fail-fast startup validation (only in Azure Functions or when explicitly enabled)
validator.ensure_startup_ready()

# ========================================================================
# APPLICATION IMPORTS - Our modules (validated at startup)
# ========================================================================

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
from config import get_app_mode_config
_app_mode = get_app_mode_config()

# CoreMachine - Universal orchestrator (Epoch 4)
from core.machine import CoreMachine

# Import service modules - no longer needed for registration (Phase 4 complete)
# Services are now explicitly registered in initialize_catalogs()
# Auto-discovery no longer needed since we use explicit registration

# Auto-discover is deprecated after Phase 4 migration
# from task_factory import auto_discover_handlers
# auto_discover_handlers()

# Application modules (our code) - HTTP Trigger Classes
# Import directly from modules to control when instances are created
from triggers.health import health_check_trigger
from triggers.livez import livez_trigger
from triggers.submit_job import submit_job_trigger
from triggers.get_job_status import get_job_status_trigger
from triggers.poison_monitor import poison_monitor_trigger
from triggers.schema_pydantic_deploy import pydantic_deploy_trigger
# ⚠️ LEGACY IMPORTS - DEPRECATED (10 NOV 2025) - COMMENTED OUT 16 NOV 2025
# These imports are kept temporarily for backward compatibility
# All functionality has been migrated to triggers/admin/
# File triggers/db_query.py has been deleted - routes no longer needed
# from triggers.db_query import (
#     schema_nuke_trigger  # Still used temporarily by db_maintenance.py
# )

from triggers.analyze_container import analyze_container_trigger
from triggers.stac_setup import stac_setup_trigger
from triggers.stac_collections import stac_collections_trigger
from triggers.stac_init import stac_init_trigger
from triggers.stac_extract import stac_extract_trigger
from triggers.stac_vector import stac_vector_trigger
from triggers.stac_nuke import stac_nuke_trigger

# STAC API v1.0.0 Portable Module (10 NOV 2025)
from stac_api import get_stac_triggers

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
from triggers.admin.h3_debug import admin_h3_debug_trigger

# Curated Dataset Admin (15 DEC 2025) - System-managed geospatial data
from triggers.curated.admin import curated_admin_trigger
from triggers.curated.scheduler import curated_scheduler_trigger

# Platform Service Layer triggers (25 OCT 2025)
from triggers.trigger_platform import (
    platform_request_submit,
    platform_raster_submit,
    platform_raster_collection_submit
)
from triggers.trigger_platform_status import (
    platform_request_status,
    platform_health,
    platform_stats,
    platform_failures
)

# OGC Features API - Standalone module (29 OCT 2025)
from ogc_features import get_ogc_triggers

# STAC API - Standalone module (11 NOV 2025)
from stac_api import get_stac_triggers

# Vector Viewer - Standalone module (13 NOV 2025) - OGC Features API
from vector_viewer import get_vector_viewer_triggers

# Pipeline Dashboard - Container blob browser (21 NOV 2025) - Read-only UI operations
from triggers.list_container_blobs import list_container_blobs_handler
from triggers.get_blob_metadata import get_blob_metadata_handler
from triggers.list_storage_containers import list_storage_containers_handler

# Janitor Triggers (21 NOV 2025) - System maintenance (timer + HTTP)
from triggers.janitor import (
    # Timer handlers
    task_watchdog_handler,
    job_health_handler,
    orphan_detector_handler,
    # HTTP handlers
    janitor_run_handler,
    janitor_status_handler,
    janitor_history_handler
)

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
# See: STORAGE_QUEUE_DEPRECATION_COMPLETE.md
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
# PLATFORM ORCHESTRATION CALLBACK (30 OCT 2025)
# ============================================================================
# Global callback for Platform job completion - imported by PlatformOrchestrator
# This allows Platform to react to job completions from the global CoreMachine instance
# ============================================================================

def _global_platform_callback(job_id: str, job_type: str, status: str, result: dict):
    """
    Global callback for Platform orchestration.

    This callback is invoked by the global CoreMachine instance when jobs complete.
    It forwards completions to PlatformOrchestrator's handler if the job belongs
    to a Platform request.

    NOTE: This function is set dynamically after PlatformOrchestrator initializes.
    See trigger_platform.py PlatformOrchestrator.__init__
    """
    # Will be set by PlatformOrchestrator during initialization
    pass

# Initialize CoreMachine at module level with EXPLICIT registries (reused across all triggers)
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS,
    on_job_complete=_global_platform_callback
)

logger.info("✅ CoreMachine initialized with explicit registries")
logger.info(f"   Registered jobs: {list(ALL_JOBS.keys())}")
logger.info(f"   Registered handlers: {list(ALL_HANDLERS.keys())}")
logger.info(f"   ✅ Platform callback registered (will be connected on Platform trigger load)")

# Initialize function app with HTTP auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ============================================================================
# BLUEPRINT REGISTRATIONS (15 DEC 2025)
# ============================================================================
# DEV/Admin endpoints moved to separate Blueprint modules for better organization
from routes import admin_db_bp, admin_servicebus_bp

app.register_functions(admin_db_bp)
app.register_functions(admin_servicebus_bp)

logger.info("✅ Blueprints registered: admin_db, admin_servicebus")





@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint using HTTP trigger base class."""
    return health_check_trigger.handle_request(req)


@app.route(route="livez", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def livez(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness probe - is the app alive? No dependencies checked."""
    return livez_trigger.handle_request(req)


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


@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/status/{job_id}", methods=["GET"])
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)




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


# H3 Debug and Bootstrap Monitoring (12 NOV 2025)
# NOTE: Changed from /api/admin/h3 to /api/h3/debug because Azure Functions reserves /api/admin/* for built-in admin UI
@app.route(route="h3/debug", methods=["GET"])
def admin_h3_debug(req: func.HttpRequest) -> func.HttpResponse:
    """
    H3 debug operations: GET /api/h3/debug?operation={op}&{params}

    Available operations:
    - schema_status: Check h3 schema exists
    - grid_summary: Grid metadata for all resolutions
    - grid_details: Detailed stats for specific grid (requires grid_id)
    - reference_filters: List all reference filters
    - reference_filter_details: Details for specific filter (requires filter_name)
    - sample_cells: Sample cells from grid (requires grid_id)
    - parent_child_check: Validate hierarchy (requires parent_id)
    """
    return admin_h3_debug_trigger.handle_request(req)


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

# Get trigger configurations (contains handler references)
_stac_triggers = get_stac_triggers()
_stac_landing = _stac_triggers[0]['handler']
_stac_conformance = _stac_triggers[1]['handler']
_stac_collections = _stac_triggers[2]['handler']
_stac_collection = _stac_triggers[3]['handler']
_stac_items = _stac_triggers[4]['handler']
_stac_item = _stac_triggers[5]['handler']

# ============================================================================
# DEPRECATED OLD STAC ENDPOINTS (13 NOV 2025) - Commented out, replaced by new stac_api module below
# These were broken (404 errors) - new working endpoints start at line 1492 with /api/stac/ paths
# TODO: Delete these after confirming new /api/stac/ endpoints work
# ============================================================================

# @app.route(route="stac", methods=["GET"])
# def stac_api_landing_OLD_DEPRECATED(req: func.HttpRequest) -> func.HttpResponse:
#     """STAC API landing page: GET /api/stac (DEPRECATED - broken, use new stac_api module)"""
#     return _stac_landing(req)


# @app.route(route="stac/conformance", methods=["GET"])
# def stac_api_conformance_OLD_DEPRECATED(req: func.HttpRequest) -> func.HttpResponse:
#     """STAC API conformance: GET /api/stac/conformance (DEPRECATED)"""
#     return _stac_conformance(req)


# @app.route(route="stac/collections", methods=["GET"])
# def stac_api_collections_list_OLD_DEPRECATED(req: func.HttpRequest) -> func.HttpResponse:
#     """STAC API collections list: GET /api/stac/collections (DEPRECATED)"""
#     return _stac_collections(req)


# ============================================================================
# STAC SETUP ENDPOINT - PgSTAC installation and management
# ============================================================================

@app.route(route="stac/setup", methods=["GET", "POST"])
def stac_setup(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC infrastructure setup and status: /api/stac/setup

    GET  /api/stac/setup              - Check installation status
    GET  /api/stac/setup?verify=true  - Full verification with tests
    POST /api/stac/setup?confirm=yes  - Install PgSTAC schema

    POST with drop (DESTRUCTIVE):
    POST /api/stac/setup?confirm=yes&drop=true - Reinstall (requires PGSTAC_CONFIRM_DROP=true)

    Returns:
        Installation status, verification results, or setup confirmation
    """
    return stac_setup_trigger.handle_request(req)


# 🚨 STAC NUCLEAR BUTTON - DEVELOPMENT ONLY (29 OCT 2025)
@app.route(route="stac/nuke", methods=["POST"])
def nuke_stac_data(req: func.HttpRequest) -> func.HttpResponse:
    """
    🚨 NUCLEAR: Clear STAC items/collections (DEV/TEST ONLY)

    POST /api/stac/nuke?confirm=yes&mode=all

    Query Parameters:
        confirm: Must be "yes" (required)
        mode: Clearing mode (default: "all")
              - "items": Delete only items (preserve collections)
              - "collections": Delete collections (CASCADE deletes items)
              - "all": Delete both collections and items

    Returns:
        Deletion results with counts and execution time

    ⚠️ This clears STAC data but preserves pgstac schema (functions, indexes, partitions)
    Much faster than full schema drop/recreate cycle
    """
    return stac_nuke_trigger.handle_request(req)


@app.route(route="stac/collections/{tier}", methods=["POST"])
def stac_collections(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC collection management for Bronze/Silver/Gold tiers.

    POST /api/stac/collections/{tier} where tier is: bronze, silver, or gold

    Body:
        {
            "container": "<bronze-container>",  // Required (use config.storage.bronze)
            "collection_id": "custom-id",       // Optional
            "title": "Custom Title",            // Optional
            "description": "Custom description" // Optional
        }

    Returns:
        Collection creation result with collection_id
    """
    return stac_collections_trigger.handle_request(req)


@app.route(route="stac/init", methods=["POST"])
def stac_init(req: func.HttpRequest) -> func.HttpResponse:
    """
    Initialize STAC production collections.

    POST /api/stac/init

    Body (optional):
        {
            "collections": ["dev", "cogs", "vectors", "geoparquet"]  // Default: all
        }

    Returns:
        Results for each collection creation
    """
    return stac_init_trigger.handle_request(req)


@app.route(route="stac/extract", methods=["POST"])
def stac_extract(req: func.HttpRequest) -> func.HttpResponse:
    """
    Extract STAC metadata from raster blob and insert into PgSTAC.

    POST /api/stac/extract

    Body:
        {
            "container": "<bronze-container>",     // Required (use config.storage.bronze)
            "blob_name": "test/file.tif",          // Required
            "collection_id": "dev",                // Optional (default: "dev")
            "insert": true                         // Optional (default: true)
        }

    Returns:
        STAC Item metadata and insertion result
    """
    return stac_extract_trigger.handle_request(req)


# ============================================================================
# PLATFORM SERVICE LAYER ENDPOINTS (25 OCT 2025)
# ============================================================================
# Platform orchestration layer above CoreMachine for external applications (DDH)
# Follows same patterns as Job→Task: PlatformRequest→Jobs→Tasks

@app.route(route="platform/submit", methods=["POST"])
def platform_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a platform request from external application (DDH).

    POST /api/platform/submit

    Body:
        {
            "dataset_id": "landsat-8",
            "resource_id": "LC08_L1TP_044034_20210622",
            "version_id": "v1.0",
            "data_type": "raster",
            "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze/...",
            "parameters": {},
            "client_id": "ddh"
        }

    Returns:
        {
            "success": true,
            "request_id": "abc123...",
            "status": "processing",
            "jobs_created": ["job1", "job2", "job3"],
            "monitor_url": "/api/platform/status/abc123"
        }
    """
    return platform_request_submit(req)


@app.route(route="platform/status/{request_id}", methods=["GET"])
async def platform_status_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request.

    GET /api/platform/status/{request_id}

    Returns detailed status including all CoreMachine jobs.
    """
    return await platform_request_status(req)


@app.route(route="platform/status", methods=["GET"])
async def platform_status_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all platform requests.

    GET /api/platform/status?limit=100&status=pending

    Returns list of all platform requests with optional filtering.
    """
    return await platform_request_status(req)


# Platform Status Endpoints for DDH Visibility (07 DEC 2025)

@app.route(route="platform/health", methods=["GET"])
async def platform_health_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    Simplified health endpoint for DDH consumption.

    GET /api/platform/health

    Returns high-level system health without internal details.
    Designed for DDH team visibility into processing availability.

    Response:
        {
            "status": "healthy",
            "api_version": "v1.0",
            "components": {
                "job_processing": "healthy",
                "stac_catalog": "healthy",
                "storage": "healthy"
            },
            "recent_activity": {
                "jobs_last_24h": 45,
                "success_rate": "93.3%"
            }
        }
    """
    return await platform_health(req)


@app.route(route="platform/stats", methods=["GET"])
async def platform_stats_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    Aggregated job statistics for DDH visibility.

    GET /api/platform/stats?hours=24

    Returns job processing statistics without exposing internal job IDs.

    Response:
        {
            "period": "24h",
            "jobs": {
                "total": 45,
                "completed": 42,
                "failed": 3
            },
            "by_data_type": {
                "raster": {"total": 30, "completed": 28, "failed": 2},
                "vector": {"total": 15, "completed": 14, "failed": 1}
            },
            "avg_processing_time_minutes": {
                "raster": 8.5,
                "vector": 2.3
            }
        }
    """
    return await platform_stats(req)


@app.route(route="platform/failures", methods=["GET"])
async def platform_failures_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures for DDH troubleshooting.

    GET /api/platform/failures?hours=24&limit=10

    Returns sanitized failure information (no internal paths or stack traces).

    Response:
        {
            "failures": [
                {
                    "request_id": "def456...",
                    "dataset_id": "parcels-2024",
                    "failed_at": "2025-12-07T09:15:00Z",
                    "error_category": "validation_failed",
                    "error_summary": "Source file not found",
                    "can_retry": true
                }
            ],
            "total_failures": 3
        }
    """
    return await platform_failures(req)


# Dedicated Raster Endpoints (05 DEC 2025)
# DDH explicitly chooses endpoint based on single vs multiple files

@app.route(route="platform/raster", methods=["POST"])
def platform_raster(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a single raster file for processing.

    POST /api/platform/raster

    DDH uses this when submitting a single raster file.
    Platform routes to process_raster_v2, with automatic fallback
    to process_large_raster_v2 if file exceeds size threshold.

    Body:
        {
            "dataset_id": "aerial-imagery-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "container_name": "bronze-rasters",
            "file_name": "aerial-alpha.tif",
            "service_name": "Aerial Imagery Site Alpha"
        }

    Note: file_name must be a string (single file), not a list.
    """
    return platform_raster_submit(req)


@app.route(route="platform/raster-collection", methods=["POST"])
def platform_raster_collection(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit multiple raster files as a collection.

    POST /api/platform/raster-collection

    DDH uses this when submitting multiple raster files to be processed
    as a single collection with MosaicJSON.

    Body:
        {
            "dataset_id": "aerial-tiles-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "container_name": "bronze-rasters",
            "file_name": ["tile1.tif", "tile2.tif", "tile3.tif"],
            "service_name": "Aerial Tiles Site Alpha"
        }

    Note: file_name must be a list with at least 2 files.
    """
    return platform_raster_collection_submit(req)


@app.route(route="stac/vector", methods=["POST"])
def stac_vector(req: func.HttpRequest) -> func.HttpResponse:
    """
    Catalog PostGIS vector table in STAC.

    POST /api/stac/vector

    Body:
        {
            "schema": "geo",                        // Required - PostgreSQL schema
            "table_name": "parcels_2025",           // Required - Table name
            "collection_id": "vectors",             // Optional (default: "vectors")
            "source_file": "data/parcels.gpkg",     // Optional - Original source file
            "insert": true,                         // Optional (default: true)
            "properties": {                         // Optional - Custom properties
                "jurisdiction": "county"
            }
        }

    Returns:
        STAC Item metadata and insertion result
    """
    return stac_vector_trigger.handle_request(req)


# ============================================================================
# PGSTAC INSPECTION ENDPOINTS (2 NOV 2025)
# ============================================================================
# Deep inspection endpoints for pgstac schema analysis and statistics
# All read-only operations for monitoring and troubleshooting
# ============================================================================

from infrastructure.pgstac_bootstrap import (
    get_schema_info,
    get_collection_stats,
    get_item_by_id,
    get_health_metrics,
    get_collections_summary
)

@app.route(route="stac/schema/info", methods=["GET"])
def stac_schema_info(req: func.HttpRequest) -> func.HttpResponse:
    """
    Deep inspection of pgstac schema structure.

    GET /api/stac/schema/info

    Returns:
        Detailed schema information including:
        - Tables (with row counts, sizes, indexes)
        - Functions (first 20)
        - Roles
        - Total schema size
    """
    try:
        result = get_schema_info()
        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error in /stac/schema/info: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="stac/collections/summary", methods=["GET"])
def stac_collections_summary(req: func.HttpRequest) -> func.HttpResponse:
    """
    Quick summary of all collections with statistics.

    GET /api/stac/collections/summary

    Returns:
        Summary with total counts and per-collection item counts
    """
    try:
        result = get_collections_summary()
        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error in /stac/collections/summary: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="stac/collections/{collection_id}/stats", methods=["GET"])
def stac_collection_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Detailed statistics for a specific collection.

    GET /api/stac/collections/{collection_id}/stats

    Path Parameters:
        collection_id: Collection ID to analyze

    Returns:
        Collection statistics including:
        - Item count
        - Spatial extent (actual bbox from items)
        - Temporal extent
        - Asset types and counts
        - Recent items
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return func.HttpResponse(
                json.dumps({'error': 'collection_id required'}),
                status_code=400,
                mimetype="application/json"
            )

        result = get_collection_stats(collection_id)
        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error in /stac/collections/{{collection_id}}/stats: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="stac/items/{item_id}", methods=["GET"])
def stac_item_lookup(req: func.HttpRequest) -> func.HttpResponse:
    """
    Look up a single STAC item by ID.

    GET /api/stac/items/{item_id}?collection_id={optional}

    Path Parameters:
        item_id: STAC item ID to retrieve

    Query Parameters:
        collection_id: Optional collection ID to narrow search

    Returns:
        STAC Item JSON or error if not found
    """
    try:
        item_id = req.route_params.get('item_id')
        if not item_id:
            return func.HttpResponse(
                json.dumps({'error': 'item_id required'}),
                status_code=400,
                mimetype="application/json"
            )

        collection_id = req.params.get('collection_id')
        result = get_item_by_id(item_id, collection_id)

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error in /stac/items/{{item_id}}: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="stac/health", methods=["GET"])
def stac_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Overall pgstac health check with metrics.

    GET /api/stac/health

    Returns:
        Health status including:
        - Status (healthy/warning/error)
        - Version
        - Collection/item counts
        - Database size
        - Issues detected
    """
    try:
        result = get_health_metrics()
        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error in /stac/health: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# STAC API STANDARD ENDPOINTS (18 OCT 2025)
# ============================================================================
# Read-only endpoints following STAC API specification
# Interoperable with STAC clients (QGIS, pystac-client, etc.)
# ============================================================================

@app.route(route="collections", methods=["GET"])
def collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all STAC collections (STAC API standard).

    GET /collections

    STAC API Specification: https://github.com/radiantearth/stac-api-spec

    Returns:
        JSON with 'collections' array containing all STAC collections
    """
    from infrastructure.pgstac_bootstrap import get_all_collections

    try:
        result = get_all_collections()

        if 'error' in result:
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=500,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error in /collections endpoint: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="collections/{collection_id}", methods=["GET"])
def collection_detail(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get single STAC collection (STAC API standard).

    GET /collections/{collection_id}

    Path Parameters:
        collection_id: Collection identifier (e.g., "system-vectors")

    Returns:
        STAC Collection object
    """
    from infrastructure.pgstac_bootstrap import get_collection

    try:
        collection_id = req.route_params.get('collection_id')

        if not collection_id:
            return func.HttpResponse(
                json.dumps({'error': 'collection_id required'}),
                status_code=400,
                mimetype="application/json"
            )

        result = get_collection(collection_id)

        if 'error' in result:
            status_code = 404 if result.get('error_type') == 'NotFound' else 500
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=status_code,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error in /collections/{{collection_id}} endpoint: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="collections/{collection_id}/items", methods=["GET"])
def collection_items(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get items in a collection (STAC API standard).

    GET /collections/{collection_id}/items

    Path Parameters:
        collection_id: Collection identifier

    Query Parameters:
        limit: Max items to return (default 100)
        bbox: Bounding box as minx,miny,maxx,maxy
        datetime: Datetime filter (RFC 3339 or interval)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    from infrastructure.pgstac_bootstrap import get_collection_items

    try:
        collection_id = req.route_params.get('collection_id')

        if not collection_id:
            return func.HttpResponse(
                json.dumps({'error': 'collection_id required'}),
                status_code=400,
                mimetype="application/json"
            )

        # Parse query parameters
        limit = int(req.params.get('limit', 100))
        bbox_str = req.params.get('bbox')
        datetime_str = req.params.get('datetime')

        bbox = None
        if bbox_str:
            try:
                bbox = [float(x) for x in bbox_str.split(',')]
                if len(bbox) != 4:
                    raise ValueError("bbox must have 4 values")
            except ValueError as e:
                return func.HttpResponse(
                    json.dumps({'error': f'Invalid bbox: {e}'}),
                    status_code=400,
                    mimetype="application/json"
                )

        result = get_collection_items(
            collection_id=collection_id,
            limit=limit,
            bbox=bbox,
            datetime_str=datetime_str
        )

        if 'error' in result:
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=500,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/geo+json"  # GeoJSON mimetype
        )

    except Exception as e:
        logging.error(f"Error in /collections/{{collection_id}}/items endpoint: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="search", methods=["GET", "POST"])
def stac_search(req: func.HttpRequest) -> func.HttpResponse:
    """
    Search STAC items across collections (STAC API standard).

    GET/POST /search

    Query Parameters (GET) or Body (POST):
        collections: Comma-separated collection IDs (GET) or array (POST)
        bbox: Bounding box as minx,miny,maxx,maxy (GET) or array (POST)
        datetime: Datetime filter (RFC 3339 or interval)
        limit: Max items to return (default 100)
        query: Additional query parameters (POST only)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    from infrastructure.pgstac_bootstrap import search_items

    try:
        # Handle GET and POST differently
        if req.method == "POST":
            # POST body with JSON
            try:
                body = req.get_json()
            except ValueError:
                return func.HttpResponse(
                    json.dumps({'error': 'Invalid JSON body'}),
                    status_code=400,
                    mimetype="application/json"
                )

            collections = body.get('collections')
            bbox = body.get('bbox')
            datetime_str = body.get('datetime')
            limit = body.get('limit', 100)
            query = body.get('query')

        else:
            # GET with query parameters
            collections_str = req.params.get('collections')
            collections = collections_str.split(',') if collections_str else None

            bbox_str = req.params.get('bbox')
            bbox = None
            if bbox_str:
                try:
                    bbox = [float(x) for x in bbox_str.split(',')]
                    if len(bbox) != 4:
                        raise ValueError("bbox must have 4 values")
                except ValueError as e:
                    return func.HttpResponse(
                        json.dumps({'error': f'Invalid bbox: {e}'}),
                        status_code=400,
                        mimetype="application/json"
                    )

            datetime_str = req.params.get('datetime')
            limit = int(req.params.get('limit', 100))
            query = None  # Query extension only supported in POST

        result = search_items(
            collections=collections,
            bbox=bbox,
            datetime_str=datetime_str,
            limit=limit,
            query=query
        )

        if 'error' in result:
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=500,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/geo+json"  # GeoJSON mimetype
        )

    except Exception as e:
        logging.error(f"Error in /search endpoint: {e}")
        return func.HttpResponse(
            json.dumps({'error': str(e)}),
            status_code=500,
            mimetype="application/json"
        )


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
# STAC API v1.0.0 ENDPOINTS (11 NOV 2025)
# ============================================================================
#
# STAC (SpatioTemporal Asset Catalog) API for metadata search and discovery.
# Fully compliant with STAC v1.0.0 specification.
#
# Standards Compliance:
#   - STAC API Core: https://api.stacspec.org/v1.0.0/core
#   - STAC API Collections: https://api.stacspec.org/v1.0.0/collections
#   - STAC API Features: https://api.stacspec.org/v1.0.0/ogcapi-features
#
# Architecture:
#   - Standalone stac_api/ module (zero dependencies on main app)
#   - READ-ONLY: All writes handled by ETL pipeline
#   - Uses infrastructure/stac.py for database operations
#   - All endpoints return STAC-compliant JSON with proper links
#
# Available Endpoints:
#   GET  /api/stac_api                                      - Landing page (catalog root)
#   GET  /api/stac_api/conformance                          - Conformance classes
#   GET  /api/stac_api/collections                          - Collections list
#   GET  /api/stac_api/collections/{collection_id}          - Collection detail
#   GET  /api/stac_api/collections/{collection_id}/items    - Items list (paginated)
#   GET  /api/stac_api/collections/{collection_id}/items/{item_id} - Item detail
#
# Query Parameters:
#   ?limit=N        - Max items per page (default: 10, max: 1000)
#   ?offset=N       - Pagination offset (default: 0)
#   ?bbox=minx,miny,maxx,maxy - Spatial filter (WGS84)

# Get trigger configurations (contains handler references)
_stac_triggers = get_stac_triggers()
_stac_landing = _stac_triggers[0]['handler']
_stac_conformance = _stac_triggers[1]['handler']
_stac_collections = _stac_triggers[2]['handler']
_stac_collection = _stac_triggers[3]['handler']
_stac_items = _stac_triggers[4]['handler']
_stac_item = _stac_triggers[5]['handler']


@app.route(route="stac", methods=["GET"])
def stac_api_v1_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 landing page: GET /api/stac"""
    return _stac_landing(req)


@app.route(route="stac/conformance", methods=["GET"])
def stac_api_v1_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 conformance: GET /api/stac/conformance"""
    return _stac_conformance(req)


@app.route(route="stac/collections", methods=["GET"])
def stac_api_v1_collections(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 collections list: GET /api/stac/collections"""
    return _stac_collections(req)


@app.route(route="stac/collections/{collection_id}", methods=["GET"])
def stac_api_v1_collection(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 collection detail: GET /api/stac/collections/{collection_id}"""
    return _stac_collection(req)


@app.route(route="stac/collections/{collection_id}/items", methods=["GET"])
def stac_api_v1_items(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 items list: GET /api/stac/collections/{collection_id}/items"""
    return _stac_items(req)


@app.route(route="stac/collections/{collection_id}/items/{item_id}", methods=["GET"])
def stac_api_v1_item(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 item detail: GET /api/stac/collections/{collection_id}/items/{item_id}"""
    return _stac_item(req)


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
# PIPELINE DASHBOARD - CONTAINER BLOB BROWSER (21 NOV 2025)
# ============================================================================
# Read-only UI operations - NO JOBS, NO TASKS, NO SERVICE BUS
# Direct Azure Blob Storage queries for Pipeline Dashboard interface

@app.route(route="containers/{container_name}/blobs", methods=["GET"])
def list_container_blobs(req: func.HttpRequest) -> func.HttpResponse:
    """
    List blobs in a container (read-only UI operation).

    GET /api/containers/{container_name}/blobs?prefix={prefix}&limit={limit}

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


@app.route(route="containers/{container_name}/blob", methods=["GET"])
def get_blob_metadata(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get metadata for a single blob (read-only UI operation).

    GET /api/containers/{container_name}/blob?path=maxar/tile_001.tif

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


# ============================================================================
# UNIFIED WEB INTERFACES (14 NOV 2025)
# ============================================================================

from web_interfaces import unified_interface_handler

@app.route(route="interface/{name}", methods=["GET"])
def web_interface_unified(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified web interface handler - dynamic module loading.

    GET /api/interface/{name}

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
# POISON QUEUE MONITORING (HTTP endpoint) - REMOVED (2 OCT 2025)
# Service Bus does not have poison queue monitoring set up yet
# Storage Queue poison monitoring was removed with Storage Queue deprecation
# ============================================================================


# ============================================================================
# SERVICE BUS TRIGGERS - Conditional Registration (11 DEC 2025)
# ============================================================================
# Multi-Function App Architecture: Triggers are conditionally registered based
# on APP_MODE environment variable. This allows identical code to be deployed
# to multiple Function Apps with different queue listening configurations.
#
# THREE QUEUES ONLY (No Legacy Fallbacks):
# - geospatial-jobs: Job orchestration + stage_complete signals
# - raster-tasks: Memory-intensive GDAL operations (low concurrency)
# - vector-tasks: DB-bound and lightweight operations (high concurrency)
#
# All task types MUST be explicitly mapped in TaskRoutingDefaults.
# Unmapped task types raise ContractViolationError (no fallback queue).
#
# See config/app_mode_config.py for mode definitions and queue mappings.
# ============================================================================

# Jobs Queue Trigger - Platform modes only (job orchestration + stage_complete signals)
if _app_mode.listens_to_jobs_queue:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
        """
        Process job messages from Service Bus using CoreMachine.

        EPOCH 4: Uses CoreMachine universal orchestrator instead of controllers.
        Works with ALL job types via registry pattern - no job-specific code needed.

        Multi-App Architecture (07 DEC 2025):
        Handles TWO message types on the jobs queue:
        1. job_submit (default): New job or stage advancement - creates tasks
        2. stage_complete: Signal from worker app that a stage finished

        Performance benefits:
        - No base64 encoding needed (Service Bus handles binary)
        - Better throughput for high-volume scenarios
        - Built-in dead letter queue support
        """
        # Generate correlation_id for function invocation tracing
        # Purpose: Log prefix [abc12345] to filter Application Insights logs for this execution
        # Scope: Local to this function invocation (not propagated to JobQueueMessage.correlation_id)
        # Usage: Search Application Insights: traces | where message contains '[abc12345]'
        # Note: This is different from JobQueueMessage.correlation_id (stage advancement tracking)
        # See: core/schema/queue.py for JobQueueMessage.correlation_id documentation
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(
            f"[{correlation_id}] 🤖 COREMACHINE JOB TRIGGER (Service Bus)",
            extra={
                'checkpoint': 'JOB_TRIGGER_START',
                'correlation_id': correlation_id,
                'trigger_type': 'service_bus',
                'queue_name': 'geospatial-jobs'
            }
        )

        try:
            # Extract message body (no base64 decoding needed for Service Bus)
            message_body = msg.get_body().decode('utf-8')
            logger.info(
                f"[{correlation_id}] 📦 Message size: {len(message_body)} bytes",
                extra={
                    'checkpoint': 'JOB_TRIGGER_RECEIVE_MESSAGE',
                    'correlation_id': correlation_id,
                    'message_size_bytes': len(message_body)
                }
            )

            # Multi-App Architecture (07 DEC 2025): Detect message type
            # Parse as generic dict first to check message_type
            message_dict = json.loads(message_body)
            message_type = message_dict.get('message_type', 'job_submit')

            if message_type == 'stage_complete':
                # Worker app signaling stage completion
                logger.info(
                    f"[{correlation_id}] 📬 Processing stage_complete message from worker",
                    extra={
                        'checkpoint': 'JOB_TRIGGER_STAGE_COMPLETE',
                        'correlation_id': correlation_id,
                        'job_id': message_dict.get('job_id', 'unknown')[:16],
                        'completed_stage': message_dict.get('completed_stage'),
                        'completed_by_app': message_dict.get('completed_by_app', 'unknown')
                    }
                )
                result = core_machine.process_stage_complete_message(message_dict)
            else:
                # Standard job message (job_submit or stage advancement)
                job_message = JobQueueMessage.model_validate_json(message_body)
                logger.info(
                    f"[{correlation_id}] ✅ Parsed job: {job_message.job_id[:16]}..., type={job_message.job_type}",
                    extra={
                        'checkpoint': 'JOB_TRIGGER_PARSE_SUCCESS',
                        'correlation_id': correlation_id,
                        'job_id': job_message.job_id,
                        'job_type': job_message.job_type,
                        'stage': job_message.stage
                    }
                )

                # Add correlation ID for tracking
                if job_message.parameters is None:
                    job_message.parameters = {}
                job_message.parameters['_correlation_id'] = correlation_id
                job_message.parameters['_processing_path'] = 'service_bus'

                # EPOCH 4: Process via CoreMachine (universal orchestrator)
                result = core_machine.process_job_message(job_message)

            elapsed = time.time() - start_time
            logger.info(f"[{correlation_id}] ✅ CoreMachine processed in {elapsed:.3f}s")
            logger.info(f"[{correlation_id}] 📊 Result: {result}")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[{correlation_id}] ❌ EXCEPTION in process_service_bus_job after {elapsed:.3f}s")
            logger.error(f"[{correlation_id}] 📍 Exception type: {type(e).__name__}")
            logger.error(f"[{correlation_id}] 📍 Exception message: {e}")
            logger.error(f"[{correlation_id}] 📍 Full traceback:\n{traceback.format_exc()}")

            # Extract job_id from either job_message or message_dict (stage_complete)
            job_id = None
            if 'job_message' in locals() and job_message:
                job_id = job_message.job_id
                logger.error(f"[{correlation_id}] 📋 Job ID: {job_message.job_id}")
                logger.error(f"[{correlation_id}] 📋 Job Type: {job_message.job_type}")
                logger.error(f"[{correlation_id}] 📋 Stage: {job_message.stage}")
            elif 'message_dict' in locals() and message_dict:
                job_id = message_dict.get('job_id')
                logger.error(f"[{correlation_id}] 📋 Job ID (from stage_complete): {job_id}")
                logger.error(f"[{correlation_id}] 📋 Message Type: {message_dict.get('message_type')}")
                logger.error(f"[{correlation_id}] 📋 Completed Stage: {message_dict.get('completed_stage')}")

            # FP1 FIX: Mark job as FAILED in database to prevent stuck jobs
            if job_id:
                try:
                    repos = RepositoryFactory.create_repositories()
                    job_repo = repos['job_repo']

                    error_msg = f"Job processing exception: {type(e).__name__}: {e}"
                    job_repo.mark_failed(job_id, error_msg)

                    logger.info(f"[{correlation_id}] ✅ Job {job_id[:16]}... marked as FAILED in database")

                except Exception as cleanup_error:
                    logger.error(f"[{correlation_id}] ❌ Failed to mark job as FAILED: {cleanup_error}")
                    logger.error(f"[{correlation_id}] 💀 Job {job_id[:16]}... may be stuck - requires manual cleanup")
            else:
                logger.error(f"[{correlation_id}] ⚠️ No job_id available - cannot mark job as FAILED")
                logger.error(f"[{correlation_id}] 📍 Exception occurred before message parsing")

            # NOTE: Job processing errors are typically critical (workflow creation failures).
            # Unlike task retries, jobs don't have application-level retry logic.
            # Log extensively but don't re-raise to avoid Service Bus retries for job messages.
            logger.warning(f"[{correlation_id}] ⚠️ Function completing (exception logged but not re-raised)")
            logger.warning(f"[{correlation_id}] ✅ Job failure handling complete")


# Raster Tasks Queue Trigger - Raster worker/platform_raster/standalone modes
if _app_mode.listens_to_raster_tasks:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="raster-tasks",
        connection="ServiceBusConnection"
    )
    def process_raster_task(msg: func.ServiceBusMessage) -> None:
        """
        Process raster task messages from dedicated raster-tasks queue.

        Multi-App Architecture (07 DEC 2025):
        - Dedicated queue for GDAL/raster operations
        - Separate Function App can use host.json with maxConcurrentCalls: 2
        - Memory-intensive operations (2-8GB per task)

        Task types routed here:
        - handler_raster_validate, handler_raster_create_cog
        - handler_stac_raster_item, validate_raster, create_cog
        - extract_stac_metadata, create_tiling_scheme, extract_tile
        """
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(
            f"[{correlation_id}] 🗺️ RASTER TASK TRIGGER (raster-tasks queue)",
            extra={
                'checkpoint': 'RASTER_TASK_TRIGGER_START',
                'correlation_id': correlation_id,
                'queue_name': 'raster-tasks'
            }
        )

        try:
            message_body = msg.get_body().decode('utf-8')
            task_message = TaskQueueMessage.model_validate_json(message_body)
            logger.info(f"[{correlation_id}] ✅ Parsed raster task: {task_message.task_id}, type={task_message.task_type}")

            if task_message.parameters is None:
                task_message.parameters = {}
            task_message.parameters['_correlation_id'] = correlation_id
            task_message.parameters['_processing_path'] = 'raster-tasks'

            result = core_machine.process_task_message(task_message)

            elapsed = time.time() - start_time
            logger.info(f"[{correlation_id}] ✅ Raster task processed in {elapsed:.3f}s")
            logger.info(f"[{correlation_id}] 📊 Result: {result}")

            if result.get('stage_complete'):
                logger.info(f"[{correlation_id}] 🎯 Stage {task_message.stage} complete for job {task_message.parent_job_id[:16]}...")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[{correlation_id}] ❌ EXCEPTION in process_raster_task after {elapsed:.3f}s")
            logger.error(f"[{correlation_id}] 📍 Exception type: {type(e).__name__}")
            logger.error(f"[{correlation_id}] 📍 Exception message: {e}")
            logger.error(f"[{correlation_id}] 📍 Full traceback:\n{traceback.format_exc()}")

            if 'task_message' in locals() and task_message:
                logger.error(f"[{correlation_id}] 📋 Task ID: {task_message.task_id}")
                logger.error(f"[{correlation_id}] 📋 Task Type: {task_message.task_type}")
                logger.error(f"[{correlation_id}] 📋 Job ID: {task_message.parent_job_id}")

            logger.warning(f"[{correlation_id}] ⚠️ Function completing (CoreMachine handled failure internally)")


# Vector Tasks Queue Trigger - Vector worker/platform_vector/standalone modes
if _app_mode.listens_to_vector_tasks:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="vector-tasks",
        connection="ServiceBusConnection"
    )
    def process_vector_task(msg: func.ServiceBusMessage) -> None:
        """
        Process vector task messages from dedicated vector-tasks queue.

        Multi-App Architecture (07 DEC 2025):
        - Dedicated queue for geopandas/PostGIS operations
        - Separate Function App can use host.json with maxConcurrentCalls: 32
        - DB-bound operations (20-200MB per task)

        Task types routed here:
        - handler_vector_prepare, handler_vector_upload
        - handler_stac_vector_item, process_vector_prepare
        - process_vector_upload, create_vector_stac
        """
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(
            f"[{correlation_id}] 📍 VECTOR TASK TRIGGER (vector-tasks queue)",
            extra={
                'checkpoint': 'VECTOR_TASK_TRIGGER_START',
                'correlation_id': correlation_id,
                'queue_name': 'vector-tasks'
            }
        )

        try:
            message_body = msg.get_body().decode('utf-8')
            task_message = TaskQueueMessage.model_validate_json(message_body)
            logger.info(f"[{correlation_id}] ✅ Parsed vector task: {task_message.task_id}, type={task_message.task_type}")

            if task_message.parameters is None:
                task_message.parameters = {}
            task_message.parameters['_correlation_id'] = correlation_id
            task_message.parameters['_processing_path'] = 'vector-tasks'

            result = core_machine.process_task_message(task_message)

            elapsed = time.time() - start_time
            logger.info(f"[{correlation_id}] ✅ Vector task processed in {elapsed:.3f}s")
            logger.info(f"[{correlation_id}] 📊 Result: {result}")

            if result.get('stage_complete'):
                logger.info(f"[{correlation_id}] 🎯 Stage {task_message.stage} complete for job {task_message.parent_job_id[:16]}...")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[{correlation_id}] ❌ EXCEPTION in process_vector_task after {elapsed:.3f}s")
            logger.error(f"[{correlation_id}] 📍 Exception type: {type(e).__name__}")
            logger.error(f"[{correlation_id}] 📍 Exception message: {e}")
            logger.error(f"[{correlation_id}] 📍 Full traceback:\n{traceback.format_exc()}")

            if 'task_message' in locals() and task_message:
                logger.error(f"[{correlation_id}] 📋 Task ID: {task_message.task_id}")
                logger.error(f"[{correlation_id}] 📋 Task Type: {task_message.task_type}")
                logger.error(f"[{correlation_id}] 📋 Job ID: {task_message.parent_job_id}")

            logger.warning(f"[{correlation_id}] ⚠️ Function completing (CoreMachine handled failure internally)")


# ============================================================================
# QUEUE ERROR HANDLING HELPER FUNCTIONS
# ============================================================================

def _extract_job_id_from_raw_message(message_content: str, correlation_id: str = "unknown") -> Optional[str]:
    """Try to extract job_id from potentially malformed message.

    Args:
        message_content: Raw message content that may be malformed
        correlation_id: Correlation ID for logging

    Returns:
        job_id if found, None otherwise
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueErrorHandler")

    # Try JSON parsing first
    try:
        data = json.loads(message_content)
        job_id = data.get('job_id')
        if job_id:
            logger.info(f"[{correlation_id}] 🔍 Extracted job_id via JSON: {job_id[:16]}...")
            return job_id
    except Exception:
        pass  # Try regex next

    # Try regex as fallback
    try:
        match = re.search(r'"job_id"\s*:\s*"([^"]+)"', message_content)
        if match:
            job_id = match.group(1)
            logger.info(f"[{correlation_id}] 🔍 Extracted job_id via regex: {job_id[:16]}...")
            return job_id
    except Exception:
        pass

    logger.warning(f"[{correlation_id}] ⚠️ Could not extract job_id from message")
    return None


def _extract_task_id_from_raw_message(message_content: str, correlation_id: str = "unknown") -> tuple[Optional[str], Optional[str]]:
    """Try to extract task_id and parent_job_id from potentially malformed message.

    Args:
        message_content: Raw message content that may be malformed
        correlation_id: Correlation ID for logging

    Returns:
        Tuple of (task_id, parent_job_id) if found, (None, None) otherwise
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueErrorHandler")
    task_id = None
    parent_job_id = None

    # Try JSON parsing first
    try:
        data = json.loads(message_content)
        task_id = data.get('task_id')
        parent_job_id = data.get('parent_job_id')
        if task_id:
            logger.info(f"[{correlation_id}] 🔍 Extracted task_id via JSON: {task_id}")
        if parent_job_id:
            logger.info(f"[{correlation_id}] 🔍 Extracted parent_job_id via JSON: {parent_job_id[:16]}...")
    except Exception:
        # Try regex as fallback
        try:
            task_match = re.search(r'"task_id"\s*:\s*"([^"]+)"', message_content)
            if task_match:
                task_id = task_match.group(1)
                logger.info(f"[{correlation_id}] 🔍 Extracted task_id via regex: {task_id}")

            job_match = re.search(r'"parent_job_id"\s*:\s*"([^"]+)"', message_content)
            if job_match:
                parent_job_id = job_match.group(1)
                logger.info(f"[{correlation_id}] 🔍 Extracted parent_job_id via regex: {parent_job_id[:16]}...")
        except Exception:
            pass

    if not task_id and not parent_job_id:
        logger.warning(f"[{correlation_id}] ⚠️ Could not extract task_id or parent_job_id from message")

    return task_id, parent_job_id


def _mark_job_failed_from_queue_error(job_id: str, error_msg: str, correlation_id: str = "unknown") -> None:
    """Helper to mark job as failed when queue processing fails.

    Args:
        job_id: Job ID to mark as failed
        error_msg: Error message to record
        correlation_id: Correlation ID for logging
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueErrorHandler")

    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        # Check if job exists and isn't already failed
        job = job_repo.get_job(job_id)
        if job and job.status not in [JobStatus.FAILED, JobStatus.COMPLETED]:
            job_repo.update_job_status_with_validation(
                job_id=job_id,
                new_status=JobStatus.FAILED,
                additional_updates={
                    'error_details': f"Queue processing error: {error_msg}",
                    'failed_at': datetime.now(timezone.utc).isoformat(),
                    'queue_correlation_id': correlation_id
                }
            )
            logger.info(f"[{correlation_id}] 📝 Job {job_id[:16]}... marked as FAILED before poison queue")
        elif job and job.status == JobStatus.FAILED:
            logger.info(f"[{correlation_id}] ℹ️ Job {job_id[:16]}... already marked as FAILED")
        elif job and job.status == JobStatus.COMPLETED:
            logger.warning(f"[{correlation_id}] ⚠️ Job {job_id[:16]}... is COMPLETED but queue error occurred")
        else:
            logger.error(f"[{correlation_id}] ❌ Job {job_id[:16]}... not found in database")
    except Exception as e:
        logger.error(f"[{correlation_id}] ❌ Failed to mark job {job_id[:16]}... as failed: {e}")


def _mark_task_failed_from_queue_error(task_id: str, parent_job_id: Optional[str], error_msg: str, correlation_id: str = "unknown") -> None:
    """Helper to mark task as failed when queue processing fails.

    Args:
        task_id: Task ID to mark as failed
        parent_job_id: Parent job ID if known
        error_msg: Error message to record
        correlation_id: Correlation ID for logging
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueErrorHandler")

    try:
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']

        # Check if task exists and isn't already failed
        task = task_repo.get_task(task_id)
        if task and task.status not in [TaskStatus.FAILED, TaskStatus.COMPLETED]:
            # Create type-safe update model
            update = TaskUpdateModel(
                status=TaskStatus.FAILED,
                error_details=f"Queue processing error: {error_msg}"
            )
            task_repo.update_task(task_id=task_id, updates=update)
            logger.info(f"[{correlation_id}] 📝 Task {task_id} marked as FAILED before poison queue")

            # Also update parent job if known
            if parent_job_id:
                _mark_job_failed_from_queue_error(
                    parent_job_id,
                    f"Task {task_id} failed in queue processing",
                    correlation_id
                )
        elif task and task.status == TaskStatus.FAILED:
            logger.info(f"[{correlation_id}] ℹ️ Task {task_id} already marked as FAILED")
        elif task and task.status == TaskStatus.COMPLETED:
            logger.warning(f"[{correlation_id}] ⚠️ Task {task_id} is COMPLETED but queue error occurred")
        else:
            logger.error(f"[{correlation_id}] ❌ Task {task_id} not found in database")
    except Exception as e:
        logger.error(f"[{correlation_id}] ❌ Failed to mark task {task_id} as failed: {e}")


# ============================================================================
# JANITOR TIMER TRIGGERS - System Maintenance (21 NOV 2025)
# ============================================================================
# Janitor is a standalone maintenance subsystem (NOT a CoreMachine job).
# This avoids circular dependency - janitor can't clean itself if stuck.
#
# Timer Schedule Rationale (22 NOV 2025):
# - Task timeout is 30 min, so checking more frequently is wasteful
# - All janitors run every 30 min for consistent, predictable behavior
# - HTTP endpoints available for immediate on-demand runs
#
# Three timers for different maintenance operations:
# 1. Task Watchdog: Detect stale PROCESSING tasks (Azure Functions timeout)
# 2. Job Health: Detect jobs with failed tasks, propagate failure
# 3. Orphan Detector: Find orphaned tasks, zombie jobs, stuck queued jobs
#
# Configuration via environment variables:
# - JANITOR_ENABLED: true/false (default: true)
# - JANITOR_TASK_TIMEOUT_MINUTES: 30 (Azure Functions max timeout)
# - JANITOR_JOB_STALE_HOURS: 24 (max reasonable job duration)
# - JANITOR_QUEUED_TIMEOUT_HOURS: 1 (max time in QUEUED state)
# ============================================================================

@app.timer_trigger(
    schedule="0 */5 * * * *",  # Every 5 minutes (15 DEC 2025 - orphan recovery with queue peek)
    arg_name="timer",
    run_on_startup=False
)
def janitor_task_watchdog(timer: func.TimerRequest) -> None:
    """
    Detect and mark stale PROCESSING tasks as FAILED.
    Also re-queues orphaned QUEUED tasks (message loss recovery).

    Tasks stuck in PROCESSING for > 30 minutes have silently failed
    (Azure Functions max execution time is 10-30 minutes).

    Tasks stuck in QUEUED for > 5 minutes with NO message in queue
    are re-queued (defense against message loss). Queue is peeked
    to verify message is actually missing before re-queueing.

    Schedule: Every 5 minutes - fast detection of orphaned queued tasks
    """
    task_watchdog_handler(timer)


@app.timer_trigger(
    schedule="0 15,45 * * * *",  # At :15 and :45 past each hour
    arg_name="timer",
    run_on_startup=False
)
def janitor_job_health(timer: func.TimerRequest) -> None:
    """
    Check job health and propagate task failures.

    Finds PROCESSING jobs with failed tasks and marks them as FAILED.
    Captures partial results from completed tasks for debugging.

    Schedule: Every 30 minutes, offset from task_watchdog by 15 min
    This runs AFTER task_watchdog has marked failed tasks, allowing
    proper failure propagation to job level.
    """
    job_health_handler(timer)


@app.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def janitor_orphan_detector(timer: func.TimerRequest) -> None:
    """
    Detect and handle orphaned tasks and zombie jobs.

    Detects:
    1. Orphaned tasks (parent job doesn't exist)
    2. Zombie jobs (PROCESSING but all tasks terminal)
    3. Stuck QUEUED jobs (no tasks created after timeout)
    4. Ancient stale jobs (PROCESSING > 24 hours)

    Schedule: Every hour - these are edge cases, not time-critical
    """
    orphan_detector_handler(timer)


@app.timer_trigger(
    schedule="0 0 */6 * * *",  # Every 6 hours at minute 0
    arg_name="timer",
    run_on_startup=False
)
def geo_orphan_check_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check for geo schema orphans every 6 hours.

    Detects:
    1. Orphaned Tables: Tables in geo schema without metadata records
    2. Orphaned Metadata: Metadata records for non-existent tables

    Detection only - does NOT auto-delete. Logs findings to Application Insights.

    Schedule: Every 6 hours - low overhead monitoring for data integrity
    """
    from services.janitor_service import geo_orphan_detector
    from util_logger import LoggerFactory, ComponentType

    timer_logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "geo_orphan_timer")
    timer_logger.info("⏰ Timer: Starting geo orphan detection")

    result = geo_orphan_detector.run()

    if result.get("success"):
        summary = result.get("summary", {})
        timer_logger.info(
            f"⏰ Timer: Geo orphan check complete - "
            f"{summary.get('tracked', 0)} tracked, "
            f"{summary.get('orphaned_tables', 0)} orphaned tables, "
            f"{summary.get('orphaned_metadata', 0)} orphaned metadata, "
            f"status={summary.get('health_status', 'UNKNOWN')}"
        )
    else:
        timer_logger.error(f"⏰ Timer: Geo orphan check failed - {result.get('error')}")


# ============================================================================
# CURATED DATASET SCHEDULER (15 DEC 2025)
# ============================================================================
# Daily timer trigger to check for curated datasets that need updating.
# Runs at 2 AM UTC - datasets checked against their update_schedule.
# Submits curated_dataset_update jobs for datasets that are due.
# ============================================================================

@app.timer_trigger(
    schedule="0 0 2 * * *",  # Daily at 2 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def curated_dataset_scheduler(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check curated datasets for updates daily at 2 AM.

    Checks all enabled datasets with schedules and submits update jobs
    for those that are due.

    Schedule: Daily at 2 AM UTC (most datasets update weekly at most)
    """
    curated_scheduler_trigger.handle_timer(timer)


# ============================================================================
# JANITOR HTTP ENDPOINTS - Manual Triggering and Status (21 NOV 2025)
# ============================================================================
# These endpoints allow manual janitor operations for testing and debugging.
# Useful for:
# - Testing janitor logic before deploying timer triggers
# - On-demand cleanup after known issues
# - Monitoring janitor health and activity
# ============================================================================

# NOTE: Using /api/cleanup/* instead of /api/admin/janitor/* because Azure Functions
# reserves /api/admin/* for built-in admin UI (returns 404)
@app.route(route="cleanup/run", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_run(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually trigger a cleanup (janitor) run.

    POST /api/cleanup/run?type={task_watchdog|job_health|orphan_detector|all}

    Examples:
        curl -X POST "https://.../api/cleanup/run?type=task_watchdog"
        curl -X POST "https://.../api/cleanup/run?type=all"
    """
    return janitor_run_handler(req)


@app.route(route="cleanup/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get current cleanup (janitor) status and configuration.

    GET /api/cleanup/status

    Returns config, enabled status, and last 24h statistics.
    """
    return janitor_status_handler(req)


@app.route(route="cleanup/history", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_history(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get recent cleanup (janitor) run history.

    GET /api/cleanup/history?hours=24&type=task_watchdog&limit=50

    Query Parameters:
        hours: How many hours of history (default: 24, max: 168)
        type: Filter by run type (optional)
        limit: Max records to return (default: 50, max: 200)
    """
    return janitor_history_handler(req)
