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
from core.machine import CoreMachine

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
# NOTE: STAC admin triggers (stac_setup, stac_collections, stac_init, stac_nuke)
# moved to admin_stac blueprint (12 JAN 2026)
from triggers.stac_extract import stac_extract_trigger
from triggers.stac_vector import stac_vector_trigger

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
# NOTE: H3 admin triggers (h3_debug, h3_datasets) moved to admin_h3 blueprint (12 JAN 2026)

# Curated Dataset Admin (15 DEC 2025) - System-managed geospatial data
from triggers.curated.admin import curated_admin_trigger
from triggers.curated.scheduler import curated_scheduler_trigger

# Platform Service Layer triggers (25 OCT 2025)
from triggers.trigger_platform import (
    platform_request_submit,
    # REMOVED (21 JAN 2026): platform_raster_submit, platform_raster_collection_submit
    # Use platform_request_submit for all submissions via /platform/submit
    platform_unpublish,  # Consolidated endpoint (21 JAN 2026)
    platform_unpublish_vector,  # DEPRECATED - use platform_unpublish
    platform_unpublish_raster   # DEPRECATED - use platform_unpublish
)
from triggers.trigger_platform_status import platform_request_status, platform_job_status
from triggers.trigger_approvals import (
    platform_approve,
    platform_revoke,
    platform_approvals_list,
    platform_approval_get,
    platform_approvals_status
)
# REMOVED (19 DEC 2025): platform_health, platform_stats, platform_failures
# These were broken and redundant with /api/health

# OGC Features API - Standalone module (29 OCT 2025)
from ogc_features import get_ogc_triggers

# STAC API - Standalone module (11 NOV 2025)
from stac_api import get_stac_triggers

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

