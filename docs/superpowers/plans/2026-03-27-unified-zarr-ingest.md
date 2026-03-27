# Unified Zarr Ingest Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a unified DAG workflow that accepts NetCDF or Zarr inputs, rechunks to 256×256, generates multiscale pyramids via ndpyramid, and registers with STAC.

**Architecture:** Conditional routing (NC vs Zarr), two parallel paths converging on shared register+STAC tail. NC path is single-pass (convert+chunk+pyramid). Zarr path is two-step (rechunk, then pyramid). Reuses existing handlers where possible, adds 2 new handlers and modifies 2.

**Tech Stack:** xarray, zarr 3.x, ndpyramid, rioxarray, Dask, adlfs, `conda activate azgeo`

**Spec:** `docs/superpowers/specs/2026-03-27-unified-zarr-ingest-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `requirements-docker.txt` | Modify | Add ndpyramid, rioxarray dependencies |
| `services/zarr/handler_validate_source.py` | Create | Detect NC vs Zarr, validate structure, report dims/chunks |
| `services/zarr/handler_generate_pyramid.py` | Create | Generate multiscale pyramid from flat Zarr store |
| `services/handler_netcdf_to_zarr.py` | Modify | Add pyramid generation to `netcdf_convert` → `netcdf_convert_and_pyramid` |
| `services/handler_ingest_zarr.py` | Modify | Add rechunk bypass for 256/512 chunks, add `zarr_store_url` to return |
| `services/__init__.py` | Modify | Register new handlers in ALL_HANDLERS |
| `workflows/ingest_zarr.yaml` | Overwrite | Unified workflow (version 2) |
| `workflows/netcdf_to_zarr.yaml` | Modify | Add superseded notice |

---

### Task 1: Add ndpyramid and rioxarray dependencies

**Files:**
- Modify: `requirements-docker.txt`

- [ ] **Step 1: Add dependencies to requirements-docker.txt**

In `requirements-docker.txt`, add after the xarray ecosystem section (after the `kerchunk` line):

```
ndpyramid>=0.3.0                        # Multiscale pyramid generation (pyramid_resample)
rioxarray>=0.17.0                       # CRS assignment for xarray datasets (rio.write_crs)
```

- [ ] **Step 2: Verify packages are installable**

Run: `conda activate azgeo && pip install ndpyramid rioxarray --dry-run 2>&1 | tail -10`

Expected: Shows packages that would be installed, no conflicts.

- [ ] **Step 3: Install locally for development**

Run: `conda activate azgeo && pip install ndpyramid rioxarray`

- [ ] **Step 4: Verify imports work**

Run: `conda activate azgeo && python -c "from ndpyramid import pyramid_resample; import rioxarray; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements-docker.txt
git commit -m "feat: add ndpyramid + rioxarray for multiscale zarr pyramids"
```

---

### Task 2: Create `zarr_validate_source` handler

**Files:**
- Create: `services/zarr/handler_validate_source.py`

- [ ] **Step 1: Create the handler**

Create `services/zarr/handler_validate_source.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - ZARR VALIDATE SOURCE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Detect input type (NC/Zarr), validate, report dims
# PURPOSE: First node in unified zarr ingest workflow — routes NC vs Zarr path
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: zarr_validate_source
# DEPENDENCIES: adlfs, xarray, fsspec
# ============================================================================
"""
Zarr Validate Source — detect input type and validate structure.

Inspects source URL to determine if input is NetCDF (.nc files) or Zarr
(zarr.json or .zmetadata present). Reports dimensions, current chunk sizes,
and whether rechunking is needed (spatial chunks not 256 or 512).
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Spatial chunk sizes that are acceptable (skip rechunk)
ACCEPTABLE_SPATIAL_CHUNKS = {256, 512}


def zarr_validate_source(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Detect input type (NetCDF vs Zarr) and validate source structure.

    Params:
        source_url (str): abfs:// URL or blob path to source data
        source_account (str): Azure storage account name
        dataset_id (str): Dataset identifier for logging
        resource_id (str): Resource identifier for logging

    Returns:
        {
            "success": True,
            "input_type": "netcdf" | "zarr",
            "file_list": [...],           # NC: list of .nc file paths
            "dimensions": {"time": N, "lat": N, "lon": N},
            "current_chunks": {...},       # Zarr: current chunk sizes
            "needs_rechunk": bool,         # True if chunks not in {256, 512}
            "variable_count": int,
            "total_size_bytes": int
        }
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    if not source_url or not source_account:
        return {
            "success": False,
            "error": "source_url and source_account are required",
            "error_type": "ValidationError",
        }

    logger.info(
        "zarr_validate_source: source=%s account=%s dataset=%s",
        source_url, source_account, dataset_id,
    )

    try:
        import fsspec

        storage_options = {"account_name": source_account}
        fs = fsspec.filesystem("az", **storage_options)

        # Detect input type by listing source contents
        source_path = source_url.replace("abfs://", "")
        entries = fs.ls(source_path, detail=False)
        entry_names = [e.split("/")[-1] for e in entries]

        # Zarr markers: zarr.json (v3) or .zmetadata (v2) or .zarray in subdirs
        zarr_markers = {"zarr.json", ".zmetadata", ".zgroup", ".zattrs"}
        nc_extensions = {".nc", ".nc4", ".netcdf"}

        is_zarr = bool(zarr_markers & set(entry_names))
        nc_files = [e for e in entries if any(e.endswith(ext) for ext in nc_extensions)]
        is_netcdf = len(nc_files) > 0 and not is_zarr

        if not is_zarr and not is_netcdf:
            return {
                "success": False,
                "error": f"Cannot detect input type at {source_url}. "
                         f"No Zarr markers or .nc files found. "
                         f"Found: {entry_names[:10]}",
                "error_type": "ValidationError",
            }

        input_type = "zarr" if is_zarr else "netcdf"
        logger.info("zarr_validate_source: detected input_type=%s", input_type)

        # ── Zarr path: open store, read dims and chunks ──────────
        if is_zarr:
            import xarray as xr

            ds = xr.open_zarr(
                source_url,
                storage_options=storage_options,
                consolidated=True,
            )
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)

                # Read current chunk sizes from first data variable
                current_chunks = {}
                spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
                needs_rechunk = False

                if ds.data_vars:
                    first_var = list(ds.data_vars)[0]
                    var_chunks = ds[first_var].encoding.get("chunks")
                    if var_chunks:
                        for dim, size in zip(ds[first_var].dims, var_chunks):
                            current_chunks[dim] = size
                            if dim.lower() in spatial_names and size not in ACCEPTABLE_SPATIAL_CHUNKS:
                                needs_rechunk = True

                # Estimate total size
                total_size_bytes = sum(
                    ds[v].nbytes for v in ds.data_vars
                )

                elapsed = time.time() - start
                logger.info(
                    "zarr_validate_source: zarr validated — dims=%s, chunks=%s, "
                    "needs_rechunk=%s, vars=%d (%0.1fs)",
                    dimensions, current_chunks, needs_rechunk, variable_count, elapsed,
                )

                return {
                    "success": True,
                    "input_type": "zarr",
                    "file_list": [],
                    "dimensions": dimensions,
                    "current_chunks": current_chunks,
                    "needs_rechunk": needs_rechunk,
                    "variable_count": variable_count,
                    "total_size_bytes": total_size_bytes,
                }
            finally:
                ds.close()

        # ── NetCDF path: list files, open first to read dims ─────
        else:
            import xarray as xr

            # Sort NC files for deterministic concat
            nc_files = sorted(nc_files)

            # Open first file to read dimensions (don't load all)
            first_url = f"abfs://{nc_files[0]}" if not nc_files[0].startswith("abfs://") else nc_files[0]
            ds = xr.open_dataset(
                first_url,
                engine="netcdf4",
                storage_options=storage_options,
            )
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)

                # Estimate total from file sizes
                total_size_bytes = sum(fs.info(f).get("size", 0) for f in nc_files)
            finally:
                ds.close()

            elapsed = time.time() - start
            logger.info(
                "zarr_validate_source: netcdf validated — %d files, dims=%s, "
                "vars=%d, total_size=%d bytes (%0.1fs)",
                len(nc_files), dimensions, variable_count, total_size_bytes, elapsed,
            )

            return {
                "success": True,
                "input_type": "netcdf",
                "file_list": nc_files,
                "dimensions": dimensions,
                "current_chunks": {},
                "needs_rechunk": False,
                "variable_count": variable_count,
                "total_size_bytes": total_size_bytes,
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_validate_source failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
```

- [ ] **Step 2: Verify file is importable**

Run: `conda activate azgeo && python -c "from services.zarr.handler_validate_source import zarr_validate_source; print(zarr_validate_source.__name__)"`

Expected: `zarr_validate_source`

- [ ] **Step 3: Commit**

```bash
git add services/zarr/handler_validate_source.py
git commit -m "feat: zarr_validate_source handler — detect NC vs Zarr, report dims/chunks"
```

---

### Task 3: Create `zarr_generate_pyramid` handler

**Files:**
- Create: `services/zarr/handler_generate_pyramid.py`

- [ ] **Step 1: Create the handler**

Create `services/zarr/handler_generate_pyramid.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - ZARR GENERATE PYRAMID HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Generate multiscale pyramid from flat Zarr store
# PURPOSE: Reads rechunked Zarr, generates ndpyramid levels, writes pyramid store
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: zarr_generate_pyramid
# DEPENDENCIES: ndpyramid, rioxarray, xarray, zarr
# ============================================================================
"""
Zarr Generate Pyramid — multiscale pyramid generation for TiTiler-xarray.

