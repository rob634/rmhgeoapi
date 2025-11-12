# Epoch 4 Structure Alignment

**Date**: 30 SEP 2025
**Purpose**: Map current structure to epoch4_framework.md target structure
**Status**: Phase 2 Complete - Alignment needed for Phase 3

---

## 🎯 The Key Insight

**epoch4_framework.md uses a different folder structure than we currently have!**

We need to align our current structure with the framework document's vision.

---

## 📊 Current vs Target Structure

### Current Structure (What We Have Now)

```
rmhgeoapi/
├── core/                          # Framework components
│   ├── models/                    # Pydantic models
│   ├── schema/                    # Workflow schemas
│   └── logic/                     # Business logic
├── infra/                         # Infrastructure (renamed from repositories/)
├── jobs/                          # 🆕 Empty - to be created
├── services/                      # Partially done
├── triggers/                      # HTTP endpoints
└── utils/                         # Utilities
```

### Target Structure (From epoch4_framework.md)

```
project/
├── pipeline/                      # Core Framework (domain-agnostic)
│   ├── orchestration/             # Orchestrator, stage_manager
│   ├── execution/                 # Executor, task_registry
│   ├── state/                     # StateManager, models, repository
│   └── messaging/                 # MessageQueue ABC + implementations
│
├── workflows/                     # Job Definitions (like our jobs/)
│   ├── workflow.py                # ABC: Workflow
│   ├── job_registry.py            # JOB_REGISTRY
│   └── hello_world.py             # HelloWorldWorkflow
│
├── tasks/                         # Task Implementations (bridge layer)
│   ├── task.py                    # ABC: Task
│   └── hello/                     # Task implementations by domain
│
├── domain/                        # Geospatial Operations
│   ├── raster/                    # Raster operations
│   └── vector/                    # Vector operations
│
├── infrastructure/                # Cross-cutting (like our infra/)
│   ├── logging.py
│   ├── config.py
│   └── exceptions.py
│
└── functions/                     # Azure Function entry points
    ├── http_triggers/
    ├── queue_triggers/
    └── timer_triggers/
```

---

## 🔄 Mapping: Current → Target

### Option A: Rename to Match Framework (Breaking Change)

```
Current              →  Target (Framework)
─────────────────────────────────────────────
core/                →  pipeline/
├── models/          →  pipeline/state/models.py
├── schema/          →  pipeline/state/ (some files)
├── logic/           →  pipeline/state/ (some files)
├── state_manager.py →  pipeline/state/state_manager.py
├── orchestration_manager.py → pipeline/orchestration/
└── core_controller.py → pipeline/orchestration/orchestrator.py

infra/               →  infrastructure/ (messaging split out)
├── postgresql.py    →  pipeline/state/repository.py
├── queue.py         →  pipeline/messaging/storage_queue.py
├── service_bus.py   →  pipeline/messaging/service_bus.py
├── blob.py          →  infrastructure/storage.py
└── (others)         →  infrastructure/

jobs/                →  workflows/
services/            →  tasks/ (rename + restructure)
triggers/            →  functions/
utils/               →  infrastructure/
```

### Option B: Keep Current Structure (Minimal Change)

```
Current              →  Keep As-Is (Epoch 4 Lite)
─────────────────────────────────────────────
core/                ✅ Keep (maps to pipeline/)
infra/               ✅ Keep (maps to infrastructure/ + pipeline/messaging)
jobs/                ✅ Keep (maps to workflows/)
services/            ✅ Keep (maps to tasks/)
triggers/            ✅ Keep (maps to functions/)
utils/               ✅ Keep (part of infrastructure/)
```

---

## 💡 Recommendation: **Option B with Clarifications**

**Rationale:**
1. **Current structure works** - 97.9% of code already organized
2. **Minimal disruption** - Don't break what's working
3. **Clear mappings** - Document how current maps to framework
4. **Progressive alignment** - Can refine over time

