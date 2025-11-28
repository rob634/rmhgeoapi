# Phase 2 Deployment & Testing Guide

**Date**: 15 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Phase**: ABC Migration (Phase 2 Complete)

---

## Pre-Deployment Checklist

### ✅ Completed Before Deployment

1. **Core Implementation**
   - [x] Created `jobs/base.py` with JobBase ABC
   - [x] Added JobBase export to `jobs/__init__.py`
   - [x] Verified decorator order (@staticmethod before @abstractmethod)

2. **Job Migrations** (10/10 Complete)
   - [x] HelloWorldJob
   - [x] CreateH3BaseJob
   - [x] GenerateH3Level4Job
   - [x] IngestVectorJob
   - [x] ValidateRasterJob
   - [x] ContainerSummaryWorkflow
   - [x] ListContainerContentsWorkflow
   - [x] StacCatalogContainerWorkflow
   - [x] StacCatalogVectorsWorkflow
   - [x] ProcessRasterWorkflow

3. **Cleanup**
   - [x] Removed `jobs/workflow.py` (unused ABC)
   - [x] Removed `jobs/registry.py` (unused decorator pattern)

4. **Documentation**
   - [x] Updated `docs_claude/ARCHITECTURE_REFERENCE.md` with JobBase ABC
   - [x] Updated `docs_claude/CLAUDE_CONTEXT.md` removed file references
   - [x] Created `PHASE_2_WHAT_ACTUALLY_CHANGED.md` (clarification doc)
   - [x] Created `PHASE_2_COMPLETE_SUMMARY.md`

5. **Local Testing**
   - [x] All 10 jobs verified with JobBase inheritance
   - [x] Python imports validated (no import errors)
   - [x] Integration test passed (HelloWorldJob end-to-end)

---

## Deployment Steps

### 1. Deploy to Azure Functions

```bash
# Deploy to rmhgeoapibeta function app
func azure functionapp publish rmhgeoapibeta --python --build remote
```

**Expected Duration**: 3-5 minutes
**What happens**: Azure builds remote Python environment, installs dependencies, deploys code

### 2. Verify Health Endpoint

```bash
# Check function app is responding
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

**Expected Response**:
```json
{
  "status": "healthy",
  "timestamp": "2025-10-15T...",
  "database": "connected",
  "service_bus": "connected"
}
```

**If health check fails**: Wait 60 seconds for cold start, retry

---

## Testing All 10 Jobs

### Test Strategy

**Phase 2 changes were minimal** (2 lines per job), but we should verify:
1. Job submission still works (ABC doesn't block instantiation)
2. Job execution completes successfully
3. No import errors from ABC decorator order

### Quick Test: HelloWorld (Simplest Job)

```bash
# Submit HelloWorld job (2-stage, minimal parameters)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "Phase 2 ABC Test", "n": 3}'
```

**Expected Response**:
```json
{
  "job_id": "abc123...",
  "status": "queued",
  "message": "Job submitted successfully"
}
```

**Check Job Status**:
```bash
# Replace {JOB_ID} with job_id from response
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**Expected Completion**: 10-30 seconds for n=3

**Success Criteria**:
- Job status progresses: QUEUED → PROCESSING → COMPLETED
- Both stages complete successfully
- No errors in Application Insights

### Comprehensive Test: All 10 Jobs

**Test each job type with minimal parameters:**

#### 1. HelloWorld (Already tested above)
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 2}'
```

#### 2. Create H3 Base Grid
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/create_h3_base \
  -H "Content-Type: application/json" \
  -d '{"resolution": 0}'
```
**Note**: Resolution 0 = 122 cells (fastest test)

#### 3. Generate H3 Level 4
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/generate_h3_level4 \
  -H "Content-Type: application/json" \
  -d '{"base_resolution": 0, "target_resolution": 1, "geojson_filter": "land.json"}'
```

#### 4. Ingest Vector
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "blob_name": "test.geojson", "table_name": "test_vectors"}'
```

#### 5. Validate Raster
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "blob_name": "test.tif"}'
```

#### 6. Summarize Container
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/summarize_container \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze"}'
```

#### 7. List Container Contents
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/list_container_contents \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "prefix": ""}'
```

#### 8. STAC Catalog Container
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/stac_catalog_container \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze"}'
```

#### 9. STAC Catalog Vectors
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/stac_catalog_vectors \
  -H "Content-Type: application/json" \
  -d '{"table_name": "test_vectors"}'
```

#### 10. Process Raster
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "blob_name": "test.tif", "target_epsg": 4326}'
```

---

## Monitoring & Debugging

### Application Insights Queries

**Check for ABC-related errors:**
```bash
# Create query script
cat > /tmp/query_abc_errors.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(1h) | where message contains 'abstract' or message contains 'JobBase' or message contains 'TypeError' | order by timestamp desc | take 20" \
  -G
EOF

chmod +x /tmp/query_abc_errors.sh && /tmp/query_abc_errors.sh | python3 -m json.tool
```

