# Active Tasks

**Last Updated**: 10 OCT 2025 - RASTER ETL PIPELINE PRODUCTION-READY! 🎉
**Author**: Robert and Geospatial Claude Legion

## 🎯 LATEST: RASTER ETL PIPELINE PRODUCTION-READY (10 OCT 2025)

### ✅ COMPLETE END-TO-END RASTER PROCESSING

**FULL PIPELINE OPERATIONAL:**

1. **Raster Validation** (`validate_raster`)
   - 9-step granular validation with LoggerFactory
   - Auto-detect raster type (RGB, DEM, multispectral, categorical)
   - CRS validation and bit-depth efficiency checking
   - Optimal COG settings recommendation

2. **COG Creation with Reprojection** (`create_cog`)
   - 7-step granular processing with error tracking
   - Single-pass reprojection + COG creation
   - JPEG compression @ 85 quality for RGB (91.9% size reduction!)
   - Automatic compression selection based on raster type
   - Upload to silver container (rmhazuregeosilver)

3. **Multi-Stage Workflow** (`process_raster`)
   - Stage 1: validate_raster → detect type and settings
   - Stage 2: create_cog → reproject, compress, upload
   - Full job completion with result aggregation
   - 15-second processing time for 208 MB → 16.9 MB COG

**GRANULAR LOGGING SUCCESS:**
- Identified and fixed 3 critical bugs via STEP-by-STEP logging
- Application Insights integration working
- Clear error codes per step (LOGGER_INIT_FAILED, COG_TRANSLATE_FAILED, etc.)
- Full tracebacks for debugging

**TEST RESULTS:**
```
Input:  test/dctest3_R1C2_regular.tif (208 MB uncompressed, EPSG:3857)
Output: test/dctest3_R1C2_regular_cog.tif (16.9 MB, EPSG:4326)
Compression: JPEG @ 85 quality (91.9% reduction)
Processing: 15.03 seconds
Status: ✅ COMPLETED
```

## 🎯 PREVIOUS: STAC METADATA EXTRACTION WITH MANAGED IDENTITY (6 OCT 2025)

### ✅ STAC WORKFLOW PRODUCTION-READY

**COMPLETE STAC IMPLEMENTATION OPERATIONAL:**

1. **STAC Collections Initialized** (`/api/stac/init`)
   - 4 production collections: dev, cogs, vectors, geoparquet
   - PgSTAC integration working
   - Collection management endpoints functional

2. **STAC Metadata Extraction** (`/api/stac/extract`)
   - User Delegation SAS with managed identity (NO storage keys!)
   - rio-stac integration for automatic metadata extraction
   - stac-pydantic validation for STAC spec compliance
   - Full raster metadata: bbox, geometry, projection, bands, statistics
   - Azure-specific properties (container, blob_path, tier)
   - Automatic insertion into PgSTAC database

3. **Critical Architecture Fixes**
   - ✅ `Asset` import from `stac_pydantic.shared` (not top-level)
   - ✅ User Delegation SAS using managed identity (no account keys)
   - ✅ rio-stac Item object conversion to dict before manipulation
   - ✅ Single authentication source: BlobRepository with managed identity
   - ✅ Missing `json` import in infrastructure/stac.py

**MANAGED IDENTITY AUTHENTICATION:**
- All blob access uses DefaultAzureCredential
- SAS URLs generated with User Delegation Key (not account keys)
- Authentication happens in ONE place: BlobRepository
- Blob URI + SAS token pattern: `blob_client.url + "?" + sas_token`

**SUCCESSFULLY TESTED:**
```bash
# Extract STAC metadata from COG
POST /api/stac/extract
{
  "container": "rmhazuregeobronze",
  "blob_name": "dctest3_R1C2_cog.tif",
  "collection_id": "dev",
  "insert": true
}

# Result: Complete STAC Item with:
# - Bounding box: Washington DC (-77.028, 38.908 to -77.013, 38.932)
# - 3 RGB bands with statistics and histograms
# - EPSG:4326 projection
# - Azure metadata (container, blob_path, tier)
# - User Delegation SAS URL (1 hour validity)
```

