# Phase 4: User-Configurable Output Parameters

**Author**: Robert and Geospatial Claude Legion
**Date**: 11 NOV 2025
**Status**: Planning - Not Yet Implemented
**Priority**: Enhancement (Post Phase 1-3)

---

## 🎯 Objective

Add user-configurable output parameters for container and filename while maintaining backward compatibility with current defaults.

**Pattern**: Standard optional parameter pattern (explicitly specified → use it, not specified → use default)

---

## 📋 Phase 4 Task List

### Task 4.1: Add `output_container` Parameter ⭐ NEW

**Current Behavior**:
- Output container hardcoded to `config.storage.silver.get_container('cogs')`
- User has no control over output container

**Proposed Behavior**:
- Add optional `output_container` parameter to job submission
- If specified → use user's container
- If not specified → use current default (silver COGs container)
- Validate container exists during job submission (Phase 1 validation)

**Files to Modify**:
1. `jobs/process_raster.py`:
   - Add `output_container` to `validate_job_parameters()` (optional)
   - Validate container exists if specified
   - Pass to Stage 2 task parameters

2. `services/raster_cog.py`:
   - Replace hardcoded container lookup with parameter check
   - Fallback to config default if not specified

**Backward Compatibility**: ✅ Zero breaking changes (parameter is optional)

---

### Task 4.2: Add `output_blob_name` Parameter ⭐ NEW

**Current Behavior**:
- Output filename auto-generated as `{original_filename}_cog.tif`
- User can only control via `output_folder` parameter
- No way to specify exact output filename

**Proposed Behavior**:
- Add optional `output_blob_name` parameter to job submission
- If specified → use user's exact blob name (allows custom naming)
- If not specified → use current auto-generation logic (`{name}_cog.tif`)
- Validate blob name format (must end with .tif)

**Files to Modify**:
1. `jobs/process_raster.py`:
   - Add `output_blob_name` to `validate_job_parameters()` (optional)
   - Validate format (must end with .tif or .tiff)
   - Pass to Stage 2 task parameters
   - Skip auto-generation if user provided explicit name

2. Stage 2 task creation logic:
   - Check if `output_blob_name` specified
   - If yes → use it directly
   - If no → use current auto-generation logic

**Backward Compatibility**: ✅ Zero breaking changes (parameter is optional)

---

### Task 4.3: Add Output Parameter Validation

**Validation Rules**:

1. **`output_container`**:
   - Optional string
   - Must be non-empty if specified
   - Container must exist (reuse Phase 1 validation)
   - Recommended: Allow only silver containers (prevent users writing to bronze/gold)

2. **`output_blob_name`**:
   - Optional string
   - Must end with `.tif` or `.tiff` (case insensitive)
   - Must be valid blob path (no invalid characters)
   - Can include folder path (e.g., `"myfolder/custom_name.tif"`)
   - Overrides `output_folder` parameter if both specified

**Interaction with Existing Parameters**:

| Scenario | output_blob_name | output_folder | Result |
|----------|------------------|---------------|--------|
| 1 | Not specified | Not specified | `{name}_cog.tif` (current default) |
| 2 | Not specified | `"processed"` | `processed/{name}_cog.tif` (current behavior) |
| 3 | `"custom.tif"` | Not specified | `custom.tif` (new: explicit name) |
| 4 | `"custom.tif"` | `"processed"` | `custom.tif` (explicit name wins) |
| 5 | `"folder/custom.tif"` | Not specified | `folder/custom.tif` (new: full path control) |
| 6 | `"folder/custom.tif"` | `"ignored"` | `folder/custom.tif` (explicit path wins) |

---

## 🔧 Implementation Details

### Task 4.1: Output Container Parameter

#### File 1: `jobs/process_raster.py` - Validation

**Location**: `validate_job_parameters()` (after line 291, before Phase 1 validation)

```python
# Validate output_container (optional - NEW Phase 4)
output_container = params.get("output_container")
if output_container is not None:
    if not isinstance(output_container, str) or not output_container.strip():
        raise ValueError("output_container must be a non-empty string")
    validated["output_container"] = output_container.strip()

    # OPTIONAL: Restrict to silver containers only (recommended)
    if not output_container.startswith('silver-'):
        raise ValueError(
            f"output_container must be a silver-tier container (e.g., 'silver-cogs'). "
            f"Got: '{output_container}'. This prevents accidental writes to bronze/gold tiers."
        )
else:
    validated["output_container"] = None
```