# Janitor Triggers (21 NOV 2025) - System maintenance (timer handlers only)
# HTTP handlers moved to triggers/admin/admin_janitor.py blueprint (12 JAN 2026)
from triggers.janitor import (
    task_watchdog_handler,
    job_health_handler,
    orphan_detector_handler
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
    Handles:
    1. Approval record creation for jobs that produce STAC items (F7.Approval - 22 JAN 2026)

    Args:
        job_id: CoreMachine job ID
        job_type: Type of job that completed
        status: 'completed' or 'failed'
        result: Job result dict containing STAC item info

    Note:
        All operations are non-fatal - failures are logged but don't affect job status.
    """
    # Skip if job failed - no approval needed for failed jobs
    if status != 'completed':
        return

    # F7.Approval (22 JAN 2026): Create approval record for STAC items
    # Every dataset requires explicit approval before publication
    try:
        stac_item_id = _extract_stac_item_id(result)
        stac_collection_id = _extract_stac_collection_id(result)

        if stac_item_id:
            from services.approval_service import ApprovalService
            from core.models.promoted import Classification

            # Extract classification from job parameters (default: OUO)
            classification_str = _extract_classification(result)
            classification = Classification.PUBLIC if classification_str == 'public' else Classification.OUO

            approval_service = ApprovalService()
            approval = approval_service.create_approval_for_job(
                job_id=job_id,
                job_type=job_type,
                classification=classification,
                stac_item_id=stac_item_id,
                stac_collection_id=stac_collection_id
            )
            logger.info(
                f"📋 [APPROVAL] Created approval record {approval.approval_id[:12]}... "
                f"for job {job_id[:8]}... (STAC: {stac_item_id}, status: PENDING)"
            )
    except Exception as e:
        # Non-fatal: approval creation failure should not affect job completion
        logger.warning(f"⚠️ [APPROVAL] Failed to create approval for job {job_id[:8]}... (non-fatal): {e}")


def _extract_stac_item_id(result: dict) -> str | None:
    """
    Extract STAC item ID from various result structures.

    Handlers return results in different formats, so we check multiple paths.

    Args:
        result: Job result dict

    Returns:
        STAC item ID if found, None otherwise
    """
    if not result:
        return None

    # Path 1: result.stac.item_id (common pattern)
    if result.get('stac', {}).get('item_id'):
        return result['stac']['item_id']

    # Path 2: result.result.stac.item_id (nested result)
    if result.get('result', {}).get('stac', {}).get('item_id'):
        return result['result']['stac']['item_id']

    # Path 3: result.item_id (flat result)
    if result.get('item_id'):
        return result['item_id']

    # Path 4: result.stac_item_id (alternative key)
    if result.get('stac_item_id'):
        return result['stac_item_id']

    # Path 5: result.result.item_id (nested flat)
    if result.get('result', {}).get('item_id'):
        return result['result']['item_id']

    return None


def _extract_stac_collection_id(result: dict) -> str | None:
    """
    Extract STAC collection ID from various result structures.

    Args:
        result: Job result dict

    Returns:
        STAC collection ID if found, None otherwise
    """
    if not result:
        return None

    # Path 1: result.stac.collection_id
    if result.get('stac', {}).get('collection_id'):
        return result['stac']['collection_id']

    # Path 2: result.result.stac.collection_id
    if result.get('result', {}).get('stac', {}).get('collection_id'):
        return result['result']['stac']['collection_id']

    # Path 3: result.collection_id
    if result.get('collection_id'):
        return result['collection_id']

    # Path 4: result.stac_collection_id
    if result.get('stac_collection_id'):
        return result['stac_collection_id']

    # Path 5: result.result.collection_id
    if result.get('result', {}).get('collection_id'):
        return result['result']['collection_id']

    return None


def _extract_classification(result: dict) -> str:
    """
    Extract classification from job result (for approval workflow).

    Jobs can specify classification in their parameters. Default is 'ouo'.

    Args:
        result: Job result dict

    Returns:
        Classification string ('ouo' or 'public')
    """
    if not result:
        return 'ouo'

    # Check various locations where classification might be stored
    # Path 1: Direct in result
    if result.get('classification'):
        return result['classification'].lower()

    # Path 2: In parameters
    if result.get('parameters', {}).get('classification'):
        return result['parameters']['classification'].lower()

    # Path 3: In result.result
    if result.get('result', {}).get('classification'):
        return result['result']['classification'].lower()

    # Path 4: access_level mapping (public → public, everything else → ouo)
    access_level = result.get('access_level') or result.get('parameters', {}).get('access_level')
    if access_level and access_level.lower() == 'public':
        return 'public'

    return 'ouo'

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
    from triggers.admin.admin_stac import bp as admin_stac_bp
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
    app.register_functions(admin_stac_bp)
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


# NOTE: STAC admin routes moved to triggers/admin/admin_stac.py blueprint (12 JAN 2026)
# - /api/stac/setup
# - /api/stac/nuke
# - /api/stac/collections/{tier}
# - /api/stac/init

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
# PLATFORM SERVICE LAYER ENDPOINTS (25 OCT 2025, conditional 15 JAN 2026)
# ============================================================================
# Platform orchestration layer above CoreMachine for external applications (DDH)
# Follows same patterns as Job→Task: PlatformRequest→Jobs→Tasks
# Only registered for modes with has_platform_endpoints=True (gateway, standalone, platform_*)

def _platform_endpoint_guard() -> Optional[func.HttpResponse]:
    """Return 404 response if platform endpoints are disabled for this app mode."""
    if not _app_mode.has_platform_endpoints:
        return func.HttpResponse(
            json.dumps({
                "error": "Platform endpoints not available",
                "message": f"APP_MODE={_app_mode.mode.value} does not expose platform/* endpoints",
                "hint": "Use gateway or standalone mode for platform endpoints"
            }),
            status_code=404,
            mimetype="application/json"
        )
    return None


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
            "container_name": "bronze-rasters",
            "file_name": "example.tif",
            "service_name": "Landsat 8 Scene",
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
    if guard := _platform_endpoint_guard():
        return guard
    return platform_request_submit(req)


@app.route(route="platform/status/{request_id}", methods=["GET"])
async def platform_status_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request or job (consolidated endpoint).

    GET /api/platform/status/{id}

    The {id} parameter can be EITHER:
    - A request_id (Platform request identifier)
    - A job_id (CoreMachine job identifier)

    The endpoint auto-detects which type of ID was provided (21 JAN 2026).
    Returns detailed status including DDH identifiers and CoreMachine job status.
    """
    if guard := _platform_endpoint_guard():
        return guard
    return await platform_request_status(req)


@app.route(route="platform/status", methods=["GET"])
async def platform_status_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all platform requests.

    GET /api/platform/status?limit=100&status=pending

    Returns list of all platform requests with optional filtering.
    """
    if guard := _platform_endpoint_guard():
        return guard
    return await platform_request_status(req)


@app.route(route="platform/jobs/{job_id}/status", methods=["GET"])
async def platform_job_status_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: Get status of a CoreMachine job directly by job_id.

    ⚠️ DEPRECATED (21 JAN 2026): Use GET /api/platform/status/{job_id} instead.
    The consolidated endpoint accepts either request_id or job_id.

    GET /api/platform/jobs/{job_id}/status

    Returns job status with task summary. Response includes deprecation headers
    and migration URL pointing to the consolidated endpoint.
    """
    if guard := _platform_endpoint_guard():
        return guard
    return await platform_job_status(req)


# ============================================================================
# PLATFORM DIAGNOSTICS FOR EXTERNAL APPS (F7.12 - 15 JAN 2026)
# ============================================================================
# Simplified, external-facing diagnostics for service layer apps.
# These replace the broken endpoints removed 19 DEC 2025.
# ============================================================================

@app.route(route="platform/health", methods=["GET"])
async def platform_health_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Simplified system readiness check for external apps.

    GET /api/platform/health

    Returns simplified health status (ready_for_jobs, queue backlog, etc.)
    without exposing internal details like enum errors or storage accounts.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_status import platform_health
    return await platform_health(req)


@app.route(route="platform/failures", methods=["GET"])
async def platform_failures_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures with sanitized error summaries.

    GET /api/platform/failures?hours=24&limit=20

    Returns failure patterns and recent failures with sanitized messages
    (no internal paths, secrets, or stack traces).
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_status import platform_failures
    return await platform_failures(req)


@app.route(route="platform/lineage/{request_id}", methods=["GET"])
async def platform_lineage_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Data lineage trace by Platform request ID.

    GET /api/platform/lineage/{request_id}

    Returns source → processing → output lineage for a Platform request.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_status import platform_lineage
    return await platform_lineage(req)


@app.route(route="platform/validate", methods=["POST"])
async def platform_validate_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Pre-flight validation before job submission.

    POST /api/platform/validate

    Validates a file exists, returns size, recommended job type, and
    estimated processing time before actually submitting a job.

    Body: {"data_type": "raster", "container_name": "...", "blob_name": "..."}
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_status import platform_validate
    return await platform_validate(req)


# REMOVED (21 JAN 2026): /platform/raster and /platform/raster-collection endpoints
# Use /platform/submit for all submissions - data_type is auto-detected from file extension
# Single vs collection is determined by whether file_name is string or array


# ============================================================================
# CONSOLIDATED UNPUBLISH ENDPOINT (21 JAN 2026)
# ============================================================================

@app.route(route="platform/unpublish", methods=["POST"])
def platform_unpublish_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Consolidated unpublish endpoint - auto-detects data type.

    POST /api/platform/unpublish

    Automatically detects whether to unpublish vector or raster data based on
    the platform request record or explicit parameters.

    Body Options:
        Option 1 - By DDH Identifiers (Preferred):
        {
            "dataset_id": "aerial-imagery-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "dry_run": true
        }

        Option 2 - By Request ID:
        {
            "request_id": "a3f2c1b8e9d7f6a5...",
            "dry_run": true
        }

        Option 3 - By Job ID:
        {
            "job_id": "abc123...",
            "dry_run": true
        }

        Option 4 - Explicit data_type (cleanup mode):
        {
            "data_type": "vector",
            "table_name": "my_table",
            "dry_run": true
        }

    Note: dry_run=true by default (preview mode, no deletions).
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_unpublish(req)


# ============================================================================
# DEPRECATED UNPUBLISH ENDPOINTS (21 JAN 2026)
# Use /api/platform/unpublish instead - it auto-detects data type
# ============================================================================

@app.route(route="platform/unpublish/vector", methods=["POST"])
def platform_unpublish_vector_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: Unpublish vector data via Platform layer.

    ⚠️ DEPRECATED (21 JAN 2026): Use POST /api/platform/unpublish instead.
    The consolidated endpoint auto-detects data type.

    POST /api/platform/unpublish/vector
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_unpublish_vector(req)


@app.route(route="platform/unpublish/raster", methods=["POST"])
def platform_unpublish_raster_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: Unpublish raster data via Platform layer.

    ⚠️ DEPRECATED (21 JAN 2026): Use POST /api/platform/unpublish instead.
    The consolidated endpoint auto-detects data type.

    POST /api/platform/unpublish/raster
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_unpublish_raster(req)


# =============================================================================
# APPROVAL PLATFORM ENDPOINTS (17 JAN 2026)
# =============================================================================

@app.route(route="platform/approve", methods=["POST"])
def platform_approve_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Approve a pending dataset for publication.

    POST /api/platform/approve

    Body:
        {
            "approval_id": "apr-abc123...",  // Or stac_item_id or job_id
            "reviewer": "user@example.com",
            "notes": "Looks good"            // Optional
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "approved",
            "action": "stac_updated",
            "message": "Dataset approved successfully"
        }
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_approve(req)


@app.route(route="platform/revoke", methods=["POST"])
def platform_revoke_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Revoke an approved dataset (unapprove).

    POST /api/platform/revoke

    This is an audit-logged operation for unpublishing approved data.

    Body:
        {
            "approval_id": "apr-abc123...",       // Or stac_item_id or job_id
            "revoker": "user@example.com",
            "reason": "Data quality issue found"  // Required for audit
        }

    Response:
        {
            "success": true,
            "approval_id": "apr-abc123...",
            "status": "revoked",
            "warning": "Approved dataset has been revoked - this action is logged for audit",
            "message": "Approval revoked successfully"
        }
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_revoke(req)


@app.route(route="platform/approvals", methods=["GET"])
def platform_approvals_list_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List approvals with optional filters.

    GET /api/platform/approvals?status=pending&limit=50

    Query Parameters:
        status: pending, approved, rejected, revoked
        classification: ouo, public
        limit: Max results (default 100)
        offset: Pagination offset

    Response:
        {
            "success": true,
            "approvals": [...],
            "count": 25,
            "status_counts": {"pending": 5, "approved": 15, ...}
        }
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_approvals_list(req)


@app.route(route="platform/approvals/{approval_id}", methods=["GET"])
def platform_approval_get_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a single approval by ID.

    GET /api/platform/approvals/{approval_id}

    Response:
        {
            "success": true,
            "approval": {...}
        }
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_approval_get(req)


@app.route(route="platform/approvals/status", methods=["GET"])
def platform_approvals_status_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get approval statuses for multiple STAC items/collections (batch lookup).

    GET /api/platform/approvals/status?stac_item_ids=item1,item2,item3
    GET /api/platform/approvals/status?stac_collection_ids=col1,col2

    Returns a map of ID -> approval status for quick UI lookups.
    Used by collection dashboards to show approved status and control delete buttons.

    Response:
        {
            "success": true,
            "statuses": {
                "item1": {"has_approval": true, "is_approved": true, ...},
                "item2": {"has_approval": false}
            }
        }
    """
    if guard := _platform_endpoint_guard():
        return guard
    return platform_approvals_status(req)


# ============================================================================
# PLATFORM CATALOG API - B2B STAC Access (16 JAN 2026 - F12.8)
# ============================================================================
# B2B endpoints for DDH to verify STAC items exist and get asset URLs.
# DDH can lookup using their identifiers without knowing our STAC IDs.
# ============================================================================

@app.route(route="platform/catalog/lookup", methods=["GET"])
async def platform_catalog_lookup_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Lookup STAC item by DDH identifiers.

    GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z

    Verifies that a STAC item exists for the given DDH identifiers.
    Returns STAC collection/item IDs and metadata if found.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_catalog import platform_catalog_lookup
    return await platform_catalog_lookup(req)


@app.route(route="platform/catalog/item/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_item_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get full STAC item by collection and item ID.

    GET /api/platform/catalog/item/{collection_id}/{item_id}

    Returns the complete STAC item (GeoJSON Feature) with all metadata.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_catalog import platform_catalog_item
    return await platform_catalog_item(req)


@app.route(route="platform/catalog/assets/{collection_id}/{item_id}", methods=["GET"])
async def platform_catalog_assets_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset URLs with pre-built TiTiler visualization URLs.

    GET /api/platform/catalog/assets/{collection_id}/{item_id}

    Returns asset URLs and TiTiler URLs for visualization.
    Query param: include_titiler=false to skip TiTiler URLs.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_catalog import platform_catalog_assets
    return await platform_catalog_assets(req)


@app.route(route="platform/catalog/dataset/{dataset_id}", methods=["GET"])
async def platform_catalog_dataset_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all STAC items for a DDH dataset.

    GET /api/platform/catalog/dataset/{dataset_id}?limit=100

    Returns all STAC items with the specified platform:dataset_id.
    """
    if guard := _platform_endpoint_guard():
        return guard
    from triggers.trigger_platform_catalog import platform_catalog_dataset
    return await platform_catalog_dataset(req)


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
logger.info("   QUEUE LISTENERS:")
logger.info(f"      listens_to_jobs_queue: {_app_mode.listens_to_jobs_queue}")
logger.info(f"      listens_to_raster_tasks: {_app_mode.listens_to_raster_tasks}")
logger.info(f"      listens_to_vector_tasks: {_app_mode.listens_to_vector_tasks}")
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


# Raster Tasks Queue Trigger - Raster worker/platform_raster/standalone modes
if STARTUP_STATE.all_passed and _app_mode.listens_to_raster_tasks:
    logger.info("✅ REGISTERING: raster-tasks queue trigger (GDAL/COG operations)")
elif _app_mode.listens_to_raster_tasks:
    logger.warning("⏭️ SKIPPING: raster-tasks queue trigger (validation failed)")
else:
    logger.warning("⏭️ SKIPPING: raster-tasks queue trigger (APP_MODE=%s)", _app_mode.mode.value)

if STARTUP_STATE.all_passed and _app_mode.listens_to_raster_tasks:
    # APP_CLEANUP Phase 2: Handler logic moved to triggers/service_bus/task_handler.py
    from triggers.service_bus import handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="raster-tasks",
        connection="ServiceBusConnection"
    )
    def process_raster_task(msg: func.ServiceBusMessage) -> None:
        """Process raster task messages from dedicated raster-tasks queue."""
        handle_task_message(msg, core_machine, queue_name="raster-tasks")


