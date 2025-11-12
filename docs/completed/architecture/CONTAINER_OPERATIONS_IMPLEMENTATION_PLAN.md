# Container Operations Implementation Plan

**Date**: 3 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Planning Phase
**Purpose**: Implement blob storage container analysis operations

---

## Overview

Implement two distinct job types for analyzing Azure Blob Storage containers:
1. **`summarize_container`** - Single-stage job producing aggregate statistics
2. **`list_container_contents`** - Two-stage job with fan-out pattern for detailed file analysis

Both operations leverage the existing Job→Stage→Task architecture with retry logic.

---

## Job Type 1: Container Summary (`summarize_container`)

### Purpose
Generate high-level statistics about a container without processing individual files in detail. Fast, lightweight operation suitable for dashboard/monitoring.

### Architecture
**Pattern**: Single-stage, single-task job
**Execution Time**: ~5-30 seconds (depending on container size)
**Database Impact**: Minimal - only job record and result data

### Job Parameters
```python
{
    "container_name": str,        # Required: Azure storage container name
    "file_limit": int | None,     # Optional: Max files to analyze (default: None = all)
    "filter": dict | None         # Optional: Filter criteria
}
```

### Filter Schema (Optional)
```python
{
    "prefix": str | None,              # Blob name prefix (e.g., "2024/")
    "extensions": list[str] | None,    # File extensions (e.g., [".tif", ".tiff"])
    "min_size_mb": float | None,       # Minimum file size in MB
    "max_size_mb": float | None,       # Maximum file size in MB
    "modified_after": str | None,      # ISO datetime string
    "modified_before": str | None      # ISO datetime string
}
```

### Output Schema
```python
{
    "container_name": str,
    "analysis_timestamp": str,              # ISO datetime
    "filter_applied": dict | None,
    "statistics": {
        "total_files": int,
        "total_size_bytes": int,
        "total_size_gb": float,
        "largest_file": {
            "name": str,
            "size_bytes": int,
            "size_mb": float,
            "last_modified": str
        },
        "smallest_file": {
            "name": str,
            "size_bytes": int,
            "last_modified": str
        },
        "file_types": {
            ".tif": {"count": int, "total_size_gb": float},
            ".tiff": {"count": int, "total_size_gb": float},
            # ... per extension
        },
        "size_distribution": {
            "0-10MB": int,
            "10-100MB": int,
            "100MB-1GB": int,
            "1GB-10GB": int,
            "10GB+": int
        },
        "date_range": {
            "oldest_file": str,      # ISO datetime
            "newest_file": str       # ISO datetime
        }
    },
    "execution_info": {
        "files_scanned": int,
        "files_filtered": int,
        "scan_duration_seconds": float,
        "hit_file_limit": bool
    }
}
```

### Implementation Details

#### Workflow Definition
```python
# jobs/container_summary.py

from core.models.stage import StageDefinition
from jobs.workflow import JobWorkflow

class ContainerSummaryWorkflow(JobWorkflow):
    """Single-stage container summary job."""

    job_type = "summarize_container"

    stages = [
        StageDefinition(
            stage_number=1,
            stage_name="analyze_container",
            task_type="container_summary_task",
            description="Scan container and compute statistics"
        )
    ]

    @staticmethod
    def validate_parameters(params: dict) -> dict:
        """Validate job parameters."""
        required = ["container_name"]
        for field in required:
            if field not in params:
                raise ValueError(f"Missing required parameter: {field}")

        # Validate container exists
        from repositories import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        blob_repo = repos['blob_repo']

        if not blob_repo.container_exists(params["container_name"]):
            raise ValueError(f"Container not found: {params['container_name']}")

        return params
```

