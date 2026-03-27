# COMPETE Run 55: Tiled Raster Handlers

**Date**: 26 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Version**: v0.10.6.3
**Split**: C (Data vs Control Flow)

## Scope

Tiled raster path: handlers that generate tiling schemes, process individual tiles in parallel via fan-out, and persist aggregated results via fan-in. The single COG path was reviewed in Run 51; this review covers the tiled path exclusively.

**Target Files**:
- `services/raster/handler_generate_tiling_scheme.py`
- `services/raster/handler_process_single_tile.py`
- `services/raster/handler_persist_tiled.py`
- `services/raster/handler_upload_cog.py` (context -- shared by tiled path)
- `services/raster_cog.py` (context -- COG creation utility)
- `services/tiling_scheme.py` (context -- tiling grid computation)
- `services/raster/identifiers.py` (context -- deterministic ID generation)
- `workflows/process_raster.yaml` (context -- orchestration)

---

## Omega Decision

**Split C (Data vs Control Flow)** confirmed. This is an ETL pipeline subsystem that transforms large rasters into tiled COGs. The productive tension is between data integrity (pixel windows, overlap, nodata, COG metadata, spatial bounds) and control flow (fan-out/fan-in orchestration, parallel execution isolation, temp file lifecycle, partial failure).

**Alpha (Data Integrity)** scope: tiling scheme correctness, pixel window calculations, COG metadata stamping, nodata handling, spatial bounds accuracy, data consistency across stores, encoding/CRS handling.

**Beta (Orchestration + Failure Handling)** scope: fan-out/fan-in boundary, parallel execution safety, temp file isolation, partial failure recovery, idempotency, error recovery per tile, resource lifecycle.

**Constitution sections**: Alpha gets Sections 1, 7 (zero-tolerance, error categories), 4 (import hierarchy), 9 (job patterns), 6 (database patterns). Beta gets Sections 1, 3 (error handling), 5 (platform dispatch), 6 (database patterns), 9 (job patterns).

---

## Alpha Review (Data Integrity)

### STRENGTHS

1. **Deterministic tile identity derivation** (`services/raster/identifiers.py:23-39`). The `derive_stac_item_id()` function produces deterministic IDs from `collection_id` + `blob_path`, matching the monolith's derivation exactly. Used consistently in both `handler_process_single_tile.py:241` and `handler_upload_cog.py:188`.

2. **Pixel window correctness in tiling scheme** (`services/tiling_scheme.py:219-283`). The `generate_tile_windows()` function correctly handles edge tiles by clamping width/height to `min(tile_size, target_dimension - offset)` at lines 260-261. This prevents reading past raster boundaries.

3. **Overlap-aware grid calculation** (`services/tiling_scheme.py:175-216`). The `calculate_tile_grid()` function uses `effective_tile_size = tile_size - overlap` for grid computation, then applies the full `tile_size` for each tile's window dimensions. This ensures tiles overlap by exactly 512 pixels (one COG block), preventing seam artifacts.

4. **Tile bounds in EPSG:4326** (`services/tiling_scheme.py:286-311`). Geographic bounds are correctly derived from pixel windows using degrees-per-pixel resolution, with proper Y-axis inversion at line 306 (`maxy = target_bounds[3] - ...`).

5. **COG stamp table covers common band/dtype combos** (`services/raster_cog.py:187-202`). The `_COG_STAMP_TABLE` correctly maps band_count + dtype to color interpretation and nodata values for RGB, RGBA, DEM, and categorical rasters.

### CONCERNS

**ALPHA-HIGH-1: Double COG stamp -- stamp after upload means stamp is applied to a file that has already been uploaded**

`handler_process_single_tile.py:193-194` sets `_skip_upload: False` (meaning `create_cog` uploads the COG to silver). Then `_process_cog_disk_based` at `raster_cog.py:491` stamps the COG *before* uploading at line 531. So far correct. However, `handler_process_single_tile.py:218-225` then attempts to stamp the local COG *again* after `create_cog` returns. This second stamp is redundant -- the file was already stamped and uploaded. The stamp modifies the local file but the uploaded blob already has the first stamp. If the second stamp changes nodata (e.g., from None to a value), the local file diverges from what was uploaded to silver.

