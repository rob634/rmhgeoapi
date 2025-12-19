# VirtualiZarr & Kerchunk Implementation Guide

## Overview

This guide covers how to serve legacy NetCDF files as cloud-native Zarr **without converting or copying the data**. Instead of physical conversion, we generate lightweight reference files that map Zarr chunk requests to byte ranges in the original NetCDF files.

### The Problem

```
Client: "We have 50 TB of NetCDF files"
Old solution: Convert everything to Zarr (weeks of compute, 2x storage, prayer mode)
New solution: Generate reference files (hours, trivial storage, chill mode)
```

### The Insight

NetCDF files (HDF5 under the hood) are already chunked internally. The chunks exist - we just need to tell xarray where they are.

---

## Concept: Virtual Zarr via Reference Files

### Physical Conversion (The Old Way)

```
NetCDF file                      Zarr store
┌──────────┐                     ┌──────────┐
│██████████│                     │ .zarray  │
│██████████│   ───── ETL ─────►  │ 0.0.0    │
│██████████│   (copy all data)   │ 0.0.1    │
│██████████│                     │ 0.1.0    │
└──────────┘                     │ ...      │
   500 GB                        └──────────┘
                                    500 GB

Storage: 1 TB total (doubled)
Time: Hours to days
Risk: High (OOM, network drops, corruption)
```

### Virtual Zarr (The Kerchunk Way)

```
NetCDF file                      Reference file
┌──────────┐                     ┌────────────────────────┐
│██████████│                     │ {                      │
│██████████│   ── scan meta ──►  │   "0.0.0": [file, 0,   │
│██████████│   (read headers)    │             1024],     │
│██████████│                     │   "0.0.1": [file, 1024,│
└──────────┘                     │             1024],     │
   500 GB                        │   ...                  │
(unchanged)                      │ }                      │
                                 └────────────────────────┘
                                        ~10 MB

Storage: 500 GB + 10 MB (negligible increase)
Time: Minutes
Risk: Minimal (just reading headers)
```

---

## How Reference Files Work

### The Reference Structure

A kerchunk reference file is JSON that maps Zarr chunk keys to byte ranges:

```json
{
  "version": 1,
  "refs": {
    ".zgroup": "{\"zarr_format\":2}",
    ".zattrs": "{\"Conventions\":\"CF-1.6\",\"history\":\"Created by climate model\"}",
    
    "temperature/.zarray": "{\"chunks\":[365,180,360],\"compressor\":null,\"dtype\":\"<f4\",\"fill_value\":\"NaN\",\"filters\":null,\"order\":\"C\",\"shape\":[3650,720,1440],\"zarr_format\":2}",
    "temperature/.zattrs": "{\"_ARRAY_DIMENSIONS\":[\"time\",\"lat\",\"lon\"],\"units\":\"K\",\"long_name\":\"Near-Surface Air Temperature\"}",
    
    "temperature/0.0.0": ["abfs://archive/climate.nc", 10240, 524288],
    "temperature/0.0.1": ["abfs://archive/climate.nc", 534528, 524288],
    "temperature/0.1.0": ["abfs://archive/climate.nc", 1058816, 524288],
    "temperature/1.0.0": ["abfs://archive/climate.nc", 1583104, 524288]
  }
}
```

Each data chunk entry is: `[file_url, byte_offset, byte_length]`

### The Read Flow

When xarray requests chunk `temperature/0.0.1`:

```
1. xarray: "I need chunk 0.0.1"
           │
           ▼
2. fsspec reference filesystem looks up in JSON:
   "temperature/0.0.1": ["abfs://archive/climate.nc", 534528, 524288]
           │
           ▼
3. HTTP range request to original file:
   GET abfs://archive/climate.nc
   Range: bytes=534528-1058815
           │
           ▼
4. Returns 524288 bytes (the chunk data)
           │
           ▼
5. xarray decompresses and returns array
```

**The NetCDF file never moves. xarray thinks it's Zarr.**

---

