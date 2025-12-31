# Dead Code Review - Aggressive Efficiency Sweep

**Status**: WORKING DOCUMENT - DO NOT DELETE CODE UNTIL REVIEWED
**Created**: 31 DEC 2025
**Author**: Claude Code Analysis
**Purpose**: Comprehensive map of dead/unused code for potential removal

---

## Executive Summary

This document catalogs all dead, deprecated, and unused code identified through systematic tracing of the job-handler dependency graph. The goal is an aggressive efficiency sweep to reduce codebase complexity and maintenance burden.

**Key Metrics:**
- Total files identified for removal: ~25 files
- Estimated code reduction: ~150KB
- Registered but unused handlers: 3
- Entire directories with zero imports: 1

---

## Methodology

Analysis performed by tracing:
1. `jobs/__init__.py` → ALL_JOBS registry (21 active jobs)
2. Each job's `stages[].task_type` declarations
3. `services/__init__.py` → ALL_HANDLERS registry (68 handlers)
4. Cross-referencing handlers used vs registered
5. Grep analysis for import statements across codebase
6. Verification of zero-import files/directories

---

## Category 1: DIRECTORIES WITH ZERO IMPORTS

### 1.1 `/vector/` (Root Level Directory)

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/vector/`

**Evidence of Non-Use**:
```bash
# Zero results - nothing imports from this directory
grep -r "from vector\." --include="*.py" .
grep -r "import vector" --include="*.py" .
```

**Files to Delete (14 total)**:

| File | Size | Purpose | Why Dead |
|------|------|---------|----------|
| `converter_base.py` | 2.2KB | Abstract base class for converters | Superseded by `services/vector/converters.py` |
| `converter_helpers.py` | 9.7KB | Utility functions for conversion | Superseded by `services/vector/helpers.py` |
| `converter_registry.py` | 4.7KB | Registry pattern for converters | Never integrated - services use direct imports |
| `converters_init.py` | 2.3KB | Package init with exports | No consumers |
| `csv_converter.py` | 3.8KB | CSV to GeoDataFrame | Duplicate of `services/vector/converters.py::_convert_csv` |
| `geojson_converter.py` | 1.8KB | GeoJSON converter | Duplicate of `services/vector/converters.py::_convert_geojson` |
| `geopackage_converter.py` | 2.6KB | GeoPackage converter | Duplicate of `services/vector/converters.py::_convert_geopackage` |
| `kml_converter.py` | 1.8KB | KML converter | Duplicate of `services/vector/converters.py::_convert_kml` |
| `kmz_converter.py` | 3.1KB | KMZ converter | Duplicate of `services/vector/converters.py::_convert_kmz` |
| `shapefile_converter.py` | 3.7KB | Shapefile converter | Duplicate of `services/vector/converters.py::_convert_shapefile` |
| `load_vector_task.py` | 7.1KB | Task handler prototype | Never registered in ALL_HANDLERS |
| `converter_usage_guide.md` | 12.2KB | Documentation | Documents unused code |
| `vector_converter_design.md` | 11.7KB | Design document | Documents unused code |

**Total Size**: ~66KB

**Historical Context**: This appears to be an earlier implementation attempt that was abandoned in favor of the `services/vector/` module. The `services/vector/converters.py` file contains the active implementations that are actually imported and used by `process_vector_tasks.py`.

**Removal Command**:
```bash
rm -rf /Users/robertharrison/python_builds/rmhgeoapi/vector/
```

---

## Category 2: SERVICE FILES WITH ZERO IMPORTS

### 2.1 `services/service_blob.py`

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/service_blob.py`
**Size**: 21.4KB

**Evidence of Non-Use**:
```bash
# Only found in documentation/archive files, never in .py imports
grep -r "from services.service_blob" --include="*.py" .
grep -r "from services import.*service_blob" --include="*.py" .
# Results: 0 matches in Python files
```

**What It Contains**:
- `create_analyze_handler()` - Factory for analyze handler
- `create_extract_handler()` - Factory for extract handler
- `create_summary_handler()` - Factory for summary handler
- Imports deprecated `schema_blob` and `schema_orchestration` modules

