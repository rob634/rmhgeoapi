# Active Tasks

**Last Updated**: 12 SEP 2025  
**Author**: Robert and Geospatial Claude Legion

## ✅ RECENTLY RESOLVED (12 SEP 2025)

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