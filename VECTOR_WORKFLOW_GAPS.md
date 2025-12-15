# Vector Workflow Gap Analysis & Remediation Plan

**Date**: 15 DEC 2025
**Scope**: `process_vector` ETL pipeline reliability improvements
**Context**: Azure Function App with hard system limits

---

## Implementation Status (15 DEC 2025)

| Gap | Priority | Status | Location |
|-----|----------|--------|----------|
| **GAP-001** | P0 | ✅ IMPLEMENTED | `jobs/process_vector.py:258-277` |
| **GAP-002** | P0 | ✅ IMPLEMENTED | `services/vector/process_vector_tasks.py:130-164` |
| **GAP-003** | P0 | ✅ ALREADY EXISTS | `services/janitor_service.py` + timer triggers |
| **GAP-004** | P0 | ✅ IMPLEMENTED | `core/state_manager.py:927-992`, `core/machine.py:1065-1078` |
| **GAP-005** | P1 | ✅ IMPLEMENTED | `services/vector/process_vector_tasks.py:490-566` |
| **GAP-006** | P1 | ✅ IMPLEMENTED | `core/models/results.py:127-252`, `jobs/process_vector.py:248-282` |
| **GAP-007** | P1 | ✅ IMPLEMENTED | `services/vector/process_vector_tasks.py:107-136` |

### Summary of Changes
- **GAP-001**: Added validation in `create_tasks_for_stage()` to fail if chunk_paths empty or table_name missing
- **GAP-002**: Added validation after converter AND after `prepare_gdf()` to fail if 0 features
- **GAP-003**: Already implemented! JanitorService has `run_task_watchdog()`, `run_job_health_check()`, `run_orphan_detection()`
- **GAP-004**: Added `StateManager.fail_all_job_tasks()` method, integrated into CoreMachine stage advancement failure handler
- **GAP-005**: Expanded exception handling to categorize MemoryError, OSError, TimeoutError, ConnectionError as retryable
- **GAP-006**: Added Pydantic models `ProcessVectorStage1Result` and `ProcessVectorStage1Data` to validate Stage 1 results before Stage 2 fan-out
- **GAP-007**: Added pre-flight file size check (2GB limit, raised from 300MB per user request) before downloading to prevent OOM

### Bug Fixes Discovered During Testing (15 DEC 2025)

| Bug | Status | Location |
|-----|--------|----------|
| **BUG-001**: Permanent task failures not marked in DB | ✅ FIXED | `core/machine.py:1146-1190` |
| **GAP-008a**: CSV lat/lon validation at submission | ✅ FIXED | `infrastructure/validators.py:1308-1385`, `jobs/process_vector.py:159-173` |
| **GAP-008b**: CSV column validation at runtime | ✅ FIXED | `services/vector/converters.py:63-86` |

- **BUG-001**: When handler returns `{success: False, retryable: False}`, task was logged as permanent failure but DB status never updated. Now calls `mark_task_failed()` + `mark_job_failed()`.
- **GAP-008a**: New `csv_geometry_params` validator added to `resource_validators`. CSV files now fail at submission with 400 if missing lat_name/lon_name OR wkt_column.
- **GAP-008b**: CSV converter now validates that specified column names exist in the actual file. Clear error: "Column 'xxx' not found. Available columns: [...]"
- **GAP-008 (task params)**: Added `lat_name`, `lon_name`, `wkt_column` to task parameters in `create_tasks_for_stage()` so they propagate to the converter

---

## System Constraints (Azure Function App)

| Constraint | Limit | Impact |
|------------|-------|--------|
| **Execution Timeout** | 10 minutes (Consumption), 30 minutes (Premium/Dedicated) | Tasks exceeding timeout = FAILED, no ambiguity |
| **Memory** | 1.5 GB (Consumption), 3.5-14 GB (Premium) | Stage 1 loads entire file into memory |
| **Service Bus Lock** | 5 minutes default | Long tasks get duplicate delivery |
| **Managed Identity Token** | 1-2 hour expiry | Long-lived connections fail on token refresh |

**Key Insight**: Hard timeouts simplify "stuck task" detection - any task in PROCESSING longer than the function timeout is definitively failed.

