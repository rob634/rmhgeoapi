# Remove DAG Worker Dead Code Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Archive the `dag_worker/` module and remove all DAG stub references from `docker_health/` and `docker_service.py`.

**Architecture:** The DAG worker was a Epoch 5 prototype (29 JAN 2026) that was never integrated. It was always disabled — the `DAGWorkerSubsystem` stub always returns `{"status": "disabled"}` because `dag_processor` is always `None`. Removing it shrinks the health response `subsystems` dict by one key (`dag_worker`), which is safe since the key was never used by any consumer. No tests, no queue, no env vars were ever wired up.

**Tech Stack:** Python, git mv (for archiving)

---

## What Is Being Removed

| Location | What | Why |
|---|---|---|
| `dag_worker/` (8 files) | Entire module | Never imported, never activated |
| `docker_health/dag_worker.py` | Stub subsystem | Pure stub, always returns `disabled` |
| `docker_health/__init__.py` | DAG param + import + subsystem entry | Wires the stub into `get_all_subsystems()` |
| `docker_service.py` | `dag_processor=None` kwarg + banner/docstring refs | Passes the stub through to health endpoint |
| Comments in `base.py`, `classic_worker.py` | DAG mentions in docstrings | Stale forward-references to removed feature |

---

### Task 1: Archive `dag_worker/` module

**Files:**
- Move: `dag_worker/` → `docs/archive/dag_worker/`

**Step 1: Create archive destination and move folder**

```bash
mkdir -p docs/archive
git mv dag_worker docs/archive/dag_worker
```

**Step 2: Verify**

```bash
ls docs/archive/dag_worker/
# Expected: __init__.py  config.py  contracts.py  executor.py  handler_registry.py  listener.py  README.md  reporter.py
```

**Step 3: Confirm nothing imports it**

```bash
grep -r "from dag_worker\|import dag_worker" . --include="*.py" | grep -v "docs/archive"
# Expected: no output
```

**Step 4: Commit**

```bash
git add -A
git commit -m "archive: move dag_worker/ prototype to docs/archive"
```

---

### Task 2: Delete `docker_health/dag_worker.py`

**Files:**
- Delete: `docker_health/dag_worker.py`

This is the `DAGWorkerSubsystem` stub class. It is imported only by `docker_health/__init__.py`, which we fix in Task 3.

**Step 1: Delete the file**

```bash
git rm docker_health/dag_worker.py
```

**Step 2: Commit (after Task 3 — see below)**

Hold this commit until Task 3 is done so the import error doesn't exist at any commit point.

---

### Task 3: Edit `docker_health/__init__.py`

**Files:**
- Modify: `docker_health/__init__.py`

**Step 1: Remove DAG references**

Three changes to make:

**a) Update module docstring** — remove the `DAGWorkerSubsystem` line:

Old:
```python
Subsystems:
- SharedInfrastructureSubsystem: Database, storage, service bus (common)
- RuntimeSubsystem: Hardware, GDAL, imports, deployment config
- ClassicWorkerSubsystem: Existing queue-based job processing
- DAGWorkerSubsystem: Future DAG-driven workflow processing (stub)
```

New:
```python
Subsystems:
- SharedInfrastructureSubsystem: Database, storage, service bus (common)
- RuntimeSubsystem: Hardware, GDAL, imports, deployment config
- ClassicWorkerSubsystem: Existing queue-based job processing
```

**b) Remove `dag_processor` parameter from `get_all_subsystems()`**

Old:
```python
def get_all_subsystems(
    queue_worker,
    worker_lifecycle,
    token_refresh_worker,
    etl_mount_status: Optional[dict] = None,
    dag_processor=None,  # Future: DAG processor reference
) -> List["WorkerSubsystem"]:
```

New:
```python
def get_all_subsystems(
    queue_worker,
    worker_lifecycle,
    token_refresh_worker,
    etl_mount_status: Optional[dict] = None,
) -> List["WorkerSubsystem"]:
```

**c) Remove the docstring line, import, and subsystem entry**

Old docstring section:
```
        etl_mount_status: ETL mount status dict (optional)
        dag_processor: Future DAG processor reference (optional)
```

New:
```
        etl_mount_status: ETL mount status dict (optional)
```

Old imports block:
```python
    from .shared import SharedInfrastructureSubsystem
    from .runtime import RuntimeSubsystem
    from .classic_worker import ClassicWorkerSubsystem
    from .dag_worker import DAGWorkerSubsystem
```

New:
```python
    from .shared import SharedInfrastructureSubsystem
    from .runtime import RuntimeSubsystem
    from .classic_worker import ClassicWorkerSubsystem
```

Old subsystems list (remove last entry):
```python
        # Priority 40: DAG worker (future system - currently disabled)
        DAGWorkerSubsystem(
            dag_processor=dag_processor,
        ),
```

Remove entirely.

Also update the `# DEPENDENCIES` header comment:

Old:
```python
# DEPENDENCIES: base, shared, runtime, classic_worker, dag_worker
```

New:
```python
# DEPENDENCIES: base, shared, runtime, classic_worker
```

