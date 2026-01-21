# Virtual Zarr Implementation Plan - CMIP6 NetCDF Support

**Created**: 17 DEC 2025
**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: 🚨 HIGH - Client has CMIP6 NetCDF data, exploring unnecessary Zarr conversion

---

## Executive Summary

Client has 20-100GB of CMIP6 climate data in NetCDF format. They're exploring converting it all to Zarr - **this is unnecessary**. Instead, we generate lightweight kerchunk reference files (~1MB each) that make NetCDF files accessible as virtual Zarr stores.

```
Client's Plan (expensive):   NetCDF → Physical Zarr (weeks, 2x storage)
Our Solution (efficient):    NetCDF → Reference JSON (hours, trivial storage)
```

Both Planetary Computer Zarr data AND client NetCDF (via refs) will be served through TiTiler-xarray.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Planetary Computer          Client CMIP6 NetCDF                        │
│  (Native Zarr)               (Bronze Container)                         │
│       │                             │                                    │
│       │                             ▼                                    │
│       │                   ┌─────────────────────┐                       │
│       │                   │ inventory_netcdf    │                       │
│       │                   │ (scan, parse, group)│                       │
│       │                   └─────────────────────┘                       │
│       │                             │                                    │
│       │                             ▼                                    │
│       │                   ┌─────────────────────┐                       │
│       │                   │ generate_virtual_zarr│                      │
│       │                   │ (refs, combine, STAC)│                      │
│       │                   └─────────────────────┘                       │
│       │                             │                                    │
│       │                             ▼                                    │
│       │                   Kerchunk References                           │
│       │                   (Silver/refs Container)                       │
│       │                             │                                    │
│       └──────────────┬──────────────┘                                   │
│                      │                                                   │
│                      ▼                                                   │
│            ┌─────────────────────┐                                      │
│            │   TiTiler-xarray    │                                      │
│            │   (unified serving) │                                      │
│            └─────────────────────┘                                      │
│                      │                                                   │
│                      ▼                                                   │
│              XYZ Tiles / WMS                                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## CMIP6 File Naming Convention

CMIP6 files follow a strict naming convention:

```
{variable}_{frequency}_{model}_{scenario}_{variant}_{grid}_{timerange}.nc

Example: tas_day_CESM2_ssp245_r1i1p1f1_gn_20500101-20591231.nc
```

| Component | Example | Description |
|-----------|---------|-------------|
| variable | `tas` | Near-surface air temperature |
| frequency | `day` | Daily data |
| model | `CESM2` | Climate model name |
| scenario | `ssp245` | SSP scenario (historical, ssp126, ssp245, ssp370, ssp585) |
| variant | `r1i1p1f1` | Realization, initialization, physics, forcing |
| grid | `gn` | Grid type (gn=native, gr=regridded) |
| timerange | `20500101-20591231` | Start-end dates |

Files with the same `{variable}_{frequency}_{model}_{scenario}_{variant}_{grid}` belong to a single logical dataset and should be combined along the time dimension.

---

## Storage Layout

```
rmhazuregeobronze/
  └── cmip6/                          # Raw CMIP6 NetCDF (unchanged)
      └── {model}/
          └── {scenario}/
              ├── tas_day_CESM2_ssp245_r1i1p1f1_gn_20150101-20241231.nc
              ├── tas_day_CESM2_ssp245_r1i1p1f1_gn_20250101-20341231.nc
              └── ...

rmhazuregeosilver/
  └── refs/                           # Kerchunk references (new)
      └── cmip6/
          └── {model}/
              └── {scenario}/
                  ├── tas_day_CESM2_ssp245_r1i1p1f1_gn_20150101-20241231.json  # Per-file refs
                  ├── tas_day_CESM2_ssp245_r1i1p1f1_gn_20250101-20341231.json
                  └── tas_day_CESM2_ssp245_combined.json                        # Combined virtual dataset
```

---

## Implementation Components

### Phase 1: Core Infrastructure

#### 1.1 CMIP6 Parser Utility

**File**: `services/netcdf_handlers/cmip6_parser.py`

