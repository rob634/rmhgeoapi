# Epoch 4 Folder Structure & Naming Conventions

**Date**: 30 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Complete guide to Epoch 4 project organization
**Status**: Phase 2 Complete - Foundation Ready

---

## 📁 Complete Folder Structure

```
rmhgeoapi/
│
├── 🎯 ENTRY POINTS (2 files)
│   ├── function_app.py              # Azure Functions entry point
│   └── config.py                    # Pydantic configuration
│
├── 🏗️ CORE ARCHITECTURE (core/ - 19 files)
│   ├── core_controller.py           # Abstract base controller (~400 lines)
│   ├── state_manager.py             # Database operations with advisory locks (~540 lines)
│   ├── orchestration_manager.py     # Dynamic task creation (~400 lines)
│   ├── machine.py                   # 🆕 FUTURE - CoreMachine universal orchestrator
│   │
│   ├── 📦 models/ (6 files - Pydantic data models)
│   │   ├── __init__.py
│   │   ├── enums.py                 # JobStatus, TaskStatus
│   │   ├── job.py                   # JobRecord, JobExecutionContext
│   │   ├── task.py                  # TaskRecord, TaskDefinition
│   │   ├── results.py               # TaskResult, StageResultContract
│   │   └── context.py               # StageExecutionContext
│   │
│   ├── 📦 schema/ (7 files - Workflow & orchestration schemas)
│   │   ├── __init__.py
│   │   ├── deployer.py              # Database schema deployment
│   │   ├── sql_generator.py         # SQL DDL generation with advisory locks
│   │   ├── workflow.py              # Workflow definitions
│   │   ├── orchestration.py         # Orchestration patterns
│   │   ├── queue.py                 # Queue message schemas
│   │   └── updates.py               # Update models
│   │
│   └── 📦 logic/ (3 files - Business logic utilities)
│       ├── __init__.py
│       ├── calculations.py          # Stage advancement calculations
│       └── transitions.py           # State transition validation
│
├── 🏭 INFRASTRUCTURE (infra/ - 13 files) ✅ RENAMED FROM repositories/
│   ├── __init__.py                  # Lazy loading for Azure Functions
│   ├── postgresql.py                # PostgreSQL implementation (~1,800 lines)
│   ├── blob.py                      # Azure Blob Storage (~800 lines)
│   ├── queue.py                     # Queue Storage (~450 lines)
│   ├── service_bus.py               # Service Bus with batching (~1,000 lines)
│   ├── vault.py                     # Azure Key Vault (~350 lines)
│   ├── jobs_tasks.py                # Job/Task business logic (~900 lines)
│   ├── factory.py                   # Repository factory (~400 lines)
│   ├── base.py                      # Common patterns (~650 lines)
│   └── interface_repository.py      # Repository interfaces (~350 lines)
│
├── 💼 JOBS (jobs/ - FUTURE) 🆕 EPOCH 4
│   ├── __init__.py                  # Auto-registration
│   ├── registry.py                  # Job registry with decorator
│   ├── hello_world.py               # 🆕 HelloWorld job (~50 lines)
│   ├── container_list.py            # 🆕 Container list job (~80 lines)
│   └── process_raster.py            # 🆕 Raster processing job (~100 lines)
│
├── ⚙️ SERVICES (services/ - 3+ files)
│   ├── __init__.py
│   ├── registry.py                  # 🆕 Handler registry
│   ├── service_hello_world.py       # Hello World handlers (~200 lines)
│   ├── service_blob.py              # Blob storage handlers (~300 lines)
│   ├── service_stac_setup.py        # STAC setup handlers (~250 lines)
│   └── hello_world.py               # 🆕 New declarative handlers (~50 lines)
│
├── 🎛️ LEGACY CONTROLLERS (Root level - TO BE ARCHIVED)
│   ├── controller_base.py           # ⚠️ God Class (2,290 lines) - ARCHIVE
│   ├── controller_hello_world.py    # ⚠️ Queue Storage version - ARCHIVE
│   ├── controller_container.py      # ⚠️ Queue Storage version - ARCHIVE
│   ├── controller_stac_setup.py     # ⚠️ Needs refactor - ARCHIVE
│   ├── controller_service_bus_hello.py  # ✅ Reference for CoreMachine extraction
│   ├── controller_service_bus_container.py  # 🔧 Stub
│   ├── controller_factories.py      # ⚠️ Replaced by jobs/registry.py - ARCHIVE
│   └── registration.py              # ⚠️ Replaced by new registries - ARCHIVE
│
├── 📜 ROOT SCHEMAS (Root level - MIXED STATUS)
│   ├── schema_base.py               # ⚠️ Replaced by core/models/ - ARCHIVE
│   ├── schema_workflow.py           # ⚠️ Replaced by core/schema/workflow.py - ARCHIVE
│   ├── schema_orchestration.py      # ⚠️ Replaced by core/schema/orchestration.py - ARCHIVE
│   ├── schema_queue.py              # ⚠️ Replaced by core/schema/queue.py - ARCHIVE
│   ├── schema_updates.py            # ⚠️ Replaced by core/schema/updates.py - ARCHIVE
│   ├── schema_file_item.py          # ✅ Still in use
│   ├── schema_geospatial.py         # ✅ Still in use
│   ├── schema_postgis.py            # ✅ Still in use
│   └── schema_stac.py               # ✅ Still in use
│
├── 🚀 TRIGGERS (triggers/ - 7 files)
│   ├── __init__.py
│   ├── health.py                    # Health check endpoint
│   ├── submit_job.py                # Job submission HTTP trigger
│   ├── get_job_status.py            # Job status query
│   ├── db_query.py                  # Database query endpoints
│   ├── schema_pydantic_deploy.py    # Schema deployment
│   ├── poison_monitor.py            # Poison queue monitoring
│   └── http_base.py                 # Base HTTP utilities
│
├── 🔧 UTILITIES (utils/ - 3 files)
│   ├── __init__.py
│   ├── contract_validator.py        # Runtime type enforcement
│   └── import_validator.py          # Import validation
│
├── 🗂️ TASK PROCESSING (Root level - 2 files)
│   ├── task_factory.py              # Task handler factory with lineage
│   └── task_handlers.py             # Task processor implementations
│
├── 📦 ARCHIVE (archive/ - Epoch 3 preservation) ✅ CREATED PHASE 1
│   ├── ARCHIVE_README.md            # Complete archive documentation
│   ├── epoch3_controllers/          # Legacy controllers (future)
│   │   └── README.md
│   ├── epoch3_schemas/              # Legacy schemas (future)
│   │   └── README.md
│   └── epoch3_docs/                 # Superseded documentation
│       └── README.md
│
├── 📚 DOCUMENTATION (Root level)
│   ├── CLAUDE.md                    # 🎯 PRIMARY - Entry point
│   ├── epoch4_framework.md          # Epoch 4 architecture vision
│   ├── EPOCH4_IMPLEMENTATION.md     # Detailed task list (32 tasks)
│   ├── EPOCH3_INVENTORY.md          # Complete code inventory
│   ├── EPOCH4_PHASE1_SUMMARY.md     # Phase 1 completion summary
│   ├── EPOCH4_PHASE2_SUMMARY.md     # Phase 2 completion summary
│   ├── epoch3.md                    # Epoch 3 reference (renamed from epoch4.md)
│   ├── core_machine.md              # CoreMachine architectural vision
│   ├── CORE_SCHEMA_MIGRATION.md     # Schema migration details (30 SEP)
│   └── LOCAL_TESTING_README.md      # Local development guide
│
├── 📚 CLAUDE DOCS (docs_claude/ - 7 files)
│   ├── CLAUDE_CONTEXT.md            # Primary context for Claude
│   ├── TODO_ACTIVE.md               # Current active tasks
│   ├── HISTORY.md                   # Project history (11 SEP - present)
│   ├── OLDER_HISTORY.md             # Project history (before 11 SEP)
│   ├── ARCHITECTURE_REFERENCE.md    # Deep technical specs
│   ├── DEPLOYMENT_GUIDE.md          # Azure deployment procedures
│   └── FILE_CATALOG.md              # File lookup reference
│
├── 📂 ARCHIVED DOCS (docs/archive/ - 16 files)
│   ├── README.md                    # Archive catalog
│   ├── service_bus/                 # Service Bus iterations (25-26 SEP)
│   ├── basecontroller/              # God Class refactoring attempts
│   ├── analysis/                    # Debugging investigations
│   └── obsolete/                    # Superseded documentation
│
├── 🧪 TESTS (test/ - 10+ files)
│   ├── test_local_integration.py
│   ├── test_deployment_readiness.py
│   └── (other test files)
│
├── 🔬 LOCAL DEVELOPMENT (local/ - Test scripts)
│   ├── test_service_bus_fix.py
│   ├── test_stac_setup_local.py
│   └── (other local test scripts)
│
├── 📊 SQL SCRIPTS (sql/ - Future)
│   └── (SQL migration scripts if needed)
│
└── ⚙️ CONFIGURATION FILES (Root level)
    ├── host.json                    # Azure Functions runtime config
    ├── requirements.txt             # Python dependencies
    ├── .funcignore                  # Azure Functions ignore patterns
    ├── local.settings.json          # Local development settings
    └── exceptions.py                # Error hierarchy
```

