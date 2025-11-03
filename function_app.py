# ============================================================================
# CLAUDE CONTEXT - AZURE FUNCTIONS ENTRY POINT
# ============================================================================
# EPOCH: SHARED - BOTH EPOCHS
# STATUS: Epoch 4
# NOTE: Careful migration required
# PURPOSE: Azure Functions entry point orchestrating the geospatial ETL pipeline with HTTP and queue triggers
# EXPORTS: app (Function App), core_machine (CoreMachine orchestrator)
# INTERFACES: Azure Functions triggers via @app decorators (http_trigger, queue_trigger, timer_trigger)
# PYDANTIC_MODELS: JobQueueMessage, TaskQueueMessage, various trigger request/response models
# DEPENDENCIES: azure.functions, triggers/*, core.machine (CoreMachine), infrastructure.*, util_logger
# SOURCE: HTTP requests, Azure Storage Queues (geospatial-jobs, geospatial-tasks), timer schedules
# SCOPE: Global application entry point managing all Azure Function triggers and explicit registration
# VALIDATION: Request validation via trigger classes, queue message validation via Pydantic models
# PATTERNS: Explicit Registration pattern (no decorators), Catalog pattern, Dependency Injection
# ENTRY_POINTS: Azure Functions runtime calls app routes; main entry: /api/jobs/submit/{job_type}, /api/platform/submit
# INDEX: Registration:170-200, HTTP routes:210-350, Queue processors:400-600, Database queries:278-332
# LAST_UPDATED: 29 OCT 2025 - Added Platform database query endpoints
# ============================================================================

