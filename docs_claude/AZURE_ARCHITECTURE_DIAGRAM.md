# Azure Architecture Diagram - rmhgeoapi System

**Date**: 5 NOV 2025
**Purpose**: Visual reference for corporate Azure deployment
**Source**: Personal Azure tenant (rmhazure)

---

## 🏗️ High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Azure Resource Group                          │
│                          (rmhazure_rg)                               │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │         Azure Function App (rmhgeoapibeta)                  │    │
│  │  ┌──────────────────────────────────────────────────────┐  │    │
│  │  │  Python 3.12 Runtime                                  │  │    │
│  │  │  - HTTP Triggers (job submission)                     │  │    │
│  │  │  - Service Bus Triggers (job/task processing)         │  │    │
│  │  │  - Timer Triggers (monitoring)                        │  │    │
│  │  │                                                        │  │    │
│  │  │  Managed Identity: 995badc6-9b03-481f...             │  │    │
│  │  └────────────┬────────────────┬────────────────┬────────┘  │    │
│  └───────────────┼────────────────┼────────────────┼───────────┘    │
│                  │                │                │                │
│                  ▼                ▼                ▼                │
│  ┌───────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │  Storage Account  │  │  Service Bus    │  │   PostgreSQL     │ │
│  │  (rmhazuregeo)    │  │  (rmhazure)     │  │   (rmhpgflex)    │ │
│  │                   │  │                 │  │                  │ │
│  │  28 Containers:   │  │  2 Queues:      │  │  4 Schemas:      │ │
│  │  - Bronze         │  │  - jobs         │  │  - geo           │ │
│  │  - Silver         │  │  - tasks        │  │  - app           │ │
│  │  - Gold           │  │                 │  │  - pgstac        │ │
│  │  - Temp           │  │  Standard Tier  │  │  - platform      │ │
│  │  - STAC assets    │  │  Lock: PT5M     │  │                  │ │
│  │  - Tiles/Vectors  │  │  Retries: 3     │  │  PostGIS 3.4+    │ │
│  │                   │  │                 │  │  PostgreSQL 17   │ │
│  │  Standard_RAGRS   │  │                 │  │  Standard_B1ms   │ │
│  └───────────────────┘  └─────────────────┘  └──────────────────┘ │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Data Flow Architecture

### 1. Job Submission Flow (HTTP → Queue → Processing)

```
┌─────────┐
│  User   │
│ Browser │
└────┬────┘
     │ HTTP POST /api/jobs/submit/{job_type}
     │ {"message": "test", "n": 3}
     │
     ▼
┌────────────────────────────────────────────────────────┐
│  Azure Function App - HTTP Trigger                     │
│  (trigger_job_submit.py)                               │
│                                                         │
│  1. Validate job parameters                            │
│  2. Generate job_id (SHA256 hash)                      │
│  3. Check idempotency (duplicate job?)                 │
│  4. Create job record in PostgreSQL                    │
│  5. Send message to Service Bus                        │
└────────────────────┬───────────────────────────────────┘
                     │
                     │ Queue message
                     │ {"job_id": "abc123...", "job_type": "hello_world"}
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Azure Service Bus - geospatial-jobs queue              │
│                                                          │
│  Lock Duration: PT5M (5 minutes)                        │
│  Max Delivery Count: 3 retries                          │
│  Message TTL: P7D (7 days)                              │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ Trigger function
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│  Azure Function App - Service Bus Trigger                │
│  (trigger_job_processor.py)                              │
│                                                           │
│  1. Acquire message lock (auto-renewed for 30 min)       │
│  2. Load job from PostgreSQL                             │
│  3. Execute job controller (create tasks)                │
│  4. Send tasks to geospatial-tasks queue                 │
│  5. Complete message (auto on success)                   │
└──────────────────────────────────────────────────────────┘
```

### 2. Task Processing Flow (Fan-out Parallel Processing)

