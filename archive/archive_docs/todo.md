# TODO

**Last Updated**: 12 September 2025 01:45 UTC - Stage Advancement Working!

## 🎯 HANDOFF SUMMARY FOR NEXT CLAUDE

### Current State
✅ **Major Progress**: Core workflow mechanics are now functioning!
- Stage 1 tasks complete successfully
- Tasks persist to database with result_data
- Stage advancement from stage 1 to stage 2 works
- Jobs correctly update status and advance stages

### Critical Issue to Solve
🔴 **Stage 2 Task Creation Failure**
- **Problem**: After stage 1 completes, job advances to stage 2 but fails with "No tasks successfully queued for stage 2"
- **Test Job**: 487cc76ef65adc3a1062765b5ebf087709dfb6ca02e8ee49351541033ca1b58b
- **Where to look**: 
  - `controller_hello_world.py` - Check `create_stage_tasks()` for stage 2
  - `function_app.py` lines 1103-1130 - Task creation logic after stage advancement
  - Check if stage 2 tasks are being created but failing to queue

### What Was Fixed Today (See HISTORY.md for details)
1. ✅ DateTime import conflicts resolved
2. ✅ Pydantic object .get() usage fixed  
3. ✅ Transaction commit issue resolved
4. ✅ All 12 Pydantic models migrated to v2

