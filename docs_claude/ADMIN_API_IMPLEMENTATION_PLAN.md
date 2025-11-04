# Admin API Implementation Plan

**Date**: 03 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 📋 Planning - Ready for Implementation
**Purpose**: Consolidate admin endpoints under `/api/admin/*` for APIM access control

---

## 🎯 **Goals**

1. **Consolidate admin endpoints** under `/api/admin/*` pattern for single APIM policy
2. **Prioritize PostgreSQL visibility** (app, geo, pgstac schemas) first
3. **Design for automation** - Health monitoring apps and AI agents as primary consumers
4. **Maintain backward compatibility** during transition (deprecation period)

---

## 📐 **Architecture Decision: Single Admin Path**

### **Why `/api/admin/*`?**

**APIM Access Control**:
```xml
<!-- Single policy for ALL admin operations -->
<policies>
  <inbound>
    <validate-azure-ad-token tenant-id="{tenant-id}">
      <client-application-ids>
        <application-id>{admin-app-id}</application-id>
      </client-application-ids>
    </validate-azure-ad-token>
    <rate-limit calls="10000" renewal-period="60" />
  </inbound>
</policies>
```

**Benefits**:
- ✅ Single APIM policy instead of dozens
- ✅ Clear separation: Public APIs vs Admin APIs
- ✅ Easy to audit admin access
- ✅ Consistent auth/rate limiting
- ✅ Future-proof for microservices split

### **Endpoint Categories**

```
/api/admin/
├── db/              # Database inspection (PostgreSQL)
│   ├── schemas/     # Schema-level operations
│   ├── tables/      # Table-level inspection
│   ├── queries/     # Query analysis
│   ├── health/      # DB health metrics
│   └── maintenance/ # Admin operations (nuke, redeploy)
│
├── stac/            # STAC system inspection (pgstac schema)
│   ├── schema/      # pgstac schema details
│   ├── collections/ # Collection statistics
│   ├── items/       # Item inspection
│   └── health/      # STAC health
│
├── servicebus/      # Service Bus operations
│   ├── queues/      # Queue inspection
│   ├── deadletter/  # Dead letter management
│   └── health/      # Service Bus health
│
├── storage/         # Blob storage inspection
│   ├── containers/  # Container operations
│   ├── blobs/       # Blob inspection
│   └── health/      # Storage health
│
├── registry/        # Job/handler discovery
│   ├── jobs/        # Registered jobs
│   ├── handlers/    # Registered handlers
│   └── health/      # Registry validation
│
├── traces/          # Workflow execution traces
│   ├── jobs/        # Job traces
│   ├── tasks/       # Task traces
│   └── correlation/ # Correlation tracing
│
└── system/          # System-wide operations
    ├── health/      # Comprehensive health
    ├── config/      # Configuration inspection
    └── metrics/     # Performance metrics
```

---

## 🗂️ **Implementation Phases**

### **Phase 1: Database Admin API (PostgreSQL)** 🔴 **HIGH PRIORITY**

**Duration**: 2-3 hours
**Impact**: Complete visibility into app, geo, pgstac schemas

#### **1.1: Schema-Level Operations**

**New Endpoints**:
```
GET /api/admin/db/schemas
    - List all schemas (app, geo, pgstac, public)
    - Show table counts per schema
    - Total row counts per schema
    - Schema sizes (MB)
    - Last modified timestamps

GET /api/admin/db/schemas/{schema_name}
    - Detailed schema info
    - All tables with row counts
    - All functions/procedures
    - Schema size breakdown
    - Access permissions

GET /api/admin/db/schemas/{schema_name}/tables
    - List all tables in schema
    - Row counts
    - Table sizes (data + indexes)
    - Last vacuum/analyze timestamps
    - Auto-vacuum status
```

**Implementation**:
- Create `triggers/admin/db_schemas.py`
- Add trigger class: `AdminDbSchemasTrigger`
- Use existing `PostgreSQLRepository` for queries
- Add helper functions for schema introspection

**SQL Queries Needed**:
```sql
-- List all schemas with sizes
SELECT
    schema_name,
    COUNT(*) FILTER (WHERE table_type = 'BASE TABLE') as table_count,
    pg_size_pretty(SUM(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)))) as total_size
FROM information_schema.tables
WHERE table_schema IN ('app', 'geo', 'pgstac')
GROUP BY schema_name;

-- Tables with row counts and sizes
SELECT
    schemaname,
    tablename,
    n_live_tup as row_count,
    pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) as data_size,
    pg_size_pretty(pg_indexes_size(schemaname || '.' || tablename)) as index_size,
    last_vacuum,
    last_autovacuum,
    last_analyze
FROM pg_stat_user_tables
WHERE schemaname = %s
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;
```

---

#### **1.2: Table-Level Inspection**

