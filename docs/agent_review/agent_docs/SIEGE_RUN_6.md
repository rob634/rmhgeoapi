# SIEGE Report -- Run 6 (Run 22)

**Date**: 02 MAR 2026
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Version**: Orchestrator v0.9.11.5 / Docker Worker v0.9.11.6
**Pipeline**: SIEGE (expanded with Provocateur invalid data sweep)
**Scope**: 5 lifecycle sequences + 32 invalid/bad data scenarios

---

## Endpoint Health

| # | Endpoint | Method | HTTP Code | Latency (s) | Notes |
|---|----------|--------|-----------|-------------|-------|
| 1 | `/api/platform/health` | GET | 200 | 0.93 | Healthy |
| 2 | `/api/platform/status` | GET | 200 | 0.61 | OK |
| 3 | `/api/platform/status/{fake-uuid}` | GET | 404 | 1.04 | Expected |
| 4 | `/api/platform/approve` | GET | 404 | 0.19 | POST-only, expected |
| 5 | `/api/platform/reject` | GET | 404 | 0.16 | POST-only, expected |
| 6 | `/api/platform/unpublish` | GET | 404 | 0.17 | POST-only, expected |
| 7 | `/api/platform/resubmit` | GET | 404 | 0.19 | POST-only, expected |
| 8 | `/api/platform/validate` | GET | 404 | 0.11 | POST-only, expected |
| 9 | `/api/platform/submit` | GET | 404 | 0.11 | POST-only, expected |
| 10 | `/api/platform/approvals` | GET | 200 | 0.65 | OK |
| 11 | `/api/platform/catalog/lookup` | GET | 400 | 0.13 | Expected (missing params) |
| 12 | `/api/platform/failures` | GET | 200 | 0.68 | OK |
| 13 | `/api/platform/lineage/{fake-uuid}` | GET | 404 | 0.48 | Expected |
| 14 | `/api/platforms` | GET | 200 | 0.50 | OK |
| 15 | `/api/health` | GET | 200 | 3.59 | Healthy (slow -- comprehensive check) |
| 16 | `/api/dbadmin/stats` | GET | 404 | 0.14 | **SG-9 still open** |
| 17 | `/api/dbadmin/jobs?limit=1` | GET | 200 | 0.37 | OK |

**Assessment**: HEALTHY (17/17 expected, 1 known bug SG-9)

---

## Workflow Results

| Sequence | Description | Steps | Pass | Fail | Unexpected |
|----------|-------------|-------|------|------|------------|
| 1 | Raster Lifecycle | 4 | 4 | 0 | 0 |
| 2 | Vector Lifecycle | 4 | 4 | 0 | 0 |
| 3 | Multi-Version | 4 | 4 | 0 | 0 |
| 4 | Unpublish | 3 | 3 | 0 | 0 |
| 5 | NetCDF/VirtualiZarr | 4 | 1 | 2 | 1 |
| **TOTAL** | | **19** | **16** | **2** | **1** |

### Sequence Details

**Seq 1-4: Raster, Vector, Multi-Version, Unpublish** -- ALL PASS
- Raster processed in ~16s, vector completed before first poll
- Multi-version resubmit correctly creates ordinal=2
- Approval materializes STAC (raster) / skips STAC (vector) correctly
- Unpublish revokes v2, restores v1 as is_latest, deletes blob
- All prior regressions (SG-1 through SG2-3) remain fixed

**Seq 5: NetCDF/VirtualiZarr** -- FAIL (2 failures, 1 unexpected)
- Submit with `data_type: "zarr"` accepted (HTTP 202)
- Pipeline fails at Stage 3 (validate): `ScipyBackendEntrypoint.open_dataset() got an unexpected keyword argument 'storage_options'`
- Despite `processing_status=failed`, approval succeeded (BUG -- no guard)
- Catalog shows approved item with no data

---

## Invalid Data Sweep (Provocateur -- 32 tests)

### Summary

| Category | Count | Details |
|----------|-------|---------|
| **Rejected at submit (4xx)** | 12 | Tests 1-10, 15 |
| **Accepted then failed in pipeline** | 15 | Tests 13-14, 16-18, 20, 22-23, 25-32 |
| **500 errors** | **0** | Zero server errors |
| **Unexpected successes** | 3 | Tests 11, 12, 19 |
| **Inconclusive** | 1 | Test 24 (huge polygon still processing) |