## 🎯 PREVIOUS: DETERMINISTIC TASK LINEAGE SYSTEM (4 OCT 2025)

### ✅ CONTAINER OPERATIONS PRODUCTION-READY

**TWO NEW JOB TYPES OPERATIONAL:**

1. **Container Summary** (`summarize_container`)
   - Single-stage aggregate statistics
   - 1,978 files analyzed in 1.34 seconds
   - File types, size distribution, date ranges

2. **Container List** (`list_container_contents`)
   - Two-stage fan-out pattern
   - 213 .tif files found and analyzed
   - Metadata stored in tasks.result_data

**DETERMINISTIC TASK LINEAGE:**
- Task IDs: `SHA256(job_id|stage|logical_unit)[:16]`
- Tasks can calculate predecessor IDs without database queries
- Foundation for complex multi-stage workflows
- Enables raster tiling, batch processing, DAG patterns

## 🏆 SYSTEM FULLY OPERATIONAL (Updated 4 OCT 2025)

**CORE CAPABILITIES:**
- Multi-stage job execution with fan-out patterns
- Deterministic task lineage across stages
- Automatic stage advancement
- Previous stage results passed to next stage
- "Last task turns out lights" pattern working
- Job completion with result aggregation
- Pydantic validation at all boundaries

### Current System Capabilities:

#### Working Features ✅
- HTTP job submission via `/api/jobs/submit/{job_type}`
- Service Bus queue-based orchestration
- Multi-stage job execution (sequential stages, parallel tasks)
- Atomic stage completion detection (PostgreSQL functions)
- Automatic stage advancement
- Job completion with result aggregation
- Pydantic validation at all boundaries
- State transition enforcement

#### Active Endpoints:
```bash
# Job Management
POST /api/jobs/submit/hello_world            - Submit hello world job
POST /api/jobs/submit/summarize_container    - Container statistics
POST /api/jobs/submit/list_container_contents - Container inventory
GET  /api/jobs/status/{job_id}               - Get job status
GET  /api/db/jobs                            - Query all jobs

# Task Management
GET /api/db/tasks/{job_id}         - Get tasks for job (with JSONB results)

# STAC Operations (NEW - 6 OCT 2025)
POST /api/stac/init                - Initialize STAC collections
POST /api/stac/extract             - Extract STAC metadata from raster
GET  /api/stac/setup               - Check PgSTAC installation status
POST /api/stac/collections/{tier}  - Create tier-specific collection

# System Health
GET /api/health                    - System health check

# Database Management
POST /api/db/schema/redeploy?confirm=yes - Redeploy schema
GET  /api/db/stats                       - Database statistics
GET  /api/db/debug/all                   - Dump all jobs and tasks
```

### Next Development Priorities:

#### Immediate (Ready to Implement):
1. **Complex Raster Workflows**
   - Multi-stage tiling with deterministic lineage
   - Parallel reproject/validate operations
   - COG conversion pipelines
   - STAC record updates

2. **Advanced Workflow Patterns**
   - Diamond patterns (fan-out then converge)
   - Dynamic stage creation based on previous results
   - Task-to-task direct communication
   - Cross-stage data dependencies

3. **Additional Container Operations** ✅ COMPLETED
   - ✅ Summarize container (aggregate statistics)
   - ✅ List container contents (per-blob metadata)
   - File type analysis and filtering
   - Size distribution analysis

#### Future Enhancements:

1. **Multi-Tier COG Architecture** 🌟 NEW
   - **Visualization Tier**: JPEG compression @ 85 quality (~17 MB, lossy, fast web maps)
   - **Analysis Tier**: DEFLATE lossless compression (~50 MB, zero data loss, scientific analysis)
   - **Archive Tier**: Minimal compression (~180 MB, long-term regulatory compliance)
   - **Client Pricing Tiers**:
     - Budget: Visualization only ($0.19/month for 1000 rasters)
     - Standard: Viz + Analysis ($0.79/month for 1000 rasters)
     - Enterprise: All three tiers ($1.20/month for 1000 rasters)
   - **Automatic Optimization**: Use existing raster type detection to select optimal compression
   - **Implementation**: Add `output_tier` parameter to `process_raster` job
   - **Business Value**: Clear upsell path from visualization → analysis → archive

   **Example Usage**:
   ```python
   # Simple flag approach
   POST /api/jobs/submit/process_raster
   {
     "blob_name": "input.tif",
     "output_tier": "visualization"  # or "analysis" or "both"
   }

   # Explicit outputs approach
   {
     "blob_name": "input.tif",
     "outputs": {
       "visualization": {"compression": "jpeg", "quality": 85},
       "analysis": {"compression": "deflate", "predictor": 2}
     }
   }
   ```

   **Storage Cost Comparison** (Azure Cool Tier @ $0.0115/GB/month):
   - Visualization: 16.9 MB → $0.0002/month per raster
   - Analysis: 52 MB → $0.0006/month per raster
   - Archive: 180 MB → $0.0021/month per raster

2. **Advanced Workflows**
   - Fan-out/fan-in patterns for massive parallelism
   - Dynamic task generation based on stage results
   - Cross-job dependencies

3. **Performance Optimization**
   - Batch task processing
   - Connection pooling optimization
   - Query performance tuning

4. **Operational Tools**
   - Job cancellation
   - Task replay
   - Historical analytics

---

## 🎉 EPOCH 4 MIGRATION MILESTONE! (1 OCT 2025)

### ✅ CRITICAL INFRASTRUCTURE COMPLETE

**ACHIEVED: Full migration from Epoch 3 `schema_base.py` to Epoch 4 `core/` architecture!**

#### Major Accomplishments Today:

1. **✅ Schema Migration Complete**
   - All `schema_base.py` imports migrated to `core/models/`
   - All `schema_queue.py` imports migrated to `core/schema/queue.py`
   - All `schema_updates.py` imports migrated to `core/schema/updates.py`
   - Infrastructure layer fully updated to use `core/` imports

2. **✅ Health Endpoint FULLY OPERATIONAL**
   - **Status**: All components healthy
   - **Imports**: 11/11 modules successful (100%)
   - **Queues**: Both geospatial-jobs and geospatial-tasks accessible
   - **Database**: PostgreSQL + PostGIS fully functional
   - **Config**: All environment variables present

3. **✅ Database Schema Redeploy WORKING**
   - **26 SQL statements executed** (0 failures!)
   - **4 PostgreSQL functions deployed** (complete_task_and_check_stage, advance_job_stage, check_job_completion, update_updated_at_column)
   - **2 tables created** (jobs, tasks)
   - **2 enums created** (job_status, task_status)
   - **10 indexes + 2 triggers created**
   - Full verification passed

4. **✅ Documentation Reorganization**
   - All root-level markdown files moved to organized `docs/` structure
   - `docs/epoch/` - Epoch planning & tracking (14 files)
   - `docs/architecture/` - CoreMachine & infrastructure design (6 files)
   - `docs/migrations/` - Migration tracking (7 files)
   - `.funcignore` updated to exclude all docs folders

5. **✅ Epoch 3 Controller Archive**
   - All legacy `controller_*.py` files moved to `archive_epoch3_controllers/`
   - Service Bus controllers preserved for reference
   - Clean separation between Epoch 3 and Epoch 4 patterns

#### Files Migrated to `core/` Imports:
- `infrastructure/` - All 7 repository files ✅
- `repositories/` - All 5 repository files ✅
- `services/service_stac_setup.py` ✅
- `controller_hello_world.py` ✅
- `controller_base.py` ✅
- `controller_container.py` ✅
- `controller_factories.py` ✅
- `triggers/health.py` ✅
- `function_app.py` ✅
- `core/machine.py` ✅