```
┌─────────────────────────────────────────────────────────┐
│  Azure Service Bus - geospatial-tasks queue             │
│                                                          │
│  Lock Duration: PT5M (5 minutes)                        │
│  Max Delivery Count: 3 retries                          │
│                                                          │
│  Example: 100 tasks for Stage 1 (all parallel)          │
└────────┬──────┬──────┬──────┬──────┬──────┬─────────────┘
         │      │      │      │      │      │
         ▼      ▼      ▼      ▼      ▼      ▼
    ┌────┴──────┴──────┴──────┴──────┴──────┴────┐
    │  Azure Function App - Service Bus Trigger   │
    │  (trigger_task_processor.py)                │
    │                                              │
    │  maxConcurrentCalls: 1 (controlled scale)   │
    │  autoComplete: true                          │
    │  maxAutoLockRenewalDuration: 00:30:00       │
    │                                              │
    │  Each instance:                              │
    │  1. Load task from PostgreSQL                │
    │  2. Execute task handler (business logic)    │
    │  3. Write results to PostgreSQL              │
    │  4. Update task status to COMPLETED          │
    │  5. Check if last task in stage              │
    │  6. Advance stage if all tasks done          │
    └──────────────────────────────────────────────┘
```

### 3. Stage Advancement Flow (Last Task Turns Out Lights)

```
┌───────────────────────────────────────────────────────────┐
│  PostgreSQL - Stage Completion Detection                  │
│  (Atomic operation with advisory locks)                   │
│                                                            │
│  Task 98 completes:                                       │
│  ┌───────────────────────────────────────────────────┐   │
│  │ BEGIN TRANSACTION;                                 │   │
│  │ SELECT pg_advisory_xact_lock(hashtext(job||stage));│   │
│  │ UPDATE tasks SET status='COMPLETED' WHERE id=98;   │   │
│  │ SELECT COUNT(*) FROM tasks WHERE stage=1 AND      │   │
│  │   status != 'COMPLETED'; -- Result: 2 remaining   │   │
│  │ -- Not last task, exit                             │   │
│  │ COMMIT;                                            │   │
│  └───────────────────────────────────────────────────┘   │
│                                                            │
│  Task 100 completes (last task):                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │ BEGIN TRANSACTION;                                 │   │
│  │ SELECT pg_advisory_xact_lock(hashtext(job||stage));│   │
│  │ UPDATE tasks SET status='COMPLETED' WHERE id=100;  │   │
│  │ SELECT COUNT(*) FROM tasks WHERE stage=1 AND      │   │
│  │   status != 'COMPLETED'; -- Result: 0 remaining   │   │
│  │ -- Last task! Advance stage                        │   │
│  │ UPDATE jobs SET stage=2, status='PROCESSING';      │   │
│  │ -- Send stage completion message to jobs queue     │   │
│  │ COMMIT;                                            │   │
│  └───────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
                         │
                         │ Queue message (stage advance)
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Service Bus - geospatial-jobs queue                     │
│  Message: {"job_id": "abc123", "action": "advance"}      │
└──────────────────────────────────────────────────────────┘
```

---

## 🔐 Security & Identity Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                  Azure Active Directory (AAD)                    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Managed Identity (System-Assigned)                    │    │
│  │  Principal ID: 995badc6-9b03-481f-9544-9f5957dd893d   │    │
│  │                                                         │    │
│  │  Associated with: Azure Function App (rmhgeoapibeta)   │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                  │
│          ┌──────────────────┼──────────────────┐               │
│          │                  │                  │               │
│          ▼                  ▼                  ▼               │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  RBAC Role    │  │  RBAC Role   │  │  Firewall Rule   │   │
│  │  Assignment   │  │  Assignment  │  │  (Future: MI)    │   │
│  │               │  │              │  │                  │   │
│  │  Storage Blob │  │  Service Bus │  │  PostgreSQL      │   │
│  │  Data         │  │  Data Owner  │  │  Allow: 0.0.0.0  │   │
│  │  Contributor  │  │              │  │  (Azure services)│   │
│  └───────┬───────┘  └──────┬───────┘  └──────┬───────────┘   │
└──────────┼──────────────────┼──────────────────┼───────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐
  │  Storage       │  │  Service Bus │  │  PostgreSQL      │
  │  Account       │  │  Namespace   │  │  Server          │
  │                │  │              │  │                  │
  │  Passwordless  │  │  Passwordless│  │  Password auth   │
  │  access via MI │  │  access via  │  │  (temp - migrate │
  │                │  │  MI          │  │   to MI later)   │
  └────────────────┘  └──────────────┘  └──────────────────┘
