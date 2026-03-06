# Claude Context - Azure Geospatial ETL Pipeline

**Date**: 23 DEC 2025
**Primary Documentation**: Start here for all Claude instances

---

## 🎯 What This System Does

A **geospatial ETL platform** that processes raster and vector data into standards-compliant APIs:

```
Bronze Storage (raw files) → CoreMachine (orchestration) → Silver Storage (COGs) + PostGIS + STAC
                                    ↓
                           Standards-Compliant APIs:
                           • OGC API - Features (vector queries)
                           • STAC API (metadata search)
                           • TiTiler (dynamic tile serving)
```

**Core Capabilities**:
- **Raster Processing**: GeoTIFF → Cloud-Optimized GeoTIFF (COG) with STAC metadata
- **Vector Processing**: GeoJSON/Shapefile/CSV → PostGIS with OGC Features API
- **Job Orchestration**: Multi-stage workflows with parallel task execution

---

## 🚀 Quick Start

### Active Environment
- **Function App**: `rmhazuregeoapi` (B3 Basic tier)
- **URL**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
- **Database**: rmhpostgres.postgres.database.azure.com (PostgreSQL 17, B2s)
- **Resource Group**: `rmhazure_rg`

### Essential Commands
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Health Check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Full Schema Rebuild (after deployment)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/full-rebuild?confirm=yes"

# Submit Test Job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# Check Job Status
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## 🏗️ Architecture Overview

### Two-Layer Design

```
┌────────────────────────────────────────────────────────────┐
│                    PLATFORM LAYER                           │
│  Client-agnostic REST API                                   │
│  "Give me data, I'll give you API endpoints"                │
│                                                             │
│  Input: ProcessingRequest (data_type, source_location)      │
│  Output: API endpoints (OGC Features, STAC, tiles)          │
└─────────────────────────┬──────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────────┐
│                    COREMACHINE                              │
│  Universal Job Orchestration Engine (~450 lines)            │
│                                                             │
│  Pattern: Composition over Inheritance                      │
│  ✅ StateManager (database ops)                             │
│  ✅ OrchestrationManager (task creation)                    │
│  ✅ All work delegated to specialized components            │
└────────────────────────────────────────────────────────────┘
```

### Job→Stage→Task Pattern

```
JOB (Blueprint)
 ├── STAGE 1 (Sequential)
 │   ├── Task A (Parallel) ┐
 │   ├── Task B (Parallel) ├─ All tasks run concurrently
 │   └── Task C (Parallel) ┘  Last task triggers stage completion
 │
 ├── STAGE 2 (waits for Stage 1)
 │   └── Tasks...
 │
 └── COMPLETION (aggregation & final status)
```

**Key Pattern: "Last Task Turns Out the Lights"**
- Advisory locks enable unlimited parallelism without deadlocks
- Exactly one task detects completion and advances stage

### Database Schemas

| Schema | Purpose | Management |
|--------|---------|------------|
| `app` | Jobs, tasks, API requests | Pydantic → SQL generator |
| `pgstac` | STAC metadata catalog | pypgstac migrate |
| `geo` | User vector/raster data | Dynamic at runtime |
| `h3` | H3 hexagonal grids | Static SQL |
| `platform` | API request tracking | Pydantic → SQL generator |

---

## 📁 Project Structure

```
rmhgeoapi/
├── function_app.py          # Azure Functions entry point
├── CLAUDE.md                # → Points here
│
├── config/                  # Modular configuration
│   └── *.py                 # app, database, queue, raster, storage, vector
│
├── core/                    # CoreMachine orchestration engine
│   ├── machine.py           # Main orchestrator (~450 lines)
│   ├── state_manager.py     # Database operations
│   ├── models/              # Pydantic models (JobRecord, TaskRecord, etc.)
│   └── schema/              # DDL generation from Pydantic
│
├── infrastructure/          # Repository pattern implementations
│   ├── postgresql.py        # Database access
│   ├── service_bus.py       # Message queues
│   └── blob.py              # Azure Blob Storage
│
├── jobs/                    # Job definitions (JobBase + JobBaseMixin)
│   ├── base.py              # JobBase ABC
│   ├── mixins.py            # JobBaseMixin (77% less boilerplate)
│   ├── process_raster_v2.py # Raster ETL
│   ├── process_vector.py    # Vector ETL
│   └── *.py                 # Other job types
│
├── services/                # Business logic & task handlers
│   ├── raster/              # COG creation, tiling
│   ├── vector/              # PostGIS operations
│   └── *.py                 # Handler implementations
│
├── triggers/                # HTTP/Service Bus endpoints
│   ├── jobs.py              # Job submission/status
│   ├── platform.py          # Platform layer API
│   └── *.py                 # Other endpoints
│
├── ogc_features/            # OGC API - Features (standalone)
├── stac_api/                # STAC API endpoints
│
└── docs_claude/             # Claude documentation (YOU ARE HERE)
    ├── CLAUDE_CONTEXT.md    # 🎯 THIS FILE - Start here
    ├── TODO.md              # Active tasks
    ├── HISTORY.md           # Completed work
    ├── JOB_CREATION_QUICKSTART.md  # New job guide
    └── *.md                 # Other reference docs
```

