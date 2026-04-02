# COMPETE: Zarr & NetCDF Ingest Pipeline

**Purpose**: Adversarial review of the unified zarr/netcdf ingest pipeline after removing pyramid generation and switching to flat Zarr v3 output. Verify the entire chain from platform submit through download, validate, convert/rechunk, register, and STAC materialization produces correct, serveable output that titiler-xarray can read.

**Best for**: Run after major pipeline restructuring (pyramid removal, 02 APR 2026). Targets the full handler chain for both NetCDF-to-Zarr conversion (PATH A) and native Zarr rechunking (PATH B).

**Motivation**: The pyramid step was removed because titiler-xarray cannot read multiscale DataTree stores. The pipeline now writes flat Zarr with optimized chunking. This review verifies that no pyramid assumptions leaked into other handlers, that the register handler reads flat stores correctly, that STAC metadata is correct, and that the unpublish path still works for the new output format.

---

## Scope Split: Split C — Data vs Control Flow

**Why this split**: This is an ETL/data processing pipeline with two paths (NetCDF conversion vs Zarr rechunking) that converge at registration. Alpha inspects the **data transformations** (chunking, encoding, coordinate handling, metadata fidelity). Beta inspects the **job lifecycle** (task ordering, error recovery, resource cleanup, state transitions, concurrency). The pyramid removal may have left orphan references or broken assumptions that only surface under failure conditions.

### Alpha — Data Validation, Transformation, Consistency

Review how data is transformed at each step. The question is: **does the output accurately represent the input, with the correct structure for downstream consumers (titiler-xarray, STAC catalog)?**

Checklist:
- Is the chunking strategy correct? time=1, spatial=256x256 for all variables?
- Does the encoding dict handle all variable types (data vars, coords, bounds)?
- Are coordinate variables preserved correctly through conversion (lat, lon, time, CRS)?
- Is the CRS written correctly via `.rio.write_crs("EPSG:4326")`? What if input is already EPSG:4326?
- Are dimension renames (lat/lon -> y/x) applied consistently?
- Is the spatial extent extracted correctly from coordinates (not hardcoded fallback)?
- Does the STAC item JSON contain correct bbox, temporal extent, variable list?
- Is the zarr_metadata table populated with correct store_url, variables, dimensions?
- Are any `_pyramid.zarr` references remaining in handlers, translation, or status endpoints?
- Does the register handler's fallback `group="0"` path still make sense for flat stores?
- Is the `stac_item_json` builder receiving correct params (no pyramid-specific fields)?
- Does the platform/status response build correct xarray URLs (no `_pyramid.zarr` in path)?

**Alpha does NOT review**: Task scheduling, retry logic, error propagation to platform status, mount cleanup, concurrency safety.

### Beta — Job Lifecycle, Ordering, Recovery, Monitoring

Review how the pipeline manages execution state. The question is: **if any step fails, hangs, or runs twice, does the system recover correctly and leave no orphaned state?**

Checklist:
- What happens if download fails mid-stream? Is mount cleaned up?
- What happens if rechunk fails partway through blob writes? Orphan blobs in silver-zarr?
- What happens if the NetCDF convert handler fails after writing partial zarr output?
- Is pre-cleanup (delete_blobs_by_prefix) called before every write to prevent stale data?
- What happens if the register handler can't open the zarr store? Does it distinguish "store doesn't exist" from "store is corrupt"?
- Is `dry_run=true` respected by ALL handlers in the chain?
- What happens if STAC materialization fails? Is the zarr_metadata row orphaned?
- Does the unpublish workflow (`unpublish_zarr`) correctly handle the new `.zarr` suffix (not `_pyramid.zarr`)?
- Are timeouts appropriate for each handler? (Large NetCDF conversion can take minutes.)
- Is the conditional routing (detect_type) correct? What if validate returns unexpected input_type?
- What happens if rechunk decides to skip (chunks already optimal) — does register find the right store URL?
- Are there race conditions if two runs target the same target_prefix?

**Beta does NOT review**: Data fidelity, chunking strategy, coordinate handling, STAC metadata correctness.

### Gamma — Gaps Between Data and Lifecycle