- File: `services/raster/handler_process_single_tile.py`, lines 218-225
- Impact: Local file metadata may differ from blob metadata. Currently non-fatal because the stamping is idempotent (same band_count/dtype produces same stamp), but it introduces a silent divergence path if stamp logic ever changes.

**ALPHA-HIGH-2: Tile width/height stored as 0 in cog_metadata -- spatial dimensions lost**

`handler_persist_tiled.py:136-137` hardcodes `width=0, height=0` in the `cog_repo.upsert()` call with the comment "Tile dimensions not tracked individually." This means cog_metadata rows for tiled rasters have no spatial dimension information. Any downstream consumer that reads `width`/`height` from cog_metadata (e.g., for validation, STAC extent calculation, or render config) will get incorrect values.

- File: `services/raster/handler_persist_tiled.py`, lines 136-137
- Impact: Data loss. Tile pixel dimensions are known at processing time (`tile_spec.target_width_pixels`, `tile_spec.target_height_pixels`) and available in the fan-out results, but they are discarded before persistence.

**ALPHA-MEDIUM-1: Tiling scheme operates in output pixel space but tile extraction uses source pixel space**

`handler_generate_tiling_scheme.py` calls `generate_tiling_scheme_from_raster()` which computes tile windows in *EPSG:4326 output space* (see `tiling_scheme.py:228-229` comment: "CRITICAL: These are pixel windows in EPSG:4326 output space"). However, `handler_process_single_tile.py:147-151` constructs a rasterio `Window` and reads from the *source raster* using `src.read(window=win)` at line 155. If the source raster CRS differs from EPSG:4326, these pixel coordinates are in the wrong coordinate space -- the output-space pixel window is applied to the source-space raster.

This works correctly when `needs_reprojection=False` (source is already EPSG:4326). When `needs_reprojection=True`, the tile handler extracts a source-space window using output-space coordinates, which reads the wrong region. The subsequent COG creation step (`create_cog`) does perform reprojection via WarpedVRT, but the *input* to that step is already a wrongly-windowed extract.

- File: `services/raster/handler_process_single_tile.py`, lines 147-161
- File: `services/tiling_scheme.py`, lines 228-229
- Impact: When source CRS != EPSG:4326, tiles will extract incorrect spatial regions from the source raster. The degree of error depends on the CRS difference. For sources already in EPSG:4326, this is not a problem.

**ALPHA-MEDIUM-2: bbox fallback of `[0, 0, 0, 0]` masks missing spatial data**

`handler_persist_tiled.py:113` uses `bbox=tile_bounds if len(tile_bounds) >= 4 else [0, 0, 0, 0]` when building the STAC item. A bbox of `[0,0,0,0]` is a valid geographic location (Gulf of Guinea) and would create a phantom spatial footprint rather than failing explicitly.

- File: `services/raster/handler_persist_tiled.py`, line 113
- Constitution: Violates Principle 1 (Explicit Failure Over Silent Accommodation). Missing bounds should be an error, not a degenerate default.

**ALPHA-MEDIUM-3: Tile blob path lacks collection_id prefix**

`handler_process_single_tile.py:178` constructs `cog_blob_name = f"{job_id[:8]}/tile_r{row}_c{col}.tif"`. This is then passed to `create_cog` as `output_blob_name`. Inside `create_cog`, the tier suffix is appended (e.g., `_analysis`), producing paths like `abcd1234/tile_r0_c0_analysis.tif`. The silver blob path convention elsewhere is `cogs/{collection_id}/{filename}`, but the tile path omits `collection_id`. This means tiled COGs land in a different directory structure than single COGs, potentially confusing downstream queries.

- File: `services/raster/handler_process_single_tile.py`, line 178
- Impact: Inconsistent blob path convention between single and tiled COG paths.

**ALPHA-LOW-1: `target_width_pixels` and `target_height_pixels` passed through tiling scheme but unused by tile handler**

`handler_generate_tiling_scheme.py:116-117` includes `target_width_pixels` and `target_height_pixels` in each tile_spec. These are not consumed by `handler_process_single_tile.py` -- the handler uses `pixel_window.width` and `pixel_window.height` instead. The fields are redundant (they have the same values as `pixel_window.width`/`height`).

