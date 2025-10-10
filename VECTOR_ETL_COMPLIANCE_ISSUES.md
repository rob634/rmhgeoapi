# Vector ETL CoreMachine Compliance Issues

**Date**: 10 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document compliance issues found in vector ETL jobs

---

## Summary

Two vector ETL job classes have been reviewed against the CoreMachine contract established by the raster ETL success. Both have **compliance issues** that need correction.

**Status**: ❌ NOT COMPLIANT (2 issues found)

---

## Issue 1: IngestVectorJob - Missing Trigger Support Methods ❌

**File**: `jobs/ingest_vector.py`
**Class**: `IngestVectorJob`

### Missing Methods

The following methods are **REQUIRED** by CoreMachine but are **NOT implemented**:

1. ❌ **`create_job_record(job_id: str, params: dict) -> dict`** - Missing
2. ❌ **`queue_job(job_id: str, params: dict) -> dict`** - Missing

### Current State

✅ **Has these methods** (compliant):
- `validate_job_parameters(params)` - Line 64
- `generate_job_id(params)` - Line 157
- `create_tasks_for_stage(stage, job_params, job_id, previous_results)` - Line 169
- `stages` attribute - Line 35

❌ **Missing these methods** (non-compliant):
- `create_job_record()` - Not present
- `queue_job()` - Not present

### Impact

Without these methods, the CoreMachine cannot:
- Create job records in the database
- Queue jobs to Service Bus
- Complete the job submission flow

### Fix Required

Add the two missing methods following the **exact pattern** from `StacCatalogVectorsWorkflow` (lines 156-248):

```python
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    """Create job record for database storage."""
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus

    job_record = JobRecord(
        job_id=job_id,
        job_type="ingest_vector",  # Match job_type attribute
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=2,  # IngestVectorJob has 2 stages
        stage_results={},
        metadata={
            "description": "Load vector file and ingest to PostGIS with parallel chunked uploads",
            "created_by": "IngestVectorJob",
            "blob_name": params.get("blob_name"),
            "table_name": params.get("table_name"),
            "file_extension": params.get("file_extension")
        }
    )

    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    job_repo.create_job(job_record)

    return job_record.model_dump()

@staticmethod
def queue_job(job_id: str, params: dict) -> dict:
    """Queue job for processing using Service Bus."""
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage
    from config import get_config
    from util_logger import LoggerFactory, ComponentType
    import uuid

    logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "IngestVectorJob.queue_job")
    logger.info(f"🚀 Starting queue_job for job_id={job_id}")

    config = get_config()
    queue_name = config.service_bus_jobs_queue

    service_bus_repo = ServiceBusRepository()

    correlation_id = str(uuid.uuid4())
    job_message = JobQueueMessage(
        job_id=job_id,
        job_type="ingest_vector",  # Match job_type attribute
        stage=1,
        parameters=params,
        correlation_id=correlation_id
    )

    message_id = service_bus_repo.send_message(queue_name, job_message)
    logger.info(f"✅ Message sent successfully - message_id={message_id}")

    result = {
        "queued": True,
        "queue_type": "service_bus",
        "queue_name": queue_name,
        "message_id": message_id,
        "job_id": job_id
    }

    logger.info(f"🎉 Job queued successfully - {result}")
    return result
```

**Critical**: Both methods must use `job_type="ingest_vector"` to match the class's `job_type` attribute (line 31).

---

## Issue 2: IngestVectorJob - Wrong aggregate Method Signature ⚠️

**File**: `jobs/ingest_vector.py`
**Class**: `IngestVectorJob`

### Current Method (WRONG)

Line 245-282:
```python
@staticmethod
def aggregate_results(stage: int, task_results: list) -> dict:
    """Aggregate task results for a stage."""
```

**Problems**:
1. ❌ Method name is `aggregate_results` - should be `aggregate_job_results`
2. ❌ Signature is `(stage: int, task_results: list)` - should be `(context: JobExecutionContext)`

### Required Method (CORRECT)

Per raster ETL success pattern, the method MUST be:

```python
@staticmethod
def aggregate_job_results(context) -> Dict[str, Any]:
    """
    Aggregate results from all completed tasks into job summary.

    Args:
        context: JobExecutionContext with task results

    Returns:
        Aggregated job results dict
    """
    from core.models import TaskStatus

    task_results = context.task_results
    params = context.parameters

    # Separate by stage
    stage_1_tasks = [t for t in task_results if t.task_type == "prepare_vector_chunks"]
    stage_2_tasks = [t for t in task_results if t.task_type == "upload_pickled_chunk"]

    # Extract chunk metadata from Stage 1
    total_chunks = 0
    total_rows = 0
    if stage_1_tasks and stage_1_tasks[0].result_data:
        stage_1_result = stage_1_tasks[0].result_data.get("result", {})
        total_chunks = stage_1_result.get("chunk_count", 0)

    # Count successful uploads from Stage 2
    successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
    total_rows_uploaded = sum(
        t.result_data.get("result", {}).get("rows_uploaded", 0)
        for t in stage_2_tasks
        if t.result_data
    )

    return {
        "job_type": "ingest_vector",
        "table_name": params.get("table_name"),
        "schema": params.get("schema"),
        "blob_name": params.get("blob_name"),
        "file_extension": params.get("file_extension"),
        "summary": {
            "total_chunks": total_chunks,
            "chunks_uploaded": successful_chunks,
            "failed_chunks": len(stage_2_tasks) - successful_chunks,
            "total_rows_uploaded": total_rows_uploaded,
            "success_rate": f"{(successful_chunks / len(stage_2_tasks) * 100):.1f}%" if stage_2_tasks else "0%"
        },
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(task_results),
        "tasks_by_status": {
            "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
        }
    }
```

