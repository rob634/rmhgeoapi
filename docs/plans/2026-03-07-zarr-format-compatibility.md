# Zarr Format Compatibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix SG13-1 (rechunk codec crash), SG13-4 (status container mismatch), and SG13-6 (NetCDF Zarr unreadable) by making `_build_zarr_encoding()` format-aware and adding `zarr_format` as a pipeline parameter.

**Architecture:** One shared encoding function supports both Zarr v2 (`numcodecs.Blosc` + `"compressor"` key) and v3 (`zarr.codecs.BloscCodec` + `"compressors"` key). The `zarr_format` parameter flows from `ZarrProcessingOptions` → job params → handler → `_build_zarr_encoding()` → `ds.to_zarr(zarr_format=N)`. Default is v3 (forward-looking), but callers can request v2 for TiTiler compat until titiler-pgstac 2.1.0 upgrade.

**Tech Stack:** zarr 3.1.5, xarray, numcodecs 0.16.5, Pydantic v2

**Fixes:** SG13-1 (HIGH), SG13-4 (HIGH), SG13-6 (MEDIUM)

---

## Summary of Changes

| # | File | Change |
|---|------|--------|
| 1 | `core/models/processing_options.py` | Add `zarr_format` field to `ZarrProcessingOptions` |
| 2 | `services/handler_netcdf_to_zarr.py` | Make `_build_zarr_encoding()` format-aware, pass `zarr_format` to `ds.to_zarr()` |
| 3 | `services/handler_ingest_zarr.py` | Pass `zarr_format` to `_build_zarr_encoding()` and `ds.to_zarr()` |
| 4 | `jobs/netcdf_to_zarr.py` | Thread `zarr_format` param into Stage 4 task params |
| 5 | `jobs/ingest_zarr.py` | Thread `zarr_format` param into Stage 2 rechunk task params |
| 6 | `triggers/trigger_platform_status.py` | Fix container fallback for zarr data types (SG13-4) |
| 7 | `tests/unit/test_zarr_encoding.py` | New test file for `_build_zarr_encoding()` |

---

## Task 1: Add `zarr_format` to ZarrProcessingOptions

**Files:**
- Modify: `core/models/processing_options.py:283-340`
- Test: `tests/unit/test_zarr_encoding.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/test_zarr_encoding.py`:

```python
"""Tests for Zarr format encoding compatibility (SG13-1, SG13-6)."""
import pytest
from core.models.processing_options import ZarrProcessingOptions


class TestZarrProcessingOptionsFormat:
    """ZarrProcessingOptions.zarr_format field."""

    def test_default_zarr_format_is_3(self):
        opts = ZarrProcessingOptions()
        assert opts.zarr_format == 3

    def test_zarr_format_2_accepted(self):
        opts = ZarrProcessingOptions(zarr_format=2)
        assert opts.zarr_format == 2

    def test_zarr_format_3_accepted(self):
        opts = ZarrProcessingOptions(zarr_format=3)
        assert opts.zarr_format == 3

    def test_zarr_format_invalid_rejected(self):
        with pytest.raises(Exception):  # ValidationError
            ZarrProcessingOptions(zarr_format=1)

    def test_zarr_format_invalid_4_rejected(self):
        with pytest.raises(Exception):
            ZarrProcessingOptions(zarr_format=4)
```

**Step 2: Run test to verify it fails**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py::TestZarrProcessingOptionsFormat -v`
Expected: FAIL — `zarr_format` field does not exist

**Step 3: Write minimal implementation**

In `core/models/processing_options.py`, add after the `rechunk` field (line 333):

```python
    zarr_format: Literal[2, 3] = Field(
        default=3,
        description="Zarr format version: 2 (legacy, TiTiler <2.1 compat) or 3 (default, native v3)"
    )
```

Add `Literal` to the imports if not already imported (it is — line 304 already uses it).

**Step 4: Run test to verify it passes**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py::TestZarrProcessingOptionsFormat -v`
Expected: PASS (5/5)

**Step 5: Commit**

```bash
git add core/models/processing_options.py tests/unit/test_zarr_encoding.py
git commit -m "feat: add zarr_format field to ZarrProcessingOptions (SG13-1)"
```

---