- File: `services/raster/handler_generate_tiling_scheme.py`, lines 116-117
- Impact: Dead data in the contract. Low severity but adds cognitive load.

### ASSUMPTIONS

1. **Source rasters for tiled path are always in EPSG:4326 or will be correctly reprojected.** If ALPHA-MEDIUM-1 is real, then all E2E tests used EPSG:4326 sources, masking the issue.

2. **The 512-pixel overlap is sufficient for all use cases.** The tiling scheme hardcodes 512px overlap. For some interpolation-heavy operations (e.g., high-order resampling near tile edges), 512px may not be enough to eliminate edge artifacts.

3. **`create_cog` always returns `cog_blob` in its result dictionary.** The fallback chain at `handler_process_single_tile.py:208` (`output_blob or cog_blob or cog_blob_name`) suggests uncertainty about which key `create_cog` actually returns.

### RECOMMENDATIONS

1. **Remove the second stamp in handler_process_single_tile.py** (lines 218-225). `create_cog` -> `_process_cog_disk_based` already stamps at `raster_cog.py:491`. The second stamp is redundant and creates a divergence risk.

2. **Pass tile dimensions to `cog_repo.upsert()`** in `handler_persist_tiled.py:136-137`. The tile_spec contains `target_width_pixels` and `target_height_pixels`; propagate these through the fan-out result and use them instead of hardcoded zeros.

3. **Validate that source CRS == EPSG:4326 when using pixel windows directly**, or use WarpedVRT in the tile extraction step when reprojection is needed. The current architecture assumes output-space windows are valid for source-space reads, which is only true when CRS matches.

4. **Replace `[0,0,0,0]` bbox fallback with an explicit error** in `handler_persist_tiled.py:113`. Per Constitution Principle 1.

---

## Beta Review (Orchestration + Failure Handling)

### VERIFIED SAFE

1. **Fan-out template correctly injects `{{ item }}` per tile** (`workflows/process_raster.yaml:118`). Each fan-out child receives the full tile_spec as `{{ item }}`, ensuring every tile gets its own pixel_window, row, col, and bounds. No shared mutable state between children.

2. **Unique temp file paths per tile** (`handler_process_single_tile.py:133-137`). Tile files are written to `{mount_path}/{run_id}/tiles/tile_r{row}_c{col}.tif`. The `run_id`-scoped directory + row/col naming eliminates collisions between parallel tiles. Bug #16 (shared `_run_id` causing temp file collisions) is fixed.

3. **COG task ID includes row/col for unique output paths** (`handler_process_single_tile.py:192`). `_task_id: f"{run_id[:8]}_r{row}_c{col}"` ensures `create_cog` writes to `output_{run_id[:8]_rN_cM}.cog.tif` -- unique per tile.

4. **Fan-in aggregation uses `collect` mode** (`workflows/process_raster.yaml:130`). The `aggregate_tiles` fan-in node collects all completed fan-out results into a list. This is the correct pattern for accumulating tile results before persistence.

5. **Tile JSON deserialization is guarded** (`handler_process_single_tile.py:72-82`). The handler gracefully handles `tile_spec` being a JSON string (from Jinja2 rendering) by parsing it with `json.loads()`.

### FINDINGS

**BETA-HIGH-1: Stamp occurs after upload -- local file modification is invisible to silver blob**

`handler_process_single_tile.py` passes `_skip_upload: False` (line 194), so `create_cog` uploads the COG to silver. Then lines 218-225 stamp the *local* COG file. But the blob is already in silver. The stamp modifies a local file that nobody reads afterward (it is deleted at line 230). This means:
- If `_process_cog_disk_based` stamps correctly (it does, at `raster_cog.py:491`), the second stamp is harmless but wasteful.
- If the intent was to stamp *after* `create_cog` but *before* upload, the `_skip_upload` flag should be `True` and upload should be a separate step.

- File: `services/raster/handler_process_single_tile.py`, lines 193-194, 218-225
- Impact: Wasted I/O. If the first stamp in `create_cog` is ever removed, tiles in silver would lack color interpretation.