```python
# ============================================================================
# CLAUDE CONTEXT - CMIP6 FILENAME PARSER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Utility - CMIP6 filename parsing and validation
# PURPOSE: Extract metadata from CMIP6-compliant filenames
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: parse_cmip6_filename, CMIP6FileMetadata
# DEPENDENCIES: re, dataclasses
# ============================================================================

import re
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class CMIP6FileMetadata:
    """Parsed metadata from a CMIP6-compliant filename."""

    variable: str           # e.g., "tas", "pr", "tasmax"
    frequency: str          # e.g., "day", "mon", "yr"
    model: str              # e.g., "CESM2", "GFDL-ESM4"
    scenario: str           # e.g., "historical", "ssp245"
    variant: str            # e.g., "r1i1p1f1"
    grid: str               # e.g., "gn", "gr"
    time_start: str         # e.g., "20150101"
    time_end: str           # e.g., "20241231"

    # Derived
    filename: str           # Original filename
    dataset_id: str         # Grouping key (excludes timerange)

    @property
    def time_start_date(self) -> datetime:
        """Parse time_start as datetime."""
        return datetime.strptime(self.time_start, "%Y%m%d")

    @property
    def time_end_date(self) -> datetime:
        """Parse time_end as datetime."""
        return datetime.strptime(self.time_end, "%Y%m%d")


# CMIP6 filename pattern
# {variable}_{frequency}_{model}_{scenario}_{variant}_{grid}_{timerange}.nc
CMIP6_PATTERN = re.compile(
    r'^(?P<variable>[a-zA-Z0-9]+)_'
    r'(?P<frequency>[a-zA-Z0-9]+)_'
    r'(?P<model>[a-zA-Z0-9-]+)_'
    r'(?P<scenario>[a-zA-Z0-9-]+)_'
    r'(?P<variant>r\d+i\d+p\d+f\d+)_'
    r'(?P<grid>[a-z]+)_'
    r'(?P<time_start>\d{8})-(?P<time_end>\d{8})\.nc$'
)

# Known CMIP6 variables (extensible)
KNOWN_VARIABLES = {
    'tas': 'Near-Surface Air Temperature',
    'tasmax': 'Daily Maximum Near-Surface Air Temperature',
    'tasmin': 'Daily Minimum Near-Surface Air Temperature',
    'pr': 'Precipitation',
    'psl': 'Sea Level Pressure',
    'hurs': 'Near-Surface Relative Humidity',
    'sfcWind': 'Near-Surface Wind Speed',
    'rsds': 'Surface Downwelling Shortwave Radiation',
}

# Known scenarios
KNOWN_SCENARIOS = {
    'historical': 'Historical simulation (1850-2014)',
    'ssp119': 'SSP1-1.9 (very low emissions)',
    'ssp126': 'SSP1-2.6 (low emissions)',
    'ssp245': 'SSP2-4.5 (intermediate)',
    'ssp370': 'SSP3-7.0 (high emissions)',
    'ssp585': 'SSP5-8.5 (very high emissions)',
}


def parse_cmip6_filename(filename: str) -> Optional[CMIP6FileMetadata]:
    """
    Parse a CMIP6-compliant filename and extract metadata.

    Args:
        filename: NetCDF filename (with or without path)

    Returns:
        CMIP6FileMetadata if valid, None if not CMIP6 compliant

    Example:
        >>> meta = parse_cmip6_filename("tas_day_CESM2_ssp245_r1i1p1f1_gn_20500101-20591231.nc")
        >>> meta.variable
        'tas'
        >>> meta.dataset_id
        'tas_day_CESM2_ssp245_r1i1p1f1_gn'
    """
    # Extract just the filename if path provided
    if '/' in filename:
        filename = filename.split('/')[-1]

    match = CMIP6_PATTERN.match(filename)
    if not match:
        return None

    groups = match.groupdict()

    # Build dataset_id (everything except timerange)
    dataset_id = (
        f"{groups['variable']}_{groups['frequency']}_{groups['model']}_"
        f"{groups['scenario']}_{groups['variant']}_{groups['grid']}"
    )

    return CMIP6FileMetadata(
        variable=groups['variable'],
        frequency=groups['frequency'],
        model=groups['model'],
        scenario=groups['scenario'],
        variant=groups['variant'],
        grid=groups['grid'],
        time_start=groups['time_start'],
        time_end=groups['time_end'],
        filename=filename,
        dataset_id=dataset_id,
    )


def group_cmip6_files(filenames: list[str]) -> dict[str, list[CMIP6FileMetadata]]:
    """
    Group CMIP6 files by dataset_id for combining into virtual datasets.

    Args:
        filenames: List of NetCDF filenames

    Returns:
        Dict mapping dataset_id to list of file metadata, sorted by time

    Example:
        >>> files = ["tas_day_CESM2_ssp245_r1i1p1f1_gn_20150101-20241231.nc",
        ...          "tas_day_CESM2_ssp245_r1i1p1f1_gn_20250101-20341231.nc"]
        >>> groups = group_cmip6_files(files)
        >>> list(groups.keys())
        ['tas_day_CESM2_ssp245_r1i1p1f1_gn']
    """
    groups: dict[str, list[CMIP6FileMetadata]] = {}

    for filename in filenames:
        meta = parse_cmip6_filename(filename)
        if meta:
            if meta.dataset_id not in groups:
                groups[meta.dataset_id] = []
            groups[meta.dataset_id].append(meta)

    # Sort each group by time_start
    for dataset_id in groups:
        groups[dataset_id].sort(key=lambda m: m.time_start)

    return groups


def get_variable_description(variable: str) -> str:
    """Get human-readable description for CMIP6 variable."""
    return KNOWN_VARIABLES.get(variable, f"CMIP6 variable: {variable}")


def get_scenario_description(scenario: str) -> str:
    """Get human-readable description for CMIP6 scenario."""
    return KNOWN_SCENARIOS.get(scenario, f"CMIP6 scenario: {scenario}")
```

---

#### 1.2 NetCDF Chunking Validator

**File**: `services/netcdf_handlers/handler_validate_netcdf.py`

