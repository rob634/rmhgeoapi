# 📁 Documentation Has Been Restructured

**Date**: 16 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Claude - Start Here!

All Claude-optimized documentation has been moved to the **`/docs_claude/`** folder for better organization.

### Primary Entry Point:
```
📂 /docs_claude/CLAUDE_CONTEXT.md
```

This is your main starting point - it contains everything you need to understand the system quickly.

### Documentation Structure:
```
docs_claude/
├── CLAUDE_CONTEXT.md                      # 🎯 START HERE - Primary context
├── TODO.md                                # ⚡ PRIMARY TASK LIST - Only active TODO file
├── COREMACHINE_PLATFORM_ARCHITECTURE.md   # 🏗️ NEW - Two-layer architecture (26 OCT 2025)
├── ARCHITECTURE_REFERENCE.md              # Deep technical specifications
├── FILE_CATALOG.md                        # Quick file lookup
├── DEPLOYMENT_GUIDE.md                    # Deployment procedures
└── HISTORY.md                             # Completed work log
```

### Quick Access Commands:
```bash
# View primary context
cat docs_claude/CLAUDE_CONTEXT.md

# Check active tasks (ONLY TODO file)
cat docs_claude/TODO.md

# See technical details
cat docs_claude/ARCHITECTURE_REFERENCE.md
```

## Important Notes:
- **USE MILITARY DATE FORMAT** (22 SEP 2025)
- **Author Attribution**: "Robert and Geospatial Claude Legion"
- **Update FILE_CATALOG.md** after any file changes

## 🔀 Git Workflow - Dev Branch Strategy (9 OCT 2025)

**CRITICAL: Always work on `dev` branch, commit frequently with detailed messages**

### Branch Strategy:
- **`dev`** - Active development branch (commit frequently here)
- **`master`** - Stable milestones only (merge from dev when stable)

### Workflow Pattern:
```bash
# 1. Ensure you're on dev branch
git checkout dev

# 2. Make changes and commit frequently with descriptive messages
git add -A
git commit -m "descriptive message about what changed"

# 3. When stable, merge to master
git checkout master
git merge dev
git push origin master

# 4. Continue working on dev
git checkout dev
```

### Why This Pattern:
- **Frequent commits on dev** = Detailed git history of what broke and when
- **Clean master** = Only stable, tested code
- **Easy rollback** = Can always revert to last working commit on dev
- **Clear debugging** = Git log shows exactly what changed between working/broken states

### Commit Message Format:
```
Brief description of changes

🔧 Technical details (what was changed)
✅ Status updates (what works now)
⚠️ Known issues (what's still broken)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Lesson Learned**: Moving too fast on STAC + Raster ETL without commits = Lost track of what broke Azure Functions with no git history. Never again!

## 🚀 Folder Migration Status (22 SEP 2025) - CRITICAL SUCCESS!

### ✅ ACHIEVED: Azure Functions Now Support Folder Structure!

**What We Learned (CRITICAL FOR FUTURE MIGRATIONS):**
1. **`__init__.py` is REQUIRED** in each folder to make it a Python package
2. **`.funcignore` must NOT have `*/`** - this excludes ALL subdirectories!
3. **Both import styles work** with proper `__init__.py`:
   - `from utils.contract_validator import enforce_contract`
   - `from utils import enforce_contract` (if exported in `__init__.py`)

**Current Status:**
- ✅ **utils/** folder created with `__init__.py`
- ✅ **contract_validator.py** successfully moved to `utils/`
- ✅ All 5 files updated with new import paths
- ✅ `.funcignore` fixed - removed `*/` wildcard
- ✅ Deployment verified - health endpoint responding!

**Next Migration Candidates:**
- `schemas/` - All schema_*.py files (6 files)
- `controllers/` - All controller_*.py files (5 files)
- `repositories/` - All repository_*.py files (6 files)
- `services/` - All service_*.py files (4 files)
- `triggers/` - All trigger_*.py files (7 files)

## 📚 Quick Navigation Index

### Priority Items
- **Current Priority** → Line 38 (Error Handling Implementation)
- **TODO.md Reference** → Line 118 (Current development tasks)
- **Recent Achievements** → Line 346 (Completed work summary)

### Core Documentation
- **File Structure** → Line 47 (Universal header template)
- **Development Philosophy** → Line 93 (No Backward Compatibility)
- **Architecture Overview** → Line 149 (Job→Stage→Task abstraction)
- **Database Schema** → Line 264 (PostgreSQL tables)
- **Project Structure** → Line 283 (File organization)

### Technical Sections
- **Queue-Driven Orchestration** → Line 166
- **Key Design Features** → Line 173
- **Factory & Registry Pattern** → Line 226
- **Pydantic Models** → Line 239
- **Auto-Discovery System** → Line 188

### Configuration & Deployment
- **Key URLs** → Line 120 (Function App, Database)
- **Deployment Info** → Line 126 (Active apps, commands)
- **Storage Environment** → Line 131 (Azure storage keys)
- **Database Monitoring Endpoints** → Line 362

### Implementation Details
- **Workflow Architecture Rationale** → Line 440
- **Job Idempotency** → Line 457
- **Future Implementation** → Line 463
- **PostGIS Details** → Line 476

**Stage Advancement Logic**: Partially implemented, needs completion for end-to-end job workflow

## 🚨 Contract Violations vs Business Errors

**CRITICAL DISTINCTION FOR ERROR HANDLING (26 SEP 2025)**

### Contract Violations (Programming Bugs)
**Type**: `ContractViolationError` (inherits from `TypeError`)
**When**: Wrong types passed, missing required fields, interface violations
**Handling**: NEVER catch these - let them bubble up to crash the function
**Purpose**: Find bugs during development, not runtime failures

**Examples**:
```python
# Contract violation - wrong type passed
if not isinstance(job_id, str):
    raise ContractViolationError(
        f"job_id must be str, got {type(job_id).__name__}"
    )