**BETA-HIGH-2: No per-tile retry -- all tiles marked `retryable: False`**

`handler_process_single_tile.py:274` returns `retryable: False` for all tile processing errors. Also at lines 201-205 (COG creation failure). Given that tile processing can fail due to transient I/O errors (file system, blob storage), marking all errors as non-retryable means any transient failure kills the entire tiled workflow. The fan-out has no mechanism to retry individual tiles.

- File: `services/raster/handler_process_single_tile.py`, lines 201-205, 274
- Impact: A single transient failure in one of 24+ tiles fails the entire raster processing job.

**BETA-HIGH-3: Partial tile persist succeeds silently -- `persist_tiled` returns success even with failures**

`handler_persist_tiled.py:168-191` returns `success: True` even when some tiles failed to persist, as long as at least one succeeded. The result includes `partial_failure: True` and an `errors` list, but the handler's success status is `True`. Downstream handlers (like `stac_materialize_collection`) see a success and proceed, even though the STAC collection may have missing tiles.

- File: `services/raster/handler_persist_tiled.py`, lines 168-191
- Impact: STAC collection created with incomplete tiles. No explicit failure signal propagated through the DAG for partial failures.

**BETA-MEDIUM-1: Source raster file handle opened N times by N parallel tiles**

Each fan-out tile opens the same source raster file with `rasterio.open(source_path)` at `handler_process_single_tile.py:154`. For a 24-tile fan-out, this means 24 concurrent file opens on the same Azure Files mount path. While rasterio supports concurrent reads, Azure Files has IOPS limits. Under heavy load, this could cause throttling or timeouts.

- File: `services/raster/handler_process_single_tile.py`, line 154
- Impact: Potential I/O bottleneck with many tiles on Azure Files mount.

**BETA-MEDIUM-2: Cleanup deletes tile files but not tile directory**

`handler_process_single_tile.py:230-235` deletes individual tile files and the local COG, but does not remove the `{mount_path}/{run_id}/tiles/` directory. For a 24-tile job, after all tiles complete, 24 empty tile directories remain on the mount. Over many jobs, these accumulate.

Note: The janitor Phase 3 (`dag_janitor.py`) handles mount cleanup for directories older than 30 days, so this is a long-term cleanup gap, not an immediate risk.

- File: `services/raster/handler_process_single_tile.py`, lines 230-235
- Impact: Mount directory accumulation between janitor sweeps.

**BETA-MEDIUM-3: `persist_tiled` tile_results extraction is fragile**

`handler_persist_tiled.py:76-80` unwraps tile results with `result = entry.get("result", entry)`. This assumes fan-in results are either `{"result": {...}}` or flat dicts. If the fan-in format changes (e.g., nested differently), the extraction silently gets the wrong data and the `if result.get("item_id")` check at line 79 filters it out, losing tiles without error.

- File: `services/raster/handler_persist_tiled.py`, lines 76-80
- Constitution: Violates Principle 10 (Explicit Data Contracts). The expected fan-in result structure should be validated, not guessed.

### RISKS

1. **Azure Files mount IOPS throttling**: 24+ concurrent rasterio opens on the same file could hit Azure Files Standard share limits (~1000 IOPS). Premium tier would be needed for large fan-outs.

2. **Job timeout for large tile counts**: Each tile does extract + COG translate + upload. For 24 tiles at ~5 minutes each, total wall time depends on parallelism. If the DAG Brain processes tiles sequentially (single worker), the job could exceed timeout thresholds.

3. **Source raster deleted by upload_single_cog on wrong path**: The YAML does not pass `source_path` cleanup to the tiled path. If `handler_upload_cog.py` is ever mistakenly added to the tiled path, its line 317 (`os.remove(source_path)`) would delete the shared source raster while other tiles are still reading it.

### EDGE CASES

1. **Single-tile tiling scheme**: If the raster is just above the 2GB threshold, the tiling scheme may produce exactly 1 tile. The fan-out/fan-in machinery still works, but adds overhead for no benefit.

2. **Zero-band raster**: If `band_count=0` (corrupt file), `calculate_optimal_tile_size` at `tiling_scheme.py:106` would divide by zero.

