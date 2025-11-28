# DEBUG_MODE Implementation Plan
**Date**: 8 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ACTIVE IMPLEMENTATION 🚧
**Purpose**: Extensible debug framework controlled by single env var

---

## 📋 Overview

Implement `DEBUG_MODE` environment variable to control verbose diagnostic features across the entire application. Initially focused on memory logging, but architected for future expansion to include timing, payload inspection, SQL queries, and more.

### Design Philosophy

**Single switch, progressive enhancement**:
- ✅ `DEBUG_MODE=false` (default) → Production-optimized, minimal overhead
- ✅ `DEBUG_MODE=true` → Comprehensive diagnostics for troubleshooting
- ✅ Easy to toggle without code deployment
- ✅ Extensible architecture for future debug features

---

## 🎯 Phase 1: Memory Logging (Current Focus)

### Objective
Track process and system memory usage at key checkpoints in memory-intensive operations to diagnose OOM issues and timeout root causes.

### Implementation Tasks

#### Task 1.1: Update Dependencies
**File**: `requirements.txt`

**Changes**:
```
psutil>=5.9.0
```

**Rationale**: `psutil` provides cross-platform process and system memory monitoring, including C library allocations (GDAL, rasterio).

---

#### Task 1.2: Add DEBUG_MODE Configuration
**File**: `config.py`

**Location**: After logging configuration section (~line 560)

**Changes**:
```python
# ========================================================================
# Debug Configuration
# ========================================================================

debug_mode: bool = Field(
    default=False,
    description="Enable debug mode for verbose diagnostics. "
                "WARNING: Increases logging overhead and log volume. "
                "Features enabled: memory tracking, detailed timing, payload logging.",
    examples=[True, False]
)
```

**Environment Variable**: `DEBUG_MODE=true` or `DEBUG_MODE=false`

**Validation**: Must handle string "true"/"false" from env vars (Pydantic auto-converts)

---

#### Task 1.3: Enhance Logger with Memory Tracking
**File**: `util_logger.py`

**Changes**:

1. **Add lazy psutil import** (top of file, after existing imports):
```python
# Lazy import for debug features (avoid failure if psutil missing)
def _lazy_import_psutil():
    """Lazy import psutil for memory tracking."""
    try:
        import psutil
        import os
        return psutil, os
    except ImportError:
        return None, None
```

2. **Add memory stats method to logger class** (after `__init__`):
```python
def _get_memory_stats(self) -> Optional[dict]:
    """
    Get current process and system memory statistics.

    Only executes if DEBUG_MODE=true in config.

    Returns:
        dict with memory stats or None if debug disabled
        {
            'process_rss_mb': float,      # Resident Set Size (actual RAM)
            'process_vms_mb': float,      # Virtual Memory Size
            'system_available_mb': float, # Available system memory
            'system_percent': float       # System memory usage %
        }
    """
    # Check if debug mode enabled
    from config import get_config
    config = get_config()

    if not config.debug_mode:
        return None

    # Lazy import psutil
    psutil_module, os_module = _lazy_import_psutil()
    if not psutil_module:
        return None

    try:
        process = psutil_module.Process(os_module.getpid())
        mem_info = process.memory_info()
        system_mem = psutil_module.virtual_memory()

        return {
            'process_rss_mb': round(mem_info.rss / (1024**2), 1),
            'process_vms_mb': round(mem_info.vms / (1024**2), 1),
            'system_available_mb': round(system_mem.available / (1024**2), 1),
            'system_percent': round(system_mem.percent, 1)
        }
    except Exception as e:
        # Fail silently - debug feature shouldn't break production
        return None
```

3. **Add memory checkpoint convenience method**:
```python
def memory_checkpoint(self, checkpoint_name: str, **extra_fields):
    """
    Log a memory usage checkpoint.

    Only logs if DEBUG_MODE=true. Otherwise, this is a no-op.

    Args:
        checkpoint_name: Descriptive name for this checkpoint
        **extra_fields: Additional context fields

    Example:
        logger.memory_checkpoint("After blob download", file_size_mb=815)
    """
    mem_stats = self._get_memory_stats()
    if mem_stats:
        self.info(
            f"📊 MEMORY CHECKPOINT: {checkpoint_name}",
            checkpoint=checkpoint_name,
            **mem_stats,
            **extra_fields
        )
```

**Decision**: Using explicit checkpoints only (not auto-injection into every log line) to reduce noise.

---

#### Task 1.4: Add Memory Checkpoints to COG Service
**File**: `services/raster_cog.py`

