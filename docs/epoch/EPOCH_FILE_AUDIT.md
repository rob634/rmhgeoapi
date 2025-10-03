# Epoch File Audit - Categorization of All Python Files

**Date**: 30 SEP 2025
**Purpose**: Identify which files belong to Epoch 3 (deprecated) vs Epoch 4 (active)
**Goal**: Safe archival of Epoch 3 files without breaking Epoch 4

---

## Category Definitions

### 🟢 EPOCH 4 - ACTIVE
Files that are part of the new architecture and must remain

### 🔴 EPOCH 3 - DEPRECATED
Files that are replaced by Epoch 4 and can be archived

### 🟡 SHARED - USED BY BOTH
Files used by both epochs (careful migration needed)

### 🔵 INFRASTRUCTURE - ALWAYS ACTIVE
Core infrastructure used regardless of epoch

---

## ROOT DIRECTORY FILES (25 files)

### 🟢 EPOCH 4 - ACTIVE (2 files)
```
./test_core_machine.py         - Epoch 4 validation tests
./test_deployment_ready.py     - Epoch 4 deployment tests
```

### 🔴 EPOCH 3 - DEPRECATED (8 files)
```
./controller_base.py                    - God Class (2,290 lines) - REPLACED by CoreMachine
./controller_container.py               - Epoch 3 container controller
./controller_hello_world.py             - Epoch 3 hello world - REPLACED by jobs/hello_world.py
./controller_service_bus.py             - Epoch 3 Service Bus base controller
./controller_service_bus_container.py   - Epoch 3 Service Bus container
./controller_service_bus_hello.py       - Epoch 3 Service Bus hello - REPLACED by CoreMachine
./controller_stac_setup.py              - Epoch 3 STAC controller
./debug_service_bus.py                  - Debug script (not part of app)
```

### 🟡 SHARED - USED BY BOTH (11 files)
```
./config.py                    - Configuration (both use)
./controller_factories.py      - Factory pattern (Epoch 3 controllers)
./exceptions.py               - Custom exceptions (both use)
./function_app.py             - Entry point (wired for Epoch 4, still loads Epoch 3)
./registration.py             - Job/Task catalogs (Epoch 3 pattern)
./schema_base.py              - Base schemas (both use)
./schema_blob.py              - Blob schemas (both use)
./schema_manager.py           - Schema deployment (both use)
./schema_orchestration.py     - Orchestration schemas (both use)
./schema_queue.py             - Queue message schemas (both use)
./schema_sql_generator.py     - SQL generation (both use)
./schema_updates.py           - Update models (both use)
./schema_workflow.py          - Workflow schemas (both use)
./service_bus_list_processor.py - Service Bus helper (both use)
./task_factory.py             - Task handler factory (Epoch 3 pattern)
./util_logger.py              - Logging utility (both use)
```

---

## CORE/ DIRECTORY (21 files)

### 🟢 EPOCH 4 - ACTIVE (2 files)
```
core/machine.py               - CoreMachine orchestrator (NEW)
core/models/stage.py          - Simple Stage model (NEW for Epoch 4)
```

### 🔵 INFRASTRUCTURE - ALWAYS ACTIVE (19 files)
```
core/__init__.py              - Package initialization
core/core_controller.py       - Minimal base controller
core/state_manager.py         - Database state management
core/orchestration_manager.py - Dynamic orchestration

core/logic/__init__.py
core/logic/calculations.py    - Business logic helpers
core/logic/transitions.py     - State transition logic

core/models/__init__.py
core/models/context.py        - Execution context models
core/models/enums.py          - Status enums (JobStatus, TaskStatus)
core/models/job.py            - Job data models
core/models/results.py        - Result models
core/models/task.py           - Task data models

core/schema/__init__.py
core/schema/deployer.py       - Schema deployment
core/schema/orchestration.py  - Orchestration schemas
core/schema/queue.py          - Queue schemas
core/schema/sql_generator.py  - SQL generation
core/schema/updates.py        - Update schemas
core/schema/workflow.py       - Workflow definition schemas
```