3. **Empty tile window at raster boundary**: If `target_width - col_off <= 0` due to rounding in grid calculation, a tile with zero width could be generated. The `min()` at `tiling_scheme.py:260` prevents negative values but not zero.

4. **tile_spec as malformed JSON string**: `handler_process_single_tile.py:74-82` handles `json.JSONDecodeError` but truncates the error message to 100 chars. For debugging, the full tile_spec would be more useful.

---

## Gamma Review (Contradictions, Blind Spots, Severity Recalibration)

### CONTRADICTIONS

None. Alpha and Beta independently identified the same double-stamp issue (ALPHA-HIGH-1 = BETA-HIGH-1) from different perspectives -- Alpha noted the data divergence risk, Beta noted the ordering/upload concern. Their analyses are compatible and reinforcing.

### AGREEMENT REINFORCEMENT

**AR-1: Double COG stamp is the highest-confidence finding** (ALPHA-HIGH-1 + BETA-HIGH-1). Both reviewers independently identified that `handler_process_single_tile.py:218-225` stamps a local COG file *after* `create_cog` has already stamped and uploaded it. The stamp is applied to a file that is about to be deleted. CONFIRMED: Traced the execution path from `_skip_upload: False` (line 194) -> `_process_cog_disk_based` uploads at `raster_cog.py:531` -> returns -> handler stamps local file at line 218 -> handler deletes local file at line 230.

**AR-2: Partial failure masking in persist_tiled** (ALPHA-MEDIUM-2 bbox fallback + BETA-HIGH-3 partial success). Both reviewers found cases where `handler_persist_tiled.py` accommodates failures silently rather than failing explicitly. Alpha found the `[0,0,0,0]` bbox fallback; Beta found the partial-success return pattern. Both violate Constitution Principle 1.

### BLIND SPOTS

**BLIND-1: `handler_process_single_tile.py` stamps after upload but `create_cog` already uploaded with stamp -- the *upload itself* happens inside create_cog, NOT as a separate handler step** [CONFIRMED]

Neither Alpha nor Beta fully traced why the tiled path does not use `handler_upload_cog.py`. Looking at `workflows/process_raster.yaml:111-128`, the tiled path goes: `generate_tiling_scheme` -> `process_tiles` (fan-out) -> `aggregate_tiles` (fan-in) -> `persist_tiled`. There is NO `upload_cog` node in the tiled path. Upload happens *inside* `handler_process_single_tile.py` via `create_cog(..., _skip_upload=False)`. This means `handler_upload_cog.py` is only used by the single COG path.

This design choice embeds upload logic inside the tile processing handler, making it non-composable. The single COG path separates create/upload/persist into three handlers (composable), but the tiled path combines create+upload into one handler. This is an architectural inconsistency.

- File: `workflows/process_raster.yaml`, lines 111-128 (tiled path) vs 53-101 (single path)
- Confidence: CONFIRMED -- traced through YAML and handler code.

**BLIND-2: `cog_container` fallback to `config.storage.silver.cogs` may return a different value than what `create_cog` used** [PROBABLE]

`handler_process_single_tile.py:209` falls back to `config.storage.silver.cogs` when `create_cog` does not return a `cog_container` key. But `create_cog` at `raster_cog.py:847` uses `config_obj.storage.silver.get_container('cogs')`. These *should* return the same value, but `get_container('cogs')` may apply different logic than the `.cogs` property. If they diverge, the tile result reports a container name that differs from where the blob was actually uploaded.

- File: `services/raster/handler_process_single_tile.py`, line 209
- Confidence: PROBABLE -- requires verifying `get_container('cogs')` vs `.cogs` property equivalence.

**BLIND-3: `handler_generate_tiling_scheme.py` does NOT pass `_run_id` to `generate_tiling_scheme_from_raster`** [CONFIRMED]

The handler at line 91 calls `generate_tiling_scheme_from_raster()` with `raster_path`, `tile_size`, `overlap`, and `target_crs`. It does NOT pass `_run_id` or any job identity. This is correct (the tiling scheme function is stateless), but it means the tiling scheme has no traceability back to the specific run. If the same raster is tiled twice with the same parameters, the tile_specs are identical. This is actually correct behavior (deterministic), but worth noting.

