# APP_CLEANUP.md - function_app.py Refactoring Plan

**Created**: 23 JAN 2026
**Updated**: 23 JAN 2026
**Status**: Phase 1-4 COMPLETE, Phase 5-7 PLANNING
**Goal**: Reduce function_app.py from ~4,100 lines to a clean entry point

---

## Executive Summary

`function_app.py` has grown organically into a 4,100+ line file. After Phase 1-4 completion:
- **Current size**: ~2,990 lines (reduced from ~4,100)
- **Remaining work**: Blueprint migration + endpoint cleanup

### Completed (Phase 1-4)
- [x] Startup validation → `startup/` module
- [x] Service Bus handlers → `triggers/service_bus/` module
- [x] Timer triggers → `triggers/timers/timer_bp.py` blueprint
- [x] CoreMachine factory → `core/machine_factory.py`

### Remaining (Phase 5-7)
- [ ] **Phase 5**: Platform Blueprint (PRIORITY - anti-corruption layer)
- [ ] **Phase 6**: Endpoint Cleanup (delete deprecated, consolidate storage)
- [ ] **Phase 7**: STAC Admin Restructuring (all stac/ is admin-only)

---

## Current State Analysis

### File Statistics
| Metric | Value |
|--------|-------|
| Total lines | ~4,100 |
| Token count | ~45,000 |
| HTTP routes (inline) | ~75 |
| Blueprints registered | 14 |
| Service Bus triggers | 3 |
| Timer triggers | 10 |

### What's Already Using Blueprints (Good)
```
triggers/probes.py                    - livez/readyz
triggers/admin/admin_db.py            - 19 dbadmin routes
triggers/admin/admin_servicebus.py    - Service Bus admin
triggers/admin/admin_janitor.py       - Cleanup routes
triggers/admin/admin_stac.py          - STAC admin
triggers/admin/admin_h3.py            - H3 admin
triggers/admin/admin_system.py        - health, stats
triggers/admin/admin_approvals.py     - Dataset approvals
triggers/admin/admin_external_db.py   - External DB init
triggers/admin/admin_artifacts.py     - Artifact registry
triggers/admin/admin_external_services.py - External services
triggers/admin/admin_data_migration.py - ADF migration
triggers/admin/snapshot.py            - Snapshots
web_interfaces/h3_sources.py          - H3 sources UI
```

---

## Phase 1: Extract Startup Logic Module - COMPLETE

**Status**: COMPLETE (23 JAN 2026)
**Lines extracted**: ~230 (Service Bus validation portion)
**Module created**: `startup/service_bus_validator.py`

### Problem
Startup validation was built through trial-and-error debugging. It works but is scattered across 500+ lines in the entry point:
- Import validation (lines 172-199)
- Environment variable validation (lines 205-280)
- Service Bus DNS validation (lines 2719-2790)
- Service Bus queue validation (lines 2792-2901)
- Startup state finalization (lines 2903-2968)

### Solution
Create `startup/` module with clean separation:

```
startup/
├── __init__.py           # Exports run_startup_validation()
├── import_validator.py   # Check critical imports
├── env_validator.py      # Regex-based env var validation
├── service_bus_validator.py  # DNS + queue checks
└── startup_state.py      # STARTUP_STATE singleton (move from startup_state.py)
```

### New Entry Point Pattern
```python
# function_app.py - AFTER Phase 1

from startup import run_startup_validation, STARTUP_STATE

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Phase 1: Probe endpoints (always available)
from triggers.probes import bp as probes_bp
app.register_functions(probes_bp)

# Phase 2: Run all validation
run_startup_validation()  # Populates STARTUP_STATE

# Phase 3: Conditional registration based on STARTUP_STATE.all_passed
if STARTUP_STATE.all_passed:
    # Register blueprints and triggers
    ...
```

### Files to Create

#### `startup/__init__.py`
```python
"""
Startup validation module for Azure Functions.

Provides comprehensive validation before registering Service Bus triggers:
1. Import validation - critical modules can be imported
2. Environment validation - required vars present with correct format
3. Service Bus DNS - namespace resolves
4. Service Bus queues - required queues exist

Usage:
    from startup import run_startup_validation, STARTUP_STATE

    run_startup_validation()
    if STARTUP_STATE.all_passed:
        # Register triggers
"""

from .startup_state import STARTUP_STATE, ValidationResult
from .orchestrator import run_startup_validation

__all__ = ['run_startup_validation', 'STARTUP_STATE', 'ValidationResult']
```

