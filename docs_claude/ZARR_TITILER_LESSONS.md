# Zarr + TiTiler-xarray Integration: Lessons Learned

**Date**: 21 DEC 2025
**Context**: Integrating ERA5 global climate data (~27GB) with TiTiler-xarray

---

## Executive Summary

Successfully deployed ERA5 global climate reanalysis data (9 variables, 744 hourly timesteps, 0.25° resolution) to Azure Blob Storage and integrated with TiTiler-xarray for tile serving. Encountered several compatibility issues between zarr-python versions, TiTiler-xarray, and Azure storage configurations.

---

## Issues Encountered & Solutions

### 1. Zarr 3.x API Breaking Changes

**Problem**: `zarr.storage.FSStore` was removed in zarr 3.x, breaking the original copy script.

**Error**:
```
AttributeError: module 'zarr.storage' has no attribute 'FSStore'
```

**Solution**: Use xarray's `storage_options` parameter instead of creating a FSStore:
```python
# OLD (zarr 2.x)
fs = adlfs.AzureBlobFileSystem(account_name=..., credential=...)
store = zarr.storage.FSStore(path, fs=fs)
ds.to_zarr(store)

# NEW (zarr 3.x)
storage_opts = {'account_name': ..., 'account_key': ...}
ds.to_zarr("abfs://container/path", storage_options=storage_opts)
```

---

### 2. Zarr Chunk Alignment Errors

**Problem**: Source ERA5 data has irregular chunk encoding that doesn't align with target chunks.

**Error**:
```
ValueError: Specified Zarr chunks encoding['chunks']=(372, 150, 150) would overlap multiple Dask chunks
```

**Solution**: Explicitly set encoding chunks as tuples matching dimension order:
```python
encoding = {}
for var in combined.data_vars:
    var_dims = combined[var].dims
    var_chunks = tuple(actual_chunks.get(dim, combined.dims[dim]) for dim in var_dims)
    encoding[var] = {'chunks': var_chunks}

combined.to_zarr(url, encoding=encoding, zarr_format=2)
```

---

### 3. Blosc Codec Compatibility (zarr 2 vs 3)

**Problem**: zarr 3.x changed codec handling, causing errors with numcodecs.Blosc.

**Error**:
```
TypeError: Expected a BytesBytesCodec. Got <class 'numcodecs.blosc.Blosc'> instead.
```

**Solution**: Use `zarr_format=2` when writing to maintain compatibility:
```python
combined.to_zarr(url, zarr_format=2, consolidated=True)
```

---

### 4. Azure RBAC vs Storage Account Keys

**Problem**: Azure CLI identity doesn't have Storage Blob Data Contributor role.

**Error**:
```
azure.core.exceptions.HttpResponseError: AuthorizationPermissionMismatch
```

**Solution**: Use storage account key instead of identity-based auth for local development:
```python
import subprocess
result = subprocess.run(
    ['az', 'storage', 'account', 'keys', 'list',
     '--account-name', storage_account,
     '--resource-group', 'rmhazure_rg',
     '--query', '[0].value', '-o', 'tsv'],
    capture_output=True, text=True, check=True
)
account_key = result.stdout.strip()
storage_opts = {'account_name': storage_account, 'account_key': account_key}
```

---

### 5. Planetary Computer STAC Authentication

**Problem**: ERA5 data on Planetary Computer requires signed URLs with SAS tokens.

**Solution**: Extract `xarray:open_kwargs` from STAC asset metadata:
```python
asset = item.assets[variable_name]
open_kwargs = asset.extra_fields.get('xarray:open_kwargs', {})
storage_options = open_kwargs.get('storage_options', {})

# Filter out 'engine' which is only for open_dataset, not open_zarr
valid_kwargs = {k: v for k, v in open_kwargs.items()
               if k not in ('storage_options', 'engine')}

ds = xr.open_zarr(asset.href, storage_options=storage_options, **valid_kwargs)
```

---

### 6. TiTiler Consolidated Metadata Issues

**Problem**: TiTiler-xarray couldn't read ERA5 variables despite valid .zmetadata.

**Symptom**:
```json
{"detail":"\"No variable named 'air_temperature_at_2_metres'. Variables on the dataset include []\""}
```