## Tools: Kerchunk vs VirtualiZarr

### Kerchunk (Lower Level)

The original library by Martin Durant (the fsspec creator).

```python
from kerchunk.hdf import SingleHdf5ToZarr
from kerchunk.combine import MultiZarrToZarr
import fsspec
import ujson

# Scan a single NetCDF/HDF5 file
nc_url = "abfs://archive/climate/temperature_2050.nc"

storage_options = {"account_name": "youraccount"}
fs = fsspec.filesystem("abfs", **storage_options)

with fs.open(nc_url) as f:
    h5chunks = SingleHdf5ToZarr(f, nc_url)
    refs = h5chunks.translate()

# Save reference file
with fs.open("abfs://refs/temperature_2050.json", "w") as f:
    ujson.dump(refs, f)
```

### VirtualiZarr (Higher Level)

Nicer API, better xarray integration, recommended for new projects.

```python
from virtualizarr import open_virtual_dataset
import xarray as xr

storage_options = {"account_name": "youraccount"}

# Open NetCDF as virtual dataset
vds = open_virtual_dataset(
    "abfs://archive/climate/temperature.nc",
    storage_options=storage_options
)

# It looks like a normal xarray Dataset
print(vds)
# <xarray.Dataset>
# Dimensions: (time: 3650, lat: 720, lon: 1440)
# Coordinates:
#   * time     (time) datetime64[ns] ...
#   * lat      (lat) float64 ...
#   * lon      (lon) float64 ...
# Data variables:
#     temperature (time, lat, lon) float32 ...

# Save the reference (not the data!)
vds.virtualize.to_kerchunk(
    "abfs://refs/temperature.json",
    storage_options=storage_options,
    format="json"
)
```

### Combining Multiple Files

Climate data often spans multiple files. Combine them into one virtual dataset:

```python
from virtualizarr import open_virtual_dataset
import xarray as xr

# Open each file as virtual
virtual_datasets = [
    open_virtual_dataset(f"abfs://archive/temperature_{year}.nc")
    for year in range(2020, 2100)
]

# Concatenate along time dimension
combined = xr.concat(virtual_datasets, dim="time")

# Save combined reference
combined.virtualize.to_kerchunk(
    "abfs://refs/temperature_2020-2100.json",
    format="json"
)

# One reference file for 80 years of data!
```

### Reference File Formats

For large archives with millions of chunks, JSON gets unwieldy. Use Parquet:

```python
# JSON - good for smaller references (<100MB)
vds.virtualize.to_kerchunk("refs.json", format="json")

# Parquet - good for large references (>100MB)
vds.virtualize.to_kerchunk("refs.parquet", format="parquet")
```

---

## Opening Virtual Datasets

### From Reference File

```python
import xarray as xr

storage_options = {"account_name": "youraccount"}

# Open from JSON reference
ds = xr.open_dataset(
    "reference://",
    engine="zarr",
    backend_kwargs={
        "consolidated": False,
        "storage_options": {
            "fo": "abfs://refs/temperature.json",        # Reference file location
            "remote_protocol": "abfs",                    # Protocol for actual data
            "remote_options": storage_options             # Auth for actual data
        }
    }
)

# Now use like any xarray dataset
temp_slice = ds['temperature'].sel(time='2050-07-15', lat=slice(30, 50))
values = temp_slice.values  # Fetches only needed chunks from original NetCDF
```

### Universal Opener Function