**Then in Phase 1 validation section** (after line 328, add):

```python
# Validate output container exists if specified (Phase 4)
output_container = validated.get("output_container")
if output_container:
    if not blob_repo.container_exists(output_container):
        raise ResourceNotFoundError(
            f"Output container '{output_container}' does not exist in storage account "
            f"'{blob_repo.account_name}'. Verify container name spelling or create "
            f"container before submitting job."
        )
```

#### File 2: `jobs/process_raster.py` - Stage 2 Task Creation

**Location**: Stage 2 task creation (around line 550)

Add to task parameters:
```python
"output_container": job_params.get('output_container'),  # NEW: Pass user container
```

#### File 3: `services/raster_cog.py` - Container Selection

**Location**: Line 268-270 (replace hardcoded lookup)

**Current**:
```python
# Get silver container from config
from config import get_config
config_obj = get_config()
silver_container = config_obj.storage.silver.get_container('cogs')
```

**New** (Phase 4):
```python
# Get output container (user-specified or config default)
output_container = params.get('output_container')
if output_container:
    # User explicitly specified output container
    silver_container = output_container
    logger.info(f"Using user-specified output container: {output_container}")
else:
    # Fallback to config default (backward compatible)
    from config import get_config
    config_obj = get_config()
    silver_container = config_obj.storage.silver.get_container('cogs')
    logger.info(f"Using default output container from config: {silver_container}")
```

---

### Task 4.2: Output Blob Name Parameter

#### File 1: `jobs/process_raster.py` - Validation

**Location**: `validate_job_parameters()` (after output_folder validation, before Phase 1 validation)

```python
# Validate output_blob_name (optional - NEW Phase 4)
output_blob_name = params.get("output_blob_name")
if output_blob_name is not None:
    if not isinstance(output_blob_name, str) or not output_blob_name.strip():
        raise ValueError("output_blob_name must be a non-empty string")

    output_blob_name = output_blob_name.strip()

    # Validate file extension
    if not (output_blob_name.lower().endswith('.tif') or output_blob_name.lower().endswith('.tiff')):
        raise ValueError(
            f"output_blob_name must end with .tif or .tiff extension. "
            f"Got: '{output_blob_name}'"
        )

    validated["output_blob_name"] = output_blob_name
else:
    validated["output_blob_name"] = None
```

#### File 2: `jobs/process_raster.py` - Stage 2 Task Creation

**Location**: Stage 2 task creation (lines 522-540, replace auto-generation logic)

**Current**:
```python
# Output blob name - extract filename and optionally prepend folder
blob_name = job_params['blob_name']
output_folder = job_params.get('output_folder')

# Extract just the filename from input path
filename = blob_name.split('/')[-1]

# Generate output filename (replace or append _cog)
if filename.lower().endswith('.tif'):
    output_filename = f"{filename[:-4]}_cog.tif"
else:
    output_filename = f"{filename}_cog.tif"

# Prepend output folder if specified, otherwise write to root
if output_folder:
    output_blob_name = f"{output_folder}/{output_filename}"
else:
    output_blob_name = output_filename
```

**New** (Phase 4):
```python
# Output blob name - user-specified or auto-generated
output_blob_name = job_params.get('output_blob_name')

if output_blob_name:
    # User explicitly specified output blob name (Phase 4)
    # Use it as-is (already validated, includes any folder path)
    logger.info(f"Using user-specified output blob name: {output_blob_name}")
else:
    # Auto-generate output blob name (current behavior, backward compatible)
    blob_name = job_params['blob_name']
    output_folder = job_params.get('output_folder')

    # Extract just the filename from input path
    filename = blob_name.split('/')[-1]

    # Generate output filename (replace or append _cog)
    if filename.lower().endswith('.tif'):
        output_filename = f"{filename[:-4]}_cog.tif"
    else:
        output_filename = f"{filename}_cog.tif"

    # Prepend output folder if specified, otherwise write to root
    if output_folder:
        output_blob_name = f"{output_folder}/{output_filename}"
    else:
        output_blob_name = output_filename

    logger.info(f"Auto-generated output blob name: {output_blob_name}")
```

