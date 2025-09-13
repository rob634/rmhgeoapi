# Active Tasks

**Last Updated**: 13 SEP 2025  
**Author**: Robert and Geospatial Claude Legion

## ✅ RECENTLY RESOLVED (13 SEP 2025)

### Poison Queue Issue - FIXED ✅
**Resolution Date**: 13 SEP 2025 01:54 UTC  
**Problem**: Stage 2 job messages were going to poison queue even though jobs completed successfully

**Root Cause Identified**: 
- When Stage 2 job message was processed, it tried to update job status from PROCESSING → PROCESSING
- This invalid status transition caused a validation error and sent the message to poison queue

**Solution Implemented**:
- Modified `controller_base.py` line 1277-1282 to check if job is already PROCESSING before updating
- Only updates status for initial stage (Stage 1) messages

**Testing Results**:
- ✅ Tested with n=1, 2, 3, 4, 20 - all complete successfully
- ✅ No poison queue messages after fix deployment
- ✅ Idempotency confirmed working (duplicate jobs return same job_id)

### N=2 Completion Bug - FIXED ✅
**Resolution Date**: 13 SEP 2025 01:42 UTC  
**Problem**: Jobs with exactly n=2 would get stuck in PROCESSING state

**Root Cause**: 
- PostgreSQL function `complete_task_and_check_stage` had a race condition with exactly 2 tasks
- Both Stage 2 tasks would report "1 remaining" instead of counting down to 0

**Solution**: 
- Schema redeploy fixed the issue (cleared state inconsistency)
- N=2 now works correctly with proper countdown (1→0)

---

## ✅ RECENTLY RESOLVED (12 SEP 2025)

### Task Handler Execution Error - FIXED
**Resolution Time**: 12 SEP 2025 21:50 UTC
**Problem**: Tasks failing with `AttributeError: 'TaskRegistry' object has no attribute 'get_handler'`
**Solution**: 
- Renamed `service_factories.py` → `task_factory.py` (proper naming convention)
- Fixed controller_base.py to use `TaskHandlerFactory.get_handler()` instead of trying to use TaskRegistry directly
- Fixed TaskResult field names (`result_data` and `error_details`)
**Result**: All tasks now execute successfully through completion

### Stage 2 Task Creation Failure - FIXED
**Status**: RESOLVED  
**Resolution Date**: 12 SEP 2025
**Problems Fixed**:
1. TaskDefinition to TaskRecord conversion missing in function_app.py lines 1133-1146
2. Config attribute error: config.storage_account_url → config.queue_service_url (line 1167)
3. Job completion status not updating after all tasks complete (lines 1221-1237)

**Verification**: Successfully tested with n=2, 3, 5, 10, and 100 tasks
- Idempotency confirmed working (duplicate submissions return same job_id)
- All 200 tasks completed successfully for n=100 test

---

## 🟡 IN PROGRESS

### function_app.py Modularization (1251 lines → 506 lines) ✅
**Problem**: function_app.py contains orchestration logic that belongs in controllers
**Goal**: Move queue processing logic to BaseController, simplify function_app.py to just routing
**Started**: 12 SEP 2025
**COMPLETED**: 12 SEP 2025

**Implementation Steps**:
1. [x] **Add orchestration methods to BaseController**
   - [x] `process_job_queue_message(job_message: JobQueueMessage)`
   - [x] `process_task_queue_message(task_message: TaskQueueMessage)`
   - [x] `_handle_stage_completion(job_id, stage)` (private helper)
   - [x] Stage advancement logic integrated
   - [x] Job completion logic integrated

2. [x] **Move helper functions from function_app.py**
   - [x] Removed `_validate_and_parse_queue_message()` - logic in controller
   - [x] Removed `_load_job_record_safely()` - logic in controller
   - [x] Removed `_verify_task_creation_success()` - logic in controller
   - [x] Removed `_mark_job_failed_safely()` - logic in controller

3. [x] **Refactor queue triggers in function_app.py**
   - [x] Simplified `process_job_queue()` to 22 lines
   - [x] Simplified `process_task_queue()` to 22 lines
   - [x] Both now just parse message and delegate to controller

4. [ ] **Testing**
   - [ ] Test hello_world with n=10
   - [ ] Verify stage advancement still works
   - [ ] Confirm job completion still works

**Achieved Outcome**:
- function_app.py: 506 lines (60% reduction from 1251 lines)
- controller_base.py: Enhanced with queue orchestration methods (~360 new lines)
- Clean separation achieved: Controllers orchestrate, Services execute, Triggers route

### Service Handler Auto-Discovery
**Problem**: Service modules not auto-imported, handlers never registered  
**Partial Fix**: Added `import service_hello_world` to function_app.py  
**Remaining Work**:
- [ ] Implement proper auto-discovery mechanism in `util_import_validator.py`
- [ ] Call `auto_discover_handlers()` during function_app startup
- [ ] Test with new service modules

---

## 🟢 READY TO START (Prioritized)

### 1. Cross-Stage Lineage System
**Goal**: Tasks automatically access predecessor data by semantic ID  
**Implementation**:
- [ ] Add `is_lineage_task: bool` to TaskRecord schema
- [ ] Add `predecessor_data: Optional[Dict]` field
- [ ] Implement `TaskRecord.load_predecessor_data()` method
- [ ] Test with multi-stage workflow

### 2. Progress Calculation
**Goal**: Remove placeholder return values  
**Files**: `schema_base.py`
- [ ] Implement `calculate_stage_progress()` with real percentages
- [ ] Implement `calculate_overall_progress()` with actual math
- [ ] Implement `calculate_estimated_completion()` with time estimates

### 3. SQL Generator Enhancements
**Goal**: Support all Pydantic v2 field constraints  
**Files**: `schema_sql_generator.py`
- [ ] Test field metadata with MinLen, Gt, Lt constraints
- [ ] Add support for all annotated_types constraints
- [ ] Verify complex nested model handling

### 4. Repository Vault Integration
**Goal**: Enable Key Vault for production  
**Files**: `repository_vault.py`
- [ ] Complete RBAC setup for Key Vault
- [ ] Enable Key Vault integration
- [ ] Test credential management flow
- [ ] Remove "Currently disabled" status

---

## 📋 Next Sprint (After Critical Issue Fixed)

### Container Operations
- [ ] Implement blob inventory scanning
- [ ] Create container listing endpoints
- [ ] Test with large containers (>10K blobs)

### STAC Implementation
- [ ] Design STAC catalog structure for Bronze tier
- [ ] Implement STAC item generation from blobs
- [ ] Create STAC validation endpoint

### Process Raster Controller
- [ ] Create ProcessRasterController with 4-stage workflow
- [ ] Implement tile boundary calculation
- [ ] Add COG conversion logic
- [ ] Integrate with STAC catalog

---

## 🔧 Development Configuration Notes

### Current Settings
- **Retry Logic**: DISABLED (`maxDequeueCount: 1`)
- **Error Mode**: Fail-fast for development
- **Key Vault**: Disabled, using env vars

### When Moving to Production
- [ ] Enable retry logic (`maxDequeueCount: 3-5`)
- [ ] Implement exponential backoff
- [ ] Enable Key Vault integration
- [ ] Add circuit breaker pattern

---

## 📝 Documentation Tasks

- [ ] Update FILE_CATALOG.md after any file changes
- [ ] Move completed tasks to HISTORY.md
- [ ] Keep this file focused on ACTIVE work only

---

*For completed tasks, see HISTORY.md. For technical details, see ARCHITECTURE_REFERENCE.md.*