# Production Architecture: Function App Separation Strategy

**Date**: 06 DEC 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: PROPOSAL - Pending Review

---

## Executive Summary

The current monolithic Function App should be split based on **workload characteristics**, not just functional boundaries. Raster (GDAL) and Vector (geopandas/PostGIS) operations have fundamentally opposite resource and concurrency requirements.

**Key Insight:** You cannot optimize `host.json` for both workloads simultaneously:
- Setting `maxConcurrentCalls: 2` for raster safety kills vector parallelism
- Setting it to 20+ for vector throughput risks OOM on raster jobs

---

## Current State Analysis

### Workload Characteristics

| Workload | Memory per Op | CPU Profile | Ideal Concurrency | Current Setting |
|----------|---------------|-------------|-------------------|-----------------|
| **Raster (GDAL)** | 2-8+ GB | Heavy (reprojection, COG) | LOW (1-2 concurrent) | `maxConcurrentCalls: 2` |
| **Vector (geopandas)** | 20-200 MB | Light (chunk uploads) | HIGH (20-100+ concurrent) | Same as raster 😬 |

### Current Monolith Constraints

- **Single `host.json`**: Cannot tune for both workload types
- **Shared memory pool**: GDAL operations can OOM when vector jobs are running
- **30-minute hard limit**: Files >30-50GB cannot complete processing
- **Compromised concurrency**: Vector throughput sacrificed for raster stability

---

## Proposed Architecture: 4 Function Apps

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AZURE API MANAGEMENT (Future)                     │
│                    https://geospatial.rmh.org/api/*                  │
└───────────┬───────────────┬───────────────┬───────────────┬─────────┘
            │               │               │               │
            ▼               ▼               ▼               ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  API Gateway  │ │ Raster Worker │ │ Vector Worker │ │ Long-Running  │
    │   (B3 Basic)  │ │  (B3 Basic)   │ │  (B3 Basic)   │ │   (App Svc)   │
    │               │ │               │ │               │ │               │
    │ • HTTP APIs   │ │ • GDAL ops    │ │ • geopandas   │ │ • Container   │
    │ • Job submit  │ │ • COG create  │ │ • PostGIS     │ │ • 50GB+ TIFFs │
    │ • OGC/STAC    │ │ • STAC raster │ │ • STAC vector │ │ • No timeout  │
    │ • Platform    │ │               │ │               │ │               │
    └───────┬───────┘ └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
            │               │               │               │
            └───────────────┴───────────────┴───────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │    Azure Service Bus   │
                        │  • geospatial-jobs     │
                        │  • raster-tasks        │ ← NEW: separate queues
                        │  • vector-tasks        │ ← NEW: separate queues
                        │  • longrun-tasks       │ ← NEW: for huge files
                        └───────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │  Azure PostgreSQL      │
                        │  (shared database)     │
                        │  • app schema          │
                        │  • pgstac schema       │
                        │  • geo schema          │
                        └───────────────────────┘
