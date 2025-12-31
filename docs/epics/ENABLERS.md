# COMPLETED ENABLERS

Technical foundation that enables all Epics above.

## Enabler EN1: Job Orchestration Engine ✅

**What It Enables**: All ETL jobs (E1, E2, E9)

| Component | Description |
|-----------|-------------|
| CoreMachine | Job→Stage→Task state machine |
| JobBaseMixin | 70%+ code reduction for new jobs |
| Retry Logic | Exponential backoff with telemetry |
| Stage Completion | "Last task turns out the lights" pattern |

**Key Files**: `core/machine.py`, `core/state_manager.py`, `jobs/base.py`, `jobs/mixins.py`

---

## Enabler EN2: Database Architecture ✅

**What It Enables**: Data separation, safe schema management

| Component | Description |
|-----------|-------------|
| Dual Database | App DB (nukeable) vs Business DB (protected) |
| Schema Management | full-rebuild, redeploy, nuke endpoints |
| Managed Identity | Same identity, different permission grants |

**Key Files**: `config/database_config.py`, `triggers/admin/db_maintenance.py`

---

## Enabler EN3: Azure Platform Integration ✅

**What It Enables**: Secure, scalable Azure deployment

| Component | Description |
|-----------|-------------|
| Managed Identity | User-assigned identity for all services |
| Service Bus | Queue-based job orchestration |
| Blob Storage | Bronze/Silver tier with SAS URLs |

**Key Files**: `infrastructure/service_bus.py`, `infrastructure/storage.py`

---

## Enabler EN4: Configuration System ✅

**What It Enables**: Environment-based configuration

| Component | Description |
|-----------|-------------|
| Modular Config | Split from 1200-line monolith |
| Type Safety | Pydantic-based config classes |

**Key Files**: `config/__init__.py`, `config/database_config.py`, `config/storage_config.py`, `config/queue_config.py`, `config/raster_config.py`

---

## Enabler EN5: Pre-flight Validation ✅

**What It Enables**: Early failure before queue submission

| Validator | Description |
|-----------|-------------|
| blob_exists | Validate blob container + name |
| blob_exists_with_size | Combined existence + size check |
| collection_exists | Validate STAC collection |
| stac_item_exists | Validate STAC item |

**Key Files**: `infrastructure/validators.py`

---

# BACKLOG ENABLERS

## Enabler EN6: Long-Running Task Infrastructure ⏳ FY26 DECISION PENDING

**Purpose**: Docker-based worker for tasks exceeding Azure Functions 30-min timeout
**What It Enables**: E2 (oversized rasters), E9 (large climate datasets)
**Reference**: See architecture diagram at `/api/interface/health`
**Owner**: DevOps (infrastructure) + Geospatial Team (handler integration)

**Decision Context**: Deploy as part of FY26 work is pending. Current chunked processing
in Azure Functions handles most use cases. EN6 activates if:
- FATHOM data volumes exceed Function App timeout limits
- Climate data (E9) requires multi-hour processing jobs
- Production workloads demonstrate need for dedicated worker

### EN6 Stories

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| EN6.1 | 📋 | Create **Long-Running Worker** Docker image | DevOps | Image builds, contains GDAL 3.6+, rasterio, xarray, fsspec, adlfs |
| EN6.2 | 📋 | Deploy **Long-Running Worker** to Azure | DevOps | Container runs, has managed identity, can access **Bronze/Silver Storage** |
| EN6.3 | 📋 | Create **Long-Running Task Queue** | DevOps | Queue exists in Service Bus namespace, dead-letter enabled |
| EN6.4 | 📋 | Implement queue listener | DevOps | Worker receives messages, logs receipt, acks on completion |
| EN6.5 | 📋 | Integrate existing handlers | Geospatial | Worker calls `raster_cog.py` functions, writes to **Silver Storage** |
| EN6.6 | 📋 | Add health endpoint | DevOps | `/health` returns 200, shows queue connection status |
| EN6.7 | 📋 | Add routing logic in **ETL Function App** | Geospatial | Jobs exceeding size threshold route to **Long-Running Task Queue** |

### EN6.1 Docker Image Specification

```dockerfile
# Base: Official GDAL image (includes Python + GDAL bindings)
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.6.4

# Python dependencies (copy from ETL Function App requirements)
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

# Required packages:
# - rasterio>=1.3.0
# - xarray>=2023.1.0
# - zarr>=2.14.0
# - fsspec>=2023.1.0
# - adlfs>=2023.1.0  (Azure blob access)
# - azure-servicebus>=7.11.0
# - azure-identity>=1.14.0

COPY worker/ /app/worker/
WORKDIR /app
CMD ["python", "-m", "worker.main"]
```

### EN6.4 Message Schema

```json
{
  "task_id": "uuid",
  "job_id": "uuid",
  "task_type": "process_large_raster",
  "parameters": {
    "source_blob": "bronze://container/path/to/large.tif",
    "destination_blob": "silver://container/path/to/output.tif",
    "compression": "lzw",
    "options": {}
  },
  "retry_count": 0,
  "submitted_at": "2025-12-19T12:00:00Z"
}
```

### EN6.4 Queue Listener Pattern

```python
# worker/main.py (skeleton)
from azure.servicebus import ServiceBusClient
from azure.identity import DefaultAzureCredential

def process_message(message):
    """Route to appropriate handler based on task_type."""
    payload = json.loads(str(message))
    task_type = payload["task_type"]

    if task_type == "process_large_raster":
        from handlers.raster_cog import process_cog
        result = process_cog(payload["parameters"])
    # ... other task types

    # Report completion back to App Database
    update_task_status(payload["task_id"], "completed", result)

def main():
    credential = DefaultAzureCredential()
    client = ServiceBusClient(namespace, credential)
    receiver = client.get_queue_receiver("long-running-raster-tasks")

    for message in receiver:
        try:
            process_message(message)
            receiver.complete_message(message)
        except Exception as e:
            receiver.dead_letter_message(message, reason=str(e))

if __name__ == "__main__":
    main()
```

**Enables**:
- F2.6 (Large Raster Support) - files exceeding chunked processing limits

---

## Enabler: Repository Pattern Enforcement 🔵

**Purpose**: Eliminate remaining direct database connections

| Task | Status | Notes |
|------|--------|-------|
| Fix triggers/schema_pydantic_deploy.py | ⬜ | Has psycopg.connect |
| Fix triggers/health.py | ⬜ | Has psycopg.connect |
| Fix core/schema/sql_generator.py | ⬜ | Has psycopg.connect |
| Fix core/schema/deployer.py | ⬜ | Review for direct connections |

---

## Enabler: Dead Code Audit 🔵

**Purpose**: Remove orphaned code, reduce maintenance burden

| Task | Status |
|------|--------|
| Audit core/ folder | ⬜ |
| Audit infrastructure/ folder | ⬜ |
| Remove commented-out code | ⬜ |
| Update FILE_CATALOG.md | ⬜ |

---

# COMPLETED ENABLERS (ADDITIONAL)

## Enabler: PgSTAC Repository Consolidation ✅

**Purpose**: Fix "Collection not found after insertion" - two classes manage pgSTAC data
**Completed**: DEC 2025

| Task | Status |
|------|--------|
| Rename PgStacInfrastructure → PgStacBootstrap | ✅ |
| Create PgStacRepository | ✅ |
| Move data operations to PgStacRepository | ✅ |
| Remove duplicate methods | ✅ |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `infrastructure/pgstac_repository.py`

---