### Fix Required

1. **DELETE** the old `aggregate_results()` method entirely (lines 245-282)
2. **ADD** the new `aggregate_job_results(context)` method with correct signature
3. **Match pattern** from `ProcessRasterWorkflow.aggregate_job_results()` (jobs/process_raster.py:431-487)

---

## Issue 3: StacCatalogVectorsWorkflow - Already Compliant ✅

**File**: `jobs/stac_catalog_vectors.py`
**Class**: `StacCatalogVectorsWorkflow`

### Status: COMPLIANT ✅

All required methods present and correct:

✅ `validate_job_parameters(params)` - Line 49
✅ `generate_job_id(params)` - Line 108
✅ `create_tasks_for_stage(stage, job_params, job_id, previous_results)` - Line 120
✅ `create_job_record(job_id, params)` - Line 156
✅ `queue_job(job_id, params)` - Line 197
✅ `aggregate_job_results(context)` - Line 251 (**CORRECT SIGNATURE**)
✅ `stages` attribute - Line 30

**No changes needed** for this class!

---

## Comparison Table

| Method | IngestVectorJob | StacCatalogVectorsWorkflow | ProcessRasterWorkflow | Required? |
|--------|----------------|---------------------------|----------------------|-----------|
| `validate_job_parameters(params)` | ✅ Line 64 | ✅ Line 49 | ✅ Line 97 | ✅ YES |
| `generate_job_id(params)` | ✅ Line 157 | ✅ Line 108 | ✅ Line 203 | ✅ YES |
| `create_tasks_for_stage(...)` | ✅ Line 169 | ✅ Line 120 | ✅ Line 310 | ✅ YES |
| `create_job_record(job_id, params)` | ❌ **MISSING** | ✅ Line 156 | ✅ Line 215 | ✅ YES |
| `queue_job(job_id, params)` | ❌ **MISSING** | ✅ Line 197 | ✅ Line 256 | ✅ YES |
| `aggregate_job_results(context)` | ❌ Wrong name/signature | ✅ Line 251 | ✅ Line 431 | ✅ YES |
| `stages` attribute | ✅ Line 35 | ✅ Line 30 | ✅ Line 61 | ✅ YES |

---

## Fix Priority

### High Priority (Blocks Execution)
1. **IngestVectorJob**: Add `create_job_record()` method
2. **IngestVectorJob**: Add `queue_job()` method
3. **IngestVectorJob**: Fix `aggregate_results()` → `aggregate_job_results(context)`

### Reference Implementation
Use **StacCatalogVectorsWorkflow** as the reference - it's already compliant!

Copy methods from:
- `create_job_record()` - Lines 156-194
- `queue_job()` - Lines 197-248
- `aggregate_job_results()` - Lines 251-294

Only change:
- `job_type="ingest_vector"` (instead of "stac_catalog_vectors")
- `total_stages=2` (instead of 1)
- Job metadata (blob_name, table_name, etc.)

---

## Testing Plan

After fixes applied:

### Local Import Test
```python
python3 -c "
from jobs.ingest_vector import IngestVectorJob
from jobs.stac_catalog_vectors import StacCatalogVectorsWorkflow

# Test IngestVectorJob has all methods
assert hasattr(IngestVectorJob, 'create_job_record')
assert hasattr(IngestVectorJob, 'queue_job')
assert hasattr(IngestVectorJob, 'aggregate_job_results')
assert not hasattr(IngestVectorJob, 'aggregate_results')  # Old method removed

print('✅ IngestVectorJob compliance verified')
print('✅ StacCatalogVectorsWorkflow already compliant')
"
```

### Deployment Test
1. Deploy to Azure Functions
2. Test job submission:
```bash
# IngestVectorJob
curl -X POST .../api/jobs/submit/ingest_vector \
  -d '{"blob_name": "test.csv", "file_extension": "csv", "table_name": "test_table"}'

# StacCatalogVectorsWorkflow
curl -X POST .../api/jobs/submit/stac_catalog_vectors \
  -d '{"schema": "geo", "table_name": "test_table"}'
```

---

## Success Criteria

- [ ] IngestVectorJob has `create_job_record()` method
- [ ] IngestVectorJob has `queue_job()` method
- [ ] IngestVectorJob has `aggregate_job_results(context)` method (NOT aggregate_results)
- [ ] Old `aggregate_results()` method removed from IngestVectorJob
- [ ] Local import test passes for both classes
- [ ] Both jobs can be submitted via API
- [ ] CoreMachine can call all required methods without AttributeError

---

## Next Steps

1. **Update IngestVectorJob** (jobs/ingest_vector.py):
   - Add `create_job_record()` method (copy from StacCatalogVectorsWorkflow, adjust job_type)
   - Add `queue_job()` method (copy from StacCatalogVectorsWorkflow, adjust job_type)
   - Replace `aggregate_results()` with `aggregate_job_results(context)`

2. **Test locally** with import validation

3. **Commit to dev branch** with descriptive message

4. **Deploy and test** job submission

---

**End of Compliance Report**
