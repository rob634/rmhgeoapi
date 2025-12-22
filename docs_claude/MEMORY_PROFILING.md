# Memory Profiling Data

**Last Updated**: 21 DEC 2025

---

## Overview

This document captures empirical memory profiling data for COG (Cloud Optimized GeoTIFF) processing operations. Data is collected via the checkpoint system in `util_logger.py` and stored in task metadata JSONB for OOM evidence.

---

## OOM Evidence System (21 DEC 2025)

### Implementation

Memory snapshots are now persisted to task metadata in the database before and after heavy operations. If a process OOMs, we have evidence of memory state before the crash.

**Key Function**: `snapshot_memory_to_task()` in `util_logger.py`

**Checkpoints in `raster_cog.py`**:
1. `baseline` - After parameter validation, before any heavy ops
2. `pre_cog_translate` - After file download, before COG creation (critical point)
3. `post_cog_translate` - After COG creation, includes peak memory and processing time

**API Access**: `GET /api/dbadmin/tasks/{job_id}` returns `metadata.memory_snapshots[]`

---

## OOM Frontier Testing (21 DEC 2025)

### Empirical Results - B3 Basic (7.7 GB RAM)

| File | Size | Type | Peak Memory | Multiplier | Mem % | Time | Result |
|------|------|------|-------------|------------|-------|------|--------|
| dctest.tif | 26 MB | RGB | ~1.1 GB | ~42x | 56% | 12s | ✅ Single pass |
| granule R0C0 | 769 MB | uint16 8-band | 2.0 GB | 2.6x | 56% | 31s | ✅ Single pass |
| Luang Prabang DTM | 986 MB | **float32** DEM | **4.6 GB** | **4.7x** | 71% | 74s | ✅ Single pass |
| Maxar R1C2 | 1,126 MB | uint16 8-band | 3.3 GB | 2.9x | 74% | 139s | ✅ Single pass |
| Maxar R2C3 | 1,437 MB | uint16 8-band | **5.6 GB** | 3.9x | **85%** | 180s | ⚠️ **6 retries** |

### Key Finding: Data Type Matters More Than File Size

The float32 DTM (986 MB) used **more memory** than the larger uint16 Maxar file (1,126 MB):
- **float32**: 4.6 GB peak (4.7x multiplier)
- **uint16**: 3.3 GB peak (2.9x multiplier)

### OOM Frontier for B3 Basic

```
Safe Zone:        < 1.1 GB input files (single pass, < 75% mem)
Caution Zone:     1.1 - 1.3 GB files (may require retries)
Danger Zone:      > 1.3 GB files (high retry rate, risk of OOM)
Recommended:      Use process_large_raster_v2 for files > 1.2 GB
```

### Memory Snapshot Examples

**986 MB DTM (float32) - Single Pass Success**:
```
baseline:           201 MB RSS, 40% mem, 4743 MB available
pre_cog_translate:  1,191 MB RSS, 53% mem, 3729 MB available
post_cog_translate: 2,643 MB RSS, 71% mem, 2307 MB available, Peak=4,624 MB
```

**1.44 GB Maxar (uint16) - Required 6 Retries**:
```
Attempt 2 (highest peak):
  baseline:           166 MB RSS, 40% mem
  pre_cog_translate:  1,566 MB RSS, 58% mem
  post_cog_translate: 4,122 MB RSS, 85% mem, Peak=5,612 MB  ← Near OOM!
```

---

## Runtime Environment

### Current Instance (B3 Basic)

| Metric | Value |
|--------|-------|
| CPU Count | 2 vCPUs |
| Total RAM | 7.7 GB |
| Platform | Linux 6.6.104.2-4.azl3 |
| App Name | rmhazuregeoapi |

### Azure App Service Plan Reference

