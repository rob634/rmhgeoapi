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
# LAST_UPDATED: 11 NOV 2025 - Added STAC API v1.0.0 endpoints (6 routes)
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

    STAC API v1.0.0 (NEW 11 NOV 2025):
    GET  /api/stac_api - STAC landing page
    GET  /api/stac_api/conformance - STAC conformance classes
    GET  /api/stac_api/collections - STAC collections list
    GET  /api/stac_api/collections/{collection_id} - STAC collection detail
    GET  /api/stac_api/collections/{collection_id}/items - STAC items (paginated)
    GET  /api/stac_api/collections/{collection_id}/items/{item_id} - STAC item detail

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
# ⚠️ LEGACY IMPORTS - DEPRECATED (10 NOV 2025)
# These imports are kept temporarily for backward compatibility
# All functionality has been migrated to triggers/admin/
from triggers.db_query import (
    schema_nuke_trigger  # Still used temporarily by db_maintenance.py
)

from triggers.analyze_container import analyze_container_trigger
from triggers.stac_setup import stac_setup_trigger
from triggers.stac_collections import stac_collections_trigger
from triggers.stac_init import stac_init_trigger
from triggers.stac_extract import stac_extract_trigger
from triggers.stac_vector import stac_vector_trigger
from triggers.stac_nuke import stac_nuke_trigger

# STAC API v1.0.0 Portable Module (10 NOV 2025)
from stac_api import get_stac_triggers

from triggers.ingest_vector import ingest_vector_trigger
from triggers.test_raster_create import test_raster_create_trigger

# Admin API triggers (10 NOV 2025) - Consolidated under /api/admin/*
from triggers.admin.db_schemas import admin_db_schemas_trigger
from triggers.admin.db_tables import admin_db_tables_trigger
from triggers.admin.db_queries import admin_db_queries_trigger
from triggers.admin.db_health import admin_db_health_trigger
from triggers.admin.db_maintenance import admin_db_maintenance_trigger
from triggers.admin.db_data import admin_db_data_trigger
from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
from triggers.admin.servicebus import servicebus_admin_trigger

# Platform Service Layer triggers (25 OCT 2025)
from triggers.trigger_platform import platform_request_submit
from triggers.trigger_platform_status import platform_request_status

# OGC Features API - Standalone module (29 OCT 2025)
from ogc_features import get_ogc_triggers

# STAC API - Standalone module (11 NOV 2025)
from stac_api import get_stac_triggers

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


# ============================================================================
# DATABASE ADMIN API ENDPOINTS - Phase 1 (03 NOV 2025)
# ============================================================================
# Database admin endpoints under /api/db/* (consolidated with existing db routes)
# NOTE: Azure Functions reserves /api/admin/* for built-in admin UI
# APIM can still restrict all /api/db/* endpoints with a single policy
# Priority: PostgreSQL visibility (app, geo, pgstac schemas)
# ============================================================================

