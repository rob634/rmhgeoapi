# CLAUDE.md - Project Context

**Last Updated**: 23 DEC 2025

---

## 🎯 START HERE

All Claude-optimized documentation is in **`/docs_claude/`**.

### Key Documents
| Document | Purpose |
|----------|---------|
| `docs_claude/CLAUDE_CONTEXT.md` | Primary context - start here |
| `docs_claude/TODO.md` | **ONLY** active task list |
| `docs_claude/FATHOM_ETL.md` | FATHOM flood data pipeline (Phase 1 & 2) |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Deep technical specs, error handling patterns |
| `docs_claude/ARCHITECTURE_DIAGRAMS.md` | **Visual diagrams** - C4/Mermaid architecture |
| `docs_claude/JOB_CREATION_QUICKSTART.md` | 5-step guide for new jobs |
| `docs_claude/APIM_ARCHITECTURE.md` | Future microservices architecture |
| `docs_claude/APPLICATION_INSIGHTS.md` | Log query patterns |
| `docs_claude/HISTORY.md` | Completed work log |

---

## ⚠️ CRITICAL RULES

1. **USE MILITARY DATE FORMAT**: `15 DEC 2025`
2. **NO BACKWARD COMPATIBILITY**: Fail explicitly, never create fallbacks
3. **NO "PRODUCTION READY"** unless explicitly instructed
4. **GIT**: Work on `dev` branch, merge to `master` when stable

---

## 📋 SAFe AGILE FRAMEWORK

**This project uses SAFe (Scaled Agile Framework) terminology for planning and tracking.**

When planning work or discussing priorities with Robert, use SAFe language:

| SAFe Term | Definition | Example |
|-----------|------------|---------|
| **Epic** | Large strategic initiative spanning multiple sprints | "Data Access Simplification" |
| **Feature** | Deliverable capability within an Epic | "Service Layer API", "Reader App Migration" |
| **Story** | Smallest unit of work (implementable in 1-3 days) | "Implement /api/raster/extract endpoint" |
| **Enabler** | Technical foundation work | "Repository pattern enforcement" |
| **Spike** | Research/investigation task | "Investigate Kerchunk performance" |

### Planning Guidelines

1. **Break Features into Stories** - Each Feature should have 3-8 Stories
2. **Stories should be atomic** - Completable in 1-3 days, independently testable
3. **Use acceptance criteria** - Define "done" for each Story
4. **Track dependencies** - Note when Stories block other Stories

### Encourage Robert to:
- Frame requests as Features or Stories
- Prioritize by business value (which Epic does this serve?)
- Think in terms of increments, not big-bang releases

**TODO.md follows this structure** - see `docs_claude/TODO.md` for the canonical backlog

### Git Commit Format
```
Brief description

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## 🚀 DEPLOYMENT

### Active Environment
| Resource | Value |
|----------|-------|
| **Function App** | `rmhazuregeoapi` (B3 Basic) |
| **URL** | https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net |
| **Database** | rmhpgflex.postgres.database.azure.com |
| **Resource Group** | `rmhazure_rg` |

**DEPRECATED APPS** (never use): `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta`

### Deploy Command
```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### Post-Deployment Validation (REQUIRED)

**Claude MUST perform these steps after EVERY deployment:**

```bash
# Step 1: Wait for app restart (30-60 seconds)
sleep 45

# Step 2: Health check (CRITICAL - detects startup failures)
curl -sf https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**If health check fails (404 or connection error):**

1. **Check Application Insights for `STARTUP_FAILED`** - the app logs missing env vars before crashing:
```bash
# Quick query for startup failures (use APPLICATION_INSIGHTS.md for full setup)
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where message contains 'STARTUP_FAILED' | order by timestamp desc | take 5" \
  -G | python3 -m json.tool
```

2. **Common cause: Missing environment variables**
   - Required: `POSTGIS_HOST`, `POSTGIS_DATABASE`, `POSTGIS_SCHEMA`, `APP_SCHEMA`, `PGSTAC_SCHEMA`, `H3_SCHEMA`
   - Check current settings: `az functionapp config appsettings list --name rmhazuregeoapi --resource-group rmhazure_rg`
   - Add missing: `az functionapp config appsettings set --name rmhazuregeoapi --resource-group rmhazure_rg --settings VAR_NAME=value`

3. **After fixing, restart and re-validate:**
```bash
az functionapp restart --name rmhazuregeoapi --resource-group rmhazure_rg
sleep 45
curl -sf https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

### Post-Deployment Testing (after health check passes)
```bash
# 1. FULL REBUILD DATABASE SCHEMAS (Required after deployment!)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=full-rebuild&confirm=yes"

# 2. Submit Test Job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "deployment test"}'

# 3. Check Job Status
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## 🔧 SCHEMA MANAGEMENT ENDPOINTS

| Endpoint | Purpose |
|----------|---------|
| `POST /api/dbadmin/maintenance?action=full-rebuild&confirm=yes` | **RECOMMENDED**: Atomic rebuild of app+pgstac schemas |
| `POST /api/dbadmin/maintenance?action=redeploy&confirm=yes` | Redeploy app schema only |
| `POST /api/dbadmin/maintenance?action=redeploy&target=pgstac&confirm=yes` | Redeploy pgstac schema only |
| `POST /api/dbadmin/maintenance?action=nuke&confirm=yes` | Drop app schema (caution!) |
| `POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30` | Delete old jobs/tasks |

### STAC Nuclear Button (DEV/TEST ONLY)
```bash
# Clear all STAC items and collections
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=all"
```

---

## 🔍 DATABASE DEBUGGING ENDPOINTS

```bash
# Query jobs
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?status=failed&limit=10

