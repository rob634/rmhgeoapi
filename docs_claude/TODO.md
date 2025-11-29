# Active Tasks - Geospatial ETL Pipelines

**Last Updated**: 28 NOV 2025 (UTC)
**Author**: Robert and Geospatial Claude Legion

---

## ✅ COMPLETED: PROCESS_RASTER_V2 - JobBaseMixin Implementation (28 NOV 2025)

**Status**: ✅ **COMPLETED AND TESTED**
**Priority**: **HIGH** - Clean slate raster workflow using JobBaseMixin pattern
**Impact**: 73% code reduction, proper config integration, resource validators
**Author**: Robert and Geospatial Claude Legion
**Completed**: 28 NOV 2025

### Summary

Created `process_raster_v2` job using JobBaseMixin pattern with resource validators. Clean slate design - no deprecated parameters, proper config integration.

### Implementation Results

| Metric | Value |
|--------|-------|
| Lines of code | 280 (vs 743 for process_raster) |
| Code reduction | 73% |
| Boilerplate eliminated | 4 methods via JobBaseMixin |
| Pre-flight validation | blob_exists resource validator |

### Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `jobs/process_raster_v2.py` | CREATED | ~280 lines, JobBaseMixin implementation |
| `jobs/__init__.py` | EDITED | +2 lines (import + registration) |
| `services/raster_cog.py` | EDITED | Fixed JPEG INTERLEAVE for visualization tier |
| `WIKI_JOB_PROCESS_RASTER_V2.md` | CREATED | Full documentation |

### Bug Fix: JPEG Visualization Tier (28 NOV 2025)

**Problem**: JPEG encoding failed with "Can't process input with band interleaving"
**Root Cause**: Unconditional `INTERLEAVE = "BAND"` setting incompatible with YCbCr encoding
**Fix**: Conditional interleave based on compression type:
- JPEG/WebP: `INTERLEAVE = "PIXEL"` (required for YCbCr encoding)
- DEFLATE/LZW/LERC: `INTERLEAVE = "BAND"` (cloud-native selective band access)

### Test Results

```bash
# Visualization tier (JPEG) - WORKING
curl -X POST '.../api/jobs/submit/process_raster_v2' \
  -d '{"blob_name": "dctest.tif", "container_name": "rmhazuregeobronze", "output_tier": "visualization"}'
# Result: 11.08 MB JPEG COG, STAC item created, TiTiler URLs generated

# Analysis tier (DEFLATE) - WORKING
curl -X POST '.../api/jobs/submit/process_raster_v2' \
  -d '{"blob_name": "dctest.tif", "container_name": "rmhazuregeobronze"}'
# Result: COG with DEFLATE compression, STAC metadata in pgstac
```

### Output URLs Structure

Job result_data now includes:
- `stac_urls`: item_url, collection_url, items_url, catalog_url (using rmhogcstac)
- `titiler_urls`: viewer_url, preview_url, tile_url, etc. (using rmhtitiler)
- `share_url`: Quick viewer link

### Documentation

See: `WIKI_JOB_PROCESS_RASTER_V2.md` for full API documentation

---

## ✅ COMPLETED: Exception Context Loss in Nested Error Handlers (28 NOV 2025)

**Status**: ✅ **COMPLETED**
**Priority**: **HIGH** - Critical for debugging production failures
**Impact**: Preserves original exception context for root cause analysis
**Author**: Robert and Geospatial Claude Legion
**Completed**: 28 NOV 2025

### Solution Implemented

Created `log_nested_error()` helper function in `core/error_handler.py` that logs both primary and cleanup errors with structured context for Application Insights filtering.

### Fixed Locations in CoreMachine

| File | Lines | Pattern | Fix Applied |
|------|-------|---------|-------------|
| `core/machine.py` | ~617-636 | Status update failure cleanup | ✅ `log_nested_error()` |
| `core/machine.py` | ~652-670 | Status update exception cleanup | ✅ `log_nested_error()` |
| `core/machine.py` | ~885-904 | Stage advancement failure cleanup | ✅ `log_nested_error()` |
| `core/machine.py` | ~935-943 | Task completion SQL failure cleanup | ✅ `log_nested_error()` |

### Application Insights Filtering

In Application Insights, you can now search for:
- `customDimensions.nested_error = true` - Find all nested errors
- `customDimensions.primary_error_type` - Filter by root cause type
- `customDimensions.cleanup_error_type` - Filter by cleanup failure type

### Files Modified

- `core/error_handler.py` - Added `log_nested_error()` helper function (~80 lines)
- `core/machine.py` - Updated 4 nested error handlers to use `log_nested_error()`

---

## ✅ COMPLETED: JSON Deserialization Error Handling (28 NOV 2025)

**Status**: ✅ **COMPLETED**
**Priority**: **HIGH** - Data corruption prevention
**Impact**: Fail-fast on serialization errors, explicit logging
**Author**: Robert and Geospatial Claude Legion
**Completed**: 28 NOV 2025

### Solution Implemented

Research found **50+ Pydantic models already exist** covering all boundaries. No new modules needed - just added explicit error handling to existing code:

1. **Service Bus** - Added try/except with dead-letter routing for malformed messages
2. **PostgreSQL** - Created `_parse_jsonb_column()` helper that logs and raises `DatabaseError` instead of silent fallbacks

### Files Modified

| File | Change |
|------|--------|
| `infrastructure/service_bus.py` | Added try/except to `receive_messages()` and `peek_messages()` |
| `infrastructure/postgresql.py` | Added `_parse_jsonb_column()` helper, updated 4 methods to use it |

### Application Insights Queries

```kql
# Find JSON deserialization errors
traces | where customDimensions.error_type == "JSONDecodeError"

# Find corrupted database records
traces | where message contains "Corrupted JSON"
```

### Original Problem Statement

The codebase uses raw `json.loads()` and `json.dumps()` throughout (~200+ occurrences), often with silent fallbacks that hide data corruption. Pydantic models should handle all serialization with explicit validation.

### Current Anti-Patterns Found

**1. Silent Fallback (Data Corruption Risk)**
```python
# infrastructure/postgresql.py:885-887
'parameters': row['parameters'] if isinstance(row['parameters'], dict)
              else json.loads(row['parameters']) if row['parameters'] else {},
```
Problem: If JSON is malformed, this silently returns `{}` instead of failing.

**2. Inconsistent Serialization**
```python
# Some places use:
json.dumps(params, sort_keys=True)

# Others use:
json.dumps(params, sort_keys=True, default=str)

# Others use Pydantic:
model.model_dump_json()
```

**3. No Type Safety**
```python
# Raw dict passed around, no validation
result_data = json.loads(row['result_data'])
# Could be anything - no schema enforcement
```

### Solution: Pydantic-First JSON Handling

**Principle**: All JSON serialization/deserialization should go through Pydantic models.

**1. Create Serialization Helpers in `core/serialization.py`**

```python
from typing import TypeVar, Type
from pydantic import BaseModel, ValidationError
import json

from exceptions import ContractViolationError

T = TypeVar('T', bound=BaseModel)


def deserialize_json(
    json_str: str | None,
    model: Type[T],
    context: str = "unknown"
) -> T | None:
    """
    Deserialize JSON string to Pydantic model with explicit error handling.

    Args:
        json_str: JSON string to deserialize (None returns None)
        model: Pydantic model class to deserialize into
        context: Description for error messages

    Returns:
        Pydantic model instance or None

    Raises:
        ContractViolationError: If JSON is malformed or doesn't match schema
    """
    if json_str is None:
        return None

    try:
        data = json.loads(json_str)
        return model.model_validate(data)
    except json.JSONDecodeError as e:
        raise ContractViolationError(
            f"Malformed JSON in {context}: {e}"
        )
    except ValidationError as e:
        raise ContractViolationError(
            f"Schema validation failed in {context}: {e}"
        )


def serialize_json(
    model: BaseModel | dict,
    sort_keys: bool = True,
    context: str = "unknown"
) -> str:
    """
    Serialize Pydantic model or dict to JSON with explicit error handling.

    Args:
        model: Pydantic model or dict to serialize
        sort_keys: Whether to sort keys (for deterministic output)
        context: Description for error messages

    Returns:
        JSON string

    Raises:
        ContractViolationError: If serialization fails
    """
    try:
        if isinstance(model, BaseModel):
            return model.model_dump_json(indent=None)
        else:
            return json.dumps(model, sort_keys=sort_keys, default=str)
    except (TypeError, ValueError) as e:
        raise ContractViolationError(
            f"JSON serialization failed in {context}: {e}"
        )


def safe_json_loads(
    json_str: str | None,
    default: dict | None = None,
    context: str = "unknown",
    loud: bool = True
) -> dict | None:
    """
    Load JSON with explicit failure handling.

    Args:
        json_str: JSON string to parse
        default: Default value if json_str is None/empty
        context: Description for error messages
        loud: If True, raise on errors. If False, log warning and return default.

    Returns:
        Parsed dict or default

    Raises:
        ContractViolationError: If loud=True and JSON is malformed
    """
    if not json_str:
        return default

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        if loud:
            raise ContractViolationError(
                f"Malformed JSON in {context}: {e}"
            )
        else:
            from util_logger import LoggerFactory, ComponentType
            logger = LoggerFactory.create_logger(ComponentType.INFRASTRUCTURE, "serialization")
            logger.warning(f"⚠️ Malformed JSON in {context}, using default: {e}")
            return default
```

**2. Update Repository Layer**

Replace:
```python
# OLD - Silent fallback
'parameters': row['parameters'] if isinstance(row['parameters'], dict)
              else json.loads(row['parameters']) if row['parameters'] else {},
```

With:
```python
# NEW - Explicit handling
from core.serialization import safe_json_loads

'parameters': safe_json_loads(
    row['parameters'] if not isinstance(row['parameters'], dict) else None,
    default=row['parameters'] if isinstance(row['parameters'], dict) else {},
    context=f"job {row['job_id']} parameters",
    loud=False  # Log warning but don't crash on legacy data
),
```

### Implementation Phases

#### Phase 1: Create Serialization Module (IMMEDIATE)
1. [ ] Create `core/serialization.py` with helper functions
2. [ ] Add unit tests for serialization helpers
3. [ ] Document usage patterns

#### Phase 2: Update CoreMachine (HIGH)
4. [ ] Update `infrastructure/postgresql.py` job/task deserialization
5. [ ] Update `infrastructure/jobs_tasks.py` task serialization
6. [ ] Update `core/machine.py` result handling

#### Phase 3: Update Job Classes (MEDIUM)
7. [ ] Update `jobs/mixins.py` generate_job_id() serialization
8. [ ] Update individual job classes using raw json.dumps()

#### Phase 4: Audit Remaining Usage (LOW)
9. [ ] Audit all `json.loads()` calls for proper error handling
10. [ ] Audit all `json.dumps()` calls for consistency
11. [ ] Create migration guide for new code

### Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `core/serialization.py` | CREATE - New serialization helpers | P1 |
| `infrastructure/postgresql.py` | UPDATE - Use safe_json_loads | P2 |
| `infrastructure/jobs_tasks.py` | UPDATE - Use serialize_json | P2 |
| `core/machine.py` | UPDATE - Explicit result handling | P2 |
| `jobs/mixins.py` | UPDATE - Deterministic serialization | P3 |

---

## 🔴 MEDIUM-HIGH PRIORITY: Dead Code Audit (28 NOV 2025)

**Status**: 🟡 **IN PROGRESS** - `create_job_record` methods commented out
**Priority**: **MEDIUM-HIGH** - Technical debt cleanup before further development
**Impact**: Reduced cognitive load, smaller codebase, fewer maintenance surprises
**Author**: Robert and Geospatial Claude Legion

### Problem Statement

During error handling review, discovered duplicate method definitions in `core/state_manager.py` where **BOTH versions are dead code** - never called by any part of the system. This suggests more orphaned code likely exists.

### Known Dead Code (Confirmed)

| File | Lines | Code | Status |
|------|-------|------|--------|
| `core/state_manager.py` | 133-173 | `create_job_record(job_id, job_type, parameters, total_stages)` | Dead (overwritten by duplicate) |
| `core/state_manager.py` | 175-212 | `create_job_record(job_record: JobRecord)` | Dead (never called) |

**Note**: Job creation happens via job class interface (`jobs/*.py`), not StateManager.

### Audit Strategy

#### Phase 1: StateManager Method Audit
Check which StateManager methods are actually called by CoreMachine:

```bash
# Methods CoreMachine DOES call:
grep -n "self.state_manager\." core/machine.py | grep -oP '\.\w+\(' | sort -u
```

**Known used methods** (from grep):
- `update_job_status()`, `update_job_stage()`, `get_task_current_status()`
- `update_task_status_direct()`, `mark_task_failed()`, `mark_job_failed()`
- `complete_task_with_sql()`, `complete_job()`, `get_stage_results()`
- `increment_task_retry_count()`

**Potentially unused** (need verification):
- `create_job_record()` - CONFIRMED DEAD
- `get_job_record()` - check callers
- `get_completed_stages()` - check callers
- `get_stage_status()` - check callers

#### Phase 2: Backup File Cleanup
```bash
# Find backup/original files that should be archived
find . -name "*_backup*" -o -name "*_original*" -o -name "*_old*" | grep "\.py$"
```

#### Phase 3: Unused Import Detection
```bash
# Use pylint or similar to find unused imports
# Example: pylint --disable=all --enable=W0611 core/*.py
```

#### Phase 4: Epoch 3 Remnants
Check for Epoch 3 code that was superseded by Epoch 4:
- Old controller patterns
- Deprecated decorators
- Legacy queue handling

### Implementation Steps

1. [ ] Comment out `create_job_record` methods in `state_manager.py` (both versions)
2. [ ] Deploy and test - verify no runtime errors
3. [ ] Audit remaining StateManager methods for callers
4. [ ] Run backup file search and archive to `docs/archive/`
5. [ ] Document any other dead code found
6. [ ] Create PR with cleanup

### Files to Audit