```python
# ============================================================================
# CLAUDE CONTEXT - NETCDF CHUNKING VALIDATOR
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Pre-flight NetCDF validation
# PURPOSE: Check HDF5 chunking before virtualization, warn on problems
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: validate_netcdf_chunking
# DEPENDENCIES: h5py, fsspec, adlfs
# ============================================================================

import logging
from typing import Any

import h5py
import fsspec

from config.app_config import get_config

logger = logging.getLogger(__name__)


def validate_netcdf_chunking(params: dict, context: dict = None) -> dict:
    """
    Validate NetCDF file chunking for virtualization suitability.

    Pre-flight check that examines HDF5 internal chunking to determine
    if the file is suitable for kerchunk virtualization or needs physical
    conversion.

    Parameters:
        params.nc_url: Full URL to NetCDF file (abfs://container/path.nc)
        params.fail_on_warnings: If True, treat warnings as errors (default: False)

    Returns:
        {
            "status": "success" | "warning" | "error",
            "nc_url": str,
            "variables": {
                "tas": {
                    "shape": [3650, 720, 1440],
                    "dtype": "float32",
                    "chunks": [365, 180, 360],
                    "compression": "gzip"
                }
            },
            "warnings": ["tas: Very large spatial chunks..."],
            "recommendation": "suitable_for_virtualization" | "consider_physical_conversion"
        }
    """
    config = get_config()
    nc_url = params['nc_url']
    fail_on_warnings = params.get('fail_on_warnings', False)

    # Azure storage options
    storage_options = {"account_name": config.storage.account_name}

    result = {
        "nc_url": nc_url,
        "variables": {},
        "warnings": [],
        "recommendation": "suitable_for_virtualization"
    }

    try:
        fs = fsspec.filesystem("abfs", **storage_options)

        with fs.open(nc_url) as f:
            with h5py.File(f, 'r') as h5:
                for var_name in h5.keys():
                    var = h5[var_name]

                    # Skip non-array items (groups, etc.)
                    if not hasattr(var, 'shape') or len(var.shape) == 0:
                        continue

                    info = {
                        "shape": list(var.shape),
                        "dtype": str(var.dtype),
                        "chunks": list(var.chunks) if var.chunks else None,
                        "compression": var.compression,
                    }
                    result["variables"][var_name] = info

                    # Check for chunking problems
                    _check_chunking_issues(var_name, var, result)

        # Determine overall status
        if result["warnings"]:
            result["status"] = "warning"
            # Check for critical warnings
            critical_keywords = ["VERY slow", "single pixels"]
            has_critical = any(
                any(kw in w for kw in critical_keywords)
                for w in result["warnings"]
            )
            if has_critical:
                result["recommendation"] = "consider_physical_conversion"
                if fail_on_warnings:
                    result["status"] = "error"
        else:
            result["status"] = "success"

        logger.info(f"Validated {nc_url}: {result['status']}, {len(result['variables'])} variables")

    except Exception as e:
        logger.error(f"Failed to validate {nc_url}: {e}")
        result["status"] = "error"
        result["error"] = str(e)

    return result


def _check_chunking_issues(var_name: str, var, result: dict) -> None:
    """Check for chunking patterns that cause performance issues."""

    if var.chunks is None:
        # Contiguous (no chunking)
        size_mb = var.nbytes / (1024 * 1024)
        if size_mb > 100:
            result["warnings"].append(
                f"{var_name}: No chunking (contiguous), {size_mb:.0f}MB. "
                "Entire variable read for any access. May be slow for large files."
            )

    elif var.chunks and len(var.shape) >= 2:
        # Check for problematic spatial chunking
        spatial_chunks = var.chunks[-2:]  # Last two dims assumed spatial

        # Single-pixel chunking (disaster)
        if any(c == 1 for c in spatial_chunks):
            result["warnings"].append(
                f"{var_name}: Chunked by single pixels in spatial dims {spatial_chunks}. "
                "Will be VERY slow. Physical conversion recommended."
            )

        # Very large chunks
        elif any(c > 1000 for c in spatial_chunks):
            result["warnings"].append(
                f"{var_name}: Very large spatial chunks {spatial_chunks}. "
                "May cause slow tile generation for small areas."
            )

        # Very small chunks (many HTTP requests)
        elif all(c < 50 for c in spatial_chunks):
            chunk_count = 1
            for s, c in zip(var.shape, var.chunks):
                chunk_count *= (s + c - 1) // c

            if chunk_count > 10000:
                result["warnings"].append(
                    f"{var_name}: Tiny chunks {var.chunks}, ~{chunk_count} total chunks. "
                    "Many HTTP requests per read. Acceptable but not optimal."
                )
```

---

#### 1.3 Kerchunk Reference Generator

**File**: `services/netcdf_handlers/handler_generate_kerchunk.py`

```python
# ============================================================================
# CLAUDE CONTEXT - KERCHUNK REFERENCE GENERATOR
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Single-file kerchunk reference generation
# PURPOSE: Generate JSON reference file for one NetCDF file
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: generate_kerchunk_ref
# DEPENDENCIES: virtualizarr, fsspec, adlfs
# ============================================================================

import logging
import json
from typing import Any

from virtualizarr import open_virtual_dataset
import fsspec

from config.app_config import get_config

logger = logging.getLogger(__name__)


def generate_kerchunk_ref(params: dict, context: dict = None) -> dict:
    """
    Generate kerchunk reference file for a single NetCDF file.

    This reads only the headers/metadata from the NetCDF file (~1MB read)
    and produces a JSON reference file that maps Zarr chunk keys to byte
    ranges in the original file.

    Parameters:
        params.nc_url: Full URL to source NetCDF (abfs://container/path.nc)
        params.ref_url: Full URL for output reference (abfs://silver/refs/path.json)

    Returns:
        {
            "status": "success" | "error",
            "nc_url": str,
            "ref_url": str,
            "dimensions": {"time": 3650, "lat": 720, "lon": 1440},
            "variables": ["tas", "lat", "lon", "time"],
            "ref_size_bytes": 1234567
        }
    """
    config = get_config()
    nc_url = params['nc_url']
    ref_url = params['ref_url']

    storage_options = {"account_name": config.storage.account_name}

    try:
        logger.info(f"Generating reference: {nc_url} → {ref_url}")

        # Open as virtual dataset (reads only headers)
        vds = open_virtual_dataset(nc_url, storage_options=storage_options)

        # Extract metadata before writing
        dimensions = dict(vds.dims)
        variables = list(vds.data_vars)
        attributes = dict(vds.attrs)

        # Write reference file
        vds.virtualize.to_kerchunk(
            ref_url,
            storage_options=storage_options,
            format="json"
        )

        # Get reference file size
        fs = fsspec.filesystem("abfs", **storage_options)
        ref_size = fs.size(ref_url.replace("abfs://", ""))

        logger.info(
            f"Generated reference: {ref_url} "
            f"({ref_size / 1024:.1f} KB, {len(variables)} variables)"
        )

        return {
            "status": "success",
            "nc_url": nc_url,
            "ref_url": ref_url,
            "dimensions": dimensions,
            "variables": variables,
            "attributes": attributes,
            "ref_size_bytes": ref_size,
        }

    except Exception as e:
        logger.error(f"Failed to generate reference for {nc_url}: {e}")
        return {
            "status": "error",
            "nc_url": nc_url,
            "ref_url": ref_url,
            "error": str(e),
        }
```

