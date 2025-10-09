# Architecture Quickstart - rmhgeoapi

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Rapid orientation for new Claude sessions

---

## 🎯 30-Second Summary

**What**: Azure Functions-based geospatial processing orchestration system
**Pattern**: Job → Stage → Task with queue-driven parallelization
**Stack**: Python 3.12, PostgreSQL 17, PostGIS 3.6, PgSTAC 0.8.5, Azure Functions
**Philosophy**: No backward compatibility, explicit errors, single source of truth

---

## 📚 Essential Reading Order

1. **Start here**: `docs_claude/CLAUDE_CONTEXT.md` (Primary context)
2. **Current work**: `docs_claude/TODO_ACTIVE.md` (Active tasks)
3. **Core pattern**: `docs/TASK_REGISTRY_PATTERN.md` (Job injection architecture)
4. **Database**: `POSTGRES_REQUIREMENTS.md` (PostgreSQL setup)
5. **Files**: `docs_claude/FILE_CATALOG.md` (Quick file lookup)

---

## 🏗️ Core Architecture (5 minutes)

### Request Flow
```
HTTP Request → Trigger → Job Registry → Core Machine → Queue → Task Processors
     ↓            ↓            ↓              ↓           ↓          ↓
 /api/jobs/   submit_job  JobRegistry   Orchestrator   Azure    Service
  {type}      .py         .get(type)    (generic)      Queue    Layer
```

### Job → Stage → Task Pattern
```
Job: hello_world
├── Stage 1: Setup
│   ├── Task: greet_1 ──┐
│   ├── Task: greet_2 ──┼─→ Parallel execution
│   └── Task: greet_3 ──┘
│        ↓ (last task completes → advance stage)
├── Stage 2: Processing
│   └── Task: process
│        ↓ (last task completes → job done)
└── Completion: Aggregate results
```

### Key Design Principle: **Composition + Registry**

```python
# Job self-registers via decorator
@JobRegistry.instance().register(job_type="hello_world")
class HelloWorldJob:
    def create_stage_tasks(self, stage, context):
        """Job defines WHAT tasks to create"""
        return [TaskDefinition(...)]

# CoreMachine uses registry (no tight coupling)
job_class = JobRegistry.get(job_type)  # Dynamic lookup
job_handler = job_class()              # Instantiate
tasks = job_handler.create_stage_tasks(stage, context)
```

**Why**: Generic orchestrator + job-specific handlers = extensible without modification

---

## 🗄️ Database Architecture

### Three Schemas (Single PostgreSQL Database: `geopgflex`)

**1. `app` Schema** (Application - Redeployable)
```sql
app.jobs   -- Job orchestration state
app.tasks  -- Task tracking and results
```
- Managed by application code
- Safe to nuke/redeploy in dev: `POST /api/db/schema/redeploy?confirm=yes`
- Uses PostgreSQL functions for atomic operations (last task detection)

**2. `pgstac` Schema** (STAC Catalog - Preserved)
```sql
pgstac.collections  -- STAC collections
pgstac.items        -- STAC items (22 tables total)
```
- Managed by PgSTAC migrations (pypgstac)
- **NEVER nuke in production** (contains business data)
- Installed via: `POST /api/stac/setup?confirm=yes`

**3. `geo` Schema** (Future - Geospatial Data)
- Planned for raster/vector catalogs
- Links to STAC items

### Connection String - CRITICAL RULE

**ONLY ONE connection string in entire codebase**:
```python
from config import get_config
config = get_config()
conn_string = config.postgis_connection_string  # Single source of truth
```

❌ **NEVER** build custom connection strings in modules
❌ **NEVER** duplicate connection logic
✅ **ALWAYS** use `config.postgis_connection_string`

---

## 📂 File Structure (Critical Files)

### Configuration
```
config.py                    # Single source of truth for all config
├── AppConfig (Pydantic v2)  # Strongly typed configuration
└── postgis_connection_string  # THE connection string
```

### Core Orchestration
```
core/
├── registry.py              # JobRegistry singleton
└── machine.py               # CoreMachine (generic orchestrator)
```

### Job Implementations
```
jobs/
├── hello_world.py           # Simple single-stage example
├── list_container.py        # Complex multi-stage fan-out
└── stage_raster.py          # Real-world geospatial workflow
```

### Infrastructure Layer
```
infrastructure/
├── base.py                  # BasePostgreSQLRepository
├── postgresql.py            # PostgreSQL connection management
├── jobs_tasks.py            # JobRepository, TaskRepository
├── stac.py                  # STAC infrastructure (PgSTAC)
├── blob.py                  # Azure Blob Storage
├── queue.py                 # Azure Queue Storage
└── service_bus.py           # Azure Service Bus
```

### Triggers (HTTP Endpoints)
```
triggers/
├── http_base.py             # BaseHttpTrigger (all inherit from this)
├── submit_job.py            # POST /api/jobs/{job_type}
├── get_job_status.py        # GET /api/jobs/status/{job_id}
├── db_query.py              # Database debugging endpoints
└── stac_setup.py            # PgSTAC installation/status
```

### Entry Point
```
function_app.py              # Azure Functions routing
```

---

## 🔧 Common Operations

### Deploy
```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Test
```bash
# Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Submit job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# Check status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Debug Database
```bash
# See all jobs/tasks
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all

# Database stats
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Redeploy schema (DEV ONLY - nukes app schema)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

---

## 🚨 Critical Design Decisions

### 1. No Backward Compatibility
**Reason**: Development environment, core architecture design phase
**Impact**: Breaking changes allowed, explicit errors required
**Example**: Removed direct controller instantiation, forced factory pattern

### 2. Explicit Error Handling
**Contract Violations** (bugs): `ContractViolationError` - let crash
**Business Errors** (expected): `BusinessLogicError` - catch and handle
```python
# Contract violation - programming bug
if not isinstance(job_id, str):
    raise ContractViolationError("job_id must be str")

