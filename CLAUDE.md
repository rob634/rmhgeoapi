# CLAUDE.md - Project Context

**Last Updated**: 10 JAN 2026

---

## 🐍 PYTHON ENVIRONMENT

**ALWAYS use the `azgeo` conda environment for this project.**

```bash
# Activate before running any Python
conda activate azgeo

# Or use full path for scripts
/Users/robertharrison/anaconda3/envs/azgeo/bin/python

# Verify correct environment
which python  # Should show: .../anaconda3/envs/azgeo/bin/python
```

| Environment | Python | numpy | Status |
|-------------|--------|-------|--------|
| `azgeo` | 3.12 | 2.3.3 | ✅ **USE THIS** |
| `base` | 3.11 | 1.26.4 | ❌ Broken dependencies |

**DO NOT** use the base anaconda environment - it has broken geospatial dependencies.

---

## 🎯 START HERE

All Claude-optimized documentation is in **`/docs_claude/`**.

### Key Documents
| Document | Purpose |
|----------|---------|
| `docs_claude/CLAUDE_CONTEXT.md` | Primary context - start here |
| `docs_claude/TODO.md` | **ONLY** active task list |
| `docs_claude/DEV_BEST_PRACTICES.md` | **Lessons learned** - patterns, common mistakes, gotchas |
| `docs_claude/ERRORS_AND_FIXES.md` | **Error tracking** - search here first when debugging |
| `docs_claude/SCHEMA_EVOLUTION.md` | **Schema changes** - safe vs breaking, migration patterns |
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

### GitHub Project (Primary Tracking)
- **Project URL**: https://github.com/users/rob634/projects/1
- **Repository**: https://github.com/rob634/rmhgeoapi
- **Setup Guide**: `docs_claude/github_safe.md`

Work items are tracked as GitHub Issues with SAFe labels (`epic`, `feature`, `story`, `enabler`).
Custom fields: Type, Epic (parent), Priority (WSJF-based).

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

### Source of Truth
- **GitHub Project**: Primary tracking for Epics, Features, Stories
- **EPICS.md**: Master definitions and WSJF calculations
- **TODO.md**: Sprint-level task details and delegation notes

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
| **Database** | rmhpostgres.postgres.database.azure.com |
| **Resource Group** | `rmhazure_rg` |

**DEPRECATED APPS** (never use): `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta`

**DEPRECATED DATABASE**: `rmhpgflex.postgres.database.azure.com` (decommissioned)