# Contract violation - wrong return type from method
if not isinstance(result, (dict, TaskResult)):
    raise ContractViolationError(
        f"Handler returned {type(result).__name__} instead of TaskResult"
    )
```

### Business Logic Errors (Expected Runtime Failures)
**Type**: `BusinessLogicError` and subclasses
**When**: Normal failures during operation (network issues, missing resources)
**Handling**: Catch and handle gracefully
**Purpose**: Keep system running despite expected issues

**Subclasses**:
- `ServiceBusError` - Service Bus communication failures
- `DatabaseError` - Database operation failures
- `TaskExecutionError` - Task failed during execution
- `ResourceNotFoundError` - Resource doesn't exist
- `ValidationError` - Business validation failed

**Examples**:
```python
# Business error - Service Bus unavailable
except ServiceBusError as e:
    logger.warning(f"Service Bus temporarily unavailable: {e}")
    return {"success": False, "retry": True}

# Business error - File not found in blob storage
except ResourceNotFoundError as e:
    logger.info(f"Expected resource not found: {e}")
    return {"success": False, "error": str(e)}
```

### Implementation Pattern
```python
try:
    # Validate contracts first
    if not isinstance(param, expected_type):
        raise ContractViolationError("...")

    # Execute business logic
    result = do_work(param)

except ContractViolationError:
    # Let contract violations bubble up (bugs)
    raise

except BusinessLogicError as e:
    # Handle expected business failures gracefully
    logger.warning(f"Business failure: {e}")
    return handle_business_failure(e)

except Exception as e:
    # Log unexpected errors with full details
    logger.error(f"Unexpected: {e}\n{traceback.format_exc()}")
    return handle_unexpected_error(e)
