# Multi-App Routing Cleanup Plan

**Created**: 19 FEB 2026
**Priority**: Low
**Trigger**: Codebase still carries artifacts from the deprecated multi-Function App architecture (raster-tasks, vector-tasks, worker_functionapp). All processing now routes through Docker worker only.

---

## Background

The project originally used multiple Azure Function Apps for processing (raster worker, vector worker, etc.) with separate Service Bus queues. V0.8 (24 JAN 2026) consolidated everything to a single Docker worker consuming `container-tasks`. V0.9 (18 FEB 2026) moved ALL remaining functionapp-tasks to Docker. The old routing code, queue configs, and model fields are now dead weight.

---

## Complete Inventory of Obsolete Items

### 1. Deprecated Queue Constants in QueueDefaults

**File**: `config/defaults.py` (lines 342-345)

| Item | Value | Status |
|------|-------|--------|
| `QueueDefaults.RASTER_TASKS_QUEUE` | `"raster-tasks"` | Dead constant, marked DEPRECATED |
| `QueueDefaults.VECTOR_TASKS_QUEUE` | `"vector-tasks"` | Dead constant, marked DEPRECATED |
| `QueueDefaults.LONG_RUNNING_TASKS_QUEUE` | `"long-running-tasks"` | Dead constant, marked DEPRECATED |

**Consumed by**: `QueueNames` class, `QueueConfig` fields, `from_environment()` — all deprecated consumers.

### 2. Deprecated Queue Constants in QueueNames

**File**: `config/queue_config.py` (lines 171-174)

| Item | Status |
|------|--------|
| `QueueNames.RASTER_TASKS` | Dead constant, references `QueueDefaults.RASTER_TASKS_QUEUE` |
| `QueueNames.VECTOR_TASKS` | Dead constant, references `QueueDefaults.VECTOR_TASKS_QUEUE` |
| `QueueNames.LONG_RUNNING_TASKS` | Dead constant, references `QueueDefaults.LONG_RUNNING_TASKS_QUEUE` |

**Consumed by**: Nothing in active code (grep confirms zero external references).

### 3. Deprecated QueueConfig Fields

**File**: `config/queue_config.py` (lines 230-244, 294-300)

| Item | Status |
|------|--------|
| `QueueConfig.raster_tasks_queue` field | Dead field, marked DEPRECATED |
| `QueueConfig.vector_tasks_queue` field | Dead field, marked DEPRECATED |
| `QueueConfig.long_running_tasks_queue` field | Dead field, marked DEPRECATED |
| `from_environment()` lines 294-300 | Loads deprecated env vars into deprecated fields |

**Consumed by**:
- `config/__init__.py` line 174-175 — debug dict includes `raster_tasks_queue` and `vector_tasks_queue`
- `triggers/admin/db_maintenance.py` lines 922-923 — queue clear uses `raster_tasks_queue` and `vector_tasks_queue`

### 4. Deprecated Env Var Validation Rules

**File**: `config/env_validation.py` (lines 376-401)

| Env Var | Status |
|---------|--------|
| `SERVICE_BUS_RASTER_TASKS_QUEUE` | Dead rule — no code reads this env var in active paths |
| `SERVICE_BUS_VECTOR_TASKS_QUEUE` | Dead rule — no code reads this env var in active paths |
| `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE` | Dead rule — no code reads this env var in active paths |

### 5. Deprecated Routing Aliases in TaskRoutingDefaults

**File**: `config/defaults.py` (lines 476-482)

```python
LONG_RUNNING_TASKS = list(DOCKER_TASKS)  # DEPRECATED
RASTER_TASKS = []                        # DEPRECATED
VECTOR_TASKS = []                        # DEPRECATED
```

**Consumed by**: Nothing (grep confirms zero external references to `TaskRoutingDefaults.RASTER_TASKS`, etc.)

### 6. Empty FUNCTIONAPP_TASKS Frozenset + Dead Routing Branch

**File**: `config/defaults.py` (line 474) — `FUNCTIONAPP_TASKS = frozenset()` (empty)
**File**: `core/machine.py` — `elif task_type in TaskRoutingDefaults.FUNCTIONAPP_TASKS` branch can never match

### 7. `functionapp-tasks` Queue Config

**File**: `config/queue_config.py` (lines 224-228, 290-293)

| Item | Status |
|------|--------|
| `QueueNames.FUNCTIONAPP_TASKS` constant | Dead — no task routes here |
| `QueueConfig.functionapp_tasks_queue` field | Dead — no task routes here |
| `from_environment()` lines 290-293 | Loads dead queue name |

### 8. Dead `functionapp-tasks` Queue Trigger

**File**: `function_app.py` (~lines 1427-1445)

Full Service Bus trigger registered for `functionapp-tasks` queue. `FUNCTIONAPP_TASKS = frozenset()` means no task types route here. Trigger fires on nothing.

### 9. `_force_functionapp` Admin Override