#### `startup/orchestrator.py`
```python
"""
Startup validation orchestrator.

Runs all validation phases in order and populates STARTUP_STATE.
"""

import logging
from .startup_state import STARTUP_STATE
from .import_validator import validate_imports
from .env_validator import validate_environment
from .service_bus_validator import validate_service_bus

_logger = logging.getLogger("startup")

def run_startup_validation() -> None:
    """Run all startup validations and finalize STARTUP_STATE."""
    _logger.info("🔍 STARTUP: Running validation phases...")

    # Phase 1: Import validation
    STARTUP_STATE.imports = validate_imports()

    # Phase 2: Environment validation
    STARTUP_STATE.env_vars = validate_environment()

    # Phase 3: Service Bus validation (DNS + queues)
    dns_result, queue_result = validate_service_bus()
    STARTUP_STATE.service_bus_dns = dns_result
    STARTUP_STATE.service_bus_queues = queue_result

    # Finalize
    STARTUP_STATE.finalize()
    STARTUP_STATE.detect_default_env_vars()

    if STARTUP_STATE.all_passed:
        _logger.info("✅ STARTUP: All validations PASSED")
    else:
        failed = STARTUP_STATE.get_failed_checks()
        _logger.warning(f"⚠️ STARTUP: {len(failed)} validation(s) FAILED: {[f.name for f in failed]}")
```

### Acceptance Criteria
- [ ] `startup/` module created with 5 files
- [ ] `run_startup_validation()` called once in function_app.py
- [ ] All startup logic removed from function_app.py (~500 lines)
- [ ] Existing tests pass
- [ ] /api/readyz returns same results as before

---

## Phase 2: Extract Service Bus Handler Logic - COMPLETE

**Status**: COMPLETE (23 JAN 2026)
**Lines extracted**: ~400
**Module created**: `triggers/service_bus/` (job_handler.py, task_handler.py, error_handler.py)

### Problem
Each Service Bus trigger (lines 3010-3501) contains ~120 lines of nearly identical code:
- Message parsing
- Correlation ID generation
- PENDING → QUEUED status update
- CoreMachine delegation
- Exception handling with job/task failure marking

### Current Duplication
```python
# process_service_bus_job (~150 lines)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    logger.info(f"[{correlation_id}] 📥 SERVICE BUS MESSAGE RECEIVED...")
    # ... 140 more lines of handling

# process_raster_task (~140 lines) - 95% identical
# process_vector_task (~140 lines) - 95% identical
```

### Solution
Create `triggers/service_bus/` module:

```
triggers/service_bus/
├── __init__.py
├── job_handler.py      # Job queue processing logic
├── task_handler.py     # Task queue processing logic (shared)
└── error_handler.py    # Extracted from function_app.py lines 3507-3665
```

### New Pattern
```python
# function_app.py - AFTER Phase 2

from triggers.service_bus import handle_job_message, handle_task_message

if STARTUP_STATE.all_passed and _app_mode.listens_to_jobs_queue:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
        """Process job messages using CoreMachine."""
        handle_job_message(msg, core_machine)

if STARTUP_STATE.all_passed and _app_mode.listens_to_raster_tasks:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="raster-tasks",
        connection="ServiceBusConnection"
    )
    def process_raster_task(msg: func.ServiceBusMessage) -> None:
        """Process raster task messages."""
        handle_task_message(msg, core_machine, queue_name="raster-tasks")

if STARTUP_STATE.all_passed and _app_mode.listens_to_vector_tasks:
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="vector-tasks",
        connection="ServiceBusConnection"
    )
    def process_vector_task(msg: func.ServiceBusMessage) -> None:
        """Process vector task messages."""
        handle_task_message(msg, core_machine, queue_name="vector-tasks")
```

### Files to Create

