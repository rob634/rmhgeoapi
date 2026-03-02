# SIEGE Report -- Run 7 (Run 23)

**Date**: 02 MAR 2026
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Version**: v0.9.11.7
**Pipeline**: SIEGE (full lifecycle + Provocateur invalid data sweep)
**Scope**: 6 lifecycle sequences + 32 invalid/bad data scenarios
**Schema**: Clean slate (rebuilt + STAC nuked before run)

---

## Endpoint Health

| # | Endpoint | Method | HTTP Code | Latency (s) | Notes |
|---|----------|--------|-----------|-------------|-------|
| 1 | `/api/platform/health` | GET | 200 | 0.84 | Healthy |
| 2 | `/api/platform/status` | GET | 200 | 0.54 | OK |
| 3 | `/api/platform/status/{fake-uuid}` | GET | 404 | 1.31 | Expected |
| 4 | `/api/platform/approve` | GET | 404 | 0.13 | POST-only, expected |
| 5 | `/api/platform/reject` | GET | 404 | 0.12 | POST-only, expected |
| 6 | `/api/platform/unpublish` | GET | 404 | 0.14 | POST-only, expected |
| 7 | `/api/platform/resubmit` | GET | 404 | 0.12 | POST-only, expected |
| 8 | `/api/platform/validate` | GET | 404 | 0.12 | POST-only, expected |
| 9 | `/api/platform/submit` | GET | 404 | 0.12 | POST-only, expected |
| 10 | `/api/platform/approvals` | GET | 200 | 0.74 | OK |
| 11 | `/api/platform/catalog/lookup` | GET | 400 | 0.12 | Expected (missing params) |
| 12 | `/api/platform/failures` | GET | 200 | 0.63 | OK |
| 13 | `/api/platform/lineage/{fake-uuid}` | GET | 404 | 0.43 | Expected |
| 14 | `/api/platforms` | GET | 200 | 0.44 | OK |
| 15 | `/api/health` | GET | 200 | 3.45 | Healthy (slow — comprehensive check) |
| 16 | `/api/dbadmin/stats` | GET | 404 | 0.16 | **SG-9 still open** |
| 17 | `/api/dbadmin/jobs?limit=1` | GET | 200 | 0.39 | OK |

**Assessment**: HEALTHY (17/17 expected, 1 known bug SG-9)

---

## Workflow Results

| Sequence | Description | Steps | Pass | Fail | Unexpected |
|----------|-------------|-------|------|------|------------|
| 1 | Raster Lifecycle | 4 | 4 | 0 | 0 |
| 2 | Vector Lifecycle | 4 | 4 | 0 | 0 |
| 3 | Multi-Version | 7 | 7 | 0 | 0 |
| 4 | Unpublish | 6 | 6 | 0 | 0 |
| 5 | NetCDF/VirtualiZarr | 4 | 4 | 0 | 0 |
| 6 | Additional Formats (CSV/SHP/KML) | 3 | 3 | 0 | 0 |
| **TOTAL** | | **28** | **28** | **0** | **0** |

### Sequence Details

**Seq 1: Raster Lifecycle** — PASS
- Submit→process→approve→catalog lookup all clean
- Processing completed in ~30s, STAC materialized correctly

**Seq 2: Vector Lifecycle** — PASS
- GeoPackage with nested path processed correctly
- STAC null on approval (correct — vector does not go to STAC by design)
- PostGIS table created, OGC Features endpoints present

**Seq 3: Multi-Version** — PASS
- v1 submitted, processed, approved
- Resubmit on approved release correctly blocked ("Revoke first")
- Fresh submit to same dataset_id created version_ordinal=2

**Seq 4: Unpublish** — PASS
- Unpublish correctly revokes approval, removes STAC item from pgSTAC
- Catalog still shows asset with `revoked` state
- Requires data_type + STAC identifiers (SG2-1 MEDIUM ergonomics issue)

**Seq 5: NetCDF/VirtualiZarr** — **PASS** ← Previously blocked by SG6-L1
- All 5 stages completed: scan → copy → validate → combine → register
- STAC materialized on approval, catalog lookup confirmed
- First clean end-to-end NetCDF pipeline run

**Seq 6: Additional Formats** — PASS
- CSV with lat/lon processing options → completed
- Zipped shapefile → completed
- KML → completed
- All three created PostGIS tables in geo schema

---

## Invalid Data Sweep (Provocateur — 32 tests)

### Summary