```python
import xarray as xr

def open_dataset_universal(url: str, storage_options: dict = None) -> xr.Dataset:
    """
    Open real Zarr, virtual Zarr (kerchunk), or raw NetCDF.
    Automatically detects format from URL.
    """
    storage_options = storage_options or {}
    
    if url.endswith('.json') or '/refs/' in url:
        # Kerchunk reference file (JSON)
        return xr.open_dataset(
            "reference://",
            engine="zarr",
            backend_kwargs={
                "consolidated": False,
                "storage_options": {
                    "fo": url,
                    "remote_protocol": "abfs",
                    "remote_options": storage_options
                }
            }
        )
    
    elif url.endswith('.parquet') and 'refs' in url:
        # Kerchunk reference file (Parquet)
        return xr.open_dataset(
            "reference://",
            engine="zarr",
            backend_kwargs={
                "consolidated": False,
                "storage_options": {
                    "fo": url,
                    "remote_protocol": "abfs",
                    "remote_options": storage_options
                }
            }
        )
    
    elif '.zarr' in url:
        # Real Zarr store
        return xr.open_zarr(url, storage_options=storage_options)
    
    elif url.endswith('.nc') or url.endswith('.nc4'):
        # Raw NetCDF (slow path - no virtualization)
        return xr.open_dataset(
            url, 
            engine="h5netcdf",
            storage_options=storage_options
        )
    
    else:
        raise ValueError(f"Unknown format: {url}")
```

---

## TiTiler-xarray Integration

### Modified Reader

Update your TiTiler-xarray to handle kerchunk references:

```python
"""
TiTiler xarray reader with kerchunk support
"""
from typing import Callable, Optional
import attr
import xarray as xr
from titiler.xarray.io import Reader

@attr.s
class KerchunkAwareReader(Reader):
    """
    Extended xarray reader that handles:
    - Real Zarr stores
    - Kerchunk reference files (JSON/Parquet)
    - Raw NetCDF (fallback)
    """
    
    input: str = attr.ib()
    storage_options: dict = attr.ib(factory=dict)
    
    def __attrs_post_init__(self):
        """Open the dataset based on URL pattern."""
        self.ds = self._open_dataset(self.input)
        super().__attrs_post_init__()
    
    def _open_dataset(self, url: str) -> xr.Dataset:
        """Route to appropriate opener based on URL."""
        
        if url.endswith('.json') or '/refs/' in url:
            # Kerchunk JSON reference
            return xr.open_dataset(
                "reference://",
                engine="zarr",
                backend_kwargs={
                    "consolidated": False,
                    "storage_options": {
                        "fo": url,
                        "remote_protocol": "abfs",
                        "remote_options": self.storage_options
                    }
                }
            )
        
        elif '.zarr' in url:
            # Real Zarr
            return xr.open_zarr(url, storage_options=self.storage_options)
        
        else:
            # Assume NetCDF
            return xr.open_dataset(
                url,
                engine="h5netcdf",
                storage_options=self.storage_options
            )
```

### Factory Configuration

```python
from titiler.xarray.factory import TilerFactory

# Use custom reader in factory
xarray_tiler = TilerFactory(
    reader=KerchunkAwareReader,
    router_prefix="/xarray"
)

app.include_router(xarray_tiler.router, prefix="/xarray")
```

### URL Patterns

| Data Type | URL Pattern | Example |
|-----------|-------------|---------|
| Real Zarr | `*.zarr` or `*.zarr/` | `abfs://data/climate.zarr` |
| Kerchunk JSON | `*.json` or `/refs/*` | `abfs://refs/climate.json` |
| Raw NetCDF | `*.nc` or `*.nc4` | `abfs://raw/climate.nc` |

---

## Reference Generation Pipeline

### One-Time Batch Processing

For processing an existing archive of NetCDF files:

```python
"""
batch_generate_refs.py

Process client's NetCDF archive and generate kerchunk references.
Run once, outputs reference files for all inputs.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from virtualizarr import open_virtual_dataset
import fsspec

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
STORAGE_ACCOUNT = "yourstorageaccount"
STORAGE_OPTIONS = {"account_name": STORAGE_ACCOUNT}
INPUT_CONTAINER = "raw-netcdf"
OUTPUT_CONTAINER = "refs"
MAX_WORKERS = 10


def generate_reference(nc_path: str) -> dict:
    """
    Generate kerchunk reference for a single NetCDF file.
    
    Input:  abfs://raw-netcdf/climate/tas_2050.nc  (could be GBs)
    Output: abfs://refs/climate/tas_2050.json      (typically MBs)
    
    Returns dict with status info.
    """
    try:
        # Construct output path
        ref_path = nc_path.replace(INPUT_CONTAINER, OUTPUT_CONTAINER).replace('.nc', '.json')
        
        # Open and scan (reads only headers, not data!)
        vds = open_virtual_dataset(nc_path, storage_options=STORAGE_OPTIONS)
        
        # Get some stats
        dims = dict(vds.dims)
        variables = list(vds.data_vars)
        
        # Write reference file
        vds.virtualize.to_kerchunk(
            ref_path,
            storage_options=STORAGE_OPTIONS,
            format="json"
        )
        
        logger.info(f"✓ {nc_path} → {ref_path}")
        
        return {
            "status": "success",
            "input": nc_path,
            "output": ref_path,
            "dimensions": dims,
            "variables": variables
        }
        
    except Exception as e:
        logger.error(f"✗ {nc_path}: {e}")
        return {
            "status": "error",
            "input": nc_path,
            "error": str(e)
        }


def process_archive():
    """Process all NetCDF files in the input container."""
    
    # List all NetCDF files
    fs = fsspec.filesystem("abfs", **STORAGE_OPTIONS)
    nc_files = fs.glob(f"{INPUT_CONTAINER}/**/*.nc")
    nc_files = [f"abfs://{f}" for f in nc_files]
    
    logger.info(f"Found {len(nc_files)} NetCDF files to process")
    
    # Process in parallel
    results = {"success": [], "error": []}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(generate_reference, f): f for f in nc_files}
        
        for future in as_completed(futures):
            result = future.result()
            results[result["status"]].append(result)
    
    # Summary
    logger.info("=" * 60)
    logger.info(f"Processing complete!")
    logger.info(f"  Success: {len(results['success'])}")
    logger.info(f"  Errors:  {len(results['error'])}")
    logger.info("=" * 60)
    
    return results


if __name__ == "__main__":
    process_archive()
```

### Azure Function: Event-Driven Generation

For ongoing ingestion - generate references as new NetCDF files arrive:

```python
"""
Azure Function: Kerchunk Reference Generator

Trigger: Blob trigger on NetCDF upload
Output: Reference JSON file in refs container
"""
import logging
import os
import azure.functions as func
from virtualizarr import open_virtual_dataset

STORAGE_ACCOUNT = os.environ["AZURE_STORAGE_ACCOUNT_NAME"]
STORAGE_OPTIONS = {"account_name": STORAGE_ACCOUNT}


def main(blob: func.InputStream):
    """
    Triggered when NetCDF file lands in raw-netcdf container.
    Generates kerchunk reference in refs container.
    """
    logging.info(f"Processing: {blob.name}")
    
    # Construct paths
    nc_url = f"abfs://raw-netcdf/{blob.name}"
    ref_url = f"abfs://refs/{blob.name.replace('.nc', '.json')}"
    
    try:
        # Generate reference (reads ~1MB headers, writes ~1MB JSON)
        vds = open_virtual_dataset(nc_url, storage_options=STORAGE_OPTIONS)
        vds.virtualize.to_kerchunk(ref_url, storage_options=STORAGE_OPTIONS)
        
        logging.info(f"✓ Generated reference: {ref_url}")
        
    except Exception as e:
        logging.error(f"✗ Failed to process {blob.name}: {e}")
        raise


# function.json
"""
{
  "bindings": [
    {
      "name": "blob",
      "type": "blobTrigger",
      "direction": "in",
      "path": "raw-netcdf/{name}.nc",
      "connection": "AzureWebJobsStorage"
    }
  ]
}
"""
```

### HTTP-Triggered Generation

For on-demand reference generation:

```python
"""
Azure Function: On-Demand Reference Generator

POST /api/generate-reference
Body: {"netcdf_url": "abfs://raw/climate.nc"}
"""
import logging
import os
import json
import azure.functions as func
from virtualizarr import open_virtual_dataset

STORAGE_OPTIONS = {"account_name": os.environ["AZURE_STORAGE_ACCOUNT_NAME"]}


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Generate kerchunk reference on demand."""
    
    try:
        body = req.get_json()
        nc_url = body.get("netcdf_url")
        
        if not nc_url:
            return func.HttpResponse(
                json.dumps({"error": "netcdf_url required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Generate reference path
        ref_url = nc_url.replace("/raw/", "/refs/").replace(".nc", ".json")
        
        # Generate reference
        vds = open_virtual_dataset(nc_url, storage_options=STORAGE_OPTIONS)
        vds.virtualize.to_kerchunk(ref_url, storage_options=STORAGE_OPTIONS)
        
        # Get metadata
        result = {
            "status": "success",
            "input": nc_url,
            "output": ref_url,
            "dimensions": dict(vds.dims),
            "variables": list(vds.data_vars),
            "attributes": dict(vds.attrs)
        }
        
        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.exception("Reference generation failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
```

---

## STAC Integration

### STAC Item with Reference Asset

Store the reference file as a STAC asset alongside (or instead of) the original NetCDF:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
  ],
  "id": "cmip6-tas-ssp245-2050",
  "properties": {
    "datetime": null,
    "start_datetime": "2050-01-01T00:00:00Z",
    "end_datetime": "2050-12-31T23:59:59Z",
    "cube:dimensions": {
      "time": {
        "type": "temporal",
        "extent": ["2050-01-01T00:00:00Z", "2050-12-31T23:59:59Z"]
      },
      "x": {
        "type": "spatial",
        "axis": "x",
        "extent": [-180, 180],
        "reference_system": 4326
      },
      "y": {
        "type": "spatial",
        "axis": "y",
        "extent": [-90, 90],
        "reference_system": 4326
      }
    },
    "cube:variables": {
      "tas": {
        "dimensions": ["time", "y", "x"],
        "type": "data",
        "unit": "K"
      }
    }
  },
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]
  },
  "bbox": [-180, -90, 180, 90],
  "assets": {
    "netcdf": {
      "href": "abfs://archive/cmip6/tas_ssp245_2050.nc",
      "type": "application/x-netcdf",
      "title": "Original NetCDF",
      "roles": ["data"],
      "description": "Original file for direct NetCDF access (slow)"
    },
    "zarr_ref": {
      "href": "abfs://refs/cmip6/tas_ssp245_2050.json",
      "type": "application/vnd+zarr+json",
      "title": "Virtual Zarr Reference",
      "roles": ["data", "zarr"],
      "description": "Kerchunk reference for cloud-native access (fast)"
    }
  }
}
```

### STAC Reader Priority

In your TiTiler pgSTAC reader, prefer `zarr_ref` over `netcdf`:

```python
ASSET_PRIORITY = ["zarr_ref", "zarr", "netcdf"]

def get_preferred_asset(item: dict) -> str:
    """Get the best available asset for reading."""
    assets = item.get("assets", {})
    
    for asset_name in ASSET_PRIORITY:
        if asset_name in assets:
            return asset_name
    
    raise ValueError("No supported asset found")
```

---

## Pre-Flight Checks

### Verify NetCDF Chunking

Before generating references, check that the source files have reasonable chunking:

```python
import h5py
import fsspec