---

## 🏷️ Naming Conventions

### File Naming Patterns

#### Core Architecture Files
```
core/
├── <component_name>.py              # Component implementation
│   Examples: state_manager.py, orchestration_manager.py
│
├── models/<domain>.py               # Pydantic models
│   Examples: job.py, task.py, results.py
│
├── schema/<type>.py                 # Schema definitions
│   Examples: workflow.py, orchestration.py, queue.py
│
└── logic/<function>.py              # Business logic utilities
    Examples: calculations.py, transitions.py
```

#### Infrastructure Files
```
infra/
├── <service>.py                     # Service implementation
│   Examples: postgresql.py, blob.py, queue.py, service_bus.py
│
├── <pattern>.py                     # Pattern implementation
│   Examples: factory.py, base.py
│
└── interface_repository.py          # Interface definitions
```

#### Job Declarations (Epoch 4)
```
jobs/
├── <job_type>.py                    # Declarative job definition
│   Examples: hello_world.py, container_list.py, process_raster.py
│   Pattern: Underscore-separated, matches job_type string
│
└── registry.py                      # Job registration system
```

#### Service Handlers
```
services/
├── service_<domain>.py              # Old pattern (Epoch 3)
│   Examples: service_hello_world.py, service_blob.py
│
├── <domain>.py                      # New pattern (Epoch 4)
│   Examples: hello_world.py, blob.py, raster.py
│   Pattern: Simple domain name
│
└── registry.py                      # Handler registration system
```