**Why Dead**:
- Handlers are NOT registered in `services/__init__.py` ALL_HANDLERS
- Uses old "factory pattern" that was replaced by direct handler functions
- Functionality superseded by:
  - `services/container_summary.py` → `analyze_container_summary`
  - `services/container_inventory.py` → `list_blobs_with_metadata`, `analyze_blob_basic`

**Dependencies to Check Before Removal**:
- `schema_blob` - May also be dead (used only by this file)
- `schema_orchestration` - May also be dead (used only by this file)

**Removal Command**:
```bash
rm /Users/robertharrison/python_builds/rmhgeoapi/services/service_blob.py
```

---

### 2.2 `services/vector/tasks.py` - Legacy Handlers

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/vector/tasks.py`
**Size**: 19.8KB

**Current Status**: File exists, functions exported in `__init__.py`, but handlers NOT registered in `ALL_HANDLERS`.

**Functions to Remove (5 total)**:

| Function | Lines | Purpose | Replacement |
|----------|-------|---------|-------------|
| `load_vector_file()` | 32-98 | Load blob to GeoDataFrame | `process_vector_prepare` handles this internally |
| `validate_vector()` | 102-128 | Validate GeoDataFrame | Validation merged into `process_vector_prepare` |
| `upload_vector_chunk()` | 130-162 | Upload chunk to PostGIS | Replaced by `process_vector_upload` |
| `prepare_vector_chunks()` | 164-386 | Old Stage 1 handler | Replaced by `process_vector_prepare` in `process_vector_tasks.py` |
| `upload_pickled_chunk()` | 388-500+ | Old Stage 2 handler | Replaced by `process_vector_upload` in `process_vector_tasks.py` |

**Evidence These Are Not Used**:
```python
# In services/__init__.py - these are COMMENTED OUT:
# from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk

# The ACTIVE handlers come from process_vector_tasks.py:
from .vector.process_vector_tasks import process_vector_prepare, process_vector_upload
```

**Historical Context**: These were the original ingest_vector handlers. They were replaced on 26 NOV 2025 with the idempotent `process_vector_*` handlers in `process_vector_tasks.py`.

**Option A - Delete Entire File**:
```bash
rm /Users/robertharrison/python_builds/rmhgeoapi/services/vector/tasks.py
```

**Option B - Keep Converters Import** (if helpers are still needed):
The file imports `_convert_*` functions from `converters.py` - verify these are also imported elsewhere before full deletion.

**Required Update to `services/vector/__init__.py`**:
```python
# REMOVE these exports:
from .tasks import (
    load_vector_file,      # DELETE
    validate_vector,       # DELETE
    upload_vector_chunk,   # DELETE
    prepare_vector_chunks, # DELETE
    upload_pickled_chunk   # DELETE
)
```

---

## Category 3: DEPRECATED BUT REGISTERED HANDLERS

These handlers are in `ALL_HANDLERS` registry but no job's `stages[].task_type` references them.

### 3.1 `h3_level4_generate` Handler

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/handler_h3_level4.py`
**Size**: 5.6KB
**Registered As**: `"h3_level4_generate": h3_level4_generate`

**Evidence of Non-Use**:
```python
# In jobs/generate_h3_level4.py - stages use DIFFERENT handler:
stages = [
    {"number": 1, "name": "generate", "task_type": "h3_native_streaming_postgis", ...},
    {"number": 2, "name": "stac", "task_type": "h3_create_stac", ...}
]
# Note: "h3_level4_generate" is NOT referenced
```

**What It Does**: Generates H3 Level 4 grid cells using older streaming approach.

**Replaced By**: `h3_native_streaming_postgis` in `handler_h3_native_streaming.py` (3.5x faster, unified implementation).

**Dependencies**:
- Imports `services/h3_grid.py` → Also deprecated (see 3.4)

**Removal Steps**:
1. Remove from `services/__init__.py`:
   ```python
   # DELETE this import:
   from .handler_h3_level4 import h3_level4_generate

   # DELETE this registry entry:
   "h3_level4_generate": h3_level4_generate,
   ```
2. Delete file:
   ```bash
   rm /Users/robertharrison/python_builds/rmhgeoapi/services/handler_h3_level4.py
   ```

---