**File**: `triggers/submit_job.py` (~lines 75-114) — captures `?force_functionapp=true` query param
**File**: `core/machine.py` (~lines 301-308) — routing branch sends tasks to dead `functionapp-tasks` queue

Tasks sent via this override are silently lost (no consumer exists).

### 10. `WORKER_FUNCTIONAPP` App Mode

**File**: `config/app_mode_config.py` (~line 143)

| Item | Status |
|------|--------|
| `AppMode.WORKER_FUNCTIONAPP` enum value | No deployed app uses this mode |
| `listens_to_functionapp_tasks` property | Only True for STANDALONE + WORKER_FUNCTIONAPP |
| Migration hints for old modes | `worker_raster`, `worker_vector`, `platform_raster`, `platform_vector` |

**File**: `config/defaults.py` (~lines 385, 388-389)
- `AppModeDefaults.WORKER_FUNCTIONAPP` constant
- Listed in `VALID_MODES`

### 11. Unused App URLs in AppModeConfig

**File**: `config/app_mode_config.py` (~lines 175-183, 488-489, 539-540)

| Item | Status |
|------|--------|
| `raster_app_url` field | Marked "future use", zero references outside own class |
| `vector_app_url` field | Marked "future use", zero references outside own class |
| `from_environment()` loads `RASTER_APP_URL`, `VECTOR_APP_URL` | Dead env var reads |
| `debug_dict()` includes both | Dead debug output |

### 12. Obsolete TaskRecord Fields (DATABASE COLUMNS)

**File**: `core/models/task.py` (lines 80-92)

| Field | Description | Added |
|-------|-------------|-------|
| `target_queue` | "Service Bus queue task was routed to (raster-tasks, vector-tasks, etc)" | 07 DEC 2025 |
| `executed_by_app` | "APP_NAME of the Function App that processed this task" | 07 DEC 2025 |
| `execution_started_at` | "Timestamp when task processing began (for duration tracking)" | 07 DEC 2025 |

**Also referenced in**:
- `core/schema/sql_generator.py` (~line 1080) — index definitions on these columns
- `core/schema/updates.py` (~line 60) — allows updates to these fields
- `triggers/admin/db_data.py` (~lines 520-556) — queries these fields for display

### 13. Health Check References to Dead Modes/Queues

**File**: `triggers/health_checks/application.py`
- ~line 87: Reports `functionapp_tasks` listening status
- ~line 163: Lists `worker_functionapp` as valid mode
- ~line 231: Checks `worker_functionapp` in conditional

### 14. Admin Maintenance References Deprecated Queues

**File**: `triggers/admin/db_maintenance.py` (lines 920-923)

Queue clear logic uses `config.queues.raster_tasks_queue` and `config.queues.vector_tasks_queue` instead of the active `container_tasks_queue`.

### 15. Deprecated Queue Documentation in queue_config.py Module Docstring

**File**: `config/queue_config.py` (lines 46-82)

Module docstring still documents old 4-queue architecture (raster-tasks, vector-tasks, long-running-tasks) with setup instructions. References deprecated env vars.

### 16. Debug Dict Includes Deprecated Queues

**File**: `config/__init__.py` (lines 171-177)

```python
'queues': {
    'jobs_queue': config.queues.jobs_queue,
    'raster_tasks_queue': config.queues.raster_tasks_queue,
    'vector_tasks_queue': config.queues.vector_tasks_queue,
    ...
}
```

Should show `container_tasks_queue` instead.

### 17. Hardcoded Deprecated App URLs

**File**: `infrastructure/pgstac_bootstrap.py` (~lines 2350, 2439) — `rmhgeoapibeta` URLs
**File**: `test/test_deployment_readiness.py` — references `rmhgeoapibeta`

### 18. 410 Gone Endpoint Stubs (KEEP FOR NOW)

**File**: `triggers/platform/platform_bp.py` (lines 699-801)

| Endpoint | Response |
|----------|----------|
| `POST /api/platform/raster` | 410 Gone with migration hint |
| `POST /api/platform/raster-collection` | 410 Gone with migration hint |
| `POST /api/platform/vector` | 410 Gone with migration hint |

**Action**: KEEP until DDH platform has fully migrated (Feature 7 complete).

---

## Items to KEEP

| Item | Reason |
|------|--------|
| `docker_worker_enabled` | Active — standalone mode uses this to decide whether to listen on `container-tasks` |
| `processing_mode` in raster results | Active — internal GDAL strategy flag (disk vs memory), not app routing |
| `container-tasks` queue | Active — Docker worker consumes this |
| `geospatial-jobs` queue | Active — orchestrator consumes this |
| 410 Gone endpoint stubs | Good deprecation practice during DDH migration |

---

## Execution Plan (Lowest Risk First)

### Wave 1: Config Constants (ZERO runtime impact — just removing dead constants)