#### Legacy Controllers (To Be Archived)
```
controller_<name>.py                 # Legacy pattern
Examples: controller_base.py, controller_hello_world.py
Status: Being replaced by jobs/ + CoreMachine
```

#### Root Schemas
```
schema_<type>.py                     # Legacy pattern (root level)
Examples: schema_base.py, schema_workflow.py
Status: Replaced by core/models/ and core/schema/

schema_<domain>.py                   # Domain-specific (still in use)
Examples: schema_geospatial.py, schema_postgis.py, schema_stac.py
Status: Keep - domain-specific models
```

#### Triggers
```
triggers/
└── <endpoint_name>.py               # HTTP endpoint implementation
    Examples: health.py, submit_job.py, get_job_status.py
```

#### Utilities
```
utils/
└── <utility_name>.py                # Utility implementation
    Examples: contract_validator.py, import_validator.py

util_<name>.py                       # Legacy pattern (root level)
Examples: util_logger.py
Status: Gradually moving to utils/ folder
```

---

## 📋 Class Naming Conventions

### Pythonic ABC Pattern (Epoch 4)

#### Abstract Base Classes
```python
# Simple, clean noun (no prefix/suffix)
class Task(ABC): ...                 # Not BaseTask, ITask, or TaskBase
class Workflow(ABC): ...             # Not BaseWorkflow or IWorkflow
class MessageQueue(ABC): ...         # Not IMessageQueue or BaseMessageQueue
```

