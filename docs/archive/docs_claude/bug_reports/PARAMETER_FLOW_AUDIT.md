# Parameter Flow Audit: process_large_raster

**Date**: 1 NOV 2025
**Purpose**: Document complete parameter flow through all 4 stages to ensure consistency

## Job Parameters (User Input)

```json
{
  "blob_name": "17apr2024wv2.tif",
  "container_name": "rmhazuregeobronze",
  "tile_size": null,
  "overlap": 512,
  "output_tier": "analysis",
  "band_names": {"5": "Red", "3": "Green", "2": "Blue"},  // dict[int, str] - JSON uses string keys
  "jpeg_quality": 85,
  "overview_level": 2
}
```

## Critical: band_names Format

**JSON Input** (string keys):
```json
{"5": "Red", "3": "Green", "2": "Blue"}
```

**Python Internal** (integer keys after Pydantic validation):
```python
{5: "Red", 3: "Green", 2: "Blue"}  # dict[int, str]
```

**Pydantic Model**: `models/band_mapping.py::BandNames`
- Automatically converts JSON string keys → Python int keys
- Validates band indices >= 1
- Validates band names are strings

---

## Stage 1: generate_tiling_scheme

### Task Parameters (jobs/process_large_raster.py lines 420-427)
```python
{
    "container_name": str,          # ✅ Bronze container
    "blob_name": str,               # ✅ Source raster filename
    "tile_size": int | None,        # ✅ None = auto-calculate based on band_count
    "overlap": int,                 # ✅ Default: 512
    "output_container": str,        # ✅ Silver container
    "band_names": dict[int, str]    # ✅ For tile size calculation
}
```

### Service Handler: services/tiling_scheme.py::generate_tiling_scheme()
**Parameters Used**:
- `container_name` → blob download
- `blob_name` → blob download
- `tile_size` → passed to generate_tiling_scheme_from_raster()
- `overlap` → passed to generate_tiling_scheme_from_raster()
- `output_container` → upload tiling scheme GeoJSON
- `band_names` → **CRITICAL**: passed to generate_tiling_scheme_from_raster() for tile size calculation

**Function Signature** (line 365-369):
```python
def generate_tiling_scheme_from_raster(
    raster_path: str,
    tile_size: Optional[int] = None,
    overlap: Optional[int] = None,
    band_names: Optional[Dict[int, str]] = None  # ✅ ADDED
) -> Dict[str, Any]:
```

**Tile Size Logic** (line 411-417):
```python
if band_names and isinstance(band_names, dict) and len(band_names) > 0:
    band_count = len(band_names)  # Use requested band count (e.g., 3 for RGB)
    logger.info(f"📊 Using requested band count: {band_count} bands")
else:
    band_count = actual_band_count  # Use all bands from file (e.g., 8 for WorldView-2)
```

**Result**: Smaller tiles when fewer bands requested (3 bands → 8,704px, 8 bands → 5,120px)

---

## Stage 2: extract_tiles

### Task Parameters (jobs/process_large_raster.py lines 446-454)
```python
{
    "container_name": str,              # ✅ Bronze container
    "blob_name": str,                   # ✅ Source raster filename
    "tiling_scheme_blob": str,          # ✅ From Stage 1 result
    "tiling_scheme_container": str,     # ✅ Silver container
    "output_container": str,            # ✅ Intermediate tiles container
    "job_id": str,                      # ✅ For folder naming
    "band_names": dict[int, str]        # ✅ For selective band reading
}
```

### Service Handler: services/tiling_extraction.py::extract_tiles()
**Parameters Used**:
- `container_name` → VSI SAS URL generation
- `blob_name` → VSI SAS URL generation
- `tiling_scheme_blob` → download tiling scheme
- `tiling_scheme_container` → download tiling scheme
- `output_container` → upload extracted tiles
- `job_id` → job-scoped folder: `{job_id[:8]}/tiles/`
- `band_names` → **CRITICAL**: determines which bands to read

**Band Reading Logic** (line 354-373):
```python
if band_names and isinstance(band_names, dict) and len(band_names) > 0:
    # Get sorted band indices from dict keys
    band_indices = sorted([idx for idx in band_names.keys() if idx <= src.count])
    band_desc = ', '.join(f"{idx} ({band_names[idx]})" for idx in band_indices)
else:
    # Read all bands
    band_indices = list(range(1, src.count + 1))
    band_desc = "all bands"
```