**Checkpoint Locations**:

1. **After blob download** (line ~279):
```python
input_size_mb = len(input_blob_bytes) / (1024 * 1024)
logger.info(f"   Downloaded input tile: {input_size_mb:.2f} MB")
logger.memory_checkpoint("After blob download", input_size_mb=input_size_mb)
```

2. **After opening MemoryFile** (line ~329):
```python
with MemoryFile(input_blob_bytes) as input_memfile:
    logger.memory_checkpoint("After opening MemoryFile")
    with input_memfile.open() as src:
```

3. **Before cog_translate** (line ~358):
```python
logger.info(f"   Overview resampling (for cog_translate): {overview_resampling_name}")
logger.memory_checkpoint("Before cog_translate",
                         in_memory=in_memory,
                         compression=compression)
```

4. **After cog_translate** (line ~381):
```python
elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
logger.info(f"✅ STEP 5: COG created successfully in memory")
logger.memory_checkpoint("After cog_translate", processing_time_seconds=elapsed_time)
```

5. **After reading COG bytes** (line ~400):
```python
output_size_mb = len(cog_bytes) / (1024 * 1024)
logger.info(f"   Read COG from memory: {output_size_mb:.2f} MB")
logger.memory_checkpoint("After reading COG bytes", output_size_mb=output_size_mb)
```

6. **After upload** (line ~421):
```python
logger.info(f"✅ STEP 6: COG uploaded successfully")
logger.memory_checkpoint("After upload (cleanup)")
```

**Total**: 6 checkpoints in critical path

---

#### Task 1.5: Add Memory Checkpoints to Validation Service
**File**: `services/raster_validation.py`

**Checkpoint Locations**:

1. **After blob download** (find download location):
```python
logger.memory_checkpoint("After blob download", blob_size_mb=blob_size_mb)
```

2. **After GDAL dataset open**:
```python
logger.memory_checkpoint("After GDAL open")
```

3. **After reading metadata**:
```python
logger.memory_checkpoint("After metadata extraction")
```

4. **After validation complete**:
```python
logger.memory_checkpoint("Validation complete")
```

**Total**: 4 checkpoints

---

#### Task 1.6: Add Memory Checkpoints to MosaicJSON Service
**File**: `services/raster_mosaicjson.py`

**Checkpoint Locations**:

1. **Before reading COG list**:
```python
logger.memory_checkpoint("Before processing COG list", cog_count=len(cog_paths))
```

2. **After creating mosaic**:
```python
logger.memory_checkpoint("After mosaic creation")
```

3. **After upload**:
```python
logger.memory_checkpoint("After mosaic upload")
```

**Total**: 3 checkpoints

---

#### Task 1.7: Update Local Development Config
**File**: `local.settings.json`

**Add**:
```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "DEBUG_MODE": "true"
  }
}
```

**Purpose**: Enable debug mode for local testing

---

### Deployment & Testing

#### Step 1: Local Testing
```bash
# Ensure DEBUG_MODE=true in local.settings.json
func start

# Test with small file
curl -X POST "http://localhost:7071/api/jobs/submit/process_raster" \
  -H "Content-Type: application/json" \
  -d '{"container_name":"rmhazuregeobronze","blob_name":"test_small.tif"}'

# Check logs for memory checkpoints
```

#### Step 2: Azure Deployment
```bash
# Deploy code
func azure functionapp publish rmhgeoapibeta --python --build remote

# Enable DEBUG_MODE in Azure
az functionapp config appsettings set \
  --name rmhgeoapibeta \
  --resource-group rmhazure_rg \
  --settings DEBUG_MODE=true

# Verify setting
az functionapp config appsettings list \
  --name rmhgeoapibeta \
  --resource-group rmhazure_rg \
  --query "[?name=='DEBUG_MODE'].value" -o tsv
```

#### Step 3: Test with R1C1 815MB File
```bash
# Submit test job
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster" \
  -H "Content-Type: application/json" \
  -d '{"container_name":"rmhazuregeobronze","blob_name":"namangan/namangan14aug2019_R1C1cog.tif","collection_id":"debug_test"}'

# Monitor with Application Insights
# (Use script from claude_log_access.md)
```

#### Step 4: Analyze Memory Logs
**KQL Query**:
```kql
traces
| where timestamp >= ago(1h)
| where message contains "MEMORY CHECKPOINT"
| project timestamp, checkpoint, process_rss_mb, system_available_mb, system_percent
| order by timestamp asc
```

**Expected Result**: See memory spike from ~850MB to ~2400MB during cog_translate