"""
Azure Functions App for Geospatial ETL Pipeline - REDESIGN ARCHITECTURE.

This module serves as the entry point for the Azure Functions-based geospatial
ETL pipeline. It provides HTTP endpoints for job submission and status checking,
queue-based asynchronous processing, and comprehensive health monitoring.

🏗️ EPOCH 4 ARCHITECTURE (1 October 2025):
    HTTP API or Service Bus → CoreMachine → Workflow (@register_job) → Tasks → Service Bus
                                   ↓              ↓                        ↓
                              Job Record    Pydantic Validation    Task Records
                          (PostgreSQL)      (Strong Typing)    (Service Layer Execution)
                                                                        ↓
                                                               Storage/Database/STAC
                                                           (PostgreSQL/PostGIS/Blob)

Job → Stage → Task Pattern:
    ✅ CLEAN ARCHITECTURE WITH DECLARATIVE WORKFLOWS
    - CoreMachine: Universal orchestrator (composition over inheritance)
    - @register_job: Declarative workflow registration
    - @register_task: Declarative task handler registration
    - Sequential stages with parallel tasks within each stage
    - Data-Behavior Separation: TaskData/JobData (data) + TaskExecutor/Workflow (behavior)  
    - "Last task turns out the lights" completion pattern
    - Strong typing discipline with explicit error handling (no fallbacks)
    - Clear separation: Controller (orchestration) vs Task (business logic)

Key Features:
    - Pydantic-based workflow definitions with strong typing discipline
    - Job→Task architecture with controller pattern
    - Idempotent job processing with SHA256-based deduplication
    - Queue-based async processing with poison queue monitoring
    - Managed identity authentication with user delegation SAS
    - Support for files up to 20GB with smart metadata extraction
    - Comprehensive STAC cataloging with PostGIS integration
    - Explicit error handling (no legacy fallbacks or compatibility layers)
    - Enhanced logging with visual indicators for debugging

Endpoints:
    Core System:
    GET  /api/health - System health check with component status

    CoreMachine Layer:
    POST /api/jobs/submit/{job_type} - Submit processing job
    GET  /api/jobs/status/{job_id} - Get job status and results

    Platform Layer:
    POST /api/platform/submit - Submit Platform API request
    GET  /api/platform/status/{request_id} - Get Platform request status

    Database Queries (DEV/TEST):
    GET  /api/db/jobs?status=failed&limit=10 - Query jobs
    GET  /api/db/tasks/{job_id} - Query tasks for job
    GET  /api/db/api_requests?limit=10 - Query Platform API requests (NEW 29 OCT 2025)
    GET  /api/db/orchestration_jobs/{request_id} - Query Platform orchestration (NEW 29 OCT 2025)
    GET  /api/db/stats - Database statistics

    Monitoring:
    GET  /api/monitor/poison - Check poison queue status
    POST /api/monitor/poison - Process poison messages

    Schema Management (DEV ONLY):
    POST /api/db/schema/nuke - Drop all schema objects (dev only)
    POST /api/db/schema/redeploy - Nuke and redeploy schema (dev only)

Supported Operations:
    Pydantic Workflow Definition Pattern (Job→Task Architecture):
    - hello_world: Fully implemented with controller routing and workflow validation

Processing Pattern - Pydantic Job→Task Queue Architecture:
    1. HTTP Request Processing:
       - HTTP request triggers workflow definition validation
       - Controller creates job record and stages based on workflow definition
       - Each stage creates parallel tasks with parameter validation
       - Job queued to geospatial-jobs queue for asynchronous processing
       - Explicit error handling with no fallback compatibility
       
    2. Queue-Based Task Execution:
       - geospatial-jobs queue: Job messages from controllers
       - geospatial-tasks queue: Task messages for atomic work units
       - Tasks processed independently with strong typing discipline
       - Last completing task aggregates results into job result_data
       - Poison queues monitor and recover failed messages
       - Each queue has dedicated Azure Function triggers for scalability

Environment Variables:
    STORAGE_ACCOUNT_NAME: Azure storage account name
    AzureWebJobsStorage: Connection string for Functions runtime
    ENABLE_DATABASE_CHECK: Enable PostgreSQL health checks (optional)
    POSTGIS_HOST: PostgreSQL host for STAC catalog
    POSTGIS_DATABASE: PostgreSQL database name
    POSTGIS_USER: PostgreSQL username
    POSTGIS_PASSWORD: PostgreSQL password

Author: Azure Geospatial ETL Team
Version: 2.1.0
Last Updated: January 2025
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
from triggers.submit_job import submit_job_trigger
from triggers.get_job_status import get_job_status_trigger
from triggers.poison_monitor import poison_monitor_trigger
from triggers.schema_pydantic_deploy import pydantic_deploy_trigger
from triggers.db_query import (
    jobs_query_trigger,
    tasks_query_trigger,
    api_requests_query_trigger,
    orchestration_jobs_query_trigger,
    db_stats_trigger,
    enum_diagnostic_trigger,
    schema_nuke_trigger,
    function_test_trigger
)
from triggers.analyze_container import analyze_container_trigger
from triggers.stac_setup import stac_setup_trigger
from triggers.stac_collections import stac_collections_trigger
from triggers.stac_init import stac_init_trigger
from triggers.stac_extract import stac_extract_trigger
from triggers.stac_vector import stac_vector_trigger
from triggers.stac_nuke import stac_nuke_trigger
from triggers.ingest_vector import ingest_vector_trigger
from triggers.test_raster_create import test_raster_create_trigger

# Platform Service Layer triggers (25 OCT 2025)
from triggers.trigger_platform import platform_request_submit
from triggers.trigger_platform_status import platform_request_status

# OGC Features API - Standalone module (29 OCT 2025)
from ogc_features import get_ogc_triggers

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
# It works with ALL jobs via EXPLICIT registries (no decorator magic!)
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





@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint using HTTP trigger base class."""
    return health_check_trigger.handle_request(req)