---

## 🔧 Creating New Jobs

**Use JobBaseMixin** - 77% less code, 30 minutes instead of 2 hours.

```python
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class MyJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    job_type = "my_job"
    description = "What this job does"

    stages = [
        {"number": 1, "name": "process", "task_type": "my_handler", "parallelism": "single"}
    ]

    parameters_schema = {
        'param': {'type': 'str', 'required': True}
    }

    @staticmethod
    def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
        return [{"task_id": f"{job_id[:8]}-s1", "task_type": "my_handler", "parameters": {}}]

    @staticmethod
    def finalize_job(context=None):
        return {"status": "completed", "job_type": "my_job"}
```

**Full guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`

---

## 🔍 Debugging & Monitoring

### Database Endpoints
```bash
# Job details
curl .../api/dbadmin/jobs/{JOB_ID}

# Tasks for job
curl .../api/dbadmin/tasks/{JOB_ID}

# Failed jobs
curl ".../api/dbadmin/jobs?status=failed&limit=10"

# Database stats
curl ".../api/dbadmin/diagnostics?type=stats"
```

### Application Insights
```bash
# Create query script (recommended pattern)
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

---

## 📚 Documentation Map

### Primary Documents
| Document | Purpose |
|----------|---------|
| **CLAUDE_CONTEXT.md** | 🎯 START HERE - System overview |
| **TODO.md** | Active tasks only |

### Architecture Layer
| Document | Purpose |
|----------|---------|
| **ARCHITECTURE_REFERENCE.md** | Deep technical specs, job patterns, error handling |
| **ARCHITECTURE_DIAGRAMS.md** | Visual C4/Mermaid diagrams |
| **COREMACHINE_PLATFORM_ARCHITECTURE.md** | Two-layer design details |
| **SCHEMA_ARCHITECTURE.md** | PostgreSQL 5-schema design |
| **SERVICE_BUS_HARMONIZATION.md** | Queue configuration |

### Operations Layer
| Document | Purpose |
|----------|---------|
| **DEPLOYMENT_GUIDE.md** | Deployment procedures |
| **APPLICATION_INSIGHTS.md** | Log queries and diagnostics |
| **MEMORY_PROFILING.md** | Performance optimization |

### Development Layer
| Document | Purpose |
|----------|---------|
| **JOB_CREATION_QUICKSTART.md** | New job creation guide |
| **OGC_FEATURES_METADATA_INTEGRATION.md** | OGC API integration |
| **ZARR_TITILER_LESSONS.md** | Zarr/TiTiler lessons learned |
| **MICROSERVICES_ARCHITECTURE.md** | Queue-based decoupling, future Function App separation |

### Pipeline Projects
| Document | Purpose |
|----------|---------|
| **FATHOM_ETL.md** | FATHOM flood data pipeline |
| **BUILDING_EXPOSURE_PIPELINE.md** | Building exposure analytics |
| **PIPELINE_BUILDER_VISION.md** | Future pipeline builder UI |

### History & Archives
| Document | Purpose |
|----------|---------|
| **HISTORY.md** | Main completed work log |
| **HISTORY_ARCHIVE_DEC2025.md** | TODO cleanup archive |

### Human Documentation (WIKI_*.md in root)
- `WIKI_ONBOARDING.md` - Comprehensive developer guide
- `WIKI_TECHNICAL_OVERVIEW.md` - Architecture for humans
- `WIKI_API_*.md` - API documentation (6 files)
- `WIKI_QUICK_START.md` - Quick start guide

---

## 🚨 Critical Reminders

1. **Function App**: Use `rmhazuregeoapi` ONLY (not rmhgeoapibeta, rmhgeoapi, etc.)
2. **Schema Rebuild**: Required after deployment: `/api/dbadmin/maintenance/full-rebuild?confirm=yes`
3. **No Backward Compatibility**: Fail fast with clear errors (development mode)
4. **Prefer Editing**: Always edit existing files over creating new ones
5. **Date Format**: Use military format (05 DEC 2025)

---

**Last Updated**: 05 DEC 2025