| File | Reason |
|------|--------|
| `core/state_manager.py` | Known duplicate methods, potential unused methods |
| `core/core_controller.py` | May be Epoch 3 remnant |
| `jobs/hello_world_original_backup.py` | Backup file - archive candidate |
| `core/logic/*.py` | May contain unused calculations |
| `core/contracts/*.py` | Check if contracts are enforced anywhere |

---

## ✅ COMPLETED: Service Bus Specific Exception Handling (28 NOV 2025)

**Status**: ✅ **COMPLETED**
**Priority**: **MEDIUM** - Improved debugging by distinguishing error types
**Completed**: 28 NOV 2025
**Author**: Robert and Geospatial Claude Legion

### Summary

Replaced generic `except Exception` blocks with Azure SDK specific exception handling in `infrastructure/service_bus.py`. Now distinguishes between:
- **Permanent errors** (auth, config, quota, message size) - fail immediately, no retry
- **Transient errors** (timeout, server busy, connection) - retry with backoff

### Changes Made

| Method | Lines Changed | Exceptions Handled |
|--------|---------------|-------------------|
| `send_message()` | 360-477 | Auth, MessageSize, EntityNotFound, Quota, Timeout, ServerBusy, Connection |
| `batch_send_messages()` | 801-913 | Same categories with batch-specific behavior |
| `receive_messages()` | 601-673 | Auth, EntityNotFound, Timeout, ServerBusy, Connection |
| `peek_messages()` | 739-796 | Same as receive_messages |

### Exception Categories

```python
# PERMANENT (never retry):
ServiceBusAuthenticationError, ServiceBusAuthorizationError
MessageSizeExceededError
MessagingEntityNotFoundError
ServiceBusQuotaExceededError

# TRANSIENT (retry with backoff):
OperationTimeoutError
ServiceBusServerBusyError
ServiceBusConnectionError
ServiceBusCommunicationError
```

### Structured Logging

All exceptions now include `extra={}` with:
- `error_type`: Specific exception class name
- `retryable`: Boolean for retry decisions
- `error_category`: Category for Application Insights filtering (auth, config, quota, transient, connection, unexpected)

---

## 🟡 LOW PRIORITY: Inconsistent Logging Levels (28 NOV 2025)

**Status**: 🟡 **NOT STARTED**
**Priority**: **LOW** - Code quality improvement
**Impact**: Consistent log severity for better alerting
**Author**: Robert and Geospatial Claude Legion

### Problem Statement

Same severity events are logged at different levels across the codebase:
- Some failures logged as `logger.error()`
- Similar failures logged as `logger.warning()`

### Examples Found

| File | Line | Current | Should Be |
|------|------|---------|-----------|
| `core/machine.py` | ~360 | `logger.error()` for registry lookup | ERROR (correct) |
| `core/machine.py` | ~405-407 | `logger.warning()` for fetch failure | ERROR (should match) |

### Guidelines to Establish

| Level | When to Use |
|-------|-------------|
| ERROR | Operation failed, job/task will fail |
| WARNING | Recoverable issue, graceful degradation |
| INFO | Normal operations, milestones |
| DEBUG | Detailed troubleshooting |

### Implementation Steps

1. [ ] Audit `core/machine.py` for logging level consistency
2. [ ] Audit `core/state_manager.py` for logging level consistency
3. [ ] Document logging level guidelines in CLAUDE.md
4. [ ] Apply consistent levels across CoreMachine

---

## 🟡 LOW PRIORITY: Missing Error Source Field (28 NOV 2025)

**Status**: 🟡 **NOT STARTED**
**Priority**: **LOW** - Debugging improvement
**Impact**: Easier error triage in Application Insights
**Author**: Robert and Geospatial Claude Legion

### Problem Statement

Hard to distinguish where errors originate:
- Orchestration layer (CoreMachine)
- Execution layer (task handlers)
- Infrastructure layer (database, blob, queue)

### Solution

Add `error_source` field to structured logging:

```python
logger.error(
    "Operation failed",
    extra={
        'error_source': 'orchestration',  # or 'execution', 'infrastructure'
        'error_type': type(e).__name__,
        ...
    }
)
```

### Application Insights Query

```kql
traces
| where customDimensions.error_source == "infrastructure"
| summarize count() by customDimensions.error_type
```

### Implementation Steps

1. [ ] Define error_source enum/constants
2. [ ] Add to `CoreMachineErrorHandler.handle_operation()`
3. [ ] Add to `log_nested_error()`
4. [ ] Update infrastructure layer error logging

---

## 🟢 NICE-TO-HAVE: Retry Telemetry (28 NOV 2025)

**Status**: 🟢 **NOT STARTED**
**Priority**: **NICE-TO-HAVE** - Enhanced monitoring
**Impact**: Track retry patterns for optimization
**Author**: Robert and Geospatial Claude Legion

### Problem Statement

Retry attempts are not fully tracked in structured logging. Cannot answer:
- How many retries are typical?
- Which tasks retry most?
- What's the retry success rate?

### Location

`core/machine.py` lines ~938-949 - retry logic

### Solution

Add retry telemetry to structured logging:

```python
logger.info(
    "Task retry scheduled",
    extra={
        'retry_attempt': current_retry + 1,
        'max_retries': max_retries,
        'error_type': type(e).__name__,
        'task_type': task_type,
        'retryable': is_retryable
    }
)
```

### Implementation Steps

1. [ ] Add retry metrics to task retry path
2. [ ] Add retry outcome tracking (success after N retries)
3. [ ] Create Application Insights dashboard query

---

## ✅ IMPLEMENTED: Pre-Flight Resource Validation Architecture (27 NOV 2025)

**Status**: ✅ **COMPLETE** - Implemented in `infrastructure/validators.py`
**Priority**: **HIGH** - Prevents wasted job records and queue messages for invalid requests
**Impact**: Fail-fast validation at job submission instead of task execution

**Implementation Summary**:
- Created `infrastructure/validators.py` with registry pattern
- 4 validators: `blob_exists`, `container_exists`, `table_exists`, `table_not_exists`
- JobBaseMixin integration complete (calls `run_validators()` in `validate_job_parameters()`)
- Updated to use `BlobRepository.instance()` singleton pattern (28 NOV 2025)
- Used by `process_vector` job, ready for `process_raster_v2`
**Author**: Robert and Geospatial Claude Legion

### Problem Statement

**Current Flow (Broken)**:
```
Submit Job → Parameters Validated (✅) → Job Created (✅) → Job Queued (✅)
→ Stage 1 Task Starts → read_blob() → ❌ ResourceNotFoundError (TOO LATE!)
```

When a user submits a job with a non-existent blob file or container:
- User gets HTTP 200 success response with `job_id`
- Job shows as `processing` or `failed` later (delayed error feedback)
- Wasted database records (app.jobs) and queue messages (Service Bus)
- Poor user experience - error hidden in Application Insights logs

**Desired Flow (Fixed)**:
```
Submit Job → Parameters Validated (✅) → Resources Validated (✅ or ❌ FAIL FAST)
→ Job Created → Job Queued → Processing begins
```

### Architecture: Declarative Resource Validators

Extend the existing `parameters_schema` pattern with a new `resource_validators` declaration.

**Design Principles**:
1. **DRY** - Validation logic written once in `infrastructure/validators.py`
2. **Declarative** - Jobs declare WHAT to validate, not HOW
3. **Consistent** - Same pattern as `parameters_schema` (already understood)
4. **Fail-Fast** - Errors at HTTP submission, not task execution
5. **Testable** - Validators are pure functions, easy to unit test
6. **Extensible** - Add new validator types without touching job classes

### Implementation Plan

#### File 1: `infrastructure/validators.py` (NEW FILE)

**Purpose**: Registry of resource validators + implementations

```python
# ============================================================================
# CLAUDE CONTEXT - RESOURCE VALIDATORS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Pre-flight resource validation
# PURPOSE: Centralized validators for blob/container/table existence checks
# LAST_REVIEWED: 27 NOV 2025
# EXPORTS: RESOURCE_VALIDATORS registry, validate_blob_exists, validate_container_exists, validate_table_exists
# INTERFACES: ValidatorResult TypedDict
# PYDANTIC_MODELS: None (uses TypedDict for lightweight validation results)
# DEPENDENCIES: infrastructure.blob.BlobRepository, infrastructure.postgresql.PostgreSQLRepository
# SOURCE: Called by JobBaseMixin.validate_job_parameters() during job submission
# SCOPE: ALL job types that declare resource_validators
# VALIDATION: Blob existence, container existence, PostGIS table existence
# PATTERNS: Registry pattern, Strategy pattern (validators are interchangeable)
# ENTRY_POINTS: JobBaseMixin calls RESOURCE_VALIDATORS[type](params, config)
# INDEX:
#   - ValidatorResult TypedDict: line 45
#   - RESOURCE_VALIDATORS registry: line 55
#   - validate_blob_exists: line 70
#   - validate_container_exists: line 120
#   - validate_table_exists: line 160
#   - validate_table_not_exists: line 200
#   - _get_zone_from_container: line 240 (helper)
# ============================================================================

"""
Pre-Flight Resource Validators

This module provides a registry of validation functions for checking external
resource existence BEFORE job creation. This prevents wasted database records
and queue messages for jobs that would fail immediately.

Usage in Job Classes:
    class ProcessVectorJob(JobBaseMixin, JobBase):
        resource_validators = [
            {
                'type': 'blob_exists',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'error': 'Source file does not exist in Bronze storage'
            }
        ]

The JobBaseMixin.validate_job_parameters() method automatically runs these
validators after schema validation passes.

Validator Interface:
    def validator_fn(params: dict, config: dict) -> ValidatorResult:
        '''
        Args:
            params: Validated job parameters (after schema validation)
            config: Validator config from resource_validators declaration

        Returns:
            ValidatorResult with 'valid' bool and 'message' str
        '''
"""

from typing import Dict, Any, Callable, Optional, TypedDict, List
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.INFRASTRUCTURE, "validators")


class ValidatorResult(TypedDict):
    """Result from a resource validator."""
    valid: bool
    message: Optional[str]


# Type alias for validator functions
ValidatorFn = Callable[[Dict[str, Any], Dict[str, Any]], ValidatorResult]

# Registry of validator functions
RESOURCE_VALIDATORS: Dict[str, ValidatorFn] = {}


def register_validator(name: str):
    """Decorator to register a validator function."""
    def decorator(func: ValidatorFn) -> ValidatorFn:
        RESOURCE_VALIDATORS[name] = func
        logger.debug(f"Registered resource validator: {name}")
        return func
    return decorator


# ============================================================================
# VALIDATOR IMPLEMENTATIONS
# ============================================================================

@register_validator("blob_exists")
def validate_blob_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a blob exists in Azure Blob Storage.

    Config options:
        container_param: str - Name of parameter containing container name
        blob_param: str - Name of parameter containing blob path
        zone: str - Optional trust zone ('bronze', 'silver', 'silverext').
                    If not specified, inferred from container name.
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'blob_exists',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'zone': 'bronze',  # Optional
                'error': 'Source file not found'  # Optional
            }
        ]
    """
    from infrastructure.blob import BlobRepository

    # Extract parameter names from config
    container_param = config.get('container_param', 'container_name')
    blob_param = config.get('blob_param', 'blob_name')

    # Get actual values from job parameters
    container = params.get(container_param)
    blob_path = params.get(blob_param)

    if not container:
        return ValidatorResult(
            valid=False,
            message=f"Container parameter '{container_param}' is missing or empty"
        )

    if not blob_path:
        return ValidatorResult(
            valid=False,
            message=f"Blob parameter '{blob_param}' is missing or empty"
        )

    # Determine trust zone
    zone = config.get('zone') or _get_zone_from_container(container)

    try:
        blob_repo = BlobRepository.for_zone(zone)
        validation = blob_repo.validate_container_and_blob(container, blob_path)

        if validation['valid']:
            logger.debug(f"✅ Pre-flight: blob exists: {container}/{blob_path}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or validation['message']
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate blob existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("container_exists")
def validate_container_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a container exists in Azure Blob Storage.

    Config options:
        container_param: str - Name of parameter containing container name
        zone: str - Optional trust zone ('bronze', 'silver', 'silverext')
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'container_exists',
                'container_param': 'source_container',
                'error': 'Source container does not exist'
            }
        ]
    """
    from infrastructure.blob import BlobRepository

    container_param = config.get('container_param', 'container_name')
    container = params.get(container_param)

    if not container:
        return ValidatorResult(
            valid=False,
            message=f"Container parameter '{container_param}' is missing or empty"
        )

    zone = config.get('zone') or _get_zone_from_container(container)

    try:
        blob_repo = BlobRepository.for_zone(zone)

        if blob_repo.container_exists(container):
            logger.debug(f"✅ Pre-flight: container exists: {container}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"Container '{container}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate container existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("table_exists")
def validate_table_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a PostGIS table exists.

    Config options:
        table_param: str - Name of parameter containing table name
        schema_param: str - Name of parameter containing schema name (default: 'schema')
        default_schema: str - Default schema if not in params (default: 'geo')
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'table_exists',
                'table_param': 'source_table',
                'schema_param': 'source_schema',
                'error': 'Source table does not exist'
            }
        ]
    """
    from infrastructure.postgresql import PostgreSQLRepository
    from psycopg import sql

    table_param = config.get('table_param', 'table_name')
    schema_param = config.get('schema_param', 'schema')
    default_schema = config.get('default_schema', 'geo')

    table_name = params.get(table_param)
    schema = params.get(schema_param, default_schema)

    if not table_name:
        return ValidatorResult(
            valid=False,
            message=f"Table parameter '{table_param}' is missing or empty"
        )

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    )
                """, (schema, table_name))
                exists = cur.fetchone()[0]

        if exists:
            logger.debug(f"✅ Pre-flight: table exists: {schema}.{table_name}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"Table '{schema}.{table_name}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate table existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("table_not_exists")
def validate_table_not_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a PostGIS table does NOT exist (for "don't overwrite" checks).

    Config options:
        table_param: str - Name of parameter containing table name
        schema_param: str - Name of parameter containing schema name
        default_schema: str - Default schema if not in params (default: 'geo')
        error: str - Optional custom error message
        allow_overwrite_param: str - Optional param that if True bypasses this check

    Example:
        resource_validators = [
            {
                'type': 'table_not_exists',
                'table_param': 'table_name',
                'error': 'Table already exists. Use overwrite=true to replace.',
                'allow_overwrite_param': 'overwrite'
            }
        ]
    """
    # Check if overwrite is allowed and enabled
    allow_overwrite_param = config.get('allow_overwrite_param')
    if allow_overwrite_param and params.get(allow_overwrite_param, False):
        logger.debug(f"✅ Pre-flight: overwrite enabled, skipping table_not_exists check")
        return ValidatorResult(valid=True, message=None)

    # Inverse of table_exists
    result = validate_table_exists(params, config)

    if result['valid']:
        # Table exists - this is a FAILURE for table_not_exists
        table_param = config.get('table_param', 'table_name')
        schema_param = config.get('schema_param', 'schema')
        default_schema = config.get('default_schema', 'geo')
        table_name = params.get(table_param)
        schema = params.get(schema_param, default_schema)

        error_msg = config.get('error') or f"Table '{schema}.{table_name}' already exists"
        return ValidatorResult(valid=False, message=error_msg)
    else:
        # Table doesn't exist - this is SUCCESS for table_not_exists
        # (unless the check itself failed due to connection error)
        if "Failed to validate" in (result.get('message') or ''):
            return result  # Propagate connection errors
        return ValidatorResult(valid=True, message=None)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_zone_from_container(container_name: str) -> str:
    """
    Infer trust zone from container name.

    Container naming convention:
        - bronze-* or *bronze* → 'bronze'
        - silver-* or *silver* → 'silver'
        - silverext-* or *external* → 'silverext'
        - Default → 'silver'

    Args:
        container_name: Azure Blob Storage container name

    Returns:
        Trust zone: 'bronze', 'silver', or 'silverext'
    """
    container_lower = container_name.lower()

    if 'bronze' in container_lower:
        return 'bronze'
    elif 'external' in container_lower or 'silverext' in container_lower:
        return 'silverext'
    elif 'silver' in container_lower:
        return 'silver'
    else:
        # Default to silver (most common for processed data)
        return 'silver'


def run_validators(
    validators: List[Dict[str, Any]],
    params: Dict[str, Any]
) -> ValidatorResult:
    """
    Run a list of validators and return first failure or success.

    Args:
        validators: List of validator configs from job's resource_validators
        params: Validated job parameters

    Returns:
        ValidatorResult - first failure, or success if all pass

    Example:
        validators = [
            {'type': 'container_exists', 'container_param': 'source'},
            {'type': 'blob_exists', 'container_param': 'source', 'blob_param': 'file'}
        ]
        result = run_validators(validators, params)
        if not result['valid']:
            raise ValueError(result['message'])
    """
    for validator_config in validators:
        validator_type = validator_config.get('type')

        if not validator_type:
            return ValidatorResult(
                valid=False,
                message="Validator config missing 'type' field"
            )

        validator_fn = RESOURCE_VALIDATORS.get(validator_type)

        if not validator_fn:
            return ValidatorResult(
                valid=False,
                message=f"Unknown validator type: '{validator_type}'. "
                        f"Available: {list(RESOURCE_VALIDATORS.keys())}"
            )

        result = validator_fn(params, validator_config)

        if not result['valid']:
            return result  # Fail fast on first error

    return ValidatorResult(valid=True, message=None)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'RESOURCE_VALIDATORS',
    'ValidatorResult',
    'ValidatorFn',
    'register_validator',
    'run_validators',
    'validate_blob_exists',
    'validate_container_exists',
    'validate_table_exists',
    'validate_table_not_exists',
]
```