### Testing Commands
```bash
# Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'

# Check job status (use job_id from above)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Check tasks for job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

---

## 🏗️ ARCHITECTURAL REFACTORING - Clear Separation of Data vs Behavior (11 Sept 2025)

### Overview
**Goal**: Establish clear naming conventions and separation between data structures and behavior contracts
**Principle**: `schema_*` = data structure, `interface_*` = behavior contracts, `*_impl` = concrete implementations
**Benefits**: Clear architecture, no mixed concerns, easier to understand and maintain

### Current Architecture Layers (PYRAMID)
```
┌─────────────────────────────────────────────────────┐
│                   HTTP TRIGGERS                      │ <- Entry Points
├─────────────────────────────────────────────────────┤
│                   CONTROLLERS                        │ <- Orchestration
├─────────────────────────────────────────────────────┤
│                    SERVICES                          │ <- Business Logic
├─────────────────────────────────────────────────────┤
│                  REPOSITORIES                        │ <- Data Access
├─────────────────────────────────────────────────────┤
│                    SCHEMAS                           │ <- Data Models
└─────────────────────────────────────────────────────┘
```

### File Naming Convention (Enforced)
- `trigger_*.py` → HTTP entry points (Azure Functions)
- `controller_*.py` → Job orchestration logic
- `service_*.py` → Task execution & business logic  
- `repository_*.py` → Concrete data access implementations
- `interface_*.py` → Abstract behavior contracts (ABCs)
- `schema_*.py` → Pure data structures (Pydantic models)
- `model_*.py` → DEPRECATED - being migrated to schema_*

### Key Architectural Principles
1. **Single Responsibility**: Each layer has one clear purpose
2. **Dependency Inversion**: Upper layers depend on interfaces, not implementations
3. **Data/Behavior Separation**: Models define structure, services define operations
4. **Factory Pattern**: All object creation through factories for consistency
5. **Registry Pattern**: Auto-discovery and registration of implementations

### Remaining Refactoring Tasks

#### Phase 5: Final Documentation Updates ✅ COMPLETED (11 Sept 2025)
- ✅ Updated ARCHITECTURE_FILE_INDEX.md with new structure
- ✅ Documented the interface/implementation separation pattern
- ✅ Added comprehensive interface/implementation architecture diagram
- ✅ Updated file counts to reflect interface_repository.py rename
- ✅ Documented benefits of separation (testability, flexibility, no circular deps)

## 🚨 CRITICAL - Current Blocking Issues

### 0. Stage 2 Task Creation Failure 🔴 ACTIVE (11 Sept 2025)

**Problem**: Stage 2 tasks fail to queue with "No tasks successfully queued for stage 2"
**Impact**: Jobs advance to stage 2 but fail immediately
**Test Job**: 487cc76ef65adc3a1062765b5ebf087709dfb6ca02e8ee49351541033ca1b58b
**Evidence**: Stage 1 completes, stage advancement works, but stage 2 task creation fails
**Current Status**: Stage advancement now works after fixing datetime and Pydantic issues
**Next Steps**: 
- [ ] Investigate why stage 2 tasks aren't being created by controller
- [ ] Check create_stage_tasks() implementation for stage 2
- [ ] Verify task queueing logic for stage 2


### 1. ~~Pydantic v1 Legacy Patterns~~ - ✅ RESOLVED (11 Sept 2025)
**Status**: All 12 models migrated to Pydantic v2 patterns (100% complete)
**Impact**: Full performance improvements achieved, modern serialization patterns
**Moved to**: HISTORY.md

### Service Handler Registration
**Problem**: Service modules not auto-imported, handlers never registered
**Partial Fix Applied**: Added `import service_hello_world` to function_app.py
**Remaining Work**:
- [ ] Implement proper auto-discovery mechanism
- [ ] Call `auto_discover_handlers()` during startup
- [ ] Add imports for future service modules automatically

---

## 🔧 Current Development Configuration

### Retry Logic: DISABLED for Development
**Configuration**: `host.json` → `maxDequeueCount: 1` (Try once, no retries)
**Rationale**: Development requires deterministic behavior - tasks either succeed or fail immediately

**Current Behavior**:
- Task messages dequeued **once only**
- Failures go straight to poison queue (`task-processing-poison`)
- No automatic retries by Azure Functions
- Failed tasks remain in FAILED or PROCESSING status

**Testing Plan for Task Execution**:
1. Deploy with `maxDequeueCount: 1` (current setting)
2. Submit hello_world job with 3 tasks
3. Monitor logs for immediate success/failure
4. Check poison queue for any failed messages
5. Verify tasks complete or fail without retries
6. Check stage advancement logic

**Expected Outcomes**:
- ✅ Tasks execute once and complete successfully
- ❌ OR tasks fail immediately and go to poison queue
- No "stuck in processing" states from retry loops
- Clear error messages in logs

### Future Production Configuration
When ready for production, implement proper retry logic:
- [ ] Change `maxDequeueCount` to 3-5 in host.json
- [ ] Implement retry_count increment on each attempt
- [ ] Add exponential backoff logic
- [ ] Differentiate transient vs permanent failures
- [ ] Add retry attempt logging
- [ ] Consider circuit breaker pattern for external services

---

## 🔄 PYDANTIC V2 FULL MIGRATION AUDIT (Critical Architecture Update)

### Context: Why This Matters
**Date Added**: 11 September 2025
**Current Status**: Using Pydantic 2.11.7 with transitional/hybrid code patterns
**Problem**: Mix of v1 and v2 patterns causing bugs (e.g., SQL generator field metadata issue)

Pydantic v2 (June 2023) was a complete rewrite with 5-50x performance improvements but massive breaking changes. Our codebase has partial v2 adoption but still uses many v1 patterns that work through compatibility layers. Full migration will:
- Fix current data type flow issues
- Improve performance significantly (Rust core)
- Enable better validation and serialization
- Future-proof the architecture

### Phase 1: Audit Current Implementation ✅ COMPLETED (11 Sept 2025)
**Status**: Audit complete - see PYDANTIC_REVIEW.md for full report
**Critical Finding**: 15 models using v1 Config classes, causing bugs and missing performance gains

#### Audit Results Summary:
- ✅ **Schema Models Audit** - Found 15 v1 Config classes needing migration
- ✅ **Validators** - Already using v2 @field_validator (11 instances)
- ✅ **SQL Generator** - Field metadata bug identified and fixed for MaxLen
- ✅ **Serialization** - Found 1 .dict() usage, needs .model_dump()
- ✅ **JSON Encoders** - 3 models using v1 json_encoders


#### 🟠 Priority 2: Pydantic v2 Migration - Remaining Work (11 Sept 2025)
**Status**: 9 of 12 models migrated to ConfigDict ✅

**Phases 1 & 2**: ✅ COMPLETED (Moved to HISTORY.md)
- Migrated 7 simple models in schema_base.py
- Migrated 2 queue models in schema_queue.py

**Phase 3: Models with json_encoders** ✅ COMPLETED (11 Sept 2025)
- ✅ JobRecord - migrated datetime & Decimal encoders to field_serializer
- ✅ TaskRecord - migrated datetime encoder to field_serializer
- ✅ JobRegistration - migrated datetime encoder to field_serializer

- ✅ **Fix Serialization Methods** - COMPLETED (11 Sept 2025)
  - ✅ Replaced `.dict()` with `.model_dump()` (schema_base.py:745)
  - ✅ Audited all .py files for .dict() usage - none remaining
  - ✅ Standardized on model_dump() throughout codebase

#### 🟡 Priority 3: MEDIUM - Optimization & Best Practices
- ✅ **Migrate json_encoders to Field Serializers** - COMPLETED (11 Sept 2025)
  - ✅ JobRecord - datetime and Decimal serializers migrated
  - ✅ TaskRecord - datetime serializer migrated
  - ✅ JobRegistration - datetime serializer migrated
  
- [ ] **SQL Generator Enhancements**
  - [ ] Test field metadata extraction with other constraint types (MinLen, Gt, Lt, etc.)
  - [ ] Add support for all annotated_types constraints
  - [ ] Verify complex nested model handling

#### 🟢 Priority 4: LOW - Future Enhancements
- [ ] **Performance Optimizations**
  - [ ] Enable strict mode for critical validation paths
  - [ ] Implement model compilation where beneficial
  - [ ] Profile before/after migration performance

- [ ] **Advanced v2 Features**
  - [ ] Consider @model_validator for complex cross-field validations
  - [ ] Implement @computed_field for derived values
  - [ ] Use Annotated style for complex field constraints

### Phase 2: Core Model Updates
**Goal**: Modernize all Pydantic models to v2 best practices

- [ ] **Model Configuration Migration**
  ```python
  # FROM (v1):
  class Config:
      use_enum_values = True
      validate_assignment = True
  
  # TO (v2):
  model_config = ConfigDict(
      use_enum_values=True,
      validate_assignment=True
  )
  ```

- [ ] **Field Definition Modernization**
  ```python
  # Consider migrating to Annotated style:
  from typing import Annotated
  from pydantic import StringConstraints
  
  # FROM:
  error_details: Optional[str] = Field(None, max_length=5000)
  
  # TO:
  error_details: Annotated[Optional[str], StringConstraints(max_length=5000)]
  ```

- [ ] **Validator Updates**
  ```python
  # FROM (v1):
  @validator('field_name')
  def validate_field(cls, v):
  
  # TO (v2):
  @field_validator('field_name')
  @classmethod
  def validate_field(cls, v):
  ```

### Phase 3: Performance Optimizations
**Goal**: Leverage v2's performance improvements

- [ ] **Model Compilation**
  - [ ] Enable model compilation where appropriate
  - [ ] Profile performance bottlenecks
  - [ ] Optimize hot paths with v2 features

- [ ] **Serialization Updates**
  - [ ] Use model_dump() with optimized parameters
  - [ ] Implement custom serializers for complex types
  - [ ] Review JSON schema generation

- [ ] **Validation Optimization**
  - [ ] Use strict mode where appropriate
  - [ ] Implement before/after validators efficiently
  - [ ] Optimize recursive model validation

### Phase 4: Advanced Features Implementation
**Goal**: Use v2's new capabilities

- [ ] **Strict Type Checking**
  - [ ] Enable strict=True for critical models
  - [ ] Implement proper type coercion policies
  - [ ] Add runtime type checking where needed

- [ ] **Computed Fields**
  - [ ] Migrate property methods to @computed_field
  - [ ] Implement efficient field dependencies
  - [ ] Add proper caching strategies

- [ ] **Model Serialization Control**
  - [ ] Implement field_serializer for custom formats
  - [ ] Use model_serializer for complex transformations
  - [ ] Add proper exclude/include patterns

### Phase 5: Testing & Validation
**Goal**: Ensure migration doesn't break functionality

- [ ] **Unit Tests**
  - [ ] Test all model validations
  - [ ] Verify serialization/deserialization
  - [ ] Check edge cases and error handling

- [ ] **Integration Tests**
  - [ ] Test SQL generation with all field types
  - [ ] Verify repository CRUD operations
  - [ ] Check queue message serialization

- [ ] **Performance Tests**
  - [ ] Benchmark v2 vs transitional code
  - [ ] Profile memory usage
  - [ ] Measure validation speed improvements

### Migration Priority Order
1. **IMMEDIATE**: Fix SQL generator field access (✅ DONE)
2. **HIGH**: Update core models (JobRecord, TaskRecord, TaskResult)
3. **MEDIUM**: Migrate validators and serializers
4. **LOW**: Optimize performance-critical paths
5. **FUTURE**: Implement advanced v2 features

### Expected Benefits
- **Bug Fixes**: Resolve current data type flow issues
- **Performance**: 5-50x faster validation and serialization
- **Maintainability**: Modern, consistent codebase
- **Features**: Access to computed fields, strict typing, better errors
- **Future-Proof**: Ready for Pydantic v3 when released

---

## 📋 Near-term Tasks

### Cross-Stage Lineage System Implementation:
**Goal**: Tasks automatically access predecessor data by semantic ID without manual handoff

**Architecture**:
- **Independent Tasks**: No predecessor dependency (validation, metadata extraction)  
- **Lineage Tasks**: Auto-load predecessor data from same semantic ID in previous stage

**Implementation Steps**:
- [ ] Add `is_lineage_task: bool` attribute to TaskRecord schema
- [ ] Add `predecessor_data: Optional[Dict]` field for loaded predecessor results
- [ ] Implement `TaskRecord.load_predecessor_data()` method:
  - Parse task_id: `"abc123-s2-tile_x5_y10"` → `"abc123-s1-tile_x5_y10"`
  - Query database for predecessor TaskRecord by computed ID
  - Load predecessor.result_data into self.predecessor_data
- [ ] Controllers specify lineage vs independent when creating TaskDefinitions
- [ ] Service layer uses predecessor_data for business logic (temp file paths, etc.)

**Example Flow**:
```
Stage 1: abc123-s1-tile_x5_y10 → Creates temp file, stores path in result_data
Stage 2: abc123-s2-tile_x5_y10 → Auto-loads Stage 1's file path from predecessor_data  
Stage 3: abc123-s3-tile_x5_y10 → Auto-loads Stage 2's processed data
```

#### Testing & Verification:
- [ ] Test lineage system: Stage 2 tasks auto-load Stage 1 predecessor data
- [ ] Verify complete Job→Stage→Task flow with cross-stage data flow

---

### Database Functions Integration
- [ ] Harden the SQL generation 
- [ ] Test PostgreSQL functions with complex data


### Container Operations (Precursor to STAC)
- [ ] Implement blob inventory scanning
- [ ] Create container listing endpoints

### STAC Implementation for Bronze
- [ ] Design STAC catalog structure
- [ ] Implement STAC item generation from blobs

### Process Raster Controller
- [ ] Create ProcessRasterController with 4-stage workflow
- [ ] Implement tile boundary calculation
- [ ] Add COG conversion logic
- [ ] Create STAC catalog integration

---

## 🔮 Future Enhancements

### Advanced Error Handling Implementation (Phases 2-5)

#### Phase 2: Error Categorization & Retry Logic
- [ ] Create error_types.py with ErrorCategory enum (transient, permanent, throttling)
- [ ] Implement ErrorHandler.categorize_error() method
- [ ] Add retry mechanism with exponential backoff
- [ ] Configure MAX_RETRIES and RETRY_DELAY settings
- [ ] Test transient vs permanent error handling

#### Phase 3: Stage-Level Error Aggregation
- [ ] Enhance aggregate_stage_results() with error details
- [ ] Implement error threshold checking (50% failure rate)
- [ ] Add should_continue_after_errors() logic
- [ ] Create error summary for stage results
- [ ] Test stage advancement with partial failures

#### Phase 4: Job-Level Error Management
- [ ] Add JobStatus.COMPLETED_WITH_ERRORS status
- [ ] Implement partial success tracking
- [ ] Preserve partial results on failure
- [ ] Update job completion logic for error scenarios
- [ ] Test job completion with various error rates

#### Phase 5: Circuit Breaker Pattern
- [ ] Create circuit_breaker.py with CircuitBreaker class
- [ ] Implement circuit states (CLOSED, OPEN, HALF_OPEN)
- [ ] Add failure threshold and recovery timeout
- [ ] Integrate with external service calls
- [ ] Test circuit breaker under load

### Production Readiness
- [ ] Add job completion webhooks
- [ ] Create monitoring dashboard
- [ ] Implement poison queue monitoring for failed messages
  - [ ] Create PoisonQueueMonitor service with actual Azure Storage Queue integration
  - [ ] Add automatic job/task failure marking from poison queues
  - [ ] Implement cleanup policies for old poison messages
  - [ ] Create poison queue dashboard and metrics

### Performance Optimization
- [ ] Add connection pooling for >100 parallel tasks
- [ ] Implement queue batching for high-volume scenarios
- [ ] Add caching layer for frequently accessed data
- [ ] Optimize PostgreSQL function performance

### Structured Error Reporting Enhancement
**Goal**: Enhance error field from simple string to structured Dict for richer error context
**Current**: `error: Optional[str]` - Simple string messages
**Future**: `error: Optional[Dict[str, Any]]` - Structured error objects

**Proposed Error Structure**:
```python
error: {
    "type": "ValidationError",  # Error classification
    "message": "Primary human-readable message",
    "code": "TASK_VALIDATION_001",  # Machine-readable error code
    "details": {  # Additional context
        "field": "input_file",
        "expected": "GeoTIFF format",
        "received": "JPEG format"
    },
    "stack_trace": "...",  # Optional, for debugging
    "timestamp": "2025-09-11T14:00:00Z",
    "retry_possible": true,  # Indicates if retry might succeed
    "suggested_action": "Convert file to GeoTIFF format"
}
```

**Implementation Steps**:
- [ ] Create ErrorDetail Pydantic model with structured fields
- [ ] Update TaskResult.error to accept Union[str, ErrorDetail] for backward compatibility
- [ ] Migrate service handlers to return structured errors
- [ ] Update error aggregation in stage/job completion
- [ ] Add error categorization and analysis capabilities

### Additional Job Types
- [ ] stage_vector - PostGIS ingestion workflow
- [ ] extract_metadata - Raster metadata extraction
- [ ] validate_stac - STAC catalog validation
- [ ] export_geoparquet - Vector to GeoParquet conversion

### Future Repository Implementations
- [ ] Implement ContainerRepository for Azure Blob Storage
- [ ] Implement CosmosRepository for Cosmos DB
- [ ] Implement RedisRepository for caching layer
- [ ] Evaluate need for additional repository patterns

### Repository Vault Integration
- [ ] Complete RBAC setup for repository_vault.py
- [ ] Enable Key Vault integration
- [ ] Remove "Currently disabled" status
- [ ] Test credential management flow

### Progress Calculation Implementation
- [ ] Implement calculate_stage_progress() in schema_base.py to return actual percentages
- [ ] Implement calculate_overall_progress() with real calculations
- [ ] Implement calculate_estimated_completion() with time estimates
- [ ] Remove all "return 0.0" placeholders in progress methods

---

## 📝 Documentation Tasks

- [ ] Update CLAUDE.md with latest architecture changes
- [ ] Create developer onboarding guide
- [ ] Document job type creation process
- [ ] Add workflow definition examples

---

## 🐛 Known Issues

- Environment variables required for local testing (STORAGE_ACCOUNT_NAME, etc.)
- Key Vault integration disabled - using environment variables only

---

## ✅ Recently Completed (See HISTORY.md for full details)

### 11 September 2025 - Transaction Commit Fix:
- ✅ Fixed critical bug preventing task completion persistence
- ✅ Implemented ALWAYS COMMIT pattern in _execute_query()
- ✅ Tasks now properly save result_data and complete
- ✅ Verified with test job - stage 1 tasks completed successfully

### 11 September 2025 - Pydantic v2 Migration Complete:
- ✅ Migrated all 12 models from Pydantic v1 to v2 patterns
- ✅ Replaced json_encoders with field_serializer for 3 models
- ✅ Full ConfigDict adoption across all models

### 11 September 2025 - Architectural Refactoring Phases 3-5:
- ✅ Created schema_queue.py separating queue models from database models
- ✅ Updated ARCHITECTURE_CORE.md with complete naming conventions
- ✅ Documented interface/implementation separation pattern
- ✅ Phase 5 documentation complete

### 10 September 2025 - Repository Consolidation:
- ✅ Created repository_factory.py - Central factory for all repository types
- ✅ Renamed repository_consolidated.py → repository_jobs_tasks.py for clarity
- ✅ Updated all imports across codebase (function_app, controllers, triggers, tests)
- ✅ Updated ARCHITECTURE_FILE_INDEX.md to reflect new structure
- ✅ Deployed and verified working in production

### 10 September 2025 - Process Job Queue Restructuring:
- ✅ Fixed job status update ordering - jobs only advance to PROCESSING after successful task creation
- ✅ Implemented phase-based exception handling with helper functions  
- ✅ Fixed metadata field NULL constraint violations in PostgreSQL
- ✅ Updated task_id format to use only URL-safe characters (hyphens instead of underscores)
- See HISTORY.md for complete details