## Task 2: Make `_build_zarr_encoding()` Format-Aware

**Files:**
- Modify: `services/handler_netcdf_to_zarr.py:54-121`
- Test: `tests/unit/test_zarr_encoding.py` (append)

**Step 1: Write the failing tests**

Append to `tests/unit/test_zarr_encoding.py`:

```python
import numpy as np
import xarray as xr


def _make_test_dataset():
    """Create a minimal xarray Dataset for encoding tests."""
    return xr.Dataset({
        "temperature": xr.DataArray(
            np.zeros((3, 10, 20)),
            dims=["time", "lat", "lon"],
        )
    })


class TestBuildZarrEncodingV3:
    """_build_zarr_encoding with zarr_format=3 (default)."""

    def test_v3_returns_blosccodec(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=3)
        compressors = encoding["temperature"]["compressors"]
        from zarr.codecs import BloscCodec
        assert isinstance(compressors[0], BloscCodec)

    def test_v3_uses_compressors_key(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=3)
        assert "compressors" in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]

    def test_v3_chunks_correct(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        target_chunks, encoding = _build_zarr_encoding(
            ds, spatial_chunk_size=256, time_chunk_size=1, zarr_format=3
        )
        assert target_chunks["time"] == 1
        assert target_chunks["lat"] == 10  # clamped to dim size
        assert target_chunks["lon"] == 20  # clamped to dim size


class TestBuildZarrEncodingV2:
    """_build_zarr_encoding with zarr_format=2."""

    def test_v2_returns_numcodecs_blosc(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=2)
        compressor = encoding["temperature"]["compressor"]
        import numcodecs
        assert isinstance(compressor, numcodecs.Blosc)

    def test_v2_uses_compressor_key(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=2)
        assert "compressor" in encoding["temperature"]
        assert "compressors" not in encoding["temperature"]

    def test_v2_compressor_params(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(
            ds, compressor_name="zstd", compression_level=3, zarr_format=2
        )
        compressor = encoding["temperature"]["compressor"]
        assert compressor.cname == "zstd"
        assert compressor.clevel == 3


class TestBuildZarrEncodingNone:
    """_build_zarr_encoding with compressor='none'."""

    def test_v3_no_compressor(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, compressor_name="none", zarr_format=3)
        assert "compressors" not in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]

    def test_v2_no_compressor(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, compressor_name="none", zarr_format=2)
        assert "compressors" not in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]
```

**Step 2: Run tests to verify they fail**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py -v -k "BuildZarr"`
Expected: FAIL — `_build_zarr_encoding()` does not accept `zarr_format` parameter

**Step 3: Write implementation**

Replace `_build_zarr_encoding` in `services/handler_netcdf_to_zarr.py:54-121` with:

```python
def _build_zarr_encoding(ds, spatial_chunk_size=256, time_chunk_size=1,
                         compressor_name="lz4", compression_level=5,
                         zarr_format=3):
    """
    Build optimized Zarr encoding for tile-serving performance.

    Generates target chunk sizes and per-variable encoding dicts for
    ds.to_zarr(encoding=...). Only encodes data variables, not coordinates.

    Args:
        ds: xarray.Dataset to encode
        spatial_chunk_size: Chunk size for spatial dims (lat/lon/y/x), clamped to dim size
        time_chunk_size: Chunk size for time dim, clamped to dim size
        compressor_name: "lz4", "zstd", or "none"
        compression_level: 1-9 (passed to Blosc clevel)
        zarr_format: 2 or 3 — determines codec objects and encoding keys

    Returns:
        (target_chunks, encoding) tuple:
            target_chunks: dict for ds.chunk() — {dim_name: chunk_size}
            encoding: dict for ds.to_zarr(encoding=...) — {var_name: {...}}
    """
    # Detect spatial and time dimensions
    spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
    time_names = {"time", "t"}

    target_chunks = {}
    for dim_name, dim_size in ds.sizes.items():
        dim_lower = dim_name.lower()
        if dim_lower in spatial_names:
            target_chunks[dim_name] = min(spatial_chunk_size, dim_size)
        elif dim_lower in time_names:
            target_chunks[dim_name] = min(time_chunk_size, dim_size)
        else:
            target_chunks[dim_name] = dim_size

    # Build compressor — format-specific codec objects
    compressor_obj = None
    if compressor_name != "none":
        if zarr_format == 2:
            import numcodecs
            compressor_obj = numcodecs.Blosc(
                cname=compressor_name,
                clevel=compression_level,
                shuffle=numcodecs.Blosc.BITSHUFFLE,
            )
        else:
            from zarr.codecs import BloscCodec
            compressor_obj = BloscCodec(
                cname=compressor_name,
                clevel=compression_level,
                shuffle="bitshuffle",
            )

    # Build per-variable encoding (data vars only, not coords)
    encoding = {}
    for var_name in ds.data_vars:
        var = ds[var_name]
        var_chunks = tuple(
            target_chunks.get(dim, ds.sizes[dim])
            for dim in var.dims
        )
        enc = {"chunks": var_chunks}
        if compressor_obj is not None:
            if zarr_format == 2:
                enc["compressor"] = compressor_obj
            else:
                enc["compressors"] = [compressor_obj]
        encoding[var_name] = enc

    logger.info(
        f"_build_zarr_encoding: zarr_format={zarr_format}, "
        f"spatial={spatial_chunk_size}, "
        f"time={time_chunk_size}, compressor={compressor_name}(L{compression_level}), "
        f"{len(encoding)} vars encoded, chunks={target_chunks}"
    )

    return target_chunks, encoding