Reads a flat rechunked Zarr store, generates downsampled pyramid levels via
ndpyramid.pyramid_resample(), and writes a multi-group Zarr v3 store.
Output follows the Zarr multiscales convention (groups named 0, 1, 2, ...).

Level 0 = full resolution (identical to input data, lossless).
Levels 1-N = 2x downsampled per level. O(1) tile reads at any zoom.
Storage overhead: ~33% above base level.
"""

import logging
import math
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Dimension name detection (shared with _build_zarr_encoding)
SPATIAL_NAMES = {"lat", "latitude", "y"}
LON_NAMES = {"lon", "longitude", "x"}
ALL_SPATIAL = SPATIAL_NAMES | LON_NAMES


def _detect_spatial_dims(ds):
    """Detect lat/lon dimension names from dataset."""
    lat_dim = lon_dim = None
    for dim in ds.dims:
        dim_lower = dim.lower()
        if dim_lower in SPATIAL_NAMES:
            lat_dim = dim
        elif dim_lower in LON_NAMES:
            lon_dim = dim
    return lat_dim, lon_dim


def _auto_detect_levels(dimensions, lat_dim, lon_dim, chunk_size=256):
    """Compute pyramid levels until coarsest fits in one chunk."""
    max_spatial = max(dimensions.get(lat_dim, 1), dimensions.get(lon_dim, 1))
    if max_spatial <= chunk_size:
        return 1
    levels = 0
    size = max_spatial
    while size > chunk_size:
        size //= 2
        levels += 1
    return max(levels, 1)


def zarr_generate_pyramid(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Generate multiscale pyramid from a flat/rechunked Zarr store.

    Params:
        zarr_store_url (str): abfs:// URL of the rechunked store
        target_container (str): Output container (e.g. "silver-zarr")
        target_prefix (str): Output blob prefix (pyramid written to {prefix}_pyramid.zarr)
        pyramid_levels (int): Number of levels (0 = auto-detect from dimensions)
        resampling (str): "bilinear" (default), "nearest"
        zarr_format (int): 3 (default)
        dry_run (bool): If True, compute levels but skip write
        dimensions (dict): From validate handler — {dim_name: size}

    Returns:
        {
            "success": True,
            "result": {
                "pyramid_url": "abfs://silver-zarr/prefix_pyramid.zarr",
                "levels_generated": 4,
                "resampling": "bilinear",
                "level_sizes": {"0": "1440x720", "1": "720x360", ...},
            }
        }
    """
    start = time.time()

    zarr_store_url = params.get("zarr_store_url")
    target_container = params.get("target_container", "silver-zarr")
    target_prefix = params.get("target_prefix")
    pyramid_levels = params.get("pyramid_levels", 0)
    resampling = params.get("resampling", "bilinear")
    zarr_format = params.get("zarr_format", 3)
    dry_run = params.get("dry_run", True)
    dimensions = params.get("dimensions", {})

    if not zarr_store_url:
        return {
            "success": False,
            "error": "zarr_store_url is required",
            "error_type": "ValidationError",
        }

    logger.info(
        "zarr_generate_pyramid: source=%s, levels=%s, resampling=%s, dry_run=%s",
        zarr_store_url, pyramid_levels, resampling, dry_run,
    )

    try:
        import xarray as xr
        import rioxarray  # noqa: F401 — registers .rio accessor
        from ndpyramid import pyramid_resample

        # Resolve storage options from URL
        from infrastructure.blob import BlobRepository
        source_account = BlobRepository.for_zone("silver").account_name
        storage_options = {"account_name": source_account}

        # Open source store
        ds = xr.open_zarr(zarr_store_url, storage_options=storage_options, consolidated=True)

        try:
            # Detect spatial dimensions
            lat_dim, lon_dim = _detect_spatial_dims(ds)
            if not lat_dim or not lon_dim:
                return {
                    "success": False,
                    "error": f"Cannot detect spatial dimensions. Found: {list(ds.dims)}",
                    "error_type": "ValidationError",
                }

            # Auto-detect levels if not specified
            if pyramid_levels <= 0:
                pyramid_levels = _auto_detect_levels(
                    dict(ds.sizes), lat_dim, lon_dim
                )
            logger.info(
                "zarr_generate_pyramid: lat=%s, lon=%s, levels=%d",
                lat_dim, lon_dim, pyramid_levels,
            )

            # Compute level sizes for reporting
            level_sizes = {}
            lat_size = ds.sizes[lat_dim]
            lon_size = ds.sizes[lon_dim]
            for lvl in range(pyramid_levels + 1):
                factor = 2 ** lvl
                level_sizes[str(lvl)] = f"{lon_size // factor}x{lat_size // factor}"

            if dry_run:
                elapsed = time.time() - start
                logger.info(
                    "zarr_generate_pyramid: [DRY-RUN] would generate %d levels (%0.1fs)",
                    pyramid_levels, elapsed,
                )
                return {
                    "success": True,
                    "result": {
                        "pyramid_url": f"abfs://{target_container}/{target_prefix}_pyramid.zarr",
                        "levels_generated": pyramid_levels,
                        "resampling": resampling,
                        "level_sizes": level_sizes,
                        "dry_run": True,
                    },
                }

            # Assign CRS (required by ndpyramid)
            ds = ds.rio.write_crs("EPSG:4326")

            # Generate pyramid
            logger.info("zarr_generate_pyramid: generating %d levels with %s resampling...", pyramid_levels, resampling)
            pyramid = pyramid_resample(
                ds,
                x=lon_dim,
                y=lat_dim,
                levels=pyramid_levels,
                resampling=resampling,
            )

            # Build target URL
            target_url = f"abfs://{target_container}/{target_prefix}_pyramid.zarr"
            target_storage_options = {"account_name": source_account}

            # Write pyramid Zarr store
            pyramid.to_zarr(
                target_url,
                zarr_format=zarr_format,
                consolidated=True,
                mode="w",
                storage_options=target_storage_options,
            )

            # Mandatory v3 metadata consolidation
            if zarr_format == 3:
                import zarr
                consolidate_store = zarr.storage.FsspecStore.from_url(
                    target_url, storage_options=target_storage_options,
                )
                zarr.consolidate_metadata(consolidate_store)
                logger.info("zarr_generate_pyramid: consolidated metadata (Zarr v3)")

            elapsed = time.time() - start
            logger.info(
                "zarr_generate_pyramid: completed %d levels to %s (%0.1fs)",
                pyramid_levels, target_url, elapsed,
            )

            return {
                "success": True,
                "result": {
                    "pyramid_url": target_url,
                    "levels_generated": pyramid_levels,
                    "resampling": resampling,
                    "level_sizes": level_sizes,
                },
            }

        finally:
            ds.close()

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_generate_pyramid failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
```

- [ ] **Step 2: Verify file is importable**

Run: `conda activate azgeo && python -c "from services.zarr.handler_generate_pyramid import zarr_generate_pyramid; print(zarr_generate_pyramid.__name__)"`

Expected: `zarr_generate_pyramid`

- [ ] **Step 3: Commit**

```bash
git add services/zarr/handler_generate_pyramid.py
git commit -m "feat: zarr_generate_pyramid handler — ndpyramid multiscale generation"
```

---

### Task 4: Modify `netcdf_convert` → add pyramid generation

**Files:**
- Modify: `services/handler_netcdf_to_zarr.py`

- [ ] **Step 1: Read the current `netcdf_convert` function**

Read `services/handler_netcdf_to_zarr.py` from line 668 to line 906 to understand the full function before modifying.

- [ ] **Step 2: Create `netcdf_convert_and_pyramid` function**

Add a new function `netcdf_convert_and_pyramid` after the existing `netcdf_convert` function (do NOT modify the original — keep it for Epoch 4 backward compat). The new function:

1. Copies the core logic from `netcdf_convert` (open, chunk, write)
2. After `ds.chunk(target_chunks)`, adds CRS assignment and pyramid generation
3. Writes the pyramid store instead of a flat store
4. Uses `pyramid.to_zarr()` instead of `ds.to_zarr()`

```python
def netcdf_convert_and_pyramid(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert NetCDF to rechunked Zarr v3 with multiscale pyramid — single pass.

    Opens NetCDF files, applies optimized chunking (256×256 spatial, time=1),
    generates ndpyramid levels, and writes the pyramid Zarr store. No
    intermediate flat store — the Dask graph goes from NC to pyramid in one pass.

    Params:
        source_url (str): abfs:// URL to source NC files
        source_account (str): Storage account name
        target_container (str): Output container (default: silver-zarr)
        target_prefix (str): Output blob prefix
        spatial_chunk_size (int): Spatial chunk dim (default: 256)
        zarr_format (int): Zarr format version (default: 3)
        pyramid_levels (int): Number of levels (0 = auto-detect)
        resampling (str): Resampling method (default: bilinear)
        dry_run (bool): If True, validate but skip write
        file_list (list): NC file paths from validate handler
        dimensions (dict): Dimensions from validate handler

    Returns:
        {"success": True, "result": {"pyramid_url": ..., "levels_generated": N, ...}}
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    target_container = params.get("target_container", "silver-zarr")
    target_prefix = params.get("target_prefix")
    spatial_chunk_size = params.get("spatial_chunk_size", 256)
    time_chunk_size = params.get("time_chunk_size", 1)
    compressor_name = params.get("compressor", "lz4")
    compression_level = params.get("compression_level", 5)
    zarr_format = params.get("zarr_format", 3)
    pyramid_levels = params.get("pyramid_levels", 0)
    resampling = params.get("resampling", "bilinear")
    dry_run = params.get("dry_run", True)
    file_list = params.get("file_list", [])
    dimensions = params.get("dimensions", {})
    dataset_id = params.get("dataset_id", "unknown")
    concat_dim = params.get("concat_dim", "time")

    if not file_list:
        return {"success": False, "error": "file_list is required (from validate)", "error_type": "ValidationError"}

    logger.info(
        "netcdf_convert_and_pyramid: %d files, target=%s/%s, "
        "pyramid_levels=%s, resampling=%s, dry_run=%s",
        len(file_list), target_container, target_prefix,
        pyramid_levels, resampling, dry_run,
    )

    try:
        import xarray as xr
        import rioxarray  # noqa: F401
        from ndpyramid import pyramid_resample
        from services.zarr.handler_generate_pyramid import _detect_spatial_dims, _auto_detect_levels

        storage_options = {"account_name": source_account}

        # Resolve NC file URLs
        nc_urls = []
        for f in file_list:
            url = f if f.startswith("abfs://") else f"abfs://{f}"
            nc_urls.append(url)

        # Open all NetCDF files
        ds = xr.open_mfdataset(
            nc_urls,
            engine="netcdf4",
            concat_dim=concat_dim,
            combine="nested",
            storage_options=storage_options,
        )

        try:
            # Build optimized chunking + encoding
            target_chunks, encoding = _build_zarr_encoding(
                ds, spatial_chunk_size, time_chunk_size,
                compressor_name, compression_level,
                zarr_format=zarr_format,
            )
            ds = ds.chunk(target_chunks)

            # Detect spatial dims
            lat_dim, lon_dim = _detect_spatial_dims(ds)
            if not lat_dim or not lon_dim:
                return {
                    "success": False,
                    "error": f"Cannot detect spatial dims. Found: {list(ds.dims)}",
                    "error_type": "ValidationError",
                }

            # Auto-detect pyramid levels
            if pyramid_levels <= 0:
                pyramid_levels = _auto_detect_levels(
                    dict(ds.sizes), lat_dim, lon_dim, spatial_chunk_size,
                )

            # Compute level sizes for reporting
            level_sizes = {}
            lat_size = ds.sizes[lat_dim]
            lon_size = ds.sizes[lon_dim]
            for lvl in range(pyramid_levels + 1):
                factor = 2 ** lvl
                level_sizes[str(lvl)] = f"{lon_size // factor}x{lat_size // factor}"

            if dry_run:
                elapsed = time.time() - start
                logger.info(
                    "netcdf_convert_and_pyramid: [DRY-RUN] would convert %d files, "
                    "%d pyramid levels (%0.1fs)",
                    len(file_list), pyramid_levels, elapsed,
                )
                return {
                    "success": True,
                    "result": {
                        "pyramid_url": f"abfs://{target_container}/{target_prefix}_pyramid.zarr",
                        "levels_generated": pyramid_levels,
                        "source_file_count": len(file_list),
                        "level_sizes": level_sizes,
                        "dry_run": True,
                    },
                }

            # Assign CRS (required by ndpyramid)
            ds = ds.rio.write_crs("EPSG:4326")

            # Generate pyramid from the chunked Dask graph — single pass
            logger.info(
                "netcdf_convert_and_pyramid: generating %d pyramid levels with %s...",
                pyramid_levels, resampling,
            )
            pyramid = pyramid_resample(
                ds,
                x=lon_dim,
                y=lat_dim,
                levels=pyramid_levels,
                resampling=resampling,
            )

            # Write pyramid Zarr store
            target_url = f"abfs://{target_container}/{target_prefix}_pyramid.zarr"
            target_storage_options = {"account_name": source_account}

            pyramid.to_zarr(
                target_url,
                zarr_format=zarr_format,
                consolidated=True,
                mode="w",
                storage_options=target_storage_options,
            )

            # Mandatory v3 metadata consolidation
            if zarr_format == 3:
                import zarr
                consolidate_store = zarr.storage.FsspecStore.from_url(
                    target_url, storage_options=target_storage_options,
                )
                zarr.consolidate_metadata(consolidate_store)
                logger.info("netcdf_convert_and_pyramid: consolidated metadata (Zarr v3)")

            elapsed = time.time() - start
            logger.info(
                "netcdf_convert_and_pyramid: completed — %d files → %d pyramid levels "
                "to %s (%0.1fs)",
                len(file_list), pyramid_levels, target_url, elapsed,
            )

            return {
                "success": True,
                "result": {
                    "pyramid_url": target_url,
                    "levels_generated": pyramid_levels,
                    "resampling": resampling,
                    "source_file_count": len(file_list),
                    "dimensions": dict(ds.sizes),
                    "variables": list(ds.data_vars),
                    "level_sizes": level_sizes,
                },
            }

        finally:
            ds.close()

    except Exception as e:
        elapsed = time.time() - start
        logger.error("netcdf_convert_and_pyramid failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
```

- [ ] **Step 3: Verify import**

Run: `conda activate azgeo && python -c "from services.handler_netcdf_to_zarr import netcdf_convert_and_pyramid; print(netcdf_convert_and_pyramid.__name__)"`

Expected: `netcdf_convert_and_pyramid`

- [ ] **Step 4: Commit**

```bash
git add services/handler_netcdf_to_zarr.py
git commit -m "feat: netcdf_convert_and_pyramid — single-pass NC→Zarr+pyramid"
```

---

### Task 5: Modify `ingest_zarr_rechunk` — add bypass + zarr_store_url output

**Files:**
- Modify: `services/handler_ingest_zarr.py:710-925`

- [ ] **Step 1: Read the current handler**

Read `services/handler_ingest_zarr.py` from line 738 to line 770 (after param extraction, before the try/xr.open_zarr block) to find the right insertion point for the bypass.

- [ ] **Step 2: Add bypass logic after param extraction**

After line 757 (the logging statement), before the `try:` block at line 759, add the bypass check:

```python
    # Check if rechunking can be skipped (chunks already 256 or 512)
    current_chunks = params.get("current_chunks", {})
    if current_chunks:
        spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
        spatial_chunk_values = [
            v for k, v in current_chunks.items()
            if k.lower() in spatial_names
        ]
        acceptable = {256, 512}
        if spatial_chunk_values and all(v in acceptable for v in spatial_chunk_values):
            elapsed = time.time() - start
            logger.info(
                "ingest_zarr_rechunk: spatial chunks %s already optimal, "
                "skipping rechunk (%0.1fs)",
                spatial_chunk_values, elapsed,
            )
            return {
                "success": True,
                "result": {
                    "rechunked": False,
                    "zarr_store_url": source_url,
                    "target_container": target_container,
                    "target_prefix": target_prefix,
                    "reason": f"Spatial chunks {spatial_chunk_values} already in {acceptable}",
                },
            }
```

- [ ] **Step 3: Add `zarr_store_url` to the success return**

In the existing success return block (around line 906-915), add `zarr_store_url` to the result dict:

Change:
```python
        return {
            "success": True,
            "result": {
                "target_chunks": target_chunks,
                "compressor": compressor_name,
                "compression_level": compression_level,
                "target_container": target_container,
                "target_prefix": target_prefix,
            },
        }
```

To:
```python
        return {
            "success": True,
            "result": {
                "rechunked": True,
                "zarr_store_url": target_az_url,
                "target_chunks": target_chunks,
                "compressor": compressor_name,
                "compression_level": compression_level,
                "target_container": target_container,
                "target_prefix": target_prefix,
            },
        }
```

Note: `target_az_url` is the variable that holds the full `abfs://` URL (check the variable name in the existing code — it may be `target_az_url` or similar).

- [ ] **Step 4: Verify the handler still imports**

Run: `conda activate azgeo && python -c "from services.handler_ingest_zarr import ingest_zarr_rechunk; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add services/handler_ingest_zarr.py
git commit -m "feat: ingest_zarr_rechunk — bypass for 256/512 chunks, add zarr_store_url output"
```

---

### Task 6: Register new handlers in ALL_HANDLERS

**Files:**
- Modify: `services/__init__.py`

- [ ] **Step 1: Add imports**

In `services/__init__.py`, add the new imports after the existing zarr handler imports (around line 126):

```python
from .zarr.handler_validate_source import zarr_validate_source
from .zarr.handler_generate_pyramid import zarr_generate_pyramid
```

Add the netcdf_convert_and_pyramid import in the NetCDF section (around line 105):

```python
    netcdf_convert_and_pyramid,
```

And update the `from .handler_netcdf_to_zarr import (` block to include it.

- [ ] **Step 2: Add to ALL_HANDLERS dict**

In the `ALL_HANDLERS` dict, add in the Zarr DAG handlers section (around line 196):

```python
    "zarr_validate_source": zarr_validate_source,
    "zarr_generate_pyramid": zarr_generate_pyramid,
```

And in the NetCDF section (around line 250):

```python
    "netcdf_convert_and_pyramid": netcdf_convert_and_pyramid,
```

- [ ] **Step 3: Verify handler count**

Run: `conda activate azgeo && python -c "from services import ALL_HANDLERS; print(f'Handler count: {len(ALL_HANDLERS)}')"`

Expected: Previous count (57) + 3 = 60.

- [ ] **Step 4: Commit**

```bash
git add services/__init__.py
git commit -m "feat: register zarr_validate_source, zarr_generate_pyramid, netcdf_convert_and_pyramid"
```

---

### Task 7: Create unified `ingest_zarr.yaml` workflow

**Files:**
- Overwrite: `workflows/ingest_zarr.yaml`
- Modify: `workflows/netcdf_to_zarr.yaml` (add superseded notice)

- [ ] **Step 1: Write the unified workflow**

Overwrite `workflows/ingest_zarr.yaml` with:

```yaml
workflow: ingest_zarr
description: "Unified Zarr ingest: NetCDF or Zarr → rechunk 256x256 → multiscale pyramid → STAC"
version: 2
reverses: [unpublish_zarr]

parameters:
  source_url: {type: str, required: true}
  source_account: {type: str, required: true}
  collection_id: {type: str, required: true}
  stac_item_id: {type: str, required: true}
  dataset_id: {type: str, required: true}
  resource_id: {type: str, required: true}
  access_level: {type: str, default: "internal"}
  target_container: {type: str, default: "silver-zarr"}
  target_prefix: {type: str, required: true}
  pyramid_levels: {type: int, default: 0}
  resampling: {type: str, default: "bilinear"}
  spatial_chunk_size: {type: int, default: 256}
  zarr_format: {type: int, default: 3}
  dry_run: {type: bool, default: true}

nodes:
  # ── Validate source and detect input type ──────────────────────
  validate:
    type: task
    handler: zarr_validate_source
    params: [source_url, source_account, dataset_id, resource_id]

  # ── Route: NetCDF or Zarr ──────────────────────────────────────
  detect_type:
    type: conditional
    depends_on: [validate]
    condition: "validate.input_type"
    branches:
      - name: netcdf_path
        condition: "eq netcdf"
        next: [convert_and_pyramid]
      - name: zarr_path
        default: true
        next: [rechunk]

  # ── PATH A: NetCDF → convert + chunk + pyramid (single pass) ───
  convert_and_pyramid:
    type: task
    handler: netcdf_convert_and_pyramid
    params: [source_url, source_account, target_container, target_prefix,
             spatial_chunk_size, zarr_format, pyramid_levels, resampling, dry_run, dataset_id]
    receives:
      file_list: "validate.file_list"
      dimensions: "validate.dimensions"

  # ── PATH B: Zarr → rechunk (skip if 256/512) ──────────────────
  rechunk:
    type: task
    handler: ingest_zarr_rechunk
    params: [source_url, source_account, target_container, target_prefix,
             spatial_chunk_size, zarr_format, dry_run]
    receives:
      current_chunks: "validate.current_chunks"
      dimensions: "validate.dimensions"

  # ── PATH B continued: generate pyramid from rechunked store ────
  generate_pyramid:
    type: task
    handler: zarr_generate_pyramid
    depends_on: [rechunk]
    params: [target_container, target_prefix, pyramid_levels, resampling, zarr_format, dry_run]
    receives:
      zarr_store_url: "rechunk.result.zarr_store_url"
      dimensions: "validate.dimensions"

  # ── Register metadata (both paths converge) ────────────────────
  register:
    type: task
    handler: zarr_register_metadata
    depends_on:
      - "convert_and_pyramid?"
      - "generate_pyramid?"
    params: [stac_item_id, collection_id, dataset_id, resource_id, access_level,
             target_container, target_prefix]

  # ── STAC materialization ───────────────────────────────────────
  materialize_item:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    params: [collection_id]
    receives:
      cog_id: "register.result.zarr_id"

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_item]
    params: [collection_id]
```

- [ ] **Step 2: Add superseded notice to netcdf_to_zarr.yaml**

Add at the top of `workflows/netcdf_to_zarr.yaml`:

```yaml
# SUPERSEDED (27 MAR 2026): Replaced by unified ingest_zarr.yaml (version 2)
# which handles both NetCDF and Zarr inputs with conditional routing.
# Kept for reference until E2E verified.
```

- [ ] **Step 3: Validate YAML loads**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
defn = loader.load_workflow('ingest_zarr')
print(f'Loaded: {defn.workflow} v{defn.version}, nodes: {len(defn.nodes)}')
for name, node in defn.nodes.items():
    print(f'  {name}: type={node.type}')
"`

Expected: `ingest_zarr v2`, 8 nodes (validate, detect_type, convert_and_pyramid, rechunk, generate_pyramid, register, materialize_item, materialize_collection).

- [ ] **Step 4: Verify total workflow count**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
registry = loader.load_all()
print(f'Total workflows: {len(registry)}')
for name in sorted(registry):
    print(f'  {name}')
"`

- [ ] **Step 5: Commit**

```bash
git add workflows/ingest_zarr.yaml workflows/netcdf_to_zarr.yaml
git commit -m "feat: unified ingest_zarr.yaml v2 — NC+Zarr → rechunk → pyramid → STAC"
```

---

### Task 8: Local validation smoke test

**Files:** None (read-only)

- [ ] **Step 1: Verify all new handlers resolve**

Run: `conda activate azgeo && python -c "
from services import ALL_HANDLERS
new_handlers = ['zarr_validate_source', 'zarr_generate_pyramid', 'netcdf_convert_and_pyramid']
for h in new_handlers:
    present = h in ALL_HANDLERS
    print(f'{h}: {\"OK\" if present else \"MISSING\"}')
print(f'Total handlers: {len(ALL_HANDLERS)}')
"`

Expected: All 3 OK, total 60.

- [ ] **Step 2: Verify workflow validation passes**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
defn = loader.load_workflow('ingest_zarr')
errors = loader.validate_workflow(defn)
print(f'Validation errors: {errors}')
"`

Expected: `Validation errors: []`

- [ ] **Step 3: Verify ndpyramid works locally**

Run: `conda activate azgeo && python -c "
import xarray as xr
import numpy as np
import rioxarray
from ndpyramid import pyramid_resample

# Create tiny test dataset
ds = xr.Dataset({
    'temp': (['lat', 'lon'], np.random.rand(64, 128).astype('float32'))
}, coords={
    'lat': np.linspace(-90, 90, 64),
    'lon': np.linspace(-180, 180, 128),
})
ds = ds.rio.write_crs('EPSG:4326')
pyramid = pyramid_resample(ds, x='lon', y='lat', levels=2, resampling='bilinear')
print(f'Pyramid levels: {list(pyramid.children.keys())}')
print(f'Level 0 shape: {dict(pyramid[\"0\"].ds.sizes)}')
print(f'Level 1 shape: {dict(pyramid[\"1\"].ds.sizes)}')
print('OK')
"`

Expected: Pyramid levels [0, 1, 2], Level 0 is 128x64, Level 1 is 64x32. `OK`.

- [ ] **Step 4: Run any existing zarr tests**

Run: `conda activate azgeo && python -m pytest tests/ -k "zarr" -v --no-header 2>&1 | tail -20`

Report results.

---

## E2E Validation (Post-Deploy — Separate Session)

After `deploy.sh docker && deploy.sh dagbrain`:

1. **NetCDF dry run**: Submit ingest_zarr with NC source, `dry_run: true`
2. **NetCDF live**: Submit with `dry_run: false` → pyramid Zarr v3 written
3. **Zarr (needs rechunk)**: Submit Zarr with striped chunks
4. **Zarr (already 256)**: Submit optimized store → rechunk bypassed
5. **Verify pyramid**: `xr.open_datatree("store")` → confirm levels
6. **Verify STAC**: Item materialized with `geoetl:data_type: "zarr"`

Test data from SIEGE:
- NC: `wargames/good-data/climatology-spei12-...-ssp370_..._median_2040-2059.nc`
- Zarr: `wargames/good-data/cmip6-tasmax-quick.zarr`