# Query specific job
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs/{JOB_ID}

# Get tasks for job
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/tasks/{JOB_ID}

# Database stats
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/stats

# All diagnostics
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/diagnostics/all
```

**Query Parameters**: `limit`, `status` (pending/processing/completed/failed), `hours`, `job_type`

---

## 🌍 OGC FEATURES API

```bash
# Landing page
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features

# List collections
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections

# Query features with bbox
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{collection}/items?bbox=-70.7,-56.3,-70.6,-56.2&limit=5"
```

**Interactive Map**: https://rmhazuregeo.z13.web.core.windows.net/

---

## 🔍 APPLICATION INSIGHTS LOG ACCESS

**Full Guide**: `docs_claude/APPLICATION_INSIGHTS.md`

### Quick Reference
```bash
# Step 1: Login
az login

# Step 2: Run query script
# rmhazuregeoapi App ID: d3af3d37-cfe3-411f-adef-bc540181cbca
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

**DO NOT try**: `az monitor app-insights query`, inline token commands - they fail!

---

## 📝 FILE HEADER TEMPLATE

All .py files should use this header format:

```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Main classes, functions, constants]
# DEPENDENCIES: [Key external libraries]
# ============================================================================
```

---

## 🏗️ ARCHITECTURE OVERVIEW

### Job → Stage → Task Pattern
```
JOB (Controller Layer)
 ├── STAGE 1 (Sequential)
 │   ├── Task A (Parallel)
 │   ├── Task B (Parallel)
 │   └── Task C (Parallel)
 ├── STAGE 2 (Sequential)
 │   └── Task D
 └── COMPLETION
```

### Key Concepts
- **Stages execute sequentially**, tasks execute in parallel
- **"Last Task Turns Out the Lights"**: Atomic SQL detects stage completion
- **Idempotent Job IDs**: SHA256(job_type + params) for deduplication

### Data Tiers
- **Bronze**: Raw data (`rmhazuregeobronze`)
- **Silver**: COGs + PostGIS
- **Gold**: GeoParquet exports (future)

**Full architecture details**: `docs_claude/ARCHITECTURE_REFERENCE.md`
**Visual diagrams**: `docs_claude/ARCHITECTURE_DIAGRAMS.md`

---

## 🚀 CREATING NEW JOBS

Use **JobBaseMixin** pattern - eliminates 77% boilerplate.

**Full guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`

### Quick Reference
```python
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class MyJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    job_type = "my_job"
    description = "What this job does"

    stages = [
        {"number": 1, "name": "stage_name", "task_type": "handler_name", "parallelism": "single"}
    ]

    parameters_schema = {
        'param': {'type': 'str', 'required': True}
    }

    @staticmethod
    def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
        return [{"task_id": f"{job_id[:8]}-s{stage}", "task_type": "handler_name", "parameters": {}}]
```

**Register in**: `jobs/__init__.py` and `services/__init__.py`

---

## 🚨 DEVELOPMENT PHILOSOPHY

### No Backward Compatibility
This is a **development environment** - never create fallbacks that mask breaking changes.

```python
# ❌ WRONG - Hides problems
job_type = entity.get('job_type') or 'default_value'

# ✅ CORRECT - Explicit errors
job_type = entity.get('job_type')
if not job_type:
    raise ValueError("job_type is required field")
```

### Error Handling
- **Contract Violations** (`ContractViolationError`): Programming bugs - let them bubble up
- **Business Errors** (`BusinessLogicError`): Expected failures - handle gracefully

**Full patterns**: `docs_claude/ARCHITECTURE_REFERENCE.md` → Error Handling Strategy

---

## 📚 REFERENCE LINKS

| Topic | Document |
|-------|----------|
| Job creation | `docs_claude/JOB_CREATION_QUICKSTART.md` |
| Architecture details | `docs_claude/ARCHITECTURE_REFERENCE.md` |
| **Architecture diagrams** | `docs_claude/ARCHITECTURE_DIAGRAMS.md` |
| Error handling | `docs_claude/ARCHITECTURE_REFERENCE.md` → Error Handling Strategy |
| APIM future plans | `docs_claude/APIM_ARCHITECTURE.md` |
| Service Bus config | `docs_claude/SERVICE_BUS_HARMONIZATION.md` |
| Schema design | `docs_claude/SCHEMA_ARCHITECTURE.md` |
| Log queries | `docs_claude/APPLICATION_INSIGHTS.md` |
| Completed work | `docs_claude/HISTORY.md` |

---

## 🗂️ AZURE FUNCTIONS FOLDER STRUCTURE

**Critical Lesson** (22 SEP 2025):
1. `__init__.py` is **REQUIRED** in each folder
2. `.funcignore` must **NOT** have `*/` (excludes all subdirectories!)
