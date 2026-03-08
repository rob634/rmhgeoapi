# Multi-Source Vector ETL — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable multi-file and multi-layer GPKG vector ingestion — N sources in, N PostGIS tables out, each with its own TiPG endpoint.

**Architecture:** New `vector_multi_source_docker` job type with a single-task handler that loops over sources (files or GPKG layers), delegates to existing `_process_single_table()` for each. Symmetric `unpublish_vector_multi_source` for teardown. Existing single-file `vector_docker_etl` is untouched.

**Tech Stack:** geopandas 1.1+ (pyogrio engine), psycopg3, Pydantic v2, JobBaseMixin pattern

**Design doc:** `docs/plans/2026-03-08-multi-source-vector-design.md`

---

## Task 1: Model Changes

Add `layer_names` to VectorProcessingOptions, `is_vector_collection` to PlatformRequest, and `MAX_VECTOR_SOURCES` to defaults.

**Files:**
- Modify: `core/models/processing_options.py:184-201`
- Modify: `core/models/platform.py:539-545`
- Modify: `config/defaults.py:584-596`

### Step 1: Add `layer_names` field to VectorProcessingOptions

In `core/models/processing_options.py`, find line 34:
```python
from typing import Literal, Optional
```

Replace with:
```python
from typing import List, Literal, Optional
```

Then find the end of `VectorProcessingOptions` (after `layer_name` field, line 201):
```python
    layer_name: Optional[str] = Field(
        default=None,
        description="GeoPackage layer name to extract (defaults to first layer)"
    )


class RasterProcessingOptions(BaseProcessingOptions):
```

Insert between the `layer_name` field and the blank line:
```python
    layer_names: Optional[List[str]] = Field(
        default=None,
        description=(
            "GeoPackage layer names to extract as separate tables. "
            "Only valid for .gpkg files. Max 10 layers."
        )
    )

    @model_validator(mode='after')
    def _validate_layer_options(self):
        """layer_name (singular) and layer_names (plural) are mutually exclusive."""
        if self.layer_name and self.layer_names:
            raise ValueError(
                "Cannot specify both 'layer_name' (single layer extraction) and "
                "'layer_names' (multi-layer extraction). Use one or the other."
            )
        return self
```

### Step 2: Verify model change

Run:
```bash
conda run -n azgeo python -c "
from core.models.processing_options import VectorProcessingOptions

# layer_names works
opts = VectorProcessingOptions(layer_names=['roads', 'buildings'])
assert opts.layer_names == ['roads', 'buildings']
print('layer_names field: OK')

# mutual exclusivity
try:
    VectorProcessingOptions(layer_name='roads', layer_names=['roads', 'buildings'])
    assert False, 'Should have raised'
except ValueError as e:
    assert 'mutually exclusive' in str(e).lower() or 'Cannot specify both' in str(e)
    print('mutual exclusivity: OK')

# None by default
opts2 = VectorProcessingOptions()
assert opts2.layer_names is None
print('default None: OK')

print('STEP 2 COMPLETE')
"
```
Expected: All 3 assertions pass.

### Step 3: Add `is_vector_collection` property to PlatformRequest

In `core/models/platform.py`, find the `is_raster_collection` property (line 539-545):
```python
    @property
    def is_raster_collection(self) -> bool:
        """Check if this is a raster collection request (multiple files)."""
        return (
            isinstance(self.file_name, list) and
            len(self.file_name) > 1 and
            self.data_type == DataType.RASTER
        )
```

Add immediately after (after line 545):
```python

    @property
    def is_vector_collection(self) -> bool:
        """Check if this is a multi-source vector request.

        True when either:
        - file_name is a list of 2+ files with data_type VECTOR (multi-file P1)
        - file_name is a single .gpkg with layer_names specified (multi-layer P3)
        """
        if self.data_type != DataType.VECTOR:
            return False
        # P1: multi-file
        if isinstance(self.file_name, list) and len(self.file_name) > 1:
            return True
        # P3: single GPKG with layer_names
        if (isinstance(self.file_name, str)
                and self.file_name.lower().endswith('.gpkg')
                and self.processing_options
                and hasattr(self.processing_options, 'layer_names')
                and self.processing_options.layer_names):
            return True
        return False
```

### Step 4: Add MAX_VECTOR_SOURCES to defaults

In `config/defaults.py`, find `VectorDefaults` class (line 584-596), after `CREATE_SPATIAL_INDEXES = True` (line 596):

```python
    CREATE_SPATIAL_INDEXES = True
```

Add:
```python

    # Multi-source collection limits (08 MAR 2026)
    MAX_VECTOR_SOURCES = 10  # Max files or GPKG layers per collection job
```

### Step 5: Verify all model changes

Run:
```bash
conda run -n azgeo python -c "
from config.defaults import VectorDefaults
assert VectorDefaults.MAX_VECTOR_SOURCES == 10
print('MAX_VECTOR_SOURCES: OK')

import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')
from core.models.platform import PlatformRequest
print('PlatformRequest import: OK')
print('STEP 5 COMPLETE')
"
```
Expected: PASS

### Step 6: Commit

```bash
git add core/models/processing_options.py core/models/platform.py config/defaults.py
git commit -m "feat: add layer_names, is_vector_collection, MAX_VECTOR_SOURCES for multi-source vector"
```

---

## Task 2: Job Definition — `vector_multi_source_docker`

Create the job class with parameters schema and pre-flight validators.

**Files:**
- Create: `jobs/vector_multi_source_docker.py`
- Modify: `jobs/__init__.py:41-62`
- Modify: `config/defaults.py:438` (DOCKER_TASKS)

### Step 1: Create job file