#### Service Layer
```python
# services/container_summary.py

from typing import Any
from datetime import datetime
from collections import defaultdict
from repositories import RepositoryFactory

def analyze_container_summary(params: dict) -> dict[str, Any]:
    """
    Scan container and generate summary statistics.

    Args:
        params: {
            "container_name": str,
            "file_limit": int | None,
            "filter": dict | None
        }

    Returns:
        Summary statistics dict matching output schema
    """
    container_name = params["container_name"]
    file_limit = params.get("file_limit")
    filter_criteria = params.get("filter", {})

    repos = RepositoryFactory.create_repositories()
    blob_repo = repos['blob_repo']

    # Initialize accumulators
    total_files = 0
    total_size = 0
    largest_file = None
    smallest_file = None
    file_types = defaultdict(lambda: {"count": 0, "total_size_gb": 0.0})
    size_buckets = {
        "0-10MB": 0,
        "10-100MB": 0,
        "100MB-1GB": 0,
        "1GB-10GB": 0,
        "10GB+": 0
    }
    oldest_date = None
    newest_date = None

    start_time = datetime.utcnow()
    files_filtered = 0

    # Stream blob list (memory efficient)
    blobs = blob_repo.list_blobs(
        container_name=container_name,
        name_starts_with=filter_criteria.get("prefix")
    )

    for blob in blobs:
        # Apply filters
        if not _matches_filter(blob, filter_criteria):
            files_filtered += 1
            continue

        # Update statistics
        total_files += 1
        total_size += blob.size

        # Track largest/smallest
        if largest_file is None or blob.size > largest_file["size_bytes"]:
            largest_file = {
                "name": blob.name,
                "size_bytes": blob.size,
                "size_mb": blob.size / (1024 * 1024),
                "last_modified": blob.last_modified.isoformat()
            }

        if smallest_file is None or blob.size < smallest_file["size_bytes"]:
            smallest_file = {
                "name": blob.name,
                "size_bytes": blob.size,
                "last_modified": blob.last_modified.isoformat()
            }

        # Track by extension
        ext = _get_extension(blob.name)
        file_types[ext]["count"] += 1
        file_types[ext]["total_size_gb"] += blob.size / (1024**3)

        # Size distribution
        size_mb = blob.size / (1024 * 1024)
        if size_mb < 10:
            size_buckets["0-10MB"] += 1
        elif size_mb < 100:
            size_buckets["10-100MB"] += 1
        elif size_mb < 1024:
            size_buckets["100MB-1GB"] += 1
        elif size_mb < 10240:
            size_buckets["1GB-10GB"] += 1
        else:
            size_buckets["10GB+"] += 1

        # Date tracking
        if oldest_date is None or blob.last_modified < oldest_date:
            oldest_date = blob.last_modified
        if newest_date is None or blob.last_modified > newest_date:
            newest_date = blob.last_modified

        # Respect file limit
        if file_limit and total_files >= file_limit:
            break

    duration = (datetime.utcnow() - start_time).total_seconds()

    return {
        "container_name": container_name,
        "analysis_timestamp": datetime.utcnow().isoformat(),
        "filter_applied": filter_criteria if filter_criteria else None,
        "statistics": {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_gb": round(total_size / (1024**3), 2),
            "largest_file": largest_file,
            "smallest_file": smallest_file,
            "file_types": dict(file_types),
            "size_distribution": size_buckets,
            "date_range": {
                "oldest_file": oldest_date.isoformat() if oldest_date else None,
                "newest_file": newest_date.isoformat() if newest_date else None
            }
        },
        "execution_info": {
            "files_scanned": total_files + files_filtered,
            "files_filtered": files_filtered,
            "scan_duration_seconds": round(duration, 2),
            "hit_file_limit": file_limit is not None and total_files >= file_limit
        }
    }


def _matches_filter(blob, filter_criteria: dict) -> bool:
    """Check if blob matches filter criteria."""
    if not filter_criteria:
        return True

    # Extension filter
    if "extensions" in filter_criteria:
        ext = _get_extension(blob.name)
        if ext not in filter_criteria["extensions"]:
            return False

    # Size filters
    size_mb = blob.size / (1024 * 1024)
    if "min_size_mb" in filter_criteria:
        if size_mb < filter_criteria["min_size_mb"]:
            return False
    if "max_size_mb" in filter_criteria:
        if size_mb > filter_criteria["max_size_mb"]:
            return False

    # Date filters
    if "modified_after" in filter_criteria:
        after = datetime.fromisoformat(filter_criteria["modified_after"])
        if blob.last_modified < after:
            return False
    if "modified_before" in filter_criteria:
        before = datetime.fromisoformat(filter_criteria["modified_before"])
        if blob.last_modified > before:
            return False

    return True


def _get_extension(filename: str) -> str:
    """Extract file extension (lowercase)."""
    if "." not in filename:
        return "no_extension"
    return filename.rsplit(".", 1)[-1].lower()
```