#### `triggers/service_bus/job_handler.py`
```python
"""
Job queue message handler.

Handles messages from geospatial-jobs queue:
- job_submit: New job or stage advancement
- stage_complete: Signal from worker app
"""

import json
import time
import uuid
import traceback
from typing import Any, Dict

import azure.functions as func

from core.schema.queue import JobQueueMessage
from core.machine import CoreMachine
from infrastructure import RepositoryFactory
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "JobHandler")


def handle_job_message(msg: func.ServiceBusMessage, core_machine: CoreMachine) -> Dict[str, Any]:
    """
    Process a job message from Service Bus.

    Args:
        msg: Service Bus message
        core_machine: CoreMachine instance for processing

    Returns:
        Processing result dict
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    # Log receipt immediately (GAP-1 fix)
    _log_message_received(msg, correlation_id, "geospatial-jobs")

    try:
        message_body = msg.get_body().decode('utf-8')
        message_dict = json.loads(message_body)
        message_type = message_dict.get('message_type', 'job_submit')

        if message_type == 'stage_complete':
            result = _handle_stage_complete(message_dict, core_machine, correlation_id)
        else:
            result = _handle_job_submit(message_body, core_machine, correlation_id)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] ✅ Processed in {elapsed:.3f}s")
        return result

    except Exception as e:
        _handle_job_exception(e, msg, correlation_id, start_time)
        return {"success": False, "error": str(e)}


def _log_message_received(msg: func.ServiceBusMessage, correlation_id: str, queue_name: str) -> None:
    """Log Service Bus message metadata immediately on receipt."""
    logger.info(
        f"[{correlation_id}] 📥 SERVICE BUS MESSAGE RECEIVED ({queue_name})",
        extra={
            'checkpoint': 'MESSAGE_RECEIVED',
            'correlation_id': correlation_id,
            'queue_name': queue_name,
            'message_id': msg.message_id,
            'sequence_number': msg.sequence_number,
            'delivery_count': msg.delivery_count,
        }
    )


def _handle_stage_complete(message_dict: dict, core_machine: CoreMachine, correlation_id: str) -> dict:
    """Handle stage_complete message from worker app."""
    logger.info(f"[{correlation_id}] 📬 Processing stage_complete")
    return core_machine.process_stage_complete_message(message_dict)


def _handle_job_submit(message_body: str, core_machine: CoreMachine, correlation_id: str) -> dict:
    """Handle job_submit message (new job or stage advancement)."""
    job_message = JobQueueMessage.model_validate_json(message_body)
    logger.info(f"[{correlation_id}] ✅ Parsed job: {job_message.job_id[:16]}...")

    if job_message.parameters is None:
        job_message.parameters = {}
    job_message.parameters['_correlation_id'] = correlation_id
    job_message.parameters['_processing_path'] = 'service_bus'

    return core_machine.process_job_message(job_message)


def _handle_job_exception(e: Exception, msg: func.ServiceBusMessage, correlation_id: str, start_time: float) -> None:
    """Handle exception during job processing - mark job as FAILED."""
    from .error_handler import extract_job_id_from_raw_message, mark_job_failed

    elapsed = time.time() - start_time
    logger.error(f"[{correlation_id}] ❌ EXCEPTION after {elapsed:.3f}s: {e}")
    logger.error(traceback.format_exc())

    # Try to extract job_id and mark as failed
    message_body = msg.get_body().decode('utf-8') if msg else ''
    job_id = extract_job_id_from_raw_message(message_body, correlation_id)

    if job_id:
        mark_job_failed(job_id, f"{type(e).__name__}: {e}", correlation_id)
```

#### `triggers/service_bus/task_handler.py`
```python
"""
Task queue message handler.

Handles messages from raster-tasks and vector-tasks queues.
Shared logic for both task types with queue-specific logging.
"""

import time
import uuid
import traceback
from typing import Any, Dict

import azure.functions as func

from core.schema.queue import TaskQueueMessage
from core.models.enums import TaskStatus
from core.machine import CoreMachine
from infrastructure import RepositoryFactory
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "TaskHandler")


def handle_task_message(
    msg: func.ServiceBusMessage,
    core_machine: CoreMachine,
    queue_name: str
) -> Dict[str, Any]:
    """
    Process a task message from Service Bus.

    Args:
        msg: Service Bus message
        core_machine: CoreMachine instance for processing
        queue_name: Queue name for logging ("raster-tasks" or "vector-tasks")

    Returns:
        Processing result dict
    """
    correlation_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    # Log receipt immediately (GAP-1 fix)
    _log_message_received(msg, correlation_id, queue_name)

    try:
        message_body = msg.get_body().decode('utf-8')
        task_message = TaskQueueMessage.model_validate_json(message_body)

        logger.info(f"[{correlation_id}] ✅ Parsed task: {task_message.task_id}, type={task_message.task_type}")

        # Add correlation tracking
        if task_message.parameters is None:
            task_message.parameters = {}
        task_message.parameters['_correlation_id'] = correlation_id
        task_message.parameters['_processing_path'] = queue_name

        # PENDING → QUEUED confirmation
        _confirm_task_queued(task_message.task_id, correlation_id, queue_name)

        # Process via CoreMachine
        result = core_machine.process_task_message(task_message)

        elapsed = time.time() - start_time
        logger.info(f"[{correlation_id}] ✅ Task processed in {elapsed:.3f}s")

        if result.get('stage_complete'):
            logger.info(f"[{correlation_id}] 🎯 Stage {task_message.stage} complete")

        return result

    except Exception as e:
        _handle_task_exception(e, msg, correlation_id, start_time)
        return {"success": False, "error": str(e)}


def _log_message_received(msg: func.ServiceBusMessage, correlation_id: str, queue_name: str) -> None:
    """Log Service Bus message metadata immediately on receipt."""
    logger.info(
        f"[{correlation_id}] 📥 SERVICE BUS MESSAGE RECEIVED ({queue_name})",
        extra={
            'checkpoint': 'MESSAGE_RECEIVED',
            'correlation_id': correlation_id,
            'queue_name': queue_name,
            'message_id': msg.message_id,
            'sequence_number': msg.sequence_number,
            'delivery_count': msg.delivery_count,
        }
    )


def _confirm_task_queued(task_id: str, correlation_id: str, queue_name: str) -> None:
    """Update task status from PENDING to QUEUED."""
    try:
        repos = RepositoryFactory.create_repositories()
        success = repos['task_repo'].update_task_status_with_validation(
            task_id,
            TaskStatus.QUEUED
        )
        if success:
            logger.info(f"[{correlation_id}] ✅ PENDING → QUEUED for {task_id[:16]}...")
        else:
            current = repos['task_repo'].get_task_status(task_id)
            logger.warning(f"[{correlation_id}] ⚠️ PENDING → QUEUED returned False. Current: {current}")
    except Exception as e:
        logger.error(f"[{correlation_id}] ❌ Failed PENDING → QUEUED: {e}")


def _handle_task_exception(e: Exception, msg: func.ServiceBusMessage, correlation_id: str, start_time: float) -> None:
    """Handle exception during task processing - mark task/job as FAILED."""
    from .error_handler import extract_task_id_from_raw_message, mark_task_failed

    elapsed = time.time() - start_time
    logger.error(f"[{correlation_id}] ❌ EXCEPTION after {elapsed:.3f}s: {e}")
    logger.error(traceback.format_exc())

    # Try to extract task_id and mark as failed
    message_body = msg.get_body().decode('utf-8') if msg else ''
    task_id, job_id = extract_task_id_from_raw_message(message_body, correlation_id)

    if task_id or job_id:
        mark_task_failed(task_id, job_id, f"{type(e).__name__}: {e}", correlation_id)
```