---

#### 1.4 Virtual Dataset Combiner

**File**: `services/netcdf_handlers/handler_combine_virtual.py`

```python
# ============================================================================
# CLAUDE CONTEXT - VIRTUAL DATASET COMBINER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Combine multiple refs into single virtual dataset
# PURPOSE: Concatenate time-series NetCDF files into one virtual Zarr
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: combine_virtual_datasets
# DEPENDENCIES: virtualizarr, xarray, fsspec
# ============================================================================

import logging
from typing import Any

from virtualizarr import open_virtual_dataset
import xarray as xr
import fsspec

from config.app_config import get_config

logger = logging.getLogger(__name__)


def combine_virtual_datasets(params: dict, context: dict = None) -> dict:
    """
    Combine multiple NetCDF files into a single virtual Zarr dataset.

    Opens each source file as a virtual dataset and concatenates them
    along the time dimension. The result is a single reference file
    that spans the entire time series.

    Parameters:
        params.nc_urls: List of NetCDF URLs to combine (in time order)
        params.combined_ref_url: Output URL for combined reference
        params.concat_dim: Dimension to concatenate along (default: "time")
        params.dataset_id: Identifier for this combined dataset

    Returns:
        {
            "status": "success" | "error",
            "dataset_id": str,
            "combined_ref_url": str,
            "source_files": int,
            "dimensions": {"time": 36500, "lat": 720, "lon": 1440},
            "time_range": ["2015-01-01", "2100-12-31"],
            "ref_size_bytes": int
        }
    """
    config = get_config()
    nc_urls = params['nc_urls']
    combined_ref_url = params['combined_ref_url']
    concat_dim = params.get('concat_dim', 'time')
    dataset_id = params.get('dataset_id', 'combined')

    storage_options = {"account_name": config.storage.account_name}

    try:
        logger.info(f"Combining {len(nc_urls)} files into {combined_ref_url}")

        # Open each file as virtual dataset
        virtual_datasets = []
        for nc_url in nc_urls:
            logger.debug(f"Opening virtual: {nc_url}")
            vds = open_virtual_dataset(nc_url, storage_options=storage_options)
            virtual_datasets.append(vds)

        # Concatenate along time dimension
        combined = xr.concat(virtual_datasets, dim=concat_dim)

        # Extract metadata
        dimensions = dict(combined.dims)
        variables = list(combined.data_vars)

        # Get time range if time dimension exists
        time_range = None
        if concat_dim in combined.coords:
            time_coord = combined.coords[concat_dim]
            time_range = [
                str(time_coord.values[0])[:10],   # Start date
                str(time_coord.values[-1])[:10],  # End date
            ]

        # Write combined reference
        combined.virtualize.to_kerchunk(
            combined_ref_url,
            storage_options=storage_options,
            format="json"
        )

        # Get reference file size
        fs = fsspec.filesystem("abfs", **storage_options)
        ref_size = fs.size(combined_ref_url.replace("abfs://", ""))

        logger.info(
            f"Combined {len(nc_urls)} files → {combined_ref_url} "
            f"({ref_size / 1024:.1f} KB)"
        )

        return {
            "status": "success",
            "dataset_id": dataset_id,
            "combined_ref_url": combined_ref_url,
            "source_files": len(nc_urls),
            "dimensions": dimensions,
            "variables": variables,
            "time_range": time_range,
            "ref_size_bytes": ref_size,
        }

    except Exception as e:
        logger.error(f"Failed to combine virtual datasets: {e}")
        return {
            "status": "error",
            "dataset_id": dataset_id,
            "combined_ref_url": combined_ref_url,
            "source_files": len(nc_urls),
            "error": str(e),
        }
```

---

### Phase 2: Jobs

#### 2.1 NetCDF Inventory Job

**File**: `jobs/inventory_netcdf.py`

