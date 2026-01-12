# ERRORS_AND_FIXES.md - Error Tracking and Resolution Log

**Last Updated**: 10 JAN 2026
**Purpose**: Canonical error tracking for pattern analysis and faster troubleshooting

---

## How to Use This Document

### For Troubleshooting
1. **Search first**: Use Ctrl+F to search for error messages or keywords
2. **Check category**: Browse relevant error category section
3. **Apply fix**: Follow the documented resolution steps

### For Recording New Errors
When you encounter and fix an error, add an entry with:
- Error message (exact text for searchability)
- Root cause analysis
- Fix applied
- Related changes that triggered it
- Prevention tips for future

---

## Error Categories

| Category | Description |
|----------|-------------|
| [CONFIG](#config-errors) | Configuration access, attribute paths, env vars |
| [IMPORT](#import-errors) | Module imports, circular dependencies |
| [DATABASE](#database-errors) | PostgreSQL, PostGIS, connection issues |
| [STORAGE](#storage-errors) | Azure Blob, SAS tokens, container access |
| [HEALTH](#health-check-errors) | Health endpoint failures, component checks |
| [DEPLOYMENT](#deployment-errors) | Azure Functions deployment, startup failures |
| [UI](#ui-errors) | Web interface rendering, HTMX, JavaScript |
| [PIPELINE](#pipeline-errors) | Job/task processing, queue issues |
| [CODE](#code-errors) | Service layer bugs, handler errors, GDAL/raster issues |

---

## CONFIG Errors

### CFG-001: 'AppConfig' object has no attribute 'app_mode'

**Date**: 10 JAN 2026
**Version**: 0.7.6.x
**Severity**: Breaking (UI crash)

**Error Message**:
```
'AppConfig' object has no attribute 'app_mode'
```

**Location**: `web_interfaces/health/interface.py` (tooltip generation)

**Root Cause**:
The `app_mode` configuration is NOT an attribute of `AppConfig`. It's accessed via a separate singleton function `get_app_mode_config()`. This was a refactoring decision to keep app mode config separate from the main config composition.

**Wrong Code**:
```python
docker_worker_enabled = config.app_mode.docker_worker_enabled
```

**Fixed Code**:
```python
from config import get_app_mode_config
app_mode_config = get_app_mode_config()
docker_worker_enabled = app_mode_config.docker_worker_enabled
```

**Related Change**: Health interface update to show Docker Worker enabled status in tooltips

**Prevention**:
- `AppConfig` uses composition pattern with these attributes: `storage`, `database`, `queues`, `raster`, `vector`, `analytics`, `h3`, `platform`, `metrics`
- `app_mode` is separate - always use `get_app_mode_config()`

---

### CFG-002: Queue config attribute name changes

**Date**: Various (DEC 2025)
**Severity**: Breaking

**Pattern**: Queue attribute names changed during Service Bus harmonization

**Common Mistakes**:
```python
# OLD (wrong)
config.queues.long_running_raster_tasks_queue

# NEW (correct)
config.queues.long_running_tasks_queue
```

**Prevention**: Check `config/queue_config.py` for current attribute names

---

## IMPORT Errors

### IMP-001: Circular import on startup

**Date**: Various
**Severity**: App crash

**Error Pattern**:
```
ImportError: cannot import name 'X' from partially initialized module 'Y'
```

**Common Causes**:
1. Service importing from triggers
2. Models importing from services
3. Config importing from infrastructure

**Resolution Pattern**:
- Move import inside function (lazy import)
- Restructure to break cycle
- Use TYPE_CHECKING guard for type hints only

**Example Fix**:
```python
# Instead of top-level import
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.some_service import SomeService

def my_function():
    # Lazy import at runtime
    from services.some_service import SomeService
    ...
```

---

### IMP-002: stac-pydantic Asset import error

**Date**: SEP 2025
**Severity**: Breaking

**Error Message**:
```
ImportError: cannot import name 'Asset' from 'stac_pydantic'
```

**Location**: `services/service_stac_metadata.py`

**Root Cause**: `stac_pydantic` library changed export structure

**Wrong Code**:
```python
from stac_pydantic import Item, Asset
```

**Fixed Code**:
```python
from stac_pydantic import Item
from stac_pydantic.item import ItemProperties  # Asset accessed differently
```

**Prevention**: Check library changelog when upgrading dependencies

---

## DATABASE Errors

### DB-001: Managed Identity connection timeout

**Date**: Various
**Severity**: Health check failure

**Error Message**:
```
connection timed out / FATAL: password authentication failed
```

**Common Causes**:
1. Missing `POSTGIS_HOST` env var
2. Managed identity not granted access
3. Firewall rules blocking Function App

**Resolution**:
1. Verify env vars: `POSTGIS_HOST`, `POSTGIS_DATABASE`, `MANAGED_IDENTITY_ADMIN_NAME`
2. Check Azure Portal: PostgreSQL > Authentication > Add managed identity
3. Check firewall: Allow Azure services or add Function App outbound IPs

---

### DB-002: Schema does not exist

**Date**: Various
**Severity**: Query failure

**Error Message**:
```
relation "app.jobs" does not exist
```

**Resolution**:
```bash
# Rebuild schemas via API
curl -X POST "https://{app-url}/api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

---

### DB-003: PostgreSQL deadlock during vector ETL

**Date**: 17-18 OCT 2025
**Severity**: Job failure

**Error Message**:
```
deadlock detected / DETAIL: Process X waits for ShareLock on transaction Y
```

**Location**: `services/service_vector.py` (bulk insert operations)

**Root Cause**: Concurrent tasks inserting into same table without proper locking strategy

**Fix**: Added row-level locking and transaction coordination for parallel chunk processing

**Prevention**:
- Use `FOR UPDATE SKIP LOCKED` for concurrent operations
- Batch commits to reduce lock contention
- Test with parallel tasks early in development

---

### DB-004: pgSTAC search_tohash() function failure

**Date**: 25 NOV 2025
**Severity**: STAC search broken

**Error Message**:
```
function search_tohash(jsonb) does not exist
```

**Location**: STAC API search endpoints

**Root Cause**: pgSTAC function deployment incomplete or schema mismatch

**Resolution**:
1. Rebuild pgstac schema: `/api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes`
2. Verify pgSTAC extension installed: `SELECT * FROM pg_extension WHERE extname = 'pgstac'`

**Prevention**: Always rebuild both app and pgstac schemas together after deployment

---

### DB-005: STAC API tuple/dict confusion

**Date**: 20 NOV 2025
**Severity**: API returning errors

**Error Message**:
```
{"error": "0"} or KeyError when accessing STAC results
```

**Location**: `triggers/trigger_stac.py`, STAC search endpoints

**Root Cause**: pgSTAC `search()` returns tuple `(items, next_token)`, code assumed dict

**Wrong Code**:
```python
results = search(...)
return results  # Returns tuple, not dict
```

**Fixed Code**:
```python
items, next_token = search(...)  # Unpack tuple
return {"items": items, "next": next_token}
```

**Pattern Recognition**: Same issue in multiple pgSTAC query functions - consolidated fix across all patterns

---

### DB-005: psycopg3 INTERVAL parameter syntax error

**Date**: 12 JAN 2026
**Version**: 0.7.7.x
**Severity**: Breaking (Janitor completely non-functional)

**Error Message**:
```
syntax error at or near "$1"
LINE 12:               AND j.created_at < NOW() - INTERVAL $1
```

**Root Cause**:
PostgreSQL does not support parameterized INTERVAL values. When psycopg3 sends `INTERVAL %s` with a value like `'24 hours'`, PostgreSQL receives `INTERVAL $1` which is invalid syntax.

**Affected Code**:
```python
# WRONG - doesn't work with psycopg3/PostgreSQL
query = sql.SQL("... WHERE created_at < NOW() - INTERVAL %s")
result = self._execute_query(query, (f'{hours} hours',))
```

**Fix Applied**:
Use `make_interval()` PostgreSQL function instead:
```python
# CORRECT - hours
query = sql.SQL("... WHERE created_at < NOW() - make_interval(hours => %s)")
result = self._execute_query(query, (hours,))  # Pass integer directly

# CORRECT - minutes
query = sql.SQL("... WHERE created_at < NOW() - make_interval(mins => %s)")
result = self._execute_query(query, (minutes,))  # Pass integer directly
```

**Files Fixed**:
- `infrastructure/janitor_repository.py` (4 occurrences)
- `infrastructure/jobs_tasks.py` (1 occurrence)

**Impact**:
- Janitor timers were running but failing silently
- Stuck QUEUED jobs never got cleaned up
- No janitor history was recorded (0 runs shown)

**Prevention**:
- Never use `INTERVAL %s` in psycopg3 queries
- Always use `make_interval(hours => %s)` or `make_interval(mins => %s)`
- Search for `INTERVAL %s` pattern when reviewing SQL queries

---

## STORAGE Errors

### STG-001: SAS token expired or invalid

**Date**: Various
**Severity**: File access failure

**Error Pattern**:
```
AuthenticationFailed / Server failed to authenticate the request
```

**Resolution**:
- Check if using managed identity (preferred) vs SAS tokens
- Verify storage account firewall allows Function App
- Check container-level permissions

---

## HEALTH Check Errors

### HLT-001: TiTiler /health returning 404

**Date**: 10 JAN 2026
**Severity**: Warning (yellow indicator)

**Symptom**: TiTiler shows as healthy in livez but /health returns 404

**Root Cause**: TiTiler deployment may not have /health endpoint configured, or endpoint path differs

**Workaround**: System handles gracefully - shows warning (yellow) when only livez responds

---

### HLT-002: Health check timeout (75s)

**Date**: 12 DEC 2025
**Version**: 0.5.x
**Severity**: Health endpoint unusable

**Root Cause**: Sequential health checks taking too long

**Fix Applied**: Parallel health checks with ThreadPoolExecutor, 25s timeout per external service

**Reference**: `triggers/health.py` - `_run_checks_parallel()`

---

## DEPLOYMENT Errors

### DEP-001: STARTUP_FAILED - Missing environment variables

**Date**: Various
**Severity**: App won't start

**Error in Application Insights**:
```
STARTUP_FAILED: Missing required environment variable: POSTGIS_HOST
```

**Resolution**:
1. Check Application Insights for exact missing var
2. Add via Azure Portal or CLI:
```bash
az functionapp config appsettings set --name rmhazuregeoapi --resource-group rmhazure_rg --settings VAR_NAME=value
```

**Required Env Vars**:
- `POSTGIS_HOST`, `POSTGIS_DATABASE`, `POSTGIS_SCHEMA`
- `APP_SCHEMA`, `PGSTAC_SCHEMA`, `H3_SCHEMA`
- `SERVICE_BUS_FQDN`

---

### DEP-002: ModuleNotFoundError after deployment

**Date**: Various
**Severity**: Function crashes

**Common Causes**:
1. New dependency not in requirements.txt
2. Remote build failed silently
3. Python version mismatch

**Resolution**:
1. Check deployment logs for pip install errors
2. Verify requirements.txt includes all imports
3. Check `func azure functionapp publish` output for warnings

---

## UI Errors

### UI-001: HTMX OOB swap fails in table context

**Date**: 26 DEC 2025
**Severity**: Stats not updating

**Root Cause**: Browser HTML parser can't handle `<div>` inside `<tbody>` context

**Fix**: Wrap OOB elements in `<template>` tag

**Reference**: `web_interfaces/jobs/interface.py` - `_render_stats_oob()`

---

### UI-002: JavaScript data path mismatch after health restructure

**Date**: 10 JAN 2026
**Severity**: Hardware info not displaying

**Error**: Environment/hardware section hidden despite data being returned

**Root Cause**: Health endpoint restructure changed data paths:
- Old: `data.components.hardware.details`
- New: `data.components.runtime.details.hardware`

**Fix**: Update JavaScript to use new path and merge hardware + memory + instance objects

---

## PIPELINE Errors

### PIP-001: Task stuck in processing

**Date**: Various
**Severity**: Job never completes

**Common Causes**:
1. Worker crashed mid-task
2. Service Bus message lock expired
3. Unhandled exception (no error logging)

**Resolution**:
1. Check Application Insights for errors around task start time
2. Use `/api/dbadmin/tasks/{job_id}` to see task details
3. Consider manual status update if worker crashed

---

### PIP-002: CoreMachine status transition "PROCESSING → PROCESSING" error

**Date**: 21 OCT 2025
**Severity**: Multi-stage jobs broken

**Error Message**:
```
Invalid status transition: PROCESSING → PROCESSING
```

**Location**: `core/machine.py`

**Root Cause**: Two bugs in CoreMachine:
1. `_advance_stage()` didn't update job status to QUEUED before sending next stage message
2. Silent exception swallowing in `process_job_message()` - status transition validation errors caught with comment "# Continue - not critical"

**Fix Applied**:
1. Added status update in `_advance_stage()` to set QUEUED before next stage
2. Removed silent exception swallowing - validation errors ARE critical

**Key Insight**: This bug affected ALL multi-stage jobs. Single-stage jobs don't reveal status transition bugs.

**Prevention**:
- Never swallow exceptions silently - schema validation errors are critical
- Test multi-stage workflows early in development
- Verify state machines with explicit transition logging

---

### PIP-003: Job stage advancement tracking bug

**Date**: 14 NOV 2025
**Severity**: Jobs never complete

**Symptom**: Jobs stuck between stages - stage 1 completes but stage 2 never starts

**Root Cause**: "Last Task Turns Out the Lights" pattern not detecting stage completion correctly

**Fix**: Improved atomic SQL for detecting when all tasks in a stage are complete

**Reference**: `core/machine.py` - `_check_stage_completion()`

---

### PIP-004: Critical job status bug - QUEUED → FAILED transition

**Date**: 11 NOV 2025
**Severity**: Jobs stuck in infinite retry loop

**Error Message**:
```
Invalid status transition: JobStatus.QUEUED → JobStatus.FAILED
```

**Root Cause**: Job state machine only allowed:
- QUEUED → PROCESSING (normal)
- PROCESSING → FAILED (processing failure)
- Missing: QUEUED → FAILED (early failure)

**Scenario**: Old Service Bus messages cause task pickup failures. CoreMachine cannot mark jobs as failed before PROCESSING state.

**Fix Applied** (`core/models/job.py` lines 127-130):
```python
# Allow early failure before processing starts (11 NOV 2025)
# Handles cases where job fails during task pickup or pre-processing validation
if current == JobStatus.QUEUED and new_status == JobStatus.FAILED:
    return True
```

**Benefits**:
- Graceful error handling for pre-processing failures
- No more infinite retry loops
- Failed jobs visible in database with proper status

---

### PIP-005: Retry orchestration bugs (3 critical)

**Date**: SEP 2025
**Severity**: Tasks failing silently

**Bug 1: StateManager missing task_repo**
```
AttributeError: 'StateManager' object has no attribute 'task_repo'
```
**Fix**: Added RepositoryFactory initialization in `__init__`

**Bug 2: TaskRepository schema reference**
```
'TaskRepository' object has no attribute 'schema'
```
**Fix**: Changed `self.schema` to `self.schema_name` in SQL composition

**Bug 3: Service Bus application_properties None**
```
TypeError: 'NoneType' object does not support item assignment
```
**Fix**: Added `sb_message.application_properties = {}` before setting metadata

**Validation**: Stress tested with n=100 tasks, 10% failure rate - all retries worked correctly

---

## CODE Errors

### COD-001: JPEG visualization tier INTERLEAVE bug

**Date**: 28 NOV 2025
**Severity**: JPEG output broken

**Error Message**:
```
Can't process input with band interleaving
```

**Location**: `services/raster_cog.py`

**Root Cause**: JPEG encoding requires PIXEL interleaving, but code was setting BAND for YCbCr encoding

**Wrong Code**:
```python
profile = {"interleave": "BAND", ...}  # Wrong for JPEG
```

**Fixed Code**:
```python
if output_format == "JPEG":
    profile = {"interleave": "PIXEL", ...}  # JPEG requires PIXEL interleaving
```

**Prevention**: Test all output format variants, not just defaults

---

### COD-002: Enum string conversion bug

**Date**: SEP 2025
**Severity**: COG creation crash

**Error Message**:
```
KeyError: <Resampling.cubic: 2>
```

**Location**: `services/raster_cog.py:244`

**Root Cause**: Passing Enum object where string expected

**Fix**: Added `.name` property conversion:
```python
resampling = resampling_method.name  # "cubic" instead of <Resampling.cubic: 2>
```

**Prevention**: Always convert enums to strings at API boundaries

---

### COD-003: BlobRepository method name mismatch

**Date**: SEP 2025
**Severity**: Upload fails

**Error Message**:
```
AttributeError: 'BlobRepository' object has no attribute 'upload_blob'
```

**Location**: `services/raster_cog.py:302`

**Root Cause**: Called wrong method name after repository refactoring

**Fix**: Changed method call from `upload_blob` to `write_blob`

**Prevention**: After refactoring, grep for old method names across codebase

---

### COD-004: ContentSettings object vs dict

**Date**: SEP 2025
**Severity**: Azure SDK error

**Error Message**:
```
AttributeError: 'dict' object has no attribute 'cache_control'
```

**Location**: `infrastructure/blob.py:353`

**Root Cause**: Azure SDK expects `ContentSettings` object, not plain dict

**Wrong Code**:
```python
content_settings = {"content_type": "image/tiff", "cache_control": "..."}
```

**Fixed Code**:
```python
from azure.storage.blob import ContentSettings
content_settings = ContentSettings(content_type="image/tiff", cache_control="...")
```

**Prevention**: Check Azure SDK type requirements when using options objects

---

### COD-005: rio_stac Item not subscriptable

**Date**: SEP 2025
**Severity**: STAC metadata extraction fails

**Error Message**:
```
'Item' object is not subscriptable
```

**Location**: `services/service_stac_metadata.py`

**Root Cause**: `rio_stac.create_stac_item()` returns `pystac.Item` object, not dict

**Fix**: Added type check and conversion:
```python
if isinstance(item, pystac.Item):
    item = item.to_dict()
```

**Prevention**: Always check return types from external libraries

---

## Error Pattern Analysis

### Common Refactoring Breakage Patterns

| Change Type | Typical Errors | Prevention |
|-------------|----------------|------------|
| Config restructure | Attribute not found | Grep for old attribute names |
| Health endpoint changes | JS data path mismatch | Update UI after backend changes |
| Import reorganization | Circular imports | Test imports in isolation |
| Schema changes | Table/column not found | Run rebuild after deploy |
| Env var renames | Startup failures | Update all deployment configs |

### Error Frequency by Category (Estimate)

| Category | Frequency | Impact |
|----------|-----------|--------|
| CONFIG | High | Medium-High |
| PIPELINE | High | Critical |
| CODE | Medium | High |
| DEPLOYMENT | Medium | High |
| DATABASE | Medium | High |
| UI | Medium | Low |
| IMPORT | Low | High |

### Root Cause Categories

| Root Cause | Example Errors | Prevention |
|------------|---------------|------------|
| **Type confusion** | COD-002 (enum), COD-004 (dict vs object), COD-005 (item type) | Explicit type checks at boundaries |
| **API contract changes** | COD-003 (method rename), IMP-002 (import structure) | Grep after refactoring, check changelogs |
| **State machine gaps** | PIP-002, PIP-004 (missing transitions) | Test all state paths, not just happy path |
| **Silent failures** | PIP-002 (swallowed exceptions) | Never catch-and-continue without logging |
| **Data path mismatches** | UI-002 (JS paths), DB-005 (tuple vs dict) | Schema validation, type hints |
| **Concurrency issues** | DB-003 (deadlocks) | Test parallel operations early |

### Debugging Strategy by Symptom

| Symptom | First Check | Category |
|---------|-------------|----------|
| App won't start | Application Insights for STARTUP_FAILED | DEPLOYMENT |
| 'object has no attribute' | Config access pattern, method names | CONFIG, CODE |
| Job stuck in PROCESSING | CoreMachine transitions, task completion | PIPELINE |
| UI not updating | JS console, data path changes | UI |
| Empty/error API responses | Return type handling, tuple unpacking | DATABASE, CODE |

---

## Adding New Errors

Use this template:

```markdown
### XXX-NNN: Brief description

**Date**: DD MMM YYYY
**Version**: 0.x.x.x
**Severity**: Breaking/Warning/Info

**Error Message**:
```
Exact error text for searchability
```

**Location**: file/path.py (context)

**Root Cause**:
Why this happened

**Resolution**:
How to fix it

**Related Change**: What triggered this error

**Prevention**: How to avoid in future
```

---

## Related Documents

- `APPLICATION_INSIGHTS.md` - Log query patterns for debugging
- `DEPLOYMENT_GUIDE.md` - Deployment troubleshooting
- `MEMORY_PROFILING.md` - OOM and memory issues
- `HISTORY.md` - Completed fixes (search for "fix", "bug", "error")