---

## JOBS/ DIRECTORY (4 files)

### 🟢 EPOCH 4 - ACTIVE (4 files)
```
jobs/__init__.py              - Package initialization
jobs/workflow.py              - Workflow ABC (base class)
jobs/registry.py              - Job registry pattern
jobs/hello_world.py           - HelloWorld workflow (declarative, 128 lines)
```

**Status**: All files are NEW for Epoch 4. No Epoch 3 files here.

---

## SERVICES/ DIRECTORY (6 files)

### 🟢 EPOCH 4 - ACTIVE (3 files)
```
services/__init__.py          - Package initialization
services/task.py              - Task ABC (base class)
services/registry.py          - Task registry pattern
services/hello_world.py       - HelloWorld task handlers (NEW, 163 lines)
```

### 🟡 SHARED - USED BY BOTH (3 files)
```
services/service_blob.py      - Blob service handlers (Epoch 3, still used)
services/service_hello_world.py - HelloWorld handlers (Epoch 3 factory pattern)
services/service_stac_setup.py  - STAC setup handlers (Epoch 3)
```

**Note**: `service_hello_world.py` (Epoch 3) vs `hello_world.py` (Epoch 4) - different patterns!

---

## INFRASTRUCTURE/ DIRECTORY (9 files)

### 🔵 INFRASTRUCTURE - ALWAYS ACTIVE (9 files)
```
infrastructure/__init__.py
infrastructure/base.py                - Base repository interface
infrastructure/blob.py                - Blob storage repository
infrastructure/factory.py             - Repository factory
infrastructure/interface_repository.py - Repository interfaces
infrastructure/jobs_tasks.py          - Jobs/Tasks repository
infrastructure/postgresql.py          - PostgreSQL repository
infrastructure/queue.py               - Queue storage repository
infrastructure/service_bus.py         - Service Bus repository
infrastructure/vault.py               - Key Vault repository
```

**Status**: All infrastructure is shared. Required by both epochs.

---

## TRIGGERS/ DIRECTORY (7 files)

### 🔵 INFRASTRUCTURE - ALWAYS ACTIVE (7 files)
```
triggers/__init__.py
triggers/db_query.py              - Database query endpoints
triggers/get_job_status.py        - Job status endpoint
triggers/health.py                - Health check endpoint
triggers/http_base.py             - HTTP trigger base class
triggers/poison_monitor.py        - Poison queue monitoring
triggers/schema_pydantic_deploy.py - Schema deployment endpoint
triggers/submit_job.py            - Job submission endpoint
```

**Status**: All HTTP triggers are shared infrastructure.

---

## UTILS/ DIRECTORY (3 files)

### 🔵 INFRASTRUCTURE - ALWAYS ACTIVE (3 files)
```
utils/__init__.py
utils/contract_validator.py   - Contract validation
utils/import_validator.py     - Import validation
```

**Status**: Utilities are shared infrastructure.

---

## SUMMARY BY CATEGORY

| Category | Count | Safe to Archive? |
|----------|-------|------------------|
| 🟢 **Epoch 4 - Active** | **13 files** | ❌ NO - Required |
| 🔴 **Epoch 3 - Deprecated** | **8 files** | ✅ YES - After dependency check |
| 🟡 **Shared - Both** | **14 files** | ⚠️ CAREFUL - Need migration |
| 🔵 **Infrastructure - Always Active** | **38 files** | ❌ NO - Core system |
| **TOTAL** | **73 files** | |

---

## FILES SAFE TO ARCHIVE (After Dependency Check)