#### `triggers/service_bus/error_handler.py`
Move these functions from function_app.py (lines 3507-3665):
- `_extract_job_id_from_raw_message` → `extract_job_id_from_raw_message`
- `_extract_task_id_from_raw_message` → `extract_task_id_from_raw_message`
- `_mark_job_failed_from_queue_error` → `mark_job_failed`
- `_mark_task_failed_from_queue_error` → `mark_task_failed`

### Acceptance Criteria
- [ ] `triggers/service_bus/` module created with 4 files
- [ ] Service Bus triggers in function_app.py reduced to ~10 lines each
- [ ] Error handler functions removed from function_app.py (~180 lines)
- [ ] All logging and checkpoints preserved
- [ ] Existing job/task processing unchanged

---

## Phase 3: Extract Timer Triggers to Blueprint - COMPLETE

**Status**: COMPLETE (23 JAN 2026)
**Lines extracted**: ~175
**Module created**: `triggers/timers/timer_bp.py` (10 timers)
Timer triggers CAN use Azure Functions Blueprint pattern:

```python
# triggers/timers/timer_bp.py
from azure.functions import Blueprint, TimerRequest

bp = Blueprint()

@bp.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def janitor_task_watchdog(timer: TimerRequest) -> None:
    from triggers.janitor import task_watchdog_handler
    task_watchdog_handler(timer)
```

### Current Timer Triggers (10 total)

| Timer | Schedule | Purpose | Handler Location |
|-------|----------|---------|------------------|
| `janitor_task_watchdog` | Every 5 min | Stale PROCESSING tasks | triggers/janitor.py |
| `janitor_job_health` | :15 and :45 | Failed task propagation | triggers/janitor.py |
| `janitor_orphan_detector` | Every hour | Orphaned tasks/zombies | triggers/janitor.py |
| `geo_orphan_check_timer` | Every 6 hours | Geo schema orphans | triggers/admin/geo_orphan_timer.py |
| `metadata_consistency_timer` | Every 6 hours | STAC↔Metadata checks | triggers/admin/metadata_consistency_timer.py |
| `geo_integrity_check_timer` | Every 6 hours | TiPG compatibility | triggers/admin/geo_integrity_timer.py |
| `curated_dataset_scheduler` | Daily 2 AM | Curated updates | triggers/curated/scheduler.py |
| `system_snapshot_timer` | Every hour | Config drift detection | triggers/admin/system_snapshot_timer.py |
| `log_cleanup_timer` | Daily 3 AM | JSONL retention | triggers/admin/log_cleanup_timer.py |
| `external_service_health_timer` | Every hour | External service health | triggers/admin/external_service_timer.py |

### Solution
Create unified timer blueprint:

```
triggers/timers/
├── __init__.py
├── timer_bp.py          # Blueprint with all timer triggers
├── janitor_timers.py    # Janitor timer configs
└── maintenance_timers.py # Maintenance timer configs
```