**Step 2: Commit Tasks 2 + 3 together**

```bash
git add docker_health/__init__.py docker_health/dag_worker.py
git commit -m "remove: DAGWorkerSubsystem stub from docker_health"
```

---

### Task 4: Edit `docker_service.py`

**Files:**
- Modify: `docker_service.py:1295-1340` (health endpoint)

**Step 1: Remove `dag_processor=None` kwarg from `get_all_subsystems()` call**

Old:
```python
    subsystems = get_all_subsystems(
        queue_worker=queue_worker,
        worker_lifecycle=worker_lifecycle,
        token_refresh_worker=token_refresh_worker,
        etl_mount_status=_etl_mount_status,
        dag_processor=None,  # Future: inject DAG processor when implemented
    )
```

New:
```python
    subsystems = get_all_subsystems(
        queue_worker=queue_worker,
        worker_lifecycle=worker_lifecycle,
        token_refresh_worker=token_refresh_worker,
        etl_mount_status=_etl_mount_status,
    )
```

**Step 2: Update the banner comment block above the health endpoint**

Old banner (lines ~1295-1308):
```python
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  HEALTH SUBSYSTEM ARCHITECTURE - 29 JAN 2026 - V0.8.1.1                   ║
# ║                                                                           ║
# ║  Refactored to use modular subsystem architecture anticipating dual       ║
# ║  queue systems: Classic Worker (existing) + DAG Worker (future).          ║
# ║                                                                           ║
# ║  Subsystems:                                                              ║
# ║  - SharedInfrastructureSubsystem: Database, Storage, Service Bus          ║
# ║  - RuntimeSubsystem: Hardware, GDAL, ETL Mount, Deployment                ║
# ║  - ClassicWorkerSubsystem: Queue worker, Auth, Lifecycle                  ║
# ║  - DAGWorkerSubsystem: Future DAG workflow processing (stub)              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
```

New banner:
```python
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  HEALTH SUBSYSTEM ARCHITECTURE - 29 JAN 2026 - V0.8.1.1                   ║
# ║                                                                           ║
# ║  Subsystems:                                                              ║
# ║  - SharedInfrastructureSubsystem: Database, Storage, Service Bus          ║
# ║  - RuntimeSubsystem: Hardware, GDAL, ETL Mount, Deployment                ║
# ║  - ClassicWorkerSubsystem: Queue worker, Auth, Lifecycle                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
```

**Step 3: Update `health_check()` docstring**

Old:
```python
    Returns comprehensive health information from all subsystems:
    - SharedInfrastructure: Database, Storage, Service Bus
    - Runtime: Hardware, GDAL, ETL Mount, Deployment
    - ClassicWorker: Queue worker, Auth tokens, Lifecycle
    - DAGWorker: Future DAG workflow processing (currently disabled)
```

New:
```python
    Returns comprehensive health information from all subsystems:
    - SharedInfrastructure: Database, Storage, Service Bus
    - Runtime: Hardware, GDAL, ETL Mount, Deployment
    - ClassicWorker: Queue worker, Auth tokens, Lifecycle
```

**Step 4: Commit**

```bash
git add docker_service.py
git commit -m "remove: dag_processor stub from docker_service.py health endpoint"
```

---

### Task 5: Minor comment cleanup

**Files:**
- Modify: `docker_health/base.py`
- Modify: `docker_health/classic_worker.py`

**Step 1: `docker_health/base.py` docstring** — remove DAGWorkerSubsystem line

Old:
```python
Each subsystem represents a logical grouping of health checks:
- SharedInfrastructureSubsystem: Common resources (database, storage)
- RuntimeSubsystem: Container environment (hardware, GDAL)
- ClassicWorkerSubsystem: Queue-based job processing
- DAGWorkerSubsystem: DAG-driven workflow processing
```

New:
```python
Each subsystem represents a logical grouping of health checks:
- SharedInfrastructureSubsystem: Common resources (database, storage)
- RuntimeSubsystem: Container environment (hardware, GDAL)
- ClassicWorkerSubsystem: Queue-based job processing
```

**Step 2: `docker_health/classic_worker.py` docstring** — remove forward-reference to DAG worker

Old:
```python
This is the "existing system" that will run alongside the future DAG worker.
```

Remove that line.

**Step 3: Commit**

```bash
git add docker_health/base.py docker_health/classic_worker.py
git commit -m "cleanup: remove stale DAG worker forward-references from comments"
```

---

## Verification

After all tasks, confirm:

```bash
# No DAG references remain outside docs/archive
grep -r "dag_worker\|DAGWorker\|dag_processor\|DagListener" . \
  --include="*.py" \
  --exclude-dir=docs \
  | grep -v ".pyc"
# Expected: no output

# docker_health still imports cleanly
python -c "from docker_health import get_all_subsystems, HealthAggregator; print('OK')"
# Expected: OK

# Health subsystem list is correct (3 subsystems, not 4)
grep -c "priority" docker_health/classic_worker.py docker_health/runtime.py docker_health/shared.py
# Expected: 1 each (3 total subsystems remain)
```