@app.route(route="jobs/submit/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/status/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)




# Database Query Endpoints - Phase 2 Database Monitoring
@app.route(route="db/jobs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query jobs with filtering: GET /api/db/jobs?limit=10&status=processing&hours=24"""
    return jobs_query_trigger.handle_request(req)


@app.route(route="db/jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS) 
def query_job_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get specific job by ID: GET /api/db/jobs/{job_id}"""
    return jobs_query_trigger.handle_request(req)


@app.route(route="db/tasks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_tasks(req: func.HttpRequest) -> func.HttpResponse:
    """Query tasks with filtering: GET /api/db/tasks?status=failed&limit=20"""
    return tasks_query_trigger.handle_request(req)


@app.route(route="db/tasks/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_tasks_for_job(req: func.HttpRequest) -> func.HttpResponse:
    """Get all tasks for a job: GET /api/db/tasks/{job_id}"""
    return tasks_query_trigger.handle_request(req)


# Platform Layer Query Endpoints (29 OCT 2025)
@app.route(route="db/api_requests", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_api_requests(req: func.HttpRequest) -> func.HttpResponse:
    """Query API requests with filtering: GET /api/db/api_requests?limit=10&status=processing"""
    return api_requests_query_trigger.handle_request(req)


@app.route(route="db/api_requests/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_api_request_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get specific API request by ID: GET /api/db/api_requests/{request_id}"""
    return api_requests_query_trigger.handle_request(req)


@app.route(route="db/orchestration_jobs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_orchestration_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query orchestration jobs with filtering: GET /api/db/orchestration_jobs?request_id={request_id}"""
    return orchestration_jobs_query_trigger.handle_request(req)


@app.route(route="db/orchestration_jobs/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def query_orchestration_jobs_for_request(req: func.HttpRequest) -> func.HttpResponse:
    """Get orchestration jobs for specific request: GET /api/db/orchestration_jobs/{request_id}"""
    return orchestration_jobs_query_trigger.handle_request(req)


@app.route(route="db/stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def database_stats(req: func.HttpRequest) -> func.HttpResponse:
    """Database statistics and health metrics: GET /api/db/stats"""
    return db_stats_trigger.handle_request(req)


@app.route(route="db/enums/diagnostic", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diagnose_enums(req: func.HttpRequest) -> func.HttpResponse:
    """Diagnose PostgreSQL enum types: GET /api/db/enums/diagnostic"""
    return enum_diagnostic_trigger.handle_request(req)


# 🚨 NUCLEAR RED BUTTON - DEVELOPMENT ONLY
@app.route(route="db/schema/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def nuclear_schema_reset(req: func.HttpRequest) -> func.HttpResponse:
    """🚨 NUCLEAR: Complete schema wipe and rebuild: POST /api/db/schema/nuke?confirm=yes"""
    return schema_nuke_trigger.handle_request(req)


# 🔄 CONSOLIDATED REBUILD - DEVELOPMENT ONLY
@app.route(route="db/schema/redeploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)  
def redeploy_schema(req: func.HttpRequest) -> func.HttpResponse:
    """
    🔄 REDEPLOY: Clean schema reset for development.
    POST /api/db/schema/redeploy?confirm=yes
    
    Single unified endpoint that:
    1. Drops ALL objects using Python discovery (no DO blocks)
    2. Deploys fresh schema from Pydantic models
    3. Uses psycopg.sql composition throughout
    
    Perfect for development deployments and testing.
    """
    # Imports moved to top of file
    
    # Check for confirmation
    confirm = req.params.get('confirm')
    if confirm != 'yes':
        return func.HttpResponse(
            body=json.dumps({
                "error": "Schema redeploy requires explicit confirmation",
                "usage": "POST /api/db/schema/redeploy?confirm=yes",
                "warning": "This will DESTROY ALL DATA and rebuild the schema",
                "implementation": "Clean Python-based discovery with psycopg.sql composition"
            }),
            status_code=400,
            headers={'Content-Type': 'application/json'}
        )
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": "schema_redeploy",
        "steps": []
    }
    
    # Step 1: Nuke the schema (clean Python implementation)
    nuke_response = schema_nuke_trigger.handle_request(req)
    nuke_data = json.loads(nuke_response.get_body())
    results["steps"].append({
        "step": "nuke_schema",
        "status": nuke_data.get("status", "failed"),
        "objects_dropped": nuke_data.get("total_objects_dropped", 0),
        "details": nuke_data.get("operations", [])
    })
    
    # Only proceed with deploy if nuke succeeded
    if nuke_response.status_code == 200:
        # Step 2: Deploy fresh schema
        # Import moved to top of file
        deploy_response = pydantic_deploy_trigger.handle_request(req)
        deploy_data = json.loads(deploy_response.get_body())
        results["steps"].append({
            "step": "deploy_schema",
            "status": deploy_data.get("status", "failed"),
            "objects_created": deploy_data.get("statistics", {}),
            "verification": deploy_data.get("verification", {})
        })

        # Step 3: Create System STAC collections (18 OCT 2025 - System STAC Layer 1)
        import logging
        logging.info("=" * 80)
        logging.info("🚀 REACHED STEP 3 CODE BLOCK")
        logging.info(f"🔍 Step 3 check: deploy_response.status_code = {deploy_response.status_code}")
        logging.info(f"📋 Current results steps count: {len(results.get('steps', []))}")
        logging.info("=" * 80)

        if deploy_response.status_code == 200:
            logging.info("📦 Step 3: Creating System STAC collections")
            stac_collections_result = {"collections_created": [], "collections_failed": []}
            try:
                from infrastructure.stac import StacInfrastructure
                logging.info("✅ StacInfrastructure imported")
                stac = StacInfrastructure()
                logging.info("✅ StacInfrastructure initialized")

                # Create system-vectors collection (database-level idempotency)
                logging.info("🔄 Creating system-vectors collection...")
                result = stac.create_production_collection('system-vectors')
                logging.info(f"✅ system-vectors result: {result}")

                if result.get('success'):
                    # Success - collection created or already existed
                    if result.get('existed'):
                        stac_collections_result["collections_created"].append('system-vectors (already exists)')
                        logging.info("ℹ️ system-vectors already exists (idempotent)")
                    else:
                        stac_collections_result["collections_created"].append('system-vectors')
                        logging.info("✅ system-vectors created")
                else:
                    # Real failure
                    stac_collections_result["collections_failed"].append({
                        "collection": "system-vectors",
                        "error": result.get('error', 'Unknown error')
                    })

                # Create system-rasters collection (database-level idempotency)
                logging.info("🔄 Creating system-rasters collection...")
                result = stac.create_production_collection('system-rasters')
                logging.info(f"✅ system-rasters result: {result}")

                if result.get('success'):
                    # Success - collection created or already existed
                    if result.get('existed'):
                        stac_collections_result["collections_created"].append('system-rasters (already exists)')
                        logging.info("ℹ️ system-rasters already exists (idempotent)")
                    else:
                        stac_collections_result["collections_created"].append('system-rasters')
                        logging.info("✅ system-rasters created")
                else:
                    # Real failure
                    stac_collections_result["collections_failed"].append({
                        "collection": "system-rasters",
                        "error": result.get('error', 'Unknown error')
                    })

                stac_collections_result["status"] = "success" if len(stac_collections_result["collections_created"]) == 2 else "partial"
                logging.info(f"📊 STAC collections result: {stac_collections_result}")

            except Exception as e:
                logging.error(f"❌ Step 3 exception: {e}")
                import traceback
                logging.error(f"Traceback: {traceback.format_exc()}")
                stac_collections_result["status"] = "failed"
                stac_collections_result["error"] = str(e)

            logging.info(f"📝 Appending Step 3 to results: {stac_collections_result}")
            results["steps"].append({
                "step": "create_system_stac_collections",
                "status": stac_collections_result.get("status", "failed"),
                "collections_created": stac_collections_result.get("collections_created", []),
                "collections_failed": stac_collections_result.get("collections_failed", [])
            })
            logging.info(f"✅ Step 3 appended. Total steps: {len(results['steps'])}")

        # Overall status
        overall_success = deploy_response.status_code == 200
        results["overall_status"] = "success" if overall_success else "partial_failure"
        results["message"] = "Schema redeployed successfully" if overall_success else "Nuke succeeded but deploy failed"

        return func.HttpResponse(
            body=json.dumps(results),
            status_code=200 if overall_success else 500,
            headers={'Content-Type': 'application/json'}
        )
    else:
        results["overall_status"] = "failed"
        results["message"] = "Schema nuke failed - deploy not attempted"
        
        return func.HttpResponse(
            body=json.dumps(results),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )


@app.route(route="db/functions/test", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def test_database_functions(req: func.HttpRequest) -> func.HttpResponse:
    """Test PostgreSQL functions: GET /api/db/functions/test"""
    return function_test_trigger.handle_request(req)


# ============================================================================
# CONTAINER ANALYSIS ENDPOINT - Post-processing for list_container_contents jobs
# ============================================================================

@app.route(route="analysis/container/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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
        save: If 'true', saves results to rmhazuregeoinventory container
    """
    return analyze_container_trigger.handle_request(req)


@app.route(route="analysis/delivery", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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
# STAC SETUP ENDPOINT - PgSTAC installation and management
# ============================================================================

@app.route(route="stac/setup", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
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
@app.route(route="stac/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/collections/{tier}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_collections(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC collection management for Bronze/Silver/Gold tiers.

    POST /api/stac/collections/{tier} where tier is: bronze, silver, or gold

    Body:
        {
            "container": "rmhazuregeobronze",  // Required
            "collection_id": "custom-id",      // Optional
            "title": "Custom Title",           // Optional
            "description": "Custom description"// Optional
        }

    Returns:
        Collection creation result with collection_id
    """
    return stac_collections_trigger.handle_request(req)


@app.route(route="stac/init", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/extract", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_extract(req: func.HttpRequest) -> func.HttpResponse:
    """
    Extract STAC metadata from raster blob and insert into PgSTAC.

    POST /api/stac/extract

    Body:
        {
            "container": "rmhazuregeobronze",      // Required
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

@app.route(route="platform/submit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def platform_submit(req: func.HttpRequest) -> func.HttpResponse:
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
    return await platform_request_submit(req)


@app.route(route="platform/status/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def platform_status_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request.

    GET /api/platform/status/{request_id}

    Returns detailed status including all CoreMachine jobs.
    """
    return await platform_request_status(req)


@app.route(route="platform/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def platform_status_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all platform requests.

    GET /api/platform/status?limit=100&status=pending

    Returns list of all platform requests with optional filtering.
    """
    return await platform_request_status(req)


@app.route(route="stac/vector", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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

from infrastructure.stac import (
    get_schema_info,
    get_collection_stats,
    get_item_by_id,
    get_health_metrics,
    get_collections_summary
)

@app.route(route="stac/schema/info", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/collections/summary", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/collections/{collection_id}/stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/items/{item_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="stac/health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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

@app.route(route="collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all STAC collections (STAC API standard).

    GET /collections

    STAC API Specification: https://github.com/radiantearth/stac-api-spec

    Returns:
        JSON with 'collections' array containing all STAC collections
    """
    from infrastructure.stac import get_all_collections

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


@app.route(route="collections/{collection_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def collection_detail(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get single STAC collection (STAC API standard).

    GET /collections/{collection_id}

    Path Parameters:
        collection_id: Collection identifier (e.g., "system-vectors")

    Returns:
        STAC Collection object
    """
    from infrastructure.stac import get_collection

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


@app.route(route="collections/{collection_id}/items", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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
    from infrastructure.stac import get_collection_items

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


@app.route(route="search", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
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
    from infrastructure.stac import search_items

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


@app.route(route="features", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_landing(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features API landing page: GET /api/features"""
    return _ogc_landing(req)


@app.route(route="features/conformance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features conformance: GET /api/features/conformance"""
    return _ogc_conformance(req)


@app.route(route="features/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_collections(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features collections list: GET /api/features/collections"""
    return _ogc_collections(req)


@app.route(route="features/collections/{collection_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_collection(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features collection metadata: GET /api/features/collections/{collection_id}"""
    return _ogc_collection(req)


@app.route(route="features/collections/{collection_id}/items", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_items(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features items query: GET /api/features/collections/{collection_id}/items"""
    return _ogc_items(req)


@app.route(route="features/collections/{collection_id}/items/{feature_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ogc_features_feature(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Features single feature: GET /api/features/collections/{collection_id}/items/{feature_id}"""
    return _ogc_feature(req)


@app.route(route="jobs/ingest_vector", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def ingest_vector(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit vector file for ETL to PostGIS.

    POST /api/jobs/ingest_vector

    Body:
        {
            "blob_name": "data/parcels.gpkg",       // Required
            "file_extension": "gpkg",               // Required (csv, geojson, gpkg, kml, kmz, shp, zip)
            "table_name": "parcels_2025",           // Required (PostgreSQL identifier)
            "container_name": "bronze",             // Optional (default: bronze)
            "schema": "geo",                        // Optional (default: geo)
            "chunk_size": 1000,                     // Optional (None = auto-calculate)
            "converter_params": {                   // Optional (format-specific)
                "layer_name": "parcels"             // For GPKG
                // OR
                "lat_name": "latitude",             // For CSV
                "lon_name": "longitude"             // For CSV
            }
        }

    Returns:
        Job creation response with job_id and status
    """
    return ingest_vector_trigger.handle_request(req)


# ============================================================================
# TEST UTILITIES - DEVELOPMENT ONLY
# ============================================================================

@app.route(route="test/create-rasters", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def test_create_rasters(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create test raster files in Azure Blob Storage for pipeline testing.

    TESTING/DEVELOPMENT ONLY - Should not be exposed in production.

    POST /api/test/create-rasters
    POST /api/test/create-rasters?raster_type=rgb

    Query Parameters:
        raster_type: Optional - Create single raster type
                     (rgb, rgba, dem, categorical_64bit, no_crs, sentinel2, wgs84)
                     If not specified, creates ALL test rasters

    Returns:
        Upload results with blob URLs
    """
    return test_raster_create_trigger.handle_request(req)




@app.route(route="db/debug/all", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def debug_dump_all(req: func.HttpRequest) -> func.HttpResponse:
    """
    🔍 DEBUG: Dump all jobs and tasks for debugging.
    GET /api/db/debug/all?limit=100
    
    Returns complete data from both jobs and tasks tables for debugging.
    Perfect for when you don't have DBeaver access.
    """
    # Imports moved to top of file
    
    limit = int(req.params.get('limit', '100'))
    
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        
        # Get connection from repository
        # Import moved to top of file
        if isinstance(job_repo, PostgreSQLRepository):
            # FIX: _get_connection() is a context manager, use with statement
            with job_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get all jobs
                    cursor.execute(f"""
                        SELECT
                            job_id, job_type, status, stage, total_stages,
                            parameters, stage_results, result_data, error_details,
                            created_at, updated_at
                        FROM {job_repo.schema_name}.jobs
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                    jobs = []
                    for row in cursor.fetchall():
                        jobs.append({
                            "job_id": row[0],
                            "job_type": row[1],
                            "status": row[2],
                            "stage": row[3],
                            "total_stages": row[4],
                            "parameters": row[5],
                            "stage_results": row[6],
                            "result_data": row[7],
                            "error_details": row[8],
                            "created_at": row[9].isoformat() if row[9] else None,
                            "updated_at": row[10].isoformat() if row[10] else None
                        })

                    # Get all tasks
                    cursor.execute(f"""
                        SELECT
                            task_id, job_id, task_type, status, stage,
                            parameters, result_data, error_details, retry_count,
                            created_at, updated_at
                        FROM {job_repo.schema_name}.tasks
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                    tasks = []
                    for row in cursor.fetchall():
                        tasks.append({
                            "task_id": row[0],
                            "job_id": row[1],
                            "task_type": row[2],
                            "status": row[3],
                            "stage": row[4],
                            "parameters": row[5],
                            "result_data": row[6],
                            "error_details": row[7],
                            "retry_count": row[8],
                            "created_at": row[9].isoformat() if row[9] else None,
                            "updated_at": row[10].isoformat() if row[10] else None
                        })
            # Context managers automatically close cursor and connection
            
            return func.HttpResponse(
                body=json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "jobs_count": len(jobs),
                    "tasks_count": len(tasks),
                    "jobs": jobs,
                    "tasks": tasks
                }, default=str),
                status_code=200,
                headers={'Content-Type': 'application/json'}
            )
            
    except Exception as e:
        return func.HttpResponse(
            body=json.dumps({
                "error": f"Debug dump failed: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )


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
# SERVICE BUS TRIGGERS - Parallel Pipeline for High-Volume Processing
# ============================================================================

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-jobs",  # Same as Storage Queue name
    connection="ServiceBusConnection"
)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    """
    Process job messages from Service Bus using CoreMachine.

    EPOCH 4: Uses CoreMachine universal orchestrator instead of controllers.
    Works with ALL job types via registry pattern - no job-specific code needed.

    Performance benefits:
    - No base64 encoding needed (Service Bus handles binary)
    - Better throughput for high-volume scenarios
    - Built-in dead letter queue support
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{correlation_id}] 🤖 COREMACHINE JOB TRIGGER (Service Bus)")

    try:
        # Extract message body (no base64 decoding needed for Service Bus)
        message_body = msg.get_body().decode('utf-8')
        logger.info(f"[{correlation_id}] 📦 Message size: {len(message_body)} bytes")

        # Parse message
        job_message = JobQueueMessage.model_validate_json(message_body)
        logger.info(f"[{correlation_id}] ✅ Parsed job: {job_message.job_id[:16]}..., type={job_message.job_type}")

        # Add correlation ID for tracking
        if job_message.parameters is None:
            job_message.parameters = {}
        job_message.parameters['_correlation_id'] = correlation_id
        job_message.parameters['_processing_path'] = 'service_bus'

        # EPOCH 4: Process via CoreMachine (universal orchestrator)
        result = core_machine.process_job_message(job_message)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] ✅ CoreMachine processed job in {elapsed:.3f}s")
        logger.info(f"[{correlation_id}] 📊 Result: {result}")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{correlation_id}] ❌ EXCEPTION in process_service_bus_job after {elapsed:.3f}s")
        logger.error(f"[{correlation_id}] 📍 Exception type: {type(e).__name__}")
        logger.error(f"[{correlation_id}] 📍 Exception message: {e}")
        logger.error(f"[{correlation_id}] 📍 Full traceback:\n{traceback.format_exc()}")

        # Log job details if available
        if 'job_message' in locals() and job_message:
            logger.error(f"[{correlation_id}] 📋 Job ID: {job_message.job_id}")
            logger.error(f"[{correlation_id}] 📋 Job Type: {job_message.job_type}")
            logger.error(f"[{correlation_id}] 📋 Stage: {job_message.stage}")

        # NOTE: Job processing errors are typically critical (workflow creation failures).
        # Unlike task retries, jobs don't have application-level retry logic.
        # Log extensively but don't re-raise to avoid Service Bus retries for job messages.
        logger.warning(f"[{correlation_id}] ⚠️ Function completing (exception logged but not re-raised)")
        logger.warning(f"[{correlation_id}] ⚠️ Job marked as failed - check logs for details")


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-tasks",  # Same as Storage Queue name
    connection="ServiceBusConnection"
)
def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
    """
    Process task messages from Service Bus using CoreMachine.

    EPOCH 4: Uses CoreMachine universal orchestrator instead of controllers.
    Handles all task execution, stage completion, and job advancement automatically.

    Performance benefits:
    - Processes batches of tasks efficiently
    - Better concurrency handling
    - Lower latency for high-volume scenarios
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{correlation_id}] 🤖 COREMACHINE TASK TRIGGER (Service Bus)")

    try:
        # Extract message body
        message_body = msg.get_body().decode('utf-8')

        # Parse message
        task_message = TaskQueueMessage.model_validate_json(message_body)
        logger.info(f"[{correlation_id}] ✅ Parsed task: {task_message.task_id}, type={task_message.task_type}")

        # Add metadata for tracking
        if task_message.parameters is None:
            task_message.parameters = {}
        task_message.parameters['_correlation_id'] = correlation_id
        task_message.parameters['_processing_path'] = 'service_bus'

        # EPOCH 4: Process via CoreMachine (universal orchestrator)
        # Handles: task execution, stage completion detection, job advancement
        result = core_machine.process_task_message(task_message)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] ✅ CoreMachine processed task in {elapsed:.3f}s")
        logger.info(f"[{correlation_id}] 📊 Result: {result}")

        # Check if stage completed
        if result.get('stage_complete'):
            logger.info(f"[{correlation_id}] 🎯 Stage {task_message.stage} complete for job {task_message.parent_job_id[:16]}...")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{correlation_id}] ❌ EXCEPTION in process_service_bus_task after {elapsed:.3f}s")
        logger.error(f"[{correlation_id}] 📍 Exception type: {type(e).__name__}")
        logger.error(f"[{correlation_id}] 📍 Exception message: {e}")
        logger.error(f"[{correlation_id}] 📍 Full traceback:\n{traceback.format_exc()}")

        # Log task details if available
        if 'task_message' in locals() and task_message:
            logger.error(f"[{correlation_id}] 📋 Task ID: {task_message.task_id}")
            logger.error(f"[{correlation_id}] 📋 Task Type: {task_message.task_type}")
            logger.error(f"[{correlation_id}] 📋 Job ID: {task_message.parent_job_id}")
            logger.error(f"[{correlation_id}] 📋 Stage: {task_message.stage}")

        # NOTE: Do NOT re-raise! CoreMachine already handled the failure internally.
        # Re-raising would trigger Service Bus retries instead of our application-level
        # retry logic (exponential backoff, retry_count tracking in database).
        # CoreMachine's process_task_message() already:
        # 1. Caught the task execution failure
        # 2. Incremented retry_count in database
        # 3. Re-queued with exponential backoff delay (if retries available)
        # 4. OR marked as permanently FAILED (if max retries exceeded)
        logger.warning(f"[{correlation_id}] ⚠️ Function completing (exception logged but not re-raised)")
        logger.warning(f"[{correlation_id}] ⚠️ CoreMachine retry logic has handled this failure internally")


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