**VSI Read** (line 443):
```python
tile_data = src.read(indexes=band_indices, window=window)
```

**Result**: Only reads requested bands (3 instead of 8) → 62.5% less data transfer over HTTP!

---

## Stage 3: create_cog (Parallel)

### Task Parameters (jobs/process_large_raster.py lines 531-541)
```python
{
    "container_name": str,          # ✅ Intermediate tiles container
    "blob_name": str,               # ✅ Tile blob path (e.g., "427b3500/tiles/file_tile_0_0.tif")
    "source_crs": str,              # ✅ From Stage 2 result
    "target_crs": str,              # ✅ "EPSG:4326"
    "raster_type": dict,            # ✅ Metadata from Stage 1
    "output_tier": str,             # ✅ "analysis" | "visualization"
    "output_blob_name": str,        # ✅ "cogs/{blob_stem}/{filename}_cog.tif"
    "jpeg_quality": int             # ✅ For visualization tier
}
```

**Note**: `band_names` NOT needed here - tiles already have correct band count from Stage 2

### Service Handler: services/raster_cog.py::create_cog()
**Parameters Used**: All parameters from task (no band_names needed)

---

## Stage 4: create_mosaicjson_with_stats

### Task Parameters (jobs/process_large_raster.py lines 568-575)
```python
{
    "cog_blobs": list[str],         # ✅ From Stage 3 results (all successful COGs)
    "container_name": str,          # ✅ Silver container
    "job_id": str,                  # ✅ For MosaicJSON naming
    "bounds": list[float],          # ✅ From Stage 3 first COG result
    "band_names": dict[int, str],   # ✅ FIXED (was list, now dict)
    "overview_level": int,          # ✅ For STAC
    "output_container": str         # ✅ Silver container
}
```

**⚠️ BUG FIXED**: Line 572 was passing `["Red", "Green", "Blue"]` (list) instead of `{5: "Red", 3: "Green", 2: "Blue"}` (dict)

### Service Handler: services/mosaicjson.py::create_mosaicjson_with_stats()
**Parameters Used**: All parameters (band_names used for STAC metadata)

---

## Summary of Fixes Applied (1 NOV 2025)

### 1. ✅ Added band_names to Stage 1 function signature
**File**: `services/tiling_scheme.py`
**Line**: 369
**Fix**: Added `band_names: Optional[Dict[int, str]] = None` parameter

### 2. ✅ Pass band_names to generate_tiling_scheme_from_raster()
**File**: `services/tiling_scheme.py`
**Line**: 587
**Fix**: Added `band_names=band_names` to function call

### 3. ✅ Fixed Stage 4 band_names default (list → dict)
**File**: `jobs/process_large_raster.py`
**Line**: 572
**Before**: `"band_names": job_params.get("band_names", ["Red", "Green", "Blue"])`
**After**: `"band_names": job_params.get("band_names", {5: "Red", 3: "Green", 2: "Blue"})`

### 4. ✅ Fixed tiling_scheme.py band_names default ([] → {})
**File**: `services/tiling_scheme.py`
**Line**: 551
**Before**: `band_names = params.get("band_names", [])`
**After**: `band_names = params.get("band_names", {})`

### 5. ✅ Created Pydantic model for automatic JSON conversion
**File**: `models/band_mapping.py` (NEW)
**Purpose**: Automatically convert JSON string keys → Python int keys

---

## Testing Checklist

- [ ] Stage 1: Verify tile size calculated with band_count=3 (should be ~8,704px)
- [ ] Stage 2: Verify only 3 bands read from VSI (check tile_size_mb in logs)
- [ ] Stage 3: Verify COG creation succeeds with 3-band tiles
- [ ] Stage 4: Verify MosaicJSON + STAC created with band_names dict

---

## Expected Performance Improvement

**Before**:
- Tile size: 10,240 × 10,240 px
- Bands read: 8 (all bands)
- Data per tile: **~1.6 GB**
- Result: Hanging/timeout on VSI read

**After**:
- Tile size: 8,704 × 8,704 px (auto-calculated for 3 bands)
- Bands read: 3 (RGB only)
- Data per tile: **~453 MB**
- Result: **72% reduction in data transfer** → fast VSI reads ✅
