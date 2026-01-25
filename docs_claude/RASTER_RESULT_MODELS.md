# Raster Workflow Result Models

**Feature**: F7.21 - Type-Safe Raster Pipeline Results
**Created**: 25 JAN 2026
**Priority**: CRITICAL - Blocks reliable checkpoint/resume and prevents silent failures
**Pattern**: Follow `ProcessVectorStage1Data` in `core/models/results.py`

---

## Problem Statement

The Docker raster workflow passes complex dict structures between:
- **Database** (`TaskRecord.checkpoint_data`, `TaskRecord.result_data`, `JobRecord.result_data`)
- **Python** (handler functions, services, `finalize_job()`)
- **Service Bus** (embedded in task parameters)

These structures have **no Pydantic models**, causing:
1. **Silent failures** when fields are renamed or removed
2. **Runtime KeyError** during checkpoint resume
3. **No IDE autocomplete** or type hints
4. **No compile-time validation** of structure changes
5. **Inconsistent serialization** between phases

The vector workflow has `ProcessVectorStage1Data` and `ProcessVectorStage2Result` - raster has nothing equivalent.

---

## Gap Analysis

| Entity | Current State | Risk Level |
|--------|--------------|------------|
| Validation Result | Dict (~25 fields) | **HIGH** |
| COG Creation Result | Dict (~10 fields) | **HIGH** |
| Handler Final Result | Dict (nested, 2 variants) | **HIGH** |
| Checkpoint Data | Dict (phase-specific) | **HIGH** |
| Tiling Scheme Result | GeoJSON dict | MEDIUM |
| Tile Extraction Result | Dict | MEDIUM |
| STAC Creation Result | Dict | MEDIUM |

---

## Implementation Plan

### Phase 1: Core Result Models (HIGH PRIORITY)

Create Pydantic models in `core/models/raster_results.py`:

#### 1.1 RasterValidationResult

```python
class RasterTypeInfo(BaseModel):
    """Raster type detection results."""
    detected_type: str  # rgb, rgba, dem, categorical, multispectral, nir
    confidence: str  # HIGH, MEDIUM, LOW
    evidence: List[str] = Field(default_factory=list)
    type_source: str = "auto_detected"
    optimal_cog_settings: Dict[str, Any] = Field(default_factory=dict)
    band_count: int
    data_type: str

class COGTierInfo(BaseModel):
    """COG tier compatibility info."""
    applicable_tiers: List[str]  # visualization, analysis, archive
    total_compatible: int
    incompatible_reason: Optional[str] = None

class BitDepthCheck(BaseModel):
    """Bit-depth efficiency check."""
    efficient: bool
    current_dtype: str
    reason: str

class MemoryEstimation(BaseModel):
    """Memory footprint estimation."""
    estimated_mb: float
    peak_mb: Optional[float] = None
    recommendation: Optional[str] = None

class RasterValidationData(BaseModel):
    """
    Validated structure for raster validation phase output.

    Stored in TaskRecord.checkpoint_data after Phase 1.
    Consumed by COG creation phase.
    """
    model_config = ConfigDict(extra="allow")

    valid: bool
    source_blob: str
    container_name: str
    source_crs: str
    crs_source: str  # file_metadata, user_override, etc.
    bounds: List[float]  # [minx, miny, maxx, maxy]
    shape: List[int]  # [height, width]
    band_count: int
    dtype: str
    data_type: str  # Alias for tier compatibility
    size_mb: float = 0
    nodata: Optional[Any] = None

    raster_type: RasterTypeInfo
    cog_tiers: COGTierInfo
    bit_depth_check: BitDepthCheck
    memory_estimation: Optional[MemoryEstimation] = None
    warnings: List[str] = Field(default_factory=list)

class RasterValidationResult(BaseModel):
    """Full task result wrapper for validation phase."""
    success: bool
    result: Optional[RasterValidationData] = None
    error: Optional[str] = None
    message: Optional[str] = None
    error_type: Optional[str] = None
```

#### 1.2 COGCreationResult

```python
class COGCreationData(BaseModel):
    """
    Validated structure for COG creation phase output.

    Stored in TaskRecord.checkpoint_data after Phase 2.
    Consumed by STAC creation phase.
    """
    model_config = ConfigDict(extra="allow")

    cog_blob: str
    cog_container: str
    size_mb: float
    compression: str  # DEFLATE, LZW, JPEG
    overview_count: int
    band_count: int
    file_checksum: Optional[str] = None  # sha256:...
    file_size: Optional[int] = None  # bytes

class COGCreationResult(BaseModel):
    """Full task result wrapper for COG creation phase."""
    success: bool
    result: Optional[COGCreationData] = None
    error: Optional[str] = None
    message: Optional[str] = None
```