```

**FILE STRUCTURE**
All .py files use Google style documentation but at the top before that, please maintain Claude Context Config in the format below
**PLEASE UPDATE PROJECT_FILE_INDEX.md AS NEEDED**
## 📝 Universal Header Template

```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description of what this file does]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Main classes, functions, or constants exposed to other modules]
# INTERFACES: [Abstract base classes or protocols this file implements]
# PYDANTIC_MODELS: [Data models defined or consumed by this file]
# DEPENDENCIES: [Key external libraries: GDAL, psycopg, azure-storage]
# SOURCE: [Where data comes from: env vars, database, blob storage, etc.]
# SCOPE: [Operational scope: global, service-specific, environment-specific]
# VALIDATION: [How inputs/config are validated: Pydantic, custom validators]
# PATTERNS: [Architecture patterns used: Repository, Factory, Singleton]
# ENTRY_POINTS: [How other code uses this: import statements, main functions]
# INDEX: [Major sections with line numbers for quick navigation]
# ============================================================================
```

**CRITICALY IMPORTANT - DO NOT UPDATE ANY .MD FILES WITH "PRODUCTION READY" UNLESS EXPLICILTY INSTRUCTED TO DO SO**

**CRITICAL DEPLOYMENT INFORMATION**
Please refer to claude_log_access.md for instructions on accessing function app application insights logs for testing and debugging



**Important md files**
- docs_claude/TODO.md - ⚡ PRIMARY AND ONLY active task list
- docs_claude/HISTORY.md - Completed work log
- docs_claude/CLAUDE_CONTEXT.md - Primary context
- docs_claude/FILE_CATALOG.md - Quick file lookup
- docs_claude/ARCHITECTURE_REFERENCE.md - Deep technical specs

**Key URLs**:
- Function App: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net (**ONLY** active app)
- Database: rmhpgflex.postgres.database.azure.com (geo schema)
- Resource Group: `rmhazure_rg` (NOT rmhresourcegroup)

**🚨 CRITICAL DEPLOYMENT INFO:**
- **ACTIVE FUNCTION APP**: `rmhgeoapibeta` (ONLY this one!)
- **DEPRECATED APPS**: `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn` (NEVER use these)
- **DEPLOYMENT COMMAND**: `func azure functionapp publish rmhgeoapibeta --python --build remote`

**📋 POST-DEPLOYMENT TESTING:**
```bash
# 1. Health Check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 2. 🔄 REDEPLOY DATABASE SCHEMA (Required after deployment!)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# 3. Submit Test Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "deployment test"}'

# 4. Check Job Status (use job_id from step 3)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**🔄 SCHEMA MANAGEMENT ENDPOINTS:**
- **Redeploy (Recommended)**: `POST /api/db/schema/redeploy?confirm=yes` - Nuke and redeploy in one operation
- **Nuke Only**: `POST /api/db/schema/nuke?confirm=yes` - Just drop everything (use with caution)

**🔍 DATABASE DEBUGGING ENDPOINTS (No DBeaver Required!):**
```bash
# Get all jobs and tasks (comprehensive dump)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all?limit=100

# Query specific job by ID
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs/{JOB_ID}

# Query all jobs with filters
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?status=failed&limit=10

# Get all tasks for a specific job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}

# Query tasks with filters
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks?status=failed&limit=20

# Database statistics and health
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Test PostgreSQL functions
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/functions/test

# Diagnose enum types
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/enums/diagnostic
```

**Query Parameters:**
- `limit`: Max number of results (default: 100)
- `status`: Filter by status (pending, processing, completed, failed)
- `hours`: Only show records from last N hours
- `job_type`: Filter by job type

**🔍 APPLICATION INSIGHTS LOG ACCESS (CRITICAL FOR DEBUGGING):**

**PREREQUISITE - Must be logged in to Azure:**
```bash
# Login via browser (required once per session)
az login

# Verify login
az account show --query "{subscription:name, user:user.name}" -o table
```

**RECOMMENDED PATTERN - Script File (Most Reliable):**
```bash
# Create query script
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 10" \
  -G
EOF

# Execute and format
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

**Common KQL Queries (replace query= in script above):**
```kql
# Recent errors
traces | where timestamp >= ago(1h) | where severityLevel >= 3 | order by timestamp desc | take 20

# Retry-related logs
traces | where timestamp >= ago(15m) | where message contains "retry" or message contains "RETRY" | order by timestamp desc

# Task processing
traces | where timestamp >= ago(15m) | where message contains "Processing task" | order by timestamp desc

# Health endpoint
union requests, traces | where timestamp >= ago(30m) | where operation_Name contains "health" | take 20
```

**Key Identifiers:**
- **App ID**: `829adb94-5f5c-46ae-9f00-18e731529222`
- **Resource Group**: `rmhazure_rg`
- **Function App**: `rmhgeoapibeta`

**Important Notes:**
- **Must run `az login` first** (opens browser for auth)
- Bearer tokens expire after 1 hour - script regenerates automatically
- **Use script file pattern** - inline commands fail due to shell evaluation issues
- Standard `az monitor app-insights query` doesn't work (requires AAD auth)
- **Full guide**: `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md`
- **Auth details**: `docs_claude/claude_log_access.md`

**STORAGE ENVIRONMENT**
Use rmhazuregeo with the storage account key to access storage to check queues and containers
[REDACTED - See Azure Portal or Key Vault for actual key]

## 🚨 Development Philosophy: No Backward Compatibility

**CRITICAL: This is a development environment focused on core architecture design and proof of concept.**

### Core Principle: Explicit Error Handling Over Fallbacks

When making core architecture changes, **NEVER implement fallback logic or attempt to accomodate legacy code**. Instead:

✅ **DO**: Add explicit error handling with clear migration guidance  
❌ **DON'T**: Create fallbacks that mask breaking changes  

### Examples

**❌ WRONG - Fallback Pattern:**
```python
# BAD: Hides architectural changes
job_type = entity.get('job_type') or entity.get('job_type')
if not job_type:
    job_type = 'default_value'  # Masks the problem