After reading Alpha and Beta reports, find:
- **Orphan pyramid references**: Any `_pyramid.zarr`, `pyramid_levels`, `resampling`, `DataTree`, `pyramid_coarsen`, `ndpyramid` remaining in the target files
- **Path divergence**: Cases where PATH A (NetCDF) and PATH B (Zarr) produce different output structure or metadata
- **URL construction gaps**: The platform status endpoint, register handler, and platform translation must all agree on the store URL pattern (`{prefix}.zarr`)
- **Rechunk skip path**: When rechunk returns the original Bronze URL (chunks already optimal), does register write the correct silver store_url or does it point to Bronze?
- **Missing error paths**: Handlers that catch exceptions but return `{"success": True}` or log-and-continue when they should fail
- **Stale STAC metadata**: If a re-run of the pipeline writes new zarr output but the STAC item still references the old `_pyramid.zarr` path

---

## Target Files

### Primary (Alpha + Beta review all)

| # | File | Lines | Role |
|---|------|-------|------|
| 1 | `workflows/ingest_zarr.yaml` | 113 | DAG workflow definition (v4, post-pyramid removal) |
| 2 | `services/zarr/handler_download_to_mount.py` | 244 | Source acquisition — NetCDF to mount, Zarr passthrough |
| 3 | `services/zarr/handler_validate_source.py` | 275 | Type detection (NC vs Zarr), dimension/chunk extraction |
| 4 | `services/handler_ingest_zarr.py` | 975 | Rechunk handler (PATH B) — optimal chunk detection, skip logic |
| 5 | `services/handler_netcdf_to_zarr.py` | 1358 | NetCDF convert handler (PATH A) — flat zarr write, encoding |
| 6 | `services/zarr/handler_register.py` | 285 | Metadata registration — opens zarr, extracts metadata, writes DB |

### Secondary (Gamma + Delta review)

| # | File | Lines | Role |
|---|------|-------|------|
| 7 | `services/stac/handler_materialize_item.py` | 155 | STAC item materialization (reads zarr_metadata, writes pgSTAC) |
| 8 | `services/stac/handler_materialize_collection.py` | 114 | Collection extent + pgSTAC search registration |
| 9 | `services/stac_materialization.py` | 1060 | Core STAC engine (B2C sanitization, extent calc) |
| 10 | `infrastructure/zarr_metadata_repository.py` | 159 | zarr_metadata table CRUD |
| 11 | `services/platform_translation.py` | 896 | Parameter reshaping (submit -> DAG params) |
| 12 | `services/zarr/handler_generate_pyramid.py` | 290 | DEAD CODE — verify no imports remain from live handlers |

**Total**: ~5,924 lines across 12 files.

---

## Severity Classification

| Severity | Definition for this target |
|----------|---------------------------|
| **CRITICAL** | Output zarr unreadable by titiler-xarray. Pyramid reference survives in live code path. Data corruption (wrong CRS, missing variables, incorrect bbox). |
| **HIGH** | Handler fails silently (returns success with incomplete output). Unpublish path broken for new format. Rechunk skip path writes wrong store_url. |
| **MEDIUM** | Pre-cleanup missing (stale blobs survive re-run). Error message unhelpful. Dry-run not respected. Missing NULL/empty checks on optional metadata. |
| **LOW** | Stale comments referencing pyramids. Unnecessary imports. Logging inconsistency. |

---

## Output Format (Delta)

Delta produces a single report with:

1. **Executive Summary** — 2-3 sentences: is the pipeline safe to deploy post-pyramid removal?
2. **Top 5 Fixes** — Table with: Severity, Finding ID, WHY (what can go wrong), WHERE (file:line), HOW (specific fix), EFFORT (S/M/L), RISK OF FIX (low/med/high)
3. **Full Finding List** — All findings with severity, confidence (CONFIRMED/PROBABLE/SPECULATIVE), description, file:line (CONFIRMED only)
4. **Pyramid Orphan Audit** — Explicit list of any surviving `_pyramid.zarr`, `pyramid_levels`, `pyramid_coarsen`, `ndpyramid`, `DataTree` references in target files
5. **Path Parity Check** — Do PATH A (NetCDF) and PATH B (Zarr) produce identical output structure at register?
6. **Accepted Risks** — Findings that are known limitations, not bugs (with reasoning)