```python
# ============================================================================
# CLAUDE CONTEXT - NETCDF INVENTORY JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - CMIP6 NetCDF inventory and grouping
# PURPOSE: Scan container, parse CMIP6 filenames, group into datasets
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: InventoryNetcdfJob
# DEPENDENCIES: jobs.base, jobs.mixins, services.netcdf_handlers
# ============================================================================

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class InventoryNetcdfJob(JobBaseMixin, JobBase):
    """
    Inventory NetCDF files in a container and group by CMIP6 dataset.

    Scans a container for .nc files, parses CMIP6-compliant filenames,
    and groups files that belong to the same logical dataset (same
    variable/model/scenario/variant/grid, different time ranges).

    Output is used by generate_virtual_zarr job to create combined
    virtual datasets.
    """

    job_type = "inventory_netcdf"
    description = "Scan container for NetCDF files and group by CMIP6 dataset"

    stages = [
        {
            "number": 1,
            "name": "scan",
            "task_type": "scan_netcdf_container",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "parse",
            "task_type": "parse_cmip6_metadata",
            "parallelism": "fan_out"  # One task per file
        },
        {
            "number": 3,
            "name": "group",
            "task_type": "group_cmip6_datasets",
            "parallelism": "single"
        },
    ]

    parameters_schema = {
        'container': {
            'type': 'str',
            'required': True,
            'description': 'Azure blob container to scan'
        },
        'prefix': {
            'type': 'str',
            'default': '',
            'description': 'Blob prefix to filter (e.g., "cmip6/CESM2/")'
        },
        'recursive': {
            'type': 'bool',
            'default': True,
            'description': 'Scan subdirectories recursively'
        },
    }

    resource_validators = [
        {
            'type': 'container_exists',
            'container_param': 'container',
            'error': 'Container does not exist'
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: dict, job_params: dict, job_id: str,
                                previous_results: list = None) -> list:
        """Create tasks for each stage."""
        stage_num = stage['number']

        if stage_num == 1:
            # Single task to scan container
            return [{
                "task_id": f"{job_id[:8]}-scan",
                "task_type": "scan_netcdf_container",
                "parameters": {
                    "container": job_params['container'],
                    "prefix": job_params.get('prefix', ''),
                    "recursive": job_params.get('recursive', True),
                }
            }]

        elif stage_num == 2:
            # Fan-out: one task per file discovered
            if not previous_results:
                return []

            # Previous stage returns list of nc_urls
            scan_result = previous_results[0].get('result', {})
            nc_files = scan_result.get('nc_files', [])

            return [
                {
                    "task_id": f"{job_id[:8]}-parse-{i}",
                    "task_type": "parse_cmip6_metadata",
                    "parameters": {"nc_url": nc_url}
                }
                for i, nc_url in enumerate(nc_files)
            ]

        elif stage_num == 3:
            # Single task to group parsed metadata
            return [{
                "task_id": f"{job_id[:8]}-group",
                "task_type": "group_cmip6_datasets",
                "parameters": {
                    "job_id": job_id,  # To retrieve stage 2 results
                }
            }]

        return []
```

---

#### 2.2 Virtual Zarr Generation Job

**File**: `jobs/generate_virtual_zarr.py`

```python
# ============================================================================
# CLAUDE CONTEXT - VIRTUAL ZARR GENERATION JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - Generate kerchunk references and register STAC
# PURPOSE: Create virtual Zarr from NetCDF, combine time series, catalog
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: GenerateVirtualZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class GenerateVirtualZarrJob(JobBaseMixin, JobBase):
    """
    Generate virtual Zarr references for NetCDF files and register in STAC.

    Takes a dataset group (files with same variable/model/scenario) and:
    1. Validates chunking suitability
    2. Generates individual kerchunk references
    3. Combines into single virtual dataset
    4. Registers STAC item with zarr_ref asset

    Can be triggered manually with explicit file list, or automatically
    from inventory_netcdf job output.
    """

    job_type = "generate_virtual_zarr"
    description = "Generate kerchunk references and STAC catalog for NetCDF dataset"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_netcdf_chunking",
            "parallelism": "fan_out"  # Validate each file
        },
        {
            "number": 2,
            "name": "generate_refs",
            "task_type": "generate_kerchunk_ref",
            "parallelism": "fan_out"  # One ref per file
        },
        {
            "number": 3,
            "name": "combine",
            "task_type": "combine_virtual_datasets",
            "parallelism": "single"
        },
        {
            "number": 4,
            "name": "register_stac",
            "task_type": "register_xarray_stac",
            "parallelism": "single"
        },
    ]

    parameters_schema = {
        'dataset_id': {
            'type': 'str',
            'required': True,
            'description': 'Unique identifier for this dataset (e.g., tas_day_CESM2_ssp245)'
        },
        'nc_urls': {
            'type': 'list',
            'required': True,
            'description': 'List of NetCDF URLs to process (in time order)'
        },
        'collection_id': {
            'type': 'str',
            'default': 'cmip6-virtual',
            'description': 'STAC collection to add item to'
        },
        'refs_container': {
            'type': 'str',
            'default': 'rmhazuregeosilver',
            'description': 'Container for reference files'
        },
        'refs_prefix': {
            'type': 'str',
            'default': 'refs/cmip6',
            'description': 'Blob prefix for reference files'
        },
        'fail_on_chunking_warnings': {
            'type': 'bool',
            'default': False,
            'description': 'Fail job if chunking warnings detected'
        },
    }

    @staticmethod
    def create_tasks_for_stage(stage: dict, job_params: dict, job_id: str,
                                previous_results: list = None) -> list:
        """Create tasks for each stage."""
        stage_num = stage['number']
        nc_urls = job_params['nc_urls']
        dataset_id = job_params['dataset_id']
        refs_container = job_params.get('refs_container', 'rmhazuregeosilver')
        refs_prefix = job_params.get('refs_prefix', 'refs/cmip6')

        if stage_num == 1:
            # Validate each file's chunking
            return [
                {
                    "task_id": f"{job_id[:8]}-validate-{i}",
                    "task_type": "validate_netcdf_chunking",
                    "parameters": {
                        "nc_url": nc_url,
                        "fail_on_warnings": job_params.get('fail_on_chunking_warnings', False),
                    }
                }
                for i, nc_url in enumerate(nc_urls)
            ]

        elif stage_num == 2:
            # Generate reference for each file
            return [
                {
                    "task_id": f"{job_id[:8]}-ref-{i}",
                    "task_type": "generate_kerchunk_ref",
                    "parameters": {
                        "nc_url": nc_url,
                        "ref_url": _build_ref_url(nc_url, refs_container, refs_prefix),
                    }
                }
                for i, nc_url in enumerate(nc_urls)
            ]

        elif stage_num == 3:
            # Combine into single virtual dataset
            combined_ref_url = f"abfs://{refs_container}/{refs_prefix}/{dataset_id}_combined.json"
            return [{
                "task_id": f"{job_id[:8]}-combine",
                "task_type": "combine_virtual_datasets",
                "parameters": {
                    "nc_urls": nc_urls,
                    "combined_ref_url": combined_ref_url,
                    "dataset_id": dataset_id,
                }
            }]

        elif stage_num == 4:
            # Register STAC item
            # Get combine result for metadata
            combine_result = {}
            if previous_results:
                combine_result = previous_results[0].get('result', {})

            return [{
                "task_id": f"{job_id[:8]}-stac",
                "task_type": "register_xarray_stac",
                "parameters": {
                    "dataset_id": dataset_id,
                    "collection_id": job_params.get('collection_id', 'cmip6-virtual'),
                    "combined_ref_url": combine_result.get('combined_ref_url'),
                    "nc_urls": nc_urls,
                    "dimensions": combine_result.get('dimensions', {}),
                    "variables": combine_result.get('variables', []),
                    "time_range": combine_result.get('time_range'),
                    "job_id": job_id,
                }
            }]

        return []


def _build_ref_url(nc_url: str, refs_container: str, refs_prefix: str) -> str:
    """Build reference URL from source NetCDF URL."""
    # Extract filename from nc_url
    filename = nc_url.split('/')[-1]
    ref_filename = filename.replace('.nc', '.json')
    return f"abfs://{refs_container}/{refs_prefix}/{ref_filename}"
```