---

## Gap Inventory

### P0 - Critical (Jobs Hang in PROCESSING)

#### GAP-001: Empty chunk_paths Creates Zero Tasks (Silent "Success")

**Location**: `jobs/process_vector.py:243-273`

**Symptom**: Job completes all stages with 0 rows inserted, appears successful.

**Root Cause**:
```python
# Line 254 - chunk_paths defaults to empty list, no error raised
chunk_paths = result_data.get('chunk_paths', [])

# Line 259-272 - Loop creates 0 tasks if chunk_paths empty
tasks = []
for i, chunk_path in enumerate(chunk_paths):  # Iterates 0 times
    tasks.append({...})
return tasks  # Returns empty list
```

**Impact**:
- Job advances to Stage 3 with no data uploaded
- STAC item created for empty table
- User sees "completed" but table has 0 rows

**Remediation**:
```python
# In create_tasks_for_stage() for stage 2
chunk_paths = result_data.get('chunk_paths', [])

if not chunk_paths:
    raise ValueError(
        f"Stage 1 returned no chunk_paths. "
        f"Stage 1 result keys: {list(result_data.keys())}. "
        f"This indicates Stage 1 failed to produce chunks - check Stage 1 logs."
    )
```

**Effort**: Low (5 lines)

---

#### GAP-002: Empty GeoDataFrame Passes Validation

**Location**: `services/vector/process_vector_tasks.py:127-137`

**Symptom**: Job creates table with 0 rows, proceeds to completion.

**Root Cause**:
```python
# Line 127 - No check for empty result
gdf = converters[file_extension](file_data, **converter_params)
total_features = len(gdf)
logger.info(f"[{job_id[:8]}] Loaded {total_features} features")
# Proceeds even if total_features == 0

# Line 137 - prepare_gdf can filter out all features
validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)
# No check if all features were filtered
```

**Impact**:
- Empty/invalid source files create empty tables
- All-null geometry files silently produce 0-row tables

**Remediation**:
```python
# After converter (line 128)
gdf = converters[file_extension](file_data, **converter_params)
total_features = len(gdf)

if total_features == 0:
    raise ValueError(
        f"Source file '{blob_name}' contains 0 features. "
        f"File may be empty, corrupted, or in wrong format for extension '{file_extension}'."
    )

# After prepare_gdf (line 138)
validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)

if len(validated_gdf) == 0:
    raise ValueError(
        f"All {total_features} features filtered out during validation. "
        f"Check geometry_params: {geometry_params}. "
        f"Common causes: all NULL geometries, invalid coordinates, CRS issues."
    )
```

**Effort**: Low (10 lines)

---

#### GAP-003: Stale Task Detection Missing

**Location**: No implementation exists

**Symptom**: Tasks stuck in PROCESSING indefinitely, jobs never complete.

**Root Cause**:
- Heartbeat disabled (token expiration issues)
- No background process to detect stale tasks
- No timeout-based cleanup

**Impact**:
- Jobs hang forever waiting for "processing" tasks
- Manual database intervention required
- Poison accumulation over time

**Remediation** (Azure Function Timer Trigger):

```python
# New file: triggers/maintenance.py

@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")  # Every 5 minutes
def detect_stale_tasks(timer: func.TimerRequest) -> None:
    """
    Detect and fail tasks stuck in PROCESSING longer than function timeout.

    Azure Function App Constraint: Tasks cannot run longer than timeout.
    If task is PROCESSING and updated_at > timeout ago, it definitively failed.
    """
    from config import get_config
    config = get_config()

    # Use function timeout as stale threshold (with buffer)
    # B3 Basic = 30 min timeout, add 5 min buffer = 35 min
    STALE_THRESHOLD_MINUTES = 35

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Find stale tasks
            cur.execute("""
                UPDATE app.tasks
                SET status = 'failed',
                    error_details = 'Task exceeded function timeout - marked failed by stale task detector',
                    updated_at = NOW()
                WHERE status = 'processing'
                  AND updated_at < NOW() - INTERVAL '%s minutes'
                RETURNING task_id, parent_job_id, task_type
            """, (STALE_THRESHOLD_MINUTES,))

            stale_tasks = cur.fetchall()

            if stale_tasks:
                logger.warning(f"Marked {len(stale_tasks)} stale tasks as FAILED")

                # Also fail parent jobs that have failed tasks
                job_ids = set(t['parent_job_id'] for t in stale_tasks)
                for job_id in job_ids:
                    cur.execute("""
                        UPDATE app.jobs
                        SET status = 'failed',
                            error_details = 'Job failed due to stale task timeout',
                            updated_at = NOW()
                        WHERE job_id = %s AND status = 'processing'
                    """, (job_id,))

            conn.commit()
```