### 3.2 `h3_base_generate` Handler

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/handler_h3_base.py`
**Size**: 5.4KB
**Registered As**: `"h3_base_generate": h3_base_generate`

**Evidence of Non-Use**:
```python
# In jobs/create_h3_base.py - stages use DIFFERENT handler:
stages = [
    {"number": 1, "name": "generate", "task_type": "h3_native_streaming_postgis", ...},
    {"number": 2, "name": "stac", "task_type": "h3_create_stac", ...}
]
# Note: "h3_base_generate" is NOT referenced
```

**What It Does**: Generates base H3 grid (resolution 0-2) using older approach.

**Replaced By**: `h3_native_streaming_postgis` - unified handler for all H3 resolutions.

**Dependencies**:
- Imports `services/h3_grid.py` → Also deprecated (see 3.4)

**Removal Steps**:
1. Remove from `services/__init__.py`:
   ```python
   # DELETE this import:
   from .handler_h3_base import h3_base_generate

   # DELETE this registry entry:
   "h3_base_generate": h3_base_generate,
   ```
2. Delete file:
   ```bash
   rm /Users/robertharrison/python_builds/rmhgeoapi/services/handler_h3_base.py
   ```

---

### 3.3 `h3_insert_to_postgis` Handler

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/handler_insert_h3_postgis.py`
**Size**: 8.0KB
**Registered As**: `"h3_insert_to_postgis": insert_h3_to_postgis`

**Evidence of Non-Use**:
```python
# In services/__init__.py - explicitly marked DEPRECATED:
"h3_insert_to_postgis": insert_h3_to_postgis,  # Stage 2: Load GeoParquet → PostGIS (DEPRECATED - use h3_native_streaming_postgis)
```

**What It Does**: Loads pre-generated GeoParquet H3 grid into PostGIS.

**Replaced By**: `h3_native_streaming_postgis` - generates AND inserts in single operation (no intermediate GeoParquet).

**Removal Steps**:
1. Remove from `services/__init__.py`:
   ```python
   # DELETE this import:
   from .handler_insert_h3_postgis import insert_h3_to_postgis

   # DELETE this registry entry:
   "h3_insert_to_postgis": insert_h3_to_postgis,
   ```
2. Delete file:
   ```bash
   rm /Users/robertharrison/python_builds/rmhgeoapi/services/handler_insert_h3_postgis.py
   ```

---

### 3.4 `services/h3_grid.py` - Deprecated Support Module

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/services/h3_grid.py`
**Size**: 52.7KB

**Evidence of Limited Use**:
```bash
grep -r "from services.h3_grid import" --include="*.py" .
# Results:
# services/handler_h3_level4.py  (DEPRECATED - see 3.1)
# services/handler_h3_base.py    (DEPRECATED - see 3.2)
```

**What It Contains**:
- `H3GridService` class - Core H3 generation logic
- `H3GridConfig` - Configuration dataclass
- Various H3 utility functions

**Why Dead**: Only imported by the two deprecated handlers above. The active `h3_native_streaming_postgis` handler uses a different, more efficient approach that doesn't require this module.

**Removal Dependency**: Must remove handlers 3.1 and 3.2 FIRST, then this file.

**Removal Command**:
```bash
rm /Users/robertharrison/python_builds/rmhgeoapi/services/h3_grid.py
```

---

## Category 4: ORPHANED SCHEMA MODULES

**Investigation Complete**: These files do NOT exist - already deleted in previous cleanup.

### 4.1 `schema_blob.py` - DOES NOT EXIST

```bash
# Verified: File not found
find . -name "schema_blob.py" -type f
# Result: No files found
```

**Status**: Already deleted. However, `services/service_blob.py` still tries to import it:
```python
from schema_blob import (
    BlobMetadata,
    ContainerSummary,
    ...
)
```
This confirms `service_blob.py` is truly dead code - it would fail on import.

---

### 4.2 `schema_orchestration.py` - DOES NOT EXIST

```bash
# Verified: File not found
find . -name "schema_orchestration.py" -type f
# Result: No files found
```

**Status**: Already deleted. `services/service_blob.py` also imports from this non-existent module.

**Conclusion**: Category 4 requires no action - schemas already removed. This further confirms `service_blob.py` is dead code with broken imports.

---

## Category 5: REGISTRY CLEANUP

### 5.1 `services/vector/__init__.py` - Remove Dead Exports

**Current State**:
```python
from .tasks import (
    load_vector_file,       # DEAD - not in ALL_HANDLERS
    validate_vector,        # DEAD - not in ALL_HANDLERS
    upload_vector_chunk,    # DEAD - not in ALL_HANDLERS
    prepare_vector_chunks,  # DEAD - commented out in services/__init__.py
    upload_pickled_chunk    # DEAD - commented out in services/__init__.py
)
```

**Required Change**: Remove all imports from `.tasks` after deleting `tasks.py`.

**Updated `__init__.py`**:
```python
"""
Vector ETL services package.

Provides vector file format conversion and PostGIS loading capabilities.

Modules:
    helpers: Conversion utility functions
    converters: Format-specific converters
    process_vector_tasks: Active Stage 1 & 2 handlers
    postgis_handler: VectorToPostGISHandler for database operations
"""

