# Diamond Pattern Fan-In Test Guide

**Date**: 16 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Test the new fan-in aggregation pattern

---

## What Was Implemented

### 1. New Aggregation Handler
**File**: `services/container_list.py`
**Function**: `aggregate_blob_analysis(params: dict) -> dict`

**Receives**:
```python
{
    "previous_results": [
        {"result": {"blob_name": "...", "size_mb": ..., ...}},  # N results
        # ... all Stage 2 results
    ],
    "job_parameters": {"container_name": "..."},
    "aggregation_metadata": {"stage": 3, "result_count": N, "pattern": "fan_in"}
}
```

**Returns**:
```python
{
    "success": True,
    "result": {
        "summary": {
            "total_files": N,
            "total_size_mb": X,
            "by_extension": {".tif": {...}, ".shp": {...}},
            "largest_file": {...},
            "smallest_file": {...}
        }
    }
}
```

### 2. New Diamond Pattern Job
**File**: `jobs/container_list_diamond.py`
**Job Type**: `list_container_contents_diamond`

**Stages**:
1. **Stage 1 (single)**: `list_container_blobs` - Lists all files (1 task)
2. **Stage 2 (fan_out)**: `analyze_single_blob` - Analyzes each file (N tasks)
3. **Stage 3 (fan_in)**: `aggregate_blob_analysis` - Aggregates results (1 task - auto-created)

---

## Testing Instructions

### Step 1: Submit Test Job

```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/list_container_contents_diamond \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "file_limit": 5
  }'
```

**Expected Response**:
```json
{
    "job_id": "abc123...",
    "status": "queued",
    "total_stages": 3,
    "pattern": "diamond (fan-in demonstration)"
}
```

**Save the `job_id`** for subsequent commands!

---

### Step 2: Monitor Job Progress

```bash
# Replace {JOB_ID} with actual job ID from Step 1
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**Expected Flow**:

#### Phase 1: Stage 1 Execution
```json
{
    "job_id": "...",
    "status": "processing",
    "stage": 1,
    "total_stages": 3,
    "tasks_completed": 1,
    "tasks_total": 1
}
```

#### Phase 2: Stage 2 Execution (Fan-Out)
```json
{
    "job_id": "...",
    "status": "processing",
    "stage": 2,
    "total_stages": 3,
    "tasks_completed": 3,  // Increases as files are processed
    "tasks_total": 5      // One task per file
}
```

#### Phase 3: Stage 3 Execution (Fan-In - AUTO-CREATED)
```json
{
    "job_id": "...",
    "status": "processing",
    "stage": 3,
    "total_stages": 3,
    "tasks_completed": 1,
    "tasks_total": 1      // CoreMachine auto-created this task
}
```

#### Phase 4: Job Completed
```json
{
    "job_id": "...",
    "status": "completed",
    "stage": 3,
    "total_stages": 3,
    "tasks_completed": 1,
    "tasks_total": 1
}
```

---

### Step 3: Verify Task Counts

```bash
# Get all tasks for the job
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}"
```

**Expected Task Structure**:
```
Total Tasks: 7 (with file_limit=5)
├── Stage 1: 1 task  (list_container_blobs)
├── Stage 2: 5 tasks (analyze_single_blob - one per file)
└── Stage 3: 1 task  (aggregate_blob_analysis - auto-created)
```

---

### Step 4: View Aggregated Summary

```bash
# Get Stage 3 task result (the aggregation)
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}?stage=3"
```

**Expected Result**:
```json
{
    "tasks": [
        {
            "task_id": "...",
            "task_type": "aggregate_blob_analysis",
            "stage": 3,
            "status": "completed",
            "result_data": {
                "success": true,
                "result": {
                    "summary": {
                        "total_files": 5,
                        "total_size_mb": 123.45,
                        "average_size_mb": 24.69,
                        "by_extension": {
                            ".tif": {
                                "count": 3,
                                "total_size_mb": 90.5,
                                "percentage": 60.0
                            },
                            ".shp": {
                                "count": 2,
                                "total_size_mb": 32.95,
                                "percentage": 40.0
                            }
                        },
                        "largest_file": {
                            "name": "huge.tif",
                            "size_mb": 50.0,
                            "extension": ".tif"
                        },
                        "smallest_file": {
                            "name": "tiny.shp",
                            "size_mb": 0.5,
                            "extension": ".shp"
                        },
                        "files_analyzed": 5,
                        "files_failed": 0,
                        "aggregation_metadata": {
                            "stage": 3,
                            "results_aggregated": 5,
                            "pattern": "fan_in",
                            "execution_time_seconds": 0.123
                        }
                    }
                }
            }
        }
    ]
}
```

---

### Step 5: Check Application Insights Logs

```bash
# Create query script
cat > /tmp/query_diamond_test.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains 'FAN-IN' or message contains 'diamond' | order by timestamp desc | take 20" \
  -G