---

#### File 2: `jobs/mixins.py` (MODIFY)

**Purpose**: Add resource validation to `validate_job_parameters()`

**Location**: After schema validation (~line 438), before return statement

**Changes Required**:

```python
# ADD after line 438 (after schema validation, before return)

# ========================================================================
# STEP 2: Resource Validation (Optional - if job declares resource_validators)
# ========================================================================

if hasattr(cls, 'resource_validators') and cls.resource_validators:
    from infrastructure.validators import run_validators

    logger.debug(f"🔍 Running {len(cls.resource_validators)} resource validators...")

    result = run_validators(cls.resource_validators, validated)

    if not result['valid']:
        error_msg = f"Pre-flight validation failed: {result['message']}"
        logger.warning(f"❌ {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"✅ All resource validators passed")
```

**Full Method After Modification** (for context):

```python
@classmethod
def validate_job_parameters(cls, params: dict) -> dict:
    """
    Default parameter validation using parameters_schema + resource_validators.

    Validation is performed in two phases:
    1. Schema validation (type checking, required fields, ranges, enums)
    2. Resource validation (blob/container/table existence) - optional

    Override for complex validation logic (cross-field validation, etc).
    """
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        f"{cls.__name__}.validate_job_parameters"
    )

    # ========================================================================
    # STEP 1: Schema Validation (existing code - unchanged)
    # ========================================================================

    # Safety check: Ensure parameters_schema is defined
    if not hasattr(cls, 'parameters_schema') or cls.parameters_schema is None:
        raise AttributeError(
            f"{cls.__name__} must define 'parameters_schema' class attribute."
        )

    validated = {}

    for param_name, schema in cls.parameters_schema.items():
        # ... existing schema validation logic (lines 407-436) ...
        value = params.get(param_name, schema.get('default'))

        if value is None and schema.get('required', False):
            raise ValueError(f"Parameter '{param_name}' is required")

        if value is None:
            continue

        # Type validation
        param_type = schema.get('type', 'str')
        if param_type == 'int':
            value = cls._validate_int(param_name, value, schema)
        elif param_type == 'float':
            value = cls._validate_float(param_name, value, schema)
        elif param_type == 'str':
            value = cls._validate_str(param_name, value, schema)
        elif param_type == 'bool':
            value = cls._validate_bool(param_name, value)
        elif param_type == 'list':
            value = cls._validate_list(param_name, value, schema)
        elif param_type == 'dict':
            value = cls._validate_dict(param_name, value, schema)
        else:
            raise ValueError(f"Unknown type '{param_type}' for parameter '{param_name}'")

        validated[param_name] = value

    logger.debug(f"✅ Schema validation passed: {list(validated.keys())}")

    # ========================================================================
    # STEP 2: Resource Validation (NEW - 27 NOV 2025)
    # ========================================================================

    if hasattr(cls, 'resource_validators') and cls.resource_validators:
        from infrastructure.validators import run_validators

        logger.debug(f"🔍 Running {len(cls.resource_validators)} resource validators...")

        result = run_validators(cls.resource_validators, validated)

        if not result['valid']:
            error_msg = f"Pre-flight validation failed: {result['message']}"
            logger.warning(f"❌ {error_msg}")
            raise ValueError(error_msg)

        logger.debug(f"✅ All resource validators passed")

    return validated
```

---

#### File 3: `jobs/process_vector.py` (MODIFY - Pilot Implementation)

**Purpose**: Add `resource_validators` declaration to pilot the pattern

**Location**: After `parameters_schema` (~line 121)

**Changes Required**:

```python
# ADD after line 121 (after parameters_schema closing brace)

# Pre-flight resource validation (27 NOV 2025)
# Validates blob exists BEFORE job creation - fail fast!
resource_validators = [
    {
        'type': 'blob_exists',
        'container_param': 'container_name',
        'blob_param': 'blob_name',
        'zone': 'bronze',  # Source files are in Bronze tier
        'error': 'Source file does not exist in Bronze storage. Check blob_name and container_name.'
    }
]
```

**Full Class Declaration After Modification**:

```python
class ProcessVectorJob(JobBaseMixin, JobBase):
    """
    Idempotent vector ETL workflow.
    """

    job_type: str = "process_vector"
    description: str = "Idempotent vector ETL: Bronze -> PostGIS + STAC"

    # Declarative validation schema (JobBaseMixin handles validation)
    parameters_schema = {
        'blob_name': {
            'type': 'str',
            'required': True,
            'description': 'Source file path in container'
        },
        'file_extension': {
            'type': 'str',
            'required': True,
            'allowed': ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip'],
            'description': 'Source file format'
        },
        'table_name': {
            'type': 'str',
            'required': True,
            'description': 'Target PostGIS table name'
        },
        'container_name': {
            'type': 'str',
            'default': 'rmhazuregeobronze',
            'description': 'Source blob container'
        },
        # ... rest of parameters_schema ...
    }

    # Pre-flight resource validation (27 NOV 2025)
    resource_validators = [
        {
            'type': 'blob_exists',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'zone': 'bronze',
            'error': 'Source file does not exist in Bronze storage. Check blob_name and container_name.'
        }
    ]

    stages: List[Dict[str, Any]] = [
        # ... stages unchanged ...
    ]
```

---

### Task Checklist

**Phase 1: Core Infrastructure**
- [ ] **Step 1**: Create `infrastructure/validators.py` with registry and 4 validators
- [ ] **Step 2**: Add `run_validators()` helper function
- [ ] **Step 3**: Add `_get_zone_from_container()` helper
- [ ] **Step 4**: Unit test validators with mock BlobRepository

**Phase 2: Integration**
- [ ] **Step 5**: Modify `jobs/mixins.py` to call resource validators
- [ ] **Step 6**: Ensure backward compatibility (jobs without resource_validators still work)
- [ ] **Step 7**: Integration test with HelloWorldJob (no validators) - should pass

**Phase 3: Pilot Rollout**
- [ ] **Step 8**: Add `resource_validators` to `jobs/process_vector.py`
- [ ] **Step 9**: Test with valid blob → job should be created
- [ ] **Step 10**: Test with invalid blob → should get HTTP 400 with clear error
- [ ] **Step 11**: Test with invalid container → should get HTTP 400 with clear error

**Phase 4: Rollout to Other Jobs**
- [ ] **Step 12**: Add validators to `jobs/ingest_vector.py`
- [ ] **Step 13**: Add validators to `jobs/process_raster.py`
- [ ] **Step 14**: Add validators to `jobs/process_large_raster.py`
- [ ] **Step 15**: Add validators to `jobs/container_list.py` (container_exists only)

**Phase 5: Documentation**
- [ ] **Step 16**: Update `JOB_CREATION_QUICKSTART.md` with resource_validators section
- [ ] **Step 17**: Add examples to `jobs/mixins.py` docstring
- [ ] **Step 18**: Update `ARCHITECTURE_REFERENCE.md` with validation flow diagram
- [ ] **Commit**: "Add pre-flight resource validation to job submission flow"

---

### Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `infrastructure/validators.py` | **CREATE** | Validator registry + implementations |
| `infrastructure/__init__.py` | **MODIFY** | Export validators module |
| `jobs/mixins.py` | **MODIFY** | Add resource validation to validate_job_parameters() |
| `jobs/process_vector.py` | **MODIFY** | Pilot: add resource_validators declaration |
| `jobs/ingest_vector.py` | **MODIFY** | Rollout: add resource_validators |
| `jobs/process_raster.py` | **MODIFY** | Rollout: add resource_validators |
| `jobs/process_large_raster.py` | **MODIFY** | Rollout: add resource_validators |
| `jobs/container_list.py` | **MODIFY** | Rollout: add container_exists validator |
| `JOB_CREATION_QUICKSTART.md` | **MODIFY** | Document resource_validators pattern |

---

### Available Validator Types

| Validator | Purpose | Config Options | Example Use Case |
|-----------|---------|----------------|------------------|
| `blob_exists` | Verify blob file exists | container_param, blob_param, zone, error | Source file for ETL jobs |
| `container_exists` | Verify container exists | container_param, zone, error | Container listing jobs |
| `table_exists` | Verify PostGIS table exists | table_param, schema_param, default_schema, error | Append-to-table jobs |
| `table_not_exists` | Verify table does NOT exist | table_param, schema_param, allow_overwrite_param, error | Create-new-table jobs |

---

### Example Usage in Jobs

**process_vector** (source blob must exist):
```python
resource_validators = [
    {
        'type': 'blob_exists',
        'container_param': 'container_name',
        'blob_param': 'blob_name',
        'zone': 'bronze',
        'error': 'Source file not found in Bronze storage'
    }
]
```

**container_list** (container must exist):
```python
resource_validators = [
    {
        'type': 'container_exists',
        'container_param': 'container_name',
        'error': 'Container does not exist'
    }
]
```

**export_to_geoparquet** (source table must exist):
```python
resource_validators = [
    {
        'type': 'table_exists',
        'table_param': 'source_table',
        'schema_param': 'source_schema',
        'error': 'Source table does not exist in PostGIS'
    }
]
```

**process_vector with overwrite check**:
```python
resource_validators = [
    {
        'type': 'blob_exists',
        'container_param': 'container_name',
        'blob_param': 'blob_name'
    },
    {
        'type': 'table_not_exists',
        'table_param': 'table_name',
        'allow_overwrite_param': 'overwrite',
        'error': 'Table already exists. Set overwrite=true to replace.'
    }
]
```

---

### Error Response Example

**Before (current - error hidden in task execution)**:
```json
HTTP 200 OK
{
    "job_id": "abc123...",
    "status": "created",
    "message": "Job created and queued for processing"
}
// User has to check job status later to find out it failed
```

**After (with pre-flight validation)**:
```json
HTTP 400 Bad Request
{
    "error": "Pre-flight validation failed: Source file 'data/missing.csv' does not exist in container 'rmhazuregeobronze'",
    "job_type": "process_vector",
    "validation_type": "blob_exists",
    "parameters": {
        "blob_name": "data/missing.csv",
        "container_name": "rmhazuregeobronze"
    }
}
// User gets immediate, actionable error
```

---

### Performance Notes

- **Latency**: ~100-300ms added to job submission (blob existence check)
- **Acceptable**: ETL jobs are async; users don't expect instant responses
- **Benefit**: Prevents wasted DB records + queue messages + debugging time
- **Caching**: Not implemented (blobs can change between check and execution)

