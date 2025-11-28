# COG Tier Detection System

**Date**: 19 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Automatic tier compatibility detection based on raster characteristics

---

## Overview

The multi-tier COG system automatically detects which output tiers are compatible with each input raster based on **band count** and **data type**. This prevents errors and ensures optimal storage strategy.

---

## How It Works

### Stage 1: Raster Validation
During validation ([services/raster_validation.py](../services/raster_validation.py)), the system:

1. **Opens raster file** using rasterio
2. **Extracts metadata**:
   - `band_count`: Number of bands (e.g., 1 for DEM, 3 for RGB, 8 for Landsat)
   - `dtype`: Data type (e.g., uint8, uint16, float32, float64)
3. **Calls `determine_applicable_tiers()`** from config
4. **Returns tier compatibility** in validation result

**Code Location**: [services/raster_validation.py:308-330](../services/raster_validation.py#L308-L330)

```python
from config import determine_applicable_tiers

# Determine which tiers are compatible with this raster
applicable_tiers = determine_applicable_tiers(band_count, str(dtype))

logger.info(f"✅ Applicable tiers: {applicable_tiers}")
# Example output: ['analysis', 'archive'] for DEM
```

### Stage 2: COG Creation
During COG creation ([services/raster_cog.py](../services/raster_cog.py)), the system:

1. **Receives `output_tier` parameter** from job
2. **Checks compatibility** using validation results
3. **Falls back to "analysis"** if requested tier is incompatible
4. **Applies tier-specific settings** (compression, quality, storage tier)

**Code Location**: [services/raster_cog.py:129-138](../services/raster_cog.py#L129-L138)

```python
# Check tier compatibility
if not tier_profile.is_compatible(band_count, data_type):
    logger.warning(f"⚠️ Tier '{output_tier.value}' not compatible")
    logger.warning(f"   Falling back to 'analysis' tier (DEFLATE - universal)")
    output_tier = CogTier.ANALYSIS
    tier_profile = COG_TIER_PROFILES[output_tier]
```

---

## Tier Compatibility Matrix

### Visualization Tier (JPEG)
**Compression**: JPEG (lossy)
**Storage**: Hot
**Compatibility**: ❌ **RESTRICTED** - RGB only

| Raster Type | Band Count | Data Type | Compatible? | Reason |
|-------------|------------|-----------|-------------|--------|
| RGB Imagery | 3 | uint8 | ✅ YES | Perfect match |
| RGB Imagery | 3 | uint16 | ❌ NO | JPEG requires uint8 |
| RGBA Drone | 4 | uint8 | ❌ NO | JPEG doesn't support alpha |
| DEM | 1 | float32 | ❌ NO | JPEG doesn't support float |
| Landsat | 8 | uint16 | ❌ NO | JPEG requires exactly 3 bands |

### Analysis Tier (DEFLATE)
**Compression**: DEFLATE (lossless)
**Storage**: Hot
**Compatibility**: ✅ **UNIVERSAL** - All raster types

| Raster Type | Band Count | Data Type | Compatible? |
|-------------|------------|-----------|-------------|
| RGB Imagery | 3 | uint8 | ✅ YES |
| RGBA Drone | 4 | uint8 | ✅ YES |
| DEM | 1 | float32 | ✅ YES |
| Landsat | 8 | uint16 | ✅ YES |
| Scientific | any | any | ✅ YES |

### Archive Tier (LZW)
**Compression**: LZW (lossless)
**Storage**: Cool
**Compatibility**: ✅ **UNIVERSAL** - All raster types

| Raster Type | Band Count | Data Type | Compatible? |
|-------------|------------|-----------|-------------|
| RGB Imagery | 3 | uint8 | ✅ YES |
| RGBA Drone | 4 | uint8 | ✅ YES |
| DEM | 1 | float32 | ✅ YES |
| Landsat | 8 | uint16 | ✅ YES |
| Scientific | any | any | ✅ YES |

---

## Real-World Examples

### Example 1: RGB Aerial Photo
**Input File**: aerial_photo.tif
```
Band Count: 3
Data Type: uint8
```

**Validation Result**:
```json
{
  "band_count": 3,
  "dtype": "uint8",
  "cog_tiers": {
    "applicable_tiers": ["visualization", "analysis", "archive"],
    "total_compatible": 3,
    "incompatible_reason": null
  }
}
```

**User Can Request**:
- `output_tier: "visualization"` → JPEG (17 MB)
- `output_tier: "analysis"` → DEFLATE (50 MB)
- `output_tier: "archive"` → LZW (180 MB)
- `output_tier: "all"` → All 3 COGs (Phase 2)

### Example 2: Digital Elevation Model (DEM)
**Input File**: elevation.tif
```
Band Count: 1
Data Type: float32
```

**Validation Result**:
```json
{
  "band_count": 1,
  "dtype": "float32",
  "cog_tiers": {
    "applicable_tiers": ["analysis", "archive"],
    "total_compatible": 2,
    "incompatible_reason": "JPEG requires RGB (3 bands, uint8)"
  }
}
```

**User Can Request**:
- `output_tier: "visualization"` → ⚠️ Auto-fallback to "analysis"
- `output_tier: "analysis"` → DEFLATE (50 MB)
- `output_tier: "archive"` → LZW (180 MB)
- `output_tier: "all"` → 2 COGs only (Phase 2)

**Log Output**:
```
⚠️ Tier 'visualization' not compatible with 1 bands, float32
   Falling back to 'analysis' tier (DEFLATE - universal)
```

### Example 3: Landsat Multispectral
**Input File**: landsat8.tif
```
Band Count: 8
Data Type: uint16
```

**Validation Result**:
```json
{
  "band_count": 8,
  "dtype": "uint16",
  "cog_tiers": {
    "applicable_tiers": ["analysis", "archive"],
    "total_compatible": 2,
    "incompatible_reason": "JPEG requires RGB (3 bands, uint8)"
  }
}
```

**User Can Request**:
- `output_tier: "visualization"` → ⚠️ Auto-fallback to "analysis"
- `output_tier: "analysis"` → DEFLATE
- `output_tier: "archive"` → LZW
- `output_tier: "all"` → 2 COGs only (Phase 2)

---

## Configuration Details

### Tier Profiles ([config.py](../config.py))

**CogTierProfile Model**:
```python
class CogTierProfile(BaseModel):
    tier: CogTier
    compression: str
    quality: Optional[int] = None
    predictor: Optional[int] = 2
    zlevel: Optional[int] = 6
    blocksize: int = 512
    storage_tier: StorageAccessTier
    description: str
    use_case: str

    # Compatibility rules
    requires_rgb: bool = False      # JPEG: True, DEFLATE/LZW: False
    supports_float: bool = True     # JPEG: False, DEFLATE/LZW: True
    supports_multiband: bool = True # JPEG: False, DEFLATE/LZW: True

    def is_compatible(self, band_count: int, data_type: str) -> bool:
        """Check if tier compatible with raster characteristics."""
        if self.requires_rgb:
            return band_count == 3 and data_type == 'uint8'
        if 'float' in data_type.lower() and not self.supports_float:
            return False
        if band_count > 3 and not self.supports_multiband:
            return False
        return True
```

**Tier Definitions**:
```python
COG_TIER_PROFILES = {
    CogTier.VISUALIZATION: CogTierProfile(
        tier=CogTier.VISUALIZATION,
        compression="JPEG",
        quality=85,
        storage_tier=StorageAccessTier.HOT,
        requires_rgb=True,  # ❌ Restricts to 3 bands, uint8
        supports_float=False,
        supports_multiband=False
    ),
    CogTier.ANALYSIS: CogTierProfile(
        tier=CogTier.ANALYSIS,
        compression="DEFLATE",
        predictor=2,
        zlevel=6,
        storage_tier=StorageAccessTier.HOT,
        requires_rgb=False,  # ✅ Works with all
        supports_float=True,
        supports_multiband=True
    ),
    CogTier.ARCHIVE: CogTierProfile(
        tier=CogTier.ARCHIVE,
        compression="LZW",
        predictor=2,
        storage_tier=StorageAccessTier.COOL,
        requires_rgb=False,  # ✅ Works with all
        supports_float=True,
        supports_multiband=True
    )
}
```

**Detection Function**:
```python
def determine_applicable_tiers(band_count: int, data_type: str) -> List[CogTier]:
    """
    Determine which COG tiers are compatible with raster characteristics.

    Args:
        band_count: Number of bands in raster
        data_type: Data type string (e.g., 'uint8', 'float32')

    Returns:
        List of compatible tier names (e.g., ['analysis', 'archive'])
    """
    applicable = []
    for tier, profile in COG_TIER_PROFILES.items():
        if profile.is_compatible(band_count, data_type):
            applicable.append(tier)
    return applicable
```

---

## Adding New Tiers

### Example: High-Compression Archive Tier

If you need a new tier (e.g., ultra-compressed WEBP for archival):

**Step 1**: Add to CogTier enum
```python
class CogTier(str, Enum):
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"
    ARCHIVE = "archive"
    ULTRA_ARCHIVE = "ultra_archive"  # NEW
```

**Step 2**: Define tier profile
```python
COG_TIER_PROFILES[CogTier.ULTRA_ARCHIVE] = CogTierProfile(
    tier=CogTier.ULTRA_ARCHIVE,
    compression="WEBP",
    quality=75,
    storage_tier=StorageAccessTier.ARCHIVE,  # Coldest tier
    description="Ultra-compressed archive for long-term cold storage",
    use_case="Regulatory compliance with minimal access",
    requires_rgb=True,  # WEBP works best with RGB
    supports_float=False,
    supports_multiband=False
)
```

**Step 3**: Update job parameter schema
```python
# In jobs/process_raster.py
"output_tier": {
    "type": "str",
    "required": False,
    "default": "analysis",
    "allowed": ["visualization", "analysis", "archive", "ultra_archive", "all"]
}
```

**Step 4**: Tier detection happens automatically
```python
# RGB raster → all 4 tiers including ultra_archive
# DEM raster → only analysis + archive (WEBP incompatible)
```

---

## Testing Tier Detection

### Unit Test Example
```python
from config import determine_applicable_tiers

# Test RGB
rgb_tiers = determine_applicable_tiers(band_count=3, data_type='uint8')
assert rgb_tiers == ['visualization', 'analysis', 'archive']

# Test DEM
dem_tiers = determine_applicable_tiers(band_count=1, data_type='float32')
assert dem_tiers == ['analysis', 'archive']
assert 'visualization' not in dem_tiers

# Test Landsat
landsat_tiers = determine_applicable_tiers(band_count=8, data_type='uint16')
assert landsat_tiers == ['analysis', 'archive']
```

### Integration Test
```bash
# Submit job with RGB raster + visualization tier
curl -X POST .../api/jobs/submit/process_raster \
  -d '{"blob_name": "aerial_rgb.tif", "output_tier": "visualization"}'

# Check validation result includes tier detection
curl .../api/jobs/status/{JOB_ID}
# Expect: "applicable_tiers": ["visualization", "analysis", "archive"]
```

---

## Validation Result Structure

**Full validation result** with tier detection:
```json
{
  "success": true,
  "result": {
    "valid": true,
    "source_blob": "sample.tif",
    "band_count": 3,
    "dtype": "uint8",
    "data_type": "uint8",

    "raster_type": {
      "detected_type": "rgb",
      "confidence": "HIGH",
      "band_count": 3,
      "data_type": "uint8"
    },

    "cog_tiers": {
      "applicable_tiers": ["visualization", "analysis", "archive"],
      "total_compatible": 3,
      "incompatible_reason": null
    }
  }
}
```

---

## Error Handling

### Fallback Behavior
If tier detection fails (exception during import or execution):
```python
# Default to all tiers
applicable_tiers = ['visualization', 'analysis', 'archive']
logger.warning("⚠️ Using default tiers: {applicable_tiers}")
```

### User Requests Incompatible Tier
If user requests `output_tier: "visualization"` for a DEM:
```python
# Auto-fallback in COG service
if not tier_profile.is_compatible(band_count, data_type):
    logger.warning("⚠️ Tier 'visualization' not compatible with 1 bands, float32")
    output_tier = CogTier.ANALYSIS
```

**Result**: User gets "analysis" tier instead, with warning in logs

---

## Performance Considerations

**Tier Detection Cost**: Negligible
- Already reading raster metadata (band_count, dtype) in validation
- `determine_applicable_tiers()` is pure Python logic (no I/O)
- Runs once per job during Stage 1 validation

**Benefits**:
- Prevents incompatible tier selection
- Enables automatic multi-tier fan-out (Phase 2)
- Improves user experience (no manual compatibility checking)

---

## Future Enhancements

### Phase 2: Multi-Tier Fan-Out
When `output_tier: "all"`:
```python
# Use applicable_tiers from validation result
applicable_tiers = validation_result['cog_tiers']['applicable_tiers']

# Create one task per tier
for tier in applicable_tiers:
    create_cog_task(tier=tier)

# RGB → 3 tasks (visualization, analysis, archive)
# DEM → 2 tasks (analysis, archive only)
```

### Advanced Compatibility Rules
Future tiers may have complex rules:
```python
class CogTierProfile(BaseModel):
    # ...existing fields...

    min_band_count: Optional[int] = None
    max_band_count: Optional[int] = None
    allowed_dtypes: Optional[List[str]] = None

    def is_compatible(self, band_count: int, data_type: str) -> bool:
        if self.min_band_count and band_count < self.min_band_count:
            return False
        if self.max_band_count and band_count > self.max_band_count:
            return False
        if self.allowed_dtypes and data_type not in self.allowed_dtypes:
            return False
        # ...existing logic...
```

---

## Summary

**Tier detection is automatic and transparent**:
1. ✅ Runs during Stage 1 validation (no extra cost)
2. ✅ Uses existing raster metadata (band_count, dtype)
3. ✅ Stored in validation result for COG stage
4. ✅ Auto-fallback prevents incompatible tier selection
5. ✅ Foundation for multi-tier fan-out (Phase 2)

**User Experience**:
- User submits: `{"blob_name": "dem.tif", "output_tier": "visualization"}`
- System detects: DEM → JPEG incompatible
- System applies: Fallback to "analysis" tier
- User receives: DEFLATE-compressed COG with tier metadata
- Logs explain: "Tier 'visualization' not compatible with 1 bands, float32"