#### 1.3 STACCreationResult

```python
class STACCreationData(BaseModel):
    """
    Validated structure for STAC creation phase output.
    """
    model_config = ConfigDict(extra="allow")

    collection_id: str
    item_id: Optional[str] = None
    item_count: int = 1
    spatial_extent: List[float]  # [minx, miny, maxx, maxy]
    viewer_url: Optional[str] = None

class STACCreationResult(BaseModel):
    """Full task result wrapper for STAC phase."""
    success: bool
    result: Optional[STACCreationData] = None
    error: Optional[str] = None
    message: Optional[str] = None
```

---

### Phase 2: Tiling Result Models (MEDIUM PRIORITY)

#### 2.1 TilingSchemeResult

```python
class TileFeatureProperties(BaseModel):
    """Properties for a single tile in the tiling scheme."""
    row: int
    col: int
    pixel_window: List[int]  # [x_off, y_off, width, height]

class TilingSchemeMetadata(BaseModel):
    """Metadata for the tiling scheme."""
    total_tiles: int
    tile_dimensions: Dict[str, int]
    source_crs: str
    overlap: int = 0

class TilingSchemeData(BaseModel):
    """
    Validated structure for tiling scheme generation output.

    Note: This is a simplified representation. The actual GeoJSON
    FeatureCollection structure is preserved in the 'features' field.
    """
    model_config = ConfigDict(extra="allow")

    tiling_scheme_blob: str
    tile_count: int
    metadata: TilingSchemeMetadata
    processing_time_seconds: float

class TilingSchemeResult(BaseModel):
    """Full task result wrapper for tiling scheme phase."""
    success: bool
    result: Optional[TilingSchemeData] = None
    error: Optional[str] = None
```

#### 2.2 TileExtractionResult

```python
class TileExtractionData(BaseModel):
    """
    Validated structure for tile extraction phase output.
    """
    model_config = ConfigDict(extra="allow")

    tile_blobs: List[str]
    source_crs: str
    extraction_time_seconds: float
    tiles_extracted: int

class TileExtractionResult(BaseModel):
    """Full task result wrapper for tile extraction phase."""
    success: bool
    result: Optional[TileExtractionData] = None
    error: Optional[str] = None
```

---

### Phase 3: Handler Final Results (HIGH PRIORITY)

#### 3.1 ProcessRasterDockerResult

```python
class ProcessingTiming(BaseModel):
    """Timing information for processing phases."""
    total_seconds: float
    validation_seconds: Optional[float] = None
    cog_seconds: Optional[float] = None
    stac_seconds: Optional[float] = None

class ResourceMetrics(BaseModel):
    """Resource usage metrics (F7.20)."""
    peak_memory_mb: Optional[float] = None
    disk_used_mb: Optional[float] = None
    cpu_percent: Optional[float] = None

class SingleCOGResultData(BaseModel):
    """Result data for single COG processing mode."""
    output_mode: Literal["single_cog"] = "single_cog"
    validation: Dict[str, Any]  # Subset of RasterValidationData
    cog: COGCreationData
    stac: STACCreationData
    processing: ProcessingTiming
    resources: Optional[ResourceMetrics] = None
    artifact_id: Optional[str] = None

class TiledResultData(BaseModel):
    """Result data for tiled processing mode."""
    output_mode: Literal["tiled"] = "tiled"
    tiling: TilingSchemeData
    extraction: TileExtractionData
    cogs: Dict[str, Any]  # {"count": int, "blobs": List[str]}
    stac: STACCreationData
    timing: ProcessingTiming
    artifact_id: Optional[str] = None

class ProcessRasterDockerResult(BaseModel):
    """
    Complete result from process_raster_complete handler.

    Supports both single_cog and tiled output modes.
    Stored in TaskRecord.result_data.
    """
    success: bool
    result: Optional[Union[SingleCOGResultData, TiledResultData]] = None
    error: Optional[str] = None
    message: Optional[str] = None
    error_type: Optional[str] = None
    interrupted: bool = False
    resumable: bool = False
    phase_completed: Optional[int] = None
```

---

### Phase 4: Checkpoint Data Model (HIGH PRIORITY)

```python
class RasterCheckpointData(BaseModel):
    """
    Validated structure for checkpoint data stored in TaskRecord.checkpoint_data.

    Enables type-safe resume after interruption.
    """
    model_config = ConfigDict(extra="allow")

    phase: int  # 1, 2, 3, or 4

    # Phase 1 outputs (available after validation)
    source_crs: Optional[str] = None
    validation_result: Optional[RasterValidationData] = None

    # Phase 2 outputs (available after COG creation)
    cog_blob: Optional[str] = None
    cog_container: Optional[str] = None
    cog_result: Optional[COGCreationData] = None

    # Tiled mode specific
    tiling_result: Optional[TilingSchemeData] = None
    extraction_result: Optional[TileExtractionData] = None
    cog_blobs: Optional[List[str]] = None
```