# Vector Tasks Queue Trigger - Vector worker/platform_vector/standalone modes
if STARTUP_STATE.all_passed and _app_mode.listens_to_vector_tasks:
    logger.info("✅ REGISTERING: vector-tasks queue trigger (PostGIS/geopandas operations)")
elif _app_mode.listens_to_vector_tasks:
    logger.warning("⏭️ SKIPPING: vector-tasks queue trigger (validation failed)")
else:
    logger.warning("⏭️ SKIPPING: vector-tasks queue trigger (APP_MODE=%s)", _app_mode.mode.value)

# Summary of trigger registration (updated 03 JAN 2026 for STARTUP_REFORM.md)
_registered_triggers = []
if STARTUP_STATE.all_passed and _app_mode.listens_to_jobs_queue:
    _registered_triggers.append("geospatial-jobs")
if STARTUP_STATE.all_passed and _app_mode.listens_to_raster_tasks:
    _registered_triggers.append("raster-tasks")
if STARTUP_STATE.all_passed and _app_mode.listens_to_vector_tasks:
    _registered_triggers.append("vector-tasks")

logger.info("-" * 70)
logger.info(f"🔌 SERVICE BUS TRIGGER REGISTRATION COMPLETE")
logger.info(f"   Triggers registered: {len(_registered_triggers)}/3")
logger.info(f"   Queues: {_registered_triggers}")
if not STARTUP_STATE.all_passed:
    logger.warning("⚠️ NO TRIGGERS REGISTERED - Startup validation failed")
    logger.warning("   Use GET /api/readyz to see validation errors")