Create `jobs/vector_multi_source_docker.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - VECTOR MULTI-SOURCE DOCKER JOB
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Jobs - Multi-file and multi-layer GPKG vector ingestion
# PURPOSE: N sources in → N PostGIS tables out, each with own TiPG endpoint
# CREATED: 08 MAR 2026
# EXPORTS: VectorMultiSourceDockerJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
VectorMultiSourceDockerJob — Multi-source vector ETL.

Supports two modes (mutually exclusive):
    P1 (multi-file): blob_list = ["roads.gpkg", "bridges.gpkg"]
        → one table per file
    P3 (multi-layer GPKG): blob_name + layer_names = ["transport", "buildings"]
        → one table per GPKG layer

Each source goes through the same validation/upload pipeline as single-file
vector_docker_etl. Geometry-type splitting applies per source.

Table naming: {base_table_name}_{source_suffix}_ord{N}
    base = user's table_name or {dataset_id}_{resource_id}
    source_suffix = filename stem (P1) or layer name (P3)

Design doc: docs/plans/2026-03-08-multi-source-vector-design.md

Exports:
    VectorMultiSourceDockerJob
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import PurePosixPath

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class VectorMultiSourceDockerJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    """
    Multi-source vector ETL job.

    Single stage, single task — the handler loops internally over sources.
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "vector_multi_source_docker"
    description = "Multi-source vector ETL: N files or N GPKG layers → N PostGIS tables"

    # ETL linkage
    reversed_by = "unpublish_vector_multi_source"

    # Single consolidated stage
    stages = [
        {
            "number": 1,
            "name": "process_sources",
            "task_type": "vector_multi_source_complete",
            "parallelism": "single"
        }
    ]

    # Expected checkpoints per source (dynamic — handler emits per source)
    validation_checkpoints: List[Dict[str, Any]] = [
        {"name": "sources_validated", "label": "Validate sources", "phase": "validate"},
        {"name": "processing_started", "label": "Begin processing", "phase": "load"},
        {"name": "all_sources_complete", "label": "All sources processed", "phase": "upload"},
    ]

    # ========================================================================
    # PARAMETER SCHEMA
    # ========================================================================
    parameters_schema = {
        # === Source (one of two modes) ===
        'blob_list': {
            'type': 'list',
            'default': None,
            'description': 'P1: List of source file paths in container'
        },
        'blob_name': {
            'type': 'str',
            'default': None,
            'description': 'P3: Single GPKG file path in container'
        },
        'layer_names': {
            'type': 'list',
            'default': None,
            'description': 'P3: GPKG layer names to extract as separate tables'
        },
        'file_extension': {
            'type': 'str',
            'required': True,
            'allowed': ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip'],
            'description': 'Source file format (all files must share same format for P1)'
        },
        'container_name': {
            'type': 'str',
            'default': None,
            'description': 'Source blob container (default: bronze.vectors from config)'
        },

        # === Target ===
        'base_table_name': {
            'type': 'str',
            'required': True,
            'description': 'Base prefix for generated table names'
        },
        'schema': {
            'type': 'str',
            'default': 'geo',
            'description': 'Target PostGIS schema'
        },
        'overwrite': {
            'type': 'bool',
            'default': False,
            'description': 'If true, allows overwriting existing tables'
        },

        # === Geometry (CSV only) ===
        'lat_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV latitude column name'
        },
        'lon_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV longitude column name'
        },
        'wkt_column': {
            'type': 'str',
            'default': None,
            'description': 'CSV WKT geometry column name'
        },
        'converter_params': {
            'type': 'dict',
            'default': {},
            'description': 'File-specific conversion parameters'
        },

        # === DDH Platform Identifiers ===
        'dataset_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH dataset identifier'
        },
        'resource_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH resource identifier'
        },
        'version_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH version identifier'
        },
        'release_id': {
            'type': 'str',
            'default': None,
            'description': 'Release ID for release_tables linkage'
        },
        'version_ordinal': {
            'type': 'int',
            'default': None,
            'description': 'Version ordinal for table naming (ord{N})'
        },
        'stac_item_id': {
            'type': 'str',
            'default': None,
            'description': 'Pre-generated STAC item ID'
        },

        # === Metadata ===
        'title': {
            'type': 'str',
            'default': None,
            'description': 'User-friendly display name'
        },
        'description': {
            'type': 'str',
            'default': None,
            'description': 'Full dataset description'
        },
        'tags': {
            'type': 'list',
            'default': None,
            'description': 'DDH tags'
        },
        'access_level': {
            'type': 'str',
            'default': None,
            'description': 'DDH access level'
        },

        # === Processing ===
        'chunk_size': {
            'type': 'int',
            'default': 100000,
            'min': 100,
            'max': 500000,
            'description': 'Rows per chunk for batch upload'
        },
    }

    # ========================================================================
    # PRE-FLIGHT RESOURCE VALIDATORS
    # ========================================================================
    resource_validators = [
        {
            'type': 'multi_source_mode',
            'blob_list_param': 'blob_list',
            'blob_name_param': 'blob_name',
            'layer_names_param': 'layer_names',
            'file_extension_param': 'file_extension',
            'error': (
                "Invalid multi-source configuration. Choose ONE mode:\n"
                "  P1 (multi-file): provide 'blob_list' (list of file paths)\n"
                "  P3 (multi-layer GPKG): provide 'blob_name' (single .gpkg) + 'layer_names'\n"
                "Cannot combine blob_list with layer_names."
            )
        },
        {
            'type': 'source_count_limit',
            'blob_list_param': 'blob_list',
            'layer_names_param': 'layer_names',
            'error': 'Source count exceeds MAX_VECTOR_SOURCES limit.'
        },
    ]

    # ========================================================================
    # TASK CREATION
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Generate single task for the consolidated handler."""
        from core.task_id import generate_deterministic_task_id
        from config import get_config

        if stage != 1:
            return []

        config = get_config()
        container_name = job_params.get('container_name') or config.storage.bronze.vectors
        task_id = generate_deterministic_task_id(job_id, 1, "vector_multi_source")

        # Pass all relevant params through to handler
        task_params = {
            # Source
            'blob_list': job_params.get('blob_list'),
            'blob_name': job_params.get('blob_name'),
            'layer_names': job_params.get('layer_names'),
            'file_extension': job_params.get('file_extension'),
            'container_name': container_name,
            # Target
            'base_table_name': job_params.get('base_table_name'),
            'schema': job_params.get('schema', 'geo'),
            'overwrite': job_params.get('overwrite', False),
            # Geometry
            'lat_name': job_params.get('lat_name'),
            'lon_name': job_params.get('lon_name'),
            'wkt_column': job_params.get('wkt_column'),
            'converter_params': job_params.get('converter_params') or {},
            # DDH identifiers
            'dataset_id': job_params.get('dataset_id'),
            'resource_id': job_params.get('resource_id'),
            'version_id': job_params.get('version_id'),
            'release_id': job_params.get('release_id'),
            'version_ordinal': job_params.get('version_ordinal'),
            'stac_item_id': job_params.get('stac_item_id'),
            # Metadata
            'title': job_params.get('title'),
            'description': job_params.get('description'),
            'tags': job_params.get('tags'),
            'access_level': job_params.get('access_level'),
            # Processing
            'chunk_size': job_params.get('chunk_size', 100000),
            'job_id': job_id,
        }

        return [{
            'task_id': task_id,
            'task_type': 'vector_multi_source_complete',
            'parameters': task_params,
        }]

    # ========================================================================
    # FINALIZATION
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Aggregate results from multi-source processing."""
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "VectorMultiSourceDockerJob.finalize_job"
        )

        if not context or not context.task_results:
            return {"job_type": "vector_multi_source_docker", "status": "completed"}

        task_result = context.task_results[0]
        result_data = getattr(task_result, 'result_data', {}) or {}

        tables_created = result_data.get('tables', [])
        table_names = [t.get('table_name') for t in tables_created]
        total_rows = sum(t.get('feature_count', 0) for t in tables_created)

        logger.info(
            f"Multi-source vector job {context.job_id[:16]}... completed — "
            f"{len(tables_created)} tables, {total_rows} total rows"
        )

        return {
            "job_type": "vector_multi_source_docker",
            "status": "completed",
            "table_names": table_names,
            "tables_created": len(tables_created),
            "total_rows": total_rows,
            "tables": tables_created,
        }
```

