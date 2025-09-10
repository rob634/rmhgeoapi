# TODO

**Last Updated**: 10 September 2025

## 📋 Priority Implementation Tasks

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

### 10 September 2025 - Process Job Queue Restructuring:
- ✅ Fixed job status update ordering - jobs only advance to PROCESSING after successful task creation
- ✅ Implemented phase-based exception handling with helper functions  
- ✅ Fixed metadata field NULL constraint violations in PostgreSQL
- ✅ Updated task_id format to use only URL-safe characters (hyphens instead of underscores)
- See HISTORY.md for complete details

### 10 September 2025 - Earlier fixes:
- ✅ Fixed Azure Functions logger propagation (line 414 in util_logger.py)
- ✅ Fixed 10 incorrect repository method calls across codebase
- ✅ Fixed syntax error in schema_sql_generator.py (line 77 indentation)

### 9 December 2025 - Code Quality:
- ✅ util_logger refactoring, JSON logging, circular imports fixed
- ✅ service_hello_world.py cleanup (225 lines removed)
- See HISTORY.md for complete details