---

## 📊 Usage Examples

### Example 1: Default Behavior (No Changes)

```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "dctest.tif"}'
```

**Result**:
- Output container: `silver-cogs` (config default)
- Output blob: `dctest_cog.tif` (auto-generated)
- Full path: `silver-cogs/dctest_cog.tif`

---

### Example 2: Custom Output Container

```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "output_container": "silver-processed"
  }'
```

**Result**:
- Output container: `silver-processed` (user-specified)
- Output blob: `dctest_cog.tif` (auto-generated)
- Full path: `silver-processed/dctest_cog.tif`

---

### Example 3: Custom Output Filename

```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "output_blob_name": "my_custom_output.tif"
  }'
```

**Result**:
- Output container: `silver-cogs` (config default)
- Output blob: `my_custom_output.tif` (user-specified)
- Full path: `silver-cogs/my_custom_output.tif`

---

### Example 4: Full Custom Path (Container + Blob)

```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "output_container": "silver-project-alpha",
    "output_blob_name": "results/2025-11-11/processed_dctest.tif"
  }'
```

**Result**:
- Output container: `silver-project-alpha` (user-specified)
- Output blob: `results/2025-11-11/processed_dctest.tif` (user-specified)
- Full path: `silver-project-alpha/results/2025-11-11/processed_dctest.tif`

---

### Example 5: Backward Compatible with output_folder

```bash
curl -X POST .../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "output_folder": "processed"
  }'
```

**Result**:
- Output container: `silver-cogs` (config default)
- Output blob: `processed/dctest_cog.tif` (auto-generated with folder)
- Full path: `silver-cogs/processed/dctest_cog.tif`

---

## ✅ Validation Matrix

| Parameter | Validation Rule | Error Message |
|-----------|-----------------|---------------|
| `output_container` | Must be non-empty string | "output_container must be a non-empty string" |
| `output_container` | Must start with 'silver-' (recommended) | "output_container must be a silver-tier container" |
| `output_container` | Must exist (Phase 1 check) | "Output container 'X' does not exist in storage account 'Y'" |
| `output_blob_name` | Must be non-empty string | "output_blob_name must be a non-empty string" |
| `output_blob_name` | Must end with .tif or .tiff | "output_blob_name must end with .tif or .tiff extension" |

---

## 🔒 Security Considerations

### Recommended: Restrict Output Container to Silver Tier

**Why**:
- Prevents accidental writes to bronze tier (raw input data)
- Prevents accidental writes to gold tier (final products)
- Enforces storage tier architecture

**Implementation**:
```python
if output_container and not output_container.startswith('silver-'):
    raise ValueError(
        f"output_container must be a silver-tier container (e.g., 'silver-cogs'). "
        f"Got: '{output_container}'. This prevents accidental writes to bronze/gold tiers."
    )
```

**Alternative** (Less restrictive):
- Allow any container if it exists
- Trust users to know what they're doing
- Document tier architecture in API docs

---

## 📋 Implementation Checklist

### Phase 4.1: Output Container Parameter

- [ ] Update `jobs/process_raster.py` → `validate_job_parameters()`:
  - [ ] Add `output_container` validation (optional string)
  - [ ] Add silver-tier restriction (recommended)
  - [ ] Add container existence check (reuse Phase 1 validation)
  - [ ] Update docstring with new parameter

- [ ] Update `jobs/process_raster.py` → `create_tasks_for_stage(stage=2)`:
  - [ ] Pass `output_container` to Stage 2 task parameters

- [ ] Update `services/raster_cog.py` → `create_cog()`:
  - [ ] Check for `params.get('output_container')`
  - [ ] Use user container if specified, else fallback to config
  - [ ] Update docstring with new parameter
  - [ ] Add logging for which container is being used

- [ ] Update `jobs/process_raster_collection.py`:
  - [ ] Same changes as process_raster.py

### Phase 4.2: Output Blob Name Parameter