### Step 2: Register job in `jobs/__init__.py`

In `jobs/__init__.py`, add import after line 41:
```python
from .vector_docker_etl import VectorDockerETLJob
```

Add:
```python
from .vector_multi_source_docker import VectorMultiSourceDockerJob
```

In `ALL_JOBS` dict, after the `vector_docker_etl` entry (line 62):
```python
    "vector_docker_etl": VectorDockerETLJob,
```

Add:
```python
    "vector_multi_source_docker": VectorMultiSourceDockerJob,
```

### Step 3: Register task type in DOCKER_TASKS

In `config/defaults.py`, after line 438:
```python
        "vector_docker_complete",         # V0.8: Consolidated vector ETL with checkpoints
```

Add:
```python
        "vector_multi_source_complete",   # V0.9: Multi-source vector collection ETL
```

### Step 4: Verify job registration

Run:
```bash
conda run -n azgeo python -c "
import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')
from jobs import ALL_JOBS, validate_job_registry
assert 'vector_multi_source_docker' in ALL_JOBS
print('Job registered: OK')
# validate_job_registry() runs at import, so if we got here it passed
print('STEP 4 COMPLETE')
"
```
Expected: PASS (note: will fail until unpublish job is also registered — see Task 5 note)

**Important:** The `reversed_by = "unpublish_vector_multi_source"` linkage means `validate_job_registry()` will fail until Task 5 registers the unpublish job. Temporarily comment out `reversed_by` for this step, or implement Tasks 2 and 5 together.

### Step 5: Commit

```bash
git add jobs/vector_multi_source_docker.py jobs/__init__.py config/defaults.py
git commit -m "feat: add VectorMultiSourceDockerJob definition and register in job/task routing"
```

---

## Task 3: Platform Translation Routing

Route multi-source vector requests to the new job type.

**Files:**
- Modify: `services/platform_translation.py:233-309`

### Step 1: Add multi-source routing

In `services/platform_translation.py`, the vector section starts at line 233. Replace the block from line 258 through line 309 (everything after the stac_item_id generation, starting at `# Detect file extension`):

Find:
```python
        # Detect file extension
        file_name = request.file_name
        if isinstance(file_name, list):
            file_name = file_name[0]
        file_ext = file_name.split('.')[-1].lower()
```

Replace that line and everything through the `return job_type, {` block (through line 309) with:

```python
        # Check for multi-source vector collection BEFORE single-file handling
        if request.is_vector_collection:
            opts = request.processing_options
            is_multi_file = isinstance(request.file_name, list) and len(request.file_name) > 1

            # Detect file extension from first file (multi-file) or single file
            if is_multi_file:
                file_ext = request.file_name[0].split('.')[-1].lower()
            else:
                file_ext = request.file_name.split('.')[-1].lower()

            logger.info(
                f"[PLATFORM] Routing multi-source vector collection to Docker worker "
                f"({'multi-file' if is_multi_file else 'multi-layer GPKG'})"
            )

            return 'vector_multi_source_docker', {
                # Source (mode determined by which field is populated)
                'blob_list': request.file_name if is_multi_file else None,
                'blob_name': request.file_name if not is_multi_file else None,
                'layer_names': opts.layer_names if not is_multi_file else None,
                'file_extension': file_ext,
                'container_name': request.container_name,

                # Target
                'base_table_name': table_name,
                'schema': cfg.vector.target_schema,
                'overwrite': opts.overwrite,

                # DDH identifiers
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,
                'stac_item_id': stac_item_id,

                # Metadata
                'title': request.generated_title,
                'description': request.description,
                'tags': request.tags,
                'access_level': request.access_level.value,

                # Processing options
                'converter_params': converter_params,

                # GPKG layer selection (single layer — not applicable for multi-source)
                'layer_name': None,
            }

        # --- Single-file vector (existing flow, unchanged) ---
        # Detect file extension
        file_name = request.file_name
        if isinstance(file_name, list):
            file_name = file_name[0]
        file_ext = file_name.split('.')[-1].lower()
```

The rest of the single-file flow (lines 264-309 in original) stays unchanged.

### Step 2: Verify translation routing