#### Step 5: Disable After Debugging
```bash
# Disable DEBUG_MODE for production
az functionapp config appsettings set \
  --name rmhgeoapibeta \
  --resource-group rmhazure_rg \
  --settings DEBUG_MODE=false
```

---

## 🚀 Phase 2: Future Debug Features (Extensible Design)

### Planned Enhancements

#### 2.1: Timing Instrumentation
**When `DEBUG_MODE=true`**:
- Log execution time for each major operation
- Track cumulative time per stage
- Identify slow operations

**Implementation**:
```python
def timing_checkpoint(self, operation_name: str, start_time: datetime):
    """Log operation timing if DEBUG_MODE enabled."""
    from config import get_config
    config = get_config()

    if not config.debug_mode:
        return

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    self.info(
        f"⏱️ TIMING: {operation_name}",
        operation=operation_name,
        elapsed_seconds=elapsed
    )
```

---

#### 2.2: Payload Logging
**When `DEBUG_MODE=true`**:
- Log full job parameters (JSON)
- Log task parameters before execution
- Log result payloads (truncated if >10KB)

**Implementation**:
```python
def log_payload(self, payload_name: str, payload: dict, max_size_kb: int = 10):
    """Log structured payload if DEBUG_MODE enabled."""
    from config import get_config
    import json
    config = get_config()

    if not config.debug_mode:
        return

    payload_json = json.dumps(payload)
    if len(payload_json) > max_size_kb * 1024:
        payload_json = payload_json[:max_size_kb * 1024] + "...[TRUNCATED]"

    self.info(
        f"📦 PAYLOAD: {payload_name}",
        payload_name=payload_name,
        payload=payload_json
    )
```

---

#### 2.3: SQL Query Logging
**When `DEBUG_MODE=true`**:
- Log all SQL queries with parameters
- Log query execution time
- Log row counts returned

**Implementation**:
```python
# In database infrastructure layer
from config import get_config
config = get_config()

if config.debug_mode:
    logger.info(f"🗄️ SQL: {query}", query=query, params=params)
```

---

#### 2.4: HTTP Request/Response Logging
**When `DEBUG_MODE=true`**:
- Log all HTTP requests to external services
- Log response status codes and body sizes
- Track external API latency

---

#### 2.5: GDAL Debug Output
**When `DEBUG_MODE=true`**:
- Enable GDAL CPL_DEBUG
- Capture GDAL warnings and errors
- Log GDAL operation details

**Implementation**:
```python
from osgeo import gdal
from config import get_config

config = get_config()
if config.debug_mode:
    gdal.SetConfigOption('CPL_DEBUG', 'ON')
    gdal.SetConfigOption('CPL_LOG_ERRORS', 'ON')
```

---

#### 2.6: Service Bus Message Inspection
**When `DEBUG_MODE=true`**:
- Log message IDs, delivery count, enqueued time
- Log message body (truncated)
- Track message processing time

---

### Multi-Level Debug Mode (Future)

**Proposed Levels**:
```python
class DebugLevel(str, Enum):
    OFF = "off"           # Production (default)
    BASIC = "basic"       # Memory + timing only
    VERBOSE = "verbose"   # + payloads + SQL
    EXTREME = "extreme"   # + HTTP + GDAL + Service Bus details
```

**Config**:
```python
debug_level: DebugLevel = Field(
    default=DebugLevel.OFF,
    description="Debug verbosity level"
)
```

**Usage**:
```python
# In logger
from config import get_config, DebugLevel
config = get_config()

if config.debug_level >= DebugLevel.BASIC:
    # Memory checkpoints

if config.debug_level >= DebugLevel.VERBOSE:
    # Payload logging

if config.debug_level >= DebugLevel.EXTREME:
    # Everything
```

---

## 📊 Expected Log Output

### Production Mode (`DEBUG_MODE=false`)
```json
{
  "timestamp": "2025-11-08T03:15:42Z",
  "level": "INFO",
  "component": "create_cog",
  "message": "Downloaded input tile: 815.5 MB",
  "job_id": "233fc984...",
  "correlation_id": "abc123"
}
```

**Characteristics**:
- ✅ Clean, concise logs
- ✅ No memory stats
- ✅ No psutil overhead
- ✅ Minimal Application Insights cost

---