---

### Phase 3: STAC Integration

#### 3.1 xarray STAC Registration Handler

**File**: `services/netcdf_handlers/handler_register_xarray_stac.py`

```python
# ============================================================================
# CLAUDE CONTEXT - XARRAY STAC REGISTRATION
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Register virtual Zarr dataset in STAC
# PURPOSE: Create STAC item with datacube extension and zarr_ref asset
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: register_xarray_stac
# DEPENDENCIES: infrastructure.pgstac_repository
# ============================================================================

import logging
from datetime import datetime
from typing import Any
import json

from config.app_config import get_config
from infrastructure.pgstac_repository import PgStacRepository
from services.netcdf_handlers.cmip6_parser import (
    parse_cmip6_filename,
    get_variable_description,
    get_scenario_description,
)

logger = logging.getLogger(__name__)


def register_xarray_stac(params: dict, context: dict = None) -> dict:
    """
    Register a virtual Zarr dataset as a STAC item.

    Creates a STAC item with:
    - datacube extension for dimension metadata
    - zarr_ref asset pointing to kerchunk reference
    - netcdf_source asset pointing to original files
    - CMIP6 metadata in properties

    Parameters:
        params.dataset_id: Unique dataset identifier
        params.collection_id: Target STAC collection
        params.combined_ref_url: URL to combined kerchunk reference
        params.nc_urls: List of source NetCDF URLs
        params.dimensions: Dict of dimension sizes
        params.variables: List of variable names
        params.time_range: [start_date, end_date] or None
        params.job_id: Job ID for provenance

    Returns:
        {
            "status": "success" | "error",
            "stac_item_id": str,
            "collection_id": str,
        }
    """
    config = get_config()

    dataset_id = params['dataset_id']
    collection_id = params['collection_id']
    combined_ref_url = params['combined_ref_url']
    nc_urls = params.get('nc_urls', [])
    dimensions = params.get('dimensions', {})
    variables = params.get('variables', [])
    time_range = params.get('time_range')
    job_id = params.get('job_id')

    try:
        # Parse CMIP6 metadata from dataset_id or first file
        cmip6_meta = None
        if nc_urls:
            cmip6_meta = parse_cmip6_filename(nc_urls[0])

        # Build STAC item
        stac_item = _build_stac_item(
            dataset_id=dataset_id,
            combined_ref_url=combined_ref_url,
            nc_urls=nc_urls,
            dimensions=dimensions,
            variables=variables,
            time_range=time_range,
            cmip6_meta=cmip6_meta,
            job_id=job_id,
        )

        # Ensure collection exists
        repo = PgStacRepository()
        _ensure_collection_exists(repo, collection_id)

        # Upsert item
        repo.upsert_item(collection_id, stac_item)

        logger.info(f"Registered STAC item: {dataset_id} in {collection_id}")

        return {
            "status": "success",
            "stac_item_id": dataset_id,
            "collection_id": collection_id,
        }

    except Exception as e:
        logger.error(f"Failed to register STAC item {dataset_id}: {e}")
        return {
            "status": "error",
            "stac_item_id": dataset_id,
            "collection_id": collection_id,
            "error": str(e),
        }


def _build_stac_item(
    dataset_id: str,
    combined_ref_url: str,
    nc_urls: list,
    dimensions: dict,
    variables: list,
    time_range: list,
    cmip6_meta,
    job_id: str,
) -> dict:
    """Build STAC item with datacube extension."""

    now = datetime.utcnow().isoformat() + "Z"

    # Determine temporal extent
    start_datetime = None
    end_datetime = None
    if time_range and len(time_range) == 2:
        start_datetime = f"{time_range[0]}T00:00:00Z"
        end_datetime = f"{time_range[1]}T23:59:59Z"

    # Build datacube dimensions
    cube_dimensions = {}
    if "time" in dimensions:
        cube_dimensions["time"] = {
            "type": "temporal",
            "extent": [start_datetime, end_datetime] if start_datetime else None,
        }
    if "lat" in dimensions or "y" in dimensions:
        lat_key = "lat" if "lat" in dimensions else "y"
        cube_dimensions["y"] = {
            "type": "spatial",
            "axis": "y",
            "extent": [-90, 90],
            "reference_system": 4326,
        }
    if "lon" in dimensions or "x" in dimensions:
        lon_key = "lon" if "lon" in dimensions else "x"
        cube_dimensions["x"] = {
            "type": "spatial",
            "axis": "x",
            "extent": [-180, 180],
            "reference_system": 4326,
        }

    # Build datacube variables
    cube_variables = {}
    for var in variables:
        cube_variables[var] = {
            "dimensions": list(dimensions.keys()),
            "type": "data",
        }

    # Build properties
    properties = {
        "datetime": None,  # Use start/end instead
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "cube:dimensions": cube_dimensions,
        "cube:variables": cube_variables,
        # App metadata
        "app:job_id": job_id,
        "app:job_type": "generate_virtual_zarr",
        "app:created": now,
    }

    # Add CMIP6 metadata if available
    if cmip6_meta:
        properties.update({
            "cmip6:variable": cmip6_meta.variable,
            "cmip6:variable_description": get_variable_description(cmip6_meta.variable),
            "cmip6:frequency": cmip6_meta.frequency,
            "cmip6:model": cmip6_meta.model,
            "cmip6:scenario": cmip6_meta.scenario,
            "cmip6:scenario_description": get_scenario_description(cmip6_meta.scenario),
            "cmip6:variant": cmip6_meta.variant,
            "cmip6:grid": cmip6_meta.grid,
        })

    # Build assets
    assets = {
        "zarr_ref": {
            "href": combined_ref_url,
            "type": "application/vnd+zarr+json",
            "title": "Virtual Zarr Reference",
            "roles": ["data", "zarr"],
            "description": "Kerchunk reference for cloud-native access",
        },
    }

    # Add source reference
    if nc_urls:
        # Get container/prefix from first URL
        first_url = nc_urls[0]
        if '/' in first_url:
            source_dir = '/'.join(first_url.split('/')[:-1])
            assets["netcdf_source"] = {
                "href": source_dir,
                "type": "application/x-netcdf",
                "title": "Source NetCDF Files",
                "roles": ["source"],
                "description": f"Original NetCDF files ({len(nc_urls)} files)",
            }

    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
        ],
        "id": dataset_id,
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
            ]]
        },
        "bbox": [-180, -90, 180, 90],
        "assets": assets,
        "links": [],
    }


def _ensure_collection_exists(repo: PgStacRepository, collection_id: str) -> None:
    """Create collection if it doesn't exist."""
    if repo.collection_exists(collection_id):
        return

    collection = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
        ],
        "id": collection_id,
        "title": "CMIP6 Virtual Zarr Datasets",
        "description": "Climate model outputs accessible as virtual Zarr via kerchunk references",
        "license": "various",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [["2015-01-01T00:00:00Z", None]]}
        },
        "links": [],
    }

    repo.upsert_collection(collection)
    logger.info(f"Created collection: {collection_id}")
```

