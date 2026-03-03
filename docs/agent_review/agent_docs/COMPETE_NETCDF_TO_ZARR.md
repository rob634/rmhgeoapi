# COMPETE Review: NetCDF-to-Zarr Pipeline

**Run**: 30 | **Date**: 03 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Scope**: `netcdf_to_zarr` 5-stage pipeline + platform routing + unpublish integration
**Split**: C (Data vs Control Flow) — data integrity in tension with orchestration

---

## EXECUTIVE SUMMARY

The NetCDF-to-Zarr pipeline is a functional implementation that correctly follows the project's established Job-Stage-Task architecture and mirrors the proven VirtualiZarr pipeline structure. However, two structural defects will cause outright failures in production: unpublish is completely broken for both native Zarr pipelines (the handler hardcodes a lookup for a `"reference"` STAC asset key that these pipelines never produce), and versioned submissions silently strip the `zarr/` prefix from the output folder, placing Zarr stores in the raster output namespace. The resource leak in the convert handler and the register handler's silent acceptance of DB write failures are high-severity issues that will cause operational pain at scale. Overall, the pipeline is approximately 85% production-ready; the top 5 fixes below would bring it to parity with the raster and VirtualiZarr pipelines.

---

## TOP 5 FIXES

### Fix 1: Unpublish broken for native Zarr pipelines

- **WHAT**: `inventory_zarr_item` looks up the STAC asset key `"reference"` to find blobs to delete; `netcdf_to_zarr` and `ingest_zarr` both produce the asset key `"zarr-store"` instead.
- **WHY**: Unpublish will fail with `"STAC item has no 'reference' asset href"` for every release produced by either native Zarr pipeline. Users cannot clean up data they have approved and later want to remove.
- **WHERE**: `services/unpublish_handlers.py`, function `inventory_zarr_item`, lines 574-583. The asset key lookup is at line 575 (`assets.get('reference', {})`) and the href fallback error is at lines 578-583.
- **HOW**: After the existing `ref_asset = assets.get('reference', {})` block, add a fallback to check `assets.get('zarr-store', {})`. When the asset key is `zarr-store`, the href points to the Zarr store prefix (HTTPS URL) rather than a `combined_ref.json` file. The blob enumeration logic must be branched: for `"reference"` assets, enumerate reference files as today; for `"zarr-store"` assets, list all blobs under the store prefix and classify them as `category="zarr-chunk"`.
- **EFFORT**: Medium (2-3 hours).
- **RISK OF FIX**: Low. The existing `"reference"` path is untouched; this adds a new branch.

### Fix 2: Versioned zarr submissions lose `zarr/` prefix

- **WHAT**: Step 6 in `submit.py` (lines 328-334) overwrites `output_folder` using `generate_raster_output_folder()` which produces `{dataset_id}/{resource_id}/{ordinal}` without the `zarr/` prefix. This fires for any zarr submission with a `version_id`.
- **WHY**: Zarr stores will be written to the wrong blob prefix, creating namespace collisions with raster COG output folders.
- **WHERE**: `triggers/platform/submit.py`, lines 328-334 (Step 6).
- **HOW**: Guard Step 6 so it only fires for raster data types:
  ```python
  if 'output_folder' in job_params and release.version_ordinal and platform_req.data_type == DataType.RASTER:
  ```
- **EFFORT**: Small (30 minutes).
- **RISK OF FIX**: Low. Raster path unchanged.

### Fix 3: xarray dataset and temp directory leak on convert exception

- **WHAT**: In `netcdf_convert`, `ds.close()` is only called in the happy path (line 680). The except block (lines 713-720) does not close the dataset or clean up the temp directory.
- **WHY**: On conversion failure, file handles remain open and temp directory leaks. Over multiple failed jobs this exhausts file descriptors or disk space on the shared mount.
- **WHERE**: `services/handler_netcdf_to_zarr.py`, function `netcdf_convert`, lines 556-720.
- **HOW**: Restructure to use try/finally. Move `ds = None` before the try block. In a `finally` block, close `ds` if not None, and attempt `shutil.rmtree(local_dir)`.
- **EFFORT**: Small (30 minutes).
- **RISK OF FIX**: Low.

### Fix 4: `netcdf_register` reports success when DB updates fail + no Zarr verification

- **WHAT**: `netcdf_register` returns `"success": True` even when all three DB updates (`update_stac_item_json`, `update_physical_outputs`, `update_processing_status`) return False. It also does not verify the Zarr store exists, unlike `ingest_zarr_register` which opens the store with `xr.open_zarr`.
- **WHY**: Ghost releases: job system thinks it succeeded, but approval workflow sees a release stuck in `processing`. Corrupt Zarr stores not caught.
- **WHERE**: `services/handler_netcdf_to_zarr.py`, function `netcdf_register`, lines 788-952. Warning-only checks at lines 900-903, 912-915, 923-926.
- **HOW**: (a) Return `"success": False` if any critical DB update fails (at minimum `update_processing_status`). (b) Add Zarr store verification before DB updates, mirroring `ingest_zarr_register` lines 472-484.
- **EFFORT**: Medium (1-2 hours).
- **RISK OF FIX**: Low.

### Fix 5: `normalize_data_type` does not recognize `netcdf_to_zarr` or `ingest_zarr`