---

## Job Type 2: List Container Contents (`list_container_contents`)

### Purpose
Create detailed records for every file in a container stored in task `result_data` JSONB fields. Enables querying, filtering, and analysis via SQL on existing `tasks` table. Suitable for inventory management, compliance auditing.

### Architecture
**Pattern**: Two-stage fan-out job
**Stage 1**: Single task lists all blobs, creates Stage 2 tasks
**Stage 2**: Parallel tasks (one per blob) analyze and store metadata in task.result_data
**Execution Time**: ~1-10 minutes (depending on file count and parallelism)
**Database Impact**: Moderate - one task record per file (no new tables needed!)

### Job Parameters
```python
{
    "container_name": str,        # Required
    "file_limit": int | None,     # Optional: Max files to process
    "filter": dict | None         # Optional: Same as summarize_container
}
```

### Task Result Data Schema

Each Stage 2 task stores blob metadata in `tasks.result_data` JSONB field:

```python
{
    "blob_name": str,
    "blob_path": str,               # container_name/blob_name
    "container_name": str,
    "size_bytes": int,
    "size_mb": float,
    "size_gb": float,
    "content_type": str | None,
    "file_extension": str,
    "last_modified": str,           # ISO datetime
    "etag": str,
    "metadata": dict                # Azure blob metadata
}
```

### Querying Results

Use existing `/api/db/tasks/{job_id}` endpoint to retrieve all file records:

```bash
# Get all files analyzed in a job
curl "https://.../api/db/tasks/{JOB_ID}?limit=10000"

# Query PostgreSQL directly for advanced filtering
SELECT
    task_id,
    result_data->>'blob_name' as filename,
    (result_data->>'size_mb')::numeric as size_mb,
    result_data->>'file_extension' as extension,
    result_data->>'last_modified' as modified
FROM app.tasks
WHERE parent_job_id = 'JOB_ID'
  AND stage = 2
  AND status = 'completed'
  AND result_data->>'file_extension' = '.tif'
ORDER BY (result_data->>'size_bytes')::bigint DESC
LIMIT 100;
```

**Benefits of Using task.result_data:**
- ✅ No new tables or schema changes needed
- ✅ Automatic indexing on parent_job_id (already exists)
- ✅ JSONB supports flexible querying with `->>` and `@>` operators
- ✅ Built-in created_at/updated_at timestamps
- ✅ Task status tracks processing state
- ✅ Retry logic already handles failures

### Stage 1: List Blobs

**Task Type**: `list_container_blobs`
**Purpose**: Enumerate all blobs, create one Stage 2 task per blob
**Output**: List of blob names for Stage 2 tasks

```python
# services/container_list.py

def list_container_blobs(params: dict) -> dict:
    """
    Stage 1: List all blobs and return list for Stage 2 task creation.

    Returns:
        {
            "container_name": str,  # Pass through for Stage 2
            "total_files": int,
            "blobs": list[str]  # Just blob names - Stage 2 will fetch details
        }
    """
    container_name = params["container_name"]
    file_limit = params.get("file_limit")
    filter_criteria = params.get("filter", {})

    repos = RepositoryFactory.create_repositories()
    blob_repo = repos['blob_repo']

    # Collect all matching blob names
    blob_names = []
    blobs = blob_repo.list_blobs(
        container_name=container_name,
        name_starts_with=filter_criteria.get("prefix")
    )

    for blob in blobs:
        if not _matches_filter(blob, filter_criteria):
            continue

        blob_names.append(blob.name)

        if file_limit and len(blob_names) >= file_limit:
            break

    return {
        "container_name": container_name,  # Must pass through for Stage 2!
        "total_files": len(blob_names),
        "blobs": blob_names  # Stage 2 creates one task per blob name
    }
```