**Root Cause**: Incomplete .zmetadata file - the initial xarray `to_zarr(consolidated=True)` didn't properly consolidate all metadata.

**Temporary Workaround** (before fix):
```
&reader_options={%22consolidated%22:false}
```
Note: Braces must NOT be URL-encoded, only quotes.

**Permanent Solution**: Re-run metadata consolidation:
```python
ds = xr.open_zarr(url, storage_options=storage_opts, consolidated=False)
ds.to_zarr(url, storage_options=storage_opts, mode='a', consolidated=True, zarr_format=2)
```

Or manually rebuild .zmetadata by collecting all .zarray and .zattrs files.

---

### 7. Azure Storage Public Access

**Problem**: TiTiler couldn't access blobs - storage container was private.

**Error**: HTTP 404 or 409 when accessing blobs via HTTPS.

**Solution**: Enable public blob access:
```bash
# Enable at account level first
az storage account update --name $ACCOUNT --allow-blob-public-access true

# Then set container level
az storage container set-permission --name silver-cogs --account-name $ACCOUNT --public-access blob
```

---

### 8. HNS vs Non-HNS Storage Accounts

**Investigation**: Tested whether Hierarchical Namespace (HNS) affects zarr compatibility.

**Finding**: Both HNS-enabled (`rmhazuregeo`) and non-HNS (`rmhstorage123`) storage accounts work correctly once:
1. Public access is enabled
2. Metadata is properly consolidated

**No difference** in TiTiler compatibility between HNS and non-HNS for zarr data.

---

## Critical TiTiler-xarray Parameters

| Parameter | Purpose | Required |
|-----------|---------|----------|
| `url` | Zarr store URL | Yes |
| `variable` | Data variable name | Yes (for /info, /tiles, /point) |
| `decode_times=false` | Handle non-standard calendars (noleap, proleptic_gregorian) | Yes |
| `bidx=N` | Band index (1-based) for temporal data | Yes |
| `colormap_name` | Color palette | Optional |
| `rescale=min,max` | Value range for colormap | Recommended |

---

## Working URL Patterns

### Variables List
```
/xarray/variables?url={zarr_url}&decode_times=false
```

### Dataset Info
```
/xarray/info?url={zarr_url}&variable={var}&decode_times=false
```

### Tiles
```
/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={zarr_url}&variable={var}&decode_times=false&bidx=1&colormap_name=viridis&rescale=250,320
```

### Point Query
```
/xarray/point/{lon},{lat}?url={zarr_url}&variable={var}&decode_times=false&bidx=1
```

### Interactive Map
```
/xarray/WebMercatorQuad/map.html?url={zarr_url}&variable={var}&decode_times=false&bidx=1&colormap_name=viridis&rescale=250,320
```

---

## Data Copy Script Template

See `scripts/copy_era5_subset.py` for a working example that handles:
- Planetary Computer STAC authentication
- Azure storage account key retrieval
- Proper chunk encoding
- zarr v2 format compatibility
- Metadata consolidation

---

## Compression Considerations

| Compressor | TiTiler Compatibility | File Size |
|------------|----------------------|-----------|
| None | Best | Largest |
| Blosc (lz4) | Works with proper .zmetadata | ~4x smaller |
| zlib | Works | ~3x smaller |

ERA5 with Blosc: 7.62 GB (compressed from ~27 GB source)

---

## Checklist for New Zarr Datasets

1. [ ] Write with `zarr_format=2` for compatibility
2. [ ] Use `consolidated=True` and verify .zmetadata is complete
3. [ ] Enable public blob access on container
4. [ ] Test `/xarray/variables` endpoint first
5. [ ] Use `decode_times=false` for climate data
6. [ ] Use `bidx=1` for first timestep
7. [ ] Set appropriate `rescale` range for your data

---

## References

- TiTiler-xarray: https://developmentseed.org/titiler-xarray/
- Zarr-Python: https://zarr.readthedocs.io/
- Azure Blob Storage: https://docs.microsoft.com/azure/storage/blobs/
- Planetary Computer: https://planetarycomputer.microsoft.com/