# Business error - normal failure
try:
    result = process_data()
except ResourceNotFoundError as e:
    logger.warning(f"Resource missing: {e}")
    return {"success": False}
```

### 3. Single Source of Truth
- **Config**: One `config.py`, no duplicate config logic
- **Connection**: One `postgis_connection_string`, no custom builders
- **Registry**: One `JobRegistry`, all jobs register here
- **Schema**: One SQL generator in `infrastructure/postgresql.py`

### 4. PostgreSQL Functions Over Application Logic
**Last Task Detection** uses PostgreSQL function with `FOR UPDATE SKIP LOCKED`:
```sql
CREATE OR REPLACE FUNCTION app.complete_task_and_check_stage(...)
RETURNS TABLE(is_stage_complete BOOLEAN, is_job_complete BOOLEAN) AS $$
  -- Atomic check prevents race conditions
  SELECT COUNT(*) FROM app.tasks
  WHERE job_id = p_job_id AND stage = current_stage
  AND status != 'completed'
  FOR UPDATE SKIP LOCKED;
$$;
```
**Why**: Race-free in distributed task processors

---

## 🎓 Learning Path

### For Quick Fixes (15 minutes)
1. Read this file
2. Check `docs_claude/TODO_ACTIVE.md` for current work
3. Find relevant file in `docs_claude/FILE_CATALOG.md`
4. Make change, test, deploy

### For New Features (1 hour)
1. Read `docs/TASK_REGISTRY_PATTERN.md` (understand job injection)
2. Read `docs_claude/CLAUDE_CONTEXT.md` (full context)
3. Study example job: `jobs/hello_world.py` or `jobs/list_container.py`
4. Copy pattern, add to registry, test

### For Deep Architecture Work (3 hours)
1. Read `docs_claude/ARCHITECTURE_REFERENCE.md` (deep technical specs)
2. Read `POSTGRES_REQUIREMENTS.md` (database architecture)
3. Study `infrastructure/postgresql.py` (repository pattern)
4. Study `core/machine.py` (orchestration engine)
5. Read `docs_claude/HISTORY.md` (evolution and decisions)

---

## 🔍 Quick Lookup

### "Where is...?"
- **Job registration**: `core/registry.py`
- **Job orchestration**: `core/machine.py`
- **Database connection**: `config.py` → `postgis_connection_string`
- **HTTP endpoints**: `function_app.py` (routing) + `triggers/*.py` (handlers)
- **Job examples**: `jobs/hello_world.py`, `jobs/list_container.py`
- **Database schema**: `infrastructure/postgresql.py` → `deploy_schema()`
- **STAC setup**: `infrastructure/stac.py`, endpoint `/api/stac/setup`

### "How do I...?"
- **Add new job type**: Create `jobs/my_job.py`, add `@JobRegistry.instance().register()` decorator
- **Debug job failure**: `curl /api/db/debug/all` or check Application Insights logs
- **Update database schema**: Edit `infrastructure/postgresql.py`, redeploy
- **Add HTTP endpoint**: Create `triggers/my_trigger.py`, register in `function_app.py`
- **Test locally**: Use `local/` scripts (e.g., `local/test_stac_local.py`)

### "Why does...?"
- **Connection fail**: Check using `config.postgis_connection_string` (single source)
- **Job not found**: Check `@JobRegistry.instance().register()` decorator present
- **Task stuck**: Check PostgreSQL function `complete_task_and_check_stage()`
- **Import fail**: Check `/api/health` for validation errors

---

## 🚀 Current State (5 OCT 2025)

### ✅ Working
- PostgreSQL 17.6 + PostGIS 3.6 + PgSTAC 0.8.5
- Job orchestration (Job → Stage → Task)
- Queue-driven task processing
- Database schema deployment
- STAC infrastructure installed
- Health monitoring and import validation

### 🚧 In Progress
- Check `docs_claude/TODO_ACTIVE.md`

### 📋 Next Steps
- Real geospatial workflows (stage_raster, ingest_cog)
- STAC collection management
- Task retry mechanisms
- Error recovery patterns

---

## 💡 Development Philosophy

**Quotes from CLAUDE.md:**

> "No Backward Compatibility: This is a development environment focused on core architecture design and proof of concept."

> "Explicit Error Handling Over Fallbacks: When making core architecture changes, NEVER implement fallback logic."

> "Single Source of Truth: Connection string, configuration, job registry - one place, always."

**Military Date Format**: 5 OCT 2025 (not 2025-10-05)
**Author Attribution**: "Robert and Geospatial Claude Legion"
**Update FILE_CATALOG.md**: After any file changes

---

## 🆘 Emergency Commands

### System is broken
```bash
# Check health
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Check database
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Redeploy schema (DEV ONLY - nukes app.* tables)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

### Need to start fresh
1. Read this file (you are here)
2. Read `docs_claude/CLAUDE_CONTEXT.md`
3. Check `docs_claude/TODO_ACTIVE.md`
4. Continue work

---

## 📞 Key Resources

**Azure Function App**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
**PostgreSQL**: rmhpgflex.postgres.database.azure.com (database: geopgflex)
**Resource Group**: rmhazure_rg
**Storage Account**: rmhazuregeo

**Deployment Command**:
```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

**Post-Deployment Test**:
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

---

**Read time**: 10-15 minutes
**Next**: `docs_claude/CLAUDE_CONTEXT.md` for full details