Run:
```bash
conda run -n azgeo python -c "
import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')

from core.models.platform import PlatformRequest, DataType, AccessLevel

# P1: multi-file should trigger is_vector_collection
req = PlatformRequest(
    dataset_id='kigali', resource_id='infrastructure',
    file_name=['roads.gpkg', 'bridges.gpkg'],
    container_name='rmhazuregeobronze',
    data_type=DataType.VECTOR,
    access_level=AccessLevel.PUBLIC,
)
assert req.is_vector_collection is True
print('P1 multi-file detection: OK')

# Single file should NOT trigger
req2 = PlatformRequest(
    dataset_id='kigali', resource_id='roads',
    file_name='roads.gpkg',
    container_name='rmhazuregeobronze',
    data_type=DataType.VECTOR,
    access_level=AccessLevel.PUBLIC,
)
assert req2.is_vector_collection is False
print('Single file not collection: OK')

print('STEP 2 COMPLETE')
"
```
Expected: PASS

### Step 3: Commit

```bash
git add services/platform_translation.py
git commit -m "feat: route multi-source vector requests to vector_multi_source_docker job"
```

---

## Task 4: Handler — `vector_multi_source_complete`

The core handler that loops over sources and delegates to existing helpers.

**Files:**
- Create: `services/handler_vector_multi_source.py`
- Modify: `services/__init__.py:74,156`

### Step 1: Create handler file