#### Next Steps:
1. **Test end-to-end job submission** with new architecture
2. **Complete Epoch 4 job registry** implementation
3. **Migrate remaining services** to new patterns
4. **Archive remaining Epoch 3 files**

---

## ✅ SERVICE BUS FULLY OPERATIONAL! (28 SEP 2025 - Evening)

### 🎉 COMPLETE FIX ACHIEVED - Service Bus Jobs Now Complete Successfully

#### Major Fixes Applied Today:

**PART 1: Task Execution Fixes (Earlier)**

1. **❌ FIXED: TaskHandlerFactory.get_handler() Wrong Parameters**
   - **Location**: `controller_service_bus_hello.py` line 691
   - **Issue**: Passing string `task_type` instead of full `TaskQueueMessage` object
   - **Fix**: Pass both `task_message` and `task_repo` as required
   - **Impact**: Caused AttributeError, tasks couldn't execute

2. **❌ FIXED: Missing Return Statement in Error Handler**
   - **Location**: `function_app.py` line 1245
   - **Issue**: After exception, code continued executing and logged success
   - **Fix**: Added `return` statement after error handling
   - **Impact**: Service Bus thought failed tasks succeeded, removed from queue

3. **❌ FIXED: AttributeError on parent_job_id**
   - **Location**: Multiple places in `controller_service_bus_hello.py`
   - **Issue**: Using `task_message.job_id` instead of `task_message.parent_job_id`
   - **Fix**: Updated 8 references to use correct attribute
   - **Impact**: Prevented task completion SQL function from executing

4. **✅ FIXED: Missing update_task_with_model Method**
   - **Location**: `function_app.py` line 1243
   - **Issue**: Called non-existent method on TaskRepository
   - **Fix**: Changed to use existing update_task() method
   - **Impact**: Fixed AttributeError preventing task updates

5. **✅ FIXED: Incorrect Import Path**
   - **Location**: `controller_service_bus_hello.py` line 691
   - **Issue**: `from repositories.factories import RepositoryFactory` - module doesn't exist
   - **Fix**: `from repositories import RepositoryFactory`
   - **Impact**: Fixed ModuleNotFoundError at runtime

**PART 2: Job Completion Fixes (Evening Session)**

6. **✅ FIXED: Missing Required Fields in JobExecutionContext**
   - **Location**: `controller_service_bus_hello.py` line 756
   - **Issue**: Missing current_stage and total_stages fields
   - **Fix**: Added both required fields from job_record
   - **Impact**: Fixed Pydantic validation error preventing job completion

7. **✅ FIXED: Complete Job Completion Flow Refactor**
   - **Added**: `TaskRepository.get_tasks_for_job()` method
   - **Fixed**: Fetch all TaskRecords and convert to TaskResult Pydantic objects
   - **Fixed**: StateManager.complete_job() signature to accept aggregated results
   - **Impact**: Jobs now complete successfully with proper type safety

### 🏆 ACHIEVEMENTS UNLOCKED:
- ✅ All 6 tasks complete successfully (3 in Stage 1, 3 in Stage 2)
- ✅ Stage advancement works correctly
- ✅ Job completion executes properly
- ✅ Full Pydantic type safety throughout pipeline
- ✅ Clean architecture with proper separation of concerns

## 🚀 READY FOR DEPLOYMENT

### Current Status:
- **Code**: All fixes implemented and ready
- **Architecture**: Clean separation using CoreController + StateManager + OrchestrationManager
- **Type Safety**: Full Pydantic model usage (TaskRecord, TaskResult, JobExecutionContext)
- **Compatibility**: Reuses schema_base.py models for consistency with BaseController

### Next Steps:
1. **Deploy** the function app with all fixes
2. **Test** Service Bus hello_world job
3. **Verify** job reaches COMPLETED status (not stuck in PROCESSING)
4. **Celebrate** full Service Bus functionality!

