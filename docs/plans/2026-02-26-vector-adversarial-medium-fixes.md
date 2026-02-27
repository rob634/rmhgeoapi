# Vector Adversarial Review — Medium/Low Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 medium/low findings from the adversarial vector workflow review.

**Architecture:** All fixes are surgical — no new abstractions, no refactoring. Each task touches 1-2 files and can be validated independently.

**Tech Stack:** Python 3.12, geopandas, shapely, psycopg, pytest

---

## Task 1: Per-row WKT error handling (M-2)

**Problem:** `wkt_df_to_gdf()` applies `wkt.loads` to every row. One bad WKT value crashes the entire file. The CSV sample validation only checks the first 5 rows.

**Files:**
- Modify: `services/vector/helpers.py:89-119`
- Test: `tests/unit/test_wkt_error_handling.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_wkt_error_handling.py
"""Tests for per-row WKT error handling in wkt_df_to_gdf."""
import pandas as pd
import pytest
from services.vector.helpers import wkt_df_to_gdf


def test_wkt_valid_rows_all_pass():
    """All valid WKT strings produce a complete GeoDataFrame."""
    df = pd.DataFrame({
        'name': ['a', 'b', 'c'],
        'wkt': ['POINT (0 0)', 'POINT (1 1)', 'POINT (2 2)']
    })
    gdf = wkt_df_to_gdf(df, 'wkt')
    assert len(gdf) == 3
    assert gdf.geometry.is_valid.all()


def test_wkt_single_bad_row_does_not_crash():
    """A single bad WKT value drops the row instead of crashing."""
    df = pd.DataFrame({
        'name': ['good', 'bad', 'good2'],
        'wkt': ['POINT (0 0)', 'NOT_WKT_AT_ALL', 'POINT (2 2)']
    })
    gdf = wkt_df_to_gdf(df, 'wkt')
    assert len(gdf) == 2
    assert list(gdf['name']) == ['good', 'good2']


def test_wkt_all_bad_rows_raises():
    """If ALL rows have bad WKT, raise ValueError (nothing to return)."""
    df = pd.DataFrame({
        'name': ['a', 'b'],
        'wkt': ['GARBAGE', 'ALSO_GARBAGE']
    })
    with pytest.raises(ValueError, match="valid geometries"):
        wkt_df_to_gdf(df, 'wkt')


def test_wkt_empty_string_treated_as_bad():
    """Empty string WKT values are dropped."""
    df = pd.DataFrame({
        'name': ['a', 'b'],
        'wkt': ['POINT (1 1)', '']
    })
    gdf = wkt_df_to_gdf(df, 'wkt')
    assert len(gdf) == 1


def test_wkt_none_values_treated_as_bad():
    """None/NaN WKT values are dropped."""
    df = pd.DataFrame({
        'name': ['a', 'b'],
        'wkt': ['POINT (1 1)', None]
    })
    gdf = wkt_df_to_gdf(df, 'wkt')
    assert len(gdf) == 1
```

**Step 2: Run test to verify it fails**

Run: `conda run -n azgeo pytest tests/unit/test_wkt_error_handling.py -v`
Expected: `test_wkt_single_bad_row_does_not_crash` FAILS (currently crashes on bad WKT)

**Step 3: Implement per-row WKT parsing**

Replace the try/except block in `wkt_df_to_gdf()` (`services/vector/helpers.py:113-119`):

```python
    # Parse WKT strings to geometries, handling per-row errors
    def _safe_wkt_load(val):
        if pd.isna(val) or val == '':
            return None
        try:
            return wkt.loads(val)
        except (ShapelyError, Exception):
            return None

    geometry = df[wkt_column].apply(_safe_wkt_load)
    bad_mask = geometry.isna()
    bad_count = bad_mask.sum()

    if bad_count == len(df):
        raise ValueError(
            f"All {len(df)} rows have invalid or empty WKT in column '{wkt_column}'. "
            f"No valid geometries to process."
        )

    if bad_count > 0:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Dropped {bad_count}/{len(df)} rows with invalid WKT in column '{wkt_column}'"
        )
        df = df[~bad_mask].copy()
        geometry = geometry[~bad_mask]

    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
    return gdf
```

**Step 4: Run test to verify it passes**

Run: `conda run -n azgeo pytest tests/unit/test_wkt_error_handling.py -v`
Expected: All 5 tests PASS

**Step 5: Run existing tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

**Step 6: Commit**

```bash
git add services/vector/helpers.py tests/unit/test_wkt_error_handling.py
git commit -m "Per-row WKT error handling — drop bad rows instead of crashing (M-2)"
```

---

## Task 2: Preserve exception context in platform_job_submit (M-5)

**Problem:** `create_and_submit_job()` catches generic `Exception`, returns `None`, and loses all context. The caller raises `RuntimeError("Failed to create CoreMachine job")` with no detail. Also, if the DB write succeeds but Service Bus send fails, an orphaned QUEUED job is left behind.

**Files:**
- Modify: `services/platform_job_submit.py:220-236`
- Modify: `triggers/platform/submit.py` (the caller, ~line 395)

