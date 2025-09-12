# Active Tasks

**Last Updated**: 11 SEP 2025  
**Author**: Robert and Geospatial Claude Legion

## 🔴 CRITICAL BLOCKING ISSUE

### Stage 2 Task Creation Failure
**Status**: ACTIVE - Blocking all workflow testing  
**Problem**: After stage 1 completes successfully, job advances to stage 2 but immediately fails  
**Error**: "No tasks successfully queued for stage 2"  
**Test Job ID**: `487cc76ef65adc3a1062765b5ebf087709dfb6ca02e8ee49351541033ca1b58b`

**Investigation Points**:
1. `controller_hello_world.py` → Check `create_stage_tasks()` method for stage 2
2. `function_app.py` lines 1103-1130 → Task creation logic after stage advancement
3. Verify if stage 2 tasks are being created but failing to queue
4. Check if stage 2 workflow definition exists in controller

**Testing Commands**:
```bash
# Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'

# Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Check tasks for job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

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