### Stage 2: Analyze Single Blob

**Task Type**: `analyze_single_blob`
**Purpose**: Fetch blob metadata and store in task.result_data
**Parallelism**: One task per blob (10,000 files = 10,000 parallel tasks)

```python
# services/container_list.py

def analyze_single_blob(params: dict) -> dict:
    """
    Stage 2: Analyze a single blob and return metadata.

    Args:
        params: {
            "container_name": str,
            "blob_name": str
        }

    Returns:
        Blob metadata dict (stored in task.result_data by CoreMachine)
    """
    container_name = params["container_name"]
    blob_name = params["blob_name"]

    repos = RepositoryFactory.create_repositories()
    blob_repo = repos['blob_repo']

    # Get blob properties
    blob_client = blob_repo.get_blob_client(container_name, blob_name)
    properties = blob_client.get_blob_properties()

    # Extract metadata
    file_ext = _get_extension(blob_name)
    size_mb = properties.size / (1024 * 1024)
    size_gb = properties.size / (1024**3)

    # Return metadata - CoreMachine stores this in task.result_data
    return {
        "blob_name": blob_name,
        "blob_path": f"{container_name}/{blob_name}",
        "container_name": container_name,
        "size_bytes": properties.size,
        "size_mb": round(size_mb, 2),
        "size_gb": round(size_gb, 4),
        "content_type": properties.content_settings.content_type if properties.content_settings else None,
        "file_extension": file_ext,
        "last_modified": properties.last_modified.isoformat(),
        "etag": properties.etag,
        "metadata": properties.metadata or {}
    }
```

### Workflow Definition

```python
# jobs/container_list.py

from core.models.stage import StageDefinition
from jobs.workflow import JobWorkflow

class ListContainerContentsWorkflow(JobWorkflow):
    """Two-stage fan-out job for detailed container inventory."""

    job_type = "list_container_contents"

    stages = [
        StageDefinition(
            stage_number=1,
            stage_name="list_blobs",
            task_type="list_container_blobs",
            description="Enumerate all blobs in container"
        ),
        StageDefinition(
            stage_number=2,
            stage_name="analyze_blobs",
            task_type="analyze_single_blob",
            description="Analyze individual blob metadata",
            parallelism="fan_out"  # One task per blob
        )
    ]

    @staticmethod
    def create_stage_2_tasks(stage_1_results: list[dict]) -> list[dict]:
        """
        Create Stage 2 task parameters from Stage 1 results.

        Stage 1 returns:
            {
                "blobs": ["blob1.tif", "blob2.tif", ...]
            }

        Returns: List of task params, one per blob
        """
        stage_1_result = stage_1_results[0]  # Single Stage 1 task
        blob_names = stage_1_result["blobs"]
        container_name = stage_1_result.get("container_name")  # Pass through from Stage 1

        tasks = []
        for blob_name in blob_names:
            tasks.append({
                "container_name": container_name,
                "blob_name": blob_name
            })

        return tasks
```

---

## HTTP Trigger Endpoints

Both job types use the existing generic job submission endpoint - no new routes needed!

### Submit Jobs

```bash
# Container Summary
curl -X POST https://.../api/jobs/submit/summarize_container \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "file_limit": 10000,
    "filter": {
      "extensions": [".tif", ".tiff"],
      "min_size_mb": 1.0
    }
  }'

# List Container Contents
curl -X POST https://.../api/jobs/submit/list_container_contents \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "file_limit": 1000
  }'
```

### Query Results

```bash
# Get container summary result
curl https://.../api/jobs/status/{JOB_ID}
# Returns summary in job.result_data

# Get all file records from list_container_contents job
curl "https://.../api/db/tasks/{JOB_ID}?limit=10000"
# Returns all Stage 2 tasks with blob metadata in task.result_data
```

---

## Implementation Phases