**Step 1: Fix non-atomic job+queue by marking job FAILED on send failure**

In `services/platform_job_submit.py`, inside `_try_create_job()`, wrap the Service Bus send in a try/except that marks the job FAILED if sending fails. Find the Service Bus send block (after `job_repo.create_job(job_record)`, around lines 183-198):

```python
            # Submit to Service Bus
            try:
                service_bus = ServiceBusRepository()
                queue_message = JobQueueMessage(
                    job_id=job_id,
                    job_type=current_job_type,
                    parameters=validated_params,
                    stage=1,
                    correlation_id=str(uuid.uuid4())[:8]
                )

                message_id = service_bus.send_message(
                    config.service_bus_jobs_queue,
                    queue_message
                )
                logger.info(f"Submitted job {job_id[:16]} to queue (message_id: {message_id})")
            except Exception as send_err:
                # Job record exists but message never queued — mark FAILED to prevent orphan
                logger.error(f"Service Bus send failed for job {job_id[:16]}: {send_err}")
                try:
                    job_repo.update_job_status(job_id, JobStatus.FAILED, error=f"Queue send failed: {send_err}")
                except Exception:
                    logger.error(f"Failed to mark orphaned job {job_id[:16]} as FAILED")
                raise RuntimeError(f"Job created but queue send failed: {send_err}") from send_err

            return job_id
```

**Step 2: Preserve exception context in outer handler**

Replace the generic `except Exception` at lines 234-236:

```python
    except Exception as e:
        logger.error(f"Failed to create/submit job: {e}", exc_info=True)
        raise RuntimeError(f"Job creation failed: {e}") from e
```

This re-raises with context instead of returning `None`.

**Step 3: Update caller in submit.py**

In `triggers/platform/submit.py`, the caller currently does:
```python
job_id = create_and_submit_job(job_type, job_params, request_id)
if not job_id:
    raise RuntimeError("Failed to create CoreMachine job")
```

Since `create_and_submit_job` now raises instead of returning `None`, simplify to:
```python
job_id = create_and_submit_job(job_type, job_params, request_id)
```

Remove the `if not job_id` check — the function now always returns a job_id or raises.

**Step 4: Run existing tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

**Step 5: Commit**

```bash
git add services/platform_job_submit.py triggers/platform/submit.py
git commit -m "Preserve exception context in job submit, mark orphaned jobs FAILED (M-5)"
```

---

## Task 3: Standardize unpublish error returns (M-7)

**Problem:** Unpublish handlers return `{"success": False, "error": "...", "error_type": "..."}` — a different shape from the `ErrorResponse` Pydantic model used by the vector docker handler. Full `ErrorResponse` adoption would be over-engineering for internal task handlers — but the error dict shape should at least be consistent.

**Approach:** This is a documentation/convention issue more than a code bug. The unpublish handlers are internal task handlers consumed by CoreMachine, not B2B API responses. `ErrorResponse` (from `core/errors.py`) is designed for external-facing responses. The internal handlers use plain dicts. Rather than force Pydantic models onto internal handlers, standardize the dict shape. All internal error dicts should include: `success`, `error`, `error_type`.

**Files:**
- Modify: `services/unpublish_handlers.py` (audit existing returns)

**Step 1: Audit all error returns in unpublish_handlers.py**

Search for all `"success": False` returns. Verify each has `error` and `error_type` keys. The ones already fixed in Fix 2 (approval guard) now include `error_type`. Check the remaining ones.

Specifically look for any returns that have `"success": False` but are missing `error_type`. Add `error_type` where missing.

Common pattern to ensure across all error returns:
```python
return {
    "success": False,
    "error": "descriptive message",
    "error_type": "CategoryName",  # Must be present
}
```

**Step 2: Run existing tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

**Step 3: Commit**

```bash
git add services/unpublish_handlers.py
git commit -m "Standardize error_type on all unpublish handler error returns (M-7)"
```

---

## Task 4: Replace manual .get() proliferation in create_tasks_for_stage (M-9)

**Problem:** `VectorDockerETLJob.create_tasks_for_stage()` has 30+ individual `.get()` calls copying parameters one by one. This is a maintenance burden — adding a new parameter requires touching both `parameters_schema` and `create_tasks_for_stage`.

**Files:**
- Modify: `jobs/vector_docker_etl.py:350-408`
- Test: `tests/job_system/test_task_creation.py` (verify existing tests still pass)

**Step 1: Write a test for parameter passthrough**

```python
# Add to tests/job_system/test_task_creation.py

def test_vector_docker_etl_passes_all_schema_params():
    """All parameters_schema keys should be available in task parameters."""
    from jobs.vector_docker_etl import VectorDockerETLJob

    # Build minimal valid job_params with all schema keys
    job_params = {
        'blob_name': 'test.csv',
        'file_extension': 'csv',
        'table_name': 'test_table',
        'lat_name': 'lat',
        'lon_name': 'lon',
    }

    tasks = VectorDockerETLJob.create_tasks_for_stage(
        stage=1,
        job_params=job_params,
        job_id='a' * 64
    )

    assert len(tasks) == 1
    task_params = tasks[0]['parameters']

    # All explicitly provided params should be in task parameters
    assert task_params['blob_name'] == 'test.csv'
    assert task_params['table_name'] == 'test_table'
    assert task_params['lat_name'] == 'lat'
```