**Effort**: Medium (new trigger + SQL)

---

#### GAP-004: Orphan Tasks on Stage Advancement Failure

**Location**: `core/machine.py:1045-1084`

**Symptom**: Job marked FAILED but sibling tasks in same stage stay PROCESSING.

**Root Cause**:
```python
# Line 1055-1063 - Only marks job failed, not sibling tasks
try:
    self.state_manager.mark_job_failed(
        task_message.parent_job_id,
        error_msg
    )
except Exception as cleanup_error:
    # Only logs, doesn't clean up other tasks
```

**Impact**:
- Orphan tasks continue processing even though job is failed
- Database inconsistency (failed job with processing tasks)
- Wasted compute resources

**Remediation**:
```python
# In _handle_stage_completion() exception handler
try:
    self.state_manager.mark_job_failed(job_id, error_msg)

    # NEW: Also fail all tasks for this job
    self.state_manager.fail_all_job_tasks(
        job_id,
        f"Parent job failed during stage advancement: {error_msg}"
    )
except Exception as cleanup_error:
    log_nested_error(...)
```

Add to StateManager:
```python
def fail_all_job_tasks(self, job_id: str, error_msg: str) -> int:
    """Mark all non-terminal tasks for a job as FAILED."""
    with self.repos['task_repo']._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE app.tasks
                SET status = 'failed',
                    error_details = %s,
                    updated_at = NOW()
                WHERE parent_job_id = %s
                  AND status NOT IN ('completed', 'failed')
                RETURNING task_id
            """, (error_msg, job_id))
            failed = cur.fetchall()
            conn.commit()
            return len(failed)
```

**Effort**: Medium (new StateManager method + integration)

---

### P1 - High (Silent Failures)

#### GAP-005: Generic Exception Marked Non-Retryable

**Location**: `services/vector/process_vector_tasks.py:463-477`

**Symptom**: Transient failures (timeout, memory pressure) permanently fail task.

**Root Cause**:
```python
except Exception as e:
    # Line 476 - All unknown exceptions marked non-retryable
    "retryable": False  # WRONG for transient errors
```

**Impact**:
- Network blips permanently fail tasks
- Memory pressure during GC permanently fails tasks
- Lock timeouts permanently fail tasks

**Remediation**:
```python
# Define retryable exception types
RETRYABLE_EXCEPTIONS = (
    psycopg.OperationalError,  # Connection issues
    MemoryError,               # Transient memory pressure
    TimeoutError,              # Operation timeouts
    ConnectionError,           # Network issues
    OSError,                   # I/O errors (often transient)
)

PERMANENT_EXCEPTIONS = (
    psycopg.DataError,         # Bad data
    psycopg.IntegrityError,    # Constraint violation
    ValueError,                # Invalid parameters
    TypeError,                 # Programming bug
    KeyError,                  # Missing required field
)

# In exception handler
except RETRYABLE_EXCEPTIONS as e:
    return {"success": False, "retryable": True, "error": str(e), ...}
except PERMANENT_EXCEPTIONS as e:
    return {"success": False, "retryable": False, "error": str(e), ...}
except Exception as e:
    # Unknown = retry cautiously (let Service Bus handle)
    return {"success": False, "retryable": True, "error": str(e), ...}
```

**Effort**: Low (exception categorization)

---

#### GAP-006: Stage 1 Result Structure Not Validated

**Location**: `jobs/process_vector.py:248-256`

**Symptom**: KeyError or silent empty values if Stage 1 returns malformed data.