---

## Integration Points

### 1. Update `validate_raster()` (services/raster_validation.py)

```python
# Before (current)
return {
    "success": True,
    "result": {...}  # Untyped dict
}

# After
from core.models.raster_results import RasterValidationResult, RasterValidationData

result_data = RasterValidationData(
    valid=True,
    source_blob=blob_name,
    ...
)
return RasterValidationResult(success=True, result=result_data).model_dump()
```

### 2. Update `create_cog()` (services/raster_cog.py)

```python
from core.models.raster_results import COGCreationResult, COGCreationData

result_data = COGCreationData(
    cog_blob=output_blob,
    cog_container=container,
    ...
)
return COGCreationResult(success=True, result=result_data).model_dump()
```

### 3. Update Checkpoint Save/Load (core/docker_context.py)

```python
from core.models.raster_results import RasterCheckpointData

# Save with validation
checkpoint_data = RasterCheckpointData(
    phase=1,
    source_crs=source_crs,
    validation_result=validation_data
)
self.save_checkpoint(phase=1, data=checkpoint_data.model_dump())

# Load with validation
raw_data = self.load_checkpoint()
checkpoint = RasterCheckpointData.model_validate(raw_data)
source_crs = checkpoint.source_crs  # Type-safe access
```

### 4. Update Handler (services/handler_process_raster_complete.py)

```python
from core.models.raster_results import (
    ProcessRasterDockerResult,
    SingleCOGResultData,
    TiledResultData
)

# Single COG success
result = ProcessRasterDockerResult(
    success=True,
    result=SingleCOGResultData(
        validation={...},
        cog=cog_data,
        stac=stac_data,
        processing=timing,
        resources=metrics
    )
)
return result.model_dump()
```

### 5. Update `finalize_job()` (jobs/process_raster_docker.py)

```python
from core.models.raster_results import ProcessRasterDockerResult

# Validate task result before processing
task_result = ProcessRasterDockerResult.model_validate(task.result_data)
if task_result.result.output_mode == "tiled":
    # Type-safe access
    tile_count = task_result.result.cogs["count"]
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `core/models/raster_results.py` | CREATE | All Pydantic models |
| `core/models/__init__.py` | MODIFY | Export new models |
| `services/raster_validation.py` | MODIFY | Use RasterValidationResult |
| `services/raster_cog.py` | MODIFY | Use COGCreationResult |
| `services/stac_collection.py` | MODIFY | Use STACCreationResult |
| `services/tiling_scheme.py` | MODIFY | Use TilingSchemeResult |
| `services/tiling_extraction.py` | MODIFY | Use TileExtractionResult |
| `services/handler_process_raster_complete.py` | MODIFY | Use all result models |
| `jobs/process_raster_docker.py` | MODIFY | Validate in finalize_job |
| `core/docker_context.py` | MODIFY | Use RasterCheckpointData |

---

## Implementation Order

1. **Create `core/models/raster_results.py`** with all models
2. **Update exports** in `core/models/__init__.py`
3. **Update `validate_raster()`** - highest impact, most complex
4. **Update `create_cog()`** - second highest impact
5. **Update handler** - ties it all together
6. **Update checkpoint save/load** - enables type-safe resume
7. **Update `finalize_job()`** - ensures consistent output
8. **Update remaining services** (tiling, STAC) - lower priority

---

## Testing Strategy

1. **Unit Tests**: Create `tests/test_raster_result_models.py`
   - Validate model construction
   - Test serialization/deserialization
   - Test optional field handling

2. **Integration Tests**: Modify existing raster job tests
   - Verify checkpoint data validates correctly
   - Verify result data validates correctly
   - Test resume from each phase

3. **Regression Tests**: Run existing Docker raster jobs
   - Verify no breaking changes to output format
   - Verify Platform consumers still work

---

## Success Criteria

1. All raster result structures have Pydantic models
2. Checkpoint resume uses typed models (no raw dict access)
3. Handler returns validated model instances
4. `finalize_job()` validates input with models
5. IDE provides autocomplete for all result fields
6. Breaking changes to result structure fail at compile time

---

## References

- `core/models/results.py` - Existing vector result models (pattern to follow)
- `services/handler_process_raster_complete.py` - Current handler implementation
- `services/raster_validation.py` - Current validation service
- `core/docker_context.py` - Checkpoint management