```

**✅ CORRECT - Explicit Error Pattern:**
```python
# GOOD: Forces proper migration
job_type = entity.get('job_type')
if not job_type:
    job_type = entity.get('job_type')
    if job_type:
        logger.error(f"Found deprecated job_type: {job_type}")
        raise ValueError(f"job_type required (found job_type: {job_type})")
    else:
        raise ValueError("job_type is required field")
```

### Rationale

**Why no backward compatibility?**
1. **Development Environment**: No production users to maintain compatibility for
2. **Core Design Focus**: Architecture changes need to be clean and intentional because we are designing first principles for a much larger system
3. **Clear Migration Path**: Errors force proper updates rather than hidden technical debt
4. **Fast Iteration**: No legacy code slowing down development
5. **Quality Enforcement**: Explicit errors catch integration issues immediately


### Implementation Guidelines

**When changing core architecture:**
1. **Remove deprecated patterns completely**
2. **Add explicit validation with clear error messages**
3. **Update all calling code to use new pattern**
4. **Add tests that verify deprecated patterns fail**
5. **Document migration requirements clearly**

**Error messages should:**
- Clearly state what's wrong
- Explain the new required pattern
- Provide specific field/parameter guidance
- Include the deprecated value found (for debugging)

### Recent Examples

**Controller Pattern Migration (7 September 2025):**
- ❌ Removed: Direct instantiation `controller = HelloWorldController()`
- ✅ Added: Factory pattern `controller = JobFactory.create_controller("hello_world")`
- ✅ Added: Decorator registration `@JobRegistry.instance().register()`
- ✅ Added: Clear error for unregistered job types

**Result**: Clean factory pattern with no direct controller instantiation allowed.

This approach ensures rapid development, clean code, and forces proper architectural compliance.



## 🏗️ Architecture

### **Job → Stage → Task Abstraction**
```
JOB (Controller Layer - Orchestration)
 ├── STAGE 1 (Controller Layer - Sequential)
 │   ├── Task A (Service + Repository Layer - Parallel)
 │   ├── Task B (Service + Repository Layer - Parallel) 
 │   └── Task C (Service + Repository Layer - Parallel)
 │                     ↓ Last task completes stage
 ├── STAGE 2 (Controller Layer - Sequential)
 │   ├── Task D (Service + Repository Layer - Parallel)
 │   └── Task E (Service + Repository Layer - Parallel)
 │                     ↓ Last task completes stage
 └── COMPLETION (job_type specific aggregation)
```

### **Queue-Driven Orchestration**
```
HTTP Request → Jobs Queue → Job Controller → Tasks Queue → Task Processors
                   ↓              ↓               ↓             ↓
               Job Record    Stage Creation   Task Records   Service Layer