- File: `services/raster/handler_generate_tiling_scheme.py`, line 91
- Confidence: CONFIRMED. Not a bug -- deterministic behavior per Principle 2.

**BLIND-4: No validation of `tile_results` item structure in `handler_persist_tiled.py`** [CONFIRMED]

The handler at lines 76-80 does `entry.get("result", entry)` without validating the expected keys (`item_id`, `blob_path`, `container`, `cog_url`, `bounds_4326`). If a fan-out child returns a malformed result (e.g., missing `item_id`), the tile is silently skipped at line 79 (`if result.get("item_id")`). There is no logging or error counting for skipped tiles. A tile that processed correctly but returned a result with a typo in the key name (e.g., `itemId` instead of `item_id`) would be silently lost.

- File: `services/raster/handler_persist_tiled.py`, lines 76-80
- Constitution: Violates Principle 10 (Explicit Data Contracts) and Principle 1 (Explicit Failure Over Silent Accommodation).
- Confidence: CONFIRMED -- traced the code path.

**BLIND-5: `handler_process_single_tile.py` does not validate pixel_window values are positive integers** [CONFIRMED]

Lines 147-152 construct a rasterio `Window` from `pixel_window.get("col_off", 0)`, etc. The defaults of 0 and 256 mean a malformed pixel_window (e.g., string values, negative numbers, or missing keys) would produce a degenerate Window that reads from the wrong region or raises a cryptic rasterio error. The handler checks `if not pixel_window` at line 139 (empty dict), but does not validate the *contents* of the dict.

- File: `services/raster/handler_process_single_tile.py`, lines 139-152
- Confidence: CONFIRMED.

### SEVERITY RECALIBRATION

| ID | Source | Original | Recalibrated | Confidence | Rationale |
|----|--------|----------|-------------|------------|-----------|
| ALPHA-MEDIUM-1 | Alpha | MEDIUM | **HIGH** | PROBABLE | CRS mismatch during tile extraction could produce completely wrong spatial data. Only safe when source == EPSG:4326. |
| ALPHA-HIGH-1 / BETA-HIGH-1 | Both | HIGH | **MEDIUM** | CONFIRMED | Double stamp is redundant but harmless -- both stamps produce identical output for the same band_count/dtype. Risk is future divergence if stamp logic changes. |
| ALPHA-HIGH-2 | Alpha | HIGH | **HIGH** | CONFIRMED | width=0, height=0 is real data loss, affects any downstream consumer of cog_metadata dimensions. |
| ALPHA-MEDIUM-2 | Alpha | MEDIUM | **HIGH** | CONFIRMED | [0,0,0,0] bbox is a Constitution violation (Principle 1). Creates phantom spatial footprint. |
| BETA-HIGH-2 | Beta | HIGH | **MEDIUM** | CONFIRMED | Non-retryable tiles is a design choice -- the DAG framework could add retry at the task level. Not a bug, but a robustness gap. |
| BETA-HIGH-3 | Beta | HIGH | **HIGH** | CONFIRMED | Partial success masking is a real risk -- downstream STAC collection created with missing tiles. |
| BETA-MEDIUM-3 | Beta | MEDIUM | **HIGH** | CONFIRMED | Silent tile loss from malformed fan-in results violates Principles 1 and 10. |
| BLIND-1 | Gamma | -- | **MEDIUM** | CONFIRMED | Architectural inconsistency (non-composable tile handler) -- not a bug, but a design debt. |
| BLIND-4 | Gamma | -- | **HIGH** | CONFIRMED | Silent data loss from unvalidated fan-in results. |
| BLIND-5 | Gamma | -- | **MEDIUM** | CONFIRMED | Missing pixel_window validation -- degenerate values produce wrong reads. |

---

## Delta Report (Final)

### EXECUTIVE SUMMARY