| Plan | RAM | vCPUs | Usable RAM* |
|------|-----|-------|-------------|
| B3 Basic | 7 GB | 2 | ~5.5 GB |
| P1V2 | 3.5 GB | 1 | ~2 GB |
| P2V2 | 7 GB | 2 | ~5.5 GB |
| P3V2 | 14 GB | 4 | ~12 GB |
| EP1 | 3.5 GB | 1 | ~2 GB |
| EP2 | 7 GB | 2 | ~5.5 GB |
| EP3 | 14 GB | 4 | ~12 GB |

*Usable RAM = Total - OS/runtime overhead (~1.5 GB)

---

## Test Results (20 DEC 2025)

### COG Creation Memory Usage

| File | Input (MB) | Peak RSS (MB) | Multiplier | COG Time |
|------|------------|---------------|------------|----------|
| namangan R2C2 | 64 | 601 | **9.4x** | 3.3s |
| namangan R2C1 | 73 | 715 | **9.7x** | 3.5s |
| granule R0C1 | 319 | 1,334 | **4.2x** | 11.9s |
| namangan R1C1 | 778 | 3,070 | **3.9x** | 44.8s |

### Memory Breakdown by Checkpoint

#### Small File (64 MB - namangan R2C2)

| Checkpoint | RSS (MB) | Duration | Delta |
|------------|----------|----------|-------|
| After GDAL open | 239 | - | baseline |
| After metadata extraction | 239 | 2ms | +0 |
| Validation complete | 249 | 130ms | +10 MB |
| After blob download | 291 | - | +42 MB |
| After opening MemoryFile | 292 | 4ms | +1 MB |
| Before cog_translate | 303 | 88ms | +11 MB |
| **After cog_translate** | **601** | **3.3s** | **+298 MB** |
| After reading COG bytes | 592 | 101ms | -9 MB |
| After upload (cleanup) | 600 | 2.5s | +8 MB |

#### Large File (778 MB - namangan R1C1)

| Checkpoint | RSS (MB) | Duration | Delta |
|------------|----------|----------|-------|
| After GDAL open | 273 | - | baseline |
| After metadata extraction | 273 | 4ms | +0 |
| Validation complete | 281 | 113ms | +8 MB |
| After blob download | 1,067 | - | +786 MB |
| After opening MemoryFile | 1,067 | 2ms | +0 |
| Before cog_translate | 1,067 | 12ms | +0 |
| **After cog_translate** | **2,274** | **44.8s** | **+1,207 MB** |
| **After reading COG bytes** | **3,070** | **1.4s** | **+796 MB** |

---

## Pattern Analysis

### Memory Multiplier by File Size

```
Small files (64-73 MB):   ~9.5x multiplier (fixed overhead dominates)
Medium files (319 MB):    ~4.2x multiplier
Large files (778 MB):     ~3.9x multiplier (more efficient per MB)
```

### Empirical Formula

```
Peak_MB ≈ Input_MB × 2.5 + 250 + Output_MB

Where:
- Input_MB × 2.5 accounts for GDAL processing buffers
- 250 MB is fixed overhead (runtime, libraries)
- Output_MB is the COG file read back into memory
```

### Key Observations

1. **cog_translate is the memory spike** - adds 300-1200 MB during GDAL processing
2. **Reading COG bytes adds output size** - full COG loaded for upload
3. **Memory doesn't release immediately** - Python/GDAL caching persists
4. **Smaller files have higher multipliers** - fixed overhead matters more

---

## Configuration

### Current Settings (21 DEC 2025)

```bash
# Azure Portal → Function App → Configuration → Application Settings
RASTER_MAX_FILE_SIZE_MB=2000    # Maximum file size for direct processing (2 GB)
RASTER_SIZE_THRESHOLD_MB=2048   # Small vs large raster cutoff (in defaults.py)

# Debug settings
DEBUG_MODE=true                  # Enable memory checkpoints
DEBUG_LOGGING=true               # Enable debug logs
```

**Note**: Limits can be changed via env vars without redeploying. See `config/raster_config.py` for env var names.

### Safe Limits by Plan (Updated 21 DEC 2025)