---

### Future Enhancements

1. **Async Validation** (if needed): Run validators in Stage 0 task instead of HTTP request
2. **Batch Validation**: Validate multiple blobs in single API call (for collection jobs)
3. **Custom Validators**: Allow jobs to define inline validator functions
4. **Validation Caching**: Cache positive results for short TTL (risky - blob could be deleted)

---

## 🚨 HIGH PRIORITY: Idempotency Fixes for ETL Workflows (25 NOV 2025)

**Status**: 🔴 **PLANNING COMPLETE** - Ready for implementation
**Priority**: **HIGH** - Critical for production reliability
**Impact**: Prevents duplicate data on retry, enables safe job recovery

### Background

Analysis revealed idempotency gaps in three workflows:
- **ingest_vector**: Stage 2 INSERT creates duplicates, Stage 3 STAC items can duplicate
- **process_raster_collection**: Stage 4 pgstac search registration (already has workaround)
- **All workflows**: No failed job recovery mechanism

### 1. FIX: ingest_vector Stage 2 - PostGIS INSERT Idempotency

**Problem**: `upload_pickled_chunk` uses plain INSERT, creating duplicate rows if task retries.

**Location**: `services/vector/postgis_handler.py` lines 707-758

**Current Code** (non-idempotent):
```python
def _insert_features(self, cur, chunk, table_name, schema):
    insert_stmt = sql.SQL("""
        INSERT INTO {schema}.{table} (geom, {cols})
        VALUES (ST_GeomFromText(%s, 4326), {placeholders})
    """)
    for idx, row in chunk.iterrows():
        cur.execute(insert_stmt, values)
```

**Solution Options**:

#### Option A: TRUNCATE + INSERT (Recommended for ingest_vector)
**Rationale**: Stage 2 tasks process distinct chunks; each chunk owns specific rows.

**Implementation**:
```python
def _insert_features_idempotent(
    self,
    cur: psycopg.Cursor,
    chunk: gpd.GeoDataFrame,
    table_name: str,
    schema: str,
    chunk_index: int,
    job_id: str
):
    """
    Idempotent insert: Delete existing rows for this chunk, then INSERT.

    Uses etl_batch_id column (added in GeoTableBuilder) to identify chunk rows.
    Format: {job_id[:8]}-chunk-{chunk_index}
    """
    batch_id = f"{job_id[:8]}-chunk-{chunk_index}"

    # Step 1: Delete any existing rows from this chunk (idempotent cleanup)
    delete_stmt = sql.SQL("""
        DELETE FROM {schema}.{table}
        WHERE etl_batch_id = %s
    """).format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name)
    )
    cur.execute(delete_stmt, (batch_id,))
    deleted_count = cur.rowcount
    if deleted_count > 0:
        logger.info(f"♻️ Idempotency: Deleted {deleted_count} existing rows for batch {batch_id}")

    # Step 2: INSERT new rows with batch_id for tracking
    for idx, row in chunk.iterrows():
        values = [geom_wkt, batch_id] + [row[col] for col in attr_cols]
        cur.execute(insert_stmt, values)
```

**Required Schema Change** (already in GeoTableBuilder):
```sql
-- etl_batch_id column for chunk tracking
ALTER TABLE geo.{table} ADD COLUMN IF NOT EXISTS etl_batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_{table}_etl_batch_id ON geo.{table}(etl_batch_id);
```

#### Option B: UPSERT with Unique Constraint
**For tables with natural keys** (e.g., country codes, admin boundaries):
```python
# Add unique constraint during table creation
ALTER TABLE geo.{table} ADD CONSTRAINT uq_{table}_natural_key UNIQUE (iso3, admin_level);

# Use UPSERT
INSERT INTO geo.{table} (geom, iso3, admin_level, ...)
VALUES (...)
ON CONFLICT (iso3, admin_level) DO UPDATE SET
    geom = EXCLUDED.geom,
    updated_at = NOW();
```

**Task Checklist - ingest_vector Stage 2**:
- [ ] **Step 1**: Add `etl_batch_id` column to `_create_table_if_not_exists()` in `postgis_handler.py`
- [ ] **Step 2**: Modify `_insert_features()` to accept `chunk_index` and `job_id` parameters
- [ ] **Step 3**: Add DELETE before INSERT pattern (DELETE WHERE etl_batch_id = ...)
- [ ] **Step 4**: Update `insert_features_only()` to pass chunk metadata
- [ ] **Step 5**: Update `upload_pickled_chunk()` in `services/vector/tasks.py` to pass chunk_index and job_id
- [ ] **Step 6**: Test with duplicate task execution
- [ ] **Commit**: "Fix: ingest_vector Stage 2 idempotency via DELETE+INSERT pattern"

**Files to Modify**:
| File | Changes |
|------|---------|
| `services/vector/postgis_handler.py` | Add etl_batch_id to schema, DELETE+INSERT pattern |
| `services/vector/tasks.py` | Pass job_id and chunk_index to handler |
| `jobs/ingest_vector.py` | Ensure job_id in Stage 2 task parameters |

---

### 2. FIX: ingest_vector Stage 3 - STAC Item Idempotency

**Problem**: `create_vector_stac` may create duplicate STAC items if retried.

**Location**: `services/stac_vector_catalog.py` lines 111-128

**Current Code** (already has partial fix):
```python
# Check if item already exists (idempotency)
if stac_infra.item_exists(item.id, collection_id):
    logger.info(f"⏭️ STEP 2: Item {item.id} already exists...")
    insert_result = {'success': True, 'skipped': True}
else:
    insert_result = stac_infra.insert_item(item, collection_id)
```

**Status**: ✅ **ALREADY IMPLEMENTED** - Code review confirms idempotency check exists.

**Verification**:
- [ ] Confirm `item_exists()` uses correct collection_id
- [ ] Confirm item_id generation is deterministic (table name based)
- [ ] Test by running Stage 3 twice with same parameters

---

### 3. FIX: process_raster_collection Stage 4 - pgstac Search Registration

**Problem**: Search registration may create duplicates on retry.

**Location**: `services/pgstac_search_registration.py` lines 214-239

**Current Code** (already has workaround):
```python
# Step 1: Check if search already exists using Python-computed hash
cur.execute("SELECT hash FROM pgstac.searches WHERE hash = %s", (search_hash,))
existing = cur.fetchone()

if existing:
    # UPDATE existing (idempotent)
    cur.execute("UPDATE pgstac.searches SET lastused = NOW() WHERE hash = %s", (search_hash,))
else:
    # INSERT new
    cur.execute("INSERT INTO pgstac.searches ...")
```

**Status**: ✅ **ALREADY IMPLEMENTED** - SELECT-then-INSERT/UPDATE pattern is idempotent.

**Verification**:
- [ ] Confirm search_hash computation is deterministic
- [ ] Test by calling `register_search()` twice with same parameters

---

### 4. NEW: Failed Job Recovery & Cleanup Workflow

**Problem**: Failed jobs cannot be retried; intermediate artifacts persist.

**Current Behavior**:
```
Submit job → job_id = ABC, status = QUEUED
Processing fails → status = FAILED
Resubmit identical params → Returns {"status": "failed", "idempotent": true}
                          → NO retry, NO cleanup
```

**Solution**: Two-part system:
1. **Retry endpoint**: Force retry of failed jobs
2. **Cleanup handler**: Remove intermediate artifacts from failed jobs

#### 4.1 Retry Failed Job Endpoint

**New Endpoint**: `POST /api/jobs/retry/{job_id}?confirm=yes`

**File**: `triggers/job_retry.py` (NEW FILE)

```python
"""
Job Retry Trigger

Allows retrying failed jobs by:
1. Cleaning up intermediate artifacts
2. Resetting job status to QUEUED
3. Re-queueing to Service Bus

Endpoint: POST /api/jobs/retry/{job_id}?confirm=yes
"""

class JobRetryTrigger:
    """Handle retry requests for failed jobs."""

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Retry a failed job.

        1. Validate job exists and is in FAILED status
        2. Call cleanup handler for job type
        3. Reset job status to QUEUED, clear error fields
        4. Reset all tasks to PENDING
        5. Queue job to Service Bus
        """
        job_id = req.route_params.get('job_id')
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return error_response("Retry requires ?confirm=yes")

        # Get job from database
        job = self.job_repo.get_job(job_id)
        if not job:
            return error_response(f"Job {job_id} not found", 404)

        if job.status.value != 'failed':
            return error_response(f"Job {job_id} is {job.status.value}, not failed", 400)

        # Execute cleanup for this job type
        cleanup_result = self._cleanup_job_artifacts(job)

        # Reset job status
        self.job_repo.update_job_status(
            job_id=job_id,
            status='queued',
            stage=1,
            metadata={'retry_count': (job.metadata.get('retry_count', 0) + 1)}
        )

        # Reset all tasks to pending
        self.job_repo.reset_tasks_for_job(job_id)

        # Queue to Service Bus
        from core.machine import CoreMachine
        core_machine = CoreMachine.instance()
        core_machine.queue_job(job_id, job.job_type, job.parameters)

        return success_response({
            "job_id": job_id,
            "status": "queued",
            "retry_count": job.metadata.get('retry_count', 0) + 1,
            "cleanup_result": cleanup_result,
            "message": f"Job {job_id} has been reset and re-queued"
        })
```

#### 4.2 Cleanup Handlers by Job Type

**File**: `services/job_cleanup.py` (NEW FILE)

```python
"""
Job Cleanup Service

Handles cleanup of intermediate artifacts when jobs fail or are retried.
Each job type registers its own cleanup handler.

Cleanup Operations by Job Type:
- ingest_vector: Delete pickle files, optionally drop PostGIS table
- process_raster: Delete intermediate COG files (if partial)
- process_raster_collection: Delete partial MosaicJSON, partial COGs
"""

from typing import Dict, Any, Callable
from config import get_config
from infrastructure.blob import BlobRepository

# Registry of cleanup handlers
CLEANUP_HANDLERS: Dict[str, Callable[[str, dict], dict]] = {}


def register_cleanup(job_type: str):
    """Decorator to register cleanup handler for job type."""
    def decorator(func):
        CLEANUP_HANDLERS[job_type] = func
        return func
    return decorator


@register_cleanup("ingest_vector")
def cleanup_ingest_vector(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed ingest_vector jobs.

    Artifacts to clean:
    1. Pickle files in blob storage ({container}/{prefix}/{job_id}/*.pkl)
    2. Optionally: PostGIS table (if partially created)
    3. Optionally: STAC item (if Stage 3 partially ran)

    Args:
        job_id: Job ID
        job_params: Original job parameters

    Returns:
        {
            "pickles_deleted": int,
            "table_action": "dropped" | "preserved" | "not_found",
            "stac_item_action": "deleted" | "preserved" | "not_found"
        }
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    # 1. Delete pickle files
    pickle_prefix = f"{config.vector_pickle_prefix}/{job_id}/"
    try:
        deleted = blob_repo.delete_blobs_by_prefix(
            container=config.vector_pickle_container,
            prefix=pickle_prefix
        )
        result["pickles_deleted"] = deleted
        logger.info(f"🗑️ Deleted {deleted} pickle files for job {job_id}")
    except Exception as e:
        result["pickles_deleted"] = 0
        result["pickle_error"] = str(e)

    # 2. Optionally drop PostGIS table
    # Only drop if explicitly requested (default: preserve data for debugging)
    table_name = job_params.get("table_name")
    schema = job_params.get("schema", "geo")
    drop_table = job_params.get("cleanup_drop_table", False)

    if drop_table and table_name:
        try:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(schema),
                            sql.Identifier(table_name)
                        )
                    )
                    conn.commit()
            result["table_action"] = "dropped"
            logger.info(f"🗑️ Dropped table {schema}.{table_name}")
        except Exception as e:
            result["table_action"] = "error"
            result["table_error"] = str(e)
    else:
        result["table_action"] = "preserved"

    # 3. Delete STAC item if exists
    try:
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        stac = PgStacBootstrap()
        item_id = f"{schema}-{table_name}"  # Standard item_id format
        collection_id = job_params.get("collection_id", "system-vectors")

        if stac.item_exists(item_id, collection_id):
            stac.delete_item(item_id, collection_id)
            result["stac_item_action"] = "deleted"
        else:
            result["stac_item_action"] = "not_found"
    except Exception as e:
        result["stac_item_action"] = "error"
        result["stac_error"] = str(e)

    return result


@register_cleanup("process_raster")
def cleanup_process_raster(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed process_raster jobs.

    Artifacts to clean:
    1. Intermediate COG in silver container (if Stage 2 failed mid-upload)
    2. STAC item (if Stage 3 partially ran)
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    # 1. Delete COG blob (if exists)
    blob_name = job_params.get("blob_name", "")
    output_tier = job_params.get("output_tier", "analysis")
    # Derive output blob name (same logic as raster_cog.py)
    base_name = blob_name.rsplit('.', 1)[0]
    cog_blob_name = f"{base_name}_cog_{output_tier}.tif"

    try:
        silver_container = config.storage.silver_cog_container
        if blob_repo.blob_exists(silver_container, cog_blob_name):
            blob_repo.delete_blob(silver_container, cog_blob_name)
            result["cog_action"] = "deleted"
        else:
            result["cog_action"] = "not_found"
    except Exception as e:
        result["cog_action"] = "error"
        result["cog_error"] = str(e)

    # 2. Delete STAC item if exists
    try:
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        stac = PgStacBootstrap()
        collection_id = job_params.get("collection_id")
        item_id = f"{collection_id}-{cog_blob_name.replace('/', '-')}"

        if collection_id and stac.item_exists(item_id, collection_id):
            stac.delete_item(item_id, collection_id)
            result["stac_item_action"] = "deleted"
        else:
            result["stac_item_action"] = "not_found"
    except Exception as e:
        result["stac_item_action"] = "error"

    return result


@register_cleanup("process_raster_collection")
def cleanup_process_raster_collection(job_id: str, job_params: dict) -> dict:
    """
    Cleanup for failed process_raster_collection jobs.

    Artifacts to clean:
    1. Partial COGs in silver container
    2. MosaicJSON file
    3. STAC collection
    4. pgstac search registration
    """
    config = get_config()
    blob_repo = BlobRepository.instance()
    result = {"job_id": job_id}

    collection_id = job_params.get("collection_id")

    # 1. Delete COGs by prefix
    cog_prefix = f"collections/{collection_id}/"
    try:
        deleted = blob_repo.delete_blobs_by_prefix(
            container=config.storage.silver_cog_container,
            prefix=cog_prefix
        )
        result["cogs_deleted"] = deleted
    except Exception as e:
        result["cogs_deleted"] = 0
        result["cog_error"] = str(e)

    # 2. Delete MosaicJSON
    mosaic_blob = f"mosaics/{collection_id}/mosaic.json"
    try:
        if blob_repo.blob_exists(config.storage.mosaicjson_container, mosaic_blob):
            blob_repo.delete_blob(config.storage.mosaicjson_container, mosaic_blob)
            result["mosaicjson_action"] = "deleted"
        else:
            result["mosaicjson_action"] = "not_found"
    except Exception as e:
        result["mosaicjson_action"] = "error"

    # 3. Delete STAC collection
    try:
        from infrastructure.pgstac_repository import PgStacRepository
        pgstac_repo = PgStacRepository()
        if pgstac_repo.collection_exists(collection_id):
            pgstac_repo.delete_collection(collection_id)  # Cascades to items
            result["stac_collection_action"] = "deleted"
        else:
            result["stac_collection_action"] = "not_found"
    except Exception as e:
        result["stac_collection_action"] = "error"

    # 4. Delete pgstac search registration
    try:
        from services.pgstac_search_registration import PgSTACSearchRegistration
        search_reg = PgSTACSearchRegistration()
        search_reg.delete_search_by_collection(collection_id)
        result["search_registration_action"] = "deleted"
    except Exception as e:
        result["search_registration_action"] = "error"

    return result


def cleanup_job(job_id: str, job_type: str, job_params: dict) -> dict:
    """
    Execute cleanup for a job based on its type.

    Args:
        job_id: Job ID
        job_type: Job type (ingest_vector, process_raster, etc.)
        job_params: Original job parameters

    Returns:
        Cleanup result dict
    """
    handler = CLEANUP_HANDLERS.get(job_type)
    if handler:
        return handler(job_id, job_params)
    else:
        return {
            "job_id": job_id,
            "job_type": job_type,
            "cleanup_action": "no_handler",
            "message": f"No cleanup handler registered for job type: {job_type}"
        }
```