```

**Step 4: Run tests to verify they pass**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py -v`
Expected: PASS (all 14 tests)

**Step 5: Commit**

```bash
git add services/handler_netcdf_to_zarr.py tests/unit/test_zarr_encoding.py
git commit -m "feat: make _build_zarr_encoding format-aware for v2/v3 (SG13-1, SG13-6)"
```

---

## Task 3: Thread `zarr_format` Through NetCDF-to-Zarr Pipeline

**Files:**
- Modify: `services/handler_netcdf_to_zarr.py:615-808` (netcdf_convert handler)
- Modify: `jobs/netcdf_to_zarr.py` (Stage 4 task creation)

**Step 1: Update `netcdf_convert` handler to read and use `zarr_format`**

In `services/handler_netcdf_to_zarr.py`, in the `netcdf_convert` function:

After line 665 (`compression_level = params.get("compression_level", 5)`), add:
```python
    zarr_format = params.get("zarr_format", 3)
```

Update the `_build_zarr_encoding` call at line 794 to pass `zarr_format`:
```python
        target_chunks, encoding = _build_zarr_encoding(
            ds, spatial_chunk_size, time_chunk_size,
            compressor_name, compression_level,
            zarr_format=zarr_format,
        )
```

Update the `ds.to_zarr` call at line 802 to pass `zarr_format`:
```python
        ds.to_zarr(
            zarr_az_url,
            mode="w",
            consolidated=True,
            storage_options=storage_options,
            encoding=encoding,
            zarr_format=zarr_format,
        )
```

**Step 2: Thread `zarr_format` from job params into Stage 4 task params**

In `jobs/netcdf_to_zarr.py`, find the Stage 4 task creation (`create_tasks_for_stage` for stage 4). The task params dict that feeds into `netcdf_convert` needs `zarr_format`. Search for where `"zarr_container"` is set in the stage 4 params block and add `"zarr_format"` next to it:

```python
"zarr_format": job_params.get("zarr_format", 3),
```

The `job_params` dict is built from `ZarrProcessingOptions` during translation in `platform_translation.py`. Verify the `zarr_format` field passes through — it should since Pydantic model fields get serialized into the job params dict automatically.

**Step 3: Run the full test suite**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add services/handler_netcdf_to_zarr.py jobs/netcdf_to_zarr.py
git commit -m "feat: thread zarr_format through netcdf_to_zarr pipeline (SG13-6)"
```

---

## Task 4: Thread `zarr_format` Through Ingest-Zarr Rechunk Pipeline

**Files:**
- Modify: `services/handler_ingest_zarr.py:688-830` (ingest_zarr_rechunk handler)
- Modify: `jobs/ingest_zarr.py` (Stage 2 rechunk task creation)

**Step 1: Update `ingest_zarr_rechunk` handler**

In `services/handler_ingest_zarr.py`, in the `ingest_zarr_rechunk` function:

After line 727 (`compression_level = params.get("compression_level", 5)`), add:
```python
    zarr_format = params.get("zarr_format", 3)