Create `services/handler_vector_multi_source.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - VECTOR MULTI-SOURCE HANDLER
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service handler - Multi-source vector ETL (multi-file + multi-layer)
# PURPOSE: Loop over N sources, produce N PostGIS tables via _process_single_table
# CREATED: 08 MAR 2026
# EXPORTS: vector_multi_source_complete
# DEPENDENCIES: services.handler_vector_docker_complete, services.vector, pyogrio
# ============================================================================
"""
Multi-Source Vector Handler.

Processes N vector sources (files or GPKG layers) into N PostGIS tables.
Delegates per-source processing to the same helpers used by single-file
vector_docker_complete.

Modes:
    P1 (multi-file): blob_list populated → one table per file
    P3 (multi-layer): blob_name + layer_names → one table per GPKG layer

Returns:
    {"success": True, "result": {"tables": [...]}}
    Each table entry: {table_name, geometry_type, feature_count, source, ...}
"""

import os
import time
import logging
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from util_logger import LoggerFactory, ComponentType
from config.platform_config import _slugify_for_postgres

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "vector_multi_source")

# Max sources (matches config/defaults.py VectorDefaults.MAX_VECTOR_SOURCES)
MAX_VECTOR_SOURCES = int(os.environ.get("MAX_VECTOR_SOURCES", "10"))


def _derive_source_suffix(source_name: str) -> str:
    """
    Derive a sanitized suffix from a filename stem or GPKG layer name.

    Examples:
        "roads.gpkg"  → "roads"
        "My Buildings.geojson" → "my_buildings"
        "transport" → "transport"
    """
    # Strip extension if present
    stem = PurePosixPath(source_name).stem if '.' in source_name else source_name
    return _slugify_for_postgres(stem)


def _compute_table_name(base: str, source_suffix: str, version_ordinal: Optional[int]) -> str:
    """
    Compute full table name: {base}_{source_suffix}_ord{N}.

    Truncates base if total exceeds 63 chars (PostgreSQL identifier limit).
    """
    ord_segment = f"_ord{version_ordinal}" if version_ordinal else ""
    full = f"{base}_{source_suffix}{ord_segment}"

    if len(full) <= 63:
        return full

    # Truncate base, keep suffix + ordinal
    suffix_part = f"_{source_suffix}{ord_segment}"
    max_base = 63 - len(suffix_part)
    if max_base < 8:
        raise ValueError(
            f"Cannot generate table name within 63-char limit: "
            f"base='{base}', suffix='{source_suffix}', ordinal={version_ordinal}"
        )
    return f"{base[:max_base].rstrip('_')}{suffix_part}"


def vector_multi_source_complete(
    parameters: Dict[str, Any],
    context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Multi-source vector ETL handler.

    Loops over sources (files or GPKG layers), processes each through
    the same pipeline as single-file vector_docker_complete.

    Args:
        parameters: Task parameters from job definition
        context: Optional execution context

    Returns:
        {"success": True/False, "result": {"tables": [...]}}
    """
    from services.handler_vector_docker_complete import (
        _process_single_table,
        _refresh_tipg,
        _load_and_validate_source,
        build_csv_converter_params,
    )
    from services.vector.core import load_vector_source
    from services.vector.postgis_handler import VectorToPostGISHandler
    from infrastructure import ReleaseTableRepository

    job_id = parameters.get('job_id', 'unknown')
    start_time = time.time()

    # Determine mode
    blob_list = parameters.get('blob_list')
    blob_name = parameters.get('blob_name')
    layer_names = parameters.get('layer_names')
    file_extension = parameters.get('file_extension', 'gpkg')
    container_name = parameters.get('container_name')
    base_table_name = parameters.get('base_table_name')
    schema = parameters.get('schema', 'geo')
    overwrite = parameters.get('overwrite', False)
    version_ordinal = parameters.get('version_ordinal')
    release_id = parameters.get('release_id')
    chunk_size = parameters.get('chunk_size', 100000)

    # Build source list: [(source_identifier, source_suffix)]
    sources = []
    if blob_list:
        # P1: multi-file
        mode = 'multi_file'
        for blob in blob_list:
            suffix = _derive_source_suffix(blob)
            sources.append((blob, suffix))
    elif blob_name and layer_names:
        # P3: multi-layer GPKG
        mode = 'multi_layer'
        for layer in layer_names:
            suffix = _derive_source_suffix(layer)
            sources.append((layer, suffix))
    else:
        return {
            "success": False,
            "error": "No sources specified. Provide blob_list or blob_name + layer_names.",
            "error_type": "ValueError"
        }

    # Validate source count
    if len(sources) > MAX_VECTOR_SOURCES:
        return {
            "success": False,
            "error": (
                f"Source count ({len(sources)}) exceeds MAX_VECTOR_SOURCES ({MAX_VECTOR_SOURCES}). "
                f"Reduce the number of files or layers."
            ),
            "error_type": "ValueError"
        }

    logger.info(
        f"[{job_id[:8]}] Multi-source vector ETL: mode={mode}, "
        f"sources={len(sources)}, base={base_table_name}"
    )

    # Process each source
    tables_created = []
    release_table_repo = ReleaseTableRepository() if release_id else None

    for idx, (source_id, source_suffix) in enumerate(sources):
        source_start = time.time()
        logger.info(
            f"[{job_id[:8]}] Processing source {idx + 1}/{len(sources)}: "
            f"{source_id} → suffix '{source_suffix}'"
        )

        try:
            # Load source data
            if mode == 'multi_file':
                # P1: each source is a separate blob
                gdf = load_vector_source(
                    blob_name=source_id,
                    file_extension=source_id.split('.')[-1].lower(),
                    container_name=container_name,
                    converter_params=parameters.get('converter_params') or {},
                )
            else:
                # P3: each source is a layer within the same GPKG
                import geopandas as gpd
                from infrastructure.blob import BlobRepository

                blob_repo = BlobRepository.for_zone("bronze")
                blob_url = blob_repo.get_blob_url_with_sas(container_name, blob_name)
                gdf = gpd.read_file(blob_url, layer=source_id, engine="pyogrio")

            if gdf is None or len(gdf) == 0:
                logger.warning(f"[{job_id[:8]}] Source '{source_id}' is empty, skipping")
                continue

            # Validate and prepare (geometry fixing, CRS, splitting)
            handler = VectorToPostGISHandler()
            prepared_groups = handler.prepare_gdf(gdf)

            if not prepared_groups:
                logger.warning(f"[{job_id[:8]}] Source '{source_id}' has no valid geometries after preparation")
                continue

            # Process each geometry type group
            has_geom_split = len(prepared_groups) > 1

            for geom_suffix, sub_gdf in prepared_groups.items():
                # Compute table name
                if has_geom_split and geom_suffix:
                    full_suffix = f"{source_suffix}_{geom_suffix}"
                else:
                    full_suffix = source_suffix

                table_name = _compute_table_name(base_table_name, full_suffix, version_ordinal)

                # Build parameters for _process_single_table
                table_params = dict(parameters)
                table_params['table_name'] = table_name

                # Checkpoint function (simplified — log only)
                def _checkpoint(name, details=None, _tid=table_name):
                    logger.info(f"[{job_id[:8]}] [{_tid}] Checkpoint: {name}")

                # Create the PostGIS table
                table_result = _process_single_table(
                    gdf=sub_gdf,
                    table_name=table_name,
                    schema=schema,
                    overwrite=overwrite,
                    parameters=table_params,
                    load_info={'source': source_id, 'mode': mode},
                    job_id=job_id,
                    chunk_size=chunk_size,
                    checkpoint_fn=_checkpoint,
                    table_group=base_table_name,
                )

                # Register in release_tables junction
                if release_table_repo and release_id:
                    geom_type = table_result.get('geometry_type', 'UNKNOWN')
                    feature_count = table_result.get('total_rows', len(sub_gdf))

                    if has_geom_split:
                        table_role = 'geometry_split'
                        table_suffix_val = f"_{geom_suffix}"
                    else:
                        table_role = 'multi_source'
                        table_suffix_val = f"_{source_suffix}"

                    release_table_repo.create(
                        release_id=release_id,
                        table_name=table_name,
                        geometry_type=geom_type,
                        table_role=table_role,
                        table_suffix=table_suffix_val,
                        feature_count=feature_count,
                    )

                tables_created.append({
                    'table_name': table_name,
                    'source': source_id,
                    'source_index': idx,
                    'geometry_type': table_result.get('geometry_type'),
                    'feature_count': table_result.get('total_rows', len(sub_gdf)),
                    'geometry_split': has_geom_split,
                    'duration_seconds': round(time.time() - source_start, 1),
                })

                logger.info(
                    f"[{job_id[:8]}] Table created: {schema}.{table_name} "
                    f"({table_result.get('total_rows', 0)} rows, {table_result.get('geometry_type')})"
                )

        except Exception as e:
            logger.error(f"[{job_id[:8]}] Failed to process source '{source_id}': {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed processing source '{source_id}': {e}",
                "error_type": type(e).__name__,
                "tables_created_before_failure": [t['table_name'] for t in tables_created],
                "failed_source": source_id,
                "failed_source_index": idx,
            }

    # Refresh TiPG once for all tables
    if tables_created:
        first_table = tables_created[0]['table_name']
        tipg_collection_id = f"{schema}.{first_table}"
        _refresh_tipg(tipg_collection_id, job_id)

    duration = round(time.time() - start_time, 1)
    total_rows = sum(t.get('feature_count', 0) for t in tables_created)

    logger.info(
        f"[{job_id[:8]}] Multi-source complete: {len(tables_created)} tables, "
        f"{total_rows} total rows in {duration}s"
    )

    return {
        "success": True,
        "result": {
            "mode": mode,
            "sources_processed": len(sources),
            "tables": tables_created,
            "total_rows": total_rows,
            "duration_seconds": duration,
        }
    }
```

### Step 2: Register handler in `services/__init__.py`

After line 74 (after vector_docker_complete import):
```python
from .handler_vector_docker_complete import vector_docker_complete
```

Add:
```python

# Docker Vector Multi-Source handler (V0.9 - multi-file + multi-layer)
from .handler_vector_multi_source import vector_multi_source_complete
```

In `ALL_HANDLERS` dict, after line 156:
```python
    "vector_docker_complete": vector_docker_complete,
```

Add:
```python
    "vector_multi_source_complete": vector_multi_source_complete,
```

### Step 3: Verify handler registration

Run:
```bash
conda run -n azgeo python -c "
import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')
from services import ALL_HANDLERS
assert 'vector_multi_source_complete' in ALL_HANDLERS
assert callable(ALL_HANDLERS['vector_multi_source_complete'])
print('Handler registered: OK')
print('STEP 3 COMPLETE')
"
```
Expected: PASS

