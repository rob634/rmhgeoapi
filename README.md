# rmhgeoapi - Geospatial ETL Pipeline

**Azure Functions-based geospatial data processing platform with Job→Stage→Task orchestration**

---

## 🚀 Quick Start

```bash
# 1. Health Check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# 2. Submit Test Job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "Testing the pipeline"}'

# 3. Check Status (use job_id from step 2)
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{job_id}
```

---

## 🏗️ Architecture Overview

### Epoch 4: Declarative Job→Stage→Task Pattern

```
HTTP Request → CoreMachine → Workflow Definition → Task Handlers → Results
                    ↓              ↓                      ↓
               Job Record    Stage Creation         Task Execution
             (PostgreSQL)    (Sequential)        (Parallel via Service Bus)
```

**Key Concepts:**

1. **Jobs** (jobs/) - WHAT to do
   - Pure data declarations
   - Define stages and parameters
   - No execution logic

2. **Tasks** (services/) - HOW to do it
   - Handler functions with business logic
   - Registered in explicit registry
   - Return `{"success": bool, ...}`

3. **CoreMachine** (core/machine.py) - ORCHESTRATION
   - Universal coordinator (450 lines vs previous 2,290-line "God Class")
   - Composition over inheritance
   - Handles all jobs via delegation

4. **Service Bus** - ASYNC PROCESSING
   - `geospatial-jobs` queue - Job messages
   - `geospatial-tasks` queue - Task messages
   - Parallel execution within stages

### Data Flow

```
Stage 1 (Sequential)
  ├── Task A (Parallel) ─┐
  ├── Task B (Parallel) ─┤→ Last task detects completion
  └── Task C (Parallel) ─┘   ("turns out the lights")
          ↓
Stage 2 (Sequential)
  ├── Task D (Parallel) ─┐
  └── Task E (Parallel) ─┘→ Job completion
```

**"Last Task Turns Out the Lights"**: The final completing task in each stage triggers stage advancement via atomic SQL operations (prevents race conditions).

---

## 📁 Project Structure

```
rmhgeoapi/
├── function_app.py              # Azure Functions entry point (HTTP routes + Service Bus triggers)
├── config.py                    # Pydantic configuration with environment validation
│
├── core/                        # Orchestration layer
│   ├── machine.py              # CoreMachine - Universal job orchestrator
│   ├── state_manager.py        # Database state management
│   ├── orchestration_manager.py # Stage advancement logic
│   ├── models/                 # Pydantic data models
│   └── schema/                 # Database schema + queue messages
│
├── jobs/                        # Job declarations (WHAT)
│   ├── __init__.py             # ALL_JOBS explicit registry
│   ├── base.py                 # JobBase ABC (5-method contract)
│   ├── hello_world.py          # Example: 2-stage greeting workflow
│   ├── process_vector.py       # Vector ETL to PostGIS (idempotent)
│   └── process_raster_v2.py    # Raster → COG pipeline (mixin pattern)
│
├── services/                    # Task handlers (HOW)
│   ├── __init__.py             # ALL_HANDLERS explicit registry
│   ├── service_hello_world.py  # Example handlers
│   ├── raster_cog.py           # COG creation logic
│   └── vector/tasks.py         # Vector processing handlers
│
├── infrastructure/              # External services
│   ├── postgresql.py           # PostgreSQL repository
│   ├── service_bus.py          # Service Bus messaging
│   ├── blob.py                 # Azure Blob Storage
│   └── stac.py                 # STAC catalog operations
│
├── triggers/                    # HTTP endpoints
│   ├── submit_job.py           # POST /api/jobs/submit/{job_type}
│   ├── get_job_status.py       # GET /api/jobs/status/{job_id}
│   ├── health.py               # GET /api/health
│   └── admin/                  # Database admin endpoints
│
└── ogc_features/                # OGC API - Features (standalone module)
    └── README.md               # OGC Features documentation
```

---

## 🛠️ Building a New Job Type

### Step-by-Step Guide

Let's build a new job type called `process_csv` that:
1. **Stage 1**: Downloads CSV from blob storage
2. **Stage 2**: Validates rows in parallel (N chunks)
3. **Stage 3**: Uploads validated data to PostgreSQL

---

### Step 1: Create Job Declaration

**File:** `jobs/process_csv.py`