#### `triggers/timers/timer_bp.py`
```python
"""
Timer Triggers Blueprint.

Consolidates all timer triggers into a single blueprint.
Handlers remain in their original locations for logical grouping.
"""

from azure.functions import Blueprint, TimerRequest

bp = Blueprint()


# =============================================================================
# JANITOR TIMERS - System maintenance (lines 3690-3748 in function_app.py)
# =============================================================================

@bp.timer_trigger(
    schedule="0 */5 * * * *",  # Every 5 minutes
    arg_name="timer",
    run_on_startup=False
)
def janitor_task_watchdog(timer: TimerRequest) -> None:
    """Detect stale PROCESSING tasks and orphaned QUEUED tasks."""
    from triggers.janitor import task_watchdog_handler
    task_watchdog_handler(timer)


@bp.timer_trigger(
    schedule="0 15,45 * * * *",  # At :15 and :45 past each hour
    arg_name="timer",
    run_on_startup=False
)
def janitor_job_health(timer: TimerRequest) -> None:
    """Check job health and propagate task failures."""
    from triggers.janitor import job_health_handler
    job_health_handler(timer)


@bp.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def janitor_orphan_detector(timer: TimerRequest) -> None:
    """Detect orphaned tasks and zombie jobs."""
    from triggers.janitor import orphan_detector_handler
    orphan_detector_handler(timer)


# =============================================================================
# INTEGRITY TIMERS - Data consistency checks
# =============================================================================

@bp.timer_trigger(
    schedule="0 0 */6 * * *",  # Every 6 hours
    arg_name="timer",
    run_on_startup=False
)
def geo_orphan_check_timer(timer: TimerRequest) -> None:
    """Check for geo schema orphans."""
    from triggers.admin.geo_orphan_timer import geo_orphan_timer_handler
    geo_orphan_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 3,9,15,21 * * *",  # Every 6 hours, offset by 3
    arg_name="timer",
    run_on_startup=False
)
def metadata_consistency_timer(timer: TimerRequest) -> None:
    """Unified metadata consistency check."""
    from triggers.admin.metadata_consistency_timer import metadata_consistency_timer_handler
    metadata_consistency_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 2,8,14,20 * * *",  # Every 6 hours, offset by 2
    arg_name="timer",
    run_on_startup=False
)
def geo_integrity_check_timer(timer: TimerRequest) -> None:
    """Check geo schema table integrity for TiPG compatibility."""
    from triggers.admin.geo_integrity_timer import geo_integrity_timer_handler
    geo_integrity_timer_handler.handle(timer)


# =============================================================================
# SCHEDULER TIMERS - Scheduled operations
# =============================================================================

@bp.timer_trigger(
    schedule="0 0 2 * * *",  # Daily at 2 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def curated_dataset_scheduler(timer: TimerRequest) -> None:
    """Check curated datasets for updates."""
    from triggers.curated.scheduler import curated_scheduler_trigger
    curated_scheduler_trigger.handle_timer(timer)


@bp.timer_trigger(
    schedule="0 0 * * * *",  # Every hour
    arg_name="timer",
    run_on_startup=False
)
def system_snapshot_timer(timer: TimerRequest) -> None:
    """Capture system configuration snapshot."""
    from triggers.admin.system_snapshot_timer import system_snapshot_timer_handler
    system_snapshot_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 3 * * *",  # Daily at 3 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def log_cleanup_timer(timer: TimerRequest) -> None:
    """Clean up expired JSONL log files."""
    from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler
    log_cleanup_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 * * * *",  # Every hour
    arg_name="timer",
    run_on_startup=False
)
def external_service_health_timer(timer: TimerRequest) -> None:
    """Check health of registered external services."""
    from triggers.admin.external_service_timer import external_service_health_timer_handler
    external_service_health_timer_handler.handle(timer)
```

### Registration in function_app.py
```python
# Register timer blueprint
from triggers.timers import bp as timer_bp
app.register_functions(timer_bp)
```

### Acceptance Criteria
- [ ] `triggers/timers/timer_bp.py` created with all 10 timers
- [ ] Timer triggers removed from function_app.py (~200 lines)
- [ ] Blueprint registered in function_app.py
- [ ] All timer schedules unchanged
- [ ] Timer handlers remain in original locations

---

## Phase 4: Extract CoreMachine Initialization and Callbacks - COMPLETE

**Status**: COMPLETE (23 JAN 2026)
**Lines extracted**: ~120
**Module created**: `core/machine_factory.py`

### Problem
CoreMachine initialization and the platform callback (`_global_platform_callback`) are defined inline in function_app.py with ~170 lines of code including:
- `_global_platform_callback` function (lines 471-520)
- `_extract_stac_item_id` helper (lines 523-558)
- `_extract_stac_collection_id` helper (lines 561-594)
- `_extract_classification` helper (lines 597-630)
- CoreMachine instantiation (lines 633-637)

### Solution
Create `core/machine_factory.py`:

```python
"""
CoreMachine factory and callbacks.

Provides configured CoreMachine instance with Platform callbacks.
"""

from typing import Callable, Optional
from core.machine import CoreMachine
from jobs import ALL_JOBS
from services import ALL_HANDLERS
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CORE, "MachineFactory")


def create_core_machine(on_job_complete: Optional[Callable] = None) -> CoreMachine:
    """
    Create configured CoreMachine instance.

    Args:
        on_job_complete: Optional callback for job completion

    Returns:
        Configured CoreMachine instance
    """
    callback = on_job_complete or _default_platform_callback

    machine = CoreMachine(
        all_jobs=ALL_JOBS,
        all_handlers=ALL_HANDLERS,
        on_job_complete=callback
    )

    logger.info("✅ CoreMachine initialized with explicit registries")
    logger.info(f"   Registered jobs: {list(ALL_JOBS.keys())}")
    logger.info(f"   Registered handlers: {list(ALL_HANDLERS.keys())}")

    return machine


def _default_platform_callback(job_id: str, job_type: str, status: str, result: dict) -> None:
    """
    Default callback for Platform orchestration.

    Creates approval records for completed jobs that produce STAC items.
    """
    if status != 'completed':
        return

    try:
        stac_item_id = _extract_stac_item_id(result)
        stac_collection_id = _extract_stac_collection_id(result)

        if stac_item_id:
            from services.approval_service import ApprovalService
            from core.models.promoted import Classification

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
            logger.info(f"📋 [APPROVAL] Created {approval.approval_id[:12]}... for job {job_id[:8]}...")

    except Exception as e:
        logger.warning(f"⚠️ [APPROVAL] Failed for job {job_id[:8]}... (non-fatal): {e}")


def _extract_stac_item_id(result: dict) -> Optional[str]:
    """Extract STAC item ID from various result structures."""
    if not result:
        return None

    paths = [
        ('stac', 'item_id'),
        ('result', 'stac', 'item_id'),
        ('item_id',),
        ('stac_item_id',),
        ('result', 'item_id'),
    ]

    for path in paths:
        value = result
        for key in path:
            value = value.get(key, {}) if isinstance(value, dict) else None
            if value is None:
                break
        if value and isinstance(value, str):
            return value

    return None


def _extract_stac_collection_id(result: dict) -> Optional[str]:
    """Extract STAC collection ID from various result structures."""
    if not result:
        return None

    paths = [
        ('stac', 'collection_id'),
        ('result', 'stac', 'collection_id'),
        ('collection_id',),
        ('stac_collection_id',),
        ('result', 'collection_id'),
    ]

    for path in paths:
        value = result
        for key in path:
            value = value.get(key, {}) if isinstance(value, dict) else None
            if value is None:
                break
        if value and isinstance(value, str):
            return value

    return None


def _extract_classification(result: dict) -> str:
    """Extract classification from job result."""
    if not result:
        return 'ouo'

    # Check various locations
    if result.get('classification'):
        return result['classification'].lower()
    if result.get('parameters', {}).get('classification'):
        return result['parameters']['classification'].lower()
    if result.get('result', {}).get('classification'):
        return result['result']['classification'].lower()

    access_level = result.get('access_level') or result.get('parameters', {}).get('access_level')
    if access_level and access_level.lower() == 'public':
        return 'public'

    return 'ouo'
```

### New Pattern in function_app.py
```python
# function_app.py - AFTER Phase 4

from core.machine_factory import create_core_machine

# Initialize CoreMachine (moved from inline)
core_machine = create_core_machine()
```

### Acceptance Criteria
- [ ] `core/machine_factory.py` created
- [ ] Callback and helper functions removed from function_app.py (~170 lines)
- [ ] CoreMachine instantiation reduced to 1 line
- [ ] Approval creation still works for completed jobs

---

## Phase 5: Platform Blueprint - PRIORITY

**Status**: PLANNING
**Priority**: HIGH - Anti-corruption layer for external apps (DDH)
**Lines to extract**: ~400

### Rationale
Platform/ is the **anti-corruption layer** that will run as its own gateway application coordinating all job requests from outside apps to our core orchestration. This is the top priority for blueprinting because:
1. It's the primary external interface
2. It will eventually be a separate Azure Function App
3. Clean separation enables independent deployment

### Current Platform Endpoints (20 total)