**Check recent job submissions:**
```bash
# Recent job submissions
cat > /tmp/query_jobs.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=requests | where timestamp >= ago(30m) | where url contains '/api/jobs/submit' | order by timestamp desc | take 10" \
  -G
EOF

chmod +x /tmp/query_jobs.sh && /tmp/query_jobs.sh | python3 -m json.tool
```

### Database Debugging

**Check job status via API:**
```bash
# Get all jobs from last hour
curl 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?hours=1&limit=20'
```

**Check failed jobs:**
```bash
# Get failed jobs
curl 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?status=failed&limit=10'
```

---

## Expected Issues & Solutions

### Issue 1: Import Error - "Can't import JobBase"

**Symptom**: Function app fails to start, health endpoint returns 500

**Cause**: `jobs/__init__.py` not exporting JobBase

**Solution**:
```python
# Verify jobs/__init__.py has:
from .base import JobBase

__all__ = [
    'ALL_JOBS',
    'get_job_class',
    'validate_job_registry',
    'JobBase',  # Must be exported
]
```

### Issue 2: TypeError - "Can't instantiate abstract class"

**Symptom**: Job submission fails with TypeError about abstract methods

**Cause**: A job is missing one of the 5 required methods

**Solution**: Check which method is missing, verify all jobs have:
1. `validate_job_parameters`
2. `generate_job_id`
3. `create_job_record`
4. `queue_job`
5. `create_tasks_for_stage`

### Issue 3: Decorator Order Error

**Symptom**: `AttributeError: attribute '__isabstractmethod__' of 'staticmethod' objects is not writable`

**Cause**: Wrong decorator order in jobs/base.py

**Solution**: Ensure `@staticmethod` comes BEFORE `@abstractmethod`:
```python
# Correct:
@staticmethod
@abstractmethod
def method(): pass

# Wrong:
@abstractmethod
@staticmethod
def method(): pass
```

---

## Success Criteria

### Phase 2 is successful if:

1. **All 10 jobs submit successfully** via API
2. **Jobs execute without ABC-related errors** (no TypeError, no import failures)
3. **At least 3 jobs complete end-to-end** (HelloWorld + 2 others)
4. **No Application Insights errors** mentioning "abstract", "JobBase", or decorator issues
5. **Health endpoint returns 200 OK**

### Partial Success:

If **most jobs work but 1-2 fail**, check:
- Job-specific handler issues (unrelated to ABC)
- Missing blob storage files (container/vector jobs)
- Database table issues (STAC catalog jobs)

**ABC migration itself is successful if jobs import and submit correctly**, even if execution fails due to missing resources.

---

## Rollback Plan

### If Deployment Fails Completely

**Symptoms**:
- Health endpoint returns 500
- All job submissions fail with import errors
- Application Insights shows ABC-related errors

**Rollback Steps**:

1. **Revert to previous git commit** (before Phase 2):
```bash
# Check git log
git log --oneline -5

# Revert to commit before ABC migration
git revert {COMMIT_HASH}
```

2. **Redeploy previous version**:
```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

3. **Verify health**:
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

### Rollback Files to Restore

If reverting manually:

1. **Remove ABC inheritance from all 10 jobs**:
```python
# Change FROM:
from jobs.base import JobBase
class YourJob(JobBase):

# Back TO:
class YourJob:
```

2. **Remove jobs/base.py**

3. **Update jobs/__init__.py** - remove JobBase export

4. **Restore deleted files**:
   - `jobs/workflow.py` (from git history)
   - `jobs/registry.py` (from git history)

---

## Post-Deployment Actions

### After Successful Deployment

1. **Update HISTORY.md**:
   - Document Phase 2 completion
   - Note all 10 jobs migrated successfully
   - Record deployment date/time

2. **Update TODO_ACTIVE.md**:
   - Remove Phase 2 tasks
   - Mark ABC migration as complete

3. **Create git tag**:
```bash
git tag -a phase-2-abc-complete -m "Phase 2: ABC Migration Complete - All 10 jobs"
git push origin phase-2-abc-complete
```

4. **Monitor for 24 hours**:
   - Check Application Insights daily
   - Verify no new ABC-related errors
   - Confirm job success rates unchanged

---

## Timeline

**Expected Duration**: 30-45 minutes total

- Deployment: 5 minutes
- Health check: 2 minutes
- Quick test (HelloWorld): 5 minutes
- Comprehensive test (all 10 jobs): 20 minutes
- Monitoring/verification: 10 minutes

---

## Contact & Support

**If issues arise**:
1. Check Application Insights for stack traces
2. Review deployment logs in Azure Portal
3. Verify git commit history for accidental changes
4. Use rollback plan if critical failure

**Key Resources**:
- Application Insights: `829adb94-5f5c-46ae-9f00-18e731529222`
- Function App: `rmhgeoapibeta`
- Resource Group: `rmhazure_rg`
- Database: `rmhpgflex.postgres.database.azure.com`

---

**Date**: 15 OCT 2025
**Status**: Ready for Deployment
**Risk Level**: LOW (minimal code changes, all local tests passed)