### 📋 Testing Plan - READY TO EXECUTE

#### Phase 1: Deployment & Basic Verification
```bash
# 1. Deploy the fixes
func azure functionapp publish rmhgeoapibeta --python --build remote

# 2. Wait for function app to restart (30-60 seconds)
sleep 60

# 3. Redeploy schema (always do this after deployment)
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"
```

#### Phase 2: Service Bus Hello World Test
```bash
# 1. Submit Service Bus hello_world job
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/sb_hello_world" \
  -H "Content-Type: application/json" \
  -d '{"message": "test after fixes", "n": 3}'

# 2. Save the job_id from response, then wait 10 seconds
JOB_ID=<job_id_from_response>
sleep 10

# 3. Check job status - should show COMPLETED, not PROCESSING
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/${JOB_ID}"

# 4. Check tasks - all should be COMPLETED
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/${JOB_ID}"

# 5. Verify stage 2 was created (if applicable)
# Look for stage: 2 in tasks
```

#### Phase 3: Verify Error Handling
```bash
# 1. Check for any failed tasks
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks?status=failed&limit=10"

# 2. If any failed, check error_details field for proper error messages
```

#### Phase 4: Compare with Storage Queue
```bash
# 1. Submit regular hello_world for comparison
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world" \
  -H "Content-Type: application/json" \
  -d '{"message": "storage queue test", "n": 3}'

# 2. Both should complete successfully
```

### 🎯 Success Criteria

✅ **Service Bus Tasks Complete**:
- Tasks move from PROCESSING → COMPLETED
- No tasks stuck in PROCESSING after 30 seconds
- Stage 2 tasks created (for multi-stage workflows)

✅ **Error Handling Works**:
- Failed tasks show FAILED status
- error_details field contains meaningful error message
- No "success" logs for failed tasks

✅ **Stage Advancement Works**:
- Last task in stage 1 triggers stage 2 creation
- Job status updates appropriately
- "Stage complete" messages in logs

### 📊 Key Metrics to Monitor

1. **Task Status Distribution**:
   - Query: `SELECT status, COUNT(*) FROM app.tasks GROUP BY status`
   - Expected: Mostly COMPLETED, some FAILED, NO long-running PROCESSING

2. **Job Completion Rate**:
   - Query: `SELECT job_type, status, COUNT(*) FROM app.jobs GROUP BY job_type, status`
   - Expected: Service Bus jobs completing at same rate as Storage Queue

3. **Error Messages**:
   - Query: `SELECT task_id, error_details FROM app.tasks WHERE status = 'failed' AND created_at > NOW() - INTERVAL '1 hour'`
   - Expected: Clear, actionable error messages

### 🔍 Debugging Commands

```bash
# Get all tasks for a job with details
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all?limit=50"

# Check Service Bus poison queue (if tasks are failing repeatedly)
# Use Azure Portal → Service Bus → Queues → geospatial-tasks/$deadletterqueue

# Query Application Insights logs (requires Azure login)
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" -G \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(10m) | where message contains 'ERROR' | project timestamp, message | limit 20"
```

### 🚀 Next Steps After Testing

#### If All Tests Pass:
1. **Deploy Service Bus Container Listing**
   - Test `sb_list_container` with real Azure Storage containers
   - Verify batch processing (100 items per batch)
   - Monitor performance vs Storage Queue version

2. **Migrate More Workflows to Service Bus**
   - STAC metadata extraction
   - GeoTIFF processing pipelines
   - Raster tiling operations

3. **Performance Benchmarking**
   - Compare Service Bus vs Storage Queue for same workflows
   - Measure throughput, latency, and cost
   - Document optimal use cases for each

#### If Tests Fail:
1. **Check Deployment Status**
   - Verify function app has restarted
   - Check if old code is cached (may need to restart function app in Azure Portal)

2. **Review Logs**
   - Check Application Insights for specific error messages
   - Look for "Controller processing failed" messages
   - Check if tasks are reaching poison queue