elif len(_registered_triggers) == 0:
    logger.warning("⚠️ NO TRIGGERS REGISTERED - APP_MODE doesn't listen to any queues")
elif len(_registered_triggers) < 3:
    logger.warning(f"⚠️ Partial trigger registration (APP_MODE={_app_mode.mode.value})")
else:
    logger.info("✅ All 3 Service Bus triggers registered (standalone mode)")
logger.info("=" * 70)

if STARTUP_STATE.all_passed and _app_mode.listens_to_vector_tasks:
    # APP_CLEANUP Phase 2: Handler logic moved to triggers/service_bus/task_handler.py
    # Note: handle_task_message import already done above for raster trigger
    if 'handle_task_message' not in dir():
        from triggers.service_bus import handle_task_message

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="vector-tasks",
        connection="ServiceBusConnection"
    )
    def process_vector_task(msg: func.ServiceBusMessage) -> None:
        """Process vector task messages from dedicated vector-tasks queue."""
        handle_task_message(msg, core_machine, queue_name="vector-tasks")


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

    Handler: triggers/admin/geo_orphan_timer.py (extracted 09 JAN 2026)
    """
    from triggers.admin.geo_orphan_timer import geo_orphan_timer_handler
    geo_orphan_timer_handler.handle(timer)


# ============================================================================
# METADATA CONSISTENCY TIMER (09 JAN 2026 - F7.10)
# ============================================================================
# Timer trigger for unified metadata consistency validation.
# Runs every 6 hours, offset from geo_orphan_check_timer by 3 hours.
# Tier 1 checks: DB cross-refs + blob HEAD (lightweight, frequent).
# ============================================================================

@app.timer_trigger(
    schedule="0 0 3,9,15,21 * * *",  # Every 6 hours at 03:00, 09:00, 15:00, 21:00 UTC
    arg_name="timer",
    run_on_startup=False
)
def metadata_consistency_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Unified metadata consistency check every 6 hours.

    Tier 1 Checks (DB + blob HEAD):
    - STAC ↔ Metadata cross-reference (vector and raster)
    - Broken backlinks (metadata → STAC items)
    - Dataset refs FK integrity
    - Raster blob existence (HEAD only)

    Detection only - does NOT auto-delete. Logs findings to Application Insights.

    Schedule: Every 6 hours, offset from geo_orphan by 3 hours to spread load.

    Handler: triggers/admin/metadata_consistency_timer.py
    """
    from triggers.admin.metadata_consistency_timer import metadata_consistency_timer_handler
    metadata_consistency_timer_handler.handle(timer)