#### 4.3 Cleanup Endpoint (Standalone)

**New Endpoint**: `POST /api/jobs/cleanup/{job_id}?confirm=yes`

For cleaning up artifacts without retrying:

```python
def handle_cleanup_request(self, req: func.HttpRequest) -> func.HttpResponse:
    """
    Cleanup artifacts from a failed job WITHOUT retrying.

    Use cases:
    - Job failed due to bad input data (no point retrying)
    - Manual cleanup before data correction
    - Freeing up storage from abandoned jobs
    """
    job_id = req.route_params.get('job_id')
    confirm = req.params.get('confirm')

    if confirm != 'yes':
        return error_response("Cleanup requires ?confirm=yes")

    job = self.job_repo.get_job(job_id)
    if not job:
        return error_response(f"Job {job_id} not found", 404)

    # Execute cleanup
    cleanup_result = cleanup_job(job_id, job.job_type, job.parameters)

    # Mark job as cleaned (optional metadata field)
    self.job_repo.update_job_metadata(job_id, {
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
        "cleanup_result": cleanup_result
    })

    return success_response({
        "job_id": job_id,
        "job_type": job.job_type,
        "job_status": job.status.value,
        "cleanup_result": cleanup_result,
        "message": f"Cleanup completed for job {job_id}"
    })
```

**Task Checklist - Job Retry & Cleanup**:
- [ ] **Step 1**: Create `services/job_cleanup.py` with cleanup handlers registry
- [ ] **Step 2**: Implement `cleanup_ingest_vector()` handler
- [ ] **Step 3**: Implement `cleanup_process_raster()` handler
- [ ] **Step 4**: Implement `cleanup_process_raster_collection()` handler
- [ ] **Step 5**: Create `triggers/job_retry.py` with retry endpoint
- [ ] **Step 6**: Add `POST /api/jobs/retry/{job_id}` route to `function_app.py`
- [ ] **Step 7**: Add `POST /api/jobs/cleanup/{job_id}` route to `function_app.py`
- [ ] **Step 8**: Add `reset_tasks_for_job()` method to PostgreSQLRepository
- [ ] **Step 9**: Add `delete_blobs_by_prefix()` method to BlobRepository
- [ ] **Step 10**: Add `delete_item()` and `delete_collection()` to PgStacBootstrap
- [ ] **Step 11**: Add `delete_search_by_collection()` to PgSTACSearchRegistration
- [ ] **Step 12**: Test retry flow end-to-end
- [ ] **Step 13**: Test cleanup flow end-to-end
- [ ] **Commit**: "Add job retry and cleanup workflow for failed jobs"

**New Files**:
| File | Purpose |
|------|---------|
| `services/job_cleanup.py` | Cleanup handlers registry and implementations |
| `triggers/job_retry.py` | HTTP trigger for retry endpoint |

**Files to Modify**:
| File | Changes |
|------|---------|
| `function_app.py` | Add routes for /api/jobs/retry and /api/jobs/cleanup |
| `infrastructure/postgresql.py` | Add `reset_tasks_for_job()` method |
| `infrastructure/blob.py` | Add `delete_blobs_by_prefix()` method |
| `infrastructure/pgstac_bootstrap.py` | Add `delete_item()`, `delete_collection()` methods |
| `services/pgstac_search_registration.py` | Add `delete_search_by_collection()` method |

---

### Summary: Implementation Order

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| 1 | ingest_vector Stage 2 DELETE+INSERT | 2 hours | Prevents duplicate rows |
| 2 | Job cleanup handlers | 3 hours | Enables artifact cleanup |
| 3 | Job retry endpoint | 2 hours | Enables failed job recovery |
| 4 | Verification of existing idempotency | 1 hour | Confirms STAC handlers work |

**Total Estimated Effort**: 8 hours

---

## ✅ RESOLVED: Platform Schema Consolidation & DDH Metadata (26 NOV 2025)

**Status**: ✅ **COMPLETED** on 26 NOV 2025
**Impact**: Simplified configuration, verified DDH → STAC metadata flow

### What Was Done

**1. Platform Schema Consolidation**:
- Removed unused `platform_schema` config field from `config/database_config.py`
- Confirmed `api_requests` table was already in `app` schema (no migration needed)
- Updated documentation in `infrastructure/platform.py` and `core/models/platform.py`
- Fixed `triggers/admin/db_data.py` queries to use correct schema and columns
- Deprecated `orchestration_jobs` endpoints (HTTP 410)

**2. Worker Configuration Optimization**:
- Set `FUNCTIONS_WORKER_PROCESS_COUNT=4` via Azure CLI
- Reduced `maxConcurrentCalls` from 8 to 2 in `host.json`
- Result: 4 workers × 2 calls = 8 concurrent DB connections (was 16)

**3. DDH Metadata Passthrough Verification**:
- Tested `process_raster` job with DDH identifiers (dataset_id, resource_id, version_id, access_level)
- Verified STAC items contain `platform:*` properties with DDH values
- Confirms Platform → CoreMachine → STAC metadata pipeline is operational

**Files Modified**:
- `config/database_config.py`
- `infrastructure/platform.py`
- `core/models/platform.py`
- `triggers/admin/db_data.py`
- `host.json`

**See**: HISTORY.md entry for 26 NOV 2025 for full details.

---

## ✅ RESOLVED: SQL Generator Invalid Index Bug (24 NOV 2025)

**Status**: ✅ **FIXED** on 24 NOV 2025
**Fix Location**: `core/schema/sql_generator.py:478-491`

### What Was Fixed

The `generate_indexes_composed()` method was creating an invalid `idx_api_requests_status` index for the `api_requests` table, which does NOT have a `status` column.

**Fix Applied** (sql_generator.py:479-481):
```python
elif table_name == "api_requests":
    # Platform Layer indexes (added 16 NOV 2025, FIXED 24 NOV 2025)
    # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
    # Status is delegated to CoreMachine job_id lookup
```

Now only valid indexes are generated:
- `idx_api_requests_dataset_id`
- `idx_api_requests_created_at`

---

## 🚨 CRITICAL: JPEG COG Compression Failing in Azure Functions (21 NOV 2025)

**Status**: ❌ **BROKEN** - JPEG compression fails, DEFLATE works fine
**Priority**: **CRITICAL** - Blocks visualization tier COG creation
**Impact**: Cannot create web-optimized COGs for TiTiler streaming

### Problem Description

The `process_raster` job fails at Stage 2 (create_cog) when using `output_tier: "visualization"` (JPEG compression), but succeeds with `output_tier: "analysis"` (DEFLATE compression).

**Error**: `COG_TRANSLATE_FAILED` after ~6 seconds of processing
**Error Classification**: The error occurs in `cog_translate()` call (rio-cogeo library)

### Evidence

| Test | Output Tier | Compression | Result | Duration |
|------|-------------|-------------|--------|----------|
| dctest_v3 | visualization | JPEG | ❌ COG_TRANSLATE_FAILED | ~6 sec |
| dctest_deflate | analysis | DEFLATE | ✅ SUCCESS (127.58 MB) | 9.8 sec |

**Same input file**: dctest.tif (27 MB RGB GeoTIFF, 7777x5030 pixels, uint8)
**Same infrastructure**: Azure Functions B3 tier, same runtime, same deployment

### Root Cause Analysis (Suspected)

1. **GDAL JPEG Driver Issue**: The Azure Functions Python runtime may have a broken or missing libjpeg library linkage with GDAL/rasterio
2. **Memory Allocation Pattern**: JPEG compression may have different memory allocation patterns that fail in the constrained Azure Functions environment
3. **rio-cogeo JPEG Profile Bug**: The JPEG COG profile configuration may be incompatible with rasterio version in Azure

### Technical Context

**Code Location**: `services/raster_cog.py` lines 388-401
```python
# This call fails for JPEG, succeeds for DEFLATE
cog_translate(
    src,                        # Input rasterio dataset
    output_memfile.name,        # Output to MemoryFile
    cog_profile,                # JPEG vs DEFLATE profile
    config=config,
    overview_level=None,
    overview_resampling=overview_resampling_name,
    in_memory=in_memory,
    quiet=False,
)
```

**COG Profile Source**: `rio_cogeo.profiles.cog_profiles` dictionary
- DEFLATE profile: Works ✅
- JPEG profile: Fails ❌

### Workaround (Active)

Use `output_tier: "analysis"` (DEFLATE) instead of `output_tier: "visualization"` (JPEG):
```bash
curl -X POST ".../api/jobs/submit/process_raster" \
  -d '{"blob_name": "image.tif", "container_name": "rmhazuregeobronze", "output_tier": "analysis"}'
```

**Trade-offs**:
- ✅ DEFLATE produces larger files (127 MB vs ~5-10 MB with JPEG for RGB imagery)
- ✅ DEFLATE is lossless (better for analysis)
- ❌ DEFLATE is slower to stream via TiTiler (more bytes to transfer)
- ❌ JPEG compression ratio (97% reduction) unavailable

### Investigation Steps Required

- [ ] **Test JPEG locally**: Run rio-cogeo with JPEG profile on local machine to verify it works outside Azure
- [ ] **Check GDAL drivers**: Add diagnostic to log available GDAL drivers in Azure Functions runtime
  ```python
  from osgeo import gdal
  logger.info(f"GDAL drivers: {[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]}")
  ```
- [ ] **Check libjpeg linkage**: Verify JPEG driver is properly linked
  ```python
  import rasterio
  logger.info(f"Rasterio GDAL version: {rasterio.gdal_version()}")
  driver = rasterio.drivers.env.get('JPEG')
  ```
- [ ] **Test explicit JPEG driver**: Try creating JPEG COG with explicit driver specification
- [ ] **Check Azure Functions base image**: Determine if Python 3.12 runtime image has JPEG support
- [ ] **Review rio-cogeo GitHub issues**: Search for known JPEG issues in cloud environments
- [ ] **Add detailed error logging**: Capture the actual exception message from cog_translate()

### Fix Options (Once Root Cause Identified)

1. **If missing driver**: Add GDAL JPEG driver to requirements or use custom Docker image
2. **If memory issue**: Reduce JPEG quality or process smaller tiles
3. **If rio-cogeo bug**: Pin to specific version or patch the library
4. **If unfixable**: Document limitation and recommend DEFLATE for all tiers

### Related Config Issue Fixed (Same Session)

**Root Cause Found**: Missing `raster_cog_in_memory` legacy property in `config/app_config.py`

**Fix Applied**: Added three missing legacy properties:
```python
@property
def raster_cog_in_memory(self) -> bool:
    return self.raster.cog_in_memory

@property
def raster_target_crs(self) -> str:
    return self.raster.target_crs

@property
def raster_mosaicjson_maxzoom(self) -> int:
    return self.raster.mosaicjson_maxzoom
```

This fix was required after the config.py → config/ package migration (20 NOV 2025).

---

## ✅ STAC API Fixed & Validated (19 NOV 2025)

**Status**: **RESOLVED** - STAC API fully operational with live data
**Achievement**: Complete end-to-end validation from raster upload to browser visualization
**Completion**: 20 NOV 2025 00:40 UTC

### What Was Fixed

**Root Cause**: Tuple/dict confusion in pgSTAC query functions
- `infrastructure/pgstac_bootstrap.py:1191` - `get_collection_items()` using `result[0]` instead of `result['jsonb_build_object']`
- `infrastructure/pgstac_bootstrap.py:1291` - `search_items()` using same incorrect pattern