```

---

## 📦 Storage Container Organization

```
Azure Storage Account: rmhazuregeo
├── Data Tier Containers (Primary workflow)
│   ├── rmhazuregeobronze/          (Raw data ingestion)
│   │   └── user_uploads/
│   │       ├── maxar_imagery/
│   │       ├── sentinel_data/
│   │       └── custom_datasets/
│   │
│   ├── rmhazuregeosilver/          (Processed data)
│   │   └── (Landing zone for processed outputs)
│   │
│   └── rmhazuregeogold/            (Analytics-ready)
│       └── geoparquet_exports/
│
├── Processing Containers (Specialized outputs)
│   ├── silver-cogs/                (Cloud-Optimized GeoTIFFs)
│   │   └── tiled_rasters/
│   │
│   ├── silver-tiles/               (Raster tiles)
│   │   ├── xyz_tiles/
│   │   └── mbtiles/
│   │
│   ├── silver-vectors/             (Vector datasets)
│   │   ├── geojson/
│   │   └── shapefiles/
│   │
│   └── silver-stac-assets/         (STAC metadata)
│       └── collection_metadata/
│
├── System Containers (Infrastructure)
│   ├── rmhazuregeotemp/            (Temporary processing)
│   ├── rmhazuregeoinventory/       (Blob inventory snapshots)
│   ├── rmhazuregeopipelines/       (Pipeline state/config)
│   ├── azure-webjobs-hosts/        (Function App runtime)
│   └── azure-webjobs-secrets/      (Function App secrets)
│
└── Web Containers
    └── $web/                       (Static website - OGC Features map)
        └── index.html
```

---

## 🗄️ PostgreSQL Schema Organization

```
PostgreSQL Server: rmhpgflex.postgres.database.azure.com
Database: (default postgres db)

├── geo schema (Geospatial data - PostGIS tables)
│   ├── Vector tables:
│   │   ├── fresh_test_stac           (Example collection)
│   │   ├── maxar_footprints
│   │   └── (other geospatial layers)
│   │
│   └── PostGIS extensions:
│       ├── postgis
│       ├── postgis_topology
│       └── postgis_raster
│
├── app schema (CoreMachine orchestration)
│   ├── jobs                          (Job state table)
│   │   ├── id (PK, job_id SHA256)
│   │   ├── job_type (hello_world, process_large_raster, etc.)
│   │   ├── status (PENDING, PROCESSING, COMPLETED, FAILED)
│   │   ├── stage (1, 2, 3, etc.)
│   │   ├── parameters (JSONB)
│   │   ├── result_data (JSONB)
│   │   └── created_at, updated_at
│   │
│   └── tasks                         (Task state table)
│       ├── id (PK, UUID)
│       ├── job_id (FK → jobs.id)
│       ├── task_type (handler name)
│       ├── status (PENDING, PROCESSING, COMPLETED, FAILED)
│       ├── stage (1, 2, 3)
│       ├── parameters (JSONB)
│       ├── result_data (JSONB)
│       ├── retry_count (0-3)
│       └── created_at, updated_at
│
├── pgstac schema (STAC API metadata catalog)
│   ├── collections                   (STAC collections)
│   ├── items                         (STAC items)
│   ├── search functions              (pgstac search API)
│   └── (pgstac internal tables)
│
└── platform schema (API request tracking)
    ├── api_requests                  (HTTP request log)
    └── orchestration_jobs            (Multi-job orchestration)