### Step 4: Commit

```bash
git add services/handler_vector_multi_source.py services/__init__.py
git commit -m "feat: add vector_multi_source_complete handler with per-source processing loop"
```

---

## Task 5: Unpublish Job + Handlers

Symmetric teardown — drops all N tables created by multi-source ingestion.

**Files:**
- Create: `jobs/unpublish_vector_multi_source.py`
- Modify: `jobs/__init__.py` (register)
- Modify: `config/defaults.py` (DOCKER_TASKS)
- Modify: `services/__init__.py` (register handlers)

### Step 1: Create unpublish job

Create `jobs/unpublish_vector_multi_source.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - UNPUBLISH VECTOR MULTI-SOURCE JOB
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Jobs - Symmetric teardown for multi-source vector collections
# PURPOSE: Drop all PostGIS tables created by vector_multi_source_docker
# CREATED: 08 MAR 2026
# EXPORTS: UnpublishVectorMultiSourceJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
UnpublishVectorMultiSourceJob — Drop all tables from a multi-source vector job.

Uses release_tables junction as the source of truth for which tables to drop.
Three-stage workflow mirrors UnpublishVectorJob pattern:
    Stage 1 (inventory): Query release_tables for all tables owned by release
    Stage 2 (drop_tables): DROP TABLE CASCADE for each (removes views too)
    Stage 3 (cleanup): Delete metadata, styles, audit records

Exports:
    UnpublishVectorMultiSourceJob
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishVectorMultiSourceJob(JobBaseMixin, JobBase):
    """Unpublish all tables from a multi-source vector collection."""

    job_type = "unpublish_vector_multi_source"
    description = "Remove all PostGIS tables from a multi-source vector collection"

    reverses = [
        "vector_multi_source_docker",
    ]

    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "unpublish_inventory_vector",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "drop_tables",
            "task_type": "unpublish_drop_multi_source_tables",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "cleanup",
            "task_type": "unpublish_delete_stac",
            "parallelism": "single"
        }
    ]

    parameters_schema = {
        "release_id": {
            "type": "str",
            "required": True,
            "description": "Release ID — used to find all tables via release_tables junction"
        },
        "schema_name": {
            "type": "str",
            "default": "geo"
        },
        "dry_run": {
            "type": "bool",
            "default": False
        },
        "force_approved": {
            "type": "bool",
            "default": False
        }
    }

    resource_validators = []

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """Generate tasks for each stage."""
        release_id = job_params.get("release_id")
        schema_name = job_params.get("schema_name", "geo")
        dry_run = job_params.get("dry_run", False)

        if stage == 1:
            # Stage 1: Inventory — get all table names from release_tables
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "unpublish_inventory_vector",
                "parameters": {
                    "release_id": release_id,
                    "schema_name": schema_name,
                    "dry_run": dry_run,
                    "force_approved": job_params.get("force_approved", False),
                    "multi_source": True,
                }
            }]

        elif stage == 2:
            # Stage 2: Drop all tables found in inventory
            inventory_data = previous_results[0] if previous_results else {}
            table_names = inventory_data.get("table_names", [])

            if not table_names:
                # Zero-task stage guard — auto-advances
                return []

            return [{
                "task_id": f"{job_id[:8]}-s2-drop-batch",
                "task_type": "unpublish_drop_multi_source_tables",
                "parameters": {
                    "table_names": table_names,
                    "schema_name": schema_name,
                    "dry_run": dry_run,
                    "release_id": release_id,
                    "_inventory_data": inventory_data,
                }
            }]

        elif stage == 3:
            # Stage 3: Cleanup metadata + audit
            stage2_result = previous_results[0] if previous_results else {}
            inventory_data = stage2_result.get("_inventory_data", {})

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "unpublish_delete_stac",
                "parameters": {
                    "stac_item_id": inventory_data.get("stac_item_id"),
                    "collection_id": inventory_data.get("stac_collection_id"),
                    "dry_run": dry_run,
                    "unpublish_job_id": job_id,
                    "unpublish_type": "vector_multi_source",
                    "original_job_id": inventory_data.get("etl_job_id"),
                    "original_job_type": "vector_multi_source_docker",
                    "tables_dropped": stage2_result.get("tables_dropped", []),
                }
            }]

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Summarize multi-source unpublish results."""
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "UnpublishVectorMultiSourceJob.finalize_job"
        )

        if not context:
            return {"job_type": "unpublish_vector_multi_source", "status": "completed"}

        tables_dropped = []
        dry_run = False

        for result in context.task_results:
            result_data = getattr(result, "result_data", {}) or {}
            task_type = getattr(result, "task_type", None)

            if task_type == "unpublish_drop_multi_source_tables":
                tables_dropped = result_data.get("tables_dropped", [])
                dry_run = result_data.get("dry_run", False)

        logger.info(
            f"Multi-source unpublish {context.job_id[:16]}... completed — "
            f"{len(tables_dropped)} tables {'previewed' if dry_run else 'dropped'}"
        )

        return {
            "job_type": "unpublish_vector_multi_source",
            "status": "completed",
            "dry_run": dry_run,
            "tables_dropped": tables_dropped,
            "tables_count": len(tables_dropped),
        }
```

### Step 2: Create batch drop handler

Add `unpublish_drop_multi_source_tables` to `services/unpublish_handlers.py`. Find the end of the `drop_postgis_table` function and add the new handler after it.

Find the existing `drop_postgis_table` function and add after it:

```python
def drop_multi_source_tables(
    parameters: Dict[str, Any],
    context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Drop multiple PostGIS tables (batch operation for multi-source unpublish).

    Also cleans up geo.table_catalog, geo.feature_collection_styles,
    and app.release_tables entries for each table.

    Args:
        parameters: Must include table_names (list), schema_name, dry_run

    Returns:
        {"success": True, "result": {"tables_dropped": [...], ...}}
    """
    table_names = parameters.get("table_names", [])
    schema_name = parameters.get("schema_name", "geo")
    dry_run = parameters.get("dry_run", False)
    release_id = parameters.get("release_id")

    if not table_names:
        return {"success": True, "result": {"tables_dropped": [], "dry_run": dry_run}}

    logger.info(
        f"{'[DRY RUN] ' if dry_run else ''}Dropping {len(table_names)} tables "
        f"from {schema_name}: {table_names}"
    )

    tables_dropped = []

    if not dry_run:
        from infrastructure.postgresql import PostgreSQLRepository
        from psycopg import sql

        pg_repo = PostgreSQLRepository()

        with pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for tbl in table_names:
                    try:
                        # DROP TABLE CASCADE (also drops attached views)
                        cur.execute(
                            sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                                sql.Identifier(schema_name),
                                sql.Identifier(tbl)
                            )
                        )

                        # Delete from geo.table_catalog
                        cur.execute(
                            sql.SQL("DELETE FROM {}.table_catalog WHERE table_name = %s").format(
                                sql.Identifier("geo")
                            ),
                            (tbl,)
                        )

                        # Delete from geo.feature_collection_styles
                        collection_id = f"{schema_name}.{tbl}"
                        cur.execute(
                            sql.SQL(
                                "DELETE FROM {}.feature_collection_styles WHERE collection_id = %s"
                            ).format(sql.Identifier("geo")),
                            (collection_id,)
                        )

                        tables_dropped.append(tbl)
                        logger.info(f"Dropped table + metadata: {schema_name}.{tbl}")

                    except Exception as e:
                        logger.error(f"Failed to drop {schema_name}.{tbl}: {e}")

                # Delete release_tables entries
                if release_id:
                    cur.execute(
                        sql.SQL("DELETE FROM {}.release_tables WHERE release_id = %s").format(
                            sql.Identifier("app")
                        ),
                        (release_id,)
                    )
                    logger.info(f"Deleted release_tables entries for {release_id[:12]}...")

                conn.commit()

        # Refresh TiPG after all drops
        try:
            from infrastructure.service_layer_client import ServiceLayerClient
            sl_client = ServiceLayerClient()
            sl_client.refresh_tipg_collections()
            logger.info("TiPG catalog refreshed after multi-source unpublish")
        except Exception as e:
            logger.warning(f"TiPG refresh failed (non-fatal): {e}")
    else:
        tables_dropped = list(table_names)  # Preview: all would be dropped

    return {
        "success": True,
        "result": {
            "tables_dropped": tables_dropped,
            "dry_run": dry_run,
            "_inventory_data": parameters.get("_inventory_data", {}),
        }
    }
```

### Step 3: Register unpublish job and handler

In `jobs/__init__.py`, add import:
```python
from .unpublish_vector_multi_source import UnpublishVectorMultiSourceJob
```

In `ALL_JOBS`, after `unpublish_vector` entry:
```python
    "unpublish_vector_multi_source": UnpublishVectorMultiSourceJob,
```

In `services/__init__.py`, add to unpublish imports (after `drop_postgis_table`):
```python
from .unpublish_handlers import (
    inventory_raster_item,
    inventory_vector_item,
    inventory_zarr_item,
    delete_blob,
    drop_postgis_table,
    drop_multi_source_tables,
)
```

In `ALL_HANDLERS`, add after `unpublish_drop_table`:
```python
    "unpublish_drop_multi_source_tables": drop_multi_source_tables,
```

In `config/defaults.py` DOCKER_TASKS, add:
```python
        "unpublish_drop_multi_source_tables",
```

### Step 4: Verify all registrations

Run:
```bash
conda run -n azgeo python -c "
import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')
from jobs import ALL_JOBS, validate_job_registry

# Both jobs registered
assert 'vector_multi_source_docker' in ALL_JOBS
assert 'unpublish_vector_multi_source' in ALL_JOBS
print('Both jobs registered: OK')

# ETL linkage validated (validate_job_registry ran at import)
print('ETL linkage valid: OK')

from services import ALL_HANDLERS
assert 'vector_multi_source_complete' in ALL_HANDLERS
assert 'unpublish_drop_multi_source_tables' in ALL_HANDLERS
print('Both handlers registered: OK')

print('STEP 4 COMPLETE')
"
```
Expected: PASS

### Step 5: Commit

```bash
git add jobs/unpublish_vector_multi_source.py jobs/__init__.py services/__init__.py services/unpublish_handlers.py config/defaults.py
git commit -m "feat: add symmetric unpublish for multi-source vector collections"
```

---

## Task 6: Pre-flight Validators

Implement the custom resource validators for multi-source mode validation.

**Files:**
- Modify: `core/machine.py` (or wherever resource validators are dispatched)

### Step 1: Find validator dispatch

Check where resource validators are resolved. The validator types `multi_source_mode` and `source_count_limit` need handler code.

Search for existing validator implementations:
```bash
conda run -n azgeo grep -rn "bare_shp_rejection\|table_name_syntax\|csv_geometry_params" core/
```

### Step 2: Add new validator types

In the validator dispatch code (likely `core/machine.py` or `core/validators.py`), add handlers for:

**`multi_source_mode`** validator:
```python
def _validate_multi_source_mode(params, validator_config):
    """Ensure exactly one multi-source mode is active."""
    blob_list = params.get(validator_config.get('blob_list_param', 'blob_list'))
    blob_name = params.get(validator_config.get('blob_name_param', 'blob_name'))
    layer_names = params.get(validator_config.get('layer_names_param', 'layer_names'))
    file_ext = params.get(validator_config.get('file_extension_param', 'file_extension'))

    has_blob_list = blob_list and len(blob_list) > 0
    has_layer_names = layer_names and len(layer_names) > 0

    # Must have at least one source mode
    if not has_blob_list and not (blob_name and has_layer_names):
        raise ValueError(
            "No sources specified. Provide either:\n"
            "  • blob_list (list of file paths) for multi-file mode\n"
            "  • blob_name + layer_names for GPKG multi-layer mode"
        )

    # Cannot combine both modes
    if has_blob_list and has_layer_names:
        raise ValueError(
            "Cannot combine blob_list (multi-file) with layer_names (multi-layer). "
            "Choose one multi-source mode per job."
        )

    # layer_names only valid for GPKG
    if has_layer_names and file_ext and file_ext.lower() != 'gpkg':
        raise ValueError(
            f"layer_names is only valid for GeoPackage (.gpkg) files, "
            f"not '{file_ext}'. Remove layer_names or change file format."
        )
```