### Full Results

| # | Test Name | HTTP | Final Status | Verdict |
|---|-----------|------|-------------|---------|
| 1 | nonexistent_file | 409 | rejected | PASS |
| 2 | nonexistent_container | 409 | rejected | PASS |
| 3 | path_traversal | 400 | rejected | PASS |
| 4 | sql_injection_dataset | 400 | rejected | PASS |
| 5 | unicode_resource | 400 | rejected | PASS |
| 6 | extremely_long_dataset | 400 | rejected | PASS |
| 7 | special_chars_dataset | 400 | rejected | PASS |
| 8 | empty_filename | 400 | rejected | PASS |
| 9 | null_values | 400 | rejected | PASS |
| 10 | wrong_extension_exe | 400 | rejected | PASS |
| 11 | raster_no_crs | 202 | **completed** | **UNEXPECTED** |
| 12 | raster_no_geo | 202 | **completed** | **UNEXPECTED** |
| 13 | raster_truncated | 202 | failed | PASS |
| 14 | raster_empty | 202 | failed | PASS (misleading msg) |
| 15 | raster_wrong_ext | 400 | rejected | PASS |
| 16 | raster_garbage | 202 | failed | PASS (misleading msg) |
| 17 | raster_corrupt_header | 202 | failed | PASS |
| 18 | vector_truncated_json | 202 | failed | PASS |
| 19 | vector_null_geometries | 202 | **completed** | **UNEXPECTED** |
| 20 | vector_empty_collection | 202 | failed | PASS |
| 21 | vector_mixed_geometry | 202 | completed | PASS (auto-split) |
| 22 | vector_html_disguised | 202 | failed | PASS |
| 23 | vector_empty_file | 202 | failed | PASS |
| 24 | vector_huge_polygon | 202 | still processing | INCONCLUSIVE |
| 25 | shapefile_two_layers | 202 | failed | PASS |
| 26 | shapefile_incomplete | 202 | failed | PASS |
| 27 | shapefile_nested_zip | 202 | failed | PASS |
| 28 | gpkg_empty_table | 202 | failed | PASS |
| 29 | csv_wrong_columns | 202 | failed | PASS |
| 30 | csv_invalid_coords | 202 | failed | PASS |
| 31 | csv_header_only | 202 | failed | PASS |
| 32 | kml_empty | 202 | failed | PASS |

### Notable Error Messages (Best-in-Class)

- **Test 4 (SQL injection)**: `"dataset_id contains invalid characters: {' ', \"'\", ';'}"` -- character whitelist
- **Test 25 (two shapefiles)**: `"Shapefile ZIP contains 2 .shp files: ['roads_lines.shp', 'road_points.shp']. Specify which shapefile to use via processing_options.shp_name"` -- actionable
- **Test 29 (wrong CSV cols)**: `"lat_name='latitude' not found in CSV. Available columns: ['id', 'x_coord', 'y_coord', 'name', 'value']"` -- lists alternatives
- **Test 30 (bad coords)**: `"Longitude values out of range: min=-999.0, max=999.0. Valid range: -180 to 180"` -- shows actual vs expected

---

## Findings

### From Lifecycle Sequences

| ID | Severity | Category | Description |
|----|----------|----------|-------------|
| **SG6-L1** | **HIGH** | PIPELINE | VirtualiZarr validate fails: `ScipyBackendEntrypoint.open_dataset() got an unexpected keyword argument 'storage_options'`. The `scipy` xarray engine does not support remote storage_options -- must use `h5netcdf` or `netcdf4` engine, or download file locally first. |
| **SG6-L2** | **HIGH** | LIFECYCLE | Approval endpoint has no guard against `processing_status=failed`. Failed releases can be approved, creating phantom catalog entries with no data. Reconfirms SG5-1 from Run 21. |
| **SG6-L3** | MEDIUM | SUBMIT | Zarr submit with `file_name` instead of `source_url` creates orphaned release before failing. Error message unhelpful -- should say "use source_url for zarr data type". |

### From Invalid Data Sweep