```

---

## Function App Specifications

### 1. API Gateway (rmhgeo-api)

**Purpose:** HTTP endpoints, job submission, read-only operations

**host.json Configuration:**
```json
{
  "version": "2.0",
  "functionTimeout": "00:02:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 5,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 16,
        "maxAutoLockRenewalDuration": "00:02:00"
      }
    }
  }
}
```

**Contains:**
- `triggers/` - All HTTP endpoints
- `ogc_features/` - OGC API Features
- `stac_api/` - STAC API
- `web_interfaces/` - Dashboard UIs
- Job submission (writes to `geospatial-jobs` queue)
- Status endpoints (reads from PostgreSQL)

**Why Separate:** Fast response times, high concurrency, no memory-intensive operations.

**Resource Profile:**
- **B3 Basic** (14 GB RAM, 4 vCPU)
- Focus on low latency, high throughput for API responses
- No GDAL or heavy processing dependencies

---

### 2. Raster Worker (rmhgeo-raster)

**Purpose:** GDAL-intensive raster processing

**host.json Configuration:**
```json
{
  "version": "2.0",
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 0,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 1,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

**Contains:**
- `jobs/process_raster_v2.py`
- `services/raster/` - validate_raster, create_cog, extract_stac_metadata handlers
- Listens to `raster-tasks` queue only

**Resource Profile:**
- **B3 Basic** (14 GB RAM, 4 vCPU) - or P1V3 Premium if needed
- **maxConcurrentCalls: 1** (MAYBE 2 max)
- Each COG operation can use 2-8 GB RAM during reprojection

**Why Separate:** GDAL is a memory beast. Isolation prevents OOM from killing vector jobs.

**Critical Settings:**
- `maxConcurrentCalls: 1` - GDAL operations need all available memory
- `prefetchCount: 0` - Don't prefetch; process one message at a time
- Long lock renewal for 30-minute operations

---

### 3. Vector Worker (rmhgeo-vector)

**Purpose:** geopandas/PostGIS operations - embarrassingly parallel workload

**host.json Configuration:**
```json
{
  "version": "2.0",
  "functionTimeout": "00:10:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 5,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 32,
        "maxAutoLockRenewalDuration": "00:10:00"
      }
    }
  }
}
```

**Contains:**
- `jobs/process_vector.py`
- `services/vector/` - process_vector_prepare, process_vector_upload, create_vector_stac handlers
- Listens to `vector-tasks` queue only

**Resource Profile:**
- **B3 Basic** (14 GB RAM)
- **maxConcurrentCalls: 32** (or higher!)
- Each chunk upload: 20-200 MB RAM

**Why Separate:** Embarrassingly parallel workload benefits from aggressive concurrency.

**Critical Settings:**
- `maxConcurrentCalls: 32` - High parallelism for chunk uploads
- `prefetchCount: 5` - Aggressive prefetch for throughput
- Shorter timeout (chunks process faster than raster)

---

### 4. Long-Running Worker (Azure Container Apps)

**Purpose:** Files too large for 30-minute Function timeout (50GB+ TIFFs)

**When to Use:**
- Input TIFF > 30-50 GB
- Estimated processing time > 25 minutes
- Pre-flight size check redirects to this service

#### Recommended: Azure Container Apps

```yaml
# container-app.yaml
name: rmhgeo-longrun
properties:
  configuration:
    activeRevisionsMode: Single
    secrets:
      - name: servicebus-connection
        value: <connection-string>
  template:
    containers:
      - name: longrun-worker
        image: rmhgeo.azurecr.io/longrun-worker:latest
        resources:
          cpu: 4
          memory: 16Gi
        env:
          - name: SERVICEBUS_CONNECTION
            secretRef: servicebus-connection
          - name: QUEUE_NAME
            value: longrun-tasks
    scale:
      minReplicas: 0
      maxReplicas: 5
      rules:
        - name: queue-scaling
          custom:
            type: azure-servicebus
            metadata:
              queueName: longrun-tasks
              messageCount: "1"
```

**Resource Profile:**
- 4 vCPU, 16 GB RAM per replica (scalable)
- Scale: 0-5 replicas based on queue depth
- **No timeout limit** - can run for hours if needed

**Why Container Apps over ACI:**
- KEDA-based autoscaling (0 replicas when idle)
- Queue-triggered scaling
- Managed Kubernetes without the complexity

#### Alternative: Azure Container Instance (ACI)

Simpler but less flexible:
```python
# Spawn per-job container
def route_large_raster(params):
    file_size_gb = get_blob_size(params['blob_name']) / 1024
    if file_size_gb > 50:
        return spawn_aci_container(params)  # One container per job
    else:
        return queue_to_raster_tasks(params)
```

- **Pros:** Pay-per-use, no idle costs, scales to 0
- **Cons:** 15-second cold start, limited SKU options

---

## Service Bus Queue Strategy

### Current (Monolith)
```
geospatial-jobs   → Job orchestration
geospatial-tasks  → ALL task types mixed
```

### Proposed (Separated)
```
geospatial-jobs   → Job orchestration (unchanged)
raster-tasks      → Raster Function App only
vector-tasks      → Vector Function App only
longrun-tasks     → Container Apps only
```

### Queue Configuration

```bash
# Job orchestration queue (unchanged)
az servicebus queue update \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 1

# Raster queue (conservative - long operations)
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name raster-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D

# Vector queue (optimized for throughput)
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name vector-tasks \
  --lock-duration PT2M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D

# Long-running queue (patient)
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name longrun-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D
```

### Task Routing Logic

```python
# In core/machine.py - route_task_to_queue()
def route_task_to_queue(task_type: str, file_size_gb: float = None) -> str:
    """Route task to appropriate queue based on type and size."""

    # Size-based routing for large files
    if file_size_gb and file_size_gb > 50:
        return "longrun-tasks"

    # Type-based routing
    RASTER_TASK_TYPES = {
        "validate_raster", "create_cog", "extract_stac_metadata",
        "create_tiling_scheme", "extract_tile", "create_mosaic_json"
    }

    VECTOR_TASK_TYPES = {
        "process_vector_prepare", "process_vector_upload",
        "create_vector_stac", "validate_vector"
    }

    if task_type in RASTER_TASK_TYPES:
        return "raster-tasks"
    elif task_type in VECTOR_TASK_TYPES:
        return "vector-tasks"
    else:
        return "geospatial-tasks"  # Fallback for misc tasks
```

---

## PostgreSQL Connection Management

### Connection Limits by PostgreSQL SKU

| PostgreSQL SKU | Max Connections | Recommended Use |
|----------------|-----------------|-----------------|
| Burstable B1ms | 50 | Development only |
| Burstable B2s | 120 | Small workloads |
| **General Purpose D2s_v3** | **200** | **Good starting point** |
| General Purpose D4s_v3 | 400 | High concurrency |
| Memory Optimized E4s_v3 | 400 | Vector-heavy workloads |

### Connection Pooling Strategy

Each Function App should have its own pool limits:

```python
# config/database_config.py

class DatabaseConfig(BaseModel):
    """Database connection configuration per app type."""

    # API Gateway: Many short queries, moderate pool
    api_pool_min: int = 2
    api_pool_max: int = 20

    # Raster Worker: Few long connections
    raster_pool_min: int = 1
    raster_pool_max: int = 4

    # Vector Worker: Many concurrent chunk uploads
    vector_pool_min: int = 5
    vector_pool_max: int = 50
```

**Total Budget:** 20 + 4 + 50 = 74 connections per instance set. With autoscaling, budget for 200-400 total connections.

### PgBouncer (When Needed)

If scaling to **100+ concurrent vector tasks**, enable Azure PgBouncer:

```bash
az postgres flexible-server parameter set \
  --resource-group rmhazure_rg \
  --server-name rmhpgflex \
  --name pgbouncer.enabled \
  --value true

az postgres flexible-server parameter set \
  --resource-group rmhazure_rg \
  --server-name rmhpgflex \
  --name pgbouncer.default_pool_size \
  --value 50
```

PgBouncer multiplexes 1000+ application connections → 100 actual PostgreSQL connections.

---

## Migration Strategy

### Phase 1: Queue Separation (Low Risk)

**Goal:** Validate routing logic without changing deployment topology

1. Create new Service Bus queues: `raster-tasks`, `vector-tasks`
2. Update `core/machine.py` to route tasks by type
3. Keep single Function App - both queues processed by same app
4. **Test:** Verify messages route correctly

**Code Change:**
```python
# core/machine.py
def queue_task(self, task: TaskDefinition):
    queue_name = self.route_task_to_queue(task.task_type)
    self.service_bus.send_to_queue(queue_name, task.model_dump_json())
```

**Rollback:** Simply route all tasks to `geospatial-tasks` again

---

### Phase 2: Raster Worker Extraction

**Goal:** Isolate memory-intensive GDAL operations

1. Create `rmhgeo-raster` Function App in Azure
2. Copy required code:
   - `core/` - CoreMachine, StateManager
   - `jobs/process_raster_v2.py`, `jobs/process_large_raster.py`
   - `services/raster/`
   - `config/`, `infrastructure/`
3. Configure `host.json` with `maxConcurrentCalls: 1`
4. Deploy and point to `raster-tasks` queue
5. Test raster jobs independently
6. Remove raster handlers from monolith

**File Structure (rmhgeo-raster):**
```
rmhgeo-raster/
├── function_app.py          # Service Bus trigger only
├── host.json                # Raster-optimized settings
├── core/                    # CoreMachine (task processing only)
├── jobs/
│   ├── process_raster_v2.py
│   └── process_large_raster.py
├── services/
│   └── raster/              # All raster handlers
├── config/
└── infrastructure/
```

---

### Phase 3: Vector Worker Extraction

**Goal:** Enable high-parallelism vector processing

1. Create `rmhgeo-vector` Function App
2. Copy required code:
   - `core/`
   - `jobs/process_vector.py`
   - `services/vector/`
   - `config/`, `infrastructure/`
3. Configure `host.json` with `maxConcurrentCalls: 32`
4. Deploy and point to `vector-tasks` queue
5. Test vector jobs independently
6. Remove vector handlers from monolith → monolith becomes API Gateway

**File Structure (rmhgeo-vector):**
```
rmhgeo-vector/
├── function_app.py          # Service Bus trigger only
├── host.json                # Vector-optimized settings
├── core/
├── jobs/
│   └── process_vector.py
├── services/
│   └── vector/
├── config/
└── infrastructure/
```

---

### Phase 4: Long-Running Container (When Needed)

**Goal:** Handle 50GB+ files without timeout constraints

1. Create Azure Container Registry (if not exists)
2. Build Docker image with GDAL + Python
3. Create Container App with queue trigger
4. Implement size-based routing in job submission
5. Test with actual 50GB+ files

**Dockerfile:**
```dockerfile
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.8.0

WORKDIR /app
COPY requirements-longrun.txt .
RUN pip install -r requirements-longrun.txt

COPY core/ ./core/
COPY services/raster/ ./services/raster/
COPY config/ ./config/
COPY infrastructure/ ./infrastructure/
COPY longrun_worker.py .

CMD ["python", "longrun_worker.py"]
```

---

## Cost Analysis

### Current State
| Resource | Monthly Cost |
|----------|--------------|
| rmhazuregeoapi (B3 Basic) | ~$70 |
| **Total** | **~$70** |

### Proposed State
| Resource | Monthly Cost |
|----------|--------------|
| rmhgeo-api (B3 Basic) | ~$70 |
| rmhgeo-raster (B3 Basic) | ~$70 |
| rmhgeo-vector (B3 Basic) | ~$70 |
| rmhgeo-longrun (Container Apps, pay-per-use) | ~$20-50 |
| Additional Service Bus queues | ~$5 |
| **Total** | **~$235-265** |

### ROI Justification

The ~3.5x cost increase is justified when:
- Vector throughput needs 10x+ improvement
- Raster jobs fail due to OOM from concurrent vector operations
- 50GB+ files need processing (impossible in current architecture)
- Production SLA requires workload isolation

### Cost Optimization Options

1. **Scale to zero:** Container Apps scale to 0 replicas when idle
2. **Right-size workers:** Start with B2 Basic, scale up if needed
3. **Spot instances:** Use spot pricing for long-running container jobs
4. **Reserved capacity:** 1-year reservation for predictable workloads

---

## Monitoring and Observability

### Application Insights (Shared)

All Function Apps and Container Apps should log to the same Application Insights instance:

```bash
# Same instrumentation key across all apps
APPINSIGHTS_INSTRUMENTATIONKEY=<shared-key>
```

### Key Metrics to Monitor

| Metric | API Gateway | Raster Worker | Vector Worker |
|--------|-------------|---------------|---------------|
| Response time | < 500ms | N/A | N/A |
| Queue depth | N/A | < 5 messages | < 100 messages |
| Memory usage | < 50% | < 80% | < 60% |
| Concurrent executions | < 20 | = 1 | < 40 |
| Error rate | < 1% | < 5% | < 2% |

### Alerting Rules

```kusto
// Raster worker memory pressure
traces
| where cloud_RoleName == "rmhgeo-raster"
| where message contains "memory" or message contains "OOM"
| summarize count() by bin(timestamp, 5m)
| where count_ > 0

// Vector queue backing up
AzureMetrics
| where ResourceProvider == "MICROSOFT.SERVICEBUS"
| where MetricName == "ActiveMessages"
| where Resource contains "vector-tasks"
| where Average > 100
```

---

## Security Considerations

### Network Isolation (Future)

When moving to production:
1. Deploy Function Apps in VNET
2. Use Private Endpoints for PostgreSQL
3. Use Private Endpoints for Service Bus
4. APIM as single public entry point

### Managed Identity

Each Function App should use its own Managed Identity:
- `rmhgeo-api-identity` - Read/write to all resources
- `rmhgeo-raster-identity` - Read Bronze, write Silver, read/write PostgreSQL
- `rmhgeo-vector-identity` - Read Bronze, write PostgreSQL

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 06 DEC 2025 | Propose 4-app architecture | Workload isolation for raster vs vector |
| 06 DEC 2025 | Container Apps over AKS | Simpler ops, KEDA scaling, no K8s overhead |
| 06 DEC 2025 | Shared PostgreSQL | Single source of truth, schema separation sufficient |
| 06 DEC 2025 | Phase 1 starts with queue separation | Low-risk validation of routing logic |

---

## Open Questions

1. **PostgreSQL tier:** Current Burstable B2s (120 connections) - sufficient for Phase 2-3?
2. **Container registry:** Use existing ACR or create dedicated?
3. **APIM timeline:** When to add API Management layer?
4. **Shared code strategy:** Git submodules, private PyPI, or code duplication?

---

## Next Steps

1. [ ] Review and approve this architecture proposal
2. [ ] Create Service Bus queues for Phase 1
3. [ ] Implement task routing in CoreMachine
4. [ ] Test routing with existing monolith
5. [ ] Plan Phase 2 extraction timeline

---

**Document Status**: PROPOSAL
**Last Updated**: 06 DEC 2025
**Next Review**: After Robert's feedback