- **WHAT**: The function only maps `'zarr'`, `'virtualzarr'`, and `'unpublish_zarr'` to `'zarr'`. Both new pipeline names are missing.
- **WHY**: Data type filtering, catalog queries, and unpublish routing will fail for these pipeline variants.
- **WHERE**: `services/platform_translation.py`, function `normalize_data_type`, line 68.
- **HOW**: Extend: `if dt_lower in ('zarr', 'virtualzarr', 'unpublish_zarr', 'netcdf_to_zarr', 'ingest_zarr'):`
- **EFFORT**: Small (15 minutes).
- **RISK OF FIX**: Low.

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| **Time range as raw numpy str** (M-3) | Close enough to ISO 8601; no STAC validator in pipeline yet | STAC validator added or consumer rejects format |
| **Full-file memory load in copy** (L-3) | Current files sub-1GB; Docker worker has 8GB. Mount architecture designed for future streaming replacement | File > 2GB submitted or pipeline goes operational |
| **No janitor for stale temp files** (BS-5) | Docker worker container is ephemeral; restarts clear mount between deployments | Persistent storage added or failure rate fills mount |
| **Global spatial fallback** (BS-7) | Produces valid discoverable STAC items; alternative (fail pipeline) blocks legitimate datasets without CRS | STAC quality gate added to approval |
| **Import layering violation** (AR-2) | Imported function is pure config helper with no side effects; same pattern in virtualzarr and ingest_zarr handlers | Broader refactoring pass on services/jobs boundary |
| **Copy size mismatch as warning** (H-2) | Validate stage will catch corrupt files. Could be upgraded to failure later | After verifying validate catches all truncation cases |

---

## ARCHITECTURE WINS

1. **Stage result propagation**: Convert handler returns metadata (spatial_extent, time_range, variables, dimensions) in its result dict, eliminating a costly Zarr store re-open in the register handler. More efficient than `ingest_zarr_register` which re-opens with `xr.open_zarr`.

2. **Translation layer isolation**: The `translate_to_coremachine()` function cleanly separates DDH API concepts from pipeline internals. Three zarr variants selected via single `pipeline` attribute keeps submit trigger pipeline-agnostic.

3. **Step 6b ordinal finalization**: The zarr branch correctly handles both `ref_output_prefix` (VirtualiZarr) and `output_folder` (NetCDF-to-Zarr) with ordinal-based paths.

4. **Consistent STAC item structure**: Both `netcdf_register` and `ingest_zarr_register` produce identical STAC shapes with `"zarr-store"` asset key, enabling uniform downstream consumption.

5. **Single-file and multi-file scan flexibility**: The scan handler detects single-file submissions by pattern-matching the URL, avoiding requirement for users to specify file count.

---

## ALL FINDINGS (Severity-Ranked)

### CRITICAL

| ID | Finding | Confidence |
|----|---------|------------|
| BS-1 | `inventory_zarr_item` cannot handle `netcdf_to_zarr` or `ingest_zarr` output — looks for `"reference"` asset key that only virtualzarr produces | CONFIRMED |
| C-1 | Versioned zarr submissions lose `zarr/` prefix in `output_folder` — Step 6 uses raster path generator | CONFIRMED |

### HIGH

| ID | Finding | Confidence |
|----|---------|------------|
| AR-1 | xarray dataset file handle + temp dir leak on convert exception | CONFIRMED |
| H-1 | `netcdf_register` does not verify Zarr store exists before COMPLETED | CONFIRMED |
| H-2 | Copy size mismatch is warning, not failure — truncated file proceeds | CONFIRMED |
| F-4 | `netcdf_register` reports success despite failed DB updates | CONFIRMED |

### MEDIUM

| ID | Finding | Confidence |
|----|---------|------------|
| AR-2 | Import layering violation: services imports from jobs | CONFIRMED |
| BS-2 | `normalize_data_type` does not recognize `netcdf_to_zarr` or `ingest_zarr` | CONFIRMED |
| BS-3 | Single-file scan swallows blob property errors, sets size=0 | CONFIRMED |
| BS-4 | source_url not normalized from container_name+file_name (fails loud) | CONFIRMED |
| BS-7 | Global spatial fallback + "now" datetime — Constitution 1.1 violation | CONFIRMED |
| F-6 | Handlers don't include `"retryable": False` — wasteful retries | CONFIRMED |
| M-2 | Coordinate name lookup only checks 3 hardcoded names per axis | CONFIRMED |
| M-3 | Time range serialized as raw str(numpy.datetime64), not ISO 8601 | CONFIRMED |
| M-6 | `ds.to_zarr()` without explicit encoding may not preserve source chunking | SPECULATIVE |
| H-4 | Undeclared parameters in schema (title, description, tags, etc.) | CONFIRMED |

### LOW

| ID | Finding | Confidence |
|----|---------|------------|
| L-3 | netcdf_copy reads entire file into memory (multi-GB risk) | CONFIRMED |
| BS-5 | No janitor for /mounts/etl-temp stale files | PROBABLE |
| L-1 | Duplicate URL parsing in _read_manifest helpers | CONFIRMED |
| L-2 | version_id extracted but unused in STAC item | CONFIRMED |
| L-4 | test_ds not protected by context manager | CONFIRMED |
| BS-6 | Logging exposes source storage account name + blob path | PROBABLE |