**Key Principle:** The framework document describes the **conceptual architecture**, not necessarily the exact folder names.

---

## 📋 Aligned Folder Structure (Recommended)

### What We'll Build (Keeping Current Naming)

```
rmhgeoapi/
│
├── 🏗️ CORE (pipeline/ equivalent)
│   ├── core/                      # Framework orchestration
│   │   ├── machine.py             # 🆕 Orchestrator (CoreMachine)
│   │   ├── state_manager.py       # StateManager (atomic operations)
│   │   ├── orchestration_manager.py # Stage advancement logic
│   │   ├── models/                # Pydantic: Job, Task, Stage
│   │   ├── schema/                # Workflow definitions
│   │   └── logic/                 # Calculations, transitions
│   │
│   └── infra/                     # Infrastructure + Messaging
│       ├── postgresql.py          # Repository (pipeline/state/repository)
│       ├── queue.py               # StorageQueue (pipeline/messaging)
│       ├── service_bus.py         # ServiceBusQueue (pipeline/messaging)
│       └── (others)               # Infrastructure concerns
│
├── 💼 WORKFLOWS (workflows/ equivalent)
│   └── jobs/                      # Job Definitions
│       ├── registry.py            # JOB_REGISTRY: job_type → Job class
│       ├── workflow.py            # 🆕 ABC: Workflow
│       └── hello_world.py         # 🆕 HelloWorldWorkflow
│
├── ⚙️ TASKS (tasks/ equivalent)
│   └── services/                  # Task Implementations
│       ├── task.py                # 🆕 ABC: Task
│       ├── registry.py            # TASK_REGISTRY: task_type → Task class
│       └── hello_world.py         # 🆕 Task handlers
│
├── 🌍 DOMAIN (geospatial operations)
│   └── domain/                    # 🆕 Create for geospatial ops
│       ├── raster/
│       └── vector/
│
├── 🚀 FUNCTIONS (functions/ equivalent)
│   ├── function_app.py            # Entry point
│   └── triggers/                  # HTTP, Queue, Timer triggers
│
└── 🔧 INFRASTRUCTURE (cross-cutting)
    ├── config.py
    ├── exceptions.py
    └── utils/
```

---

## 🎯 Key Alignments

### 1. pipeline/ → core/ + infra/

**Framework Concept:**
- `pipeline/orchestration/` → `core/machine.py`, `core/orchestration_manager.py`
- `pipeline/execution/` → Task execution logic in services/
- `pipeline/state/` → `core/state_manager.py`, `core/models/`, `infra/postgresql.py`
- `pipeline/messaging/` → `infra/queue.py`, `infra/service_bus.py`

**Why This Works:**
- `core/` contains orchestration framework
- `infra/` contains messaging + data access
- Same separation, different naming

### 2. workflows/ → jobs/

**Framework Concept:**
- `workflows/workflow.py` → `jobs/workflow.py` (ABC)
- `workflows/job_registry.py` → `jobs/registry.py`
- `workflows/hello_world.py` → `jobs/hello_world.py`

**Why This Works:**
- "jobs" and "workflows" are synonymous here
- Same purpose: declare WHAT jobs do

### 3. tasks/ → services/

**Framework Concept:**
- `tasks/task.py` → `services/task.py` (ABC)
- `tasks/hello/greet.py` → `services/hello_world.py` (handler)

**Why This Works:**
- Tasks ARE services that execute business logic
- "services" is more familiar to Python developers
- Same bridge between framework and domain

### 4. domain/ → domain/ ✅

**Framework Concept:**
- `domain/raster/operations.py` → Same structure
- `domain/vector/operations.py` → Same structure

**Why This Works:**
- Already aligned!
- Create `domain/` folder as-is from framework

### 5. infrastructure/ → config.py + utils/ + exceptions.py

**Framework Concept:**
- `infrastructure/logging.py` → `utils/import_validator.py` (has logging)
- `infrastructure/config.py` → `config.py` (root level)
- `infrastructure/exceptions.py` → `exceptions.py` (root level)

