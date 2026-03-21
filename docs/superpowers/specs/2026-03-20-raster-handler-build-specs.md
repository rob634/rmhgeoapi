# AGENT M -- RESOLVER REPORT
# Raster ETL Handler Build Specifications (Handlers 1-5)

**Date**: 20 MAR 2026
**Inputs**: Agent P (Purist Design), Agent F (Behavior Preservation), Agent D (Diff Audit with Operator GATE1 Annotations)
**Scope**: `raster_download_source`, `raster_validate`, `raster_create_cog`, `raster_upload_cog`, `raster_persist_app_tables`
**Monolith**: `services/handler_process_raster_complete.py` function `process_raster_complete` (L1353-2369), single-COG path
**Supporting modules**: `services/raster_validation.py`, `services/raster_cog.py`, `services/stac_renders.py`

---

## 1. CONFLICTS RESOLVED

### CR-1: STAC Metadata Extraction -- Blob Read vs Upstream Assembly

**What P proposed**: `raster_persist_app_tables` assembles `stac_item_json` purely from upstream handler results received via DAG `receives`. The handler performs zero blob storage reads. P's boundary rule: "raster_persist_app_tables IS NOT responsible for: Any blob storage operations."

**What F defended**: The monolith's Phase 3 Step 1 (L1880-1889) calls `StacMetadataService.extract_item_from_blob()` which reads the COG blob from silver storage to produce `raster_bands`, `rescale_range`, `transform`, `resolution`. These fields are then written to `cog_metadata` (L1983-1987). F rates this CRITICAL (P2, P6) because without these fields, TiTiler lacks rendering parameters.

**Resolution**: ADOPT P's no-blob-read boundary. IMPLEMENT Infrastructure Context item 8: `raster_create_cog` extracts `raster_bands`, `rescale_range`, `transform`, and `resolution` from the output COG while rasterio is already open on the file. These flow forward via DAG `receives` to `raster_persist_app_tables`.

**Rationale**: The operator explicitly decided this (Infrastructure Context item 8): "Since raster_create_cog has rasterio open on the output COG already, it should extract these fields and return them in its result -- eliminating the blob read in persist_app_tables." This closes D's GAP-4 and satisfies F's P6 requirement without violating P's boundary.

**Tradeoff**: The STAC item JSON cached in `cog_metadata.stac_item_json` will be constructed by `raster_persist_app_tables` from discrete fields rather than extracted by a STAC service from the blob. The structure must match what `stac_materialize_item` expects. This is acceptable because pgSTAC is a materialized view rebuilt from internal state.

---

### CR-2: Error Return Shape -- `error_code` vs `error`

**What P proposed**: All handlers use `"error": "descriptive message"` and `"error_type": "TypedErrorName"` in failure returns.

**What F defended**: F verified (section 4.6) that the monolith uses inconsistent field names. Validation failures use `error_code` (L1584, L1601, L1631). COG failures use `error` (L1754, L1769). The outer exception handler uses `error` (L2353). F flagged this as an inconsistency that should be standardized.

**Resolution**: ADOPT P's standardization. All 5 handlers use:
```
"error": "Human-readable description"
"error_type": "TypedErrorName"
"retryable": bool
```
The field `error_code` is eliminated. This aligns with the Infrastructure Context handler contract (`handler(params) -> {"success": True/False, ...}`). This is a deliberate improvement, not a behavior loss.

**Tradeoff**: Any downstream consumer that parsed `error_code` from the monolith's return dict will need updating. Since these handlers replace the monolith entirely (strangler fig), there are no backward-compatibility concerns.

---

### CR-3: Non-Fatal Sub-Step Wrapping in raster_persist_app_tables

**What P proposed**: `raster_persist_app_tables` performs all database writes (cog_metadata upsert, render_config insert). P does not specify independent try/except per sub-step. P's contract implies any failure returns `{"success": false}`.

**What F defended**: F verified (section 3, P9) that the monolith wraps Phase 3a (cog_metadata upsert, L1901-2018), Phase 3b (render_config insert, L2021-2048), and Phase 3 Step 1 (STAC extraction, L1859-1894) each in independent try/except blocks. Each failure is logged as a warning but does NOT abort the handler. F flags R3 risk: converting non-fatal handling to fatal would cause the entire workflow to fail on a transient DB issue even though the COG exists in silver storage.

**Resolution**: PRESERVE non-fatal wrapping within `raster_persist_app_tables`. The handler has TWO sub-steps that are independently wrapped:

1. **cog_metadata upsert** -- try/except, failure logged as warning, sets `cog_metadata_upserted: false` in result
2. **render_config insert** -- try/except, failure logged as warning, sets `render_config_written: false` in result

The handler returns `{"success": true}` even if one or both sub-steps fail, because the COG exists in silver storage and is directly accessible. The result dict includes degradation flags so the workflow can detect incomplete persistence.

**Tradeoff**: A "successful" handler result may have incomplete database state. This matches the monolith's behavior and is intentional resilience -- the COG is the primary artifact, metadata is supplementary. The workflow can optionally retry the persist handler if degradation flags are set.

---

### CR-4: `stac_item_id` Generation -- Upload Handler vs Persist Handler

**What P proposed**: `raster_upload_cog` generates `cog_id` and `item_id` as deterministic hashes from `collection_id` + blob filename. These are passed to `raster_persist_app_tables` as inputs.

**What F defended**: F verified (section 2.1) that `stac_item_id` is computed at L1847-1851 in Phase 3 (persist), not Phase 2 (COG creation/upload). The derivation is `{collection_id}-{safe_name}` where `safe_name = cog_blob.replace('/', '-').replace('.', '-')`. F rates the consistency chain CRITICAL because this ID is used as primary key for cog_metadata, render_configs, and STAC items.

**Resolution**: ADOPT P's boundary (generate in upload, consume in persist) but USE F's derivation algorithm. `raster_upload_cog` computes `stac_item_id` using a shared utility function that implements the monolith's logic: `{collection_id}-{safe_name}`. The shared utility lives in `services/raster/identifiers.py` (per P's coupling warning 4.3). Both `raster_upload_cog` and `raster_persist_app_tables` import the same function. Tests verify determinism.

