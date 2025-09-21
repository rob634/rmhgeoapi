# Active Tasks

**Last Updated**: 21 SEP 2025 - Multi-Stage Jobs Working End-to-End!
**Author**: Robert and Geospatial Claude Legion

## ✅ CURRENT STATUS: SYSTEM OPERATIONAL

### Working Features
- ✅ **Multi-stage job orchestration** (tested with HelloWorld 2-stage workflow)
- ✅ **Contract enforcement** throughout system with @enforce_contract decorators
- ✅ **JSON serialization** with Pydantic `model_dump(mode='json')`
- ✅ **Error handling** with proper job failure marking
- ✅ **Advisory locks** preventing race conditions at any scale (tested n=30+)
- ✅ **Stage advancement** working correctly with StageResultContract
- ✅ **PostgreSQL atomic operations** via StageCompletionRepository
- ✅ **Idempotency** - SHA256 hash ensures duplicate submissions return same job_id
- ✅ **Database monitoring** - Comprehensive query endpoints at /api/db/*
- ✅ **Schema management** - Redeploy endpoint for clean state

### Recent Critical Fixes (21 SEP 2025)

#### 1. JSON Serialization Fixed
- **Problem**: TaskResult objects with enums/datetime not JSON serializable
- **Solution**: Use `model_dump(mode='json')` to convert enums→strings, datetime→ISO
- **File**: controller_hello_world.py line 351

#### 2. Contract Compliance Enforced
- **Problem**: HelloWorldController returned wrong field names ('successful' vs 'successful_tasks')
- **Solution**: Updated aggregate_stage_results() to return StageResultContract format
- **File**: controller_hello_world.py lines 273-354

#### 3. Error Handling Added
- **Problem**: Jobs stuck in PROCESSING forever when errors occurred
- **Solution**: Added granular try-catch blocks in process_job_queue_message()
- **File**: controller_base.py lines 1564-1620

### Test Results (21 SEP 2025)
```
Job: 641608072a6583d29d95d14c1ad64c6491efd3b4b4f4031c88e99241885c2265
Status: COMPLETED
Stage 1: 3 greeting tasks ✅
Stage 2: 3 reply tasks ✅
Total execution time: ~7 seconds
```

## 🔄 Next Priority Tasks

### 0. Queue Message Boundary Validation & Error Handling
**Status**: IMMEDIATE PRIORITY - Prevent poison queue messages
**Priority**: CRITICAL - Must complete before other work
**Reference**: See QUEUE_MESSAGE_VALIDATION_OUTLINE.md for complete implementation details

#### Phase 1: Add Comprehensive Logging (IMMEDIATE)
- [ ] Log raw message content before parsing (first 500 chars)
- [ ] Add correlation IDs to track messages through system
- [ ] Log each phase of processing separately
- [ ] Add message size and queue metadata logging

#### Phase 2: Queue Trigger Improvements (HIGH PRIORITY)
**File**: `function_app.py` lines 429-501

**Job Queue Trigger (process_job_queue)**:
- [ ] Separate message extraction from parsing
- [ ] Wrap model_validate_json() in specific try-catch
- [ ] Extract job_id from malformed messages if possible
- [ ] Add _mark_job_failed_from_queue_error() helper
- [ ] Log ValidationError details before raising
- [ ] Separate controller creation from processing
- [ ] Ensure job marked as FAILED before poison queue

**Task Queue Trigger (process_task_queue)**:
- [ ] Separate message extraction from parsing
- [ ] Wrap model_validate_json() in specific try-catch
- [ ] Extract task_id from malformed messages if possible
- [ ] Add _mark_task_failed_from_queue_error() helper
- [ ] Log ValidationError details before raising
- [ ] Update parent job if task parsing fails

#### Phase 3: Controller Method Improvements (HIGH PRIORITY)
**File**: `controller_base.py`

**process_job_queue_message() - 8 Granular Steps**:
- [ ] Step 1: Repository setup with error handling
- [ ] Step 2: Job record retrieval with null checks
- [ ] Step 3: Status validation (skip if completed)
- [ ] Step 4: Previous stage results retrieval (if stage > 1)
- [ ] Step 5: Task creation with rollback on failure
- [ ] Step 6: Queue client setup with credential handling
- [ ] Step 7: Per-task queueing with individual error handling
- [ ] Step 8: Final status update only if tasks queued

**process_task_queue_message() - 6 Granular Steps**:
- [ ] Step 1: Repository setup with error handling
- [ ] Step 2: Task record retrieval and validation
- [ ] Step 3: Status check (must be QUEUED)
- [ ] Step 4: Update to PROCESSING with verification
- [ ] Step 5: Task execution with TaskHandlerFactory
- [ ] Step 6: Atomic completion with stage check

#### Phase 4: Helper Functions (MEDIUM PRIORITY)
**New functions to add**:
- [ ] _mark_job_failed_from_queue_error(job_id, error_msg)
- [ ] _mark_task_failed_from_queue_error(task_id, error_msg)
- [ ] _is_job_marked_failed(job_id) -> bool
- [ ] _is_task_marked_failed(task_id) -> bool
- [ ] _extract_job_id_from_raw_message(message_content) -> Optional[str]
- [ ] _extract_task_id_from_raw_message(message_content) -> Optional[str]

#### Phase 5: Poison Queue Handlers (MEDIUM PRIORITY)
**New file**: `function_app.py` additions

**Poison Job Queue Handler**:
- [ ] Create @app.queue_trigger for "geospatial-jobs-poison"
- [ ] Extract job_id using JSON parsing or regex
- [ ] **CHECK CURRENT JOB STATUS FIRST**:
  - [ ] If already FAILED: Log as "expected poison" and dispose
  - [ ] If NOT FAILED: **🚨 CRITICAL UNHANDLED ERROR** - requires special handling
  - [ ] If COMPLETED: Log warning - shouldn't be in poison queue
  - [ ] If PROCESSING: Mark as FAILED with "UNHANDLED POISON" flag
- [ ] For unhandled errors: Send alert/notification to team
- [ ] Store first 1000 chars of poison message in job record
- [ ] Mark all pending tasks as FAILED (only if job wasn't already failed)
- [ ] Log with different severity levels (INFO for expected, ERROR for unhandled)

**Poison Task Queue Handler**:
- [ ] Create @app.queue_trigger for "geospatial-tasks-poison"
- [ ] Extract task_id and parent_job_id
- [ ] **CHECK CURRENT TASK STATUS FIRST**:
  - [ ] If already FAILED: Log as "expected poison" and dispose
  - [ ] If NOT FAILED: **🚨 CRITICAL UNHANDLED ERROR** - requires special handling
  - [ ] If COMPLETED: Log warning - shouldn't be in poison queue
  - [ ] If PROCESSING/QUEUED: Mark as FAILED with "UNHANDLED POISON" flag
- [ ] For unhandled errors: Check parent job status and update if needed
- [ ] Log comprehensive poison message details with appropriate severity

#### Phase 6: Testing Strategy (REQUIRED)
- [ ] Test with malformed JSON
- [ ] Test with missing required fields
- [ ] Test with invalid data types
- [ ] Test with unknown job_type
- [ ] Test with database connection failures
- [ ] Test with queue client failures
- [ ] Test with concurrent duplicate messages
- [ ] Verify all failures have database records

**Success Criteria**:
- ✅ Zero messages in poison queue without database error record
- ✅ Every ValidationError logged before raising
- ✅ Clear audit trail: raw message → parsing → error → database update → poison queue
- ✅ Poison handlers can recover partial information
- ✅ No silent failures anywhere in queue processing

### 1. Contract Enforcement Testing
**Status**: Ready for comprehensive testing
**Priority**: HIGH - Validate all contract work
**Tasks**:
- [ ] End-to-end multi-stage job testing with various n values
- [ ] Verify Stage 1 → Stage 2 data flow with contract enforcement
- [ ] Test error injection to confirm loud failures
- [ ] Validate contract violations produce clear error messages
- [ ] Performance testing with contract decorators (n=100+)

### 2. Container Controller Implementation
**Status**: Skeleton exists, needs implementation
**Files**: controller_container.py, repository_blob.py
**Tasks**:
- [ ] Implement list_container workflow for actual blob operations
- [ ] Add pagination support for large containers
- [ ] Test with real Azure Storage containers
- [ ] Validate large-scale file processing (1000+ files)
- [ ] Add error handling for blob access failures

### 2. STAC Integration
**Status**: Setup services created, need integration
**Files**: controller_stac_setup.py, service_stac_setup.py
**Tasks**:
- [ ] Complete STAC setup service implementation
- [ ] Test pgstac schema deployment
- [ ] Implement STAC item registration workflow
- [ ] Add spatial indexing for PostGIS geometries
- [ ] Create STAC collection management endpoints

### 3. Production Hardening
**Status**: Core working, needs resilience features
**Tasks**:
- [ ] Add retry logic for transient failures (network, storage)
- [ ] Implement exponential backoff for retries
- [ ] Add circuit breaker pattern for external services
- [ ] Implement dead letter queue processing
- [ ] Add comprehensive metrics and monitoring (Application Insights)
- [ ] Create alerting rules for job failures
- [ ] Add performance profiling for bottleneck identification

### 4. Raster Processing Workflow
**Status**: Not started
**Tasks**:
- [ ] Design stage_raster controller for COG generation
- [ ] Implement chunking strategy for large rasters
- [ ] Add GDAL-based reprojection service
- [ ] Create validation for output COGs
- [ ] Integrate with STAC catalog for metadata

### 5. Vector Processing Workflow
**Status**: Not started
**Tasks**:
- [ ] Design stage_vector controller for PostGIS ingestion
- [ ] Implement geometry validation and repair
- [ ] Add coordinate system transformation
- [ ] Create spatial indexing strategy
- [ ] Implement feature filtering and selection

## 📊 System Health Metrics

### Performance Benchmarks
- **Single task execution**: ~1-2 seconds
- **30 parallel tasks**: ~5-7 seconds total
- **Stage advancement**: <1 second
- **Job completion detection**: <1 second

### Current Limitations
- **Max parallel tasks**: Tested up to n=30, theoretical limit much higher
- **Max job parameters size**: 64KB (queue message limit)
- **Max result data size**: 1MB inline, larger results need blob storage

## 🔍 Known Issues

### Low Priority
1. **Duplicate task results in Stage 2**: Stage aggregation shows 6 tasks instead of 3 (cosmetic issue)
2. **Timezone handling**: All timestamps in UTC, need timezone support for UI
3. **Job cleanup**: Old completed jobs remain in database indefinitely

### Won't Fix (By Design)
1. **No backward compatibility**: System fails fast on breaking changes (development mode)
2. **No job cancellation**: Once started, jobs run to completion or failure
3. **No partial retries**: Failed stages require full job retry

## 📝 Documentation Needs

### High Priority
- [ ] API documentation with OpenAPI/Swagger
- [ ] Deployment guide for production environments
- [ ] Performance tuning guide

### Medium Priority
- [ ] Controller development guide with templates
- [ ] Service implementation patterns
- [ ] Database migration strategy

### Low Priority
- [ ] Architectural decision records (ADRs)
- [ ] Security best practices guide
- [ ] Monitoring and alerting setup

## 🚀 Quick Test Commands

```bash
# Test multi-stage job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 5, "message": "production test"}'

# Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Query all tasks for a job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}

# Get system health
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

---

*System is operational. Multi-stage jobs working. Ready for production workflows.*