**Root Cause**:
```python
# Line 249 - Assumes [0] exists
stage_1_result = previous_results[0]

# Line 250 - Assumes 'success' key exists
if not stage_1_result.get('success'):

# Line 253-256 - Multiple nested .get() with defaults
result_data = stage_1_result.get('result', {})
chunk_paths = result_data.get('chunk_paths', [])
table_name = result_data.get('table_name')  # Could be None!
```

**Impact**:
- Empty previous_results → IndexError
- Missing keys → AttributeError or None values propagate
- Debugging requires tracing through multiple stages

**Remediation** (Pydantic model for stage results):
```python
# In core/models/results.py
from pydantic import BaseModel, Field
from typing import List, Optional

class Stage1VectorResult(BaseModel):
    """Validated structure for process_vector Stage 1 results."""
    success: bool
    result: 'Stage1VectorData'

class Stage1VectorData(BaseModel):
    chunk_paths: List[str] = Field(..., min_length=1)  # Must have at least 1
    total_features: int = Field(..., gt=0)  # Must be positive
    num_chunks: int = Field(..., gt=0)
    table_name: str
    schema: str = "geo"
    columns: List[str]
    geometry_type: str
    srid: int = 4326

# In create_tasks_for_stage()
from core.models.results import Stage1VectorResult

if stage == 2:
    if not previous_results:
        raise ValueError("Stage 2 requires Stage 1 results")

    # Validate structure with Pydantic
    try:
        stage_1 = Stage1VectorResult(**previous_results[0])
    except ValidationError as e:
        raise ValueError(f"Stage 1 result validation failed: {e}")

    chunk_paths = stage_1.result.chunk_paths  # Guaranteed to exist and be non-empty
```

**Effort**: Medium (Pydantic model + integration)

---

#### GAP-007: Memory Exhaustion During GeoDataFrame Load

**Location**: `services/vector/process_vector_tasks.py:126-128`

**Symptom**: Function crashes with OOM, no useful error message.

**Root Cause**: Large files loaded entirely into memory with no size check.

**Azure Constraint**: B3 Basic has ~1.75GB memory, Premium up to 14GB.

**Remediation** (pre-flight size check + streaming for large files):
```python
# At start of process_vector_prepare
blob_repo = BlobRepository.for_zone("bronze")

# Get blob size before download
blob_properties = blob_repo.get_blob_properties(container_name, blob_name)
blob_size_mb = blob_properties.get('size', 0) / (1024 * 1024)

# Memory safety threshold (leave headroom for GDF expansion)
# GeoDataFrame typically 3-5x larger than source file in memory
MAX_SAFE_SIZE_MB = 300  # ~1GB in memory after expansion

if blob_size_mb > MAX_SAFE_SIZE_MB:
    raise ValueError(
        f"Source file too large for in-memory processing: {blob_size_mb:.1f}MB. "
        f"Maximum supported: {MAX_SAFE_SIZE_MB}MB. "
        f"Use 'process_large_vector' job type for files > {MAX_SAFE_SIZE_MB}MB."
    )

logger.info(f"[{job_id[:8]}] Source file size: {blob_size_mb:.1f}MB (limit: {MAX_SAFE_SIZE_MB}MB)")
```

**Effort**: Low (size check) / High (streaming alternative)

---

### P2 - Medium (Debug Logging Gaps)

#### GAP-008: No Timing Per Chunk in Stage 2

**Location**: `services/vector/process_vector_tasks.py:349-477`

**Symptom**: Can't identify slow chunks or estimate completion time.

**Remediation**:
```python
def process_vector_upload(parameters: Dict[str, Any]) -> Dict[str, Any]:
    import time
    start_time = time.time()

    # ... existing code ...

    # After INSERT completes
    elapsed = time.time() - start_time
    rows_per_second = result['rows_inserted'] / elapsed if elapsed > 0 else 0

    logger.info(
        f"[{job_id[:8]}] Chunk {chunk_index} uploaded: "
        f"{result['rows_inserted']} rows in {elapsed:.2f}s "
        f"({rows_per_second:.0f} rows/sec)"
    )

    return {
        "success": True,
        "result": {
            **result,
            "elapsed_seconds": round(elapsed, 2),
            "rows_per_second": round(rows_per_second, 0)
        }
    }
```