#### Concrete Implementations
```python
# Descriptive compound name
class ValidateRasterTask(Task): ...
class ServiceBusQueue(MessageQueue): ...
class HelloWorldWorkflow(Workflow): ...
class PostgreSQLRepository(Repository): ...
```

### Repository Pattern
```python
# Interface (if using separate interfaces)
class IJobRepository(ABC): ...

# Implementation
class PostgreSQLRepository: ...       # Service-specific
class JobRepository: ...              # Domain-specific wrapper
```

### Pydantic Models
```python
# Descriptive noun ending in purpose
class JobRecord(BaseModel): ...       # Database record
class JobExecutionContext(BaseModel): ...  # Execution context
class TaskDefinition(BaseModel): ...  # Task definition
class StageResultContract(BaseModel): ...  # Result contract
```

### Controllers (Epoch 3 - Being Replaced)
```python
# Descriptive + Controller suffix
class HelloWorldController(BaseController): ...
class ServiceBusHelloWorldController(CoreController): ...

# Epoch 4 Pattern (New)
class HelloWorldJob(JobDeclaration): ...  # Declarative, not controller
```

---

## 📂 Folder Naming Conventions

### Plural vs Singular

#### Plural Folders (Collections)
```
models/          # Multiple models live here
schemas/         # Multiple schemas
triggers/        # Multiple trigger endpoints
utils/           # Multiple utilities
jobs/            # Multiple job declarations
services/        # Multiple service handlers
```

#### Singular Folders (Concepts)
```
core/            # Core architecture (concept, not collection)
infra/           # Infrastructure (concept)
archive/         # Archive (concept)
```

### Special Folders

#### Prefixed Folders
```
docs_claude/     # Claude-specific documentation
epoch3_*/        # Epoch-specific archives
```

#### Temporal Folders
```
local/           # Local development only
test/            # Test files only
.venv/           # Virtual environment (ignored)
__pycache__/     # Python cache (ignored)
```

---

## 🎯 Import Path Patterns

### Epoch 4 Standard Imports

```python
# Core architecture
from core import CoreController, StateManager, OrchestrationManager
from core.models import JobRecord, TaskRecord, JobStatus, TaskStatus
from core.schema import WorkflowDefinition, OrchestrationInstruction
from core.logic import calculate_stage_completion

# Infrastructure
from infra import RepositoryFactory, PostgreSQLRepository
from infra.factory import create_repositories

# Jobs (Epoch 4)
from jobs.registry import register_job, get_job_declaration
from jobs.hello_world import HelloWorldJob

# Services (Epoch 4)
from services.registry import register_handler, get_handler
from services.hello_world import handle_greeting, handle_reply

# Configuration & utilities
from config import AppConfig
from exceptions import BusinessLogicError, ContractViolationError
from utils.contract_validator import enforce_contract
```

### Legacy Imports (Being Replaced)

```python
# ⚠️ OLD - Being replaced
from repositories import RepositoryFactory          # → from infra import
from schema_base import JobRecord, TaskRecord      # → from core.models import
from schema_workflow import WorkflowDefinition     # → from core.schema import
from controller_base import BaseController         # → Delete (God Class)
```

---

## 🗂️ File Organization Principles

### 1. Separation of Concerns

```
core/           → Framework (how we orchestrate)
jobs/           → Declarations (what jobs do)
services/       → Business logic (how tasks execute)
infra/          → Infrastructure (how we access data)
triggers/       → Entry points (how we receive requests)
```

### 2. Composition Over Inheritance

```python
# ❌ BAD: God Class inheritance
class MyController(BaseController):  # Inherits 2,290 lines!
    pass

# ✅ GOOD: Composition
class MyJob(JobDeclaration):
    def __init__(self):
        self.state_manager = StateManager()      # Injected
        self.orchestrator = OrchestrationManager()  # Injected
```

### 3. Single Responsibility

```
One file = One clear purpose
- state_manager.py: ONLY state management
- orchestration_manager.py: ONLY task orchestration
- hello_world.py: ONLY HelloWorld job declaration
```

### 4. Domain-Driven Design