```python
# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Three-stage CSV processing workflow
# PURPOSE: Download CSV, validate in chunks, upload to PostgreSQL
# EXPORTS: ProcessCsvJob
# INTERFACES: JobBase (implements 5-method contract)
# PATTERNS: Job declaration (pure data)
# ============================================================================

from typing import List, Dict, Any
import hashlib
import json
from jobs.base import JobBase


class ProcessCsvJob(JobBase):
    """
    CSV processing job - download, validate, upload.

    This is PURE DATA - no execution logic!
    """

    job_type: str = "process_csv"
    description: str = "Process CSV file with parallel validation"

    # Stage definitions (pure data!)
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "download",
            "task_type": "csv_download",
            "parallelism": "single",  # Only one download task
        },
        {
            "number": 2,
            "name": "validate",
            "task_type": "csv_validate_chunk",
            "parallelism": "dynamic",  # N parallel validation tasks
            "count_param": "chunk_count",  # Which parameter controls count
            "depends_on": 1,
            "uses_lineage": True  # Can access stage 1 results
        },
        {
            "number": 3,
            "name": "upload",
            "task_type": "csv_upload",
            "parallelism": "single",  # One upload task
            "depends_on": 2,
            "uses_lineage": True  # Can access stage 2 results
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container": {"type": "str", "default": "bronze"},
        "chunk_count": {"type": "int", "min": 1, "max": 100, "default": 10},
        "table_name": {"type": "str", "required": True}
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for each stage.

        This is the ONLY job-specific logic - creating task parameters.
        Everything else (queuing, status, completion) handled by CoreMachine.
        """

        if stage == 1:
            # Stage 1: Single download task
            return [{
                "task_id": f"{job_id}_download",
                "blob_name": job_params["blob_name"],
                "container": job_params.get("container", "bronze")
            }]

        elif stage == 2:
            # Stage 2: Parallel validation tasks (N chunks)
            # Get downloaded file info from stage 1
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 download failed")

            download_result = previous_results[0]["result"]
            total_rows = download_result["total_rows"]
            chunk_count = job_params.get("chunk_count", 10)
            rows_per_chunk = total_rows // chunk_count

            tasks = []
            for i in range(chunk_count):
                start_row = i * rows_per_chunk
                end_row = start_row + rows_per_chunk if i < chunk_count - 1 else total_rows

                tasks.append({
                    "task_id": f"{job_id}_validate_chunk_{i}",
                    "chunk_index": i,
                    "start_row": start_row,
                    "end_row": end_row,
                    "temp_file_path": download_result["temp_file_path"]
                })

            return tasks

        elif stage == 3:
            # Stage 3: Single upload task
            # Get validation results from stage 2
            if not all(r.get("success") for r in previous_results):
                raise ValueError("Some validation tasks failed")

            validated_row_count = sum(r["result"]["valid_rows"] for r in previous_results)

            return [{
                "task_id": f"{job_id}_upload",
                "table_name": job_params["table_name"],
                "validated_row_count": validated_row_count,
                "temp_file_path": previous_results[0]["result"]["temp_file_path"]
            }]

        else:
            raise ValueError(f"Invalid stage: {stage}")
```

---

### Step 2: Register Job in ALL_JOBS

**File:** `jobs/__init__.py`

```python
# Add import at top
from .process_csv import ProcessCsvJob

# Add to ALL_JOBS dict
ALL_JOBS = {
    "hello_world": HelloWorldJob,
    "process_csv": ProcessCsvJob,  # ← ADD THIS LINE
    # ... other jobs
}
```

**That's it for the job!** No decorators, no magic - just add to the dict.

---

### Step 3: Create Task Handlers

**File:** `services/service_csv.py`