**Why This Works:**
- Cross-cutting concerns already at root level
- Functionally equivalent

### 6. functions/ → function_app.py + triggers/

**Framework Concept:**
- `functions/http_triggers/` → `triggers/` (our folder)
- `functions/queue_triggers/` → Queue triggers in `function_app.py`
- `functions/timer_triggers/` → Timer triggers in `function_app.py`

**Why This Works:**
- Azure Functions pattern: one `function_app.py` + trigger functions
- Functionally equivalent

---

## 📝 Phase 3 Adjustments

### Files to Create (Aligned with Framework)

#### 1. Core Orchestration
```
core/
└── machine.py                     # Orchestrator class (framework's pipeline/orchestration/orchestrator.py)
```

#### 2. Workflow System
```
jobs/
├── workflow.py                    # ABC: Workflow (framework's workflows/workflow.py)
├── registry.py                    # JOB_REGISTRY (framework's workflows/job_registry.py)
└── hello_world.py                 # HelloWorldWorkflow (framework's workflows/hello_world.py)
```

#### 3. Task System
```
services/
├── task.py                        # ABC: Task (framework's tasks/task.py)
├── registry.py                    # TASK_REGISTRY (framework's tasks/task_registry.py)
└── hello_world.py                 # Task handlers (framework's tasks/hello/greet.py, etc.)
```

#### 4. Domain Layer (Future)
```
domain/
├── raster/
│   ├── operations.py              # reproject_raster(), create_cog()
│   └── validation.py              # validate_crs()
└── vector/
    ├── operations.py              # buffer(), simplify()
    └── validation.py              # validate_geometry()
```

---

## 🎨 Naming Convention Alignment

### Framework Document Says:

**Folders:** Plural nouns
- `workflows/` ✅ Matches our `jobs/` (both plural)
- `tasks/` ✅ Matches our `services/` (both plural)

**Files:** Singular nouns
- `orchestrator.py` ✅ Matches our `machine.py` (both singular concepts)
- `workflow.py` ✅ Our `workflow.py` (ABC)
- `task.py` ✅ Our `task.py` (ABC)

**Classes:** Match file names
- `orchestrator.py` → `class Orchestrator` ✅ We'll use `class CoreMachine` (but same pattern)
- `workflow.py` → `class Workflow` ✅ Same
- `task.py` → `class Task` ✅ Same

---

## ✅ What This Means for Phase 3

### Files to Create (Framework-Aligned):

1. **core/machine.py** (~300-400 lines)
   - Framework equivalent: `pipeline/orchestration/orchestrator.py`
   - Class: `CoreMachine` (or `Orchestrator` to match framework exactly)

2. **jobs/workflow.py** (~100 lines)
   - Framework equivalent: `workflows/workflow.py`
   - Class: `Workflow` (ABC)

3. **jobs/registry.py** (~100 lines)
   - Framework equivalent: `workflows/job_registry.py`
   - Exports: `JOB_REGISTRY`, `register_job()`, `get_workflow()`

4. **jobs/hello_world.py** (~50 lines)
   - Framework equivalent: `workflows/hello_world.py`
   - Class: `HelloWorldWorkflow(Workflow)`

5. **services/task.py** (~100 lines)
   - Framework equivalent: `tasks/task.py`
   - Class: `Task` (ABC)

6. **services/registry.py** (~100 lines)
   - Framework equivalent: `pipeline/execution/task_registry.py`
   - Exports: `TASK_REGISTRY`, `register_task()`, `get_task()`

7. **services/hello_world.py** (~50 lines)
   - Framework equivalent: `tasks/hello/greet.py`, `tasks/hello/process.py`
   - Functions: `greet_task()`, `process_greeting_task()`, `finalize_hello_task()`

---

## 🎯 Import Pattern Alignment

### Framework Document Pattern:
```python
# From framework document
from workflows.workflow import Workflow
from pipeline.state.models import Stage
from tasks.task import Task
```