```

Update the `_build_zarr_encoding` call at line 777:
```python
        target_chunks, encoding = _build_zarr_encoding(
            ds, spatial_chunk_size, time_chunk_size,
            compressor_name, compression_level,
            zarr_format=zarr_format,
        )
```

Update the `ds.to_zarr` call at line 795:
```python
        ds.to_zarr(
            target_az_url,
            mode="w",
            consolidated=True,
            storage_options=target_storage_options,
            encoding=encoding,
            zarr_format=zarr_format,
        )
```

**Step 2: Thread `zarr_format` from job params into Stage 2 rechunk task params**

In `jobs/ingest_zarr.py`, find the rechunk task creation block (where `"rechunk"` is checked and `ingest_zarr_rechunk` task type is selected). Add `"zarr_format"` to the task params dict:

```python
"zarr_format": job_params.get("zarr_format", 3),
```

**Step 3: Run tests**

Run: `conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add services/handler_ingest_zarr.py jobs/ingest_zarr.py
git commit -m "feat: thread zarr_format through ingest_zarr rechunk pipeline (SG13-1)"
```

---

## Task 5: Fix Status Endpoint Container for Zarr (SG13-4)

**Files:**
- Modify: `triggers/trigger_platform_status.py:695-701`

**Step 1: Fix the container fallback**

The bug is at line 701: `outputs["container"] = container or "silver-cogs"`. This defaults ALL data types to `silver-cogs`, but zarr stores live in `silver-zarr`.

Replace lines 692-701 with:

```python
    # Raster outputs
    if release.blob_path:
        outputs["blob_path"] = release.blob_path
        # Container from job_result (not stored on release)
        container = None
        if job_result:
            cog_data = job_result.get('cog', {})
            if isinstance(cog_data, dict):
                container = cog_data.get('cog_container')
            # SG13-4: Check zarr result for container
            if not container:
                zarr_data = job_result.get('zarr_store_url', '')
                if zarr_data and zarr_data.startswith('abfs://'):
                    container = zarr_data.replace('abfs://', '').split('/')[0]
        if not container:
            # Infer from data_type if available
            from core.models.asset import DataType
            asset_data_type = getattr(release, 'data_type', None)
            if asset_data_type in (DataType.ZARR, DataType.RASTER_ZARR, 'zarr', 'raster_zarr'):
                container = "silver-zarr"
            else:
                container = "silver-cogs"
        outputs["container"] = container
```

Note: This requires knowing the data_type on the release or from context. Check how `data_type` flows into this function. If `data_type` is not available on the release object, the `job_result` zarr_store_url check is the primary path.

**Alternative simpler approach**: If `release.blob_path` starts with `zarr/`, the container is `silver-zarr`. If not, `silver-cogs`.

```python
    # Raster outputs
    if release.blob_path:
        outputs["blob_path"] = release.blob_path
        # Container from job_result
        container = None
        if job_result:
            cog_data = job_result.get('cog', {})
            if isinstance(cog_data, dict):
                container = cog_data.get('cog_container')
            if not container:
                zarr_url = job_result.get('zarr_store_url', '')
                if zarr_url and zarr_url.startswith('abfs://'):
                    container = zarr_url.replace('abfs://', '').split('/')[0]
        # SG13-4: Default based on blob_path prefix
        if not container:
            container = "silver-zarr" if release.blob_path.startswith("zarr/") else "silver-cogs"
        outputs["container"] = container
```

Choose the approach that aligns with how `blob_path` is structured. Inspect a few release blob_paths to confirm the `zarr/` prefix convention.

**Step 2: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "fix: status endpoint reports correct container for zarr releases (SG13-4)"
```

---

## Task 6: Update Documentation and Memory

**Files:**
- Modify: `docs_claude/ERRORS_AND_FIXES.md` — add SG13-1, SG13-4, SG13-6 entries
- Modify: `~/.claude/projects/.../memory/MEMORY.md` — mark bugs as fixed
- Modify: `docs/agent_review/AGENT_RUNS.md` — add fix markers

**Step 1: Add error entries and update memory**