**New Endpoints**:
```
GET /api/admin/db/tables/{schema}.{table}
    - Complete table details
    - Columns: name, type, nullable, default
    - Constraints: PK, FK, unique, check
    - Indexes: name, type, columns, size
    - Row count and size
    - Sample statistics

GET /api/admin/db/tables/{schema}.{table}/sample
    - Return first/last N rows (default: 10)
    - Query params: limit, offset, order_by
    - Show recent data for debugging
    - IMPORTANT: Respect geometry column (use ST_AsGeoJSON for geo schema)

GET /api/admin/db/tables/{schema}.{table}/columns
    - Detailed column information
    - Data types with PostgreSQL type info
    - NOT NULL constraints
    - Default values
    - Column statistics (n_distinct, correlation)

GET /api/admin/db/tables/{schema}.{table}/indexes
    - All indexes on table
    - Index type (btree, gist, gin, etc.)
    - Columns covered
    - Size and bloat estimate
    - Last reindex time
    - Index usage statistics
```

**Implementation**:
- Create `triggers/admin/db_tables.py`
- Add trigger class: `AdminDbTablesTrigger`
- Handle geometry columns gracefully (geo schema has geom columns)
- Add pagination for large tables

**SQL Queries Needed**:
```sql
-- Table column details
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default,
    character_maximum_length,
    numeric_precision
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position;

-- Table indexes
SELECT
    indexname,
    indexdef,
    pg_size_pretty(pg_relation_size(schemaname || '.' || indexname)) as size
FROM pg_indexes
WHERE schemaname = %s AND tablename = %s;

-- Sample rows (with geometry handling)
SELECT * FROM {schema}.{table}
ORDER BY {order_column} DESC
LIMIT %s OFFSET %s;
```

---

#### **1.3: Query Analysis**

**New Endpoints**:
```
GET /api/admin/db/queries/running
    - List currently running queries
    - Query text (first 500 chars)
    - Duration
    - State (active, idle in transaction)
    - Blocking queries
    - Client application/user

GET /api/admin/db/queries/slow
    - Top 20 slowest queries (pg_stat_statements)
    - Execution count
    - Average duration
    - Max duration
    - Total time
    - Rows affected

GET /api/admin/db/locks
    - Current database locks
    - Lock type and mode
    - Blocking vs waiting queries
    - Lock wait times
    - CRITICAL for debugging deadlocks

GET /api/admin/db/connections
    - Active connection count
    - Connections by application
    - Connections by state
    - Max connections limit
    - Connection pool status
```

**Implementation**:
- Create `triggers/admin/db_queries.py`
- Add trigger class: `AdminDbQueriesTrigger`
- Requires `pg_stat_statements` extension (verify in deployment)
- Add timeout protection (queries analyzing queries can hang)

**SQL Queries Needed**:
```sql
-- Running queries
SELECT
    pid,
    usename,
    application_name,
    state,
    query,
    now() - query_start as duration,
    wait_event_type,
    wait_event
FROM pg_stat_activity
WHERE state != 'idle' AND pid != pg_backend_pid()
ORDER BY query_start;

-- Current locks
SELECT
    l.pid,
    l.locktype,
    l.mode,
    l.granted,
    a.query,
    now() - a.query_start as duration
FROM pg_locks l
JOIN pg_stat_activity a ON l.pid = a.pid
WHERE NOT l.granted
ORDER BY a.query_start;

-- Slow queries (requires pg_stat_statements)
SELECT
    query,
    calls,
    total_exec_time / calls as avg_time_ms,
    max_exec_time,
    rows / calls as avg_rows
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

---

#### **1.4: Database Health & Maintenance**

**New Endpoints**:
```
GET /api/admin/db/health
    - Overall database health
    - Connection pool status
    - Replication lag (if applicable)
    - Table bloat estimates
    - Index bloat estimates
    - Vacuum progress
    - Long-running transactions

GET /api/admin/db/health/performance
    - Query performance metrics
    - Cache hit ratios (buffer cache)
    - Index usage statistics
    - Sequential scan counts
    - Tuple reads vs fetches

POST /api/admin/db/maintenance/vacuum
    - Trigger VACUUM ANALYZE on specified tables
    - Query param: schema, table (optional - all if not specified)
    - Background operation, returns job_id

POST /api/admin/db/maintenance/reindex
    - Reindex specific table or entire schema
    - Query params: schema, table
    - Background operation, returns job_id

POST /api/admin/db/maintenance/cleanup
    - Clean up old completed jobs (>30 days)
    - Remove old task records
    - Requires confirmation parameter
    - Returns counts of deleted records