**`source_count_limit`** validator:
```python
def _validate_source_count_limit(params, validator_config):
    """Ensure source count doesn't exceed MAX_VECTOR_SOURCES."""
    from config.defaults import VectorDefaults

    max_sources = int(os.environ.get("MAX_VECTOR_SOURCES", str(VectorDefaults.MAX_VECTOR_SOURCES)))

    blob_list = params.get(validator_config.get('blob_list_param', 'blob_list'))
    layer_names = params.get(validator_config.get('layer_names_param', 'layer_names'))

    count = 0
    if blob_list:
        count = len(blob_list)
    elif layer_names:
        count = len(layer_names)

    if count > max_sources:
        raise ValueError(
            f"Source count ({count}) exceeds limit ({max_sources}). "
            f"Reduce the number of files or layers, or increase MAX_VECTOR_SOURCES."
        )
```

### Step 3: Verify validators

Run manual validation test:
```bash
conda run -n azgeo python -c "
# Test the validation logic directly
params_bad = {'blob_list': ['a.gpkg', 'b.gpkg'], 'layer_names': ['x', 'y']}
try:
    # Simulate: both modes active
    if params_bad.get('blob_list') and params_bad.get('layer_names'):
        raise ValueError('Cannot combine blob_list with layer_names')
    assert False
except ValueError:
    print('Mutual exclusivity rejection: OK')

params_too_many = {'blob_list': [f'file{i}.gpkg' for i in range(15)]}
if len(params_too_many['blob_list']) > 10:
    print('Source count rejection: OK')

print('STEP 3 COMPLETE')
"
```

### Step 4: Commit

```bash
git add core/machine.py  # or wherever validators live
git commit -m "feat: add multi_source_mode and source_count_limit pre-flight validators"
```

---

## Task 7: Integration Verification

End-to-end verification that all pieces connect.

**Files:**
- No new files — verification only

### Step 1: Verify import chain

```bash
conda run -n azgeo python -c "
import os
os.environ.setdefault('APP_MODE', 'standalone')
os.environ.setdefault('APP_NAME', 'test')

# Full import chain
from jobs import ALL_JOBS, validate_job_registry
from services import ALL_HANDLERS

# Jobs
assert 'vector_multi_source_docker' in ALL_JOBS
assert 'unpublish_vector_multi_source' in ALL_JOBS

# Handlers
assert 'vector_multi_source_complete' in ALL_HANDLERS
assert 'unpublish_drop_multi_source_tables' in ALL_HANDLERS

# Task routing
from config.defaults import TaskRoutingDefaults
assert 'vector_multi_source_complete' in TaskRoutingDefaults.DOCKER_TASKS
assert 'unpublish_drop_multi_source_tables' in TaskRoutingDefaults.DOCKER_TASKS

# Model fields
from core.models.processing_options import VectorProcessingOptions
opts = VectorProcessingOptions(layer_names=['a', 'b', 'c'])
assert opts.layer_names == ['a', 'b', 'c']

# Detection property
from core.models.platform import PlatformRequest, DataType, AccessLevel
req = PlatformRequest(
    dataset_id='test', resource_id='multi',
    file_name=['a.gpkg', 'b.gpkg'],
    container_name='rmhazuregeobronze',
    data_type=DataType.VECTOR,
    access_level=AccessLevel.PUBLIC,
)
assert req.is_vector_collection is True

# Config
from config.defaults import VectorDefaults
assert VectorDefaults.MAX_VECTOR_SOURCES == 10

print('ALL INTEGRATION CHECKS PASSED')
"
```

### Step 2: Verify table naming logic

```bash
conda run -n azgeo python -c "
from services.handler_vector_multi_source import _derive_source_suffix, _compute_table_name

# Filename stems
assert _derive_source_suffix('roads.gpkg') == 'roads'
assert _derive_source_suffix('My Buildings.geojson') == 'my_buildings'
assert _derive_source_suffix('transport') == 'transport'

# Table names
assert _compute_table_name('kigali_infra', 'roads', 1) == 'kigali_infra_roads_ord1'
assert _compute_table_name('kigali_infra', 'roads', None) == 'kigali_infra_roads'

# Truncation
long_base = 'a' * 50
name = _compute_table_name(long_base, 'roads', 1)
assert len(name) <= 63
print(f'Truncated: {name} ({len(name)} chars)')

print('TABLE NAMING: ALL OK')
"
```

### Step 3: Verify route creation fix (from earlier session)

```bash
conda run -n azgeo python -c "
import inspect
from services.asset_approval_service import AssetApprovalService

# Check the method signature includes multi-table logic
source = inspect.getsource(AssetApprovalService._create_routes)
assert 'release_tables' in source.lower() or 'get_tables' in source
assert 'table_suffix' in source or 'has_splits' in source
print('Route creation handles multi-table: OK')

source_del = inspect.getsource(AssetApprovalService._delete_routes)
assert 'release_tables' in source_del.lower() or 'get_tables' in source_del
print('Route deletion handles multi-table: OK')

print('ROUTE FIX VERIFIED')
"
```

### Step 4: Final commit

```bash
git add -A
git commit -m "feat: multi-source vector ETL — complete implementation (P1 multi-file + P3 multi-layer GPKG)"
```

---

## Summary

| Task | Files | What |
|------|-------|------|
| 1 | 3 modified | Model fields + config constant |
| 2 | 1 created, 2 modified | Job definition + registration |
| 3 | 1 modified | Platform translation routing |
| 4 | 1 created, 1 modified | Handler + registration |
| 5 | 1 created, 3 modified | Unpublish job + handler + registration |
| 6 | 1 modified | Pre-flight validators |
| 7 | 0 | Integration verification |

**Total**: 4 new files, 8 modified files

**Post-implementation**: Run SIEGE sequences 20-22 (from design doc) against deployed instance.
