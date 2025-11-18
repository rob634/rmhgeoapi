# Output GeoTIFF Naming and Container Convention

**Author**: Robert and Geospatial Claude Legion
**Date**: 11 NOV 2025
**Status**: Current Implementation Documentation

---

## 🎯 Quick Answer

### Output Container
**Hardcoded in Stage 2** (`services/raster_cog.py` line 270):
```python
silver_container = config_obj.storage.silver.get_container('cogs')
```
**Result**: Always uses silver COG container from config (not user-configurable per job)

### Output Filename
**Determined in Stage 2 setup** (`jobs/process_raster.py` lines 527-540):
```python
# Extract filename from input path
filename = blob_name.split('/')[-1]  # e.g., "dctest.tif"

# Generate output filename (replace .tif with _cog.tif)
if filename.lower().endswith('.tif'):
    output_filename = f"{filename[:-4]}_cog.tif"  # "dctest_cog.tif"
else:
    output_filename = f"{filename}_cog.tif"

# Prepend output folder if specified
if output_folder:
    output_blob_name = f"{output_folder}/{output_filename}"  # "myfolder/dctest_cog.tif"
else:
    output_blob_name = output_filename  # "dctest_cog.tif" (root)
```

---

## 📋 Detailed Breakdown

### Stage 2 Task Creation (Job Controller)

**Location**: `jobs/process_raster.py` → `create_tasks_for_stage(stage=2)` (lines 501-561)

#### Input Parameters Used:
- `job_params['blob_name']` - Original input blob path (e.g., "dctest.tif" or "path/to/dctest.tif")
- `job_params['output_folder']` - Optional output folder (default: None)

#### Filename Generation Logic:

```python
# Step 1: Extract filename from input path (ignore directory structure)
blob_name = job_params['blob_name']  # "path/to/dctest.tif"
filename = blob_name.split('/')[-1]   # "dctest.tif"

# Step 2: Generate COG filename (append _cog before extension)
if filename.lower().endswith('.tif'):
    output_filename = f"{filename[:-4]}_cog.tif"  # "dctest_cog.tif"
else:
    output_filename = f"{filename}_cog.tif"       # "somefile_cog.tif"

# Step 3: Apply output folder if specified
output_folder = job_params.get('output_folder')
if output_folder:
    output_blob_name = f"{output_folder}/{output_filename}"  # "myfolder/dctest_cog.tif"
else:
    output_blob_name = output_filename  # "dctest_cog.tif" (write to container root)
```

#### Examples:

| Input blob_name | output_folder | Output blob_name |
|----------------|---------------|------------------|
| `dctest.tif` | None | `dctest_cog.tif` |
| `dctest.tif` | `"processed"` | `processed/dctest_cog.tif` |
| `namangan/tile_001.tif` | None | `tile_001_cog.tif` |
| `namangan/tile_001.tif` | `"namangan_output"` | `namangan_output/tile_001_cog.tif` |
| `somefile.jpg` | None | `somefile.jpg_cog.tif` |

---

### Stage 2 Task Execution (COG Handler)

**Location**: `services/raster_cog.py` → `create_cog()` (lines 60-500+)

#### Container Determination:

```python
# STEP 3: Get silver container from config (line 268-270)
from config import get_config
config_obj = get_config()
silver_container = config_obj.storage.silver.get_container('cogs')
# Result: Hardcoded to silver COGs container (not user-configurable)
```

#### Upload Operation:

```python
# STEP 6: Upload COG to silver container (line 441-448)
blob_repo.write_blob(
    container=silver_container,  # Silver COGs container from config
    blob_path=output_blob_name,  # From Stage 2 task parameters
    data=cog_bytes,
    content_type='image/tiff',
    overwrite=True
)
```

#### Return Result:

```python
# Handler returns (line 468-472)
{
    "success": True,
    "result": {
        "cog_blob": output_blob_name,        # e.g., "dctest_cog.tif"
        "cog_container": silver_container,   # e.g., "silver-cogs"
        "cog_tier": "analysis",
        "storage_tier": "hot",
        ...
    }
}
```

---

## 🔧 Configuration Source

### Silver Container Lookup

**Config path**: `config.storage.silver.get_container('cogs')`

**Implementation** (`config.py`):
```python
class SilverStorageConfig:
    def get_container(self, data_type: str) -> str:
        """Get silver container name by data type"""
        mapping = {
            'cogs': self.cogs_container,
            'tiles': self.tiles_container,
            'mosaicjson': self.mosaicjson_container
        }
        return mapping.get(data_type, self.cogs_container)
```

**Environment Variable**: `SILVER_COGS_CONTAINER` (default: "silver-cogs")

---

## 📊 Full Processing Flow Example

### Example Job Submission:

```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "output_folder": "processed"
  }'
```

### Processing Flow:

```
┌─────────────────────────────────────────────────────────────┐
│ INPUT                                                       │
├─────────────────────────────────────────────────────────────┤
│ Container: rmhazuregeobronze (Bronze - user input)        │
│ Blob:      dctest.tif                                       │
│ Folder:    processed (optional parameter)                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1: VALIDATION                                         │
├─────────────────────────────────────────────────────────────┤
│ Task Type: validate_raster                                  │
│ Handler:   services/raster_validation.py                    │
│ Input:     rmhazuregeobronze/dctest.tif                    │
│ Output:    Validation metadata (CRS, type, etc.)           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2: COG CREATION (Filename determined here)           │
├─────────────────────────────────────────────────────────────┤
│ Controller: jobs/process_raster.py (lines 527-540)         │
│                                                             │
│ 1. Extract filename from blob_name:                        │
│    "dctest.tif".split('/')[-1] = "dctest.tif"             │
│                                                             │
│ 2. Generate COG filename:                                  │
│    "dctest"[:-4] + "_cog.tif" = "dctest_cog.tif"         │
│                                                             │
│ 3. Apply output_folder:                                    │
│    "processed" + "/" + "dctest_cog.tif"                   │
│    = "processed/dctest_cog.tif"                           │
│                                                             │
│ 4. Task created with output_blob_name parameter           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2: COG CREATION (Container determined here)          │
├─────────────────────────────────────────────────────────────┤
│ Handler:   services/raster_cog.py (line 270)               │
│                                                             │
│ 1. Get silver container from config:                       │
│    config.storage.silver.get_container('cogs')            │
│    = "silver-cogs" (from env var SILVER_COGS_CONTAINER)   │
│                                                             │
│ 2. Download from bronze:                                   │
│    rmhazuregeobronze/dctest.tif                           │
│                                                             │
│ 3. Create COG in memory (reproject + optimize)            │
│                                                             │
│ 4. Upload to silver:                                       │
│    silver-cogs/processed/dctest_cog.tif                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ OUTPUT                                                      │
├─────────────────────────────────────────────────────────────┤
│ Container: silver-cogs (Silver - from config)              │
│ Blob:      processed/dctest_cog.tif                        │
│                                                             │
│ Result metadata:                                            │
│ {                                                           │
│   "cog_blob": "processed/dctest_cog.tif",                  │
│   "cog_container": "silver-cogs",                          │
│   "cog_tier": "analysis",                                  │
│   "storage_tier": "hot"                                    │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔍 Key Observations

### 1. Container is NOT User-Configurable

**Current Implementation**:
- Output container is **hardcoded** to silver COGs container from config
- No `output_container` parameter in job submission
- Always writes to: `config.storage.silver.get_container('cogs')`

**Why**:
- Enforces storage tier architecture (Bronze → Silver → Gold)
- Prevents users from accidentally writing to wrong containers
- Consistent output location for downstream processing

### 2. Filename Generation is Predictable

**Pattern**: `{original_filename}_cog.tif`

**Predictability**:
- Input: `dctest.tif` → Output: `dctest_cog.tif` ✅
- Input: `path/to/file.tif` → Output: `file_cog.tif` (ignores path) ✅
- Input: `noextension` → Output: `noextension_cog.tif` ✅

**Collision Risk**: If you process same file twice without output_folder, it overwrites (overwrite=True)

### 3. Output Folder Provides Organization

**Use Cases**:
- `output_folder: "project_alpha"` → Group all project outputs
- `output_folder: "2025-11-11"` → Organize by date
- `output_folder: "rgb_tiles"` → Organize by type
- `output_folder: null` → Write to container root (flat structure)

**Benefit**: Prevents container clutter for large batch jobs

---

## ⚙️ How to Change Output Container (If Needed)

### Option 1: Change Config Environment Variable

```bash
# Set different silver COGs container
export SILVER_COGS_CONTAINER="my-custom-cogs-container"
```

### Option 2: Add output_container Job Parameter (Future Enhancement)

**Would require changes to**:
1. `jobs/process_raster.py` → Accept `output_container` parameter
2. `jobs/process_raster.py` → Pass to Stage 2 task parameters
3. `services/raster_cog.py` → Use `params.get('output_container')` instead of config lookup

**Example future implementation**:
```python
# In raster_cog.py (line 268-270)
silver_container = params.get('output_container')
if not silver_container:
    # Fallback to config default
    from config import get_config
    config_obj = get_config()
    silver_container = config_obj.storage.silver.get_container('cogs')
```

**Risk**: Breaks storage tier architecture if users pick wrong container

---

## 📚 Related Files

| File | Purpose | Lines |
|------|---------|-------|
| `jobs/process_raster.py` | Determines output filename and folder | 527-540 |
| `services/raster_cog.py` | Determines output container | 268-270 |
| `config.py` | Provides silver container name | SilverStorageConfig |

---

## ✅ Summary

**Output Container**: Hardcoded to `config.storage.silver.get_container('cogs')` (silver-cogs)
**Output Filename**: `{original_filename}_cog.tif`
**Output Path**: `{output_folder}/{output_filename}` or just `{output_filename}` (root)

**Example**:
```
Input:  rmhazuregeobronze/dctest.tif
Output: silver-cogs/dctest_cog.tif (if no output_folder)
        silver-cogs/processed/dctest_cog.tif (if output_folder="processed")
```

**User Control**:
- ✅ Can control output filename (via input filename)
- ✅ Can control output folder (via `output_folder` parameter)
- ❌ Cannot control output container (hardcoded to silver COGs)
