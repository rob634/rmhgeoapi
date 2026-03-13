# Multi-App Architecture (Queue-Based Decoupling)

**Date**: 13 MAR 2026 (Updated to reflect production 3-app deployment)
**Status**: Production Architecture -- Deployed
**Purpose**: Document the deployed multi-app architecture with Service Bus queue decoupling

> **NOTE**: This project uses the **Platform layer as a custom mini-APIM** (API Gateway).
> We do NOT use Azure API Management. The Gateway Function App handles:
> - HTTP endpoint exposure for external clients (DDH)
> - Request validation and translation
> - Queue submission to CoreMachine
> - Authentication (Azure AD / Managed Identity)
>
> **Terminology**: Platform = Gateway = Custom Mini-APIM (interchangeable)

---

## 1. Current Production Architecture

The platform runs as 3 separate Azure apps communicating via Service Bus queues. All 3 deploy from the same codebase; `APP_MODE` controls which endpoints register.

| Role | App Name | APP_MODE | URL |
|------|----------|----------|-----|
| Orchestrator | `rmhazuregeoapi` | `standalone` | https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net |
| Gateway | `rmhgeogateway` | `platform` | https://rmhgeogateway-gdc4hrafawfrcqak.eastus-01.azurewebsites.net |
| Docker Worker | `rmhheavyapi` | `worker_docker` | https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net |

### Shared Resources

| Resource | Value |
|----------|-------|
| Database | `rmhpostgres.postgres.database.azure.com` (database: `geopgflex`) |
| Resource Group | `rmhazure_rg` |
| ACR | `rmhazureacr.azurecr.io` (image: `geospatial-worker`) |
| App Insights | All 3 apps log to same instance (`d3af3d37-cfe3-411f-adef-bc540181cbca`) |
| Service Bus | 3 queues: `geospatial-jobs`, `functionapp-tasks`, `container-tasks` |

### Deprecated Apps (never use)

`rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta`

### Deprecated Database

`rmhpgflex.postgres.database.azure.com` (decommissioned)

---

## 2. APP_MODE Routing

The same codebase deploys to all 3 apps. `APP_MODE` (set via Azure App Settings) controls which endpoints `function_app.py` registers at startup.

| APP_MODE | Registers | Ignores |
|----------|-----------|---------|
| `standalone` | All endpoints + Service Bus triggers | Nothing (full monolith for dev) |
| `platform` | Platform/Gateway HTTP endpoints only | CoreMachine, Service Bus triggers |
| `worker_docker` | Docker task handlers + health | Platform endpoints, HTTP triggers |

`standalone` mode is used for local development and for the Orchestrator in production (it needs both HTTP endpoints for admin/status and Service Bus triggers for job processing). The Gateway and Docker Worker each run a restricted subset.

---

## 3. The Queue Contract

Platform and CoreMachine communicate ONLY via Service Bus queues. This is the fundamental decoupling pattern.

```
Gateway (rmhgeogateway)
  POST /api/platform/submit --> validates, translates, enqueues
         |
         v
  SERVICE BUS (geospatial-jobs queue)  <-- THE CONTRACT BOUNDARY
         |
         v
Orchestrator (rmhazuregeoapi)
  Consumes job message --> creates tasks --> routes to queues
         |
         v
  SERVICE BUS (functionapp-tasks OR container-tasks)
         |
         v
Docker Worker (rmhheavyapi) -- heavy compute (GDAL, geopandas, xarray)
  OR
Orchestrator itself -- lightweight tasks (DB updates, STAC registration)
```

### Detailed Flow

```
Gateway (rmhgeogateway)                  Orchestrator (rmhazuregeoapi)
========================                 ============================

POST /api/platform/submit                Service Bus Trigger
         |                                        |
         v                                        v
  Validate DDH request                   Consume job message
         |                                        |
         v                                        v
  Translate to CoreMachine format        Load job definition
         |                                        |
         v                                        v
  Generate request_id                    Create tasks for stage
         |                                        |
         v                                        v
  Enqueue to Service Bus ===============> Execute handlers
         |                                        |
         v                                        v
  Return {request_id, queued}            Update job/task status


Gateway writes to: platform.platform_requests (tracking)
Orchestrator writes to: app.jobs, app.tasks (orchestration)
Both read from: PostgreSQL (shared instance, separate schemas)
```