3. **Rollback Plan**
   - Keep BaseController working as fallback
   - Can switch back to Storage Queue pipeline immediately
   - No breaking changes to existing code

### 📝 Files Modified in This Fix

1. **function_app.py**
   - Line 1246: Added return statement in error handler
   - Lines 1218-1221: Added controller result checking

2. **controller_service_bus_hello.py**
   - Line 694: Fixed TaskHandlerFactory.get_handler call
   - Lines 710, 714, 719, 723, 734, 752, 754, 761, 765: Fixed parent_job_id references

3. **service_bus_list_processor.py**
   - Line 596: Fixed TaskHandlerFactory.get_handler call

### 📚 Documentation Created

1. **active_tracing.md** - Complete execution trace for debugging
2. **postgres_comparison.md** - Comparison of PostgreSQL usage patterns
3. **stuck_task_analysis.md** - Root cause analysis of processing issues

### 🏗️ MAJOR ARCHITECTURE REFACTORING (26 SEP 2025 Afternoon)

**ACHIEVED: Clean Service Bus Architecture WITHOUT God Class Inheritance!**

#### What We Built:
1. **CoreController** (`controller_core.py`)
   - Minimal abstract base with ONLY inherited methods
   - 5 abstract methods + ID generation + validation
   - ~430 lines (vs BaseController's 2,290!)

2. **StateManager** (`state_manager.py`)
   - All database operations with advisory locks
   - Critical "last task turns out lights" pattern
   - Shared by both Queue Storage and Service Bus
   - ~540 lines of focused state management

3. **OrchestrationManager** (`orchestration_manager.py`)
   - Simplified dynamic task creation
   - Optimized for Service Bus batching
   - No workflow definition dependencies
   - ~400 lines for orchestration logic

4. **ServiceBusListProcessor** (`service_bus_list_processor.py`)
   - Reusable base for "list-then-process" workflows
   - Template method pattern for common operations
   - Examples: Container listing, STAC ingestion, GeoJSON batching
   - ~500 lines of reusable patterns

#### Architecture Strategy:
- **Composition Over Inheritance**: Service Bus uses focused components
- **Parallel Build**: BaseController unchanged, new architecture runs alongside
- **Zero Breaking Changes**: Existing Queue Storage code unaffected
- **Clean Separation**: Each component has single responsibility

#### Total Lines:
- **New Architecture**: ~1,870 lines across 4 focused components
- **Old BaseController**: 2,290 lines of God Class
- **Result**: Cleaner, more testable, more maintainable

### Previous Victories (26 SEP 2025 Morning)
- ✅ **SERVICE BUS PARALLEL PIPELINE FULLY OPERATIONAL!**
  - Service Bus repository with batch support
  - Service Bus-optimized controller with 100-item batching
  - HelloWorld job processed with 20 tasks successfully
  - Both pipelines (Queue Storage + Service Bus) running in parallel!

### Working Features
- ✅ **DUAL PIPELINE ARCHITECTURE** - Queue Storage AND Service Bus in parallel!
- ✅ **Clean Component Architecture** - No God Class inheritance for Service Bus!
- ✅ **Multi-stage job orchestration** (tested with HelloWorld 2-stage workflow)
- ✅ **Contract enforcement** throughout system with @enforce_contract decorators
- ✅ **Advisory locks** preventing race conditions at any scale
- ✅ **Idempotency** - SHA256 hash ensures duplicate submissions return same job_id
- ✅ **Database monitoring** - Comprehensive query endpoints at /api/db/*
- ✅ **Batch coordination** - Aligned batches between PostgreSQL and Service Bus

## 🚨 CRITICAL: Pydantic Contract Enforcement for CoreController Architecture

**Date Discovered**: 27 SEP 2025
**Issue**: Service Bus pipeline exposes type safety hole that BaseController accidentally protected against
**Root Cause**: Direct repository calls bypass protective abstractions, revealing Dict[str, Any] type unsafety

### The Problem Discovered:
```python
# BaseController (God Class) accidentally protected against this:
controller.process_task_queue_message(...)  # Safe abstraction

# Service Bus directly exposes the bug:
task_repo.update_task_status_with_validation(...)  # Type mismatch crash!
# Calls .value on already-string status → AttributeError
```

**Key Insight**: "It works unintentionally" is NOT good design! BaseController's 2,290 lines accidentally hid type safety issues that proper architecture reveals.

### Implementation Plan:

#### Phase 1: Create Pydantic Update Models (NEW FILE: schema_updates.py)
```python
class TaskUpdateModel(BaseModel):
    """Strongly typed task update contract"""
    status: Optional[TaskStatus] = None  # Enum, not string!
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    heartbeat: Optional[datetime] = None
    retry_count: Optional[int] = None

    # Pydantic handles enum→string conversion automatically
    class Config:
        use_enum_values = True  # Serialize enums to values

class JobUpdateModel(BaseModel):
    """Strongly typed job update contract"""
    status: Optional[JobStatus] = None
    stage: Optional[int] = None
    stage_results: Optional[Dict[str, Any]] = None
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
```

#### Phase 2: Update Repository Interfaces (repositories/interface_repository.py)
```python
# BEFORE (Type Safety Hole):
def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:

# AFTER (Contract Enforced):
def update_task(self, task_id: str, updates: TaskUpdateModel) -> bool:
```

#### Phase 3: Fix PostgreSQL Implementation (repositories/postgresql.py)
- **Line 961**: Change signature to accept `TaskUpdateModel`
- **Lines 986-993**: REMOVE hasattr/isinstance fallback logic
- Use `updates.dict(exclude_unset=True)` to get only set fields
- Pydantic automatically converts enums to strings

#### Phase 4: Update StateManager (state_manager.py)
- All update methods must create Pydantic models
- Add `@enforce_contract` decorators
- Example:
```python
def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
    update = TaskUpdateModel(status=status)
    return self.task_repo.update_task(task_id, update)
```

#### Phase 5: Fix Direct Callers
1. **function_app.py Line 1183** (Service Bus pipeline):
```python
# BEFORE:
task_repo.update_task_status_with_validation(task_message.task_id, TaskStatus.PROCESSING)

# AFTER:
update = TaskUpdateModel(status=TaskStatus.PROCESSING)
task_repo.update_task(task_message.task_id, update)
```

2. **function_app.py Lines 1399-1402** (Error handler):
```python
# BEFORE:
task_repo.update_task(task_id, {'status': TaskStatus.FAILED, ...})

# AFTER:
update = TaskUpdateModel(
    status=TaskStatus.FAILED,
    error_details=f"Queue processing error: {error_msg}"
)
task_repo.update_task(task_id, update)
```

#### Phase 6: Update Jobs/Tasks Repository (repositories/jobs_tasks.py)
- **Line 404**: Remove manual `.value` conversion
- Create `TaskUpdateModel` instead of dict
- Let Pydantic handle all conversions

### Files to Modify:
1. **NEW**: `schema_updates.py` - Create Pydantic update models
2. `repositories/interface_repository.py` - Update method signatures
3. `repositories/postgresql.py` - Accept Pydantic models (line 961+)
4. `repositories/jobs_tasks.py` - Use Pydantic models (line 404)
5. `function_app.py` - Fix direct calls (lines 1183, 1399-1402)
6. `state_manager.py` - Use Pydantic models for all updates

### Benefits:
- **Type Safety**: Compile-time checking, IDE autocomplete
- **No Ambiguity**: Clear contract about expected types
- **Automatic Validation**: Pydantic validates all fields
- **Enum Handling**: Automatic enum↔string conversion
- **Reveals Hidden Bugs**: Like this one that was masked by God Class

### Success Criteria:
- [ ] All repository update methods use Pydantic models
- [ ] No Dict[str, Any] in repository interfaces
- [ ] Service Bus pipeline works without type errors
- [ ] All tests pass with strong typing
- [ ] @enforce_contract on all update methods

## 🔄 Next Priority Tasks

### 1. Test Clean Architecture with Service Bus (BLOCKED - Fix Contract First!)

**STATUS**: Ready for testing
**OBJECTIVE**: Validate new component architecture

#### Testing Steps:
1. **Update ServiceBusHelloWorldController**
   ```python
   from controller_core import CoreController
   from state_manager import StateManager

   class ServiceBusHelloWorldController(CoreController):
       # Inherit from CoreController, not BaseController!
   ```

2. **Test with Container Operations**
   ```python
   from service_bus_list_processor import ServiceBusListProcessor

   class ServiceBusContainerController(ServiceBusListProcessor):
       # Automatic list-then-process pattern!
   ```

3. **Verify Advisory Locks**
   - Test with n=100 tasks
   - Confirm no race conditions
   - Validate StateManager operations

### 2. Implement Production Service Bus Controllers

**STATUS**: Architecture ready, implementation needed

#### Controllers to Build:
1. **ServiceBusContainerController**
   - Extends ServiceBusListProcessor
   - List container → process files in batches
   - Test with 10,000+ files

2. **ServiceBusSTACController**
   - Extends ServiceBusListProcessor
   - List rasters → create STAC items in batches
   - Integrate with PgSTAC

3. **ServiceBusGeoJSONController**
   - Extends ServiceBusListProcessor
   - Read GeoJSON → upload to PostGIS in batches
   - Handle large feature collections

### 3. Refactor Queue Storage Controllers (FUTURE)

**STATUS**: After Service Bus proven
**OBJECTIVE**: Apply clean architecture to Queue Storage

#### Migration Plan:
1. Create `QueueStorageProcessor` component
2. Update existing controllers to use components
3. Gradually remove methods from BaseController
4. Eventually deprecate BaseController God Class

### 4. Performance Testing & Metrics

**STATUS**: Ready after controllers implemented

#### Test Scenarios:
- HelloWorld: n=1000 (2,000 tasks total)
- Container: 10,000 files
- GeoJSON: 100,000 features
- Compare Queue Storage vs Service Bus

#### Metrics to Collect:
- Throughput (tasks/second)
- Latency (job completion time)
- Resource usage (CPU, memory)
- Database connection pool

## 📝 Documentation Updates Needed

### High Priority:
- [x] Update TODO_ACTIVE.md with architecture changes
- [ ] Update HISTORY.md with refactoring details
- [ ] Update FILE_CATALOG.md with new files
- [ ] Create ARCHITECTURE_COMPONENTS.md

### Medium Priority:
- [ ] Update deployment guide for Service Bus
- [ ] Document component interfaces
- [ ] Create migration guide from BaseController

### Low Priority:
- [ ] Update sequence diagrams
- [ ] Add component interaction diagrams
- [ ] Performance comparison documentation

## 🚀 Quick Test Commands

```bash
# Test Service Bus with new architecture
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/sb_hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 100, "message": "clean architecture test"}'

# Test container listing (when implemented)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/sb_list_container \
  -H "Content-Type: application/json" \
  -d '{"container": "bronze", "extension_filter": ".tif"}'
```

## 🎯 Success Criteria

### Architecture Goals:
- ✅ Service Bus without God Class inheritance
- ✅ Composition over inheritance
- ✅ Single responsibility components
- ✅ Parallel implementation (no breaking changes)

### Performance Goals:
- [ ] 250x improvement for 1,000+ task jobs
- [ ] No timeouts at 10,000+ tasks
- [ ] Linear scaling with batch size
- [ ] Sub-second task creation for 100-item batches

### Code Quality Goals:
- ✅ No component over 600 lines
- ✅ Each component single responsibility
- ✅ Testable in isolation
- ✅ Clear interfaces between components

---

*System architecture refactored. Clean Service Bus implementation ready. No God Classes!*