**Fix Applied**: Changed from tuple indexing to dictionary key access with RealDictCursor

**Validation Results**:
- ✅ Deployed to Azure Functions (20 NOV 2025 00:08:28 UTC)
- ✅ Schema redeployment: app + pgSTAC 0.9.8
- ✅ Live test: process_raster job with dctest.tif (27 MB → 127.6 MB COG)
- ✅ STAC API endpoints working: `/api/stac/collections` and `/api/stac/collections/{id}/items`
- ✅ TiTiler URLs present in STAC items using `/vsiaz/silver-cogs/` pattern
- ✅ **USER CONFIRMED**: TiTiler interactive map working in browser

### Database State

**pgSTAC** (pgstac schema):
- Version: 0.9.8 with 22 tables
- Collections: 1 (`dctest_validation_19nov2025`)
- Items: 1 (`dctest_validation_19nov2025-dctest_cog_analysis-tif`)
- Search hash functions: `search_tohash`, `search_hash`, `search_fromhash` all present
- GENERATED hash column: Working correctly

**CoreMachine** (app schema):
- Jobs: process_raster job completed in 25 seconds
- Tasks: All 3 stages completed successfully

---

## ✅ COMPLETED - Refactor config.py God Object (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025
**Restore Point**: Commit `f765f58` (pre-deletion backup)
**Purpose**: Split 1,747-line config.py into domain-specific modules
**Achievement**: 10 clean, focused modules instead of 1 monolithic file

### What Was Done

**Phase 1-3**: Created new `config/` package with domain-specific modules:
- ✅ `config/__init__.py` - Exports and singleton pattern
- ✅ `config/app_config.py` - Main composition class with legacy properties
- ✅ `config/storage_config.py` - COG tiers, multi-account storage
- ✅ `config/database_config.py` - PostgreSQL/PostGIS configuration
- ✅ `config/raster_config.py` - Raster pipeline settings
- ✅ `config/vector_config.py` - Vector pipeline settings
- ✅ `config/queue_config.py` - Service Bus queue configuration
- ✅ `config/h3_config.py` - H3 hexagonal grid configuration
- ✅ `config/stac_config.py` - STAC metadata configuration
- ✅ `config/validation.py` - Configuration validators

**Phase 4**: Deleted old `config.py` (25 NOV 2025)
- All imports now use `config/` package
- Legacy properties in `app_config.py` maintained for backward compatibility
- Production deployment verified: health check passing

### Results

| Metric | Before | After |
|--------|--------|-------|
| **AppConfig size** | 1,090 lines (63+ fields) | 150 lines (5 composed configs) |
| **Find raster setting** | Search 1,747 lines | Look in config/raster_config.py |
| **Test raster code** | Mock all 63+ fields | Only mock RasterConfig |
| **Merge conflicts** | High | Low (different files per domain) |

### Deployment Verified
```bash
# 25 NOV 2025 - Post-deletion verification
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
# ✅ Status: healthy
```

---

## 🎯 CURRENT PRIORITY - process_raster_collection Job

**Status**: Ready to implement
**Purpose**: Multi-raster collection processing with TiTiler search URLs

### Analysis (18 NOV 2025 03:50 UTC)

**The Sequence**:
1. `stac_collection.py:326` → `PgStacRepository().insert_collection()` ✅ Succeeds
2. `stac_collection.py:335` → `PgStacInfrastructure().collection_exists()` ❌ Returns False
3. Code raises: "Collection not found in PgSTAC after insertion"

**The Problem**:
- `PgStacRepository` and `PgStacInfrastructure` both create **separate** `PostgreSQLRepository` instances
- Each instance = separate connection context
- INSERT commits on Connection A, SELECT queries on Connection B
- Possible transaction isolation or connection pooling visibility issue

### Immediate Fix Required

**Quick Fix** (services/stac_collection.py lines 325-341):
```python
# BEFORE (current broken pattern):
pgstac_id = _insert_into_pgstac_collections(collection_dict)  # Creates PgStacRepository
stac_service = StacMetadataService()  # Creates PgStacInfrastructure
if not stac_service.stac.collection_exists(collection_id):  # Different connection!
    raise RuntimeError("Collection not found...")

# AFTER (single repository instance):
repo = PgStacRepository()  # Create ONCE
collection = Collection.from_dict(collection_dict)
pgstac_id = repo.insert_collection(collection)  # Use it for insert
if not repo.collection_exists(collection_id):  # Use SAME instance for verification
    raise RuntimeError("Collection not found...")
```

### Long-Term Architectural Fix - Consolidate PgSTAC Classes

**Current Duplication** (18 NOV 2025 analysis):

| Class | Lines | Purpose | Issues |
|-------|-------|---------|--------|
| **PgStacRepository** | 390 | Collections/Items CRUD | ✅ Clean, focused, newer (12 NOV) |
| **PgStacInfrastructure** | 2,060 | Setup + Operations + Queries | ❌ Bloated, duplicates PgStacRepository methods |

**Duplicate Methods Found**:
- `collection_exists()` - **THREE copies** (PgStacRepository:214, PgStacInfrastructure:802, PgStacInfrastructure:943)
- `insert_item()` - **TWO copies** (PgStacRepository:247, PgStacInfrastructure:880)

**Root Cause**: PgStacInfrastructure was created first (4 OCT), PgStacRepository added later (12 NOV) but old methods never removed

### Refactoring Plan - Rename & Consolidate

**Step 1: Rename PgStacInfrastructure → PgStacBootstrap**
- Clarifies purpose: schema setup, installation, verification
- Filename: `infrastructure/stac.py` → `infrastructure/pgstac_bootstrap.py`
- Class: `PgStacInfrastructure` → `PgStacBootstrap`

**Step 2: Move ALL Data Operations to PgStacRepository**

**PgStacBootstrap** (setup/installation ONLY):
- ✅ Keep: `check_installation()`, `install_pgstac()`, `verify_installation()`, `_drop_pgstac_schema()`, `_run_pypgstac_migrate()`
- ✅ Keep: Standalone query functions for admin/diagnostics (`get_collection()`, `get_collection_items()`, `search_items()`, etc.)
- ❌ Remove: `collection_exists()` (duplicate)
- ❌ Remove: `item_exists()` (duplicate)
- ❌ Remove: `insert_item()` (duplicate)
- ❌ Remove: `create_collection()` (data operation, not setup)

**PgStacRepository** (ALL data operations):
- ✅ Keep: All existing methods (`insert_collection()`, `update_collection_metadata()`, `collection_exists()`, `insert_item()`, `get_collection()`, `list_collections()`)
- ➕ Add: `bulk_insert_items()` (move from PgStacBootstrap)
- ➕ Add: `item_exists()` (if not already present)

**Step 3: Update All Imports**
- Search codebase for `from infrastructure.stac import PgStacInfrastructure`
- Replace with `from infrastructure.pgstac_repository import PgStacRepository` where data operations are used
- Replace with `from infrastructure.pgstac_bootstrap import PgStacBootstrap` where setup/admin functions are used

**Step 4: Fix StacMetadataService**
- Change `self.stac = PgStacInfrastructure()` to `self.stac = PgStacRepository()`
- This ensures single repository pattern throughout

### Task Breakdown

- [ ] **CRITICAL**: Implement quick fix in stac_collection.py (single repository instance)
- [ ] Test quick fix with new job submission
- [ ] Rename infrastructure/stac.py → infrastructure/pgstac_bootstrap.py
- [ ] Rename class PgStacInfrastructure → PgStacBootstrap
- [ ] Remove duplicate methods from PgStacBootstrap (collection_exists, insert_item, item_exists, create_collection)
- [ ] Add bulk_insert_items to PgStacRepository (if needed)
- [ ] Update all imports (search for PgStacInfrastructure, replace appropriately)
- [ ] Fix StacMetadataService to use PgStacRepository
- [ ] Test end-to-end STAC collection creation
- [ ] Update documentation (FILE_CATALOG.md, ARCHITECTURE_REFERENCE.md)
- [ ] Commit: "Consolidate PgSTAC: Rename to Bootstrap, eliminate duplication"

### Expected Benefits

1. ✅ **Fixes "Collection not found" error** - single repository instance eliminates READ AFTER WRITE issue
2. ✅ **Eliminates duplication** - removes 3 duplicate method implementations
3. ✅ **Clearer architecture** - PgStacBootstrap = setup, PgStacRepository = data operations
4. ✅ **Easier maintenance** - no more confusion about which class to use
5. ✅ **Better testability** - single repository pattern easier to mock

---

## ✅ RESOLVED - STAC Metadata Encapsulation (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025
**Purpose**: Standardized approach for adding custom metadata to STAC collections and items
**Achievement**: Centralized metadata enrichment with ~375 lines of duplicate code eliminated

### What Was Implemented

**Created New Files**:
- `services/iso3_attribution.py` (~300 lines) - Standalone ISO3 country code attribution service
- `services/stac_metadata_helper.py` (~550 lines) - Main helper class with dataclasses

**Key Classes Created**:

```python
# services/iso3_attribution.py
@dataclass
class ISO3Attribution:
    iso3_codes: List[str]
    primary_iso3: Optional[str]
    countries: List[str]
    attribution_method: Optional[str]  # 'centroid' or 'first_intersect'
    available: bool

class ISO3AttributionService:
    def get_attribution_for_bbox(bbox: List[float]) -> ISO3Attribution
    def get_attribution_for_geometry(geometry: Dict) -> ISO3Attribution

# services/stac_metadata_helper.py
@dataclass
class PlatformMetadata:
    dataset_id: Optional[str]
    resource_id: Optional[str]
    version_id: Optional[str]
    request_id: Optional[str]
    access_level: Optional[str]
    client_id: str = 'ddh'

    @classmethod
    def from_job_params(cls, params: Dict) -> Optional['PlatformMetadata']
    def to_stac_properties(self) -> Dict[str, Any]  # Returns platform:* prefixed dict

@dataclass
class AppMetadata:
    job_id: Optional[str]
    job_type: Optional[str]
    created_by: str = 'rmhazuregeoapi'
    processing_timestamp: Optional[str]

    def to_stac_properties(self) -> Dict[str, Any]  # Returns app:* prefixed dict

class STACMetadataHelper:
    def augment_item(item_dict, bbox, container, blob_name, platform, app,
                     include_iso3=True, include_titiler=True) -> Dict
    def augment_collection(collection_dict, bbox, platform, app,
                          include_iso3=True, register_search=True) -> Tuple[Dict, VisualizationMetadata]
```

**Files Modified**:

| File | Changes |
|------|---------|
| `services/__init__.py` | Added exports for new classes |
| `services/service_stac_metadata.py` | Added `platform_meta`, `app_meta` params; replaced inline ISO3 code with helper (~190 lines removed) |
| `services/service_stac_vector.py` | Added `platform_meta`, `app_meta` params; replaced inline ISO3 code with helper (~175 lines removed) |
| `services/stac_collection.py` | Added ISO3 attribution to collection `extra_fields` |

### Property Namespaces Implemented

| Namespace | Purpose | Example Properties |
|-----------|---------|-------------------|
| `platform:*` | DDH platform identifiers | `platform:dataset_id`, `platform:resource_id`, `platform:version_id` |
| `app:*` | Application/job linkage | `app:job_id`, `app:job_type`, `app:created_by` |
| `geo:*` | Geographic attribution | `geo:iso3`, `geo:primary_iso3`, `geo:countries` |
| `azure:*` | Azure storage provenance | `azure:source_container`, `azure:source_blob` (existing) |

### Usage Example

```python
from services import STACMetadataHelper, PlatformMetadata, AppMetadata

# Extract metadata from job parameters
platform_meta = PlatformMetadata.from_job_params(job_params)
app_meta = AppMetadata(job_id=job_id, job_type='process_raster')

# Augment STAC item
helper = STACMetadataHelper()
item_dict = helper.augment_item(
    item_dict=item_dict,
    bbox=bbox,
    container='rmhazuregeobronze',
    blob_name='test.tif',
    platform=platform_meta,
    app=app_meta,
    include_iso3=True,
    include_titiler=True
)
```

### Benefits

1. ✅ **DRY Code**: Eliminated ~375 lines of duplicated ISO3 attribution code
2. ✅ **Type Safety**: Dataclasses with factory methods prevent parameter errors
3. ✅ **Consistent Namespacing**: All metadata uses standardized prefixes
4. ✅ **Job Linkage**: Every STAC item now links back to its creating job via `app:job_id`
5. ✅ **Graceful Degradation**: Non-critical metadata failures don't block STAC creation
6. ✅ **Extensible**: Easy to add new metadata categories

### Related Bug Fix (25 NOV 2025)

**Issue**: TiTiler URLs were missing from STAC API responses at `/api/stac/collections/{id}`
**Root Cause**: `stac_api/service.py` was OVERWRITING `links[]` with standard STAC links
**Fix Applied**: Modified to preserve existing custom links (TiTiler preview/tilejson/tiles) by merging:
```python
# FIX (25 NOV 2025): Preserve TiTiler links stored in pgstac database
existing_links = response.get('links', [])
standard_rels = {'self', 'items', 'parent', 'root'}
custom_links = [link for link in existing_links if link.get('rel') not in standard_rels]
response['links'] = standard_links + custom_links
```

---

## ✅ RESOLVED - pgSTAC search_tohash() Function Failure (25 NOV 2025)

**Status**: ✅ **RESOLVED** - Workaround implemented + full-rebuild available
**Resolution Date**: 25 NOV 2025
**Documentation**: See `services/pgstac_search_registration.py` module docstring for full details

### Problem Summary

**Error**: `function search_tohash(jsonb) does not exist`
**Context**: Occurred when using `ON CONFLICT (hash)` with pgstac.searches GENERATED column

### Root Cause

The pgstac.searches table has a GENERATED column:
```sql
hash TEXT GENERATED ALWAYS AS (search_hash(search, metadata))
```

When using `ON CONFLICT (hash)`, PostgreSQL's query planner "inlines" the GENERATED column
expression during conflict detection. This caused it to look for `search_tohash(jsonb)` with
1 argument, but the function was defined as `search_tohash(jsonb, jsonb)` with 2 arguments.