The tiled raster pipeline is functionally correct for its primary use case (EPSG:4326 source rasters processed into tiled COGs). The fan-out/fan-in machinery works, temp file isolation is sound (Bug #16 fix confirmed), and deterministic identifiers are correctly derived. However, the pipeline has five actionable issues: (1) tile extraction uses output-space pixel windows on source-space rasters, which is only correct when CRS matches; (2) tile dimensions are discarded during persistence; (3) partial failures are silently accommodated rather than explicitly surfaced; (4) fan-in result validation is absent, creating a silent data loss path; and (5) the double COG stamp is harmless but wasteful. The most impactful fix is adding CRS validation to prevent incorrect tile extraction when the source is not in EPSG:4326.

### TOP 5 FIXES

#### Fix 1: Validate source CRS matches target CRS before pixel-window extraction

- **WHAT**: Add a guard that fails explicitly when `needs_reprojection=True` and the handler attempts to extract a tile using output-space pixel windows from a source-space raster.
- **WHY**: The tiling scheme generates pixel windows in EPSG:4326 output space (`tiling_scheme.py:228`). The tile handler applies these windows directly to the source raster (`handler_process_single_tile.py:154-155`). When source CRS != EPSG:4326, this reads the wrong spatial region. The 8.8GB tiled raster E2E test worked because the source was likely already in EPSG:4326.
- **WHERE**: `services/raster/handler_process_single_tile.py`, function `raster_process_single_tile`, lines 112-155. Add validation after line 119 (source_path exists check).
- **HOW**: Either (a) fail with an explicit error when `needs_reprojection=True` (forcing the caller to pre-reproject), or (b) use a `WarpedVRT` to open the source raster in the target CRS before windowed reads, similar to `raster_cog.py:458-464`. Option (b) is more robust but more complex. At minimum, add: `if needs_reprojection: return {"success": False, "error": "Tiled extraction requires source in target CRS. Pre-reproject the source raster.", "retryable": False}`.
- **EFFORT**: Small (< 1 hour) for option (a), Medium (1-4 hours) for option (b).
- **RISK OF FIX**: Low. Option (a) is a safe guard. Option (b) requires testing with WarpedVRT + windowed reads.

#### Fix 2: Validate fan-in result structure in persist_tiled and log skipped tiles

- **WHAT**: Add explicit validation of required keys in each tile result, and log/count tiles that are skipped due to missing data.
- **WHY**: `handler_persist_tiled.py:76-80` silently drops tiles where `result.get("item_id")` is falsy. A fan-out child that succeeds but returns a malformed result (missing `item_id`) is silently lost. This violates Constitution Principles 1 and 10.
- **WHERE**: `services/raster/handler_persist_tiled.py`, function `raster_persist_tiled`, lines 75-88.
- **HOW**: Define the expected keys: `required_keys = {"item_id", "blob_path", "container", "cog_url", "bounds_4326"}`. For each entry, validate presence of all required keys. Log a warning for each skipped entry with the missing keys. If all entries are skipped, return `success: False` with details. Add a `skipped_tiles` counter to the result.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Purely additive validation.

#### Fix 3: Replace `[0,0,0,0]` bbox fallback with explicit failure

- **WHAT**: Fail explicitly when `tile_bounds` has fewer than 4 elements instead of using `[0,0,0,0]`.
- **WHY**: A bbox of `[0,0,0,0]` is a valid geographic location (Gulf of Guinea) and creates a phantom spatial footprint in STAC. This violates Constitution Principle 1 (Explicit Failure Over Silent Accommodation). If bounds are missing, the tile's metadata is corrupt and should not be persisted.
- **WHERE**: `services/raster/handler_persist_tiled.py`, function `raster_persist_tiled`, line 113.
- **HOW**: Replace `bbox=tile_bounds if len(tile_bounds) >= 4 else [0, 0, 0, 0]` with a validation check: `if not tile_bounds or len(tile_bounds) < 4: errors.append(f"{tile_cog_id}: missing bounds_4326"); continue`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Tiles with missing bounds will be counted as errors rather than silently persisted with wrong coordinates.

#### Fix 4: Pass tile dimensions to cog_metadata upsert instead of hardcoded zeros

- **WHAT**: Propagate `target_width_pixels` and `target_height_pixels` from the fan-out result into the cog_metadata `width` and `height` fields.
- **WHY**: `handler_persist_tiled.py:136-137` stores `width=0, height=0`. This discards known tile dimensions, making cog_metadata incomplete. Any downstream query filtering by dimensions or computing aggregate statistics will get incorrect results.
- **WHERE**: `services/raster/handler_persist_tiled.py`, function `raster_persist_tiled`, lines 100-137. Also requires `handler_process_single_tile.py` to include width/height in its return value (from the pixel_window or COG metadata).
- **HOW**: In `handler_process_single_tile.py`, add `"width": win.width` and `"height": win.height` to the success result dict (around line 254). In `handler_persist_tiled.py`, read these from the tile result: `tile_width = tile.get("width", 0)`, `tile_height = tile.get("height", 0)`, and pass them to `cog_repo.upsert(width=tile_width, height=tile_height)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Additive data, no existing behavior changed.

#### Fix 5: Remove redundant second stamp in handler_process_single_tile.py

- **WHAT**: Remove the COG stamp block at lines 211-225 in `handler_process_single_tile.py`.
- **WHY**: `create_cog` with `_skip_upload=False` already stamps the COG at `raster_cog.py:491` *before* uploading to silver. The second stamp modifies a local file that is immediately deleted. It is wasted I/O and creates a theoretical divergence path if stamp logic ever changes. Both Alpha and Beta independently identified this.
- **WHERE**: `services/raster/handler_process_single_tile.py`, function `raster_process_single_tile`, lines 211-225 (the "Step 3: Stamp COG metadata" block).
- **HOW**: Delete lines 211-225. The comment block and stamp logic are entirely redundant. If the intent is to stamp *after* create_cog but *before* upload, the handler should use `_skip_upload=True` and add a separate upload step (like the single COG path does).
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Removing dead code.

### ACCEPTED RISKS

1. **Non-composable tile handler (BLIND-1)**: The tiled path combines create+upload inside `handler_process_single_tile.py`, while the single COG path separates them into distinct handlers. This is a design inconsistency but not a bug. Refactoring to match the single COG pattern would require adding `upload_cog` to the fan-out template, which adds complexity to the DAG. **Revisit when**: the tile handler needs to support different upload targets or when composability becomes a product requirement.

2. **Non-retryable tiles (BETA-HIGH-2)**: All tile errors return `retryable: False`. The DAG framework supports task-level retry via the janitor, so retry semantics should be managed there, not in the handler. **Revisit when**: transient failures (blob upload timeouts, IOPS throttling) are observed in production.

3. **Azure Files IOPS for concurrent tile reads (BETA-MEDIUM-1)**: 24+ concurrent `rasterio.open()` calls on the same source file may hit Azure Files limits. Current scale (24 tiles on Premium tier) is within limits. **Revisit when**: tile counts exceed 50 or Standard tier is used.

4. **`cog_container` property equivalence (BLIND-2)**: `config.storage.silver.cogs` vs `config_obj.storage.silver.get_container('cogs')` -- assumed to be equivalent. **Revisit when**: storage config layer is refactored.

5. **Partial persist success (BETA-HIGH-3)**: `persist_tiled` returns `success: True` with partial failures. After Fix 2 (result validation), partial failures will be more visible, but the success semantics remain. **Revisit when**: business rules require strict all-or-nothing persist for tiled rasters.

### ARCHITECTURE WINS

1. **Fan-out temp file isolation is correct** (`handler_process_single_tile.py:133-137, 192`). Run-scoped directories + row/col naming + tile-specific `_task_id` ensures zero collisions between parallel tiles. Bug #16 fix is comprehensive.

2. **Deterministic STAC item IDs** (`services/raster/identifiers.py`). A single 3-line function shared by all raster handlers. Same inputs always produce the same ID. Clean implementation of Principle 2.

3. **Tiling scheme is stateless and deterministic** (`services/tiling_scheme.py`). Given the same raster metadata and tile parameters, the same tile grid is produced. No side effects. The GeoJSON output includes full metadata for downstream traceability.

4. **Tile bounds calculated from pixel windows** (`services/tiling_scheme.py:286-311`). Geographic bounds are derived mathematically from pixel coordinates and degrees-per-pixel, avoiding expensive per-tile coordinate transforms. Correct Y-axis inversion handling.

5. **Handler return contract is consistent** -- all three tiled handlers return `{"success": bool, "result": {...}}` with typed error information. Compliant with Constitution Standard 3.2.