**Effort**: Low

---

#### GAP-009: No Memory Usage Logging

**Location**: `services/vector/process_vector_tasks.py:126-137`

**Symptom**: OOM failures with no warning signs in logs.

**Remediation**:
```python
def _log_memory_usage(gdf, label: str, job_id: str):
    """Log GeoDataFrame memory usage for debugging."""
    mem_bytes = gdf.memory_usage(deep=True).sum()
    mem_mb = mem_bytes / (1024 * 1024)
    logger.info(f"[{job_id[:8]}] Memory usage ({label}): {mem_mb:.1f}MB")
    return mem_mb

# In process_vector_prepare
gdf = converters[file_extension](file_data, **converter_params)
_log_memory_usage(gdf, "after_load", job_id)

validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)
_log_memory_usage(validated_gdf, "after_validation", job_id)
```

**Effort**: Low

---

#### GAP-010: No Batch ID Logging at DELETE Phase

**Location**: `services/vector/process_vector_tasks.py:407-418`

**Symptom**: Can't verify idempotency worked from logs alone.

**Remediation**:
```python
# In insert_chunk_idempotent (VectorToPostGISHandler)
logger.info(
    f"[{batch_id}] DELETE+INSERT: "
    f"deleted={rows_deleted} existing rows, "
    f"inserting={len(chunk)} new rows into {schema}.{table_name}"
)
```

**Effort**: Low

---

### P3 - Future (Heartbeat / Progress)

#### GAP-011: Heartbeat Disabled (Token Expiration)

**Location**: `core/machine.py:835-846`

**Current Status**: Disabled due to Managed Identity token expiration on long-lived connections.

**Azure Constraint**: MI tokens expire after 1-2 hours. Background threads holding connections fail.

**Alternative Approach** (timestamp-based instead of active heartbeat):

Since Azure Functions have hard timeouts, we don't need active heartbeats. Instead:

1. **Use `updated_at` as implicit heartbeat** - updated on status changes
2. **Timer trigger detects stale tasks** (GAP-003)
3. **Service Bus visibility timeout** handles in-flight tasks

**Recommendation**: Do NOT re-enable active heartbeat. The timer trigger approach (GAP-003) is simpler and works within Azure constraints.

**Effort**: N/A (use GAP-003 instead)

---

#### GAP-012: No Progress Tracking for Chunked Uploads

**Location**: No implementation exists

**Symptom**: No way to see "5 of 10 chunks uploaded" during Stage 2.

**Remediation** (job metadata progress field):
```python
# In CoreMachine when task completes (process_task_message)
if result.status == TaskStatus.COMPLETED:
    # Update job progress metadata
    self._update_job_progress(
        task_message.parent_job_id,
        task_message.stage,
        task_message.task_type
    )

def _update_job_progress(self, job_id: str, stage: int, task_type: str):
    """Update job metadata with progress info."""
    # Get task counts for this stage
    all_tasks = self.repos['task_repo'].get_tasks_for_job(job_id)
    stage_tasks = [t for t in all_tasks if t.stage == stage]

    completed = sum(1 for t in stage_tasks if t.status == TaskStatus.COMPLETED)
    total = len(stage_tasks)

    # Update job metadata
    progress = {
        f"stage_{stage}_progress": f"{completed}/{total}",
        f"stage_{stage}_percent": round(completed / total * 100) if total > 0 else 0
    }

    self.repos['job_repo'].update_job_metadata(job_id, progress)
```

**Effort**: Medium

---

## Implementation Priority

### Phase 1: Quick Wins (P0 + P1 Low Effort)
| Gap | Description | Effort |
|-----|-------------|--------|
| GAP-001 | Empty chunk_paths validation | 5 lines |
| GAP-002 | Empty GeoDataFrame validation | 10 lines |
| GAP-005 | Exception categorization | 20 lines |
| GAP-007 | Pre-flight file size check | 15 lines |

**Total**: ~50 lines, 1-2 hours