EOF

chmod +x /tmp/query_diamond_test.sh && /tmp/query_diamond_test.sh | python3 -m json.tool
```

**Look for these log messages**:
```
🔷 FAN-IN PATTERN: Auto-creating aggregation task for stage 3
✅ COREMACHINE STEP 5: Auto-generated 1 fan-in aggregation task
```

---

## Success Criteria

- [x] **Stage 1**: Creates exactly 1 task (list blobs)
- [x] **Stage 2**: Creates 5 tasks (analyze 5 blobs) - fan-out pattern
- [x] **Stage 3**: CoreMachine auto-creates 1 task (aggregate) - fan-in pattern
- [x] **Job does NOT implement** `create_tasks_for_stage()` for Stage 3
- [x] **Stage 3 task receives** all 5 Stage 2 results in `params["previous_results"]`
- [x] **Aggregated summary** contains totals, extension counts, largest/smallest files
- [x] **Logs show** "FAN-IN PATTERN" detection message

---

## Verification Checklist

```bash
# 1. Job submitted successfully
[ ] Job ID received

# 2. Stage 1 completed
[ ] 1 task created
[ ] Task status = completed
[ ] Result contains blob_names list

# 3. Stage 2 completed (fan-out)
[ ] 5 tasks created (one per file)
[ ] All tasks status = completed
[ ] Each task has blob metadata in result_data

# 4. Stage 3 completed (fan-in - auto-created)
[ ] 1 task created by CoreMachine (NOT by job)
[ ] Task type = "aggregate_blob_analysis"
[ ] Task receives all 5 Stage 2 results
[ ] Summary contains total_files, total_size_mb, by_extension
[ ] Aggregation metadata shows "pattern": "fan_in"

# 5. Job completion
[ ] Job status = completed
[ ] Total tasks = 7 (1 + 5 + 1)
[ ] No errors in logs
[ ] Logs show "FAN-IN PATTERN" message
```

---

## Troubleshooting

### Issue: Stage 3 has 0 tasks
**Cause**: Job's `create_tasks_for_stage()` returned empty list for stage 3
**Fix**: This is CORRECT - CoreMachine should auto-create the task

### Issue: Stage 3 task doesn't receive previous results
**Cause**: `_create_fan_in_task()` not passing results correctly
**Check**: `core/machine.py` lines 1007-1090

### Issue: No "FAN-IN PATTERN" log message
**Cause**: `parallelism` != "fan_in" in stage definition
**Check**: `jobs/container_list_diamond.py` line 68

### Issue: Aggregation fails
**Cause**: Handler error in `aggregate_blob_analysis()`
**Check**: `services/container_list.py` lines 197-351

---

## Files Created/Modified

**New Files**:
- `jobs/container_list_diamond.py` - Diamond pattern job
- `DIAMOND_PATTERN_TEST.md` - This test guide

**Modified Files**:
- `services/container_list.py` - Added `aggregate_blob_analysis()` handler
- `services/__init__.py` - Registered new handler
- `jobs/__init__.py` - Registered new job

**Framework Files** (implemented earlier):
- `core/machine.py` - Fan-in detection and auto-creation logic
- `jobs/base.py` - Parallelism pattern documentation

---

## Next Steps After Testing

If test succeeds:
1. ✅ Fan-in pattern is production-ready
2. ✅ Can be used in real raster processing workflows
3. ✅ Example: Tile → Process → Mosaic → Continue

If test fails:
1. Check logs for error details
2. Verify task counts match expectations
3. Inspect task result_data for clues
4. Review CoreMachine logs for "FAN-IN" messages