| Plan | Total RAM | Usable* | Safe Limit (uint16) | Safe Limit (float32) |
|------|-----------|---------|---------------------|----------------------|
| B3 | 7.7 GB | ~6 GB | **1.2 GB** | **800 MB** |
| EP2/P2V2 | 7 GB | ~5.5 GB | 1.1 GB | 700 MB |
| EP3/P3V2 | 14 GB | ~12 GB | 2.5 GB | 1.5 GB |

*Usable = Total - OS/runtime overhead (~1.5 GB)

**Key Insight**: float32 DEMs require ~60% more memory than uint16 imagery of same file size.

**Recommendation**: Route files > 1.2 GB to `process_large_raster_v2` (chunked processing).

---

## Checkpoint System

### Available Functions

```python
from util_logger import (
    log_memory_checkpoint,      # Log memory/CPU at a point in time
    get_runtime_environment,    # Get instance specs (cached)
    monitored_gdal_operation,   # Context manager with pulse logging
    clear_checkpoint_context,   # Clean up timing data
)
```

### Usage Example

```python
from util_logger import log_memory_checkpoint, monitored_gdal_operation

# Simple checkpoint
log_memory_checkpoint(logger, "After download", context_id=task_id, file_size_mb=64)

# With pulse monitoring for long operations
with monitored_gdal_operation(logger, "cog_translate", context_id=task_id):
    cog_translate(input_path, output_path, profile)
```

### Fields Captured

**Every checkpoint:**
- `process_rss_mb` - Resident Set Size (actual RAM used)
- `process_vms_mb` - Virtual Memory Size
- `process_cpu_percent` - Process CPU usage
- `system_available_mb` - Available system memory
- `system_percent` - System memory usage %
- `system_cpu_percent` - System CPU usage %
- `duration_since_last_ms` - Time since previous checkpoint
- `context_id` - Task/job ID for correlation

**First checkpoint per context (runtime environment):**
- `cpu_count` - Logical CPU count
- `total_ram_gb` - Total system RAM
- `platform` - OS and kernel version
- `azure_site_name` - Function app name
- `azure_instance_id` - Instance identifier

---

## Querying Logs

### Application Insights Query

```kusto
// Memory checkpoints with runtime environment
traces
| where timestamp >= ago(1h)
| where message contains "MEMORY CHECKPOINT"
| extend parsed = parse_json(message)
| extend dims = parsed.customDimensions
| project
    timestamp,
    checkpoint = tostring(dims.checkpoint),
    rss_mb = todouble(dims.process_rss_mb),
    cpu_count = toint(dims.cpu_count),
    total_ram_gb = todouble(dims.total_ram_gb),
    context_id = tostring(dims.context_id)
| order by timestamp asc
```

### CLI Query Script

```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains 'MEMORY CHECKPOINT' | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
```

---

## Future Enhancements

### Completed (21 DEC 2025)

- [x] Add peak memory tracking via `resource.getrusage()` ✅
- [x] Persist memory snapshots to task metadata JSONB ✅
- [x] Add `/api/health` hardware report ✅
- [x] Profile multi-band (8-band WorldView) vs single-band (DEM) ✅
- [x] Establish OOM frontier empirically ✅

### Pending Integration

- [ ] Wire `monitored_gdal_operation` pulse worker for continuous peak tracking
- [ ] Add memory logging to `raster_validation.py`
- [ ] Add memory logging to other high-memory handlers (vector, H3)
- [ ] Implement chunk size calculator based on runtime environment + data type

### Additional Data Needed

- [ ] Profile with reprojection (EPSG:4326 → EPSG:3857)
- [ ] Profile polar/high-latitude data (expected higher multipliers)
- [ ] Test concurrent task memory interaction
- [ ] Profile float64 data (rare but exists)

---

## References

- `util_logger.py` - Checkpoint implementation
- `services/raster_cog.py` - COG creation with checkpoints
- `services/raster_validation.py` - Validation with checkpoints
- `config/raster_config.py` - Size limit configuration
