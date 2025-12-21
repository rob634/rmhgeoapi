# Memory Profiling Data

**Last Updated**: 20 DEC 2025

---

## Overview

This document captures empirical memory profiling data for COG (Cloud Optimized GeoTIFF) processing operations. Data is collected via the checkpoint system in `util_logger.py`.

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

### Current Settings

```bash
RASTER_MAX_FILE_SIZE_MB=800     # Maximum file size for direct processing
RASTER_SIZE_THRESHOLD_MB=800    # Small vs large raster cutoff (default)
DEBUG_MODE=true                  # Enable memory checkpoints
DEBUG_LOGGING=true               # Enable debug logs
```

### Safe Limits by Plan

| Plan | Usable RAM | Conservative (10x) | Moderate (5x) | Observed (4x) |
|------|------------|-------------------|---------------|---------------|
| B3 | 5.5 GB | 550 MB | 1.1 GB | 1.4 GB |
| EP2/P2V2 | 5.5 GB | 550 MB | 1.1 GB | 1.4 GB |
| EP3/P3V2 | 12 GB | 1.2 GB | 2.4 GB | 3.0 GB |

**Current limit of 800 MB is safe for B3 tier** (778 MB file used 3 GB peak, within 5.5 GB usable).

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

### Pending Integration

- [ ] Wire `monitored_gdal_operation` into `raster_cog.py` for pulse monitoring during cog_translate
- [ ] Add peak memory tracking (requires background sampling thread)
- [ ] Implement chunk size calculator based on runtime environment

### Additional Data Needed

- [ ] Profile with reprojection (EPSG:4326 → EPSG:3857)
- [ ] Profile polar/high-latitude data (expected higher multipliers)
- [ ] Profile multi-band vs single-band rasters
- [ ] Test concurrent task memory interaction

---

## References

- `util_logger.py` - Checkpoint implementation
- `services/raster_cog.py` - COG creation with checkpoints
- `services/raster_validation.py` - Validation with checkpoints
- `config/raster_config.py` - Size limit configuration