# Schema-level operations
@app.route(route="db/schemas", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_schemas_list(req: func.HttpRequest) -> func.HttpResponse:
    """List all schemas: GET /api/db/schemas"""
    return admin_db_schemas_trigger.handle_request(req)


@app.route(route="db/schemas/{schema_name}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_schema_details(req: func.HttpRequest) -> func.HttpResponse:
    """Get schema details: GET /api/db/schemas/{schema_name}"""
    return admin_db_schemas_trigger.handle_request(req)


@app.route(route="db/schemas/{schema_name}/tables", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_schema_tables(req: func.HttpRequest) -> func.HttpResponse:
    """List schema tables: GET /api/db/schemas/{schema_name}/tables"""
    return admin_db_schemas_trigger.handle_request(req)


# Table-level operations
@app.route(route="db/tables/{table_identifier}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_table_details(req: func.HttpRequest) -> func.HttpResponse:
    """Get table details: GET /api/db/tables/{schema}.{table}"""
    return admin_db_tables_trigger.handle_request(req)


@app.route(route="db/tables/{table_identifier}/sample", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_table_sample(req: func.HttpRequest) -> func.HttpResponse:
    """Sample table rows: GET /api/db/tables/{schema}.{table}/sample"""
    return admin_db_tables_trigger.handle_request(req)


@app.route(route="db/tables/{table_identifier}/columns", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_table_columns(req: func.HttpRequest) -> func.HttpResponse:
    """Get table columns: GET /api/db/tables/{schema}.{table}/columns"""
    return admin_db_tables_trigger.handle_request(req)


@app.route(route="db/tables/{table_identifier}/indexes", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_table_indexes(req: func.HttpRequest) -> func.HttpResponse:
    """Get table indexes: GET /api/db/tables/{schema}.{table}/indexes"""
    return admin_db_tables_trigger.handle_request(req)


# Query analysis
@app.route(route="db/queries/running", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_queries_running(req: func.HttpRequest) -> func.HttpResponse:
    """Get running queries: GET /api/db/queries/running"""
    return admin_db_queries_trigger.handle_request(req)


@app.route(route="db/queries/slow", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_queries_slow(req: func.HttpRequest) -> func.HttpResponse:
    """Get slow queries: GET /api/db/queries/slow"""
    return admin_db_queries_trigger.handle_request(req)


@app.route(route="db/locks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_locks(req: func.HttpRequest) -> func.HttpResponse:
    """Get database locks: GET /api/db/locks"""
    return admin_db_queries_trigger.handle_request(req)


@app.route(route="db/connections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_connections(req: func.HttpRequest) -> func.HttpResponse:
    """Get connection stats: GET /api/db/connections"""
    return admin_db_queries_trigger.handle_request(req)


# Health and performance
@app.route(route="db/health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_health(req: func.HttpRequest) -> func.HttpResponse:
    """Get database health: GET /api/db/health"""
    return admin_db_health_trigger.handle_request(req)


@app.route(route="db/health/performance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def db_health_performance(req: func.HttpRequest) -> func.HttpResponse:
    """Get performance metrics: GET /api/db/health/performance"""
    return admin_db_health_trigger.handle_request(req)


# Maintenance operations
@app.route(route="db/maintenance/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def db_maintenance_nuke(req: func.HttpRequest) -> func.HttpResponse:
    """Nuke schema: POST /api/db/maintenance/nuke?confirm=yes"""
    return admin_db_maintenance_trigger.handle_request(req)


@app.route(route="db/maintenance/redeploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def db_maintenance_redeploy(req: func.HttpRequest) -> func.HttpResponse:
    """Redeploy schema: POST /api/db/maintenance/redeploy?confirm=yes"""
    return admin_db_maintenance_trigger.handle_request(req)


@app.route(route="db/maintenance/cleanup", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def db_maintenance_cleanup(req: func.HttpRequest) -> func.HttpResponse:
    """Cleanup old records: POST /api/db/maintenance/cleanup?confirm=yes&days=30"""
    return admin_db_maintenance_trigger.handle_request(req)


# ============================================================================
# SERVICE BUS ADMIN API ENDPOINTS - Phase 2 (04 NOV 2025)
# ============================================================================
# Service Bus queue monitoring and management under /api/servicebus/*
# Read-only inspection + nuclear button for clearing queues
# Priority: Production operations and debugging
# ============================================================================

@app.route(route="servicebus/queues", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_list_queues(req: func.HttpRequest) -> func.HttpResponse:
    """List all Service Bus queues: GET /api/servicebus/queues"""
    return servicebus_admin_trigger.handle_request(req)


@app.route(route="servicebus/queues/{queue_name}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_queue_details(req: func.HttpRequest) -> func.HttpResponse:
    """Get queue details: GET /api/servicebus/queues/{queue_name}"""
    return servicebus_admin_trigger.handle_request(req)


@app.route(route="servicebus/queues/{queue_name}/peek", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_peek_messages(req: func.HttpRequest) -> func.HttpResponse:
    """Peek active messages: GET /api/servicebus/queues/{queue_name}/peek?limit=10"""
    return servicebus_admin_trigger.handle_request(req)


@app.route(route="servicebus/queues/{queue_name}/deadletter", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_peek_deadletter(req: func.HttpRequest) -> func.HttpResponse:
    """Peek dead letter messages: GET /api/servicebus/queues/{queue_name}/deadletter?limit=10"""
    return servicebus_admin_trigger.handle_request(req)


@app.route(route="servicebus/health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_health(req: func.HttpRequest) -> func.HttpResponse:
    """Get Service Bus health: GET /api/servicebus/health"""
    return servicebus_admin_trigger.handle_request(req)


@app.route(route="servicebus/queues/{queue_name}/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def servicebus_admin_nuke_queue(req: func.HttpRequest) -> func.HttpResponse:
    """🚨 NUCLEAR: Clear queue messages: POST /api/servicebus/queues/{queue_name}/nuke?confirm=yes&target=all"""
    return servicebus_admin_trigger.handle_request(req)


# ============================================================================
# END SERVICE BUS ADMIN API ENDPOINTS
# ============================================================================


# ============================================================================
# END DATABASE ADMIN API ENDPOINTS
# ============================================================================


@app.route(route="jobs/submit/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)



@app.route(route="jobs/status/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)




# Database Query Endpoints - Phase 2 Database Monitoring
@app.route(route="dbadmin/jobs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query jobs with filtering: GET /api/admin/db/jobs?limit=10&status=processing&hours=24"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_job_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get specific job by ID: GET /api/admin/db/jobs/{job_id}"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/tasks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_tasks(req: func.HttpRequest) -> func.HttpResponse:
    """Query tasks with filtering: GET /api/admin/db/tasks?status=failed&limit=20"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/tasks/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_tasks_for_job(req: func.HttpRequest) -> func.HttpResponse:
    """Get all tasks for a job: GET /api/admin/db/tasks/{job_id}"""
    return admin_db_data_trigger.handle_request(req)


# Platform Layer Query Endpoints (29 OCT 2025 - Migrated to Admin API 10 NOV 2025)
@app.route(route="dbadmin/platform/requests", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_api_requests(req: func.HttpRequest) -> func.HttpResponse:
    """Query API requests with filtering: GET /api/admin/db/platform/requests?limit=10&status=processing"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/platform/requests/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_api_request_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get specific API request by ID: GET /api/admin/db/platform/requests/{request_id}"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/platform/orchestration", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_orchestration_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query orchestration jobs with filtering: GET /api/admin/db/platform/orchestration?request_id={request_id}"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/platform/orchestration/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_query_orchestration_jobs_for_request(req: func.HttpRequest) -> func.HttpResponse:
    """Get orchestration jobs for specific request: GET /api/admin/db/platform/orchestration/{request_id}"""
    return admin_db_data_trigger.handle_request(req)


@app.route(route="dbadmin/stats", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_database_stats(req: func.HttpRequest) -> func.HttpResponse:
    """Database statistics and health metrics: GET /api/admin/db/stats"""
    return admin_db_diagnostics_trigger.handle_request(req)


@app.route(route="dbadmin/diagnostics/enums", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_diagnose_enums(req: func.HttpRequest) -> func.HttpResponse:
    """Diagnose PostgreSQL enum types: GET /api/admin/db/diagnostics/enums"""
    return admin_db_diagnostics_trigger.handle_request(req)


@app.route(route="dbadmin/diagnostics/functions", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_test_functions(req: func.HttpRequest) -> func.HttpResponse:
    """Test PostgreSQL functions: GET /api/admin/db/diagnostics/functions"""
    return admin_db_diagnostics_trigger.handle_request(req)


@app.route(route="dbadmin/diagnostics/all", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_all_diagnostics(req: func.HttpRequest) -> func.HttpResponse:
    """Get all diagnostics: GET /api/admin/db/diagnostics/all"""
    return admin_db_diagnostics_trigger.handle_request(req)


# 🚨 NUCLEAR RED BUTTON - DEVELOPMENT ONLY (⚠️ DEPRECATED - Use /api/admin/db/maintenance/nuke)
@app.route(route="db/schema/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def nuclear_schema_reset(req: func.HttpRequest) -> func.HttpResponse:
    """⚠️ DEPRECATED: Use /api/admin/db/maintenance/nuke instead. POST /api/db/schema/nuke?confirm=yes"""
    return admin_db_maintenance_trigger.handle_request(req)


# 🔄 CONSOLIDATED REBUILD - DEVELOPMENT ONLY (⚠️ DEPRECATED - Use /api/admin/db/maintenance/redeploy)
@app.route(route="db/schema/redeploy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def redeploy_schema(req: func.HttpRequest) -> func.HttpResponse:
    """⚠️ DEPRECATED: Use /api/admin/db/maintenance/redeploy instead. POST /api/db/schema/redeploy?confirm=yes"""
    return admin_db_maintenance_trigger.handle_request(req)


# Note: Legacy inline redeploy code (150+ lines) has been removed (10 NOV 2025)
# It has been migrated to triggers/admin/db_maintenance.py AdminDbMaintenanceTrigger._redeploy_schema()
# The old /api/db/schema/redeploy route now redirects to admin_db_maintenance_trigger


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


@app.route(route="stac", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API landing page: GET /api/stac"""
    return _stac_landing(req)


@app.route(route="stac/conformance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API conformance: GET /api/stac/conformance"""
    return _stac_conformance(req)


@app.route(route="stac/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API collections list: GET /api/stac/collections"""
    return _stac_collections(req)


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


@app.route(route="stac_api", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 landing page: GET /api/stac_api"""
    return _stac_landing(req)


@app.route(route="stac_api/conformance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 conformance: GET /api/stac_api/conformance"""
    return _stac_conformance(req)


@app.route(route="stac_api/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_collections(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 collections list: GET /api/stac_api/collections"""
    return _stac_collections(req)


@app.route(route="stac_api/collections/{collection_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_collection(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 collection detail: GET /api/stac_api/collections/{collection_id}"""
    return _stac_collection(req)


@app.route(route="stac_api/collections/{collection_id}/items", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_items(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 items list: GET /api/stac_api/collections/{collection_id}/items"""
    return _stac_items(req)


@app.route(route="stac_api/collections/{collection_id}/items/{item_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_v1_item(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 item detail: GET /api/stac_api/collections/{collection_id}/items/{item_id}"""
    return _stac_item(req)


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
                            task_id, parent_job_id, task_type, status, stage,
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
                            "parent_job_id": row[1],
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

        # Parse message
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

            # FP1 FIX: Mark job as FAILED in database to prevent stuck jobs
            try:
                repos = RepositoryFactory.create_repositories()
                job_repo = repos['job_repo']

                error_msg = f"Job processing exception: {type(e).__name__}: {e}"
                job_repo.mark_failed(job_message.job_id, error_msg)

                logger.info(f"[{correlation_id}] ✅ Job {job_message.job_id[:16]}... marked as FAILED in database")

            except Exception as cleanup_error:
                logger.error(f"[{correlation_id}] ❌ Failed to mark job as FAILED: {cleanup_error}")
                logger.error(f"[{correlation_id}] 💀 Job {job_message.job_id[:16]}... may be stuck - requires manual cleanup")
        else:
            logger.error(f"[{correlation_id}] ⚠️ job_message is None - cannot mark job as FAILED")
            logger.error(f"[{correlation_id}] 📍 Exception occurred before job message parsing")

        # NOTE: Job processing errors are typically critical (workflow creation failures).
        # Unlike task retries, jobs don't have application-level retry logic.
        # Log extensively but don't re-raise to avoid Service Bus retries for job messages.
        logger.warning(f"[{correlation_id}] ⚠️ Function completing (exception logged but not re-raised)")
        logger.warning(f"[{correlation_id}] ✅ Job failure handling complete")


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
    # Generate correlation_id for function invocation tracing
    # Purpose: Log prefix [abc12345] to filter Application Insights logs for this execution
    # Scope: Local to this function invocation (not propagated to TaskQueueMessage)
    # Usage: Search Application Insights: traces | where message contains '[abc12345]'
    # Note: TaskQueueMessage doesn't have correlation_id field (only JobQueueMessage does)
    # See: core/schema/queue.py for correlation_id field documentation
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