def check_netcdf_chunking(nc_url: str, storage_options: dict = None) -> dict:
    """
    Check if NetCDF file has sane chunking for virtualization.
    
    Returns dict with chunking info and warnings.
    """
    storage_options = storage_options or {}
    fs = fsspec.filesystem("abfs", **storage_options)
    
    result = {"url": nc_url, "variables": {}, "warnings": []}
    
    with fs.open(nc_url) as f:
        with h5py.File(f, 'r') as h5:
            for var_name in h5.keys():
                var = h5[var_name]
                
                if not hasattr(var, 'shape'):
                    continue
                    
                info = {
                    "shape": var.shape,
                    "dtype": str(var.dtype),
                    "chunks": var.chunks,
                    "compression": var.compression
                }
                result["variables"][var_name] = info
                
                # Check for problems
                if var.chunks is None:
                    result["warnings"].append(
                        f"{var_name}: No chunking (contiguous). "
                        "May be slow for partial reads."
                    )
                
                elif var.chunks and len(var.shape) >= 2:
                    # Check for weird chunking patterns
                    spatial_chunks = var.chunks[-2:]
                    if any(c == 1 for c in spatial_chunks):
                        result["warnings"].append(
                            f"{var_name}: Chunked by single pixels in spatial dims. "
                            "Will be VERY slow. Consider physical conversion."
                        )
                    elif any(c > 1000 for c in spatial_chunks):
                        result["warnings"].append(
                            f"{var_name}: Very large spatial chunks ({spatial_chunks}). "
                            "May cause slow tile generation."
                        )
    
    return result


# Usage
info = check_netcdf_chunking("abfs://raw/climate.nc", STORAGE_OPTIONS)

if info["warnings"]:
    print("⚠️  Warnings:")
    for w in info["warnings"]:
        print(f"   - {w}")
else:
    print("✓ Chunking looks good for virtualization")
```

### Chunking Guidelines

| Chunking Pattern | Virtualization Performance | Recommendation |
|------------------|---------------------------|----------------|
| `(365, 180, 360)` - balanced | ✅ Excellent | Use as-is |
| `(1, 720, 1440)` - by time step | ✅ Good for spatial queries | Use as-is |
| `(3650, 1, 1)` - by pixel | ❌ Terrible | Consider physical conversion |
| `None` (contiguous) | ⚠️ Whole file per read | May need conversion for large files |
| `(10, 10, 10)` - tiny chunks | ⚠️ Many HTTP requests | Acceptable but not optimal |

---

## Pipeline Comparison

### Physical Conversion (Prayer Mode)

```
50 TB NetCDF
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  • Spin up beefy compute ($$$$)                         │
│  • Read entire file into memory                         │
│  • Rechunk (memory explosion risk)                      │
│  • Recompress                                           │
│  • Write to blob storage                                │
│  • Handle network failures                              │
│  • Handle OOM crashes                                   │
│  • Handle Azure throttling                              │
│  • Retry failed files                                   │
│  • Validate output                                      │
│  • Delete and retry corrupted writes                    │
└─────────────────────────────────────────────────────────┘
     │
     ▼
50 TB Zarr (+ 50 TB NetCDF still sitting there)

Time: Days to weeks
Cost: Massive compute + 2x storage
Stress: 📈📈📈📈📈
Failure modes: ∞
```

### Reference Generation (Chill Mode)

```
50 TB NetCDF
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  • Read file headers (~1 MB per file)                   │
│  • Write JSON reference (~1 MB per file)                │
│  • Next file                                            │
└─────────────────────────────────────────────────────────┘
     │
     ▼
~500 MB of JSON references

Time: Hours
Cost: Minimal compute, trivial storage
Stress: 😎
Failure modes: File not found, bad permissions (just retry)
```

### Metrics Comparison

| Metric | Physical Conversion | Reference Generation |
|--------|--------------------|--------------------|
| **50 TB input** | 50 TB output + compute | ~500 MB output |
| **Time per file** | Minutes to hours | Seconds |
| **Memory needed** | 10-100+ GB | ~1 GB |
| **Network transfer** | Read all + write all | Read headers only |
| **Can run in Function** | No | Yes (even Consumption) |
| **Failure recovery** | Complex, partial state | Re-run file (seconds) |
| **Storage cost** | 2x | ~0.001x |

---

## Error Handling

Reference generation is simple, so error handling is simple:

```python
def generate_with_retry(nc_path: str, max_retries: int = 3) -> dict:
    """
    Generate reference with retry logic.
    
    Unlike physical conversion, failures are cheap to retry
    because we're only reading headers.
    """
    for attempt in range(max_retries):
        try:
            ref_path = nc_path.replace(".nc", ".json").replace("/raw/", "/refs/")
            
            vds = open_virtual_dataset(nc_path, storage_options=STORAGE_OPTIONS)
            vds.virtualize.to_kerchunk(ref_path, storage_options=STORAGE_OPTIONS)
            
            return {"status": "success", "input": nc_path, "output": ref_path}
            
        except Exception as e:
            if attempt == max_retries - 1:
                return {"status": "error", "input": nc_path, "error": str(e)}
            
            logging.warning(f"Attempt {attempt + 1} failed for {nc_path}: {e}")
            time.sleep(2 ** attempt)  # Exponential backoff