Key properties:
- **Gateway knows NOTHING about job execution** -- it enqueues and returns 202
- **CoreMachine knows NOTHING about DDH/Gateway** -- it consumes queue messages
- **The queue is durable and decoupled** -- either side can restart independently
- **Fault isolation is built-in** -- Gateway failure does not affect running jobs

---

## 4. Task Routing

The Orchestrator creates tasks and routes them to the appropriate queue based on task type.

| Queue | Consumer | Task Types |
|-------|----------|------------|
| `geospatial-jobs` | Orchestrator | Job orchestration messages (new job submissions) |
| `functionapp-tasks` | Orchestrator | Lightweight tasks (DB updates, STAC registration, inventory, cleanup) |
| `container-tasks` | Docker Worker | Heavy compute (GDAL, geopandas, xarray, zarr, virtualizarr) |

The routing decision is made by the job definition's `stages` configuration. Each stage specifies a `task_type` which maps to a handler, and the handler's registration determines which queue receives the task.

---

## 5. Why No API Gateway (APIM)

| Reason | Explanation |
|--------|-------------|
| **Cost** | APIM Standard is ~$700/month -- not justified for this use case |
| **Complexity** | Adds another component to manage, configure, debug |
| **Not Needed** | Service Bus queues provide all necessary decoupling |
| **Auth in Code** | Function Apps validate Azure AD tokens directly |

### Security Without APIM

Each app handles its own authentication:
- **Gateway**: Azure AD / Managed Identity validation for external clients (DDH)
- **Orchestrator**: Admin endpoints protected by Azure AD
- **Docker Worker**: Internal only -- consumes from Service Bus (SAS auth)
- **Inter-app**: Service Bus shared access signatures

---

## 6. Deployment

Use `deploy.sh` for all deployments -- it handles versioning, health checks, and verification.

```bash
./deploy.sh orchestrator   # Deploy Orchestrator (rmhazuregeoapi)
./deploy.sh gateway        # Deploy Gateway (rmhgeogateway)
./deploy.sh docker         # Deploy Docker Worker (rmhheavyapi)
./deploy.sh all            # Deploy all 3 apps
```

### What the Script Does

1. Reads version from `config/__init__.py`
2. Deploys to the target app(s)
3. Waits for restart (45s for Function Apps, 60s for Docker)
4. Runs health check
5. Verifies deployed version matches expected

### Manual Commands (Reference)

```bash
# Function Apps (Orchestrator or Gateway)
func azure functionapp publish rmhazuregeoapi --python --build remote
func azure functionapp publish rmhgeogateway --python --build remote

# Docker Worker
az acr build --registry rmhazureacr --image geospatial-worker:VERSION --file Dockerfile .
az webapp config container set --name rmhheavyapi --resource-group rmhazure_rg \
  --docker-custom-image-name "rmhazureacr.azurecr.io/geospatial-worker:VERSION"
az webapp stop --name rmhheavyapi --resource-group rmhazure_rg && \
az webapp start --name rmhheavyapi --resource-group rmhazure_rg
```

---

## 7. Key Design Decisions

1. **No APIM** -- Cost (~$700/mo) and complexity not justified. Service Bus provides all decoupling needed.
2. **Shared codebase, APP_MODE routing** -- Single repo, 3 deployments. Eliminates code duplication and drift.
3. **Shared database, separate schemas** -- All apps connect to `geopgflex` on `rmhpostgres`. Schemas: `app`, `pgstac`, `geo`, `h3`, `platform`.
4. **All apps log to same App Insights** -- Cross-app correlation via `service.namespace = "rmhgeo-platform"`. Instance: `d3af3d37-cfe3-411f-adef-bc540181cbca`.
5. **Docker Worker uses ACR images** -- `rmhazureacr.azurecr.io/geospatial-worker:VERSION`. Heavy dependencies (GDAL, geopandas, xarray) isolated in container.
6. **psycopg3 connection pooling per app** -- Each app manages its own connection pool. Monitor connection limits across all 3 apps.

---

## 8. Related Documents

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Deep technical specs, error handling patterns |
| [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) | Visual C4/Mermaid diagrams |
| [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) | Deployment procedures and troubleshooting |
| [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md) | Docker worker details and parallelism model |
| [SERVICE_BUS_HARMONIZATION.md](./SERVICE_BUS_HARMONIZATION.md) | Queue configuration and message contracts |
| [PLATFORM_STANDARDIZATION.md](../PLATFORM_STANDARDIZATION.md) | Cross-app seam analysis |