### Deploy Command
```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### Versioning Convention

Version format: `0.v.i.d` (defined 04 JAN 2026)

| Segment | Meaning | When to Increment |
|---------|---------|-------------------|
| `0` | Pre-production | Stays 0 until production release (then 1.0.0) |
| `v` | Version | Major feature set / architectural epoch |
| `i` | Iteration | Work batch (features, refactoring, reviews) |
| `d` | Deployment | Optional - hotfixes between iterations |

**Examples:**
- `0.7.3` → Version 7, iteration 3
- `0.7.3.1` → Deployment fix after 0.7.3 (no new features)
- `0.7.4` → New iteration with features
- `0.8.0` → New major version/epoch

**Version location**: `config/__init__.py` → `__version__`

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
# 1. REBUILD DATABASE SCHEMAS (Required after deployment!)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"

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
| `POST /api/dbadmin/maintenance?action=ensure&confirm=yes` | **SAFE**: Additive sync - creates missing tables/indexes (no data loss) |
| `POST /api/dbadmin/maintenance?action=rebuild&confirm=yes` | **DESTRUCTIVE**: Atomic rebuild of app+pgstac schemas |
| `POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes` | **DESTRUCTIVE**: Rebuild app schema only (with warning) |
| `POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes` | **DESTRUCTIVE**: Rebuild pgstac schema only (with warning) |
| `POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30` | Delete old jobs/tasks |

**Use `action=ensure`** when deploying new tables - it's safe and won't drop existing data.

**Note**: Rebuilding app and pgstac together is recommended because job IDs in app.jobs correspond to STAC items in pgstac.items. Rebuilding one without the other may create orphaned references.

### STAC Nuclear Button (DEV/TEST ONLY)
```bash
# Clear all STAC items and collections
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=all"
```

---

## 📐 SCHEMA EVOLUTION PATTERN

**Principle**: Prefer non-breaking (additive) changes. Breaking changes require migration plans.

### Decision Tree

| Change Type | Action | Safe? |
|-------------|--------|-------|
| Add new table | `action=ensure` | ✅ Yes |
| Add new column with DEFAULT | `action=ensure` | ✅ Yes |
| Add new index | `action=ensure` | ✅ Yes |
| Add new enum type | `action=ensure` | ✅ Yes |
| Add value to existing enum | Migration script | ⚠️ Careful |
| Rename column/table | Migration script | ❌ Breaking |
| Change column type | Migration script | ❌ Breaking |
| Remove column/table | Migration script | ❌ Breaking |

### Quick Rules

1. **New features** → Add new tables/columns, use `action=ensure`
2. **Schema fixes** → Write migration script, test on dev first
3. **Never** → Modify existing columns in production without migration plan

**Full guide**: `docs_claude/SCHEMA_EVOLUTION.md`

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

## 🔧 ERROR TROUBLESHOOTING

**Canonical error log**: `docs_claude/ERRORS_AND_FIXES.md`

### When You Encounter an Error

1. **Search ERRORS_AND_FIXES.md first** - many errors have already been solved
2. **Check error category** - CONFIG, IMPORT, DATABASE, STORAGE, HEALTH, DEPLOYMENT, UI, PIPELINE, CODE
3. **Apply documented fix** - follow resolution steps exactly

### After Fixing Any Error

**ALWAYS add the error to `docs_claude/ERRORS_AND_FIXES.md`** with:
- Exact error message (for searchability)
- Root cause analysis
- Fix applied (with code snippets)
- Related change that triggered it
- Prevention tips

### Common Error Patterns

| Symptom | First Check | Likely Category |
|---------|-------------|-----------------|
| `'object has no attribute'` | Config access pattern | CFG-xxx |
| `ImportError: cannot import` | Circular imports, library changes | IMP-xxx |
| Job stuck in PROCESSING | CoreMachine transitions | PIP-xxx |
| `relation does not exist` | Schema rebuild needed | DB-xxx |
| App won't start | Missing env vars | DEP-xxx |
| UI not updating | JS data paths changed | UI-xxx |

### Config Access Quick Reference

```python
# AppConfig attributes (via get_config()):
config.storage, config.database, config.queues, config.raster,
config.vector, config.analytics, config.h3, config.platform, config.metrics

# AppModeConfig (SEPARATE singleton - common mistake!):
from config import get_app_mode_config
app_mode_config = get_app_mode_config()
app_mode_config.docker_worker_enabled
```

---

## 📚 REFERENCE LINKS

| Topic | Document |
|-------|----------|
| **Dev best practices** | `docs_claude/DEV_BEST_PRACTICES.md` |
| **Schema evolution** | `docs_claude/SCHEMA_EVOLUTION.md` |
| **Error tracking** | `docs_claude/ERRORS_AND_FIXES.md` |
| Job creation | `docs_claude/JOB_CREATION_QUICKSTART.md` |
| Architecture details | `docs_claude/ARCHITECTURE_REFERENCE.md` |
| **Architecture diagrams** | `docs_claude/ARCHITECTURE_DIAGRAMS.md` |
| Error handling patterns | `docs_claude/ARCHITECTURE_REFERENCE.md` → Error Handling Strategy |
| APIM future plans | `docs_claude/APIM_ARCHITECTURE.md` |
| Service Bus config | `docs_claude/SERVICE_BUS_HARMONIZATION.md` |
| Schema design | `docs_claude/SCHEMA_ARCHITECTURE.md` |
| Log queries | `docs_claude/APPLICATION_INSIGHTS.md` |
| Memory profiling | `docs_claude/MEMORY_PROFILING.md` |
| Completed work | `docs_claude/HISTORY.md` |

---

## 🗂️ AZURE FUNCTIONS FOLDER STRUCTURE

**Critical Lesson** (22 SEP 2025):
1. `__init__.py` is **REQUIRED** in each folder
2. `.funcignore` must **NOT** have `*/` (excludes all subdirectories!)