### Phase 1: Container Summary (Estimated: 2-3 hours)

1. **Create workflow definition** (`jobs/container_summary.py`)
2. **Implement service layer** (`services/container_summary.py`)
3. **Add HTTP trigger** (update `triggers/submit_job.py`)
4. **Register job type** (update `jobs/registry.py`)
5. **Test with small container** (10-100 files)
6. **Test with large container** (10,000+ files)
7. **Validate output schema**

**Testing Strategy**:
```bash
# Test 1: Small container, no filters
curl -X POST .../api/jobs/submit/summarize_container \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze"}'

# Test 2: With file limit
curl -X POST .../api/jobs/submit/summarize_container \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "file_limit": 1000}'

# Test 3: With filters
curl -X POST .../api/jobs/submit/summarize_container \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "filter": {"extensions": [".tif"], "min_size_mb": 10}
  }'
```

### Phase 2: List Container Contents (Estimated: 2-3 hours)

1. **Create Stage 1 service** (`services/container_list.py::list_container_blobs`)
2. **Create Stage 2 service** (`services/container_list.py::analyze_single_blob`)
3. **Create workflow definition** (`jobs/container_list.py`)
4. **Register job type** (update `jobs/registry.py`)
5. **Test with small file count** (10 files)
6. **Test with moderate file count** (100 files)
7. **Test with large file count** (1,000 files)
8. **Validate task records** (check result_data JSONB)

**Testing Strategy**:
```bash
# Test 1: Small container
curl -X POST .../api/jobs/submit/list_container_contents \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "file_limit": 10}'

# Test 2: Check job status
curl .../api/jobs/status/{JOB_ID}

# Test 3: Query all file records from tasks
curl ".../api/db/tasks/{JOB_ID}?limit=100"

# Test 4: Query PostgreSQL directly for analysis
# (Use DBeaver or psql to run JSONB queries)

# Test 5: Full container (production scale)
curl -X POST .../api/jobs/submit/list_container_contents \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "file_limit": 1000}'
```

---

## Architecture Validation

### Retry Logic Integration
Both job types benefit from existing retry mechanism:
- **Network failures** during blob listing → automatic retry
- **Database write failures** in Stage 2 → automatic retry
- **Exponential backoff** prevents API throttling

### Parallelism Patterns

**Container Summary**: No parallelism needed - single task aggregates in memory
**List Container**: Fan-out parallelism in Stage 2
- 10,000 files = 10,000 parallel Stage 2 tasks (one task per blob)
- Service Bus handles task distribution
- CoreMachine stores blob metadata in task.result_data automatically

### Performance Considerations

**Container Summary**:
- Memory usage: O(1) - streaming aggregation
- Network calls: O(n) - one list_blobs() call
- Database writes: 1 (job result only)
- Bottleneck: Blob listing API (pagination)

**List Container**:
- Memory usage: O(1) per task - one blob at a time
- Network calls: O(n) - Stage 1 lists, Stage 2 fetches properties per blob
- Database writes: O(n) - task records created automatically
- Bottleneck: Azure Blob Storage API rate limits

### Scalability Limits

| Metric | Container Summary | List Container |
|--------|------------------|----------------|
| Max files (practical) | 1,000,000+ | 100,000 |
| Execution time (1K files) | 5-10 sec | 30-60 sec |
| Execution time (10K files) | 30-60 sec | 5-10 min |
| Database impact | Minimal | High |
| Memory per task | <100MB | <50MB |

---

## Error Handling

### Expected Errors

1. **Container doesn't exist**
   - Detected in: `validate_parameters()`
   - Response: HTTP 400 with clear error message

2. **Empty container**
   - Detected in: Service layer (zero blobs)
   - Behavior: Return valid result with zero counts

3. **Blob listing timeout**
   - Detected in: Azure SDK raises exception
   - Behavior: Retry logic catches and reschedules task

4. **Blob properties fetch failure** (list_container_contents Stage 2)
   - Detected in: Azure SDK raises exception
   - Behavior: Task marked as FAILED, retries up to 3 times