```python
# ============================================================================
# CLAUDE CONTEXT - SERVICE HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - CSV processing task handlers
# PURPOSE: Execute CSV download, validation, and upload tasks
# EXPORTS: csv_download, csv_validate_chunk, csv_upload
# PATTERNS: Handler functions with {"success": bool} contract
# ============================================================================

from typing import Dict, Any, Optional
import pandas as pd
from infrastructure import BlobStorageRepository, RepositoryFactory
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "csv_processing")


def csv_download(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Stage 1: Download CSV from blob storage.

    Handler Contract:
    - Returns: {"success": True, "result": {...}} on success
    - Returns: {"success": False, "error": "..."} on failure
    - Or raises exception (CoreMachine converts to failure)
    """
    logger.info(f"🔽 Downloading CSV: {params['blob_name']}")

    try:
        blob_repo = BlobStorageRepository()

        # Download CSV to temp location
        temp_path = f"/tmp/{params['blob_name'].split('/')[-1]}"
        blob_repo.download_blob(
            container=params['container'],
            blob_name=params['blob_name'],
            destination=temp_path
        )

        # Get row count
        df = pd.read_csv(temp_path, nrows=1000)  # Sample for count
        total_rows = len(df)  # Or use wc -l for exact count

        logger.info(f"✅ Downloaded CSV: {total_rows} rows")

        return {
            "success": True,
            "result": {
                "temp_file_path": temp_path,
                "total_rows": total_rows,
                "columns": list(df.columns)
            }
        }

    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def csv_validate_chunk(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Stage 2: Validate a chunk of CSV rows in parallel.
    """
    logger.info(f"✅ Validating chunk {params['chunk_index']}: rows {params['start_row']}-{params['end_row']}")

    try:
        # Read chunk
        df = pd.read_csv(
            params['temp_file_path'],
            skiprows=range(1, params['start_row'] + 1),
            nrows=params['end_row'] - params['start_row']
        )

        # Validate (example: check for nulls)
        invalid_rows = df.isnull().sum().sum()
        valid_rows = len(df) - invalid_rows

        logger.info(f"✅ Chunk {params['chunk_index']}: {valid_rows} valid, {invalid_rows} invalid")

        return {
            "success": True,
            "result": {
                "chunk_index": params['chunk_index'],
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "temp_file_path": params['temp_file_path']
            }
        }

    except Exception as e:
        logger.error(f"❌ Validation failed for chunk {params['chunk_index']}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def csv_upload(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Stage 3: Upload validated CSV to PostgreSQL.
    """
    logger.info(f"⬆️ Uploading to table: {params['table_name']}")

    try:
        # Read full CSV
        df = pd.read_csv(params['temp_file_path'])

        # Upload to PostgreSQL
        repos = RepositoryFactory.create_repositories()
        pg_repo = repos['job_repo']  # Get PostgreSQL connection

        with pg_repo._get_connection() as conn:
            df.to_sql(
                params['table_name'],
                conn,
                schema='geo',
                if_exists='replace',
                index=False
            )

        logger.info(f"✅ Uploaded {len(df)} rows to {params['table_name']}")

        return {
            "success": True,
            "result": {
                "table_name": params['table_name'],
                "rows_uploaded": len(df)
            }
        }

    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
```

---

### Step 4: Register Handlers in ALL_HANDLERS

**File:** `services/__init__.py`

```python
# Add import at top
from .service_csv import csv_download, csv_validate_chunk, csv_upload

# Add to ALL_HANDLERS dict
ALL_HANDLERS = {
    "hello_world_greeting": handle_greeting,
    "csv_download": csv_download,              # ← ADD THESE
    "csv_validate_chunk": csv_validate_chunk,  # ← THREE
    "csv_upload": csv_upload,                  # ← LINES
    # ... other handlers
}
```

---

### Step 5: Deploy and Test

```bash
# 1. Deploy to Azure
func azure functionapp publish rmhazuregeoapi --python --build remote

# 2. Redeploy schema (if database changes needed)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# 3. Submit job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_csv \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "data/customers.csv",
    "container": "bronze",
    "chunk_count": 5,
    "table_name": "customers_import"
  }'

# 4. Check status
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{job_id}

# 5. Query database
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs?job_type=process_csv&limit=10"
```

---

## 📋 Job Development Checklist

- [ ] **Create job class** in `jobs/your_job.py`
  - [ ] Inherit from `JobBase`
  - [ ] Define `job_type`, `description`
  - [ ] Define `stages` list
  - [ ] Define `parameters_schema`
  - [ ] Implement `create_tasks_for_stage()`

- [ ] **Register job** in `jobs/__init__.py`
  - [ ] Import job class
  - [ ] Add to `ALL_JOBS` dict

- [ ] **Create handlers** in `services/service_your_domain.py`
  - [ ] One handler function per task type
  - [ ] Return `{"success": bool, ...}`
  - [ ] Use logger for visibility

- [ ] **Register handlers** in `services/__init__.py`
  - [ ] Import handler functions
  - [ ] Add to `ALL_HANDLERS` dict

- [ ] **Test locally** (if Azure Functions Core Tools installed)
  - [ ] `func start`
  - [ ] Submit test job
  - [ ] Check logs

- [ ] **Deploy and test**
  - [ ] Deploy to Azure
  - [ ] Submit test job
  - [ ] Check Application Insights logs
  - [ ] Query database for results

---

## 🔑 Key Patterns

### 1. Explicit Registration (No Decorators!)

**Why:** Decorators only execute when modules are imported. If a module is never imported, its decorator never runs, causing silent registration failures.