# ============================================================================
# GEO INTEGRITY TIMER (14 JAN 2026)
# ============================================================================
# Timer trigger for geo schema integrity validation.
# Detects tables with untyped geometry, missing SRID - incompatible with TiPG.
# Runs every 6 hours, offset from geo_orphan by 2 hours.
# ============================================================================

@app.timer_trigger(
    schedule="0 0 2,8,14,20 * * *",  # Every 6 hours at 02:00, 08:00, 14:00, 20:00 UTC
    arg_name="timer",
    run_on_startup=False
)
def geo_integrity_check_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check geo schema table integrity every 6 hours.

    Detects tables incompatible with TiPG/OGC Features:
    1. Untyped geometry columns (GEOMETRY without POLYGON, POINT, etc.)
    2. Missing SRID (srid = 0 or NULL)
    3. Missing spatial indexes
    4. Tables not registered in geometry_columns view

    Detection only - does NOT auto-delete. Logs DELETE CANDIDATES for manual action.

    Schedule: Every 6 hours, offset from geo_orphan by 2 hours to spread load.

    Handler: triggers/admin/geo_integrity_timer.py
    """
    from triggers.admin.geo_integrity_timer import geo_integrity_timer_handler
    geo_integrity_timer_handler.handle(timer)


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
# SYSTEM SNAPSHOT SCHEDULER (04 JAN 2026)
# ============================================================================
# Hourly timer trigger to capture system configuration snapshots.
# Detects configuration drift in Azure platform settings.
# Snapshots are also captured at startup and via manual endpoint.
# ============================================================================

@app.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def system_snapshot_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Capture system configuration snapshot hourly.

    Captures current system configuration including network/VNet settings,
    instance info, and config sources. Compares to previous snapshot and
    logs if configuration drift is detected.

    Schedule: Every hour on the hour (aligns with instance scaling)

    Handler: triggers/admin/system_snapshot_timer.py (extracted 09 JAN 2026)
    """
    from triggers.admin.system_snapshot_timer import system_snapshot_timer_handler
    system_snapshot_timer_handler.handle(timer)