```

**Implementation**:
- Create `triggers/admin/db_health.py`
- Create `triggers/admin/db_maintenance.py`
- Add safety checks (confirmations, dry-run mode)
- Log all maintenance operations

---

#### **1.5: Migration Plan for Existing `/api/db/*` Endpoints**

**Current Endpoints to Migrate**:
```
MOVE: /api/db/jobs                    → /api/admin/db/app/jobs
MOVE: /api/db/jobs/{job_id}           → /api/admin/db/app/jobs/{job_id}
MOVE: /api/db/tasks                   → /api/admin/db/app/tasks
MOVE: /api/db/tasks/{job_id}          → /api/admin/db/app/tasks/{job_id}
MOVE: /api/db/stats                   → /api/admin/db/health/stats
MOVE: /api/db/enums/diagnostic        → /api/admin/db/app/enums/diagnostic
MOVE: /api/db/schema/nuke             → /api/admin/db/maintenance/nuke
MOVE: /api/db/schema/redeploy         → /api/admin/db/maintenance/redeploy
MOVE: /api/db/functions/test          → /api/admin/db/app/functions/test
MOVE: /api/db/debug/all               → /api/admin/db/app/debug/all

DEPRECATED (Platform schema removed):
DELETE: /api/db/api_requests
DELETE: /api/db/api_requests/{request_id}
DELETE: /api/db/orchestration_jobs
DELETE: /api/db/orchestration_jobs/{request_id}
```

**Migration Strategy**:
1. **Create new endpoints first** (Phase 1A)
2. **Keep old endpoints temporarily** with deprecation warnings (Phase 1B)
3. **Update documentation** to point to new endpoints (Phase 1C)
4. **Remove old endpoints** after 1 deployment cycle (Phase 1D)

**Deprecation Response Headers**:
```python
def _add_deprecation_headers(response: func.HttpResponse, new_endpoint: str):
    """Add deprecation warning headers to old endpoints."""
    response.headers['X-Deprecated'] = 'true'
    response.headers['X-Deprecated-Endpoint'] = new_endpoint
    response.headers['X-Deprecation-Date'] = '2025-12-01'
    return response
```

---

### **Phase 2: STAC Admin API (pgstac schema)** 🟡 **MEDIUM PRIORITY**

**Duration**: 1-2 hours
**Impact**: Deep STAC inspection capabilities

**Note**: Many STAC inspection endpoints already exist, just need to move under `/api/admin/stac/*`

#### **2.1: STAC Schema Operations**

**Existing Endpoints to Migrate**:
```
MOVE: /api/stac/schema/info               → /api/admin/stac/schema/info
MOVE: /api/stac/collections/summary       → /api/admin/stac/collections/summary
MOVE: /api/stac/collections/{id}/stats    → /api/admin/stac/collections/{id}/stats
MOVE: /api/stac/items/{item_id}           → /api/admin/stac/items/{item_id}
MOVE: /api/stac/health                    → /api/admin/stac/health
```

**New Endpoints**:
```
GET /api/admin/stac/schema/tables
    - List all pgstac tables with sizes
    - Row counts for collections, items, searches
    - Partition information
    - Index health

GET /api/admin/stac/schema/functions
    - List all pgstac functions
    - Function signatures
    - Last modified times
    - Execution counts (if available)

GET /api/admin/stac/performance
    - Query performance metrics
    - Most queried collections
    - Slow STAC searches
    - Index usage statistics
```

**Implementation**:
- Move existing `infrastructure/stac.py` inspection functions
- Create `triggers/admin/stac_inspection.py`
- Add new performance queries

---

#### **2.2: STAC Maintenance Operations**

**Existing Endpoints to Migrate**:
```
MOVE: /api/stac/nuke                      → /api/admin/stac/maintenance/nuke
MOVE: /api/stac/setup                     → /api/admin/stac/maintenance/setup
```

**Keep These as Operational (Not Admin)**:
```
KEEP: /api/stac/collections/{tier}        # Used by ETL pipeline
KEEP: /api/stac/init                      # System initialization
KEEP: /api/stac/extract                   # ETL operation
KEEP: /api/stac/vector                    # ETL operation
```

---

### **Phase 3: Service Bus Admin API** 🟠 **HIGH PRIORITY**

**Duration**: 3-4 hours
**Impact**: Critical visibility into queue infrastructure

#### **3.1: Queue Inspection**

**New Endpoints**:
```
GET /api/admin/servicebus/queues
    - List all queues (geospatial-jobs, geospatial-tasks)
    - Active message count
    - Dead letter message count
    - Scheduled message count
    - Queue sizes
    - Queue configuration

GET /api/admin/servicebus/queues/{queue_name}
    - Detailed queue information
    - Message counts by state
    - Oldest message timestamp
    - Queue metrics (receive rate, send rate)
    - Auto-delete on idle settings
    - Max delivery count

GET /api/admin/servicebus/queues/{queue_name}/peek
    - Peek at next N messages without dequeuing
    - Show message properties
    - Show message body (first 1000 chars)
    - Show scheduled delivery time
    - CRITICAL for debugging stuck jobs

GET /api/admin/servicebus/deadletter
    - List all dead letter messages across queues
    - Group by queue name
    - Show failure reasons
    - Show dead letter counts
    - Show message properties
```

**Implementation**:
- Create `triggers/admin/servicebus_queues.py`
- Use `ServiceBusManagementClient` from `azure-servicebus`
- Add `azure-mgmt-servicebus` to requirements.txt
- Use DefaultAzureCredential for authentication

**Key Code Patterns**:
```python
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.identity import DefaultAzureCredential

class AdminServiceBusTrigger:
    def __init__(self):
        credential = DefaultAzureCredential()
        namespace = os.getenv('SERVICE_BUS_NAMESPACE')
        self.admin_client = ServiceBusAdministrationClient(
            fully_qualified_namespace=f"{namespace}.servicebus.windows.net",
            credential=credential
        )

    def get_queue_properties(self, queue_name: str):
        props = self.admin_client.get_queue_runtime_properties(queue_name)
        return {
            "active_message_count": props.active_message_count,
            "dead_letter_message_count": props.dead_letter_message_count,
            "scheduled_message_count": props.scheduled_message_count,
            "total_message_count": props.total_message_count,
            "size_in_bytes": props.size_in_bytes
        }
```

---

#### **3.2: Dead Letter Management**

**New Endpoints**:
```
GET /api/admin/servicebus/queues/{queue_name}/deadletter
    - List dead letter messages for specific queue
    - Show message bodies
    - Show failure reasons
    - Show enqueue times
    - Pagination support

POST /api/admin/servicebus/queues/{queue_name}/deadletter/{message_id}/requeue
    - Move specific dead letter message back to main queue
    - Requires confirmation
    - Returns new message ID

POST /api/admin/servicebus/queues/{queue_name}/deadletter/requeue-all
    - Move ALL dead letter messages back to main queue
    - Requires explicit confirmation
    - Background operation, returns count

POST /api/admin/servicebus/queues/{queue_name}/purge
    - Clear all messages from queue
    - DEV/TEST ONLY
    - Requires explicit confirmation
    - Returns count of purged messages
```

**Implementation**:
- Create `triggers/admin/servicebus_deadletter.py`
- Use `ServiceBusReceiver` with sub_queue=ServiceBusSubQueue.DEAD_LETTER
- Add safety confirmations
- Log all requeue operations

---

#### **3.3: Service Bus Health**

**New Endpoints**:
```
GET /api/admin/servicebus/health
    - Overall Service Bus health
    - Namespace status
    - Queue backlogs (alert if >1000 messages)
    - Dead letter counts (alert if >10 messages)
    - Connection status
    - Oldest message age (alert if >1 hour)

GET /api/admin/servicebus/metrics
    - Historical metrics (requires Azure Monitor integration)
    - Message send rate
    - Message receive rate
    - Queue depth over time
    - Dead letter trends
```

**Implementation**:
- Create `triggers/admin/servicebus_health.py`
- Query all queues for metrics
- Define thresholds for warnings/errors
- Return structured health status

---

### **Phase 4: Storage Admin API** 🟢 **LOWER PRIORITY**

**Duration**: 2-3 hours
**Impact**: Blob storage visibility (Bronze/Silver/Gold tiers)

#### **4.1: Container Operations**

**New Endpoints**:
```
GET /api/admin/storage/containers
    - List all containers
    - Blob counts per container
    - Total sizes
    - Last modified timestamps
    - Access tier distribution

GET /api/admin/storage/containers/{container_name}
    - Detailed container info
    - Blob count by extension
    - Total size breakdown
    - Recent blobs (last 10)
    - Storage tier metrics

GET /api/admin/storage/containers/{container_name}/blobs
    - List blobs with pagination
    - Filter by: prefix, extension, size range, modified date
    - Sort by: name, size, modified date
    - Return: name, size, content type, last modified

GET /api/admin/storage/blobs/{container}/{blob_path}
    - Get blob metadata without downloading
    - Show: size, content type, etag, last modified
    - Show: custom metadata, tags
    - Show: access tier, archive status
```

**Implementation**:
- Create `triggers/admin/storage_containers.py`
- Use existing `BlobRepository` from infrastructure
- Add pagination and filtering
- Optimize for large containers (>10k blobs)

---

#### **4.2: Storage Analysis**

**Existing Endpoint to Migrate**:
```
MOVE: /api/analysis/container/{job_id}    → /api/admin/storage/analysis/{job_id}
MOVE: /api/analysis/delivery              → /api/admin/storage/analysis/delivery
```

**New Endpoints**:
```
GET /api/admin/storage/health
    - Storage account health
    - Available quota
    - Connection status
    - Access tier distribution
    - Cost estimates by tier

GET /api/admin/storage/containers/{container_name}/usage
    - Detailed storage usage
    - File type breakdown
    - Size distribution histogram
    - Age distribution
    - Recommendations for tier changes
```

---

### **Phase 5: Registry & Discovery API** 🟡 **MEDIUM PRIORITY**

**Duration**: 1-2 hours
**Impact**: AI agent auto-discovery of capabilities

#### **5.1: Job Registry**

**New Endpoints**:
```
GET /api/admin/registry/jobs
    - List all registered job types
    - Show: job_type, description, stage_count
    - Show: parameter schemas
    - Show: handler mappings

GET /api/admin/registry/jobs/{job_type}
    - Detailed job definition
    - All stage definitions
    - Task types per stage
    - Parallelism settings
    - Parameter schema with examples
    - Workflow visualization data (DAG)

POST /api/admin/registry/jobs/{job_type}/validate
    - Validate job definition
    - Check all handlers exist
    - Validate parameter schema
    - Check stage consistency
    - Return validation errors
```

**Implementation**:
- Create `triggers/admin/registry_jobs.py`
- Access `ALL_JOBS` from `jobs/__init__.py`
- Introspect job classes for metadata
- Generate OpenAPI-style parameter schemas

**Code Pattern**:
```python
def get_all_jobs():
    """List all registered jobs with metadata."""
    from jobs import ALL_JOBS

    result = []
    for job_type, job_class in ALL_JOBS.items():
        result.append({
            "job_type": job_type,
            "description": job_class.description,
            "stages": len(job_class.stages),
            "parameters_schema": job_class.parameters_schema,
            "stage_definitions": job_class.stages
        })

    return {"jobs": result, "count": len(result)}
```

---

#### **5.2: Handler Registry**

**New Endpoints**:
```
GET /api/admin/registry/handlers
    - List all registered task handlers
    - Show: handler_name, task_type
    - Show: service module
    - Show: handler function signature

GET /api/admin/registry/handlers/{handler_name}
    - Detailed handler information
    - Function signature
    - Expected parameters
    - Return value schema
    - Used by which jobs
```

**Implementation**:
- Create `triggers/admin/registry_handlers.py`
- Access `ALL_HANDLERS` from `services/__init__.py`
- Introspect handler functions
- Map handlers to jobs that use them

---

#### **5.3: Registry Health**

**New Endpoints**:
```
GET /api/admin/registry/health
    - Validate all jobs can be instantiated
    - Validate all handlers exist
    - Check for orphaned handlers (registered but unused)
    - Check for missing handlers (referenced but not registered)
    - Return detailed validation report

GET /api/admin/registry/imports
    - Show import validation status
    - Currently uses health endpoint's import check
    - All auto-discovered modules
    - Critical dependency status
```

---

### **Phase 6: Traces & Execution Analysis** 🟠 **HIGH PRIORITY**

**Duration**: 2-3 hours
**Impact**: Essential for debugging complex workflows

#### **6.1: Job Traces**

**New Endpoints**:
```
GET /api/admin/traces/job/{job_id}
    - Complete execution trace for job
    - All stages with timestamps
    - All tasks with parameters and results
    - Stage advancement decisions
    - Error history and retry attempts
    - Total duration and stage breakdown

GET /api/admin/traces/job/{job_id}/timeline
    - Timeline visualization data
    - Gantt chart JSON format
    - Show parallel task execution
    - Show stage transitions
    - Identify bottlenecks
    - Show critical path

GET /api/admin/traces/job/{job_id}/errors
    - All errors encountered during job
    - Group by stage, task
    - Show retry history
    - Show error patterns
```

**Implementation**:
- Create `triggers/admin/traces_jobs.py`
- Query jobs and tasks tables
- Aggregate stage_results and result_data
- Calculate durations and critical path
- Format for timeline visualization

---

#### **6.2: Task Traces**

**New Endpoints**:
```
GET /api/admin/traces/task/{task_id}
    - Complete task execution trace
    - Input parameters
    - Handler used
    - Execution logs (if captured)
    - Output results
    - Errors and retry history

GET /api/admin/traces/correlation/{correlation_id}
    - Trace all jobs/tasks with correlation ID
    - Full chain: Request → Jobs → Tasks
    - Essential for Platform layer debugging
    - Show execution order and timing
```

**Implementation**:
- Create `triggers/admin/traces_tasks.py`
- Query by correlation_id from parameters field (JSONB)
- Build complete execution chain
- Show parent-child relationships

---

### **Phase 7: System-Wide Operations** 🟡 **MEDIUM PRIORITY**

**Duration**: 2-3 hours
**Impact**: Comprehensive system health and configuration

#### **7.1: System Health**

**New Endpoints**:
```
GET /api/admin/system/health
    - Comprehensive system health check
    - Database: connection, performance
    - Service Bus: queue depths, dead letters
    - Blob Storage: connectivity, quota
    - STAC: pgstac health
    - OGC Features: PostGIS health
    - Function App: memory, instances

GET /api/admin/system/health/detailed
    - Component-by-component detailed status
    - Response times for each component
    - Error counts
    - Warning indicators
    - Recommendations for fixes

GET /api/admin/system/dependencies
    - All external dependencies
    - Azure SDK versions
    - GDAL/PROJ/GEOS versions
    - Python package versions
    - PostGIS extension versions
```

**Implementation**:
- Enhance existing `/api/health` endpoint
- Move to `/api/admin/system/health`
- Add more detailed checks
- Include performance metrics

---

#### **7.2: Configuration Inspection**

**New Endpoints**:
```
GET /api/admin/system/config
    - All environment variables (REDACTED secrets)
    - Storage account names
    - Service Bus namespace
    - Database connection details
    - Queue names
    - Schema names
    - Tier prefixes

GET /api/admin/system/config/validation
    - Validate all required env vars set
    - Check configuration consistency
    - Test database connectivity
    - Test Service Bus connectivity
    - Test blob storage connectivity
    - Return validation report

GET /api/admin/system/config/schemas
    - Show Pydantic config schemas
    - Default values
    - Current values (REDACTED)
    - Validation rules
```

**Implementation**:
- Create `triggers/admin/system_config.py`
- Use existing `config.py` module
- Add validation checks
- IMPORTANT: Redact passwords, connection strings, keys

---

#### **7.3: Performance Metrics**

**New Endpoints**:
```
GET /api/admin/system/metrics/jobs
    - Job statistics over time
    - Success/failure rates by job type
    - Average job duration by type
    - Queue wait times
    - Stage completion times
    - Query params: time_range (24h, 7d, 30d)

GET /api/admin/system/metrics/tasks
    - Task statistics over time
    - Success/failure rates by task type
    - Average task duration
    - Retry count distribution
    - Most common errors
    - Query params: time_range

GET /api/admin/system/metrics/performance
    - Function execution statistics
    - Average response times per endpoint
    - Queue processing throughput
    - Database query performance
    - Storage operation performance
```

**Implementation**:
- Create `triggers/admin/system_metrics.py`
- Query database for historical data
- Aggregate by time buckets
- Calculate percentiles (p50, p95, p99)

---

## 📋 **Implementation Checklist**

### **Phase 1: Database Admin API** (Priority 1)
- [ ] Create `triggers/admin/` folder
- [ ] Create `triggers/admin/__init__.py`
- [ ] Create `triggers/admin/db_schemas.py`
  - [ ] GET /api/admin/db/schemas
  - [ ] GET /api/admin/db/schemas/{schema_name}
  - [ ] GET /api/admin/db/schemas/{schema_name}/tables
- [ ] Create `triggers/admin/db_tables.py`
  - [ ] GET /api/admin/db/tables/{schema}.{table}
  - [ ] GET /api/admin/db/tables/{schema}.{table}/sample
  - [ ] GET /api/admin/db/tables/{schema}.{table}/columns
  - [ ] GET /api/admin/db/tables/{schema}.{table}/indexes
- [ ] Create `triggers/admin/db_queries.py`
  - [ ] GET /api/admin/db/queries/running
  - [ ] GET /api/admin/db/queries/slow
  - [ ] GET /api/admin/db/locks
  - [ ] GET /api/admin/db/connections
- [ ] Create `triggers/admin/db_health.py`
  - [ ] GET /api/admin/db/health
  - [ ] GET /api/admin/db/health/performance
- [ ] Create `triggers/admin/db_maintenance.py`
  - [ ] POST /api/admin/db/maintenance/vacuum
  - [ ] POST /api/admin/db/maintenance/reindex
  - [ ] POST /api/admin/db/maintenance/cleanup
- [ ] Migrate existing `/api/db/*` endpoints
  - [ ] Move to `/api/admin/db/app/*`
  - [ ] Add deprecation warnings to old endpoints
  - [ ] Update all internal references
  - [ ] Update documentation
- [ ] Add tests for new endpoints
- [ ] Deploy and verify

### **Phase 2: STAC Admin API** (Priority 2)
- [ ] Create `triggers/admin/stac_inspection.py`
  - [ ] Migrate existing endpoints to `/api/admin/stac/*`
  - [ ] Add new schema inspection endpoints
  - [ ] Add performance analysis endpoints
- [ ] Update STAC documentation
- [ ] Deploy and verify

### **Phase 3: Service Bus Admin API** (Priority 1)
- [ ] Add `azure-mgmt-servicebus` to requirements.txt
- [ ] Create `triggers/admin/servicebus_queues.py`
  - [ ] GET /api/admin/servicebus/queues
  - [ ] GET /api/admin/servicebus/queues/{queue_name}
  - [ ] GET /api/admin/servicebus/queues/{queue_name}/peek
  - [ ] GET /api/admin/servicebus/deadletter
- [ ] Create `triggers/admin/servicebus_deadletter.py`
  - [ ] GET /api/admin/servicebus/queues/{queue_name}/deadletter
  - [ ] POST /api/admin/servicebus/queues/{queue_name}/deadletter/{message_id}/requeue
  - [ ] POST /api/admin/servicebus/queues/{queue_name}/deadletter/requeue-all
  - [ ] POST /api/admin/servicebus/queues/{queue_name}/purge
- [ ] Create `triggers/admin/servicebus_health.py`
  - [ ] GET /api/admin/servicebus/health
  - [ ] GET /api/admin/servicebus/metrics
- [ ] Add tests for new endpoints
- [ ] Deploy and verify

### **Phase 4: Storage Admin API** (Priority 3)
- [ ] Create `triggers/admin/storage_containers.py`
  - [ ] GET /api/admin/storage/containers
  - [ ] GET /api/admin/storage/containers/{container_name}
  - [ ] GET /api/admin/storage/containers/{container_name}/blobs
  - [ ] GET /api/admin/storage/blobs/{container}/{blob_path}
- [ ] Migrate `/api/analysis/*` endpoints
- [ ] Add storage health endpoint
- [ ] Deploy and verify

### **Phase 5: Registry & Discovery API** (Priority 2)
- [ ] Create `triggers/admin/registry_jobs.py`
  - [ ] GET /api/admin/registry/jobs
  - [ ] GET /api/admin/registry/jobs/{job_type}
  - [ ] POST /api/admin/registry/jobs/{job_type}/validate
- [ ] Create `triggers/admin/registry_handlers.py`
  - [ ] GET /api/admin/registry/handlers
  - [ ] GET /api/admin/registry/handlers/{handler_name}
- [ ] Create `triggers/admin/registry_health.py`
  - [ ] GET /api/admin/registry/health
  - [ ] GET /api/admin/registry/imports
- [ ] Deploy and verify

### **Phase 6: Traces & Execution Analysis** (Priority 1)
- [ ] Create `triggers/admin/traces_jobs.py`
  - [ ] GET /api/admin/traces/job/{job_id}
  - [ ] GET /api/admin/traces/job/{job_id}/timeline
  - [ ] GET /api/admin/traces/job/{job_id}/errors
- [ ] Create `triggers/admin/traces_tasks.py`
  - [ ] GET /api/admin/traces/task/{task_id}
  - [ ] GET /api/admin/traces/correlation/{correlation_id}
- [ ] Deploy and verify

### **Phase 7: System-Wide Operations** (Priority 2)
- [ ] Create `triggers/admin/system_health.py`
  - [ ] GET /api/admin/system/health
  - [ ] GET /api/admin/system/health/detailed
  - [ ] GET /api/admin/system/dependencies
- [ ] Create `triggers/admin/system_config.py`
  - [ ] GET /api/admin/system/config
  - [ ] GET /api/admin/system/config/validation
  - [ ] GET /api/admin/system/config/schemas
- [ ] Create `triggers/admin/system_metrics.py`
  - [ ] GET /api/admin/system/metrics/jobs
  - [ ] GET /api/admin/system/metrics/tasks
  - [ ] GET /api/admin/system/metrics/performance
- [ ] Migrate `/api/health` to `/api/admin/system/health`
- [ ] Deploy and verify

### **Final Steps**
- [ ] Update `function_app.py` with all new routes
- [ ] Update CLAUDE.md with new endpoint documentation
- [ ] Update FILE_CATALOG.md
- [ ] Create `ADMIN_API_REFERENCE.md` with full endpoint list
- [ ] Remove deprecated endpoints after 1 deployment cycle
- [ ] Add APIM policy documentation
- [ ] Create example AI agent client code

---

## 🤖 **Design for AI Agents**

### **Discovery Flow**
```python
# AI Agent discovers system capabilities
1. GET /api/admin/registry/jobs
   → Returns list of all available job types

2. GET /api/admin/registry/jobs/{job_type}
   → Returns detailed job definition with parameter schema

3. POST /api/jobs/submit/{job_type}
   → Submit job with validated parameters

4. GET /api/admin/traces/job/{job_id}
   → Monitor execution and debug issues
```

### **Health Monitoring Flow**
```python
# AI Agent monitors system health
1. GET /api/admin/system/health
   → Overall system status

2. GET /api/admin/servicebus/health
   → Check for queue backlogs

3. GET /api/admin/db/health
   → Check database performance

4. GET /api/admin/system/metrics/jobs
   → Check job success rates

5. GET /api/admin/servicebus/deadletter
   → Identify failed messages
```

### **Debugging Flow**
```python
# AI Agent debugs failed job
1. GET /api/admin/traces/job/{job_id}
   → Get complete execution trace

2. GET /api/admin/traces/job/{job_id}/errors
   → Get all errors encountered

3. GET /api/admin/db/tables/app.tasks?job_id={job_id}
   → Get all task details

4. GET /api/admin/servicebus/deadletter
   → Check if any messages dead-lettered
```

---

## 📚 **Documentation Updates Required**

### **New Documentation Files**
1. `ADMIN_API_REFERENCE.md` - Complete endpoint reference
2. `ADMIN_API_QUICKSTART.md` - Getting started guide
3. `AI_AGENT_INTEGRATION.md` - AI agent integration patterns

### **Update Existing Files**
1. `CLAUDE.md` - Add admin API section
2. `FILE_CATALOG.md` - Add new trigger files
3. `ARCHITECTURE_REFERENCE.md` - Add admin API architecture
4. `TODO.md` - Track implementation progress

---

## 🚀 **Deployment Strategy**

### **Incremental Rollout**
1. **Phase 1A**: Deploy new `/api/admin/db/*` endpoints (keep old `/api/db/*`)
2. **Phase 1B**: Add deprecation warnings to old endpoints
3. **Phase 1C**: Update internal references and documentation
4. **Phase 1D**: Remove old endpoints after 1 week

### **Testing Strategy**
1. **Unit Tests**: Test each trigger class individually
2. **Integration Tests**: Test full request/response cycle
3. **Load Tests**: Test with high query volumes
4. **Security Tests**: Verify no sensitive data leaks

### **Monitoring**
1. Track endpoint usage (Application Insights)
2. Monitor response times
3. Alert on errors
4. Track deprecation header responses

---

## 🔐 **Security Considerations**

### **Access Control**
- All `/api/admin/*` endpoints require authentication
- Use Azure AD token validation
- Restrict to admin service principals
- Log all admin operations

### **Data Protection**
- Redact passwords and secrets in config endpoints
- Redact connection strings
- Limit message body preview (first 1000 chars)
- Paginate large result sets

### **Rate Limiting**
- Higher rate limits for admin endpoints (10k/min vs 1k/min)
- Throttle expensive operations (vacuum, reindex)
- Prevent abuse of peek/sample endpoints

---

## ⚠️ **Known Limitations**

### **Platform Schema Deprecation**
- Platform schema tables removed (moved to app schema)
- Platform endpoints (`/api/db/api_requests`, `/api/db/orchestration_jobs`) will be deleted
- No migration needed - Platform layer no longer in use

### **Query Performance**
- Some queries (pg_stat_statements, locks) can be expensive
- Add timeouts to prevent long-running admin queries
- Consider caching for frequently accessed metrics

### **Storage Container Listing**
- Large containers (>10k blobs) may be slow to list
- Implement pagination and filtering early
- Consider blob inventory for analytics

---

## 📊 **Success Metrics**

### **Completeness**
- [ ] 100% of database schemas have inspection endpoints
- [ ] Service Bus queues have full visibility
- [ ] All job types discoverable via API
- [ ] Complete trace capability for any job

### **Usability**
- [ ] AI agent can discover all capabilities
- [ ] Health monitoring app can detect all issues
- [ ] Documentation covers all endpoints
- [ ] Example code provided for common use cases

### **Performance**
- [ ] All admin endpoints respond < 5 seconds
- [ ] Pagination for large result sets
- [ ] No N+1 query issues
- [ ] Efficient queries (EXPLAIN ANALYZE verified)

---

## 🎯 **Next Steps**

1. **Review this plan** with Robert for approval
2. **Create GitHub issues** for each phase (optional)
3. **Start with Phase 1** (Database Admin API)
4. **Deploy incrementally** (one phase at a time)
5. **Test thoroughly** after each phase
6. **Update documentation** continuously
7. **Deprecate old endpoints** after validation

---

## ✅ **Questions to Resolve Before Starting**

1. **APIM Timeline**: When will APIM be set up? (Determines urgency of consolidation)
2. **Authentication**: What authentication method for admin endpoints? (Azure AD, API keys, both?)
3. **Rate Limits**: Specific rate limit requirements for admin vs public APIs?
4. **Logging**: Should all admin operations be logged to separate audit log?
5. **Permissions**: Different permission levels within admin API? (read-only vs full admin)
6. **Monitoring**: Specific Application Insights queries/dashboards needed?

---

**End of Plan** 🎉

Ready for implementation! This is a comprehensive plan that prioritizes PostgreSQL visibility first, consolidates all admin endpoints under `/api/admin/*`, and designs for AI agent and monitoring app consumers.