### Unexpected Errors

All unexpected errors handled by existing CoreMachine exception handling:
- Logged to Application Insights with full traceback
- Task marked as FAILED after max retries
- Job continues if other tasks succeed (graceful degradation)

---

## Monitoring & Observability

### Key Metrics to Track

**Container Summary**:
- Job completion time vs. file count
- Memory usage during aggregation
- Filter effectiveness (filtered vs. scanned)

**List Container**:
- Stage 1 → Stage 2 fan-out ratio (1 task → N tasks)
- Task success rate per blob
- API rate limit throttling incidents

### Application Insights Queries

```kql
-- Container summary performance
traces
| where message contains "summarize_container"
| where message contains "completed"
| project timestamp,
    files_scanned = extract("files_scanned: ([0-9]+)", 1, message),
    duration = extract("duration: ([0-9.]+)", 1, message)

-- List container Stage 2 task distribution
traces
| where message contains "analyze_single_blob"
| summarize count() by bin(timestamp, 1m)
| render timechart

-- Blob property fetch errors
traces
| where message contains "get_blob_properties"
| where message contains "ERROR"
| project timestamp, message
```

---

## Future Enhancements

1. **Incremental Updates**: Only process new/modified blobs since last job
2. **Geospatial Metadata Extraction**: Parse COG headers for spatial extent
3. **Thumbnail Generation**: Create preview images for rasters
4. **Storage Tier Analysis**: Track hot/cool/archive tier usage
5. **Cost Estimation**: Calculate storage costs per container
6. **Duplicate Detection**: Find identical files via content hash
7. **Retention Policy**: Auto-delete inventory records older than N days

---

## Questions for Robert

1. **Task Granularity**: One task per blob means 10,000 blobs = 10,000 tasks. Is this acceptable, or should we batch (e.g., 100 blobs per task)?
   - **Pro (1 task/blob)**: Simple, fine-grained retry, easy debugging
   - **Con (1 task/blob)**: More Service Bus messages, more database rows
   - **Pro (batched)**: Fewer tasks, less overhead
   - **Con (batched)**: Retry entire batch if one blob fails

2. **Default Container**: Should `rmhazuregeobronze` be the default container if not specified?

3. **Filter Persistence**: Should Stage 1 result include which specific files were filtered out (for debugging), or just counts?

4. **Querying Results**: Is using `/api/db/tasks/{JOB_ID}` + PostgreSQL JSONB queries sufficient, or do you want a dedicated filtering endpoint?

---

## Success Criteria

**Container Summary**:
- ✅ Completes in <60 seconds for 10,000 files
- ✅ Accurate statistics (spot-check against Azure Portal)
- ✅ Memory-efficient (streaming, not loading all blobs)
- ✅ Filters work correctly (extension, size, date)

**List Container**:
- ✅ Successfully processes 1,000+ files
- ✅ All task records created (verify count matches file count)
- ✅ Stage 2 tasks complete in parallel
- ✅ Retry logic handles transient failures
- ✅ Task result_data contains correct blob metadata
- ✅ JSONB queries return accurate results

---

## Implementation Checklist

### Phase 1: Container Summary
- [ ] Create `jobs/container_summary.py`
- [ ] Create `services/container_summary.py`
- [ ] Update `jobs/registry.py` (register summarize_container)
- [ ] Test with 10 files
- [ ] Test with 1,000 files
- [ ] Test with 10,000 files
- [ ] Validate filters work correctly

### Phase 2: List Container Contents
- [ ] Create `jobs/container_list.py`
- [ ] Create `services/container_list.py`
- [ ] Update `jobs/registry.py` (register list_container_contents)
- [ ] Test with 10 files
- [ ] Test with 100 files
- [ ] Test with 1,000 files
- [ ] Verify task.result_data contains blob metadata
- [ ] Test JSONB queries on tasks table
- [ ] Validate retry logic works for failed blob fetches

### Documentation & Deployment
- [ ] Update HISTORY.md with completion
- [ ] Commit to master
- [ ] Deploy to Azure

---

**End of Implementation Plan**
