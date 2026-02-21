# DAG Spike - Workflow Orchestration Research

**Created**: 27 JAN 2026
**Status**: Research/Educational
**Purpose**: Understand DAGs and workflow orchestration systems for future reference

---

## Table of Contents

1. [What is a DAG?](#what-is-a-dag)
2. [DAG vs Current Linear Stage Model](#dag-vs-current-linear-stage-model)
3. [What DAGs Enable](#what-dags-enable)
4. [How DAGs Store Dependencies](#how-dags-store-dependencies)
5. [Apache Airflow](#apache-airflow)
6. [Other Workflow Orchestration Systems](#other-workflow-orchestration-systems)
7. [Code Examples](#code-examples)
8. [Is a DAG Appropriate for This System?](#is-a-dag-appropriate-for-this-system)
9. [Azure Durable Functions Alternative](#azure-durable-functions-alternative)
10. [Decision Summary](#decision-summary)

---

## What is a DAG?

A **Directed Acyclic Graph** is a data structure where:

- **Directed**: Edges have a direction (A → B means A must complete before B)
- **Acyclic**: No cycles allowed (can't have A → B → C → A)
- **Graph**: Nodes connected by edges (not a simple list or tree)

```
       ┌──────┐
       │  A   │  (Start)
       └──┬───┘
          │
    ┌─────┴─────┐
    ▼           ▼
┌──────┐    ┌──────┐
│  B   │    │  C   │  (B and C can run in parallel)
└──┬───┘    └──┬───┘
   │           │
   │     ┌─────┘
   │     │
   ▼     ▼
  ┌───────┐
  │   D   │  (D waits for BOTH B and C)
  └───┬───┘
      │
      ▼
  ┌───────┐
  │   E   │  (End)
  └───────┘
```

---

## DAG vs Current Linear Stage Model

### Current System Architecture

Our system uses a **linear stage model**:

```python
# Job definition
stages = [
    {"number": 1, "name": "validate", "task_type": "raster_validate", "parallelism": "single"},
    {"number": 2, "name": "create_cog", "task_type": "raster_create_cog", "parallelism": "parallel"},
    {"number": 3, "name": "create_stac", "task_type": "raster_extract_stac_metadata", "parallelism": "single"}
]
```

Execution pattern:
```
JOB_CREATED          ──┐
                       │
STAGE_1_STARTED      ──┤
├─ TASK_QUEUED (×N)    │   ← Tasks created in parallel
├─ TASK_STARTED (×N)   │   ← Tasks run in parallel
├─ TASK_COMPLETED (×N) │   ← "Last task turns out lights"
STAGE_1_COMPLETED    ──┤
                       │
STAGE_2_STARTED      ──┤   ← Advances only after ALL stage 1 tasks done
...
```

### Comparison Table

| Aspect | Our System (Linear Stages) | DAG System (Airflow/Prefect) |
|--------|----------------------------|------------------------------|
| **Structure** | Stages are sequential, tasks parallel within stage | Any node can depend on any other node(s) |
| **Storage** | `stages = [{number: 1}, {number: 2}]` | Graph edges: `{A→B, A→C, B→D, C→D, D→E}` |
| **Fan-out** | All tasks in a stage start together | Explicit: A triggers B and C |
| **Fan-in** | "Last task turns out lights" pattern | Explicit: D waits for B AND C |
| **Branching** | Not supported | Task D can run only if condition met |
| **Skipping** | Whole stage skipped on failure | Individual paths can be skipped |

---

## What DAGs Enable

### 1. Complex Dependencies (Fan-in from Different Stages)

Our system can't express:

```
    Stage 1: [Validate]
                ↓
    Stage 2: [Create COG A] [Create COG B]
                ↓               ↓
    Stage 3: [Index A to STAC]  │
                ↓               │
    Stage 4: ←──────────────────┘ [Merge A + B into Mosaic]

The merge needs BOTH "Index A" AND "Create COG B" -
but they're in different stages.
```

### 2. Conditional Branching

```python
# DAG can express:
if file_size > 1GB:
    run_docker_worker()
else:
    run_function_app()

# Then both paths merge back to "register_in_stac"
```

### 3. Dynamic Task Generation

```python
# Airflow example - tasks created at runtime based on data
@task
def get_file_list():
    return ["file1.tif", "file2.tif", "file3.tif"]

@task
def process_file(filename):
    # Process one file
    pass

# DAG dynamically creates 3 parallel tasks
files = get_file_list()
process_file.expand(filename=files)  # Fan-out to N tasks
```

### 4. Incremental Processing

```
❌ Current: All tiles must complete before ANY STAC work starts

✅ With DAG: Each tile can register to STAC immediately after creation

   [tile_r0c0] ──→ [stac_r0c0] ──┐
   [tile_r0c1] ──→ [stac_r0c1] ──┼──→ [finalize_collection]
   [tile_r1c0] ──→ [stac_r1c0] ──┤
   [tile_r1c1] ──→ [stac_r1c1] ──┘
```

---

## How DAGs Store Dependencies

### Option 1: Edge List (Airflow Style)

```python
# Stored as explicit dependencies in Python
task_a >> task_b  # A before B
task_a >> task_c  # A before C (parallel with B)
[task_b, task_c] >> task_d  # D waits for both
```

### Option 2: Adjacency List (Database)

```sql
CREATE TABLE workflow_edges (
    workflow_id VARCHAR(64),
    from_task VARCHAR(64),
    to_task VARCHAR(64),
    condition JSONB  -- Optional: run only if condition met
);

-- Raster workflow as edges:
INSERT INTO workflow_edges VALUES
('raster_v2', 'START', 'validate'),
('raster_v2', 'validate', 'create_cog_r0c0'),
('raster_v2', 'validate', 'create_cog_r0c1'),  -- Fan-out
('raster_v2', 'validate', 'create_cog_r1c0'),
('raster_v2', 'validate', 'create_cog_r1c1'),
('raster_v2', 'create_cog_r0c0', 'create_stac'),  -- Fan-in
('raster_v2', 'create_cog_r0c1', 'create_stac'),
('raster_v2', 'create_cog_r1c0', 'create_stac'),
('raster_v2', 'create_cog_r1c1', 'create_stac'),
('raster_v2', 'create_stac', 'END');
```

### Option 3: Task-Level Dependencies

```sql
CREATE TABLE tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    job_id VARCHAR(64),
    depends_on VARCHAR(64)[]  -- Array of task_ids that must complete first
);
```

---

## Apache Airflow

### What is Airflow?

**Apache Airflow** is an open-source workflow orchestration platform written in Python, originally created by Airbnb in 2014. It lets you define, schedule, and monitor complex data pipelines.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AIRFLOW ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│   │   Web UI     │     │  Scheduler   │     │   Metadata   │   │
│   │  (Flask)     │     │  (daemon)    │     │   Database   │   │
│   └──────────────┘     └──────┬───────┘     │  (Postgres)  │   │
│                               │             └──────────────┘   │
│                               ▼                                 │
│                    ┌────────────────────┐                       │
│                    │      Executor      │                       │
│                    │  (runs the tasks)  │                       │
│                    └────────┬───────────┘                       │
│                             │                                   │
│              ┌──────────────┼──────────────┐                   │
│              ▼              ▼              ▼                   │
│         ┌────────┐    ┌────────┐    ┌────────┐                │
│         │Worker 1│    │Worker 2│    │Worker 3│                │
│         └────────┘    └────────┘    └────────┘                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **DAG Definition** | Python code that defines tasks and dependencies |
| **Scheduler** | Watches clock + dependencies, decides when to run tasks |
| **Executor** | Runs tasks (locally, on Kubernetes, Celery workers, etc.) |
| **Metadata DB** | Tracks task states, run history, logs |
| **Web UI** | Monitor runs, view logs, trigger manual runs, see DAG visualization |

### Scheduler Logic (Pseudo-code)

```python
# What the scheduler does every few seconds
while True:
    for dag in all_dags:
        if dag.is_scheduled_to_run_now():
            create_dag_run(dag)

    for task in all_pending_tasks:
        # Check if all upstream dependencies are complete
        upstream_tasks = get_dependencies(task)

        if all(t.status == 'success' for t in upstream_tasks):
            # All dependencies met - task can run!
            executor.queue_task(task)
        elif any(t.status == 'failed' for t in upstream_tasks):
            # Upstream failed - skip this task
            task.status = 'upstream_failed'

    sleep(5)
```

### Comparison: Our System vs Airflow

| Aspect | Our System | Airflow |
|--------|-------------|---------|
| **Language** | Python | Python |
| **DAG Definition** | `stages = [...]` in job class | Python code with `>>` operators |
| **Scheduler** | Timer trigger + Service Bus | Dedicated scheduler daemon |
| **Executor** | Function App / Docker worker | Celery, Kubernetes, Local |
| **State Storage** | `app.jobs`, `app.tasks` tables | Airflow metadata DB |
| **Triggers** | HTTP submit, timer, queue message | Schedule, external trigger, sensor |
| **UI** | Docker UI | Built-in React UI |

---

## Other Workflow Orchestration Systems

| System | Language | Key Differentiator |
|--------|----------|-------------------|
| **Apache Airflow** | Python | Most popular, huge ecosystem, complex setup |
| **Prefect** | Python | "Airflow but easier", better local dev, cloud-hosted option |
| **Dagster** | Python | Data-aware (tracks what data flows between tasks), great testing |
| **Temporal** | Go/Java/Python/etc | Durable execution, handles long-running workflows, retries built-in |
| **Luigi** | Python | Spotify's tool, simpler than Airflow, file-based targets |
| **Argo Workflows** | YAML + any | Kubernetes-native, containers as tasks |
| **Step Functions** | JSON/YAML | AWS managed service, integrates with Lambda |
| **Azure Durable Functions** | C#/Python/JS | Azure-native, orchestrator functions |

---

## Code Examples

### Airflow DAG Example

```python
# dags/raster_pipeline.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime

# Define the DAG
with DAG(
    dag_id='process_raster',
    start_date=datetime(2026, 1, 1),
    schedule='@daily',  # Run every day at midnight
    catchup=False
) as dag:

    # Task 1: Validate
    validate = PythonOperator(
        task_id='validate_raster',
        python_callable=lambda: print("Validating raster...")
    )

    # Task 2a, 2b: Create COGs (parallel)
    create_cog_1 = BashOperator(
        task_id='create_cog_tile_1',
        bash_command='gdal_translate -of COG input.tif tile_1.tif'
    )

    create_cog_2 = BashOperator(
        task_id='create_cog_tile_2',
        bash_command='gdal_translate -of COG input.tif tile_2.tif'
    )

    # Task 3: Register to STAC (waits for BOTH COGs)
    register_stac = PythonOperator(
        task_id='register_stac',
        python_callable=lambda: print("Registering to STAC...")
    )

    # Define dependencies (the DAG edges)
    validate >> [create_cog_1, create_cog_2]  # Fan-out
    [create_cog_1, create_cog_2] >> register_stac  # Fan-in
```

Creates this graph:
```
        [validate]
            │
      ┌─────┴─────┐
      ▼           ▼
[create_cog_1] [create_cog_2]
      │           │
      └─────┬─────┘
            ▼
     [register_stac]
```

### Prefect Example (Modern Alternative)

```python
from prefect import flow, task

@task
def validate_raster(blob_name: str) -> dict:
    """Validate input raster."""
    # validation logic
    return {"valid": True, "crs": "EPSG:4326"}

@task
def create_cog(blob_name: str, tile_id: int) -> str:
    """Create a COG tile."""
    output = f"tile_{tile_id}.tif"
    # COG creation logic
    return output

@task
def register_to_stac(cog_paths: list[str]) -> str:
    """Register all COGs to STAC catalog."""
    # STAC registration
    return "collection_123"

@flow
def process_raster(blob_name: str):
    """Main workflow."""
    # Validate first
    validation = validate_raster(blob_name)

    # Create 4 COGs in parallel (Prefect handles this automatically)
    cog_paths = create_cog.map(
        blob_name=[blob_name] * 4,
        tile_id=[0, 1, 2, 3]
    )

    # Register to STAC (waits for all COGs automatically)
    collection_id = register_to_stac(cog_paths)

    return collection_id

# Run locally
process_raster("my_raster.tif")
```

---

## Is a DAG Appropriate for This System?

### Arguments FOR Adopting DAGs

| Scenario | Benefit |
|----------|---------|
| Cross-stage dependencies | Mosaic needs tiles from stage 2 AND metadata from stage 3 |
| Conditional workflows | Skip STAC registration if validation finds issues |
| Partial retries | Re-run only failed branch, not whole stage |
| Complex pipelines | ML training → evaluation → conditional deployment |

### Arguments AGAINST (Why Current Model Works)

| Reason | Explanation |
|--------|-------------|
| **Simplicity** | Linear stages are easy to understand, debug, visualize |
| **Workflows are linear** | Validate → COG → STAC is naturally sequential |
| **"Last task turns out lights"** | Fan-in pattern works via SQL atomic check |
| **No conditional branching needed** | All tasks in a stage do the same thing |
| **Parallelism is uniform** | All COG tiles are equal, no special dependencies |

### When to Consider DAGs

Switch to a DAG system if you need:

1. **50+ different workflow types** - Managing job classes becomes unwieldy
2. **Complex cross-workflow dependencies** - Job A output triggers Job B
3. **Team of 5+ data engineers** - Standard tooling, everyone knows Airflow
4. **Visual DAG editor** - Non-engineers defining workflows
5. **Heavy scheduling needs** - "Run at 3am, but only on weekdays, after Job X finishes"

---

## Azure Durable Functions Alternative

If DAG-like orchestration is needed in Azure without Airflow:

```python
# Azure Durable Functions - Orchestrator pattern
import azure.durable_functions as df

def orchestrator_function(context: df.DurableOrchestrationContext):
    """Orchestrator - defines the workflow."""

    # Step 1: Validate
    validation = yield context.call_activity('validate_raster', blob_name)

    # Step 2: Fan-out to parallel COG creation
    cog_tasks = [
        context.call_activity('create_cog', {"blob": blob_name, "tile": i})
        for i in range(4)
    ]
    cog_results = yield context.task_all(cog_tasks)  # Wait for all

    # Step 3: Register to STAC
    result = yield context.call_activity('register_stac', cog_results)

    return result
```

This is essentially what our CoreMachine does, but with Azure handling the state persistence and replay logic.

---

## Decision Summary

### Current Recommendation: Keep Linear Stage Model

| Question | Answer |
|----------|--------|
| **Are DAGs more powerful?** | Yes, they enable complex dependencies and branching |
| **Do we need that power?** | No, our workflows are genuinely linear |
| **Cost of switching?** | High - new scheduler, dependency resolution, infrastructure |
| **Benefit of current model?** | Simplicity, debuggability, serverless-friendly |

### When to Revisit

Consider DAGs if:
- Workflow complexity increases significantly
- Need conditional branching (if X then Y else Z)
- Need cross-workflow dependencies
- Team grows and needs standard tooling

### If We Adopt DAGs Later

Prefer using an existing system (Airflow, Prefect, Temporal) rather than building one. The scheduler complexity (detecting when all dependencies are met, handling partial failures, retries) is substantial and well-solved by existing tools.

---

## References

- [Apache Airflow Documentation](https://airflow.apache.org/docs/)
- [Prefect Documentation](https://docs.prefect.io/)
- [Dagster Documentation](https://docs.dagster.io/)
- [Azure Durable Functions](https://docs.microsoft.com/en-us/azure/azure-functions/durable/)
- [Temporal.io](https://temporal.io/)
