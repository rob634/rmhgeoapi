# ERRORS_AND_FIXES.md - Error Tracking and Resolution Log

**Last Updated**: 19 FEB 2026
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
| [OBSERVABILITY](#observability-errors) | Application Insights, logging, telemetry |

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

### DB-006: job_events event_id NULL constraint violation (BUG-001)

**Date**: 27 JAN 2026
**Version**: 0.7.33.x
**Severity**: Medium (Events not recorded, but jobs complete successfully)

**Error Message**:
```
null value in column "event_id" of relation "job_events" violates not-null constraint
DETAIL: Failing row contains (null, 4950fb4031cd..., STAGE_COMPLETED, ...)
```

**Location**: `infrastructure/job_event_repository.py` → `record_event()`

**Root Cause**:
The `PydanticToSQL` generator only detected SERIAL type for fields named exactly `id`. The `JobEvent` model uses `event_id` as primary key, which was generated as `INTEGER PRIMARY KEY` instead of `SERIAL PRIMARY KEY`. Without SERIAL's auto-increment sequence, INSERT without explicit `event_id` value resulted in NULL.

**Detection Pattern**:
```python
# PydanticToSQL line 250 (before fix)
if field_name == "id" and primary_key == ["id"] and is_optional:
    sql_type_str = "SERIAL"
# event_id didn't match, so INTEGER was used instead
```

**Fix Applied** (27 JAN 2026):

1. **Schema Generator Fix** (`core/schema/sql_generator.py`):
   - Added support for `__sql_serial_columns` metadata
   - Uses Python name-mangling pattern (`_ClassName__attr`) for proper attribute access
   - Models can now explicitly declare which columns are SERIAL

2. **Model Metadata** (`core/models/job_event.py`):
   - Added `__sql_serial_columns: ClassVar[List[str]] = ["event_id"]`

**Fix for Deployed Tables** (First Principles - No Migrations):
```bash
# Rebuild schema - recreates job_events with correct SERIAL type
curl -X POST "https://rmhazuregeoapi-.../api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

**Note**: JobEvent is already registered in `sql_generator.py` (lines 1567-1613). The `generate_composed_statements()` method includes:
- Enum generation for `JobEventType` and `JobEventStatus`
- Table creation for `JobEvent`
- Index creation for job_events

**Orthodox Compliance** (also added):
- `IJobEventRepository` interface in `infrastructure/interface_repository.py`
- `JobEventData` base contract in `core/contracts/__init__.py`
- Event parameter names in `ParamNames` class

**Prevention**:
- For auto-increment primary keys not named `id`, add `__sql_serial_columns` metadata
- Verify DDL output during schema deployment for new tables
- Test INSERT operations without explicit ID values

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

### DEP-003: Schema rebuild missing ETL tracking tables (vector_etl_tracking)

**Date**: 23 JAN 2026
**Version**: 0.7.20.x
**Severity**: Critical (vector ETL pipeline broken)

**Error Message**:
```
relation "app.vector_etl_tracking" does not exist
LINE 2:                     INSERT INTO app.vector_etl_tracking (
```

**Location**: `triggers/schema_pydantic_deploy.py` → `_deploy_schema()`

**Root Cause**:
The `_deploy_schema()` method only called `generator.generate_composed_statements()` which generates core app tables (jobs, tasks). It did NOT call:
- `generate_geo_schema_ddl()` - for geo schema tables
- `generate_etl_tracking_ddl()` - for ETL tracking tables like `vector_etl_tracking`

The rebuild workflow (`action=rebuild`) uses `pydantic_deploy_trigger` which was incomplete.

**Wrong Code**:
```python
composed_statements = generator.generate_composed_statements()  # Only core tables!
```

**Fixed Code** (23 JAN 2026):
```python
# 1. Geo schema (geo.table_catalog) - must come first for FK dependencies
geo_statements = generator.generate_geo_schema_ddl()

# 2. App core (jobs, tasks, api_requests, etc.)
app_core_statements = generator.generate_composed_statements()

# 3. ETL tracking (vector_etl_tracking, raster_etl_tracking) - has FK to geo.table_catalog
etl_statements = generator.generate_etl_tracking_ddl(conn=None, verify_dependencies=False)

# Combine all statements in dependency order
composed_statements = geo_statements + app_core_statements + etl_statements
```

**Prevention**:
- When adding new DDL generation methods to `PydanticToSQL`, ensure they're called in BOTH:
  - `db_maintenance.py` → `_ensure_tables()`
  - `schema_pydantic_deploy.py` → `_deploy_schema()`
- The `ensure` action was correct; only `rebuild` was broken

**Workaround** (before fix deployed):
```bash
POST /api/dbadmin/maintenance?action=ensure&confirm=yes
```

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

### PIP-006: Docker Worker Competing Consumers - Messages Immediately Dead-Lettered

**Date**: 23 JAN 2026
**Version**: 0.7.20.x
**Severity**: Critical (Docker worker completely non-functional)

**Symptoms**:
- Messages to `long-running-tasks` queue dead-lettered within 2 seconds of being sent
- Dead-letter count increasing rapidly (10 delivery attempts in ~2 seconds)
- Docker worker health shows `messages_processed: 0`
- Docker worker logs show `receive_messages() returned: 0 message(s)` consistently
- Active message count stays at 0 even immediately after sending

**Error Investigation**:
```bash
# Check queue status - shows messages going straight to dead-letter
az servicebus queue show --resource-group rmhazure_rg --namespace-name rmhazure \
  --name long-running-tasks --query "countDetails"
# Result: activeMessageCount: 0, deadLetterMessageCount: 17 (increasing)

# Check Docker worker instances - found the problem!
az webapp list-instances --name rmhheavyapi --resource-group rmhazure_rg
# Result: 2 instances running (cb79aa50... in az2, 0287b48c... in az3)
```

**Root Cause**:
The App Service Plan `ASP-rmhazure` had `capacity: 2` (2 workers), causing **two Docker container instances** to compete for the same queue. With both instances polling aggressively and potentially one instance in a bad state (stale code, startup issues), messages were rapidly received and abandoned, hitting `maxDeliveryCount=10` within seconds.

```
Instance A ──┐
             ├──► long-running-tasks queue ──► Rapid receive/abandon ──► Dead-letter
Instance B ──┘
```

**Fix**:
```bash
# Scale App Service Plan to 1 instance
az appservice plan update --name ASP-rmhazure --resource-group rmhazure_rg --number-of-workers 1

# Restart Docker worker to ensure clean state
az webapp restart --name rmhheavyapi --resource-group rmhazure_rg
```

**Verification**:
```bash
# Confirm single instance
az webapp list-instances --name rmhheavyapi --resource-group rmhazure_rg
# Should show 1 instance

# Submit test job
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/process_raster_docker" \
  -H "Content-Type: application/json" \
  -d '{"blob_name":"test.tif","container_name":"bronze-fathom","collection_id":"test"}'

# Check Docker worker health
curl https://rmhheavyapi.../health
# Should show messages_processed: 1 (or more)
```

**Prevention**:
- Docker worker is designed for **single-instance operation** (1 task at a time, all resources dedicated)
- If horizontal scaling is needed, ensure all instances are healthy and running same code version
- Monitor `az webapp list-instances` after App Service Plan changes
- Consider session-enabled queues for multi-instance scenarios

**Related**: See DOCKER_INTEGRATION.md → "Docker Worker Parallelism Model" for architecture details

### PIP-007: Draft asset approval returns 400 — version lineage self-conflict

**Date**: 18 FEB 2026
**Version**: 0.8.19.x
**Severity**: Critical (draft approval workflow completely broken)
**Found by**: QA testing (Robert + Rajesh)

**Error Message**:
```
Version lineage validation failed: Version 'None' already exists in lineage for collection '...'
```

**Location**: `services/asset_service.py` → `assign_version()`

**Root Cause**:
Draft assets were receiving full lineage wiring at submit time: `lineage_id` (computed), `version_ordinal=1`, `is_latest=True`. When `/api/platform/approve` called `assign_version()`, `validate_version_lineage()` found the draft itself as `current_latest` (because `is_latest=True`). It then rejected the new `version_id` because it detected an existing version — the draft's own unversioned record.

On the second attempt (with a bypass), the draft saw itself as predecessor, resulting in `version_ordinal=2` and `previous_asset_id` pointing to its own `asset_id`.

**Resolution** (two-part fix):

1. **`triggers/platform/submit.py`**: Drafts now get `lineage_id=None`, `version_ordinal=None`, `is_latest=False`. All lineage deferred to approval.
```python
if is_draft:
    lineage_id = None
    version_ordinal = None
    logger.info("  Draft mode: lineage validation deferred to approve")
```

2. **`services/asset_service.py`**: Added `draft_self_conflict` detection — when the only "existing" version is the draft itself, force `ordinal=1` and `previous_asset_id=None`.

**Prevention**:
- Version ordinals must NEVER be assigned until a `version_id` is provided (at approve time)
- Drafts are "invisible" to lineage until versioned
- Rule: `is_latest=False` for all drafts at submit

### PIP-008: Asset creation failure silently ignored — jobs run without asset records

**Date**: 18 FEB 2026
**Version**: 0.8.19.x
**Severity**: High (orphaned jobs with no asset linkage)
**Found by**: QA testing (Rajesh — ADO repo `ITSES-GEOSPATIAL-ETL/tree/QA`)

**Error Message**: No error — that was the problem. Asset creation failures were logged as warnings and processing continued.

**Location**: `triggers/platform/submit.py` → asset creation block

**Root Cause**:
Asset creation was wrapped in a try/except that logged a warning and continued. If the database insert failed (constraint violation, connection issue), the job would be submitted and run to completion but with no `asset_id` linked. Downstream approval, lineage, and STAC catalog operations would then fail with confusing errors.

**Resolution** (three-layer defense, ported from Rajesh):

1. **Layer 1**: Asset creation failure is now FATAL — returns HTTP 500 immediately
2. **Layer 2**: Post-creation verification reads the job back to confirm `asset_id` persisted
3. **Layer 3**: Emergency repair via `JobRepository.set_asset_id()` if verification fails

**Prevention**:
- Asset creation is a hard prerequisite for platform jobs — never degrade to warning
- Always verify critical writes with a read-back

### PIP-009: Platform validate endpoint returns 200 on validation failure

**Date**: 18 FEB 2026
**Version**: 0.8.19.x
**Severity**: Medium (clients can't distinguish valid from invalid via HTTP status)
**Found by**: QA testing (Rajesh — ADO repo)

**Error Message**: N/A — endpoint returned `{"valid": false, ...}` with HTTP 200

**Location**: `triggers/trigger_platform_status.py` → `/api/platform/validate`

**Root Cause**: The validate endpoint always returned HTTP 200 regardless of validation result. Clients relying on HTTP status codes (rather than parsing the JSON body) would treat invalid submissions as successful.

**Resolution**:
```python
status_code = 200 if validation_result.valid else 400
```

**Prevention**: API endpoints that report success/failure should use appropriate HTTP status codes, not just JSON body fields.

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

### COD-006: STAC result contract mismatch (BUG-005)

**Date**: 27 JAN 2026
**Version**: V0.8 (0.7.33.7)
**Severity**: STAC collections never created for tiled rasters

**Error Message**:
No explicit error - job completes but `"stac": {}` in result.

**Location**: `services/stac_collection.py` return statement vs `services/handler_process_raster_complete.py:439`

**Root Cause**:
Contract mismatch between handler and service. Handler expects Orthodox return pattern `{"success": True, "result": {...}}` but `stac_collection.py` returned data at top level.

**Wrong Code** (stac_collection.py):
```python
return {
    "success": True,
    "collection_id": collection_id,  # Data at top level
    "search_id": search_id,
    ...
}
```

**Handler expected**:
```python
stac_result = stac_response.get('result', {})  # Looks for 'result' key
# Gets {} because there's no 'result' key in the response!
```

**Fixed Code**:
```python
return {
    "success": True,
    "result": {  # Wrapped in "result" key
        "collection_id": collection_id,
        "search_id": search_id,
        ...
    }
}
```

**Prevention**:
1. All handler services MUST use Orthodox return pattern: `{"success": True/False, "result": {...}}`
2. Error returns can omit `result` but success returns MUST include it
3. Check handler extraction pattern when updating service returns

---

### COD-007: MosaicJSON dead code - UnboundLocalError (BUG-004)

**Date**: 27 JAN 2026
**Version**: V0.8 (0.7.33.4)
**Severity**: STAC creation fails for tiled rasters

**Error Message**:
```
"cannot access local variable 'mosaicjson_url' where it is not associated with a value"
```

**Location**: `services/stac_collection.py:628`

**Root Cause**:
MosaicJSON was deprecated in V0.8, but dead code remained. The `mosaicjson_url` variable was only defined inside the `if mosaicjson_blob:` block (line 359), but was referenced unconditionally in the return dict (line 628). When tiled raster jobs called `_create_stac_collection_impl()` with `mosaicjson_blob=None`, Python raised `UnboundLocalError`.

**Wrong Code**:
```python
# Line 356-359: Only defined conditionally
if mosaicjson_blob:
    mosaicjson_vsiaz = f"/vsiaz/{container}/{mosaicjson_blob}"
    mosaicjson_url = f"https://..."  # Only defined if mosaicjson_blob exists

# Line 628: Referenced unconditionally - BUG!
return {
    ...
    "mosaicjson_url": mosaicjson_url,  # UnboundLocalError when mosaicjson_blob is None
    ...
}
```

**Fixed Code**:
```python
# Initialize before conditional (V0.8 - BUG-004 fix)
mosaicjson_url = None  # DEPRECATED - kept for backward compat only

if mosaicjson_blob:
    mosaicjson_url = f"https://..."

# Removed mosaicjson_url from return dict entirely
return {
    ...
    # V0.8: MosaicJSON REMOVED - pgSTAC search provides mosaic access
    "search_id": search_id,  # Use search_id for TiTiler-PgSTAC mosaic access
    ...
}
```

**V0.8 Context**:
- MosaicJSON was deprecated in favor of pgSTAC searches (HISTORY 12 NOV 2025)
- pgSTAC search provides OAuth-only mosaic access without two-tier auth problems
- `search_id` is the canonical way to access mosaics via TiTiler-PgSTAC

**Prevention**:
1. When deprecating a feature, grep for ALL references and clean up dead code
2. Variable initialization should be done before conditional branches that may define them
3. Return dict fields should not reference variables that may be undefined

---

### COD-008: TiTiler bidx parameters missing for multi-band collections (BUG-012)

**Date**: 01 FEB 2026
**Version**: V0.8 (0.8.6.4)
**Severity**: Multi-band tile rendering fails (HTTP 500 from TiTiler)

**Error Message**:
```
TiTiler returns HTTP 500 when viewing collections with 4+ band COGs
Preview URL: ...map.html?assets=data (missing bidx=1&bidx=2&bidx=3)
```

**Location**: `services/handler_raster_collection_complete.py:446`

**Root Cause**:
The handler was extracting `detected_type` from the wrong level of the validation result. The RasterValidationData has structure:
```python
{
    "band_count": 8,  # TOP LEVEL
    "raster_type": {
        "detected_type": "multispectral",  # NESTED HERE
    }
}
```

But the code was doing:
```python
v.get('detected_type', 'unknown')  # Always 'unknown' - field not at top level
```

While `band_count` was correctly at top level, the `detected_type` bug masked confidence in the raster type detection. Additionally, checkpoint resume didn't re-derive raster_type from older checkpoints missing this field.

**Wrong Code**:
```python
# Lines 446-450 - BUG: detected_type is NESTED in raster_type
raster_type_info = {
    'detected_type': v.get('detected_type', 'unknown'),  # WRONG - not at top level
    'band_count': v.get('band_count', 3),  # OK
    'data_type': v.get('data_type', 'uint8'),  # OK
}
```

**Fixed Code**:
```python
# BUG-012 FIX: detected_type is nested inside raster_type
rt = v.get('raster_type', {})
raster_type_info = {
    'detected_type': rt.get('detected_type', 'unknown'),  # Fixed: access nested field
    'band_count': v.get('band_count', 3),
    'data_type': v.get('data_type', 'uint8'),
}
```

**Also Fixed**:
- Checkpoint resume now re-derives raster_type if missing from older checkpoints

**Prevention**:
1. When accessing nested structures, trace the full path through Pydantic models
2. Add logging to confirm raster_type propagation through the pipeline
3. Test multi-band (4+, 8-band) imagery specifically, not just 3-band RGB

### COD-009: Missing `import json` in asset_repository.py

**Date**: 18 FEB 2026
**Version**: 0.8.19.1
**Severity**: Critical (all asset operations with JSONB columns crash)

**Error Message**:
```
NameError: name 'json' is not defined
```

**Location**: `infrastructure/asset_repository.py` — 8+ call sites using `json.dumps()` for JSONB column serialization

**Root Cause**:
The `import json` statement was missing from the file. The module uses `json.dumps()` in every method that writes JSONB columns (`stac_properties`, `processing_options`, etc.). Likely lost during a recent edit or linter run.

**Resolution**: Added `import json` at line 29.

**Prevention**:
- When editing imports, verify all stdlib references are still present
- JSONB serialization is a critical path — any asset create/update would crash

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

## OBSERVABILITY Errors

### OBS-001: Docker Worker logs not appearing in Application Insights

**Date**: 21 JAN 2026
**Version**: 0.7.17.x
**Severity**: Breaking (no visibility into Docker worker processing)

**Error Message** (in container logs):
```
azure.monitor.opentelemetry.exporter.export._base | Retryable server side error: Operation returned an invalid status 'Unauthorized'. Your Application Insights resource may be configured to use entra ID authentication.
```

**Location**: Docker worker container logs (`az webapp log download`)

**Root Cause**:
The Docker worker was sending logs to a **different** Application Insights resource than the Function App. Additionally, the App Insights resource has `DisableLocalAuth=true` requiring Entra ID authentication.

**Key Discovery**: Multiple App Insights resources exist in the resource group:
- `rmhazuregeoapi` (correct - Function App uses this)
- `rmhheavyapi` (wrong - Docker worker was using this)
- `rmhgeoapi-worker` (wrong)

The connection strings have different instrumentation keys:
- Correct: `6aa0e75f-3c96-4e8e-a632-68d65137e39a`
- Wrong: `5f779879-7abf-409a-be84-cad2582d529d`

**Resolution**:
1. Update `APPLICATIONINSIGHTS_CONNECTION_STRING` to use the `rmhazuregeoapi` App Insights connection string
2. Add `APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD` for Entra ID auth
3. Update `docker_service.py` to pass `DefaultAzureCredential` when AAD auth is required

**Related Changes**: Docker worker setup, Application Insights configuration

**Prevention**:
- Always verify Docker worker uses same App Insights as Function App
- Check container logs for "Unauthorized" or "Forbidden" errors after deployment
- Use `/test/logging` endpoint to verify logging configuration

---

### OBS-002: Docker Worker logs "Forbidden" after AAD auth enabled

**Date**: 21 JAN 2026
**Version**: 0.7.17.x
**Severity**: Breaking

**Error Message**:
```
azure.monitor.opentelemetry.exporter.export._base | Retryable server side error: Operation returned an invalid status 'Forbidden'. Your application may be configured with a token credential but your Application Insights resource may be configured incorrectly. Please make sure your Application Insights resource has enabled entra Id authentication and has the correct `Monitoring Metrics Publisher` role assigned.
```

**Location**: Docker worker container logs

**Root Cause**:
AAD authentication is working (error changed from "Unauthorized" to "Forbidden"), but the managed identity doesn't have the required RBAC role on the Application Insights resource.

**Resolution**:
Assign "Monitoring Metrics Publisher" role to the Docker worker's managed identity:

```bash
# Get Docker worker's managed identity principal ID
PRINCIPAL_ID=$(az webapp identity show --name rmhheavyapi --resource-group rmhazure_rg --query principalId -o tsv)

# Assign role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Monitoring Metrics Publisher" \
  --scope "/subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/microsoft.insights/components/rmhazuregeoapi"
```

**Note**: Role propagation can take several minutes. Restart the Docker worker after assigning the role.

**Prevention**:
- When setting up a new Docker worker, always check for existing RBAC role assignments
- Document required roles in deployment checklist
- Test with `/test/logging/verify` endpoint after deployment

---

### OBS-003: Docker Worker logs going to wrong App Insights resource

**Date**: 21 JAN 2026
**Version**: 0.7.17.x
**Severity**: Critical (silent data loss)

**Symptoms**:
- Docker worker health shows `azure_monitor_enabled: true`
- No errors in container logs
- BUT logs don't appear when querying Function App's App Insights

**Root Cause**:
Docker worker's `APPLICATIONINSIGHTS_CONNECTION_STRING` points to a different App Insights resource than the Function App.

**How to Diagnose**:
1. Check Docker worker's instrumentation key:
```bash
curl https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net/test/logging
# Look at "instrumentation_key" in response
```

2. Compare with Function App's App Insights:
```bash
az resource show --name rmhazuregeoapi --resource-group rmhazure_rg \
  --resource-type "microsoft.insights/components" \
  --query "properties.InstrumentationKey" -o tsv
```

**Resolution**:
Update Docker worker to use correct connection string:
```bash
az webapp config appsettings set --name rmhheavyapi --resource-group rmhazure_rg \
  --settings APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=6aa0e75f-3c96-4e8e-a632-68d65137e39a;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;ApplicationId=d3af3d37-cfe3-411f-adef-bc540181cbca"
```

Then stop/start the container.

**Prevention**:
- Document the correct App Insights connection string in CLAUDE.md
- Add verification to deployment checklist
- Use `/test/logging` endpoint to confirm correct instrumentation key

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
- `DEPLOYMENT_GUIDE.md` - Deployment troubleshooting, Docker Worker App Insights setup
- `MEMORY_PROFILING.md` - OOM and memory issues
- `HISTORY.md` - Completed fixes (search for "fix", "bug", "error")

---

**Last Updated**: 19 FEB 2026