| Route | Method | Purpose | Keep? |
|-------|--------|---------|-------|
| `/platform/submit` | POST | Submit request from DDH | YES |
| `/platform/status/{id}` | GET | Get request/job status | YES |
| `/platform/status` | GET | List all requests | YES |
| `/platform/jobs/{job_id}/status` | GET | Job status by ID | **DELETE** (deprecated) |
| `/platform/health` | GET | System readiness | YES |
| `/platform/failures` | GET | Recent failures | YES |
| `/platform/lineage/{id}` | GET | Data lineage trace | YES |
| `/platform/validate` | POST | Pre-flight validation | YES |
| `/platform/unpublish` | POST | Consolidated unpublish | YES |
| `/platform/unpublish/vector` | POST | Vector unpublish | **DELETE** (deprecated) |
| `/platform/unpublish/raster` | POST | Raster unpublish | **DELETE** (deprecated) |
| `/platform/approve` | POST | Approve dataset | YES |
| `/platform/revoke` | POST | Revoke approval | YES |
| `/platform/approvals` | GET | List approvals | YES |
| `/platform/approvals/{id}` | GET | Get approval | YES |
| `/platform/approvals/status` | GET | Approval status summary | YES |
| `/platform/catalog/lookup` | GET | STAC lookup by DDH IDs | YES |
| `/platform/catalog/item/{c}/{i}` | GET | Get STAC item | YES |
| `/platform/catalog/assets/{c}/{i}` | GET | Get assets with TiTiler URLs | YES |
| `/platform/catalog/dataset/{id}` | GET | List items for dataset | YES |

### Blueprint Structure
```
triggers/platform/
├── __init__.py
├── platform_bp.py           # Blueprint with all 17 endpoints
├── submit_handler.py        # /platform/submit logic
├── status_handler.py        # /platform/status/* logic
├── approval_handler.py      # /platform/approve, /revoke, /approvals/*
├── catalog_handler.py       # /platform/catalog/* logic
└── unpublish_handler.py     # /platform/unpublish logic
```