### Debug Mode (`DEBUG_MODE=true`)
```json
{
  "timestamp": "2025-11-08T03:15:42Z",
  "level": "INFO",
  "component": "create_cog",
  "message": "📊 MEMORY CHECKPOINT: After blob download",
  "checkpoint": "After blob download",
  "input_size_mb": 815.5,
  "process_rss_mb": 850.3,
  "process_vms_mb": 1024.7,
  "system_available_mb": 2600.1,
  "system_percent": 24.5,
  "job_id": "233fc984...",
  "correlation_id": "abc123"
}
```

**Characteristics**:
- ✅ Detailed memory telemetry
- ✅ Process and system stats
- ✅ Named checkpoints for analysis
- ✅ Extra context fields
- ⚠️ Higher log volume
- ⚠️ Higher Application Insights cost

---

## 🔍 Troubleshooting with DEBUG_MODE

### Use Case 1: OOM Investigation (Current)

**Problem**: Tasks timing out during COG processing

**Solution**:
1. Enable `DEBUG_MODE=true`
2. Resubmit job
3. Query Application Insights for memory checkpoints
4. Identify exact operation causing memory spike

**KQL Query**:
```kql
traces
| where timestamp >= ago(1h)
| where message contains "MEMORY CHECKPOINT"
| where customDimensions.job_id == "233fc984..."
| project timestamp, checkpoint, process_rss_mb, system_available_mb
| order by timestamp asc
```

**Analysis**:
```
After blob download:      850 MB  (baseline)
Before cog_translate:     900 MB  (stable)
After cog_translate:    2,400 MB  (🔥 SPIKE!)
After reading COG:      2,450 MB  (peak)
After upload:             100 MB  (cleanup)
```

**Conclusion**: cog_translate causes 1,500MB spike → need disk-based processing

---

### Use Case 2: Performance Profiling (Future)

**Problem**: Jobs slower than expected

**Solution**:
1. Enable `DEBUG_MODE=true`
2. Add timing checkpoints
3. Identify bottlenecks

---

### Use Case 3: Data Pipeline Debugging (Future)

**Problem**: Task parameters incorrect or missing

**Solution**:
1. Enable `DEBUG_MODE=true`
2. Log payloads at stage boundaries
3. Trace data flow

---

## 📁 Files Modified

### Phase 1 (Memory Logging)
1. ✅ `requirements.txt` - Add psutil
2. ✅ `config.py` - Add debug_mode field
3. ✅ `util_logger.py` - Add memory tracking methods
4. ✅ `services/raster_cog.py` - Add 6 checkpoints
5. ✅ `services/raster_validation.py` - Add 4 checkpoints
6. ✅ `services/raster_mosaicjson.py` - Add 3 checkpoints
7. ✅ `local.settings.json` - Add DEBUG_MODE=true
8. ✅ `docs_claude/DEBUG_MODE_IMPLEMENTATION_PLAN.md` - This document

**Total**: 7 modified, 1 new

---

## ✅ Success Criteria

### Phase 1 Complete When:
- ✅ `DEBUG_MODE=false` → No memory stats in logs, zero psutil overhead
- ✅ `DEBUG_MODE=true` → Memory checkpoints appear in Application Insights
- ✅ R1C1 test job shows memory spike during cog_translate
- ✅ Can identify exact operation causing OOM
- ✅ Can toggle debug mode without redeployment
- ✅ No production impact when disabled

---

## 🎯 Next Steps After Phase 1

1. **Analyze R1C1 memory telemetry** - Confirm OOM root cause
2. **Implement adaptive memory threshold** - Switch to disk-based for large files
3. **Test fix with DEBUG_MODE enabled** - Verify memory stays under limit
4. **Disable DEBUG_MODE** - Return to production mode
5. **Plan Phase 2** - Timing instrumentation next priority

---

## 🚨 Production Safety

### Safeguards Built In:
- ✅ **Default OFF** - `debug_mode=False` in config
- ✅ **Lazy imports** - psutil import only when needed
- ✅ **Silent failures** - Debug features never break production code
- ✅ **Explicit checkpoints** - Only log where explicitly called
- ✅ **Easy disable** - Single env var controls everything
- ✅ **No code changes** - Toggle via Azure Portal settings

### Cost Considerations:
- **Application Insights**: More log volume = higher ingestion cost
- **Recommendation**: Only enable for troubleshooting, disable after
- **Estimate**: DEBUG_MODE=true increases log volume by ~3x for affected services

---

## 📖 Related Documentation

- `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md` - KQL queries for log analysis
- `docs_claude/claude_log_access.md` - How to access logs
- `CLAUDE.md` - Project overview and context
- `config.py` - Configuration reference

---

**END OF DEBUG_MODE IMPLEMENTATION PLAN**