### Resolution

**Two-Part Fix:**

1. **Workaround Implemented** (`services/pgstac_search_registration.py`):
   - Uses SELECT-then-INSERT/UPDATE pattern instead of UPSERT
   - Avoids `ON CONFLICT (hash)` entirely (the only operation that triggers the bug)
   - Computes hash in Python, uses it for lookup, then INSERT or UPDATE separately

2. **Root Cause Fix Available** (`/api/dbadmin/maintenance/full-rebuild?confirm=yes`):
   - `DROP SCHEMA pgstac CASCADE` + fresh `pypgstac migrate`
   - Creates functions with correct signatures
   - After clean rebuild, workaround is technically unnecessary but kept as defensive programming

### Verification Query

```sql
SELECT p.proname, pg_get_function_arguments(p.oid)
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'pgstac'
AND p.proname IN ('search_tohash', 'search_hash');

-- Expected (correct after full-rebuild):
--   search_hash    | search jsonb, metadata jsonb
--   search_tohash  | search jsonb                   <- 1 argument
```

---

## ✅ RESOLVED - Fix STAC Collection Description Validation Error (25 NOV 2025)

**Status**: ✅ **FIXED** in code
**Fix Location**: `services/stac_collection.py:110-112`
**Resolution**: Default description provided: `f"Raster collection: {collection_id}"`

### Problem Summary

**Error**: `None is not of type 'string'`
**Context**: STAC 1.1.0 collection validation fails on `description` field
**Impact**: `process_large_raster` Stage 5 (STAC creation) fails; Stages 1-4 complete successfully

### Fix Applied

**File**: `services/stac_collection.py:110-112`
```python
# FIX (25 NOV 2025): Provide default description to satisfy STAC 1.1.0 validation
description = job_parameters.get("collection_description") or params.get("description") or f"Raster collection: {collection_id}"
```

---

## 🚨 CRITICAL NEXT WORK - Repository Pattern Enforcement (16 NOV 2025)

**Purpose**: Eliminate all direct database connections, enforce repository pattern
**Status**: 🟡 **IN PROGRESS** - Managed identity operational, service files remain
**Priority**: **HIGH** - Complete repository pattern migration for maintainability
**Root Cause**: 5+ service files bypass PostgreSQLRepository, directly manage connections

**✅ Managed Identity Status**: Operational in production (15 NOV 2025)
**📘 Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for setup guide

### Architecture Violation

**Current Broken Pattern**:
```python
# ❌ VIOLATES REPOSITORY PATTERN
from config import get_postgres_connection_string
conn_str = get_postgres_connection_string()  # Creates repo, throws it away
with psycopg.connect(conn_str) as conn:      # Manages connection directly
    cur.execute("SELECT ...")                 # Bypasses repository
```

**Problems**:
1. PostgreSQLRepository created just to extract connection string
2. Connection management scattered across 10+ files
3. Can't centralize: pooling, retry logic, monitoring, token refresh
4. Violates single responsibility - repository should manage connections
5. Makes testing harder - can't mock repository

**Correct Pattern**:
```python
# ✅ REPOSITORY PATTERN - ONLY ALLOWED PATTERN
from infrastructure.postgresql import PostgreSQLRepository

# Option 1: Use repository methods (PREFERRED)
repo = PostgreSQLRepository()
job = repo.get_job(job_id)  # Repository manages connection internally

# Option 2: Raw SQL via repository connection manager (ALLOWED)
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...")
```

---

## CRITICAL ETL FILES - IMMEDIATE REFACTORING REQUIRED

### Priority 1: Schema Management (BLOCKING SCHEMA REDEPLOY)

**1. triggers/schema_pydantic_deploy.py** (lines 283-287)
- **Current**: `get_postgres_connection_string()` + `psycopg.connect()`
- **Fix**: Use `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema deployment failing (36 statements fail due to "already exists")
- **Blocking**: YES - prevents nuke operation

**2. triggers/db_query.py** (lines 139-141, 1017-1019)
- **Current**: `DatabaseQueryTrigger._get_database_connection()` builds connection directly
- **Fix**: Make `_get_database_connection()` use `PostgreSQLRepository._get_connection()`
- **Impact**: All database query endpoints + nuke operation broken
- **Blocking**: YES - nuke returns 0 objects dropped

**3. core/schema/deployer.py** (lines 102-103)
- **Current**: `SchemaManager._build_connection_string()` returns connection string
- **Fix**: Replace with `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema management utilities broken
- **Blocking**: YES - used by nuke operation

**4. infrastructure/postgis.py** (lines 57-71)
- **Current**: `check_table_exists()` uses `get_postgres_connection_string()`
- **Fix**: Create `PostgreSQLRepository`, use `_get_connection()`
- **Impact**: Table existence checks (used in validation)
- **Blocking**: NO - but needed for production readiness

---

### Priority 2: STAC Metadata Pipeline (CORE ETL)

**5. infrastructure/stac.py** (10+ direct connections)
- **Lines**: 1082-1083, 1140-1141, 1193-1194, 1283-1284, 1498-1499, 1620-1621, 1746-1747, 1816-1817, 1898-1899, 2000-2001
- **Current**: Every function creates connection via `get_postgres_connection_string()`
- **Fix**: Create `PgSTACRepository` class that wraps pgstac operations
- **Impact**: ALL STAC operations (collections, items, search)
- **Blocking**: YES - STAC is core metadata layer