```

---

## Trade-offs: Virtual vs Physical Zarr

### When Virtual Zarr (Kerchunk) Is Better

✅ Archive data you don't own/control (CMIP6, Copernicus, etc.)
✅ Legacy NetCDF you can't or won't delete
✅ Massive datasets where copying is prohibitive
✅ Quick proof-of-concept before committing to conversion
✅ Data that's already well-chunked
✅ Read-heavy workloads (no writes needed)

### When Physical Zarr Is Better

✅ You own the data and control storage
✅ Source NetCDF has poor chunking
✅ You need optimal chunk sizes for your access patterns
✅ You want better compression (Blosc/Zstd vs old gzip)
✅ Source files might move or disappear
✅ You need maximum read performance

### Hybrid Approach

For critical/frequently-accessed data, do both:

```
Original NetCDF ──► Kerchunk ref (immediate access)
       │
       └──────────► Physical Zarr (optimized, eventual)
```

Use kerchunk immediately, convert to physical Zarr in background for hot data.

---

## Dependencies

### Core Requirements

```txt
# requirements.txt

# Virtual Zarr libraries
virtualizarr>=1.0.0
kerchunk>=0.2.0

# NetCDF/HDF5 support
h5netcdf>=1.3.0
h5py>=3.10.0

# xarray with Zarr
xarray>=2024.1.0
zarr>=2.16.0

# Filesystem abstraction
fsspec>=2024.2.0
aiohttp>=3.9.0

# Azure support
adlfs>=2024.4.1

# Fast JSON
ujson>=5.9.0
```

### For TiTiler Integration

```txt
# Additional for TiTiler
titiler.xarray[full]>=0.18.0
```

---

## Quick Start Checklist

1. **Install dependencies**
   ```bash
   pip install virtualizarr kerchunk h5netcdf adlfs
   ```

2. **Check source file chunking**
   ```python
   info = check_netcdf_chunking("abfs://raw/sample.nc")
   print(info["warnings"])  # Verify no showstoppers
   ```

3. **Generate reference for one file**
   ```python
   vds = open_virtual_dataset("abfs://raw/sample.nc")
   vds.virtualize.to_kerchunk("abfs://refs/sample.json")
   ```

4. **Test reading via reference**
   ```python
   ds = xr.open_dataset("reference://", engine="zarr",
       backend_kwargs={"storage_options": {"fo": "abfs://refs/sample.json", ...}})
   print(ds)  # Should show dataset structure
   ```

5. **Batch process archive**
   ```bash
   python batch_generate_refs.py
   ```

6. **Update TiTiler to handle references**
   - Add `KerchunkAwareReader` or URL routing
   - Test tile generation from reference URLs

7. **Add to STAC catalog**
   - Create items with `zarr_ref` assets
   - Point TiTiler at reference URLs

---

## Summary

Kerchunk and VirtualiZarr let you serve legacy NetCDF as cloud-native Zarr without touching the original data. Instead of expensive physical conversion:

- Generate lightweight JSON reference files (seconds per file)
- Store references alongside original data
- TiTiler-xarray serves tiles transparently
- Original NetCDF files never move or change

**The "pipeline" isn't processing data - it's just writing down where the data already is.**

```
NetCDF stays where it is → Generate tiny reference file → Serve as if it's Zarr
```

No prayers required.