**Pattern:**
```python
# jobs/__init__.py
ALL_JOBS = {
    "your_job": YourJobClass,  # ← Explicit!
}

# services/__init__.py
ALL_HANDLERS = {
    "your_task": your_handler_function,  # ← Explicit!
}
```

### 2. Handler Contract (Enforced by CoreMachine)

```python
def handler(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns:
        {"success": True, "result": {...}}   # On success
        {"success": False, "error": "..."}   # On failure

    Or raise exception (CoreMachine converts to failure)
    """
```

**Contract enforcement:**
- Missing `"success"` field → `ContractViolationError` (crashes function)
- Non-boolean `"success"` → `ContractViolationError`

### 3. "Last Task Turns Out the Lights"

The final completing task in a stage triggers advancement using atomic SQL:

```sql
-- CoreMachine uses this pattern internally
UPDATE jobs
SET stage = stage + 1
WHERE job_id = $1
  AND (SELECT COUNT(*) FROM tasks WHERE job_id = $1 AND stage = $2 AND status != 'COMPLETED') = 0
```

**You don't write this** - CoreMachine handles it. Just return `{"success": True}` from your handlers.

### 4. Stage Lineage (Access Previous Results)

```python
# In create_tasks_for_stage():
if stage == 2:
    # Access stage 1 results
    stage1_result = previous_results[0]["result"]
    file_path = stage1_result["temp_file_path"]

    # Use in stage 2 tasks
    return [{
        "task_id": f"{job_id}_task2",
        "input_file": file_path  # ← Data flows forward
    }]
```

### 5. Dynamic Parallelism

```python
stages = [
    {
        "parallelism": "dynamic",      # N parallel tasks
        "count_param": "chunk_count"   # Get N from params
    }
]

def create_tasks_for_stage(stage, job_params, job_id, previous_results):
    n = job_params["chunk_count"]  # User specifies N
    return [{"task_id": f"{job_id}_{i}"} for i in range(n)]
```

---

## 🗄️ Database Schemas

```
PostgreSQL (rmhpostgres.postgres.database.azure.com):
├── app      - CoreMachine (jobs, tasks tables)
├── geo      - PostGIS vector data
├── pgstac   - STAC metadata catalog
└── platform - Platform API requests (DDH integration)
```

**Query database without DBeaver:**
```bash
# All jobs
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs?limit=100"

# All tasks for a job
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/tasks/{job_id}"

# Database stats
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/stats"
```

---

## 📡 APIs Exposed

### 1. **Job API** (Custom - CoreMachine)
- `POST /api/jobs/submit/{job_type}` - Submit job
- `GET /api/jobs/status/{job_id}` - Get status

### 2. **STAC API** (Standards-Compliant - STAC v1.0.0)
- `GET /api/stac` - Landing page (catalog root)
- `GET /api/stac/conformance` - Conformance classes
- `GET /api/stac/collections` - List STAC collections
- **Full Documentation**: [stac_api/README.md](stac_api/README.md) | [Unified API Docs](docs/API_DOCUMENTATION.md)

### 3. **OGC API - Features** (OGC Core 1.0)
- `GET /api/features` - Landing page
- `GET /api/features/collections` - List PostGIS vector collections
- `GET /api/features/collections/{id}/items` - Query features with filters
- Query params: `?bbox=minx,miny,maxx,maxy&limit=100&simplify=10`
- **Full Documentation**: [ogc_features/README.md](ogc_features/README.md) | [Unified API Docs](docs/API_DOCUMENTATION.md)

### 4. **Platform API** (DDH Integration)
- `POST /api/platform/submit` - Submit platform request
- `GET /api/platform/status/{request_id}` - Get status

### 5. **Admin API** (Observability & Operations) - Third Layer

**Architecture:** Admin API is **orthogonal** to the Platform/CoreMachine orchestration layers. It provides cross-layer inspection and maintenance capabilities.

```
┌─────────────────────────────────────────────┐
│  CLIENT APPS → Platform API → CoreMachine  │  (Request flow - vertical)
└──────────────┬──────────────────────────────┘
               ↓
         [PostgreSQL, Service Bus, Storage]
               ↑
    ═══════════════════════════════════════
    Admin API (Horizontal inspection)
    ═══════════════════════════════════════
```

**Purpose:** Read-only inspection + emergency maintenance across all system layers

**Phase 1 - Database Admin:** ✅ Complete
- Schema inspection: `/api/db/schemas`, `/api/db/tables/{schema}.{table}`
- Query analysis: `/api/db/queries/running`, `/api/db/locks`, `/api/db/connections`
- Health monitoring: `/api/db/health`, `/api/db/health/performance`
- Maintenance: `/api/db/maintenance/nuke`, `/api/db/maintenance/cleanup`