| Category | Count | Details |
|----------|-------|---------|
| **Rejected at submit (4xx)** | 11 | Tests 1-10, 15 |
| **Accepted then failed in pipeline** | 17 | Tests 13-14, 16-18, 20, 22-23, 25-32 |
| **500 errors** | **0** | Zero server errors |
| **Unexpected successes** | 2 | Tests 11, 12 (known: SG6-P1, SG6-P2) |
| **Arguably correct** | 2 | Tests 19 (null_geom), 21 (mixed_geom auto-split) |
| **Inconclusive** | 1 | Test 24 (huge polygon still processing) |

### Full Results

| # | Test Name | HTTP | Final Status | Verdict |
|---|-----------|------|-------------|---------|
| 1 | nonexistent_file | 400 | rejected | PASS |
| 2 | nonexistent_container | 400 | rejected | PASS |
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
| 14 | raster_empty | 202 | failed | PASS |
| 15 | raster_wrong_ext | 400 | rejected | PASS |
| 16 | raster_garbage | 202 | failed | PASS |
| 17 | raster_corrupt_header | 202 | failed | PASS |
| 18 | vector_truncated_json | 202 | failed | PASS |
| 19 | vector_null_geometries | 202 | **completed** | PASS* |
| 20 | vector_empty_collection | 202 | failed | PASS |
| 21 | vector_mixed_geometry | 202 | completed | PASS* (auto-split) |
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

- **Test 4 (SQL injection)**: `"dataset_id contains invalid characters: {' ', \"'\", ';'}"` — character whitelist
- **Test 25 (two shapefiles)**: `"Shapefile ZIP contains 2 .shp files: ['roads_lines.shp', 'road_points.shp']. Specify which shapefile to use via processing_options.shp_name"` — actionable
- **Test 29 (wrong CSV cols)**: `"lat_name='latitude' not found in CSV. Available columns: ['id', 'x_coord', 'y_coord', 'name', 'value']"` — lists alternatives
- **Test 30 (bad coords)**: `"Longitude values out of range: min=-999.0, max=999.0. Valid range: -180 to 180"` — shows actual vs expected

---

## Findings

### New in This Run

| ID | Severity | Category | Description |
|----|----------|----------|-------------|
| (none) | — | — | **No new bugs found.** SG6-L1 (NetCDF pipeline) is now fixed. |

### Previously Known (Status Check)

| ID | Status | Note |
|----|--------|------|
| SG6-L1 HIGH | **FIXED** | NetCDF pipeline now completes all 5 stages end-to-end |
| SG-9 LOW | CONFIRMED | /api/dbadmin/stats returns 404 |
| SG6-P1 MEDIUM | CONFIRMED | Raster without CRS silently processed |
| SG6-P2 MEDIUM | CONFIRMED | Raster without geotransform silently processed |
| SG2-1 MEDIUM | CONFIRMED | Unpublish requires STAC IDs + data_type, not just release_id |
| SG5-1/SG6-L2 CRITICAL | NOT TESTED | Approval of failed releases (not in scope this run) |

---

## Verdict: PASS

**All 6 lifecycle sequences PASSED** — including the NetCDF/VirtualiZarr pipeline which was blocked in Run 22.

### Scoring

| Area | Score | Notes |
|------|-------|-------|
| Endpoint health | 16/17 | SG-9 dbadmin/stats still 404 |
| Raster lifecycle | 4/4 | Clean |
| Vector lifecycle | 4/4 | Clean |
| Multi-version | 7/7 | Clean (resubmit blocked on approved = correct) |
| Unpublish | 6/6 | Clean |
| NetCDF/VirtualiZarr | **4/4** | **FIXED — first clean run** |
| Additional formats (CSV/SHP/KML) | 3/3 | Clean |
| Input validation (submit) | 11/11 | All injection/payload attacks caught |
| Pipeline error handling | 17/17 | All corrupt files caught with clear messages |
| Corrupt data rejection | 12/15 | 2 unexpected accepts (no CRS, no geo), 1 inconclusive |

**Overall**: 84/88 (95.5%) — up from 88.75% in Run 22, 54.5% in Run 1

---

## Token Usage

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Cartographer | Endpoint probing | ~30,000 | ~57s |
| Lancer | Lifecycle execution | ~64,000 | ~8m |
| Provocateur | Invalid data sweep | ~59,000 | ~9.5m |
| **Total** | | **~153,000** | **~18m** |

---

## Delta from Run 22

| Change | Run 22 (v0.9.11.5/6) | Run 23 (v0.9.11.7) |
|--------|----------------------|---------------------|
| NetCDF pipeline | FAIL (SG6-L1) | **PASS** |
| Lifecycle sequences | 16/19 | **28/28** |
| Score | 71/80 (88.75%) | **84/88 (95.5%)** |
| Additional formats tested | 0 | 3 (CSV, SHP, KML) |
| New bugs found | 3 (SG6-L1/L2/L3) | **0** |