```

---

## ⚙️ Configuration Harmonization Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Azure Service Bus (Infrastructure Configuration)  │
│                                                              │
│  Queue: geospatial-tasks                                    │
│  ┌────────────────────────────────────────────────────┐    │
│  │ lockDuration: PT5M (5 minutes)                     │    │
│  │ maxDeliveryCount: 3                                │    │
│  │ maxSizeInMegabytes: 1024                           │    │
│  │ defaultMessageTimeToLive: P7D (7 days)             │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────────┘
                      │ Must be ≤
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Azure Functions (host.json Runtime Config)        │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ functionTimeout: "00:30:00"                        │    │
│  │ extensions.serviceBus:                             │    │
│  │   prefetchCount: 0                                 │    │
│  │   messageHandlerOptions:                           │    │
│  │     autoComplete: true                             │    │
│  │     maxConcurrentCalls: 1                          │    │
│  │     maxAutoLockRenewalDuration: "00:30:00"         │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────────┘
                      │ Should equal
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Application (config.py Business Logic)            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ function_timeout_minutes: int = 30                 │    │
│  │ task_max_retries: int = 3                          │    │
│  │ task_retry_base_delay: int = 5                     │    │
│  │ task_retry_max_delay: int = 300                    │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

Validation Rule:
PT5M ≤ 00:30:00 = 00:30:00 = 30 minutes ✅

This ensures:
- Lock renewed automatically for up to 30 minutes
- No premature message redelivery
- No race conditions from duplicate processing
```

---

## 🌐 Network Topology (Current: Public Access)

```
Internet
    │
    │ HTTPS (443)
    │
    ▼
┌────────────────────────────────────────────────────────┐
│  Azure Function App                                    │
│  URL: rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01...     │
│                                                         │
│  Public Endpoints:                                     │
│  - /api/health                                         │
│  - /api/jobs/submit/{job_type}                        │
│  - /api/jobs/status/{job_id}                          │
│  - /api/features/*  (OGC Features API)                │
│  - /api/collections/*  (STAC API)                     │
└────────┬──────────────┬─────────────┬─────────────────┘
         │              │             │
         │              │             │ Azure internal network
         │              │             │ (Service endpoints)
         │              │             │
         ▼              ▼             ▼
┌──────────────┐  ┌──────────┐  ┌──────────────────┐
│  Storage     │  │ Service  │  │  PostgreSQL      │
│  Account     │  │ Bus      │  │  Server          │
│              │  │          │  │                  │
│  Public:     │  │ Internal │  │  Firewall:       │
│  - Blob API  │  │ only     │  │  - 0.0.0.0 (AZ)  │
│  - Static    │  │          │  │  - Client IPs    │
│    website   │  │          │  │                  │
└──────────────┘  └──────────┘  └──────────────────┘
```

### Optional: Enhanced Security with Private Endpoints

```
Internet
    │
    │ HTTPS (443)
    │
    ▼
┌────────────────────────────────────────────────────────┐
│  Azure Front Door / Application Gateway (Optional)     │
│  - WAF protection                                      │
│  - DDoS protection                                     │
│  - Custom domain                                       │
└────────┬───────────────────────────────────────────────┘
         │
         │ VNet injection
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  Azure Virtual Network (VNet)                          │
│  Address Space: 10.0.0.0/16                           │
│                                                         │
│  ┌──────────────────────────────────────────────────┐ │
│  │  Subnet: functions-subnet (10.0.1.0/24)          │ │
│  │  ┌────────────────────────────────────────────┐  │ │
│  │  │  Azure Function App (VNet integrated)      │  │ │
│  │  └────────┬──────────┬─────────────┬──────────┘  │ │
│  └───────────┼──────────┼─────────────┼─────────────┘ │
│              │          │             │               │
│              │          │             │               │
│  ┌───────────▼──────┐ ┌▼──────────┐ ┌▼──────────┐    │
│  │  Private        │ │  Private  │ │  Private  │    │
│  │  Endpoint       │ │  Endpoint │ │  Endpoint │    │
│  │  (Storage)      │ │  (SvcBus) │ │  (PgSQL)  │    │
│  └─────────────────┘ └───────────┘ └───────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 Monitoring & Observability Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Azure Application Insights                                │
│  App ID: 829adb94-5f5c-46ae-9f00-18e731529222             │
│                                                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Telemetry Data:                                  │    │
│  │  - traces (logs with correlation IDs)            │    │
│  │  - requests (HTTP endpoints)                     │    │
│  │  - dependencies (external calls)                 │    │
│  │  - exceptions (errors and stack traces)          │    │
│  │  - customMetrics (job/task counts)               │    │
│  └──────────────────────────────────────────────────┘    │
│                                                            │
│  KQL Query Examples:                                       │
│  - traces | where severityLevel >= 3                     │
│  - requests | where operation_Name contains "health"      │
│  - dependencies | where name contains "PostgreSQL"        │
└────────────────────────────────────────────────────────────┘
         ▲                  ▲                   ▲
         │                  │                   │
         │ Log stream       │ Metrics           │ Events
         │                  │                   │
┌────────┴──────────────────┴───────────────────┴────────────┐
│  Azure Function App (rmhgeoapibeta)                        │
│                                                             │
│  Python logging → Azure SDK → Application Insights         │
└─────────────────────────────────────────────────────────────┘

Internal Monitoring Endpoints:
- /api/health                  (Health check)
- /api/db/stats                (Database metrics)
- /api/db/jobs                 (Job query endpoint)
- /api/db/tasks/{job_id}       (Task query endpoint)
- /api/db/debug/all            (Full state dump)
```