```
jobs/           → Job domain (workflow declarations)
services/       → Service domain (business logic)
infra/          → Infrastructure domain (data access)
core/models/    → Data domain (models)
core/schema/    → Schema domain (validation)
```

---

## 📊 File Size Guidelines

### Target Sizes (Epoch 4)

| File Type | Target Lines | Max Lines | Examples |
|-----------|-------------|-----------|----------|
| Job Declaration | 50-100 | 150 | jobs/hello_world.py |
| Service Handler | 50-150 | 300 | services/hello_world.py |
| CoreMachine | 300-400 | 500 | core/machine.py |
| StateManager | 400-600 | 800 | core/state_manager.py |
| Repository | 500-1,000 | 2,000 | infra/postgresql.py |
| Pydantic Model | 50-200 | 300 | core/models/job.py |

### Warning Signs

| Lines | Status | Action |
|-------|--------|--------|
| < 50 | ✅ Excellent | Concise, focused |
| 50-500 | ✅ Good | Single responsibility |
| 500-1,000 | ⚠️ Warning | Consider splitting |
| 1,000-2,000 | ⚠️ High | Refactor if possible |
| > 2,000 | 🚨 God Class | MUST refactor |

**Epoch 3 Example**:
- `controller_base.py`: 2,290 lines → 🚨 God Class (being replaced)

**Epoch 4 Target**:
- `jobs/hello_world.py`: ~50 lines → ✅ Perfect
- `services/hello_world.py`: ~50 lines → ✅ Perfect
- `core/machine.py`: ~300 lines → ✅ Good (shared by all jobs)

---

## 🎨 Code Organization Within Files

### Standard File Structure

```python
# ============================================================================
# CLAUDE CONTEXT - FILE TYPE
# ============================================================================
# PURPOSE: One sentence description
# EXPORTS: Main classes/functions exposed
# ... (other metadata)
# ============================================================================

"""
Module docstring with detailed description.
"""

# ========================================================================
# IMPORTS - Categorized
# ========================================================================

# Standard library
import os
from typing import Dict, Any

# Third-party libraries
from pydantic import BaseModel

# Application modules - Core
from core.models import JobRecord

# Application modules - Infrastructure
from infra import RepositoryFactory

# ========================================================================
# CONSTANTS
# ========================================================================

DEFAULT_TIMEOUT = 30

# ========================================================================
# CLASSES
# ========================================================================

class MyClass:
    """Class docstring."""
    pass

# ========================================================================
# FUNCTIONS
# ========================================================================

def my_function():
    """Function docstring."""
    pass
```

---

## 🚀 Migration Status Summary

### Completed ✅
- [x] Phase 1: Archive structure created
- [x] Phase 2: `repositories/` → `infra/` migration
- [x] Core architecture organized (`core/models/`, `core/schema/`, `core/logic/`)

### In Progress 🔄
- [ ] Phase 3: CoreMachine creation (`core/machine.py`)
- [ ] Phase 3: Job registry system (`jobs/registry.py`)
- [ ] Phase 3: Service handler registry (`services/registry.py`)

### Future 🎯
- [ ] Phase 4: HelloWorld migration to declarative pattern
- [ ] Phase 5: Deployment & validation
- [ ] Phase 6: Legacy code archival
- [ ] Phase 7: Additional job migrations

---

## 📝 Quick Reference

### Finding Files by Purpose

**Need to understand orchestration?**
→ `core/state_manager.py`, `core/orchestration_manager.py`

**Need to add a new job?**
→ Create `jobs/<job_type>.py` (~50 lines)

**Need to add business logic?**
→ Create `services/<domain>.py` (~50-150 lines)

**Need to access database/storage?**
→ Use `infra/postgresql.py`, `infra/blob.py`, etc.

**Need to understand models?**
→ `core/models/` (enums, job, task, results, context)

**Need to see workflow definitions?**
→ `core/schema/workflow.py`

**Need to understand legacy code?**
→ `archive/ARCHIVE_README.md`

---

**Last Updated**: 30 SEP 2025
**Status**: Phase 2 Complete - Infrastructure Migrated
**Next**: Phase 3 - CoreMachine Creation