---

### Phase 4: Handler Registration

#### 4.1 Handler Module Init

**File**: `services/netcdf_handlers/__init__.py`

```python
# ============================================================================
# CLAUDE CONTEXT - NETCDF HANDLERS MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Module - NetCDF/Kerchunk handler exports
# PURPOSE: Export all NetCDF-related handlers for registration
# LAST_REVIEWED: 17 DEC 2025
# ============================================================================

from services.netcdf_handlers.handler_validate_netcdf import validate_netcdf_chunking
from services.netcdf_handlers.handler_generate_kerchunk import generate_kerchunk_ref
from services.netcdf_handlers.handler_combine_virtual import combine_virtual_datasets
from services.netcdf_handlers.handler_register_xarray_stac import register_xarray_stac
from services.netcdf_handlers.cmip6_parser import (
    parse_cmip6_filename,
    group_cmip6_files,
    CMIP6FileMetadata,
)

# Additional handlers for inventory job
from services.netcdf_handlers.handler_inventory import (
    scan_netcdf_container,
    parse_cmip6_metadata,
    group_cmip6_datasets,
)

__all__ = [
    # Validation
    'validate_netcdf_chunking',
    # Reference generation
    'generate_kerchunk_ref',
    'combine_virtual_datasets',
    # STAC
    'register_xarray_stac',
    # Inventory
    'scan_netcdf_container',
    'parse_cmip6_metadata',
    'group_cmip6_datasets',
    # Parser utilities
    'parse_cmip6_filename',
    'group_cmip6_files',
    'CMIP6FileMetadata',
]
```

#### 4.2 Registration in services/__init__.py

Add to the ALL_HANDLERS dict:

```python
# NetCDF / Virtual Zarr handlers
from services.netcdf_handlers import (
    validate_netcdf_chunking,
    generate_kerchunk_ref,
    combine_virtual_datasets,
    register_xarray_stac,
    scan_netcdf_container,
    parse_cmip6_metadata,
    group_cmip6_datasets,
)

ALL_HANDLERS = {
    # ... existing handlers ...

    # NetCDF / Virtual Zarr
    "validate_netcdf_chunking": validate_netcdf_chunking,
    "generate_kerchunk_ref": generate_kerchunk_ref,
    "combine_virtual_datasets": combine_virtual_datasets,
    "register_xarray_stac": register_xarray_stac,
    "scan_netcdf_container": scan_netcdf_container,
    "parse_cmip6_metadata": parse_cmip6_metadata,
    "group_cmip6_datasets": group_cmip6_datasets,
}
```

#### 4.3 Registration in jobs/__init__.py

Add to ALL_JOBS:

```python
from jobs.inventory_netcdf import InventoryNetcdfJob
from jobs.generate_virtual_zarr import GenerateVirtualZarrJob

ALL_JOBS = {
    # ... existing jobs ...

    # NetCDF / Virtual Zarr
    "inventory_netcdf": InventoryNetcdfJob,
    "generate_virtual_zarr": GenerateVirtualZarrJob,
}
```

---

### Phase 5: Dependencies

#### 5.1 requirements.txt additions

```txt
# Virtual Zarr / Kerchunk
virtualizarr>=1.0.0
kerchunk>=0.2.0

# NetCDF support
h5netcdf>=1.3.0
h5py>=3.10.0
netCDF4>=1.6.0

# Already present (verify versions)
xarray>=2024.1.0
zarr>=2.16.0
fsspec>=2024.2.0
adlfs>=2024.4.1
```

---

## Testing Commands

### 1. Validate Single NetCDF

```bash
# Check chunking before processing
curl -X POST .../api/jobs/submit/generate_virtual_zarr \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test_validation",
    "nc_urls": ["abfs://bronze/cmip6/test.nc"],
    "fail_on_chunking_warnings": true
  }'
```

### 2. Process Single Dataset

```bash
curl -X POST .../api/jobs/submit/generate_virtual_zarr \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "tas_day_CESM2_ssp245",
    "nc_urls": [
      "abfs://bronze/cmip6/CESM2/ssp245/tas_day_CESM2_ssp245_r1i1p1f1_gn_20150101-20241231.nc",
      "abfs://bronze/cmip6/CESM2/ssp245/tas_day_CESM2_ssp245_r1i1p1f1_gn_20250101-20341231.nc"
    ],
    "collection_id": "cmip6-virtual"
  }'
```

### 3. Inventory Container

```bash
curl -X POST .../api/jobs/submit/inventory_netcdf \
  -H "Content-Type: application/json" \
  -d '{
    "container": "rmhazuregeobronze",
    "prefix": "cmip6/"
  }'
```

### 4. Verify STAC Registration

```bash
# Check item exists
curl .../api/stac/collections/cmip6-virtual/items/tas_day_CESM2_ssp245
```

### 5. Test TiTiler-xarray Access

```bash
# Get tile from virtual dataset
curl ".../api/xarray/tiles/cmip6-virtual/tas_day_CESM2_ssp245/0/0/0.png?variable=tas"
```

---

## Implementation Order

| Order | Component | File | Estimated Effort |
|-------|-----------|------|------------------|
| 1 | CMIP6 Parser | `services/netcdf_handlers/cmip6_parser.py` | Small |
| 2 | Chunking Validator | `services/netcdf_handlers/handler_validate_netcdf.py` | Small |
| 3 | Reference Generator | `services/netcdf_handlers/handler_generate_kerchunk.py` | Medium |
| 4 | Virtual Combiner | `services/netcdf_handlers/handler_combine_virtual.py` | Medium |
| 5 | STAC Registration | `services/netcdf_handlers/handler_register_xarray_stac.py` | Medium |
| 6 | Inventory Handlers | `services/netcdf_handlers/handler_inventory.py` | Small |
| 7 | Generate Job | `jobs/generate_virtual_zarr.py` | Small |
| 8 | Inventory Job | `jobs/inventory_netcdf.py` | Small |
| 9 | Handler Registration | `services/__init__.py` | Trivial |
| 10 | Job Registration | `jobs/__init__.py` | Trivial |
| 11 | Dependencies | `requirements.txt` | Trivial |
| 12 | TiTiler Config | TiTiler-xarray setup | Medium |

---

## TiTiler-xarray Configuration (Separate Concern)

TiTiler-xarray needs to be configured to:

1. **Handle `reference://` protocol** for kerchunk refs
2. **Azure authentication** for both refs and source NetCDF
3. **Asset routing** - prefer `zarr_ref` over raw `netcdf`

This is deployment configuration, not application code. See TiTiler-xarray documentation for setup.

---

## Success Criteria

1. ✅ CMIP6 NetCDF files remain in Bronze container (unchanged)
2. ✅ Kerchunk references generated in Silver/refs (~1MB each)
3. ✅ Combined virtual datasets span full time series
4. ✅ STAC items registered with datacube extension
5. ✅ TiTiler-xarray serves tiles from virtual datasets
6. ✅ No physical Zarr conversion required
7. ✅ Client saves weeks of compute and 2x storage costs

---

## References

- `NETCDF.md` - Original technical guide (kerchunk/virtualizarr details)
- `docs_claude/JOB_CREATION_QUICKSTART.md` - JobBaseMixin patterns
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Stage/task patterns