### Our Aligned Pattern:
```python
# Our equivalent
from jobs.workflow import Workflow           # Same concept
from core.models import Stage                 # Same concept (pipeline/state/models)
from services.task import Task                # Same concept
```

**Result:** Conceptually identical, just different folder names!

---

## 📊 Summary Table

| Framework Document | Our Implementation | Status |
|-------------------|-------------------|--------|
| `pipeline/orchestration/orchestrator.py` | `core/machine.py` | 🆕 Create Phase 3 |
| `pipeline/state/state_manager.py` | `core/state_manager.py` | ✅ Exists |
| `pipeline/state/models.py` | `core/models/` | ✅ Exists |
| `pipeline/state/repository.py` | `infra/postgresql.py` | ✅ Exists |
| `pipeline/messaging/service_bus.py` | `infra/service_bus.py` | ✅ Exists |
| `workflows/workflow.py` | `jobs/workflow.py` | 🆕 Create Phase 3 |
| `workflows/job_registry.py` | `jobs/registry.py` | 🆕 Create Phase 3 |
| `workflows/hello_world.py` | `jobs/hello_world.py` | 🆕 Create Phase 3 |
| `tasks/task.py` | `services/task.py` | 🆕 Create Phase 3 |
| `tasks/hello/` | `services/hello_world.py` | 🆕 Create Phase 3 |
| `domain/raster/` | `domain/raster/` | 🎯 Future |
| `infrastructure/config.py` | `config.py` | ✅ Exists (root) |
| `functions/http_triggers/` | `triggers/` | ✅ Exists |

---

## ✅ Action Items for Phase 3

### Aligned with Framework Document:

1. **Create Orchestrator** (`core/machine.py`)
   - Class name: `CoreMachine` or `Orchestrator` (decide)
   - Matches framework's `pipeline/orchestration/orchestrator.py`

2. **Create Workflow ABC** (`jobs/workflow.py`)
   - Class: `Workflow(ABC)`
   - Method: `define_stages() -> list[Stage]`
   - Matches framework's `workflows/workflow.py`

3. **Create Job Registry** (`jobs/registry.py`)
   - `JOB_REGISTRY: Dict[str, Type[Workflow]]`
   - `@register_job` decorator
   - Matches framework's `workflows/job_registry.py`

4. **Create HelloWorld Workflow** (`jobs/hello_world.py`)
   - Class: `HelloWorldWorkflow(Workflow)`
   - Exactly as shown in framework document
   - Matches framework's `workflows/hello_world.py`

5. **Create Task ABC** (`services/task.py`)
   - Class: `Task(ABC)`
   - Method: `execute(params: dict) -> dict`
   - Matches framework's `tasks/task.py`

6. **Create Task Registry** (`services/registry.py`)
   - `TASK_REGISTRY: Dict[str, Type[Task]]`
   - `@register_task` decorator
   - Matches framework's `pipeline/execution/task_registry.py`

7. **Create HelloWorld Tasks** (`services/hello_world.py`)
   - Task handlers for greet, process, finalize
   - Matches framework's `tasks/hello/` folder

---

## 💡 Final Recommendation

**Use framework document naming for NEW files we create:**

- ✅ `Workflow` (not `JobDeclaration`)
- ✅ `Task` (simple ABC name)
- ✅ `Orchestrator` or `CoreMachine` (decide which)
- ✅ `HelloWorldWorkflow(Workflow)`

**Keep current folder names:**
- ✅ `core/` (conceptually = `pipeline/`)
- ✅ `jobs/` (conceptually = `workflows/`)
- ✅ `services/` (conceptually = `tasks/`)
- ✅ `infra/` (conceptually = `infrastructure/` + `pipeline/messaging/`)

**Result:** Framework-aligned implementation with practical folder names!

---

**Created**: 30 SEP 2025
**Status**: Ready for Phase 3 with framework alignment
**Next**: Create files using framework document as blueprint