@app.timer_trigger(
    schedule="0 0 3 * * *",  # Daily at 3 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def log_cleanup_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Clean up expired JSONL log files daily.

    Deletes old log files from Azure Blob Storage based on retention settings:
    - Verbose logs (DEBUG+): 7 days (JSONL_DEBUG_RETENTION_DAYS)
    - Default logs (WARNING+): 30 days (JSONL_WARNING_RETENTION_DAYS)
    - Metrics logs: 14 days (JSONL_METRICS_RETENTION_DAYS)

    Schedule: Daily at 3 AM UTC (low traffic period)

    Handler: triggers/admin/log_cleanup_timer.py (created 11 JAN 2026 - F7.12.F)
    """
    from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler
    log_cleanup_timer_handler.handle(timer)


# ============================================================================
# EXTERNAL SERVICE HEALTH TIMER (22 JAN 2026)
# ============================================================================
# Hourly timer trigger to check health of registered external geospatial services.
# Monitors ArcGIS, WMS, WFS, WMTS, OGC API, STAC API, XYZ tiles, etc.
# Sends notifications for outages/recoveries via App Insights and Service Bus.
# ============================================================================

@app.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def external_service_health_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check health of registered external geospatial services.

    Checks all services where next_check_at <= NOW() AND enabled = true.
    Updates status, consecutive_failures, and health_history.
    Sends notifications for status changes (outages and recoveries).

    Schedule: Every hour on the hour

    Handler: triggers/admin/external_service_timer.py (created 22 JAN 2026)
    """
    from triggers.admin.external_service_timer import external_service_health_timer_handler
    external_service_health_timer_handler.handle(timer)


# NOTE: Cleanup/janitor routes moved to triggers/admin/admin_janitor.py blueprint (12 JAN 2026)
# - /api/cleanup/run
# - /api/cleanup/metadata-health
# - /api/cleanup/status
# - /api/cleanup/history


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