```

### **Key Design Features**

#### **Sequential Stages with Parallel Tasks**
- **Stages execute sequentially**: Stage 1 → Stage 2 → ... → Completion
- **Tasks execute in parallel**: All tasks in a stage run concurrently
- **Results flow forward**: Previous stage results passed to next stage

#### **"Last Task Turns Out the Lights"**
- **Atomic detection**: SQL operations prevent race conditions
- **Stage completion**: Last task in stage triggers transition
- **Job completion**: Last task in final stage triggers job completion

#### **Idempotent Operations**
- **Job IDs**: SHA256 hash of parameters for natural deduplication
- **Duplicate submissions**: Return existing job without creating new one
- **Parameter consistency**: Same inputs always produce same job ID

#### **Auto-Discovery Import Validation System** 🔍
- **Automatic Module Detection**: Scans filesystem for new Python files using naming patterns
- **Zero-Configuration Monitoring**: New classes automatically included in health validation
- **Two-Tier Validation**: Critical external dependencies + auto-discovered application modules
- **Continuous Health Reporting**: `/api/health` endpoint provides real-time import status

**Auto-Discovery Patterns:**
```
controller_*.py → "* workflow controller"
service_*.py    → "* service implementation"  
model_*.py      → "* Pydantic model definitions"
repository_*.py → "* repository layer"
trigger_*.py    → "* HTTP trigger class"
util_*.py       → "* utility module"
validator_*.py  → "* validation utilities"
```

**Import Validation Registry Structure:**
```json
{
  "critical_modules": {
    "azure.functions": { "status": "success", "last_validated": "..." },
    "pydantic": { "status": "success", "last_validated": "..." }
  },
  "application_modules": {
    "controller_hello_world": { "auto_discovered": true, "status": "success" },
    "service_geospatial": { "auto_discovered": true, "status": "success" }
  }
}
```

**Benefits for Development:**
- **Early Import Detection**: Catches missing dependencies before runtime failures
- **Deployment Verification**: Confirms all modules load correctly in Azure Functions
- **Health Monitoring**: Real-time status via health endpoint  
- **Zero Maintenance**: Automatically includes new files following naming conventions

### **Core Classes & Patterns**

#### **Factory & Registry Pattern (NEW 7 September 2025)**
- **JobFactory**: Creates controllers via `JobFactory.create_controller(job_type)`
- **JobRegistry**: Singleton registry for decorator-based controller registration
- **TaskFactory**: Creates bulk tasks (100-1000) with semantic IDs like "tile_x5_y10"

#### **Abstract Base Classes**
- **BaseController**: Job orchestration with abstract methods:
  - `validate_job_parameters()`: Validate job parameters
  - `create_stage_tasks()`: Create tasks for a stage
  - `aggregate_stage_results()`: Aggregate task results
  - `should_advance_stage()`: Determine stage advancement

#### **Pydantic Models**
- **WorkflowDefinition**: Defines job stages and dependencies
- **StageDefinition**: Stage configuration (task type, parallelism, timeouts)
- **JobRecord/TaskRecord**: Database models with JSONB fields
- **TaskResult**: Task execution results with success/failure status

### **Database Schema (PostgreSQL)**
**🚨 ARCHITECTURAL DECISION: PostgreSQL Replaces Azure Storage Tables**

**Rationale:**
- **Race Condition Prevention**: ACID transactions prevent "last task turns out lights" race conditions
- **Strict Schema Enforcement**: PostgreSQL enforces data types, constraints, and relationships
- **Complex Queries**: Support for joins, aggregations, and advanced querying
- **Atomic Operations**: Critical for workflow state transitions

```sql
-- PostgreSQL Tables (app schema)
jobs: id, job_type, status, stage, parameters, metadata, result_data, created_at, updated_at

-- Tasks table  
tasks: id, job_id, task_type, status, stage, parameters, heartbeat, retry_count, metadata, result_data, created_at, updated_at
```

**⚠️ DEPRECATED: Azure Storage Tables**
- Storage Tables were replaced due to race condition vulnerabilities
- Health endpoint shows table errors (expected - tables no longer used)

## 📁 Current Project Structure (Updated 7 September 2025)
```
rmhgeoapi/ (32 files total)
├── function_app.py          # Azure Functions entry point
├── config.py                # Strongly typed configuration with Pydantic v2 ⭐ NEW
├── host.json                # Azure Functions runtime configuration
├── requirements.txt         # Python dependencies
│
├── Job→Task Architecture (Pydantic Strong Typing):
│   ├── controller_base.py         # ✅ Abstract base with workflow validation
│   ├── controller_hello_world.py  # ✅ HelloWorld 2-stage implementation  
│   ├── model_core.py              # ✅ Core Pydantic models for Job→Task
│   ├── model_job_base.py          # ✅ Job parameter models
│   ├── model_stage_base.py        # ✅ Stage workflow models  
│   ├── model_task_base.py         # ✅ Task execution models
│   ├── schema_core.py             # ✅ Schema validation utilities
│   ├── schema_workflow.py         # ✅ Workflow definition schemas
│   ├── service_hello_world.py     # ✅ HelloWorld business logic
│   └── validator_schema.py        # ✅ Custom validators
│
├── Storage & Repository Layer:
│   ├── adapter_storage.py   # ✅ Azure Storage abstraction
│   └── repository_data.py   # ✅ Data repository patterns with completion detection
│
├── Utilities:
│   ├── util_completion.py   # Job completion orchestration
│   └── util_logger.py       # Centralized logging
│
├── Configuration:
│   ├── local.settings.json  # Local development configuration
│   ├── local.settings.example.json # Configuration template
│   └── INFRA_CONFIG.md      # Azure infrastructure documentation
│
└── Documentation (8 files):
    ├── CLAUDE.md            # 🚨 PRIMARY: Project context & status
    ├── CONFIGURATION_USAGE.md # Config system usage guide ⭐ NEW  
    ├── PROJECT_FILE_INDEX.md # Complete file catalog ⭐ NEW
    ├── FILE_NAMING_CONVENTION.md # Naming standards
    ├── HELLO_WORLD_IMPLEMENTATION_PLAN.md # Controller demo (not working)
    ├── STRONG_TYPING_ARCHITECTURE_STATUS.md # Typing status
    ├── consolidated_redesign.md # Architecture evolution
    └── redesign.md          # Historical design docs
