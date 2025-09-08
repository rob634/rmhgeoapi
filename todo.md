# TODO

**Last Updated**: 7 September 2025

## 🚀 Current Priority: Error Handling Implementation

### 🔴 CRITICAL - Immediate Next Steps

#### 0. Error Handling Implementation (NEW TOP PRIORITY)

**Critical Fix Required**: Tasks currently marked as "completed" even when they fail!
- **Line 726-733 in function_app.py**: Must pass error_details to PostgreSQL
- **Impact**: Lost error context, impossible debugging, incorrect job status
- **Fix Time**: < 1 hour
- **See**: ERROR_HANDLING_PLAN.md for complete implementation guide

#### 1. Stage Advancement Logic Implementation Plan

**Current State:** Stage advancement partially implemented but has issues:
- ✅ PostgreSQL functions called correctly
- ❌ Uses non-existent `StageExecutionContext` class
- ❌ Calls non-existent `controller.complete_job()` method
- ❌ Missing task queueing for next stage

**Implementation Phases:**

##### Phase 1: Fix Task Completion (Lines ~715-729)
- [x] ✅ Fixed PostgreSQL function signature to match Python interface (5 params)
- [x] ✅ Updated repository_postgresql.py to pass all required parameters
- [ ] 🔴 **CRITICAL**: Pass error_details parameter when task fails (see Error Handling section)
- [ ] Ensure `complete_task_and_check_stage()` handles errors properly

##### Phase 2: Fix Controller Methods (Lines ~761, ~848)
- [x] ✅ Fixed parameter naming: stage_results (plural) everywhere
- [x] ✅ Replaced `controller.complete_job()` with `aggregate_stage_results()`
- [x] ✅ Convert PostgreSQL JSONB results to TaskResult objects
- [ ] Use aggregated results for job completion

##### Phase 3: Fix Next Stage Task Creation (Lines ~836-849)
- [x] ✅ Removed StageExecutionContext references
- [x] ✅ Fixed `create_stage_tasks()` to use correct parameters
- [x] ✅ Fixed task queueing field mapping
- [ ] Verify stage advancement triggers correctly

##### Phase 4: Queue Next Stage Tasks
- [x] ✅ Create TaskQueueMessage for each new task
- [x] ✅ Save tasks to database via TaskRepository
- [x] ✅ Send messages to 'geospatial-tasks' queue
- [ ] Add proper error handling for queue operations

**Files to Modify:**
- `function_app.py` - Primary changes in task queue processor
- Optional: Create helper function `queue_tasks_for_stage()`

#### 2. Test HelloWorld End-to-End
- [ ] Submit job via HTTP endpoint
- [ ] Verify stage 1 tasks execute
- [ ] Confirm stage advancement triggers
- [ ] Verify stage 2 tasks execute
- [ ] Confirm job completion

---

## 🔴 Error Handling Implementation (NEW PRIORITY)

### Phase 1: Task Failure Handling (CRITICAL - Week 1)
- [ ] Fix task completion to pass error_details parameter (function_app.py lines 726-733)
- [ ] Update repository_postgresql.py to handle error_details explicitly
- [ ] Ensure PostgreSQL function receives error information
- [ ] Test task failure with proper error tracking

### Phase 2: Error Categorization & Retry Logic (Week 1)
- [ ] Create error_types.py with ErrorCategory enum
- [ ] Implement ErrorHandler.categorize_error() method
- [ ] Add retry mechanism with exponential backoff
- [ ] Configure MAX_RETRIES and RETRY_DELAY settings
- [ ] Test transient vs permanent error handling

### Phase 3: Stage-Level Error Aggregation (Week 2)
- [ ] Enhance aggregate_stage_results() with error details
- [ ] Implement error threshold checking (50% failure rate)
- [ ] Add should_continue_after_errors() logic
- [ ] Create error summary for stage results
- [ ] Test stage advancement with partial failures

### Phase 4: Job-Level Error Management (Week 2)
- [ ] Add JobStatus.COMPLETED_WITH_ERRORS status
- [ ] Implement partial success tracking
- [ ] Preserve partial results on failure
- [ ] Update job completion logic for error scenarios
- [ ] Test job completion with various error rates

### Phase 5: Circuit Breaker Pattern (Week 3)
- [ ] Create circuit_breaker.py with CircuitBreaker class
- [ ] Implement circuit states (CLOSED, OPEN, HALF_OPEN)
- [ ] Add failure threshold and recovery timeout
- [ ] Integrate with external service calls
- [ ] Test circuit breaker under load

### Error Handling Testing
- [ ] Unit tests for error_details parameter
- [ ] Integration tests for stage advancement with failures
- [ ] Load tests with 10% failure rate
- [ ] End-to-end test with mixed error types
- [ ] Circuit breaker state transition tests

**Documentation**: See ERROR_HANDLING_PLAN.md for detailed implementation guide

---

## 📋 Near-term Tasks

### Database Functions Integration
- [ ] Test all three PostgreSQL functions with real workflows
- [ ] Verify atomic operations prevent race conditions
- [ ] Add performance monitoring for high-volume scenarios

### HelloWorld Workflow Completion
- [ ] Fix stage advancement in HelloWorldController
- [ ] Implement proper task aggregation
- [ ] Test end-to-end job completion

### Process Raster Controller
- [ ] Create ProcessRasterController with 4-stage workflow
- [ ] Implement tile boundary calculation
- [ ] Add COG conversion logic
- [ ] Create STAC catalog integration

---

## 🔮 Future Enhancements

### Production Readiness
- [ ] Add task-level retry logic with exponential backoff
- [ ] Implement circuit breakers for external services
- [ ] Add job completion webhooks
- [ ] Create monitoring dashboard

### Performance Optimization
- [ ] Add connection pooling for >100 parallel tasks
- [ ] Implement queue batching for high-volume scenarios
- [ ] Add caching layer for frequently accessed data
- [ ] Optimize PostgreSQL function performance

### Additional Job Types
- [ ] stage_vector - PostGIS ingestion workflow
- [ ] extract_metadata - Raster metadata extraction
- [ ] validate_stac - STAC catalog validation
- [ ] export_geoparquet - Vector to GeoParquet conversion

---

## 📝 Documentation Tasks

- [ ] Update CLAUDE.md with latest architecture changes
- [ ] Create developer onboarding guide
- [ ] Document job type creation process
- [ ] Add workflow definition examples

---

## 🐛 Known Issues

### Current Bugs
- [ ] HelloWorld job not completing final stage
- [ ] Task heartbeat not updating properly
- [ ] Queue message TTL needs configuration

### Technical Debt
- [ ] Remove remaining test code from function_app.py
- [ ] Standardize error message format
- [ ] Add comprehensive logging to all components
- [ ] Create integration test suite

---

## ✅ Recently Completed (See HISTORY.md for details)

- ✅ Repository Class Cleanup: Eliminated duplicate names, clear PostgreSQL→Business logic hierarchy (7 September 2025)
- ✅ Orphaned Module Cleanup: Deleted unused util_enum_conversion.py (7 September 2025)
- ✅ BaseController Consolidation: Removed duplicate, single source in controller_base.py (7 September 2025)
- ✅ Stage Advancement Logic: Major fixes to function_app.py (7 September 2025)
- ✅ Completion Logic Refactoring: Moved from util_completion.py to BaseController (7 September 2025)
- ✅ Architecture Unification: Pydantic + ABC Merger (7 September 2025)
- ✅ PostgreSQL Repository Refactoring (6 September 2025)