**Phase 2 - Service Bus Admin:** ✅ Complete
- Queue monitoring: `/api/servicebus/queues`, `/api/servicebus/queues/{queue}`
- Message inspection: `/api/servicebus/queues/{queue}/peek` (read-only)
- Dead letters: `/api/servicebus/queues/{queue}/deadletter`
- Emergency ops: `/api/servicebus/queues/{queue}/nuke?confirm=yes`

**Phase 3-7 - Future:**
- STAC Admin (pgstac inspection)
- Storage Admin (blob containers)
- Registry & Discovery (jobs/handlers metadata)
- Traces & Analysis (Application Insights integration)
- System-Wide Operations (cache, metrics)

**Access:** Designed for AI agents, DevOps tools, monitoring dashboards (future APIM access control)

---

## 🧪 Testing & Debugging

### Health Check
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

Returns:
```json
{
  "status": "healthy",
  "components": {
    "postgresql": "ok",
    "service_bus": "ok",
    "blob_storage": "ok"
  },
  "registered_jobs": ["hello_world", "process_csv", ...],
  "registered_handlers": ["csv_download", "csv_validate_chunk", ...]
}
```

### Application Insights Logs

**Pattern - Create query script:**
```bash
# 1. Login to Azure
az login

# 2. Create query script
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 10" \
  -G
EOF

# 3. Execute
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

**Useful KQL queries:**
```kql
# Recent errors
traces | where timestamp >= ago(1h) | where severityLevel >= 3 | take 20

# Specific job
traces | where message contains "job_id_here" | order by timestamp desc

# Task processing
traces | where message contains "Processing task" | take 50
```

### Database Debugging
```bash
# All jobs with filters
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs?status=failed&hours=24"

# Tasks for specific job
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/tasks/{job_id}"

# Complete debug dump
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/debug/all?limit=100"
```

---

## 🚨 Development Tools

### Nuclear Buttons (DEV/TEST ONLY)

```bash
# Clear all schema objects and redeploy
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# Clear STAC items/collections (preserves schema)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=all"

# Clear Service Bus queue
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/servicebus/queues/geospatial-jobs/nuke?confirm=yes&target=all"
```

---

## 📚 Further Reading

- **In-Depth Architecture**: See `function_app.py` lines 27-118 for data flow diagrams
- **Job Examples**:
  - Simple: `jobs/create_h3_base.py`
  - Multi-stage: `jobs/hello_world.py`
  - Complex: `jobs/process_raster_v2.py`
- **Handler Contract**: `services/__init__.py` lines 32-70
- **CoreMachine**: `core/machine.py` - Universal orchestrator implementation
- **Extended Docs**: `/docs_claude/CLAUDE_CONTEXT.md` for comprehensive documentation

---

## 🤝 Contributing

### Adding a New Job Type

1. Create job class in `jobs/`
2. Register in `jobs/__init__.py` ALL_JOBS dict
3. Create handlers in `services/`
4. Register in `services/__init__.py` ALL_HANDLERS dict
5. Test with `/api/health` (validates registration)
6. Deploy and submit test job

**The validation functions will catch:**
- Missing required methods (5 for jobs, contract for handlers)
- Invalid stage definitions
- Unregistered jobs/handlers
- Type mismatches

**Fail-fast at import time, not at runtime!**

---

## 📖 Key Files Quick Reference

| File | Purpose | Lines | What to Look For |
|------|---------|-------|------------------|
| `function_app.py` | Entry point | 2,026 | HTTP routes, Service Bus triggers, architecture diagram |
| `core/machine.py` | Orchestrator | 450 | CoreMachine coordinator logic |
| `jobs/__init__.py` | Job registry | 222 | ALL_JOBS dict, validation |
| `services/__init__.py` | Handler registry | 180 | ALL_HANDLERS dict, contract |
| `jobs/hello_world.py` | Example job | 150 | Simple 2-stage workflow |
| `config.py` | Configuration | 800+ | Environment variables, Pydantic validation |

---

## 🏷️ Version & Status

- **Epoch**: 4 (Declarative Job→Stage→Task)
- **Active Function App**: `rmhazuregeoapi`
- **Database**: PostgreSQL Flexible Server (`rmhpostgres.postgres.database.azure.com`)
- **Messaging**: Azure Service Bus (Storage Queues deprecated)
- **Python**: 3.11
- **Key Libraries**: Azure Functions, Pydantic, psycopg3, GDAL/rasterio

---

## License

MIT License