```

## 🔑 Core Concepts

### Endpoint Usage (CRITICAL)
- **Primary Endpoint**: `/api/jobs/{job_type}` 


### Data Tiers
- **Bronze**: Raw data deposited by users (or Robert)(`rmhazuregeobronze`)
- **Silver**: COGs + PostGIS
- **Gold**: GeoParquet exports (future)


## 🚀 Current Status (Updated 7 September 2025)

### **Recent Achievements (See HISTORY.md for details)**
- ✅ Repository Architecture Cleanup: Clear naming, no duplicates (7 Sept)
- ✅ Controller Factory Pattern: Decorator-based registration (7 Sept)  
- ✅ BaseController Consolidation: Single source of truth (7 Sept)
- ✅ psycopg.sql Composition: SQL injection prevention (5 Sept)
- ✅ Database Monitoring System: Nuclear Red Button (3 Sept)
- ✅ Poison Queue Root Cause: 4 critical issues fixed (3 Sept)

### **Operational Status**

**Systems Working:**
- HTTP job submission → Queue message creation → Queue processing → Database retrieval
- PostgreSQL schema validation and function deployment
- Enhanced logging with correlation tracking
- Database query endpoints (`/api/db/*`)
- Nuclear Red Button schema reset system

**Database Monitoring Endpoints:**
- `/api/db/jobs` - Query jobs with filtering
- `/api/db/tasks/{job_id}` - Query tasks for specific job  
- `/api/db/stats` - Database statistics and metrics
- `/api/db/enums/diagnostic` - Schema diagnostic tools
- `/api/db/functions/test` - Function testing and verification
- `/api/db/schema/nuke?confirm=yes` - Nuclear schema reset (DEV ONLY)

## 💡 Key Technical Decisions

### **Complex Workflow Architecture Rationale**
The sophisticated Job→Stage→Task system accommodates real-world geospatial workflows like "stage raster":

**Example Real Workflow - "stage_raster":**
1. **Stage 1**: Ensure metadata exists, extract if missing
2. **Stage 2**: If raster is gigantic, create tiling scheme  
3. **Stage 3**: **Fan-out** - Parallel tasks to reproject/validate raster chunks
4. **Stage 4**: **Fan-out** - Parallel tasks to convert chunks to COGs
5. **Stage 5**: Job completion updates STAC record with tiled COGs as single dataset

**Architecture Features Supporting This:**
- **Sequential Stages**: Each stage waits for previous to complete
- **Fan-out/Fan-in**: Stages can create N parallel tasks, wait for all to complete
- **Inter-stage Data Flow**: Results from previous stages feed into next stages
- **"Last Task Turns Out Lights"**: Atomic completion detection prevents race conditions

### Job Idempotency & Deduplication
- **SHA256(job_type + params)** = deterministic job ID
- **Natural deduplication**: Same inputs always produce same job ID
- **Duplicate submissions**: Return existing job without creating new work


## 🚨 FUTURE Implementation Details for storage container content analysis

### Blob Inventory (solves 64KB limit)
- Gzipped inventories in `rmhazuregeoinventory` (93.5% compression)
- Three files: full, geo-only, summary

### Poison Queue Monitoring
- Timer: Every 5 min | Endpoint: `/api/monitor/poison`
- Auto-marks jobs as failed after 5 dequeues

### Large Path Handling
- Maxar paths >255 chars → MD5 hash IDs

## Future Database details

### PostGIS: v3.4, `geo` schema, geometry types
- We need the geometry field name to be a global config variable so when this application is deployed it can be set to "shape" if we are acomodating ArcGIS Enterprise Geodatabases