**Step 2: Refactor create_tasks_for_stage to use explicit include list**

Replace lines 350-407 with:

```python
        # Parameters to pass through to handler (explicit include list)
        _PASSTHROUGH_PARAMS = [
            # Source
            'blob_name', 'file_extension',
            # Target
            'table_name', 'overwrite',
            # Geometry
            'lat_name', 'lon_name', 'wkt_column', 'layer_name',
            'converter_params', 'geometry_params',
            # Column mapping
            'column_mapping', 'temporal_property',
            # Metadata
            'title', 'description', 'attribution', 'license', 'keywords',
            # DDH identifiers
            'dataset_id', 'resource_id', 'version_id', 'release_id',
            'stac_item_id', 'tags', 'access_level',
            # Style
            'style',
            # Processing
            'chunk_size', 'indexes', 'create_tile_view', 'max_tile_vertices',
            # Platform tracking
            '_platform_job_id',
        ]

        task_params = {k: job_params.get(k) for k in _PASSTHROUGH_PARAMS}

        # Override computed values
        task_params['job_id'] = job_id
        task_params['container_name'] = container_name
        task_params['schema'] = job_params.get('schema', 'geo')

        # Apply defaults for dict/int params that need non-None defaults
        if task_params.get('converter_params') is None:
            task_params['converter_params'] = {}
        if task_params.get('geometry_params') is None:
            task_params['geometry_params'] = {}
        if task_params.get('chunk_size') is None:
            task_params['chunk_size'] = 20000
        if task_params.get('indexes') is None:
            task_params['indexes'] = {'spatial': True, 'attributes': [], 'temporal': []}
        if task_params.get('max_tile_vertices') is None:
            task_params['max_tile_vertices'] = 256

        return [{
            'task_id': task_id,
            'task_type': 'vector_docker_complete',
            'parameters': task_params,
        }]
```

**Step 3: Run tests**

Run: `conda run -n azgeo pytest tests/job_system/test_task_creation.py -v`
Expected: All PASS

**Step 4: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

**Step 5: Commit**

```bash
git add jobs/vector_docker_etl.py tests/job_system/test_task_creation.py
git commit -m "Replace 30+ manual .get() calls with explicit passthrough list (M-9)"
```

---

## Task 5: Centralize EventCallback type alias (L-1)

**Problem:** `EventCallback = Callable[[str, Dict[str, Any]], None]` is defined identically in both `services/vector/core.py:43` and `services/vector/postgis_handler.py:41`.

**Files:**
- Modify: `services/vector/__init__.py` (add the type alias)
- Modify: `services/vector/core.py:43` (import instead of define)
- Modify: `services/vector/postgis_handler.py:39-41` (import instead of define)

**Step 1: Read services/vector/__init__.py to see current exports**

Read the file to understand what's currently exported.

**Step 2: Add EventCallback to services/vector/__init__.py**

Add at the top of the file:
```python
from typing import Dict, Any, Callable

# Shared type alias for event callback functions
# Signature: callback(event_name: str, details: dict) -> None
EventCallback = Callable[[str, Dict[str, Any]], None]
```

**Step 3: Update core.py to import instead of define**

Replace line 43 in `services/vector/core.py`:
```python
# BEFORE
EventCallback = Callable[[str, Dict[str, Any]], None]

# AFTER
from services.vector import EventCallback
```

Remove `Callable` from the typing import on line 34 if no longer needed (check other uses first).

**Step 4: Update postgis_handler.py to import instead of define**

Replace lines 39-41 in `services/vector/postgis_handler.py`:
```python
# BEFORE
# Type alias for event callback function
# Signature: callback(event_name: str, details: dict) -> None
EventCallback = Callable[[str, Dict[str, Any]], None]

# AFTER
from services.vector import EventCallback
```

Remove `Callable` from the typing import on line 29 if no longer needed.

**Step 5: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions (type alias is the same, just imported from a single location)

**Step 6: Commit**

```bash
git add services/vector/__init__.py services/vector/core.py services/vector/postgis_handler.py
git commit -m "Centralize EventCallback type alias in services/vector/__init__.py (L-1)"
```

---

## Execution Order

Tasks are independent — can be done in any order or in parallel.

| Task | Finding | Effort | Risk |
|------|---------|--------|------|
| 1 | M-2: WKT per-row error handling | 20 min | Low |
| 2 | M-5: Job submit exception context | 15 min | Low-Medium |
| 3 | M-7: Standardize error_type | 10 min | Near zero |
| 4 | M-9: Passthrough param list | 15 min | Low |
| 5 | L-1: Centralize EventCallback | 5 min | Near zero |
| **Total** | | **~65 min** | |