### Acceptance Criteria
- [ ] Blueprint created with 17 endpoints (3 deprecated deleted)
- [ ] All platform/* routes removed from function_app.py (~400 lines)
- [ ] Conditional registration based on APP_MODE (gateway modes only)
- [ ] All existing tests pass

---

## Phase 6: Endpoint Cleanup

**Status**: PLANNING
**Priority**: MEDIUM

### 6A: Delete Deprecated Endpoints

| Endpoint | Deprecated Date | Replacement |
|----------|-----------------|-------------|
| `platform/jobs/{job_id}/status` | 21 JAN 2026 | `/platform/status/{job_id}` |
| `platform/unpublish/vector` | 21 JAN 2026 | `/platform/unpublish` |
| `platform/unpublish/raster` | 21 JAN 2026 | `/platform/unpublish` |

### 6B: Delete Duplicate STAC Endpoints

The `/api/collections/*` routes duplicate `/api/stac/collections/*`:

| Delete | Keep |
|--------|------|
| `GET /collections` | `GET /stac/collections` |
| `GET /collections/{id}` | `GET /stac/collections/{id}` |
| `GET /collections/{id}/items` | `GET /stac/collections/{id}/items` |
| `GET /search` | (move to stac/search or delete) |

**Lines to delete**: ~170 (lines 1641-1807)

### 6C: Consolidate Storage Endpoints

Merge `containers/*` into `storage/*`:

| Current | New |
|---------|-----|
| `GET /containers/{name}/blobs` | `GET /storage/{container}/blobs` |
| `GET /containers/{name}/blob` | `GET /storage/{container}/blob` |
| `GET /storage/containers` | Keep |
| `POST /storage/upload` | Keep |

**Lines affected**: ~50

### Acceptance Criteria
- [ ] 3 deprecated platform endpoints deleted
- [ ] 4 duplicate collections/* endpoints deleted
- [ ] containers/* merged into storage/*
- [ ] ~220 lines removed

---

## Phase 7: STAC Admin Restructuring

**Status**: PLANNING
**Priority**: MEDIUM

### Design Decision
**ALL stac/ endpoints are admin-only** - there is no B2C (business-to-consumer) STAC API. All access is through our Platform layer or internal admin tools.

### Current STAC Endpoints

| Route | Type | Current Location | Action |
|-------|------|------------------|--------|
| `stac/` (landing) | API | function_app.py | → `admin_stac_bp` |
| `stac/conformance` | API | function_app.py | → `admin_stac_bp` |
| `stac/collections` | API | function_app.py | → `admin_stac_bp` |
| `stac/collections/{id}` | API | function_app.py | → `admin_stac_bp` |
| `stac/collections/{id}/items` | API | function_app.py | → `admin_stac_bp` |
| `stac/collections/{id}/items/{item}` | API | function_app.py | → `admin_stac_bp` |
| `stac/schema/info` | Admin | function_app.py | → `admin_stac_bp` |
| `stac/collections/summary` | Admin | function_app.py | → `admin_stac_bp` |
| `stac/collections/{id}/stats` | Admin | function_app.py | → `admin_stac_bp` |
| `stac/items/{item_id}` | Admin | function_app.py | → `admin_stac_bp` |
| `stac/health` | Admin | function_app.py | → `admin_stac_bp` |
| `stac/vector` | Write | function_app.py | → `admin_stac_bp` |
| `stac/extract` | Utility | function_app.py | → `admin_stac_bp` |
| `stac/repair/*` | Admin | admin_stac_bp | Keep |
| `stac/nuke` | Admin | admin_stac_bp | Keep |

### Solution
Consolidate ALL stac/* endpoints into the existing `admin_stac_bp` blueprint:

```python
# triggers/admin/admin_stac.py - EXPANDED
# Now contains ALL stac/ endpoints (API + admin + write)
```

### Acceptance Criteria
- [ ] All 13 inline stac/* endpoints moved to admin_stac_bp
- [ ] Existing admin_stac_bp endpoints preserved
- [ ] ~200 lines removed from function_app.py

---

## Summary: Line Reduction Progress

### Completed (Phases 1-4)

| Phase | Lines Removed | Module Created |
|-------|---------------|----------------|
| Phase 1: Startup Logic | ~230 | `startup/service_bus_validator.py` |
| Phase 2: Service Bus Handlers | ~400 | `triggers/service_bus/` |
| Phase 3: Timer Triggers | ~175 | `triggers/timers/timer_bp.py` |
| Phase 4: CoreMachine Factory | ~120 | `core/machine_factory.py` |
| **Phases 1-4 Total** | **~925** | |

**Current state**: function_app.py reduced from ~4,100 to ~2,990 lines

### Planned (Phases 5-7)

| Phase | Lines to Remove | Target |
|-------|-----------------|--------|
| Phase 5: Platform Blueprint | ~400 | `triggers/platform/platform_bp.py` |
| Phase 6: Endpoint Cleanup | ~220 | Delete deprecated + duplicates |
| Phase 7: STAC Admin | ~200 | Expand `admin_stac_bp` |
| **Phases 5-7 Total** | **~820** | |

**After Phases 5-7**: function_app.py reduced to ~2,170 lines

### Future Blueprint Candidates

| Blueprint | Routes | Priority |
|-----------|--------|----------|
| `raster_bp` | 14 raster/* + 3 xarray/* | Medium |
| `maps_bp` | 8 maps/* | Medium |
| `features_bp` | 8 features/* (OGC) | Low |
| `jobs_bp` | 5 jobs/* | Low |
| `promote_bp` | 5 promote/* | Low |

**After all blueprints**: function_app.py reduced to ~800 lines (pure entry point)

---

## Execution Order

```
Phase 1-4: COMPLETE (23 JAN 2026)
    ├── startup/service_bus_validator.py
    ├── triggers/service_bus/ (job_handler, task_handler, error_handler)
    ├── triggers/timers/timer_bp.py
    └── core/machine_factory.py

Phase 5: Platform Blueprint (NEXT)
    ├── Delete 3 deprecated endpoints
    ├── Create triggers/platform/platform_bp.py
    ├── Move 17 platform/* endpoints to blueprint
    ├── Test Platform submission/status flow
    └── Commit: "Extract Platform layer to dedicated blueprint"

Phase 6: Endpoint Cleanup
    ├── Delete duplicate collections/* endpoints
    ├── Consolidate containers/* into storage/*
    └── Commit: "Remove duplicate and consolidate storage endpoints"

Phase 7: STAC Admin Restructuring
    ├── Move all stac/* endpoints to admin_stac_bp
    ├── Expand existing admin_stac_bp
    └── Commit: "Consolidate all STAC endpoints as admin-only"

[FUTURE: Additional blueprint migrations as needed]
```

---

## Testing Checklist

### Phase 1-4 Tests (COMPLETE)
- [x] `GET /api/livez` returns 200
- [x] `GET /api/readyz` returns validation results
- [x] `GET /api/health` shows component status
- [x] Job processes through Service Bus queues
- [x] Timer triggers registered in Azure
- [x] CoreMachine processes jobs correctly

### Phase 5 Tests (Platform Blueprint)
- [ ] `POST /platform/submit` creates request
- [ ] `GET /platform/status/{id}` returns status
- [ ] `POST /platform/unpublish` works (consolidated)
- [ ] Deprecated endpoints return 404

### Phase 6 Tests (Endpoint Cleanup)
- [ ] `/collections/*` returns 404
- [ ] `/stac/collections/*` still works
- [ ] `/storage/{container}/blobs` works (new route)

### Phase 7 Tests (STAC Admin)
- [ ] All stac/* endpoints work via admin_stac_bp
- [ ] Conditional registration for admin modes only

---

## References

- `CLAUDE.md` - Project context and deployment guide
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Job→Stage→Task pattern
- `docs_claude/DEV_BEST_PRACTICES.md` - Coding patterns
- `startup_state.py` - Existing STARTUP_STATE singleton