### 🔴 Definitely Deprecated (8 files):
1. `controller_base.py` - Replaced by CoreMachine
2. `controller_container.py` - Epoch 3 only
3. `controller_hello_world.py` - Replaced by jobs/hello_world.py
4. `controller_service_bus.py` - Epoch 3 only
5. `controller_service_bus_container.py` - Epoch 3 only
6. `controller_service_bus_hello.py` - Replaced by CoreMachine
7. `controller_stac_setup.py` - Epoch 3 only
8. `debug_service_bus.py` - Standalone script

### ⚠️ Need Migration Plan (3 files):
1. `controller_factories.py` - Creates Epoch 3 controllers (used by function_app.py)
2. `registration.py` - Epoch 3 catalog pattern (used by function_app.py)
3. `task_factory.py` - Epoch 3 task handler factory (used by function_app.py)

---

## DEPENDENCY ANALYSIS

### Files That Import Deprecated Controllers

**function_app.py** imports:
```python
# Line 197-256: Epoch 3 controller imports
from controller_hello_world import HelloWorldController
from controller_container import SummarizeContainerController, ListContainerController
from controller_stac_setup import STACSetupController
from controller_service_bus_hello import ServiceBusHelloWorldController
from controller_service_bus_container import ServiceBusContainerController, ServiceBusExtractMetadataController
```

**Status**: These are registered in job_catalog but NOT used by Epoch 4 triggers!

### Files That Could Import Deprecated Controllers

**controller_factories.py**:
```python
# Creates controllers from job_catalog
# If we remove controllers, this will fail
```

**registration.py**:
```python
# Job/Task catalog registration
# Stores references to controller classes
```

---

## SAFE ARCHIVAL PLAN

### Phase 1: Verify No Runtime Usage
```bash
# Check if any Epoch 3 controllers are actually called
# In function_app.py, only Service Bus triggers matter for Epoch 4
# They use core_machine, not controllers
```

**Current State**:
- ✅ Service Bus triggers use `core_machine` (Epoch 4)
- ⚠️ Storage Queue triggers still use `JobFactory.create_controller()` (Epoch 3)
- ⚠️ HTTP triggers use `submit_job_trigger` which uses `JobFactory.create_controller()` (Epoch 3)

### Phase 2: Keep Epoch 3 Controllers for Now
**Reason**: Storage Queue triggers and HTTP job submission still use them

**Strategy**:
1. Mark headers as DEPRECATED (for clarity)
2. Leave files in place (functional)
3. Migrate Storage Queue triggers to CoreMachine (Phase 6)
4. Then archive safely

### Phase 3: Archive When Ready
```bash
mkdir -p archive/epoch3_controllers
mv controller_*.py archive/epoch3_controllers/
mv registration.py archive/epoch3_controllers/
mv task_factory.py archive/epoch3_controllers/
mv controller_factories.py archive/epoch3_controllers/
```

---

## RECOMMENDATIONS

### ✅ Safe to Mark as DEPRECATED Now (8 files)
Add header marker but **keep in place**:
```python
# EPOCH: 3 - DEPRECATED
# STATUS: Functional but replaced by Epoch 4 CoreMachine
# MIGRATION: Will be archived after Storage Queue triggers migrated
```

### ⚠️ Need Careful Migration (3 files)
Still used by function_app.py:
- `controller_factories.py`
- `registration.py`
- `task_factory.py`

### ✅ Mark as EPOCH 4 Active (13 files)
```python
# EPOCH: 4 - ACTIVE
# STATUS: Required for CoreMachine orchestration
```

### ✅ Mark as INFRASTRUCTURE (38 files)
```python
# EPOCH: INFRASTRUCTURE
# STATUS: Shared by all epochs, always active
```

---

## NEXT STEPS

1. ✅ Update headers in all files with EPOCH markers
2. ⚠️ Keep deprecated files in place (Storage Queue still needs them)
3. 📋 Phase 6: Migrate Storage Queue triggers to CoreMachine
4. 📦 Phase 7: Archive Epoch 3 controllers safely

**Current Safety**: All files can stay in place. No breakage risk.