---

## 🚀 Deployment Pipeline Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Local Development Machine                               │
│  /Users/robertharrison/python_builds/rmhgeoapi          │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │  Code Changes:                                  │    │
│  │  - Python functions                             │    │
│  │  - host.json                                    │    │
│  │  - requirements.txt                             │    │
│  │  - Database schema SQL                          │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────┬────────────────────────────────────┘
                      │
                      │ Azure Functions Core Tools
                      │ func azure functionapp publish rmhgeoapibeta
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Azure Function App - Remote Build                      │
│  rmhgeoapibeta                                          │
│                                                          │
│  Deployment Steps:                                      │
│  1. Upload code to staging directory                    │
│  2. Install Python dependencies (requirements.txt)      │
│  3. Build Python packages                               │
│  4. Deploy to production slot                           │
│  5. Restart function host                               │
└─────────────────────┬───────────────────────────────────┘
                      │
                      │ Post-deployment
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  Database Schema Deployment                             │
│  POST /api/db/schema/redeploy?confirm=yes              │
│                                                          │
│  Actions:                                               │
│  1. Drop and recreate schemas (geo, app, platform)      │
│  2. Create tables with proper types                     │
│  3. Add indexes and constraints                         │
│  4. Install PostgreSQL functions                        │
│  5. Grant permissions                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 📝 Summary: Key Configuration Matrix

| Component | Resource Name | Critical Setting | Value | Why |
|-----------|---------------|------------------|-------|-----|
| **Function App** | rmhgeoapibeta | Runtime | Python 3.12 | Latest stable Python |
| | | Timeout | 00:30:00 | Long-running tasks (raster processing) |
| | | Managed Identity | Enabled | Passwordless auth to Azure services |
| **Storage** | rmhazuregeo | SKU | Standard_RAGRS | Geo-redundancy for data durability |
| | | Container Count | 28 | Bronze/Silver/Gold + specialized containers |
| **Service Bus** | rmhazure | Tier | Standard | Cost-effective for dev/test |
| | | Lock Duration | PT5M | Max allowed on Standard tier |
| | | Max Delivery | 3 | Allow 3 retry attempts |
| **PostgreSQL** | rmhpgflex | Version | 17 | Latest stable with PostGIS support |
| | | SKU | Standard_B1ms | Burstable for cost-effectiveness |
| | | Schemas | 4 | geo, app, pgstac, platform |
| **host.json** | (code file) | functionTimeout | 00:30:00 | Match Function App setting |
| | | maxAutoLockRenewal | 00:30:00 | Auto-renew Service Bus locks |
| | | maxConcurrentCalls | 1 | Controlled concurrency |
| **config.py** | (code file) | timeout_minutes | 30 | Match host.json setting |
| | | task_max_retries | 3 | Match Service Bus max delivery |

---

**Document Status**: Ready for Corporate IT Review
**Last Updated**: 5 NOV 2025
**Related Documents**:
- [CORPORATE_AZURE_CONFIG_REQUEST.md](CORPORATE_AZURE_CONFIG_REQUEST.md) - Full deployment guide
- [AZURE_CONFIG_QUICK_REFERENCE.md](AZURE_CONFIG_QUICK_REFERENCE.md) - Quick reference commands
- [SERVICE_BUS_HARMONIZATION.md](SERVICE_BUS_HARMONIZATION.md) - Configuration harmonization details