**6. services/stac_collection.py** (line 617-620)
- **Current**: Uses `get_postgres_connection_string()` for pgstac operations
- **Fix**: Use `PgSTACRepository` (after creating it from #5)
- **Impact**: STAC collection creation
- **Blocking**: YES - needed for dataset ingestion

**7. services/service_stac_vector.py** (lines 181-183)
- **Current**: Direct connection for vector → STAC ingestion
- **Fix**: Use `PgSTACRepository`
- **Impact**: Vector data STAC indexing
- **Blocking**: YES - core ETL pipeline

**8. services/service_stac_setup.py** (lines 56-57)
- **Current**: `get_connection_string()` wrapper around `get_postgres_connection_string()`
- **Fix**: Delete function, use `PgSTACRepository`
- **Impact**: pgstac installation
- **Blocking**: NO - setup only

---

### Priority 3: Vector Ingestion Handlers

**9. services/vector/postgis_handler.py** (lines 55-59)
- **Current**: Stores `self.conn_string` in constructor, creates connections in methods
- **Fix**: Store `self.repo = PostgreSQLRepository()`, use `repo._get_connection()`
- **Impact**: Vector data ingestion to PostGIS
- **Blocking**: YES - primary ingestion path

**10. services/vector/postgis_handler_enhanced.py** (lines 88-92)
- **Current**: Same pattern as postgis_handler.py
- **Fix**: Same fix - use repository
- **Impact**: Enhanced vector ingestion
- **Blocking**: YES - used for complex vector datasets

---

## IMPLEMENTATION STEPS

### Step 1: Fix PostgreSQLRepository (✅ COMPLETED - 16 NOV 2025)
- [x] Remove fallback logic (no password fallback) - DONE
- [x] Use environment variable `MANAGED_IDENTITY_NAME` with fallback to `WEBSITE_SITE_NAME`
- [x] Environment variable set in Azure: `MANAGED_IDENTITY_NAME=rmhazuregeoapi`
- [x] NO fallbacks - fails immediately if token acquisition fails
- [x] **PostgreSQL user `rmhazuregeoapi` created** - Operational in production (15 NOV 2025)

### Step 2: Create PgSTACRepository Class (NEW)
**File**: `infrastructure/pgstac_repository.py` (refactor existing)
```python
class PgSTACRepository:
    """Repository for pgstac operations - wraps all STAC database operations."""

    def __init__(self):
        self.repo = PostgreSQLRepository()  # Delegate to PostgreSQL repo

    def list_collections(self) -> List[Dict]:
        with self.repo._get_connection() as conn:
            # pgstac collection listing logic

    def get_collection(self, collection_id: str) -> Dict:
        with self.repo._get_connection() as conn:
            # pgstac collection retrieval logic

    # ... all other pgstac operations
```

### Step 3: Fix Schema Management Files (COMPLETED - 16 NOV 2025)
1. ✅ **triggers/schema_pydantic_deploy.py**:
   ```python
   # OLD
   from config import get_postgres_connection_string
   conn_string = get_postgres_connection_string()
   conn = psycopg.connect(conn_string)

   # NEW
   from infrastructure.postgresql import PostgreSQLRepository
   repo = PostgreSQLRepository()
   with repo._get_connection() as conn:
       # Execute schema statements
   ```

2. ✅ **triggers/db_query.py**:
   ```python
   # OLD
   def _get_database_connection(self):
       from config import get_postgres_connection_string
       conn_str = get_postgres_connection_string()
       return psycopg.connect(conn_str)

   # NEW
   def _get_database_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()  # Returns context manager
   ```

3. ✅ **core/schema/deployer.py**:
   ```python
   # OLD
   def _build_connection_string(self) -> str:
       from config import get_postgres_connection_string
       return get_postgres_connection_string()

   # NEW
   def _get_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()
   ```

### Step 4: Migrate STAC Files to PgSTACRepository
- Update `infrastructure/stac.py` to use `PgSTACRepository` methods
- Update `services/stac_collection.py`
- Update `services/service_stac_vector.py`

### Step 5: Fix Vector Handlers
- Update `services/vector/postgis_handler.py`
- Update `services/vector/postgis_handler_enhanced.py`

### Step 6: Delete get_postgres_connection_string() Helper
**File**: `config.py` (line 1666-1747)
- **After all files migrated**, delete the helper function
- This enforces repository pattern at compile time

### Step 7: Deploy and Test
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test schema redeploy (should work 100%)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# Test STAC
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections"

# Test OGC Features
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections"
```

---

## NOT TOUCHING (Lower Priority)

### H3 Grid System (not core ETL)
- `services/handler_h3_native_streaming.py` - Can refactor later
- `services/handler_create_h3_stac.py` - Can refactor later

### OGC Features API (separate module)
- `ogc_features/config.py` - Already standalone, can refactor later

---

## ✅ MANAGED IDENTITY - USER-ASSIGNED PATTERN (22 NOV 2025)

**Status**: ✅ Configured with automatic credential detection
**Architecture**: User-assigned identity `rmhpgflexadmin` for read/write/admin database access
**Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for complete setup guide

### Authentication Priority Chain (NEW - 22 NOV 2025)

The system automatically detects and uses credentials in this order:

1. **User-Assigned Managed Identity** - If `MANAGED_IDENTITY_CLIENT_ID` is set
2. **System-Assigned Managed Identity** - If running in Azure (detected via `WEBSITE_SITE_NAME`)
3. **Password Authentication** - If `POSTGIS_PASSWORD` is set
4. **FAIL** - Clear error message with instructions

This allows the same codebase to work in:
- Azure Functions with user-assigned identity (production - recommended)
- Azure Functions with system-assigned identity (simpler setup)
- Local development with password (developer machines)

### Identity Strategy

**User-Assigned (RECOMMENDED)** - Single identity shared across multiple apps:
- `rmhpgflexadmin` - Read/write/admin access (Function App, etc.)
- `rmhpgflexreader` (future) - Read-only access (TiTiler, OGC/STAC apps)

**Benefits**:
- Single identity for multiple apps (easier to manage)
- Identity persists even if app is deleted
- Can grant permissions before app deployment
- Cleaner separation of concerns

### Environment Variables

```bash
# For User-Assigned Identity (production)
MANAGED_IDENTITY_CLIENT_ID=<client-id>        # From Azure Portal → Managed Identities
MANAGED_IDENTITY_NAME=rmhpgflexadmin          # PostgreSQL user name

# For System-Assigned Identity (auto-detected in Azure)
# No env vars needed - WEBSITE_SITE_NAME is set automatically

# For Local Development
POSTGIS_PASSWORD=<password>                   # Password auth fallback
```

### Azure Setup Required

**1. Create PostgreSQL user for managed identity**:
```sql
-- As Entra admin
SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;

-- Grant on existing tables
GRANT ALL ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;

-- Default for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO rmhpgflexadmin;
-- etc.
```

**2. Assign identity to Function App** (Azure Portal or CLI):
```bash
# Assign existing user-assigned identity
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --identities /subscriptions/{sub}/resourcegroups/rmhazure_rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/rmhpgflexadmin
```

**3. Configure environment variables**:
```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhpgflexadmin \
    MANAGED_IDENTITY_CLIENT_ID=<client-id-from-portal>
```

### Files Updated (22 NOV 2025)
- `config/database_config.py` - Added `managed_identity_client_id` field
- `infrastructure/postgresql.py` - Updated to use user-assigned identity by default

### Previous Production Setup (15 NOV 2025)
- ✅ PostgreSQL user `rmhazuregeoapi` created with pgaadauth
- ✅ All schema permissions granted (app, geo, pgstac, h3)
- ✅ Function App managed identity enabled
- ✅ Environment variable `USE_MANAGED_IDENTITY=true` configured
- ✅ PostgreSQLRepository using ManagedIdentityCredential
- ✅ Token refresh working (automatic hourly rotation)

**For New Environments** (QA/Production):

See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) section "Managed Identity for Database Connections" for complete setup instructions including:
- Azure CLI commands to enable managed identity
- PostgreSQL user creation script
- Environment variable configuration
- Verification steps

**Quick Setup** (for reference):
```bash
# 1. Enable managed identity on Function App
az functionapp identity assign --name <app-name> --resource-group <rg>

# 2. Create PostgreSQL user (as Entra admin)
psql "host=<server>.postgres.database.azure.com dbname=<db> sslmode=require"
SELECT pgaadauth_create_principal('<app-name>', false, false);
# ... grant permissions (see QA_DEPLOYMENT.md)

# 3. Configure Function App
az functionapp config appsettings set --name <app-name> \
  --settings USE_MANAGED_IDENTITY=true
```

---

## Current Status (16 NOV 2025 - 22:25 UTC)

### ✅ COMPLETED - Phase 1: Schema Management (Critical Path)
- ✅ Fixed PostgreSQLRepository:
  - Changed from `DefaultAzureCredential` → `ManagedIdentityCredential` (explicit control)
  - Removed ALL fallback logic (no password fallback)
  - Uses `MANAGED_IDENTITY_NAME` env var (value: `rmhazuregeoapi`)
  - Supports user-assigned identities via `MANAGED_IDENTITY_CLIENT_ID`
  - Fails immediately if token acquisition fails
- ✅ Fixed PostgreSQL ownership (all app schema objects owned by `rmhazuregeoapi`)
- ✅ Refactored 4 critical schema management files:
  - triggers/schema_pydantic_deploy.py
  - triggers/db_query.py
  - core/schema/deployer.py
  - infrastructure/postgis.py
- ✅ Deployed to Azure (16 NOV 2025 20:49 UTC)
- ✅ **VERIFIED WORKING**:
  - Schema redeploy: 100% success (38/38 statements)
  - Nuke operation: Works perfectly
  - Hello world job: Completed successfully
  - Managed identity authentication: Operational

### ✅ COMPLETED - Phase 2A: STAC Infrastructure (16 NOV 2025 23:20 UTC)
- ✅ **infrastructure/stac.py**: Refactored all 9 standalone functions (10 occurrences):
  - get_collection() - Added optional repo parameter
  - get_collection_items() - Added optional repo parameter
  - search_items() - Added optional repo parameter
  - get_schema_info() - Added optional repo parameter
  - get_collection_stats() - Added optional repo parameter
  - get_item_by_id() - Added optional repo parameter
  - get_health_metrics() - Added optional repo parameter
  - get_collections_summary() - Added optional repo parameter
  - get_all_collections() - Added optional repo parameter (removed duplicate, kept better implementation)
- ✅ All functions use repository pattern with dependency injection
- ✅ Backward compatible (repo parameter optional)
- ✅ Compiled successfully (python3 -m py_compile)
- ✅ ZERO remaining `get_postgres_connection_string()` calls in infrastructure/stac.py

### 🔴 REMAINING - Phase 2B: STAC Service Files (NEXT)
- ⏳ services/stac_collection.py
- ⏳ services/service_stac_vector.py
- ⏳ services/service_stac_setup.py
- ⏳ services/vector/postgis_handler.py
- ⏳ services/vector/postgis_handler_enhanced.py

### 📋 NEXT STEPS - STAC Infrastructure Refactoring

**Phase 2A: Fix infrastructure/stac.py (10 direct connections - BLOCKING STAC JOBS)**

The file has TWO usage patterns that need different fixes:

**Pattern 1: Class Methods (lines 140-166, already correct)**
- `PgStacInfrastructure.__init__()` already creates `self._pg_repo = PostgreSQLRepository()`
- `check_installation()`, `verify_installation()`, etc. already use `self._pg_repo._get_connection()`
- ✅ NO CHANGES NEEDED - already using repository pattern correctly

**Pattern 2: Standalone Functions (10 violations)**
These are module-level functions that bypass the repository pattern:

1. **get_all_collections()** (lines 1082-1083, 2000-2001) - 2 occurrences
   - Fix: Accept optional `repo` parameter, default to creating new PostgreSQLRepository

2. **get_collection()** (lines 1140-1141)
   - Fix: Same pattern - accept optional `repo` parameter

3. **get_collection_items()** (lines 1193-1194)
   - Fix: Same pattern - accept optional `repo` parameter

4. **search_items()** (lines 1283-1284)
   - Fix: Same pattern - accept optional `repo` parameter

5. **get_schema_info()** (lines 1498-1499)
   - Fix: Same pattern - accept optional `repo` parameter

6. **get_collection_stats()** (lines 1620-1621)
   - Fix: Same pattern - accept optional `repo` parameter

7. **get_item_by_id()** (lines 1746-1747)
   - Fix: Same pattern - accept optional `repo` parameter

8. **get_health_metrics()** (lines 1816-1817)
   - Fix: Same pattern - accept optional `repo` parameter

9. **get_collections_summary()** (lines 1898-1899)
   - Fix: Same pattern - accept optional `repo` parameter

**Refactoring Pattern**:
```python
# OLD
def get_all_collections() -> Dict[str, Any]:
    from config import get_postgres_connection_string
    connection_string = get_postgres_connection_string()
    with psycopg.connect(connection_string) as conn:
        # ... query logic

# NEW
def get_all_collections(repo: Optional[PostgreSQLRepository] = None) -> Dict[str, Any]:
    if repo is None:
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        # ... query logic (unchanged)
```

**Why This Pattern**:
- Allows dependency injection for testing
- Backward compatible (callers can omit repo parameter)
- Repository creates managed identity connection automatically
- No need for PgSTACRepository wrapper - these are already pgstac-schema-aware functions

**Phase 2B: Update STAC service files**
- services/stac_collection.py
- services/service_stac_vector.py
- services/service_stac_setup.py

**Phase 2C: Update vector handlers**
- services/vector/postgis_handler.py
- services/vector/postgis_handler_enhanced.py

**Phase 2D: Final cleanup**
- Delete `get_postgres_connection_string()` helper (after all migrations complete)

---

## ✅ RESOLVED - ISO3 Country Attribution in STAC Items (25 NOV 2025)

**Status**: ✅ **COMPLETED** on 25 NOV 2025 (as part of STAC Metadata Encapsulation)
**Purpose**: Add ISO3 country codes to STAC item metadata during creation
**Achievement**: Extracted to standalone service with graceful degradation

### What Was Implemented

**File Created**: `services/iso3_attribution.py` (~300 lines)

```python
@dataclass
class ISO3Attribution:
    iso3_codes: List[str]           # All intersecting countries
    primary_iso3: Optional[str]      # Centroid-based primary country
    countries: List[str]             # Country names (if available)
    attribution_method: Optional[str] # 'centroid' or 'first_intersect'
    available: bool                  # True if attribution succeeded

    def to_stac_properties(self, prefix: str = "geo") -> Dict[str, Any]:
        """Convert to STAC properties dict with namespaced keys."""

class ISO3AttributionService:
    def get_attribution_for_bbox(bbox: List[float]) -> ISO3Attribution
    def get_attribution_for_geometry(geometry: Dict) -> ISO3Attribution
```

### Integration Points

| Location | How ISO3 is Added |
|----------|-------------------|
| Raster STAC items | `STACMetadataHelper.augment_item()` calls ISO3AttributionService |
| Vector STAC items | `STACMetadataHelper.augment_item()` with `include_titiler=False` |
| STAC collections | Direct call to `ISO3AttributionService.get_attribution_for_bbox()` |

### Properties Added to STAC Items

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `geo:iso3` | List[str] | ISO 3166-1 alpha-3 codes for all intersecting countries | `["USA", "CAN"]` |
| `geo:primary_iso3` | str | Primary country (centroid-based) | `"USA"` |
| `geo:countries` | List[str] | Country names (if available in admin0 table) | `["United States", "Canada"]` |
| `geo:attribution_method` | str | How primary was determined | `"centroid"` or `"first_intersect"` |

### Configuration

Uses existing H3 config for admin0 table:
```python
from config import get_config
config = get_config()
admin0_table = config.h3.system_admin0_table  # "geo.system_admin0_boundaries"
```

### Graceful Degradation

The service handles failures gracefully:
- Returns `available=False` if admin0 table doesn't exist
- Returns `available=True` with empty lists if geometry is in ocean/international waters
- Non-fatal warnings logged but STAC item creation continues

### Future Enhancements (Unchanged)

1. **H3 Cell Lookup**: Use H3 grid with precomputed country_code for faster lookup
2. **Admin1 Attribution**: Add state/province codes for granular attribution
3. **Batch Processing**: Single query for multiple bboxes in bulk operations

---

## 🎨 MEDIUM-LOW PRIORITY - Multispectral Band Combination URLs in STAC (21 NOV 2025)

**Status**: Planned - Enhancement for satellite imagery visualization
**Purpose**: Auto-generate TiTiler viewer URLs with common band combinations for Landsat/Sentinel-2 imagery
**Priority**: MEDIUM-LOW (nice-to-have for multispectral data users)
**Effort**: 2-3 hours
**Requested By**: Robert (21 NOV 2025)

### Problem Statement

**Current State**: When `process_raster` detects multispectral imagery (11+ bands like Sentinel-2), it creates standard TiTiler URLs that don't specify band combinations. The default TiTiler viewer can't display 11-band data without explicit band selection.

**User Experience Today**:
1. User processes Sentinel-2 GeoTIFF
2. TiTiler preview URL opens blank/error page
3. User must manually craft URL with `&bidx=4&bidx=3&bidx=2&rescale=0,3000` parameters
4. No guidance provided for common visualization patterns

**Desired State**: STAC items for multispectral imagery should include multiple ready-to-use visualization URLs:
```json
{
  "assets": {
    "data": { "href": "..." },
    "visual_truecolor": {
      "href": "https://titiler.../preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../preview?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../preview?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Detection Logic

**When to generate band combination URLs**:
```python
# Criteria for "multispectral satellite imagery"
should_add_band_urls = (
    band_count >= 4 and
    (dtype == 'uint16' or dtype == 'int16') and
    (
        # Sentinel-2 pattern (11-13 bands)
        band_count in [10, 11, 12, 13] or
        # Landsat 8/9 pattern (7-11 bands)
        band_count in [7, 8, 9, 10, 11] or
        # Generic multispectral with band descriptions
        has_band_descriptions_matching(['blue', 'green', 'red', 'nir'])
    )
)
```

### Standard Band Combinations

**Sentinel-2 (10m/20m bands)**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,3000` | Natural appearance |
| False Color NIR | B8, B4, B3 | `bidx=8&bidx=4&bidx=3&rescale=0,3000` | Vegetation health |
| SWIR | B11, B8, B4 | `bidx=11&bidx=8&bidx=4&rescale=0,3000` | Moisture/geology |
| Agriculture | B11, B8, B2 | `bidx=11&bidx=8&bidx=2&rescale=0,3000` | Crop analysis |

**Landsat 8/9**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,10000` | Natural appearance |
| False Color NIR | B5, B4, B3 | `bidx=5&bidx=4&bidx=3&rescale=0,10000` | Vegetation health |
| SWIR | B7, B5, B4 | `bidx=7&bidx=5&bidx=4&rescale=0,10000` | Moisture/geology |

### Implementation Location

**File**: [services/service_stac_metadata.py](../services/service_stac_metadata.py)

**Location**: In `_generate_titiler_urls()` method, after standard URL generation (around line 455)

```python
# After generating standard URLs...

# Check if multispectral imagery
if raster_type == 'multispectral' and band_count >= 10:
    # Determine rescale based on dtype
    rescale = "0,3000" if dtype == 'uint16' else "0,255"

    # Sentinel-2 band combinations (11-13 bands)
    if band_count >= 10:
        band_combinations = {
            'truecolor': {
                'bands': [4, 3, 2],
                'title': 'True Color (RGB)',
                'description': 'Natural color composite (Red, Green, Blue)'
            },
            'falsecolor_nir': {
                'bands': [8, 4, 3],
                'title': 'False Color (NIR)',
                'description': 'Near-infrared composite for vegetation analysis'
            },
            'swir': {
                'bands': [11, 8, 4] if band_count >= 11 else [8, 4, 3],
                'title': 'SWIR Composite',
                'description': 'Short-wave infrared for moisture and geology'
            }
        }

        for combo_name, combo_info in band_combinations.items():
            bidx_params = '&'.join([f'bidx={b}' for b in combo_info['bands']])
            urls[f'preview_{combo_name}'] = f"{titiler_base}/cog/preview?url={encoded_url}&{bidx_params}&rescale={rescale}"

        logger.info(f"Added {len(band_combinations)} band combination URLs for multispectral imagery")
```

### Task Checklist

- [ ] **Step 1**: Add band combination detection logic to `_validate_raster()` or `_detect_raster_type()`
- [ ] **Step 2**: Create band combination profiles (Sentinel-2, Landsat 8/9, generic)
- [ ] **Step 3**: Extend `_generate_titiler_urls()` to add band-specific preview URLs
- [ ] **Step 4**: Update STAC item assets structure to include visual role URLs
- [ ] **Step 5**: Test with Sentinel-2 imagery (bia_glo30dem.tif is actually Sentinel-2)
- [ ] **Step 6**: Test with Landsat imagery (if available)
- [ ] **Step 7**: Document new STAC asset types in API documentation
- [ ] **Commit**: "Add band combination URLs for multispectral STAC items"

### Expected STAC Item Structure

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "sentinel2-scene-001",
  "properties": {
    "datetime": "2025-11-21T00:00:00Z",
    "geo:raster_type": "multispectral",
    "eo:bands": [
      {"name": "B1", "description": "Coastal aerosol"},
      {"name": "B2", "description": "Blue"},
      {"name": "B3", "description": "Green"},
      {"name": "B4", "description": "Red"},
      {"name": "B5", "description": "Vegetation Red Edge"},
      {"name": "B6", "description": "Vegetation Red Edge"},
      {"name": "B7", "description": "Vegetation Red Edge"},
      {"name": "B8", "description": "NIR"},
      {"name": "B8A", "description": "Vegetation Red Edge"},
      {"name": "B11", "description": "SWIR"},
      {"name": "B12", "description": "SWIR"}
    ]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/...",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    },
    "thumbnail": {
      "href": "https://titiler.../cog/preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000&width=256&height=256",
      "type": "image/png",
      "roles": ["thumbnail"]
    },
    "visual_truecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite Viewer",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Notes

- **Rescale values**: Sentinel-2 L2A reflectance is typically 0-10000 but clipped at 3000 for visualization
- **Band indexing**: TiTiler uses 1-based indexing (band 1 = first band)
- **uint16 handling**: Most satellite imagery is uint16, requires rescale parameter
- **Graceful degradation**: If band combination bands don't exist, skip that combination