- [ ] Update `jobs/process_raster.py` → `validate_job_parameters()`:
  - [ ] Add `output_blob_name` validation (optional string)
  - [ ] Validate .tif/.tiff extension
  - [ ] Update docstring with new parameter

- [ ] Update `jobs/process_raster.py` → `create_tasks_for_stage(stage=2)`:
  - [ ] Check if `output_blob_name` specified
  - [ ] If yes → skip auto-generation, use user's name
  - [ ] If no → use current auto-generation logic
  - [ ] Add logging for which path is being used

- [ ] Update `jobs/process_raster_collection.py`:
  - [ ] Consider: Collections may not need this (tiles need consistent naming)

### Phase 4.3: Testing

- [ ] Test default behavior (no parameters) → backward compatible
- [ ] Test custom output_container → writes to specified container
- [ ] Test custom output_blob_name → uses exact name
- [ ] Test both parameters together → full custom path
- [ ] Test validation errors (invalid container, wrong extension)
- [ ] Test interaction with output_folder (explicit name wins)

### Phase 4.4: Documentation

- [ ] Update API documentation with new parameters
- [ ] Update `OUTPUT_NAMING_CONVENTION.md` with Phase 4 changes
- [ ] Add examples to user guide
- [ ] Document security considerations (silver-tier restriction)

---

## 🎯 Benefits

### User Benefits

✅ **Flexibility**: Users can now organize outputs however they want
✅ **Custom Naming**: Support for meaningful filenames (dates, versions, projects)
✅ **Multi-Project Support**: Different containers for different projects
✅ **Backward Compatible**: Existing scripts/workflows continue to work unchanged

### Examples of New Capabilities

**Date-based Organization**:
```json
{
  "blob_name": "dctest.tif",
  "output_container": "silver-cogs",
  "output_blob_name": "2025/11/11/dctest_processed.tif"
}
```

**Project-based Organization**:
```json
{
  "blob_name": "dctest.tif",
  "output_container": "silver-project-alpha",
  "output_blob_name": "results/dctest_alpha_v2.tif"
}
```

**Version Control**:
```json
{
  "blob_name": "dctest.tif",
  "output_blob_name": "dctest_v1.0.0_cog.tif"
}
```

---

## 🚀 Rollout Plan

### Phase 4.1: Output Container (Week 1)
1. Implement parameter validation
2. Update controller logic
3. Update handler logic
4. Test all scenarios
5. Deploy to dev environment
6. Monitor for issues
7. Deploy to production

### Phase 4.2: Output Blob Name (Week 2)
1. Implement parameter validation
2. Update auto-generation logic
3. Test interaction with output_folder
4. Test all scenarios
5. Deploy to dev environment
6. Monitor for issues
7. Deploy to production

### Documentation & Communication (Week 2-3)
1. Update API documentation
2. Create usage examples
3. Announce new features to users
4. Collect feedback

---

## 📚 Related Documents

- **OUTPUT_NAMING_CONVENTION.md** - Current naming convention (pre-Phase 4)
- **PHASE_1_IMPLEMENTATION_SUMMARY.md** - Validation implementation
- **RASTER_VALIDATION_IMPLEMENTATION_PLAN.md** - Complete Phase 1-3 plan

---

## 🔮 Future Enhancements (Beyond Phase 4)

### Potential Phase 4.X Tasks (To Be Added)

- [ ] **4.3**: Add `output_crs` parameter (override target_crs per job)
- [ ] **4.4**: Add `output_tile_size` parameter (override default 512x512)
- [ ] **4.5**: Add `output_compression_level` parameter (fine-tune DEFLATE level)
- [ ] **4.6**: Add `create_thumbnail` parameter (auto-generate preview image)

**Add new tasks here as they're identified...**

---

## ✅ Summary

**Phase 4 Goal**: Give users control over output location and naming while maintaining backward compatibility

**Implementation Pattern**: Standard optional parameter pattern
- Parameter specified → use it
- Parameter not specified → use current default

**Breaking Changes**: ZERO (all parameters are optional)

**Timeline**: 2 weeks (1 week per major task)

**Status**: 📋 Planning phase - ready to implement after Phase 1-3 complete

---

**Author**: Robert and Geospatial Claude Legion
**Next Review**: After Phase 3 completion