| Step | File | Action | Risk |
|------|------|--------|------|
| 1a | `config/defaults.py` | Remove 3 deprecated `QueueDefaults` constants (lines 342-345) | None — only consumed by deprecated QueueConfig fields |
| 1b | `config/defaults.py` | Remove 3 deprecated `TaskRoutingDefaults` aliases (lines 480-482) | None — zero external references |
| 1c | `config/defaults.py` | Remove `AppModeDefaults.WORKER_FUNCTIONAPP` + update `VALID_MODES` | Low — no deployment uses this mode |
| 1d | `config/defaults.py` | Update `QueueDefaults` docstring to remove functionapp-tasks mention | None |
| 1e | `config/defaults.py` | Update `AppModeDefaults` docstring to remove functionapp references | None |

### Wave 2: Queue Config Cleanup (removes deprecated fields + consumers)

| Step | File | Action | Risk |
|------|------|--------|------|
| 2a | `config/queue_config.py` | Remove 3 `QueueNames` deprecated constants | None — zero external references |
| 2b | `config/queue_config.py` | Remove 3 `QueueConfig` deprecated fields + `from_environment()` lines | Low — consumers updated in 2c-2d |
| 2c | `config/__init__.py` | Update debug dict: replace `raster_tasks_queue`/`vector_tasks_queue` with `container_tasks_queue` | None |
| 2d | `triggers/admin/db_maintenance.py` | Fix queue clear to use `container_tasks_queue` instead of deprecated queues | Low — fixes a bug (clearing wrong queues) |
| 2e | `config/env_validation.py` | Remove 3 deprecated env var validation rules | None |
| 2f | `config/queue_config.py` | Update module docstring to reflect Docker-only architecture | None |

### Wave 3: App Mode Config Cleanup

| Step | File | Action | Risk |
|------|------|--------|------|
| 3a | `config/app_mode_config.py` | Remove `raster_app_url` + `vector_app_url` fields, `from_environment()` lines, `debug_dict()` lines | None — zero external references |
| 3b | `config/app_mode_config.py` | Remove `WORKER_FUNCTIONAPP` enum value + migration hints for old modes | Low — check Azure App Settings first |
| 3c | `triggers/health_checks/application.py` | Remove `functionapp_tasks` + `worker_functionapp` references | Low |

### Wave 4: Routing Cleanup (removes dead code paths)

| Step | File | Action | Risk |
|------|------|--------|------|
| 4a | `triggers/submit_job.py` | Remove `_force_functionapp` parameter capture | Low |
| 4b | `core/machine.py` | Remove `_force_functionapp` routing branch | Low |
| 4c | `config/defaults.py` | Remove empty `FUNCTIONAPP_TASKS` frozenset | Low — routing branch removed in 4b |
| 4d | `core/machine.py` | Remove dead `elif FUNCTIONAPP_TASKS` routing branch | Low |
| 4e | `config/queue_config.py` | Remove `functionapp_tasks_queue` field + `QueueNames.FUNCTIONAPP_TASKS` | Low |

### Wave 5: Function App Trigger Cleanup

| Step | File | Action | Risk |
|------|------|--------|------|
| 5a | `function_app.py` | Remove dead `process_functionapp_task()` trigger | Medium — Azure Functions deployment |
| 5b | `config/app_mode_config.py` | Remove `listens_to_functionapp_tasks` property | Low — after 5a |
| 5c | `startup/service_bus_validator.py` | Remove `functionapp-tasks` queue validation | Low |

### Wave 6: Database Schema Cleanup (HIGHEST RISK)

| Step | File | Action | Risk |
|------|------|--------|------|
| 6a | `core/models/task.py` | Remove `target_queue`, `executed_by_app`, `execution_started_at` fields | Medium — schema migration |
| 6b | `core/schema/sql_generator.py` | Remove index definitions for dropped columns | Medium |
| 6c | `core/schema/updates.py` | Remove update allowances for dropped fields | Low |
| 6d | `triggers/admin/db_data.py` | Remove queries for dropped fields | Low |
| 6e | Schema migration | `ALTER TABLE tasks DROP COLUMN` for all 3 | Medium — run at next rebuild |

### Wave 7: Miscellaneous Cleanup (DEFERRED)

| Step | File | Action | Risk |
|------|------|--------|------|
| 7a | `infrastructure/pgstac_bootstrap.py` | Replace `rmhgeoapibeta` URLs with active app URLs | Low |
| 7b | `test/test_deployment_readiness.py` | Replace deprecated app references | Low |
| 7c | `triggers/platform/platform_bp.py` | Remove 410 Gone stubs | Deferred — keep until DDH migration complete |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Removing queue config breaks startup | Wave 1-2 only remove dead constants/fields — no active code uses them |
| Removing WORKER_FUNCTIONAPP breaks a deployment | Check Azure App Settings for all 3 apps before Wave 3 |
| Removing functionapp trigger breaks Azure Functions | Wave 5 after all routing cleanup — deploy and verify |
| TaskRecord field removal breaks DB reads | Wave 6 at next schema rebuild — use `action=ensure` with ALTER |
| Someone still uses `?force_functionapp` | Check App Insights for recent usage before Wave 4 |
| 410 stubs removed too early | Wave 7c deferred until Feature 7 DDH integration complete |