Add to ERRORS_AND_FIXES.md under a new section for 07 MAR 2026:

```markdown
### COD-SG131: Zarr Rechunk Blosc Codec Incompatibility (07 MAR 2026)

**Error**: `Expected a BytesBytesCodec. Got <class 'numcodecs.blosc.Blosc'>`
**Category**: PIPELINE
**Severity**: HIGH
**Root cause**: `_build_zarr_encoding()` only produced zarr v3 `BloscCodec` objects. When reading a v2 source Zarr store (with `numcodecs.Blosc` metadata) and writing with v3 encoding, the codec systems conflicted.
**Fix**: Made `_build_zarr_encoding()` format-aware — accepts `zarr_format=2|3`, produces matching codec objects and encoding keys. Both `netcdf_convert` and `ingest_zarr_rechunk` handlers pass `zarr_format` to `ds.to_zarr()`.
**Files**: `services/handler_netcdf_to_zarr.py`, `services/handler_ingest_zarr.py`, `core/models/processing_options.py`
**Prevention**: Always match codec object types to the target zarr format version.

### COD-SG134: Status Endpoint Wrong Container for Zarr (07 MAR 2026)

**Error**: Status response `outputs.container` returns `silver-cogs` for zarr releases
**Category**: ENDPOINT
**Severity**: HIGH
**Root cause**: `_build_outputs_block()` in `trigger_platform_status.py:701` defaulted to `"silver-cogs"` for all data types.
**Fix**: Container inference now checks `job_result.zarr_store_url` first, then falls back based on `blob_path` prefix.
**Files**: `triggers/trigger_platform_status.py`

### COD-SG136: NetCDF-Converted Zarr Empty Variables (07 MAR 2026)

**Error**: TiTiler `/xarray/variables` returns `[]` for NetCDF-converted Zarr stores
**Category**: PIPELINE
**Severity**: MEDIUM
**Root cause**: `ds.to_zarr()` with zarr 3.1.5 writes v3 format by default (`zarr.json`, `c/` chunk paths). TiTiler's `titiler.xarray 0.24.x` reads v2 format only (`.zgroup`, `.zarray`, dot-separated chunks). Same root cause as SG13-1.
**Fix**: `zarr_format` parameter lets callers choose v2 (TiTiler compat) or v3. Default is v3; set to 2 until TiTiler upgrade to titiler-pgstac 2.1.0.
**Files**: Same as COD-SG131
```

**Step 2: Commit**

```bash
git add docs_claude/ERRORS_AND_FIXES.md docs/agent_review/AGENT_RUNS.md
git commit -m "docs: add SG13-1/4/6 error entries and fix markers"
```

---

## Verification

After all tasks are complete, verify the fixes:

```bash
# 1. Unit tests pass
conda activate azgeo && python -m pytest tests/unit/test_zarr_encoding.py -v

# 2. _build_zarr_encoding produces correct v2 output
conda activate azgeo && python -c "
import numpy as np, xarray as xr
from services.handler_netcdf_to_zarr import _build_zarr_encoding
ds = xr.Dataset({'temp': xr.DataArray(np.zeros((3,10,20)), dims=['time','lat','lon'])})
_, enc = _build_zarr_encoding(ds, zarr_format=2)
assert 'compressor' in enc['temp'], 'Missing v2 compressor key'
import numcodecs
assert isinstance(enc['temp']['compressor'], numcodecs.Blosc), 'Wrong compressor type'
print('v2 encoding: PASS')
_, enc3 = _build_zarr_encoding(ds, zarr_format=3)
assert 'compressors' in enc3['temp'], 'Missing v3 compressors key'
from zarr.codecs import BloscCodec
assert isinstance(enc3['temp']['compressors'][0], BloscCodec), 'Wrong codec type'
print('v3 encoding: PASS')
"

# 3. ZarrProcessingOptions accepts zarr_format
conda activate azgeo && python -c "
from core.models.processing_options import ZarrProcessingOptions
o2 = ZarrProcessingOptions(zarr_format=2)
o3 = ZarrProcessingOptions(zarr_format=3)
assert o2.zarr_format == 2
assert o3.zarr_format == 3
print('ZarrProcessingOptions: PASS')
"
```