| ID | Severity | Category | Description |
|----|----------|----------|-------------|
| **SG6-P1** | MEDIUM | VALIDATION | Raster without CRS silently processed into COG. Creates spatially ambiguous data. Pipeline should reject or warn. |
| **SG6-P2** | MEDIUM | VALIDATION | Raster without geotransform silently processed. STAC bbox/geometry meaningless. |
| **SG6-P3** | LOW | ERROR_MSG | Empty/garbage raster files produce misleading "transient network issue" error. Actual cause is corrupt/empty file. |
| **SG6-P4** | LOW | VALIDATION | Vector with null geometries silently accepted into PostGIS. Should emit warning about null geometry count. |
| **SG6-P5** | INFO | TIMEOUT | Huge polygon (100K vertices) still processing after 4+ minutes with no timeout guard. |
| **SG6-P6** | INFO | HTTP | File/container not found returns 409 instead of 404. Semantically inaccurate but functional. |

### Previously Known (Confirmed Still Present)

| ID | Status | Note |
|----|--------|------|
| SG-6 (raster) | CONFIRMED | Cached stac_item_id uses -ord1, live pgSTAC uses -v1 |
| SG-9 | CONFIRMED | /api/dbadmin/stats returns 404 |
| SG5-1 | RECONFIRMED as SG6-L2 | Failed release can be approved |

---

## Root Cause Analysis: SG6-L1

The `virtualzarr_validate` handler at `services/handler_virtualzarr.py:432` uses:

```python
xr.open_dataset(
    f"az://{blob_path}",
    engine="scipy",
    storage_options=storage_options,
)
```

**Problem**: The `scipy` xarray backend (`ScipyBackendEntrypoint`) does not accept `storage_options`. This parameter is only supported by backends that integrate with fsspec (e.g., `h5netcdf`, `netcdf4`, `zarr`). The scipy backend expects a local file path or file-like object.

**Fix options**:
1. **Use `h5netcdf` engine** -- supports `storage_options` natively via fsspec, handles both NetCDF3 and NetCDF4. Requires adding `h5netcdf` to requirements-docker.txt.
2. **Use `netcdf4` engine** -- also supports `storage_options` but only handles NetCDF4/HDF5 (not NetCDF3 classic).
3. **Download first, open locally** -- use fsspec to download to temp file, then open with `engine="scipy"`.

**Recommended**: Option 1 (`h5netcdf`) -- broadest format support, minimal code change.

---

## Verdict: CONDITIONAL PASS

**Sequences 1-4**: PASS (100% -- raster, vector, multi-version, unpublish all clean)
**Sequence 5**: FAIL (NetCDF pipeline blocked by scipy backend incompatibility)
**Invalid data sweep**: STRONG PASS (0 server errors, 26/32 graceful, 3 unexpected accepts)

### Scoring

| Area | Score | Notes |
|------|-------|-------|
| Endpoint health | 16/17 | SG-9 dbadmin/stats still 404 |
| Raster lifecycle | 4/4 | Clean |
| Vector lifecycle | 4/4 | Clean |
| Multi-version | 4/4 | Clean |
| Unpublish | 3/3 | Clean |
| NetCDF/VirtualiZarr | 1/4 | **Blocked by SG6-L1** |
| Input validation (submit) | 12/12 | All injection/payload attacks caught |
| Pipeline error handling | 15/17 | 2 misleading messages, but no crashes |
| Corrupt data rejection | 12/15 | 3 unexpected accepts (no CRS, no geo, null geom) |

**Overall**: 71/80 (88.75%) -- up from 54.5% in Run 1

---

## Token Usage

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Sentinel | Campaign brief | -- | inline |
| Cartographer | Endpoint probing | 26,352 | 58s |
| Lancer | Lifecycle execution | 67,021 | 11m 22s |
| Provocateur | Invalid data sweep | 55,214 | 10m 45s |
| **Total** | | **~148,587** | **~23m 05s** |

---

## Next Steps (Priority Order)

1. **FIX SG6-L1**: Replace `engine="scipy"` with `engine="h5netcdf"` in validate handler. Add `h5netcdf` to requirements-docker.txt. This is the only blocker for NetCDF pipeline.
2. **FIX SG6-L2/SG5-1**: Add `processing_status == 'completed'` guard in approval endpoint. This is a recurring finding across 3 SIEGE runs.
3. **Redeploy Docker** and re-run Sequence 5 only.
4. Consider SG6-P1/P2 (raster georeferencing validation) for a future iteration.