### Phase 2: Reliability (P0 Medium Effort)
| Gap | Description | Effort |
|-----|-------------|--------|
| GAP-003 | Stale task detector timer trigger | New file |
| GAP-004 | Orphan task cleanup | StateManager method |

**Total**: ~100 lines + new trigger, 2-4 hours

### Phase 3: Observability (P2)
| Gap | Description | Effort |
|-----|-------------|--------|
| GAP-008 | Timing per chunk | 10 lines |
| GAP-009 | Memory logging | 15 lines |
| GAP-010 | Batch ID logging | 5 lines |

**Total**: ~30 lines, 1 hour

### Phase 4: Optional (P1 Medium + P3)
| Gap | Description | Effort |
|-----|-------------|--------|
| GAP-006 | Pydantic stage result models | New models |
| GAP-012 | Progress tracking | CoreMachine changes |

**Total**: ~150 lines, 4-6 hours

---

## Testing Strategy

### Unit Tests
- Empty GeoDataFrame converter results
- Empty chunk_paths in Stage 2
- Exception categorization (retryable vs permanent)
- Stage result validation

### Integration Tests
- Submit job with empty file → expect 400 or Stage 1 failure
- Submit job with oversized file → expect 400 pre-flight failure
- Simulate Stage 1 timeout → expect stale task detection

### Manual Verification
- Monitor Application Insights for new log fields
- Verify orphan task cleanup in database
- Confirm stale task timer trigger fires

---

## Appendix: Execution Trace Reference

```
POST /api/jobs/submit/process_vector
    │
    ├─[VALIDATE] parameters_schema (JobBaseMixin)
    ├─[VALIDATE] resource_validators (blob_exists, table_not_exists)
    ├─[CREATE] JobRecord → app.jobs (status=QUEUED)
    └─[QUEUE] JobQueueMessage → Service Bus (jobs queue)
           │
           ▼
    CoreMachine.process_job_message() [Stage 1]
        │
        ├─[UPDATE] job status: QUEUED → PROCESSING
        ├─[CREATE] TaskDefinition for Stage 1
        ├─[INSERT] TaskRecord → app.tasks (status=QUEUED)
        └─[QUEUE] TaskQueueMessage → Service Bus (vector-tasks queue)
               │
               ▼
        CoreMachine.process_task_message() [Stage 1]
            │
            ├─[UPDATE] task status: QUEUED → PROCESSING
            ├─[EXECUTE] process_vector_prepare handler
            │     │
            │     ├─[DOWNLOAD] blob from Bronze zone
            │     ├─[CONVERT] to GeoDataFrame ⚠️ GAP-002, GAP-007
            │     ├─[VALIDATE] prepare_gdf() ⚠️ GAP-002
            │     ├─[CREATE] PostGIS table
            │     ├─[CHUNK] GeoDataFrame
            │     ├─[PICKLE] chunks to Silver zone
            │     └─[RETURN] chunk_paths
            │
            ├─[UPDATE] task status: PROCESSING → COMPLETED
            ├─[CHECK] stage_complete? (advisory lock)
            └─[ADVANCE] queue Stage 2 job message ⚠️ GAP-004
                   │
                   ▼
        CoreMachine.process_job_message() [Stage 2]
            │
            ├─[FETCH] Stage 1 results
            ├─[CREATE] N TaskDefinitions (fan-out) ⚠️ GAP-001, GAP-006
            └─[QUEUE] N TaskQueueMessages
                   │
                   ▼
        CoreMachine.process_task_message() [Stage 2, N times]
            │
            ├─[EXECUTE] process_vector_upload handler ⚠️ GAP-005, GAP-008
            │     │
            │     ├─[LOAD] pickled chunk
            │     ├─[DELETE] existing rows (batch_id) ⚠️ GAP-010
            │     └─[INSERT] new rows
            │
            ├─[UPDATE] task status → COMPLETED
            └─[CHECK] last task? → advance Stage 3
                   │
                   ▼
        [Stage 3: create_vector_stac - similar pattern]
```

---

**Document Created**: 15 DEC 2025
**Author**: Claude Code Analysis
**Review Required**: Before implementation