from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from .process_vector_tasks import process_vector_prepare, process_vector_upload
from .postgis_handler import VectorToPostGISHandler

__all__ = [
    # Helpers
    'xy_df_to_gdf',
    'wkt_df_to_gdf',
    'extract_zip_file',
    'DEFAULT_CRS',
    # Active handlers
    'process_vector_prepare',
    'process_vector_upload',
    # Handler class
    'VectorToPostGISHandler',
]
```

---

### 5.2 `services/__init__.py` - Remove Deprecated Handler Registrations

**Lines to Remove**:
```python
# REMOVE these imports:
from .handler_h3_level4 import h3_level4_generate
from .handler_h3_base import h3_base_generate
from .handler_insert_h3_postgis import insert_h3_to_postgis

# REMOVE these registry entries:
"h3_level4_generate": h3_level4_generate,
"h3_base_generate": h3_base_generate,
"h3_insert_to_postgis": insert_h3_to_postgis,
```

---

## Category 6: CONFIG/DEFAULTS CLEANUP

### 6.1 `config/defaults.py` - TaskRoutingDefaults

After removing deprecated handlers, clean up task routing:

**Tasks to Remove from RASTER_TASKS or VECTOR_TASKS**:
```python
# If these exist, remove them:
"h3_level4_generate"
"h3_base_generate"
"h3_insert_to_postgis"
```

---

## Execution Order

**Phase 1: Zero-Import Deletions (Safe)**
1. Delete `/vector/` directory (root level)
2. Delete `services/service_blob.py`

**Phase 2: Legacy Handler Cleanup**
3. Delete `services/vector/tasks.py`
4. Update `services/vector/__init__.py`

**Phase 3: Deprecated H3 Handlers**
5. Remove registry entries from `services/__init__.py`
6. Delete `services/handler_h3_level4.py`
7. Delete `services/handler_h3_base.py`
8. Delete `services/handler_insert_h3_postgis.py`
9. Delete `services/h3_grid.py`

**Phase 4: Schema Cleanup (If Applicable)**
10. Investigate and delete orphaned schema files

**Phase 5: Verification**
11. Run `func start` to verify no import errors
12. Run test suite
13. Deploy to dev environment and test jobs

---

## Risk Assessment

| Category | Risk Level | Rollback Complexity |
|----------|------------|---------------------|
| Category 1 (vector/) | Very Low | Git restore |
| Category 2 (service_blob.py) | Very Low | Git restore |
| Category 3 (deprecated handlers) | Low | Re-add to registry |
| Category 4 (schemas) | Medium | Need investigation first |
| Category 5 (registry cleanup) | Low | Git restore |

---

## Estimated Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Files in /services/ | 53 | 49 | -4 files |
| Files in /vector/ (root) | 14 | 0 | -14 files |
| Registered handlers | 68 | 65 | -3 handlers |
| Total codebase size | ~2.5MB | ~2.35MB | ~150KB reduction |
| Import complexity | High | Lower | Cleaner dependency graph |

---

## Next Steps

1. [ ] Review this document with Robert
2. [ ] Confirm no external dependencies on deprecated code
3. [ ] Create backup branch before deletion
4. [ ] Execute Phase 1 (safest deletions)
5. [ ] Verify function app starts correctly
6. [ ] Execute remaining phases incrementally
7. [ ] Update HISTORY.md with cleanup summary

---

**Document Status**: Ready for Review
**Last Updated**: 31 DEC 2025