**Tradeoff**: Moving ID generation earlier to the upload handler means the upload handler must accept `collection_id` as a parameter (which it does in P's design). This is pure parameter passing. The alternative (generating in persist) would mean persist cannot construct `cog_url` without also knowing the blob path, which it already receives.

---

### CR-5: Mount Cleanup Ownership

**What P proposed**: `raster_upload_cog` deletes both the source file and the COG file from the ETL mount after successful upload. P returns `mount_cleanup: {source_deleted: bool, cog_deleted: bool}`.

**What F defended**: F notes the monolith has no mount files to clean up (it operates on blob URLs). This is a NEW behavior (D's NEW-2).

**Resolution**: ADOPT P's design. `raster_upload_cog` cleans up ONLY the files whose paths it received via `receives` (source_path and cog_path). It does NOT glob-delete the run directory. Cleanup failure is non-fatal -- logged as warning, cleanup status reported in result dict.

**Rationale**: Infrastructure Context item 5 states "Cleaned by finalize handler." However, for the 5-handler single-COG path, mount cleanup in the upload handler is sufficient because there are exactly 2 files to clean. The finalize handler is a broader concern for multi-file workflows. If a dedicated finalize handler is added later, `raster_upload_cog` can be configured to skip cleanup via a parameter.

**Tradeoff**: If `raster_upload_cog` fails after uploading but before cleanup, the files remain on mount. The DAG Brain's retry will re-run the handler, which will re-upload (idempotent due to deterministic blob path) and re-attempt cleanup. Worst case, the files persist until the Docker container recycles.

---

### CR-6: `raster_type` Data Shape -- String vs Dict

**What P proposed**: `raster_validate` returns `raster_type: str` (e.g., `"dem"`, `"imagery"`). `raster_create_cog` receives it as a string.

**What F defended**: F verified (C9) that the monolith passes the full `raster_type` dict from validation to `create_cog` (L1723). This dict contains `detected_type`, `optimal_cog_settings`, `band_count`, `data_type` -- all consumed by `create_cog` to select compression, resampling, and profile settings. F also verified (section 2.3) that `raster_type.detected_type`, `raster_type.band_count`, and `raster_type.data_type` are consumed by `raster_persist_app_tables` for cog_metadata and render_config.

**Resolution**: PRESERVE the dict shape. `raster_validate` returns `raster_type` as a dict with the full structure from `validate_raster_data`. `raster_create_cog` receives the full dict. `raster_persist_app_tables` receives `detected_type`, `band_count`, and `data_type` as individual fields extracted from the dict by the YAML `receives` mapping.

**Tradeoff**: The `raster_type` dict crosses the validate-to-create_cog boundary as a structured object rather than a flat string. This is acceptable because `create_cog` delegates to `raster_cog.py` which already expects this dict shape. Flattening it would require refactoring `raster_cog.py` for no functional benefit.

---

### CR-7: `cog_container` Fallback Logic

**What P proposed**: `raster_upload_cog` receives `container_name` as a required parameter specifying the silver target container.

**What F defended**: F verified (C4) that the monolith extracts `cog_container` from the COG creation result with a fallback: `cog_result.get('cog_container') or config.storage.silver.cogs` (L1763). The container can come from either the `create_cog` return or the app config.

**Resolution**: ADOPT P's boundary. The silver container is a job-level parameter, not computed by `create_cog`. The YAML workflow specifies `silver_container` in job params (e.g., `silver-cogs`). `raster_upload_cog` receives it directly. No fallback chain -- if the parameter is missing, the handler fails with a clear error.

**Rationale**: In the DAG architecture, configuration belongs in the workflow definition, not buried in handler fallback chains. The monolith's fallback existed because `create_cog` sometimes returned a container and sometimes did not. With the boundary split, `create_cog` no longer does uploads, so it has no container to return.

**Tradeoff**: The YAML workflow must explicitly specify `silver_container`. This is a desirable constraint -- it makes the workflow self-documenting.

---

### CR-8: Validation Output -- `bounds_4326` and `needs_reprojection`

**What P proposed**: `raster_validate` returns `bounds_4326`, `needs_reprojection`, and `target_crs` as pre-computed values.

**What F defended**: F notes the monolith does NOT compute `bounds_4326` or `needs_reprojection` in validation. Bounds come from the COG result (Phase 2). The reprojection decision is made inside `create_cog` by comparing source_crs to target_crs.

**Resolution**: SPLIT responsibilities:
- `raster_validate` returns `source_crs`, `source_bounds` (in the source CRS), and `needs_reprojection` (computed by comparing source_crs to target_crs from params).
- `raster_create_cog` returns `bounds_4326` (WGS84 bounds of the output COG, which may differ from source bounds after reprojection).
- `needs_reprojection` is a clean architectural improvement (D's NEW-3) -- it pre-computes a decision that the monolith makes implicitly inside `create_cog`.

**Tradeoff**: `raster_validate` must accept `target_crs` as a parameter to compute `needs_reprojection`. This is acceptable because the target CRS is a job parameter, not something derived during processing.

---

### CR-9: New Behaviors in raster_validate -- Tier Assessment, Bit Depth, Memory Estimation

**What P proposed**: `raster_validate` returns `cog_tiers` (compatible/recommended tier), `bit_depth_check` (efficiency recommendation), and `memory_estimation` (estimated MB).

**What F defended**: F found no evidence of these behaviors in the monolith. D classifies them as AMBIGUOUS (NEW-4, NEW-5, NEW-6).

**Resolution**: EXCLUDE all three from the initial handler build. These are speculative features with no monolith equivalent and no current consumer. They can be added as enrichments to `raster_validate` in a future iteration without breaking the handler contract (additive fields only).

**Tradeoff**: P's design is trimmed. The validate handler is simpler, faster, and focused on the behaviors that the monolith actually performs. Future enrichment is straightforward.

---

## 2. ESCALATED

### ESC-1: `validate_raster_header` Input Path Change (Blob URL vs Local Path)

**What F flagged**: F verified (V2) that the monolith passes `blob_url` (SAS URL) to `validate_raster_header` (L1570), not a local file path. The DAG handler will pass a local mount path instead. F notes that `raster_validation.py` already handles local paths (L266: `is_local_path = blob_url.startswith('/')`) but flags this as requiring testing.

**Why escalated**: This is not a design conflict -- both P and F agree on the local-path approach. But it is an untested code path in `raster_validation.py`. The `validate_raster_header` function's local-path branch may have bugs that were never exercised in production (the monolith always used SAS URLs).

**Operator decision needed**: Should the handler author (a) trust the existing local-path branch and test it during handler development, or (b) audit `raster_validation.py`'s local-path branch before starting handler development? Option (b) is safer but adds a pre-requisite task.

---

### ESC-2: `create_cog` Internal Upload Elimination

**What F flagged**: F verified (C1) that `raster_cog.py`'s `create_cog()` function handles BOTH the COG transformation AND the upload to silver blob storage in a single call. The disk-based path writes a local temp file, then uploads it.

**Why escalated**: Splitting into `raster_create_cog` (transform only) and `raster_upload_cog` (upload only) requires modifying `raster_cog.py` -- either (a) adding a mode parameter that skips the upload, (b) extracting the transform logic into a separate function, or (c) having `raster_create_cog` call `create_cog()` as-is and then having `raster_upload_cog` upload from the local temp file path (ignoring the blob that `create_cog` already uploaded).

**Operator decision needed**: Which approach? Option (b) is cleanest but requires refactoring `raster_cog.py`. Option (a) is minimal-change but makes the function's contract ambiguous. Option (c) wastes bandwidth (double upload) and leaves orphan blobs.

---

### ESC-3: `output_blob_name` Tier Suffix Convention

**What F flagged (section 4.4)**: F identified that `create_cog` in `raster_cog.py` (L600-606) appends a tier suffix to the output blob name (e.g., `sample.tif` becomes `sample_analysis.tif`). This naming convention affects the downstream blob path and the `stac_item_id` derivation.

**Why escalated**: If `raster_create_cog` produces a local file and `raster_upload_cog` constructs the silver blob path, the tier suffix logic must live in one of these two handlers. P's design does not mention tier suffixes. The suffix affects `stac_item_id` derivation because the `safe_name` is derived from `cog_blob` (which includes the suffix).

**Operator decision needed**: Does the tier suffix convention survive into the DAG architecture? If yes, which handler owns it? If no, what replaces it?

---

## 3. HANDLER BUILD SPECS

### 3.1 Handler: `raster_download_source`

**PURPOSE**: Stream a single blob from bronze blob storage to the Docker ETL mount, producing a local file path for downstream handlers.

**PARAMS**:

| Parameter | Type | Source | Required |
|---|---|---|---|
| `container_name` | str | job params | yes |
| `blob_name` | str | job params | yes |
| `etl_mount_path` | str | system config (`config.docker.etl_mount_path`) | no (default from config) |
| `_run_id` | str | system (DAG Brain) | yes (namespace isolation) |

**RETURNS** (success):
```
{
  "success": true,
  "result": {
    "source_path": "/mnt/etl/{_run_id}/{blob_name}",
    "file_size_bytes": int,
    "transfer_duration_seconds": float,
    "content_type": str
  }
}
```

**RETURNS** (failure):
```
{
  "success": false,
  "error": "Blob not found: {container_name}/{blob_name}",
  "error_type": "BlobNotFoundError",
  "retryable": true
}
```

**BEHAVIORS TO PORT** (from monolith):

| # | Behavior | Monolith Location | Notes |
|---|----------|-------------------|-------|
| D-B1 | Create `_run_id` subdirectory on ETL mount for namespace isolation | NEW (no monolith equivalent) | Monolith uses blob URLs, not local files. Docker mount pattern is architecturally new. |
| D-B2 | Stream blob bytes from bronze storage to local file | Phase 0.5 L1460 (`blob_repo.read_blob()`) downloads full blob for checksum. Conceptually similar but the monolith held bytes in memory; this handler streams to disk. | Delegate to `BlobRepository.for_zone('bronze')`. |
| D-B3 | Return file size for downstream logging/metrics | Phase 2 `cog_result.get('size_mb')` for the COG; source file size not tracked in monolith. | NEW metric, no monolith equivalent. |

**NEW BEHAVIORS**:

| # | Behavior | Rationale |
|---|----------|-----------|
| D-N1 | Path traversal guard: reject `blob_name` containing `..` or starting with `/` | Security hardening for Docker mount. Not needed in monolith (blob URLs cannot traverse). |
| D-N2 | ETL mount existence check before write | Docker mount may not be available. Monolith had no local filesystem dependency. |
| D-N3 | `_run_id` subdirectory creation with `os.makedirs(exist_ok=True)` | Idempotent directory creation for retry safety. |

**ERROR HANDLING**:

| Error Condition | error_type | retryable | Rationale |
|---|---|---|---|
| Blob not found in bronze | `BlobNotFoundError` | true | Transient storage issue or eventual consistency. |
| Storage auth failure | `StorageAuthError` | true | Managed identity token refresh. |
| ETL mount not available | `MountUnavailableError` | true | Docker mount may need remounting. |
| Path traversal in blob_name | `InvalidParameterError` | false | User error, will not self-resolve. |
| Disk write failure (full disk) | `DiskSpaceError` | true | May resolve after other jobs clean up. |

**SIDE EFFECTS**:
- Creates directory: `{etl_mount_path}/{_run_id}/`
- Creates file: `{etl_mount_path}/{_run_id}/{blob_name}`
- Reads blob: `BlobRepository.for_zone('bronze').read_blob(container_name, blob_name)`

**SUBTLE BEHAVIORS TO PRESERVE**: None from monolith (this handler is architecturally new).

**TESTING**:
- Unit: Mock `BlobRepository`, verify file creation on temp directory, verify path traversal rejection.
- Integration: Stage a test blob in bronze, run handler, verify file exists at expected path with correct size.
- Idempotency: Run handler twice with same params, verify no error on second run (file overwrite is acceptable).

---

### 3.2 Handler: `raster_validate`

**PURPOSE**: Perform header-level and data-level validation of a local raster file, returning structural metadata and a reprojection decision.

**PARAMS**:

| Parameter | Type | Source | Required |
|---|---|---|---|
| `source_path` | str | receives from `download.result.source_path` | yes |
| `blob_name` | str | job params (for validation function compatibility) | yes |
| `container_name` | str | job params (for validation function compatibility) | yes |
| `input_crs` | str | job params (user CRS override, e.g., `"EPSG:4326"`) | no |
| `target_crs` | str | job params (default `"EPSG:4326"`) | no (default EPSG:4326) |
| `raster_type` | str | job params (user override, e.g., `"dem"`) | no (default `"auto"`) |
| `strict_mode` | bool | job params | no (default false) |

**RETURNS** (success):
```
{
  "success": true,
  "result": {
    "source_crs": "EPSG:32637",
    "crs_source": "file_metadata",
    "target_crs": "EPSG:4326",
    "needs_reprojection": true,
    "nodata": -9999.0,
    "raster_type": {
      "detected_type": "dem",
      "band_count": 1,
      "data_type": "float32",
      "optimal_cog_settings": {...}
    },
    "source_bounds": [36.0, -1.0, 37.0, 0.0],
    "epsg": 32637,
    "file_size_bytes": 104857600
  }
}
```

**RETURNS** (failure -- missing CRS):
```
{
  "success": false,
  "error": "No CRS found in file metadata and no input_crs provided",
  "error_type": "CRSMissingError",
  "retryable": false,
  "user_fixable": true,
  "remediation": "Ensure the raster file has a CRS, or provide input_crs parameter."
}
```

**BEHAVIORS TO PORT** (from monolith):

| # | Behavior | Monolith Location | Notes |
|---|----------|-------------------|-------|
| V-B1 | Two-stage validation: header first (cheap), then data (GDAL stats) | L1577 (`validate_raster_header`), L1623 (`validate_raster_data`). Two separate calls, not one. Header catches garbage files before GDAL is invoked. | CRITICAL per F (V1). Delegate to existing `raster_validation.py` functions. |
| V-B2 | `validate_raster_data` receives `header_result` as second argument | L1623: `validate_raster_data(data_params, header_result)`. Header result provides context so data validation can skip redundant checks. | CRITICAL per F (section 6, incomplete item 2). Must preserve this coupling. |
| V-B3 | CRS extraction from header_result and None check | L1594-1609. `source_crs = header_result.get('source_crs')`. If None, return hard error with `user_fixable: True`. | CRITICAL per F (V3) and Infrastructure Context item 10. |
| V-B4 | `raster_type` user override passed to data validation | L1619: `params.get('raster_type', 'auto')` passed to `validate_raster_data`. Checked against auto-detection in `COMPATIBLE_OVERRIDES` hierarchy (raster_validation.py L71-79). | IMPORTANT per F (V5). |
| V-B5 | All validation failure returns set `retryable: False` | L1591, L1608, L1637. These are data quality issues. | IMPORTANT per F (V7). Per Infrastructure Context item 10, CRS-less rasters are `retryable: false, user_fixable: true`. |
| V-B6 | `validation_result` populated from `validation_response.get('result', {})` | L1640. The handler must return the full result dict from `validate_raster_data`. | IMPORTANT per F (V6). |

**NEW BEHAVIORS**:

| # | Behavior | Rationale |
|---|----------|-----------|
| V-N1 | Compute `needs_reprojection` by comparing `source_crs` to `target_crs` | D's NEW-3. Clean architectural improvement -- pre-computes a decision the monolith makes implicitly inside `create_cog`. |
| V-N2 | Return `crs_source: "file_metadata"` or `"user_override"` | Traceability for how CRS was determined. Not in monolith but aids debugging. |
| V-N3 | File existence check before opening with GDAL | Docker-specific guard. Monolith used blob URLs which either resolve or 404. |

**ERROR HANDLING**:

| Error Condition | error_type | retryable | Rationale |
|---|---|---|---|
| File not found at source_path | `FileNotFoundError` | false | Download handler should have produced it. Programming error. |
| source_path outside ETL mount | `SecurityError` | false | Path traversal attempt. |
| GDAL cannot open file (corrupt) | `RasterCorruptError` | false | User must provide uncorrupted file. |
| No CRS in file and no input_crs | `CRSMissingError` | false | Per Infrastructure Context item 10: HARD ERROR, user_fixable. |
| Header validation failure | `HeaderValidationError` | false | Data quality issue. |
| Data validation failure | `DataValidationError` | false | Data quality issue. |

**SIDE EFFECTS**: None. This handler is read-only. It reads the local file but writes nothing to disk or database.

**SUBTLE BEHAVIORS TO PRESERVE**:

| # | Behavior | Source | Notes |
|---|----------|--------|-------|
| V-S1 | ERH-2: validation never skips despite checkpoint | L1551-1556 | In DAG architecture, if validate node succeeds, it will not re-run on retry of a downstream node. This concern is eliminated by design (F V4). However, if the validate node itself is retried (e.g., transient GDAL error), it MUST re-run validation fully. No caching of validation results within the handler. |
| V-S2 | `input_crs` is used for blob_url (SAS URL) parameter in header_params | L1570-1574 | In DAG handler, `source_path` replaces `blob_url`. The `header_params` dict must use `blob_url: source_path` (local path) because `validate_raster_header` dispatches on `blob_url.startswith('/')` (raster_validation.py L266). See ESC-1. |
| V-S3 | Return shape must include `epsg` as integer | L1972: `crs=f"EPSG:{validation_result.get('epsg', 4326)}"`. The persist handler constructs CRS string from the integer. `raster_validation.py` returns `epsg` in header_result. |

**TESTING**:
- Unit: Test with local GeoTIFF files covering: valid single-band DEM, valid RGB imagery, CRS-less file (expect CRSMissingError), corrupt file (expect RasterCorruptError), CRS-less file with `input_crs` override (expect success).
- Integration: End-to-end with a file on mock ETL mount, verify all result fields populated.
- Regression: Verify `validate_raster_header` local-path branch produces identical results to blob-URL branch for the same file.

---

### 3.3 Handler: `raster_create_cog`

**PURPOSE**: Transform a local raster file into a Cloud-Optimized GeoTIFF on the ETL mount, applying reprojection and compression based on raster type. Extract STAC-relevant metadata from the output COG.

**PARAMS**:

| Parameter | Type | Source | Required |
|---|---|---|---|
| `source_path` | str | receives from `download.result.source_path` | yes |
| `raster_type` | dict | receives from `validate.result.raster_type` | yes |
| `source_crs` | str | receives from `validate.result.source_crs` | yes |
| `target_crs` | str | receives from `validate.result.target_crs` | yes |
| `needs_reprojection` | bool | receives from `validate.result.needs_reprojection` | yes |
| `nodata` | float/null | receives from `validate.result.nodata` | no |
| `output_tier` | str | job params (e.g., `"analysis"`) | no (default `"analysis"`) |
| `output_blob_name` | str | job params (custom output name) | no |
| `jpeg_quality` | int | job params | no (default from config) |
| `overview_resampling` | str | job params | no (default from config) |
| `reproject_resampling` | str | job params | no (default from config) |
| `_run_id` | str | system (DAG Brain) | yes |

**RETURNS** (success):
```
{
  "success": true,
  "result": {
    "cog_path": "/mnt/etl/{_run_id}/output.cog.tif",
    "cog_size_bytes": 52428800,
    "processing_time_seconds": 12.4,
    "compression": "DEFLATE",
    "resampling": "nearest",
    "tile_size": [512, 512],
    "overview_levels": [2, 4, 8, 16],
    "bounds_4326": [-70.7, -56.3, -70.6, -56.2],
    "shape": [10980, 10980],
    "raster_bands": [
      {"band": 1, "data_type": "float32", "nodata": -9999.0,
       "statistics": {"min": 0.0, "max": 5895.0, "mean": 1200.3, "stddev": 400.1}}
    ],
    "rescale_range": [0.0, 5895.0],
    "transform": [0.00009, 0.0, -70.7, 0.0, -0.00009, -56.2],
    "resolution": [0.00009, 0.00009],
    "file_checksum": "sha256:abc123...",
    "interleave": "BAND",
    "crs": "EPSG:4326"
  }
}
```

**RETURNS** (failure):
```
{
  "success": false,
  "error": "GDAL warp failed: insufficient disk space",
  "error_type": "COGCreationError",
  "retryable": false
}
```

**BEHAVIORS TO PORT** (from monolith):

| # | Behavior | Monolith Location | Notes |
|---|----------|-------------------|-------|
| C-B1 | Delegate COG transformation to `raster_cog.py` | L1716-1748. `create_cog(cog_params)` is the core call. | CRITICAL. The handler wraps the existing module; it does not reimplement COG creation. See ESC-2 for how to handle the upload-embedded-in-create_cog issue. |
| C-B2 | `in_memory` hardcoded to `False` for Docker path | L1729. Docker always uses disk-based processing. | IMPORTANT per F (C2). |
| C-B3 | Full `raster_type` dict passed to `create_cog` params | L1723: `'raster_type': validation_result.get('raster_type', {})`. The dict contains `detected_type`, `optimal_cog_settings`, `band_count`, `data_type`. | IMPORTANT per F (C9). See CR-6. |
| C-B4 | `output_blob` / `cog_blob` extraction with fallback | L1762: `cog_result.get('output_blob') or cog_result.get('cog_blob')`. Historical naming inconsistency. | IMPORTANT per F (C3). In the DAG handler, this becomes the local output file path, not a blob name. The fallback pattern may still be needed depending on `raster_cog.py`'s return shape. |
| C-B5 | COG creation failure and missing output path are separate error paths | L1750-1759 (creation failure), L1765-1774 (missing output path). Both must set `retryable`. | CRITICAL bug fix per F (C7, C8). Monolith omits `retryable` on these paths. |
| C-B6 | INTERLEAVE setting: PIXEL for jpeg/webp, BAND for others | raster_cog.py L734-737. Load-bearing TiTiler compatibility setting. | IMPORTANT per F (section 6, incomplete item 5). Preserved by delegating to `raster_cog.py`. |
| C-B7 | WarpedVRT pattern for disk-based reprojection | raster_cog.py L349-367. Disk-based path uses `rasterio.vrt.WarpedVRT`. | IMPORTANT per F (section 6, incomplete item 6). Preserved by delegating to `raster_cog.py`. |

**NEW BEHAVIORS**:

| # | Behavior | Rationale |
|---|----------|-----------|
| C-N1 | Extract `raster_bands` from output COG via rasterio | Infrastructure Context item 8. Eliminates the blob read in persist_app_tables. Read band metadata (dtype, nodata, statistics) from the open rasterio dataset after COG write. |
| C-N2 | Extract `transform` (6-element affine) from output COG | Infrastructure Context item 8. `dataset.transform` as 6-element list. |
| C-N3 | Compute `resolution` from transform | Infrastructure Context item 8. `[abs(transform[0]), abs(transform[4])]`. Monolith derives this in Phase 3 (L1958-1960). Moving it here. |
| C-N4 | Compute `rescale_range` from band statistics | Infrastructure Context item 8. `[min_val, max_val]` from the band statistics of band 1. Monolith gets this from STAC extraction; handler computes directly. |
| C-N5 | Compute `file_checksum` (SHA-256) of the output COG | D's GAP-9. Compute hash while the file is on local disk (fast). Returns as `"sha256:{hex_digest}"`. |
| C-N6 | Return `bounds_4326` from the reprojected output COG | Monolith gets this from `cog_result.get('bounds_4326')` which is already returned by `create_cog`. Handler passes it through. |

**ERROR HANDLING**:

| Error Condition | error_type | retryable | Rationale |
|---|---|---|---|
| Source file not found | `FileNotFoundError` | false | Download handler should have produced it. |
| Unknown `raster_type` | `InvalidParameterError` | false | User/config error. |
| GDAL/rasterio processing failure | `COGCreationError` | false | Same input will produce same failure. |
| Insufficient disk space | `DiskSpaceError` | true | May resolve after other jobs clean up. |
| Missing output file after create_cog | `COGCreationError` | false | create_cog completed but produced no output. |

**SIDE EFFECTS**:
- Creates file: COG on ETL mount at `{etl_mount_path}/{_run_id}/output.cog.tif`
- Reads file: `source_path` (input raster)
- May create temp files in `{etl_mount_path}/{_run_id}/` during GDAL processing

**SUBTLE BEHAVIORS TO PRESERVE**:

| # | Behavior | Source | Notes |
|---|----------|--------|-------|
| C-S1 | Tier suffix appended to output blob name | raster_cog.py L600-606 | F flagged this (section 4.4): `sample.tif` becomes `sample_analysis.tif`. The handler must decide whether to apply this suffix to the local output file name. See ESC-3. If the handler calls `create_cog()` as-is, the suffix is applied by the existing code. |
| C-S2 | `_task_id` passed to create_cog for temp file naming | L1730 | In DAG context, `_run_id` replaces `_task_id` for temp file namespace isolation. |
| C-S3 | Config defaults for `jpeg_quality`, `overview_resampling`, `reproject_resampling` | L1726-1728 | Defaults from `config.raster.*`. Handler should read config for defaults when job params do not specify. |

**TESTING**:
- Unit: Mock `create_cog`, verify parameter construction, verify metadata extraction from mock rasterio dataset, verify file_checksum computation.
- Integration: Use a small test GeoTIFF, run through full COG creation, verify output is valid COG (GDAL validate), verify all metadata fields populated.
- Metadata extraction: Verify `raster_bands`, `transform`, `resolution`, `rescale_range` match values that `StacMetadataService.extract_item_from_blob` would produce for the same COG. This is the key regression test for CR-1.
- Idempotency: Run twice with same params, verify identical output (deterministic COG + deterministic checksum).

---

### 3.4 Handler: `raster_upload_cog`

**PURPOSE**: Upload a COG file from the ETL mount to silver blob storage, generate deterministic identifiers, and clean up mount files.

**PARAMS**:

| Parameter | Type | Source | Required |
|---|---|---|---|
| `cog_path` | str | receives from `create_cog.result.cog_path` | yes |
| `source_path` | str | receives from `download.result.source_path` | yes |
| `container_name` | str | job params (silver target container) | yes |
| `blob_name` | str | job params (original source blob name) | yes |
| `collection_id` | str | job params | yes |
| `output_blob_name` | str | job params (custom output name) | no |

**RETURNS** (success):
```
{
  "success": true,
  "result": {
    "stac_item_id": "collection-name-safe-blob-name",
    "silver_container": "silver-cogs",
    "silver_blob_path": "cogs/collection_id/output_analysis.cog.tif",
    "cog_url": "/vsiaz/silver-cogs/cogs/collection_id/output_analysis.cog.tif",
    "cog_size_bytes": 52428800,
    "etag": "0x8DC...",
    "blob_version_id": "2026-03-20T...",
    "transfer_duration_seconds": 2.1,
    "mount_cleanup": {
      "source_deleted": true,
      "cog_deleted": true
    }
  }
}
```

**RETURNS** (failure):
```
{
  "success": false,
  "error": "Storage auth failed for silver zone",
  "error_type": "StorageAuthError",
  "retryable": true
}
```

**BEHAVIORS TO PORT** (from monolith):

| # | Behavior | Monolith Location | Notes |
|---|----------|-------------------|-------|
| U-B1 | Upload COG to silver blob storage | Embedded inside `create_cog()` (raster_cog.py). In the monolith, `create_cog` handles both transform + upload. The DAG handler owns the upload portion. | CRITICAL. Delegate to `BlobRepository.for_zone('silver')`. |
| U-B2 | `stac_item_id` derivation: `{collection_id}-{safe_name}` where `safe_name` replaces `/` with `-` and `.` with `-` | L1849-1851 (Phase 3 in monolith). Moved earlier to upload handler per CR-4. | CRITICAL per F (P1, section 2.1). Use shared utility function per Infrastructure Context item 7. |
| U-B3 | `cog_url` construction: `/vsiaz/{container}/{blob}` | L1908 (Phase 3 in monolith). Moved to upload handler since it has both container and blob path. | IMPORTANT per F (P7). |
| U-B4 | Validate COG blob exists in silver after upload | L1796-1813 (Phase 2 checkpoint validation). `blob_repo.blob_exists(cog_container, cog_blob)`. In monolith this was a checkpoint guard; in DAG this is a post-upload verification. | IMPORTANT per F (C6). |
| U-B5 | `blob_version_id` capture from Azure upload response | Phase 2 data flow. D's GAP-10 -- monolith captures this from `create_cog` result. | IMPORTANT. Capture from Azure SDK upload response. |

**NEW BEHAVIORS**:

| # | Behavior | Rationale |
|---|----------|-----------|
| U-N1 | Mount file cleanup: delete source_path and cog_path after successful upload | D's NEW-2. Docker-specific. See CR-5. |
| U-N2 | Post-upload blob existence verification | Adapted from monolith checkpoint validation (C6). Guards against silent upload failure. |
| U-N3 | Transfer throughput metrics | D's NEW-9. Compute bytes/second during upload. |

**ERROR HANDLING**:

| Error Condition | error_type | retryable | Rationale |
|---|---|---|---|
| COG file not found at cog_path | `FileNotFoundError` | false | create_cog handler should have produced it. |
| COG file is 0 bytes | `InvalidFileError` | false | create_cog produced empty output. |
| Storage auth failure | `StorageAuthError` | true | Managed identity token refresh. |
| Upload failure (network) | `UploadError` | true | Transient network issue. |
| Post-upload verification failed (blob not found) | `UploadVerificationError` | true | Eventual consistency or silent failure. |
| Mount cleanup failure | Non-fatal | n/a | Logged as warning. Does not affect success. |

**SIDE EFFECTS**:
- Writes blob: `BlobRepository.for_zone('silver').upload(container_name, silver_blob_path, cog_bytes)`
- Reads file: `cog_path` (local COG on mount)
- Deletes file: `source_path` (local source on mount) -- non-fatal if fails
- Deletes file: `cog_path` (local COG on mount) -- non-fatal if fails

**SUBTLE BEHAVIORS TO PRESERVE**:

| # | Behavior | Source | Notes |
|---|----------|--------|-------|
| U-S1 | `stac_item_id` derivation uses `cog_blob` (the silver blob path), NOT `blob_name` (the source blob name) | L1850: `safe_name = cog_blob.replace('/', '-').replace('.', '-')`. The `cog_blob` is the output path which may have a tier suffix appended. | CRITICAL. The `safe_name` input to ID derivation is the silver blob path (after any tier suffix), not the original source file name. This must match exactly or cog_metadata/render_config primary keys will not align with STAC item IDs. |
| U-S2 | Silver blob path construction: the handler must construct the destination blob path within the silver container | In monolith, `create_cog` handles this internally. Handler must replicate the path convention (e.g., `cogs/{collection_id}/{output_name}`). | The exact path convention depends on `raster_cog.py`'s logic. May need to be extracted as a shared utility. |

**TESTING**:
- Unit: Mock `BlobRepository`, verify upload called with correct container/path, verify `stac_item_id` derivation matches monolith logic for known inputs, verify cleanup attempts.
- Integration: Upload a test COG to a test container, verify blob exists, verify blob_version_id and etag populated.
- Idempotency: Upload same COG twice, verify no error (blob overwrite is idempotent), verify `stac_item_id` is identical.
- ID consistency: Verify `stac_item_id` produced by upload handler matches what `raster_persist_app_tables` would derive for the same inputs (use shared utility function).

---

### 3.5 Handler: `raster_persist_app_tables`

**PURPOSE**: Upsert one row into `app.cog_metadata` and one row into `app.raster_render_configs`, caching a constructed `stac_item_json` in the metadata row.

**PARAMS**:

| Parameter | Type | Source | Required |
|---|---|---|---|
| `stac_item_id` | str | receives from `upload.result.stac_item_id` | yes |
| `collection_id` | str | job params | yes |
| `silver_container` | str | receives from `upload.result.silver_container` | yes |
| `silver_blob_path` | str | receives from `upload.result.silver_blob_path` | yes |
| `cog_url` | str | receives from `upload.result.cog_url` | yes |
| `cog_size_bytes` | int | receives from `upload.result.cog_size_bytes` | yes |
| `etag` | str | receives from `upload.result.etag` | yes |
| `bounds_4326` | list[float] | receives from `create_cog.result.bounds_4326` | yes |
| `shape` | list[int] | receives from `create_cog.result.shape` | yes |
| `raster_bands` | list[dict] | receives from `create_cog.result.raster_bands` | yes |
| `rescale_range` | list[float] | receives from `create_cog.result.rescale_range` | yes |
| `transform` | list[float] | receives from `create_cog.result.transform` | yes |
| `resolution` | list[float] | receives from `create_cog.result.resolution` | yes |
| `crs` | str | receives from `create_cog.result.crs` | yes |
| `compression` | str | receives from `create_cog.result.compression` | yes |
| `tile_size` | list[int] | receives from `create_cog.result.tile_size` | yes |
| `overview_levels` | list[int] | receives from `create_cog.result.overview_levels` | yes |
| `file_checksum` | str | receives from `create_cog.result.file_checksum` | no |
| `detected_type` | str | receives from `validate.result.raster_type.detected_type` | yes |
| `band_count` | int | receives from `validate.result.raster_type.band_count` | yes |
| `data_type` | str | receives from `validate.result.raster_type.data_type` | yes |
| `nodata` | float/null | receives from `validate.result.nodata` | no |
| `source_crs` | str | receives from `validate.result.source_crs` | yes |
| `blob_name` | str | job params (source file for provenance) | yes |
| `job_id` | str | system `_run_id` | yes |
| `default_ramp` | str | job params (user color ramp preference) | no |

**RETURNS** (success):
```
{
  "success": true,
  "result": {
    "cog_metadata_upserted": true,
    "cog_id": "collection-name-safe-blob-name",
    "render_config_written": true,
    "render_id": "default",
    "stac_item_json_cached": true,
    "colormap": "terrain"
  }
}
```

**RETURNS** (success with degradation):
```
{
  "success": true,
  "result": {
    "cog_metadata_upserted": false,
    "cog_metadata_error": "Database connection timeout",
    "render_config_written": false,
    "render_config_error": "Relation does not exist",
    "stac_item_json_cached": false
  }
}
```

**RETURNS** (failure -- all sub-steps failed):
```
{
  "success": false,
  "error": "All database writes failed",
  "error_type": "DatabaseError",
  "retryable": true
}
```

**BEHAVIORS TO PORT** (from monolith):

| # | Behavior | Monolith Location | Notes |
|---|----------|-------------------|-------|
| P-B1 | `cog_metadata.upsert()` with ~25 fields | L1962-2001. Full field list: cog_id, container, blob_path, cog_url, width, height, band_count, dtype, nodata, crs, is_cog, bbox_minx/miny/maxx/maxy, compression, blocksize, overview_levels, transform, resolution, raster_bands, rescale_range, colormap, stac_item_id, stac_collection_id, etl_job_id, source_file, source_crs, custom_properties, stac_item_json. | CRITICAL per F (P5). |
| P-B2 | `recommend_colormap(detected_type)` for colormap field | L1925. Maps detected raster type to a visualization colormap. | IMPORTANT per F (section 6, incomplete item 3). Import from `services/stac_renders.py`. |
| P-B3 | `RasterRenderConfig.create_default_for_cog()` with dtype, band_count, nodata, detected_type, default_ramp | L2025-2031. Creates a render config from raster type info. | CRITICAL per F (P8) and Infrastructure Context item 9. render_config is NOT a dead write -- TiTiler consumes it. |
| P-B4 | `render_repo.create_from_model(render_config)` persists to `app.raster_render_configs` | L2033-2034. Database write. | CRITICAL per Infrastructure Context item 9. |
| P-B5 | `cog_url` constructed as `/vsiaz/{container}/{blob}` | L1908. GDAL virtual filesystem path for TiTiler. | IMPORTANT per F (P7). In DAG handler, receives this from upload handler (pre-constructed). |
| P-B6 | Spatial bounds extracted from `bounds_4326` into separate minx/miny/maxx/maxy fields | L1911-1915. `cog_bounds[0]` through `cog_bounds[3]`. | Must validate bounds list has exactly 4 elements. |
| P-B7 | Dimensions from `shape` into height/width | L1918-1920. `shape[0]` = height, `shape[1]` = width. | Must validate shape list has at least 2 elements. |
| P-B8 | `tile_size` to `blocksize` conversion | L1928-1929. `blocksize = tile_size if isinstance(tile_size, list) else None`. | Monolith checks list type; handler should pass through. |
| P-B9 | `stac_item_json` cached in cog_metadata row | L2000. The STAC item dict is the source of truth for pgSTAC rebuild. | CRITICAL per F (P5). Handler constructs the STAC JSON from its inputs. See CR-1. |
| P-B10 | Independent try/except for cog_metadata and render_config | L1901-2018 (cog_metadata), L2021-2048 (render_config). Each failure is non-fatal. | CRITICAL per CR-3. Preserve non-fatal wrapping. |
| P-B11 | ETL provenance fields: source_file, source_crs, etl_job_id | L1994-1996. Traceability columns. | IMPORTANT per F (P3) and P's section 6.3. |
| P-B12 | `custom_properties` with `raster_type` | L1998. `{'raster_type': detected_type}`. | Preserve for querying/filtering by raster type. |
| P-B13 | `crs` field constructed as `f"EPSG:{epsg}"` string | L1972. Uses `validation_result.get('epsg', 4326)`. In DAG handler, receives `crs` from create_cog result (already a string like `"EPSG:4326"`). | Handler receives `crs` directly; no construction needed. |

**NEW BEHAVIORS**:

| # | Behavior | Rationale |
|---|----------|-----------|
| P-N1 | Construct `stac_item_json` from discrete received fields instead of blob read | CR-1. Build the STAC item dict as a pure function of handler inputs. Structure must match what `stac_materialize_item` expects. |
| P-N2 | Return degradation flags when sub-steps fail | CR-3. `cog_metadata_upserted: false` and `render_config_written: false` with error messages. |

**ERROR HANDLING**:

| Error Condition | error_type | retryable | Rationale |
|---|---|---|---|
| cog_metadata upsert failure | Non-fatal within handler | n/a | Logged as warning. Sets `cog_metadata_upserted: false`. |
| render_config insert failure | Non-fatal within handler | n/a | Logged as warning. Sets `render_config_written: false`. |
| Both sub-steps fail | `DatabaseError` | true | Handler returns `success: false` only if ALL writes fail. |
| Missing required params | `InvalidParameterError` | false | Programming error in workflow wiring. |

**SIDE EFFECTS**:
- UPSERT into `app.cog_metadata` (1 row)
- INSERT into `app.raster_render_configs` (1 row)
- No blob operations, no file operations

**SUBTLE BEHAVIORS TO PRESERVE**:

| # | Behavior | Source | Notes |
|---|----------|--------|-------|
| P-S1 | `stac_item_id` is the primary key for BOTH cog_metadata AND render_configs | L1963, L2026 | Both tables use `cog_id=stac_item_id`. The value received from upload handler MUST be used for both writes. |
| P-S2 | `stac_item_json` is the rebuild source of truth | Memory note: "pgSTAC = materialized view" | The `stac_item_json` column in `cog_metadata` is the source from which `stac_materialize_item` rebuilds pgSTAC. The JSON structure must include: `id`, `type`, `geometry`, `bbox`, `properties` (with `proj:transform`, `proj:epsg`, `datetime`, `renders`), `assets.data` (with `raster:bands`, `href`). |
| P-S3 | render_config uses `detected_type` for colormap selection, not `raster_type` string | L2030 | The `detected_type` comes from the raster type dict's `detected_type` field, which may differ from the user-supplied `raster_type` param if auto-detection overrides. |
| P-S4 | `is_cog` hardcoded to `True` | L1973 | Always True for this handler since the input is always a COG. |

**TESTING**:
- Unit: Mock `RasterMetadataRepository` and `RasterRenderRepository`. Verify upsert called with all 25+ fields. Verify render_config created with correct dtype/band_count/nodata/detected_type. Verify stac_item_json structure.
- Degradation: Simulate cog_metadata failure, verify handler returns success with degradation flags. Simulate both failures, verify handler returns failure.
- STAC JSON validation: Verify constructed `stac_item_json` matches the structure produced by `StacMetadataService.extract_item_from_blob` for the same COG. This is the key regression test for CR-1.
- Idempotency: Run twice with same params, verify upsert is idempotent (no duplicate rows, updated timestamps).
- render_config: Verify `RasterRenderConfig.create_default_for_cog()` is called with correct params and result is persisted.

---

## 4. DEPENDENCY MAP

```
                    +----------------------+
                    | JOB PARAMS           |
                    | container_name       |
                    | blob_name            |
                    | collection_id        |
                    | target_crs           |
                    | raster_type (user)   |
                    | output_tier          |
                    +----------+-----------+
                               |
                               v
                 +----------------------------+
            +--->| 1. raster_download_source  |
            |    +----------------------------+
            |    | IN:  container_name,       |
            |    |      blob_name             |
            |    | OUT: source_path,          |
            |    |      file_size_bytes       |
            |    +-------------+--------------+
            |                  |
            |                  v
            |    +----------------------------+
            |    | 2. raster_validate         |
            |    +----------------------------+
            |    | IN:  source_path,          |
            |    |      blob_name,            |
            |    |      container_name,       |
            |    |      input_crs,            |
            |    |      target_crs,           |
            |    |      raster_type (user)    |
            |    | OUT: source_crs,           |
            |    |      needs_reprojection,   |
            |    |      raster_type (dict),   |
            |    |      nodata, epsg          |
            |    +-------------+--------------+
            |                  |
            |                  v
            |    +----------------------------+
            |    | 3. raster_create_cog       |
            |    +----------------------------+
            |    | IN:  source_path,          |
            |    |      raster_type (dict),   |
            |    |      source_crs,           |
            |    |      target_crs,           |
            |    |      needs_reprojection,   |
            |    |      nodata                |
            |    | OUT: cog_path,             |
            |    |      bounds_4326, shape,   |
            |    |      raster_bands,         |
            |    |      rescale_range,        |
            |    |      transform, resolution,|
            |    |      file_checksum,        |
            |    |      compression, tile_size|
            |    +-------------+--------------+
            |                  |
    source_path                v
    flows to     +----------------------------+
    upload too   | 4. raster_upload_cog       |
            |    +----------------------------+
            |    | IN:  cog_path,             |
            |    |      source_path,          |
            |    |      container_name,       |
            |    |      blob_name,            |
            |    |      collection_id         |
            |    | OUT: stac_item_id,         |
            |    |      silver_container,     |
            |    |      silver_blob_path,     |
            |    |      cog_url, etag,        |
            |    |      blob_version_id       |
            +--->+-------------+--------------+
                               |
                               v
                 +----------------------------+
                 | 5. raster_persist_app_tables|
                 +----------------------------+
                 | IN:  (receives from all    |
                 |       upstream handlers)   |
                 | OUT: cog_metadata_upserted,|
                 |      render_config_written,|
                 |      stac_item_json_cached |
                 +----------------------------+
```

**Data Flow Summary**:

| Source Handler | Target Handler | Fields Transferred |
|---|---|---|
| download -> validate | `source_path` |
| download -> create_cog | `source_path` |
| download -> upload | `source_path` (for cleanup) |
| validate -> create_cog | `raster_type` (dict), `source_crs`, `target_crs`, `needs_reprojection`, `nodata` |
| validate -> persist | `detected_type`, `band_count`, `data_type`, `nodata`, `source_crs`, `epsg` |
| create_cog -> upload | `cog_path` |
| create_cog -> persist | `bounds_4326`, `shape`, `raster_bands`, `rescale_range`, `transform`, `resolution`, `file_checksum`, `compression`, `tile_size`, `overview_levels`, `crs` |
| upload -> persist | `stac_item_id`, `silver_container`, `silver_blob_path`, `cog_url`, `cog_size_bytes`, `etag` |

**Execution Order**: Strictly sequential. 1 -> 2 -> 3 -> 4 -> 5. No parallelism within this 5-handler chain.

---

## 5. RISK REGISTER

### RISK-1: STAC JSON Structure Mismatch (HIGH)

**Risk**: The `stac_item_json` constructed by `raster_persist_app_tables` from discrete fields may not match the structure that `stac_materialize_item` expects, causing materialization failures or incorrect TiTiler rendering.

**Trigger**: Handler builds STAC JSON with wrong field names, missing nested structure, or incorrect property paths.

**Mitigation**: Write a dedicated test that:
1. Creates a COG via the old monolith path (which uses `StacMetadataService.extract_item_from_blob`)
2. Creates STAC JSON via the new handler path (from discrete fields)
3. Compares the two structures field-by-field
4. Verifies `stac_materialize_item` accepts both

**Residual risk**: Medium. The test will catch structural mismatches, but semantic differences (e.g., different `datetime` formatting) may still cause issues.

---

### RISK-2: `validate_raster_header` Local Path Branch Untested (MEDIUM)

**Risk**: The `validate_raster_header` function has a local-path branch (raster_validation.py L266: `is_local_path = blob_url.startswith('/')`) that has never been exercised in production. This branch may have bugs.

**Trigger**: Handler passes a local mount path instead of a SAS URL to `validate_raster_header`.

**Mitigation**: ESC-1 (escalated). Before handler development, audit the local-path branch in `raster_validation.py` and add unit tests for it.

**Residual risk**: Low after audit. The function likely works since rasterio handles local paths natively.

---

### RISK-3: `create_cog` Refactoring Scope (HIGH)

**Risk**: `raster_cog.py`'s `create_cog()` function combines COG transformation and blob upload in a single call. The DAG handler needs transform-only behavior. Refactoring this function could introduce regressions in the monolith (which still uses it during the strangler fig transition).

**Trigger**: ESC-2. Any approach to splitting create_cog affects both the new handler and the old monolith.

**Mitigation**: Option (a) is safest during transition -- add a `skip_upload: bool` parameter to `create_cog()` that defaults to `False`. The DAG handler passes `skip_upload=True`. The monolith continues to pass `False` (or nothing). This is a backward-compatible change that requires minimal refactoring.

**Residual risk**: Medium. The `skip_upload` flag adds conditional complexity to `create_cog`. After the strangler fig completes (v0.11.0), the upload code in `create_cog` can be removed entirely.

---

### RISK-4: `stac_item_id` Derivation Divergence (HIGH)

**Risk**: The `stac_item_id` is derived from `cog_blob` (the silver blob path), which depends on the tier suffix convention (ESC-3) and the silver blob path construction logic. If the upload handler constructs the blob path differently from `create_cog`'s internal logic, the ID will differ from historical records.

**Trigger**: Upload handler uses a different path convention than `create_cog` used in the monolith.

**Mitigation**: Extract the blob path construction logic and the `stac_item_id` derivation logic into shared utility functions. Unit test these functions with known inputs and expected outputs from the monolith.

**Residual risk**: Low after shared utility extraction.

---

### RISK-5: Metadata Extraction Equivalence (MEDIUM)

**Risk**: The monolith extracts `raster_bands`, `rescale_range`, `transform`, `resolution` from the STAC item dict, which itself is built by `StacMetadataService.extract_item_from_blob`. This extraction may include processing/formatting that raw rasterio metadata does not match. For example, `rescale_range` in the monolith comes from `renders.default.rescale[0]` in the STAC item, which is computed by the STAC service's rendering engine, not by raw band statistics.

**Trigger**: `raster_create_cog` extracts these fields directly from rasterio, producing different values than the STAC service would.

**Mitigation**: The regression test from RISK-1 covers this. Additionally, examine `StacMetadataService.extract_item_from_blob` to understand how it computes `rescale_range` and replicate that logic in the metadata extraction code within `raster_create_cog`.

**Residual risk**: Medium. Rescale range computation may require understanding TiTiler's rendering defaults.

---

### RISK-6: Non-Fatal Wrapping Hides Persistent Failures (LOW)

**Risk**: `raster_persist_app_tables` returns `success: true` even when database writes fail (CR-3). If the database has a persistent issue (not transient), the handler will keep "succeeding" with degraded results and no retry will fix it.

**Trigger**: Schema mismatch, missing table, or persistent connection issue.

**Mitigation**: The handler returns `success: false` if ALL sub-steps fail (both cog_metadata and render_config). For single-sub-step failures, the degradation flags in the result dict are visible to monitoring. A workflow-level health check can detect persistent degradation and alert.

**Residual risk**: Low. The monolith has the same behavior and it has not been a problem in practice.

---

### RISK-7: Mount Cleanup Timing (LOW)

**Risk**: `raster_upload_cog` cleans up mount files after upload. If the handler fails between upload-complete and cleanup, files remain on disk. If the handler is retried, it will re-upload (idempotent) and re-attempt cleanup.

**Trigger**: Handler crash or timeout between upload and cleanup.

**Mitigation**: Cleanup failure is non-fatal. Docker container recycling provides a backstop. For persistent cleanup failures, the finalize handler (Infrastructure Context item 5) can be added as a workflow-level cleanup step.

**Residual risk**: Low. Disk usage accumulates slowly and Docker containers recycle.

---

## 6. ORPHAN DISPOSITION

All orphaned behaviors identified by Agent D are accounted for below. Each is mapped to its resolution.

| Orphan | D's ID | Resolution | Handler Owner |
|---|---|---|---|
| Release status management | ORPHAN-1 | DEFERRED. Workflow orchestration concern. DAG Brain or YAML workflow hooks. Not in scope for these 5 handlers. | None (orchestrator) |
| Source checksum computation | ORPHAN-2 | DEFERRED per Infrastructure Context item 11. Not in scope. | None |
| Overwrite detection / early-exit | ORPHAN-3 | DEFERRED per Infrastructure Context item 11. Future conditional node. | None |
| Checkpoint manager | ORPHAN-4 | ELIMINATED by design. DAG Brain retries at node level. | None |
| Artifact registry creation | ORPHAN-5 | DEFERRED per Infrastructure Context item 11. Future composable handler. | None |
| Old COG deletion on overwrite | ORPHAN-6 | DEFERRED per Infrastructure Context item 11. Tied to ORPHAN-3. | None |
| Phase 4 STAC deferred/Release caching | ORPHAN-7 | DEFERRED. Release caching is part of Release lifecycle (ORPHAN-1). STAC materialization is `stac_materialize_item` (separate handler). | None |
| Job event emissions | ORPHAN-8 | DEFERRED. Cross-cutting concern. DAG Brain can emit events on task transitions. Sub-step events (within handlers) are not preserved. | None (orchestrator) |
| Memory tracking / resource stats | ORPHAN-9 | DEFERRED. Docker worker concern, not handler concern. Per D: "likely INTENTIONALLY ELIMINATED." | None |
| Graceful shutdown checks | ORPHAN-10 | ELIMINATED by design. Docker worker checks between handler invocations. Handlers are short-lived. | None |
| Progress reporting | ORPHAN-11 | ELIMINATED by design. DAG Brain infers progress from task state transitions. | None |
| `is_platform_job` conditional logic | ORPHAN-12 | DEFERRED. Future conditional node in YAML workflow. | None |
| ProvenanceProperties construction | ORPHAN-13 | ABSORBED into `raster_persist_app_tables` per P section 6.3. ETL provenance fields (source_file, source_crs, etl_job_id) written directly. | raster_persist_app_tables (P-B11) |
| PlatformProperties construction | ORPHAN-14 | DEFERRED. Future enrichment to persist handler or separate handler. | None |

**Accounting check**: 14 orphans from D. 1 absorbed (ORPHAN-13 -> P-B11). 4 eliminated by design (ORPHAN-4, ORPHAN-10, ORPHAN-11). 9 deferred (ORPHAN-1, 2, 3, 5, 6, 7, 8, 9, 12, 14). All accounted for.

---

## 7. F-BEHAVIOR COVERAGE CHECK

Every behavior from Agent F's analysis is mapped to exactly one handler's BEHAVIORS TO PORT or explicitly deferred.

| F ID | F Description | Handler | Build Spec ID |
|---|---|---|---|
| V1 | Two-stage header+data validation | raster_validate | V-B1 |
| V2 | blob_url vs local path in header_params | raster_validate | V-S2 (subtle) + ESC-1 |
| V3 | source_crs None check with user_fixable error | raster_validate | V-B3 |
| V4 | ERH-2: validation never skips | raster_validate | V-S1 (eliminated by design) |
| V5 | raster_type user override | raster_validate | V-B4 |
| V6 | validation_result from response.result | raster_validate | V-B6 |
| V7 | All validation failures retryable:false | raster_validate | V-B5 |
| C1 | create_cog combines transform+upload | raster_create_cog + raster_upload_cog | C-B1 + ESC-2 |
| C2 | in_memory=False for Docker | raster_create_cog | C-B2 |
| C3 | output_blob/cog_blob fallback | raster_create_cog | C-B4 |
| C4 | cog_container fallback | raster_upload_cog | CR-7 (eliminated) |
| C5 | Peak memory tracking wraps COG creation | DEFERRED | ORPHAN-9 |
| C6 | Checkpoint validates COG exists | raster_upload_cog | U-B4 |
| C7 | COG failure missing retryable (BUG) | raster_create_cog | C-B5 (fixed) |
| C8 | Missing output path missing retryable (BUG) | raster_create_cog | C-B5 (fixed) |
| C9 | raster_type dict passed to create_cog | raster_create_cog | C-B3, CR-6 |
| P1 | stac_item_id deterministic derivation | raster_upload_cog | U-B2, CR-4 |
| P2 | STAC extraction reads COG blob | raster_create_cog | CR-1, C-N1 through C-N4 |
| P3 | ProvenanceProperties construction | raster_persist_app_tables | P-B11 |
| P4 | PlatformProperties (DDH fields) | DEFERRED | ORPHAN-14 |
| P5 | cog_metadata.upsert ~25 fields + stac_item_json | raster_persist_app_tables | P-B1, P-B9 |
| P6 | raster_bands/rescale/transform/resolution from STAC | raster_create_cog -> raster_persist_app_tables | CR-1, C-N1 through C-N4 |
| P7 | cog_url as /vsiaz/ path | raster_upload_cog | U-B3 |
| P8 | RasterRenderConfig.create_default_for_cog | raster_persist_app_tables | P-B3, P-B4 |
| P9 | Independent try/except per sub-step | raster_persist_app_tables | P-B10, CR-3 |
| P10 | recommend_colormap() | raster_persist_app_tables | P-B2 |
| S1 | No pgSTAC write | ALL handlers | None write to pgSTAC. Confirmed. |
| S2 | Release STAC JSON cache | DEFERRED | ORPHAN-7 |
| S3 | Release blob_path update | DEFERRED | ORPHAN-1 |
| S4 | stac_result degraded flag | raster_persist_app_tables | P-N2 (degradation flags) |
| F 4.1 | render_config NOT a dead write | raster_persist_app_tables | P-B3, P-B4, Infrastructure Context item 9 |
| F 4.2 | Redundant get_config() | ELIMINATED | Each handler gets its own config. No redundancy. |
| F 4.3 | _emit_job_event stage=1 | DEFERRED | ORPHAN-8 |
| F 4.4 | Source checksum downloads entire blob | DEFERRED | ORPHAN-2 |
| F 4.5 | ERH-2 validation never skips | raster_validate | V-S1 (eliminated by design) |
| F 4.6 | error_code vs error inconsistency | ALL handlers | CR-2 (standardized) |
| F 4.7 | Release error truncation str(e)[:500] | DEFERRED | ORPHAN-1 |
| F 6 incomplete 2 | validate_raster_data takes header_result | raster_validate | V-B2 |
| F 6 incomplete 3 | recommend_colormap() | raster_persist_app_tables | P-B2 |
| F 6 incomplete 4 | Tier suffix on output blob name | raster_create_cog / raster_upload_cog | ESC-3 |
| F 6 incomplete 5 | INTERLEAVE setting | raster_create_cog | C-B6 |
| F 6 incomplete 6 | WarpedVRT pattern | raster_create_cog | C-B7 |

**Coverage**: All 41 F-identified behaviors are mapped. 0 unaccounted.
