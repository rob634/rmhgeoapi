# AGENT M -- RESOLVER REPORT
# Vector ETL Handler Build Specifications (Handlers 1-3)

**Date**: 19 MAR 2026
**Inputs**: Agent P (Purist Design), Agent F (Behavior Preservation), Agent D (Diff Audit with Operator GATE1 Annotations)
**Scope**: `vector_load_source`, `vector_validate_and_clean`, `vector_create_and_load_tables`
**Out of scope**: Nodes 4-6 (`vector_create_split_views`, `vector_register_catalog`, `vector_refresh_tipg`) -- already built and deployed per Infrastructure Context item 6.

---

## 1. CONFLICTS RESOLVED

### CR-1: CRS-Less Data -- Reject vs Silent Assignment

**What P proposed**: `vector_validate_and_clean` raises `CRSMissingError` when source data has no CRS. P treats this as a data quality gate -- the handler refuses to guess.

**What F defended**: The monolith silently assigns EPSG:4326 to CRS-less data (postgis_handler L625-627: `gdf = gdf.set_crs("EPSG:4326")`). F verified this is the actual behavior (F section V-2), correcting R's ambiguity. F rates this CRITICAL (H2-B10) because CRS-less CSV files with lat/lon columns are the most common ingest case.

**Resolution**: PRESERVE the monolith behavior. Assign EPSG:4326 with a warning. P's `CRSMissingError` is rejected.

**Rationale**: The Infrastructure Context item 8 explicitly flags this as a common use case (CRS-less CSV files) and frames it as a behavior change decision. The monolith works. Rejecting CRS-less data would break the most common CSV ingest workflow. The handler MUST log a warning ("No CRS defined, assuming EPSG:4326") and include this warning in the `warnings` list in the result dict, but MUST NOT fail.

**Tradeoff**: Users who upload data in a non-4326 CRS without CRS metadata will get silently incorrect spatial data. This is the same tradeoff the monolith accepts. Adding a `default_crs` parameter to `processing_options` is a future enhancement that could make this explicit without breaking existing workflows.

---

### CR-2: `load_info` Metadata Propagation -- Eliminate vs Preserve

**What P proposed**: Eliminate the `load_info` dict as shared state. Each handler produces only specific named fields in its result. No monolithic metadata bag crosses handler boundaries. P's `vector_load_source` result includes `crs_raw`, `row_count`, `file_extension`, `source_size_bytes`, `column_count`, `geometry_column`.

**What F defended**: `load_info` carries `original_crs`, `file_size_mb`, `feature_count`, `columns`, and `source` (F section C-4, H1-B12). These are consumed by `register_table_metadata` at handler L676-678 for catalog population. Missing fields cause KeyErrors or missing metadata in `geo.table_catalog`.

**Resolution**: ADOPT P's decomposition but ensure all F's required fields are covered. P's result shape already includes equivalents for all `load_info` fields:

| `load_info` field | P's result field | Notes |
|---|---|---|
| `original_crs` | `crs_raw` | Same data, different name. Acceptable. |
| `file_size_mb` | `source_size_bytes` | Different unit. Node 5 can convert. |
| `feature_count` | `row_count` | Same semantics at load time. |
| `columns` | `column_count` | P returns count, not names. **GAP -- see below.** |
| `source` | Not in P's result | Source filename/path. **GAP -- see below.** |

**Gaps to fill**: `vector_load_source` result must ALSO include:
- `columns: list[str]` -- column names (not just count), because `vector_register_catalog` (node 5) needs them for catalog metadata.
- `source_file: str` -- the original blob name, needed for catalog metadata `source_file` field.

**Tradeoff**: P's boundary is preserved (no `load_info` dict crosses), but the result shape is slightly larger than P designed. This is pure parameter passing, not coupling -- each field is independently consumable.

---

### CR-3: Column Mapping vs Column Sanitization -- Two Operations

**What P proposed**: `vector_validate_and_clean` performs "column sanitization" -- automatic fixing of problematic names (lowercase, special chars, reserved words). P treats this as a single operation.

**What F defended**: F verified (section V-3) that the monolith has TWO distinct column operations:
1. **Column mapping** (handler L566-572, core.py L335-378): User-specified rename rules from `parameters.get('column_mapping')`, applied BEFORE validation. Example: `{'OLD_NAME': 'new_name'}`.
2. **Column sanitization** (postgis_handler L639-641): Automatic cleanup via `sanitize_columns()`, applied AFTER validation but BEFORE geometry type split.

**Resolution**: PRESERVE both operations in `vector_validate_and_clean`. They execute in sequence: user mapping first (respecting user intent), then automatic sanitization (ensuring PostgreSQL compatibility).

**Tradeoff**: `vector_validate_and_clean` accepts an additional `column_mapping` parameter in `processing_options`. This slightly increases the handler's scope beyond what P designed, but both operations are logically "prepare columns for PostGIS" and belong together. Separating them into two handlers would require an additional GeoParquet serialization round-trip for no functional benefit.

---

### CR-4: Single Connection vs Handler-Owned Connection

**What P proposed**: Each handler opens and closes its own database connection. No connection crosses handler boundaries. This is architecturally correct for the DAG model.

**What F defended**: The monolith uses a single connection spanning Phases 2-4 (handler L942 through L1137). F warns (C-1, S-4) that the per-chunk `conn.commit()` pattern within `insert_chunk_idempotent` is load-bearing: each chunk is independently committed so that retries only redo the failed chunk, not all preceding chunks.

**Resolution**: ADOPT P's handler-owned connection, but MANDATE per-chunk commit. `vector_create_and_load_tables` opens one connection, holds it for the entire handler execution (DDL, all chunks, indexes, ANALYZE, verification), and commits after each chunk's DELETE+INSERT. This preserves F's per-chunk idempotency guarantee within P's handler boundary model.

**Tradeoff**: The connection is held longer than strictly necessary (through index creation and verification), but this matches the monolith's pattern. Opening a second connection for verification would add complexity with no benefit. The key constraint is: each chunk MUST be committed independently, not wrapped in a single transaction.

---

### CR-5: NaT-to-None Conversion -- Where Does It Live?

**What P proposed**: P does not explicitly address NaT-to-None conversion in `vector_create_and_load_tables`. P's handler trusts its input from `vector_validate_and_clean`.

**What F defended**: F discovered (S-1, R-2) that `insert_chunk_idempotent` does NOT perform NaT-to-None conversion (postgis_handler L1779-1785 uses raw `row[col]`), unlike `_insert_features` (L1217-1227). The protection relies ENTIRELY on `prepare_gdf` (in validate_and_clean) having already sanitized datetime columns. If data bypasses validation and reaches insert directly, NaT values write year ~48113 to PostgreSQL, corrupting the table for all future reads.

**Resolution**: IMPLEMENT NaT-to-None conversion in BOTH handlers as defense-in-depth:
1. `vector_validate_and_clean` MUST sanitize datetime columns (H2-B8): detect NaT and out-of-range years, convert to None, prune all-NaT columns. This is the primary defense.
2. `vector_create_and_load_tables` MUST perform NaT-to-None conversion during INSERT (in the value-building loop for each row). This is the secondary defense and fixes a latent bug in the monolith.

**Tradeoff**: Redundant conversion in handler 3. This costs negligible CPU (one `is pd.NaT` check per value per row) but provides defense-in-depth against a CRITICAL data corruption bug. P's "trust the boundary" principle is relaxed here because the consequence of a single missed NaT is catastrophic (table permanently unreadable).

---

### CR-6: Reserved Column Filtering -- Dual Check

**What P proposed**: `vector_validate_and_clean` sanitizes columns. `vector_create_and_load_tables` trusts the input.

**What F defended**: F identified (C-5, H2-B16) that BOTH the validation step AND the DDL step check for reserved columns (`id`, `geom`, `geometry`, `etl_batch_id`). Validation removes them from the GeoDataFrame. DDL skips them when building column definitions. If either check is missing, the `id` column collision causes `"column specified more than once"` SQL error.

**Resolution**: PRESERVE dual check. `vector_validate_and_clean` removes reserved columns from the GeoDataFrame and the GeoParquet output (primary defense). `vector_create_and_load_tables` skips reserved column names when building the CREATE TABLE DDL (secondary defense). The reserved column list MUST be identical in both handlers.

**Tradeoff**: Same as CR-5 -- redundant check, negligible cost, prevents a hard SQL error if data bypasses validation.

---

### CR-7: `is_split` Flag Derivation

**What P proposed**: `vector_create_and_load_tables` receives `geometry_groups` (a list of 1-3 entries) and determines table naming from the list length.

**What F defended**: F identified (S-6) that `is_split = len(prepared_groups) > 1` drives five downstream behaviors: table naming suffix, table_group catalog update, result shape, geometry_type reporting, and table_role classification.

**Resolution**: ADOPT P's approach. `is_split` is derived from `len(geometry_groups) > 1` inside `vector_create_and_load_tables`. This is equivalent to the monolith's derivation but uses the handler's input rather than a shared variable. The five downstream behaviors are all internal to handler 3 and node 5 (catalog registration).

**Tradeoff**: None. P's approach produces identical behavior through parameter passing instead of shared state.

---

### CR-8: Progress Logging Granularity

**What P proposed**: P acknowledges progress logging (O-8) but does not specify the implementation detail.

**What F defended**: F requires (H3-B15) logging at 25/50/75/100% milestones with rows/sec throughput rate. This is operationally important for uploads taking 30+ minutes.

**Resolution**: PRESERVE F's milestone logging. `vector_create_and_load_tables` MUST log at 25%, 50%, 75%, and 100% completion milestones. Each log entry includes: milestone percentage, rows uploaded so far, total rows expected, elapsed time, and rows/sec throughput rate.

**Tradeoff**: None. This is pure logging with no architectural impact.

---

### CR-9: Error Enrichment -- Handler vs Infrastructure

**What P proposed**: P defers error enrichment (O-16) to a handler wrapper in infrastructure. Each handler returns basic `error` and `error_type` strings.

**What F defended**: The monolith has rich error mapping (`_map_exception_to_error_code()` at L1255-1337) and remediation text (`_get_vector_remediation()` at L1340-1448) that provide user-facing guidance.

**Resolution**: Each handler returns structured errors with `error_type` classification per P's design. The full ErrorCode taxonomy and remediation text generation are DEFERRED to infrastructure (a handler wrapper or DAG-level error enrichment). Handlers provide enough context in `error` and `error_type` for the wrapper to map to rich remediation.

**Tradeoff**: First deployment will have less rich error messages than the monolith. The error wrapper can be built incrementally. The key fields (`error_type` classification like `ValidationError`, `UnsupportedFormatError`, `TableExistsError`) are sufficient for programmatic error handling.

---

### CR-10: Mount Writability Probe

**What P proposed**: P does not explicitly mention the write-probe test.

**What F defended**: F requires (H1-B2, IMPORTANT) a mount writability probe: create `.write-test` file, write `"ok"`, then delete it. Without this, a read-only mount fails later during blob streaming with a confusing permission error.

**Resolution**: PRESERVE the writability probe. `vector_load_source` MUST test mount writability before attempting blob streaming. This is a fast, clear diagnostic that prevents confusing downstream errors.

**Tradeoff**: Adds ~1ms of I/O before the real work begins. Negligible cost for clear error messaging.

---

### CR-11: Geometry Type Detection from First Feature

**What P proposed**: P's design trusts the `geometry_type` field from `geometry_groups` entries.

**What F defended**: F identified (S-5) that the monolith determines PostGIS geometry type by sampling the first feature (`gdf.geometry.iloc[0].geom_type.upper()`). This works ONLY because multi-type normalization (H2-B5) and geometry type split (H2-B13) guarantee all rows in a group have the same type.

**Resolution**: ADOPT P's approach with F's precondition. `vector_create_and_load_tables` uses the `geometry_type` string from `geometry_groups` to declare the PostGIS column type (mapping `"polygon"` to `MULTIPOLYGON`, `"line"` to `MULTILINESTRING`, `"point"` to `MULTIPOINT`). It does NOT sample the first feature. This is cleaner and produces identical results because `vector_validate_and_clean` guarantees type uniformity. The mapping is:

| `geometry_type` value | PostGIS column type |
|---|---|
| `"polygon"` | `GEOMETRY(MULTIPOLYGON, 4326)` |
| `"line"` | `GEOMETRY(MULTILINESTRING, 4326)` |
| `"point"` | `GEOMETRY(MULTIPOINT, 4326)` |

**Tradeoff**: Handler 3 no longer independently verifies type uniformity -- it trusts handler 2's guarantee. This is acceptable because handler 2 is the authority on geometry processing.

---

### CR-12: Overwrite Semantics and Split View Metadata Cleanup

**What P proposed**: P specifies `DROP TABLE CASCADE` when `overwrite=true` and `TableExistsError` when `overwrite=false`.

**What F defended**: F requires (H3-B3, R-8) that the overwrite path also calls `cleanup_split_view_metadata()` to remove stale catalog entries for old views. Without this, `DROP CASCADE` removes the views but stale catalog entries persist, causing 404 errors in the map UI.

**Resolution**: PRESERVE F's cleanup. When `overwrite=true` and the table exists, `vector_create_and_load_tables` MUST:
1. Call `cleanup_split_view_metadata(table_name, schema_name)` to remove stale catalog entries.
2. Execute `DROP TABLE IF EXISTS {schema}.{table} CASCADE`.
3. Proceed with table creation.

This must happen for EACH table in `geometry_groups` (e.g., `my_data_polygon`, `my_data_line`).

**Tradeoff**: Handler 3 has a catalog-cleaning side effect during overwrite that P would prefer in node 5. However, the cleanup MUST happen BEFORE the DROP, and the DROP MUST happen BEFORE CREATE. This ordering constraint requires the cleanup to live in handler 3. Node 5 registers new entries; handler 3 cleans old ones during overwrite.

---

## 2. ESCALATED

### ESC-1: Style Creation Timing and Ownership

**What P wants**: OGC style creation (O-12) is DEFERRED to a separate future node. Not a handler 1-3 concern.

**What F wants**: Style creation (H3-B17 vicinity, handler L705-751) is non-fatal but HIGH severity. Without a default style, OGC clients render unstyled data. F argues this is a visible user-facing regression.

**Why I cannot resolve**: The Infrastructure Context lists nodes 4-6 as already built. Style creation is not in any of them. Creating a new node 7 is a workflow design decision (adds YAML complexity, but clean separation). Putting it in node 5 (`vector_register_catalog`) changes that handler's scope. Deferring it means the first deployment has no styles.

**Option A**: Add style creation to `vector_register_catalog` (node 5). Node 5 already handles catalog metadata and accepts a `style` parameter via workflow params. Pro: no new node. Con: node 5 scope creep.

**Option B**: Create a new `vector_create_default_style` node (node 7), non-fatal, running after node 5. Pro: clean separation, failure does not block workflow. Con: additional YAML node, additional handler to build.

**Option C**: Defer entirely. First deployment has no OGC styles. Add later. Pro: smaller scope for initial build. Con: visible regression from monolith behavior.

**Operator must decide**: Which option, and if A or B, whether the `style` parameter (custom fill/stroke colors) should be accepted.

---

### ESC-2: `feature_count` Update Ownership

**What P wants**: Feature count update in `table_catalog` belongs to `vector_register_catalog` (node 5), receiving the verified row count from handler 3's result.

**What F wants**: F requires (H3-B11) that when the DB row count differs from the GDF length, `table_catalog.feature_count` is updated. The monolith does this inside the same connection that performed the row count cross-check.

**Why I cannot resolve**: Node 5 (`vector_register_catalog`) is already built and deployed. Its current contract accepts a `tables_info` list. If it already sets `feature_count` during registration, then handler 3 just needs to pass the verified count. If it does NOT currently set `feature_count`, then either node 5 needs modification or handler 3 must do it.

**Option A**: Handler 3 passes `row_count` (the verified DB count) in its result. Node 5 uses that count when registering. Requires verifying node 5's current behavior.

**Option B**: Handler 3 sets `feature_count` directly via SQL UPDATE after its row count cross-check. Duplicates catalog-writing responsibility between handler 3 and node 5.

**Operator must decide**: Does node 5 already handle `feature_count`? If yes, Option A. If no, should node 5 be modified (preferred) or should handler 3 do it (expedient)?

---

### ESC-3: Validation Events to `job_events` Table

**What P wants**: Validation events (O-3) are DEFERRED to DAG infrastructure, not a handler concern.

**What F wants**: F rates validation events as IMPORTANT (H1-B13). The swimlane UI uses these events for progress visibility. Without them, users lose insight into download and validation stages.

**Why I cannot resolve**: This depends on whether the DAG infrastructure currently supports event emission from handlers. The Infrastructure Context does not document a handler event emission mechanism. If no mechanism exists, events are silently lost until infrastructure catches up.

**Option A**: `vector_validate_and_clean` emits events to the `job_events` table directly (adds a DB write side-effect to an otherwise pure-transformation handler).

**Option B**: Events are logged as structured log entries. A future log-to-events pipeline ingests them. Swimlane UI is temporarily degraded.

**Option C**: Skip events for handlers 1-3. The DAG's `workflow_tasks` table already tracks task start/complete timestamps, providing coarse progress visibility.

**Operator must decide**: Is swimlane UI visibility critical enough to add a DB side-effect to the validation handler?

---

## 3. HANDLER BUILD SPECS

### HANDLER: `vector_load_source`

**PURPOSE**: Stream a blob from bronze storage to the ETL mount, convert format-specific files to GeoDataFrame, persist as GeoParquet for downstream consumption.

**PARAMS**:

| Name | Type | Required | Default | Source |
|---|---|---|---|---|
| `blob_name` | `str` | yes | -- | workflow param |
| `container_name` | `str` | yes | -- | workflow param |
| `file_extension` | `str` | yes | -- | workflow param, normalized lowercase |
| `job_id` | `str` | yes | -- | workflow param (MUST be required, never default to `'unknown'`) |
| `processing_options` | `dict` | no | `{}` | workflow param |
| `_run_id` | `str` | yes | -- | system-injected |
| `_node_name` | `str` | yes | -- | system-injected |

Keys consumed from `processing_options`:
- `lat_name` (str): CSV latitude column name
- `lon_name` (str): CSV longitude column name
- `wkt_column` (str): CSV WKT geometry column name
- `layer_name` (str): GPKG layer to load

The handler MUST NOT read any other keys from `processing_options`.

**RETURNS (success)**:
```
{
    "success": true,
    "result": {
        "intermediate_path": str,       # Absolute path to GeoParquet on mount
        "row_count": int,               # Features in the GeoDataFrame
        "file_extension": str,          # Normalized extension used
        "source_size_bytes": int,       # Raw file size before conversion
        "column_count": int,            # Attribute columns (excluding geometry)
        "columns": list[str],           # Attribute column names (excluding geometry)
        "geometry_column": str,         # Name of geometry column
        "crs_raw": str | None,          # CRS as detected from source, before any reprojection
        "source_file": str              # Original blob_name for catalog lineage
    }
}
```

**RETURNS (failure)**:
```
{
    "success": false,
    "error": str,                       # Human-readable error message
    "error_type": str                   # One of: ValidationError, UnsupportedFormatError,
                                        #         MountUnavailableError, BlobNotFoundError,
                                        #         BlobStreamError, FormatConversionError,
                                        #         EmptyFileError
}
```

**BEHAVIORS TO PORT**:

| ID | Behavior | Monolith Reference | Implementation Notes |
|---|---|---|---|
| H1-B1 | Mount directory creation with `source/` and `extract/` subdirectories using `os.makedirs(exist_ok=True)` | handler L172-176 | Create under `/mnt/etl/{_run_id}/source/` and `/mnt/etl/{_run_id}/extract/` |
| H1-B2 | Mount writability probe: create `.write-test` file, write `"ok"`, delete | handler L179-181 | Run BEFORE blob streaming. Fail with `MountUnavailableError` if probe fails. |
| H1-B3 | Blob streaming via `BlobRepository.for_zone("bronze").stream_blob_to_mount()` with `chunk_size_mb=32` | handler L186-191 | 32MB chunk size is a tuned parameter. Do not change. |
| H1-B4 | File size logging after stream: `os.path.getsize(dest_path)` formatted as MB | handler L197-201 | Log as INFO. Return raw bytes as `source_size_bytes`. |
| H1-B5 | CSV converter parameter merging: top-level `lat_name`, `lon_name`, `wkt_column` override nested `converter_params` | handler L464-466, core.py L230-240 | Extract from `processing_options`. These are API ergonomics -- top-level takes precedence. |
| H1-B6 | GPKG layer name routing: `processing_options.get('layer_name')` into converter params | handler L468-469 | Required for multi-layer GPKG files. |
| H1-B7 | GPKG layer existence validation: check `requested_layer in layer_names` via `pyogrio.list_layers()` | handler L472-486 | Error message MUST include available layers list: `"Layer 'X' not found. Available layers: [...]"` |
| H1-B8 | GPKG non-spatial layer rejection: detect layers where `geom_type is None` in available layers | handler L488-499 | Reject attribute-only tables. Error message must name the layer and explain it has no geometry. |
| H1-B9 | GPKG QGIS metadata layer detection: detect `QGIS_SIGNATURE_COLUMNS` overlap >= 2 | handler L535-563 | Warn user with spatial_hint listing actual data layers. Important: `spatial_layers` variable from H1-B8 MUST be explicitly passed to this block -- do not rely on closure scope (see S-2). |
| H1-B10 | Mount converter extras for ZIP formats: pass `extract_dir` to converter | handler L217-218, L501-503 | ZIP/SHP/KMZ files need an extraction directory on the mount. Pass `/mnt/etl/{_run_id}/extract/` as `extract_dir`. |
| H1-B11 | Zero-feature check after conversion: fail if `len(gdf) == 0` | core.py L196-200 | Return `EmptyFileError`. Message: "Source file contains zero features." |
| H1-B12 | `load_info` equivalent construction | core.py L202-208 | Build the result dict with all fields listed in RETURNS above. This replaces the monolith's `load_info` dict. |

**NEW BEHAVIORS**:

| ID | Behavior | Source |
|---|---|---|
| N-4 | Mount failure is a hard error (`MountUnavailableError`). No in-memory fallback. | P's design, operator GATE1 O-20 confirmed |
| N-5 | `UnsupportedFormatError` for unrecognized file extensions with supported formats list | P's design. Supported: csv, geojson, json, gpkg, kml, kmz, shp, zip |
| N-6 | `source_size_bytes` as structured result field (was log-only in monolith) | P's design |
| N-8 | `BlobNotFoundError` when blob does not exist in container | P's design. Catch Azure SDK 404 during streaming. |

**ERROR HANDLING**:

| Error Condition | Error Type | Recovery |
|---|---|---|
| `_run_id` or required params missing | `ValidationError` | Fail immediately, no I/O |
| `file_extension` not in supported set | `UnsupportedFormatError` | Fail immediately, include supported formats list |
| Mount directory creation fails | `MountUnavailableError` | Fail immediately |
| Write probe fails | `MountUnavailableError` | Fail immediately, message: "ETL mount at {path} is not writable" |
| Blob not found in container | `BlobNotFoundError` | Fail, include blob_name and container_name in message |
| Blob streaming fails (non-404) | `BlobStreamError` | Fail. Do NOT fall back to in-memory. |
| GPKG requested layer not found | `ValidationError` | Fail, include available layers in message |
| GPKG non-spatial layer selected | `ValidationError` | Fail, explain layer has no geometry |
| Format conversion fails | `FormatConversionError` | Fail, include original exception message |
| Zero features after conversion | `EmptyFileError` | Fail |
| Any unexpected exception | `HandlerError` | Fail, include traceback in error message |

**SIDE EFFECTS**:
- Creates directories on ETL mount: `/mnt/etl/{_run_id}/source/`, `/mnt/etl/{_run_id}/extract/`
- Writes blob file to mount (source subdirectory)
- Writes GeoParquet file to mount (returned as `intermediate_path`)
- Reads from Azure Blob Storage (bronze zone)
- No database operations

**SHARED STATE RESOLUTION**:
- `mount_source_path`: Internal to this handler. Created during blob streaming, used during format conversion, never returned. Downstream handlers receive only the GeoParquet `intermediate_path`.
- `load_info`: Eliminated. All fields are individual result dict entries.
- `processing_options`: Received as input. Handler reads ONLY `lat_name`, `lon_name`, `wkt_column`, `layer_name`. All other keys are ignored.

**SUBTLE BEHAVIORS TO PRESERVE**:
- **S-2 (GPKG `spatial_layers` scope)**: The `spatial_layers` list computed during non-spatial layer rejection (H1-B8) MUST be explicitly passed to the QGIS metadata detection logic (H1-B9). Do NOT rely on variable scoping. Implement as a helper function that takes `spatial_layers` as a parameter.
- **H1-B5 (CSV param merging)**: Top-level `lat_name`/`lon_name`/`wkt_column` from `processing_options` override any nested `converter_params` values. This is for API ergonomics.
- **H1-B10 (ZIP extract_dir)**: The extraction directory MUST be on the mount (`/mnt/etl/{_run_id}/extract/`), not a system temp directory. This ensures cleanup via the finalize handler.

**IDEMPOTENCY**:
Handler is idempotent. On retry, it re-streams the blob and overwrites the GeoParquet file. `os.makedirs(exist_ok=True)` ensures directory creation is idempotent. The GeoParquet write overwrites any previous file at `intermediate_path`.

**TESTING**:
Via `POST /api/dag/test/handler/vector_load_source`:
1. Provide `blob_name` pointing to a known test file in the `wargames` container.
2. Verify response `success: true`.
3. Verify `intermediate_path` file exists on mount and is valid GeoParquet.
4. Verify `row_count` matches expected feature count.
5. Verify `crs_raw` is populated (or null for CRS-less CSV).
6. Verify `columns` list matches expected column names.
7. Test GPKG with `layer_name` specified.
8. Test CSV with `lat_name`/`lon_name`.
9. Test unsupported extension -- expect `UnsupportedFormatError`.
10. Test nonexistent blob -- expect `BlobNotFoundError`.

---

### HANDLER: `vector_validate_and_clean`

**PURPOSE**: Perform geometry cleaning, CRS handling, column operations, split-column pre-validation, and geometry-type splitting on a loaded GeoDataFrame, producing 1-3 cleaned GeoParquet files (one per geometry group).

**PARAMS**:

| Name | Type | Required | Default | Source |
|---|---|---|---|---|
| `source_path` | `str` | yes | -- | `receives:` from `load_source.intermediate_path` |
| `processing_options` | `dict` | no | `{}` | workflow param |
| `_run_id` | `str` | yes | -- | system-injected |
| `_node_name` | `str` | yes | -- | system-injected |

Keys consumed from `processing_options`:
- `split_column` (str or None): Column name for split-view pre-validation
- `simplify` (dict or None): `{"tolerance": float}` for Douglas-Peucker simplification
- `quantize` (dict or None): `{"precision": int}` for coordinate precision reduction
- `column_mapping` (dict or None): User-specified rename rules `{"old_name": "new_name"}`

The handler MUST NOT read any other keys from `processing_options`.

**RETURNS (success)**:
```
{
    "success": true,
    "result": {
        "intermediate_path": str,           # Directory containing cleaned parquets
        "geometry_groups": [                # 1-3 entries
            {
                "geometry_type": str,       # "polygon", "line", or "point"
                "row_count": int,
                "parquet_path": str         # Absolute mount path
            }
        ],
        "total_row_count": int,
        "original_row_count": int,
        "rows_removed": int,
        "crs_output": str,                  # Always "EPSG:4326"
        "crs_input": str | None,            # Original CRS as detected
        "columns": list[str],               # Sanitized column names (excluding geometry)
        "warnings": list[str],
        "split_column_validated": bool,
        "split_column_values": list[str] | None,   # ADVISORY ONLY
        "split_column_cardinality": int | None
    }
}
```

**RETURNS (failure)**:
```
{
    "success": false,
    "error": str,
    "error_type": str                   # One of: ValidationError, IntermediateNotFoundError,
                                        #         AllNullGeometryError, AllFilteredError,
                                        #         UnsupportedGeometryError,
                                        #         SplitColumnNotFoundError,
                                        #         SplitColumnCardinalityError,
                                        #         SplitColumnTypeError
}
```

**BEHAVIORS TO PORT**:

The following operations MUST execute in the order listed. Reordering changes semantics.

| ID | Behavior | Monolith Reference | Implementation Notes |
|---|---|---|---|
| H2-B12 | User-specified column mapping (rename) | handler L566-572, core.py L335-378 | Apply FIRST, before any validation. Validate source columns exist. `column_mapping` from `processing_options`. |
| H2-B1 | Null geometry removal with diagnostic sampling | postgis_handler L130-163 | Log first 5 null-geometry rows showing first 3 non-geom columns. Add `NULL_GEOMETRY_DROPPED` warning with count. |
| H2-B2 | `make_valid()` for invalid geometries with post-repair verification | postgis_handler L205-224 | Apply `shapely.make_valid()`. Count and log geometries that remain invalid after repair. |
| H2-B3 | Force 2D: strip Z and M dimensions via `shapely.force_2d()` with GeoDataFrame reconstruction | postgis_handler L227-268 | MUST reconstruct the GeoDataFrame after force_2d (lines 257-261). In-place geometry assignment does not update column metadata. |
| H2-B4 | Antimeridian fix: detect and split geometries crossing 180deg longitude | postgis_handler L270-381 | Affects Pacific-region datasets. Geometries crossing the antimeridian render as globe-spanning lines without this fix. |
| H2-B5 | Multi-type normalization: Polygon to MultiPolygon, LineString to MultiLineString, Point to MultiPoint | postgis_handler L385-425 | ALL geometries normalized to Multi- type. This is a precondition for type-split correctness. |
| H2-B6 | Polygon winding order enforcement: CCW exterior, CW holes via `orient(geom, sign=1.0)` | postgis_handler L427-477 | Required for MVT tile specification compliance. Without this, TiPG renders invisible or inverted polygons. |
| H2-B7 | PostGIS geometry type validation: reject GeometryCollection and unsupported types | postgis_handler L479-520 | Error message MUST include solutions: explode, filter, or split. Fail with `UnsupportedGeometryError`. |
| H2-B8 | Datetime validation: NaT/out-of-range year detection, conversion to NULL, all-NaT column pruning | postgis_handler L522-584 | CRITICAL. NaT values cause year ~48113 in PostgreSQL via psycopg3, making the table permanently unreadable. Guard the `dt.year` extraction with try/except for mixed-type columns (let column pass through if extraction fails). |
| H2-B9 | All-null column pruning: drop columns where every value is null/NaN/NaT | postgis_handler L586-613 | Prevents TiPG OverflowError on empty TIMESTAMP columns. |
| H2-B10 | CRS handling: reproject if not 4326, assign 4326 if no CRS (with warning), verify if already 4326 | postgis_handler L615-637 | ASSIGN 4326 for CRS-less data (do NOT reject). Log warning. Add to `warnings` list. See CR-1. |
| H2-B11 | Column name sanitization via `sanitize_columns()` | postgis_handler L639-641 | Lowercase, replace special chars, protect reserved words. Applied AFTER column mapping. |
| H2-B16 | Reserved column filtering: skip `id`, `geom`, `geometry`, `etl_batch_id` | core.py L381-407, postgis_handler L1632-1647 | Remove these columns from the GeoDataFrame before writing GeoParquet. Add warning if any were removed. |
| H2-B15 | Optional geometry simplification (Douglas-Peucker) and quantization | postgis_handler L643-713 | Only if `processing_options.simplify` or `processing_options.quantize` provided. Guard quantization import with try/except for Shapely version. |
| H2-B13 | Geometry type split: group by geometry type with suffix mapping | postgis_handler L714-758 | Split into 1-3 groups. Suffix mapping: MultiPolygon -> "polygon", MultiLineString -> "line", MultiPoint -> "point". Each group written as separate GeoParquet file. |
| H2-B14 | Warnings accumulation: NULL_GEOMETRY_DROPPED, GEOMETRY_TYPE_SPLIT, CRS_ASSUMED | postgis_handler L176-186, L739-750 | Accumulate all warnings. Return in result `warnings` list. |

Split-column pre-validation (runs after geometry type split, on the combined data):

| ID | Behavior | Implementation Notes |
|---|---|---|
| SC-1 | Check split_column exists in sanitized columns | After sanitization, the column name may have changed. Check against sanitized names. Fail with `SplitColumnNotFoundError`. |
| SC-2 | Check split_column is not geometry/binary type | Fail with `SplitColumnTypeError`. |
| SC-3 | Check split_column cardinality <= 100 | Count distinct values. Fail with `SplitColumnCardinalityError` if > 100. Include actual cardinality in error. |
| SC-4 | Return `split_column_values` as ADVISORY | These values are for cardinality checking. Node 4 (`create_split_views`) MUST re-discover values from PostGIS via `SELECT DISTINCT`. |

**NEW BEHAVIORS**:

| ID | Behavior | Source |
|---|---|---|
| N-1 | Split column cardinality limit (max 100) | P's design. Prevents creation of thousands of views. |
| N-2 | GeoParquet as intermediate format between handlers | P's design. Required by DAG architecture. |
| N-7 | `rows_removed` and `original_row_count` as structured result fields | P's design. Promotes monolith log data to first-class fields. |
| N-9 | `AllNullGeometryError` and `AllFilteredError` distinction | P's design. Finer-grained than monolith's generic ValueError. |

**ERROR HANDLING**:

| Error Condition | Error Type | Recovery |
|---|---|---|
| `source_path` missing or empty | `ValidationError` | Fail immediately |
| Source parquet file does not exist on mount | `IntermediateNotFoundError` | Fail immediately |
| All geometries are null (100% null after H2-B1) | `AllNullGeometryError` | Fail |
| All features filtered during cleaning (0 remaining after make_valid, type checks) | `AllFilteredError` | Fail |
| GeometryCollection or unsupported type found | `UnsupportedGeometryError` | Fail with guidance |
| `split_column` specified but not found post-sanitization | `SplitColumnNotFoundError` | Fail |
| `split_column` cardinality > 100 | `SplitColumnCardinalityError` | Fail |
| `split_column` is geometry or binary type | `SplitColumnTypeError` | Fail |
| Datetime year extraction fails on a column | (not an error) | Catch, log warning, let column pass through |
| Quantization import fails (Shapely version) | (not an error) | Log warning, skip quantization |

**SIDE EFFECTS**:
- Reads GeoParquet from mount (at `source_path`)
- Writes 1-3 GeoParquet files to mount (under `/mnt/etl/{_run_id}/validated/`)
- No database operations
- No blob storage operations

**SHARED STATE RESOLUTION**:
- `prepared_groups` dict: Eliminated. Replaced by `geometry_groups` list in result, with GeoDataFrames serialized as GeoParquet files on mount.
- `data_warnings`: Eliminated. Each handler returns its own `warnings` list.
- `load_info`: Not consumed by this handler. CRS info comes from reading the GeoParquet's CRS metadata.
- `processing_options`: Received as input. Handler reads ONLY `split_column`, `simplify`, `quantize`, `column_mapping`.

**SUBTLE BEHAVIORS TO PRESERVE**:
- **S-1 (NaT conversion)**: The datetime validation (H2-B8) MUST convert `pd.NaT` to `None` at the pandas level. This is the PRIMARY defense against the year-48113 corruption bug. The handler that writes to PostGIS has a secondary defense (CR-5), but this handler is the first line.
- **S-3 (Hardcoded SRID 4326)**: The output CRS is always EPSG:4326. This is a POST-CONDITION of this handler, not a pre-condition of handler 3. Port faithfully.
- **S-5 (Geometry type from first feature)**: After type splitting, all rows in each group have the same geometry type. The `geometry_type` value in `geometry_groups` is derived from the actual geometries, not from metadata. Verify by checking `gdf.geometry.iloc[0].geom_type` matches the group assignment.
- **H2-B3 (Force 2D reconstruction)**: After `shapely.force_2d()`, the GeoDataFrame MUST be reconstructed (not just in-place geometry update). The reconstruction updates column metadata that in-place assignment does not.
- **Operation ordering**: Column mapping -> null geometry removal -> make_valid -> force_2d -> antimeridian fix -> multi-type normalization -> winding order -> geometry type validation -> datetime validation -> all-null column pruning -> CRS handling -> column sanitization -> reserved column filtering -> optional simplification/quantization -> geometry type split -> split-column validation. This order is load-bearing.

**IDEMPOTENCY**:
Handler is idempotent. On retry, it re-reads the source GeoParquet, reprocesses, and overwrites output GeoParquet files. No database state is modified.

**TESTING**:
Via `POST /api/dag/test/handler/vector_validate_and_clean`:
1. Place a test GeoParquet on mount. Run handler with `source_path` pointing to it.
2. Verify `crs_output` is always `"EPSG:4326"`.
3. Verify `total_row_count` equals sum of all `geometry_groups[*].row_count`.
4. Verify each `parquet_path` exists and is valid GeoParquet.
5. Test with mixed geometry types (Polygon + LineString) -- expect 2 groups.
6. Test with null geometries -- verify `rows_removed > 0` and warning present.
7. Test with CRS-less data -- verify `crs_output` is `"EPSG:4326"` and warning present.
8. Test with `split_column` pointing to valid column -- verify `split_column_validated: true`.
9. Test with `split_column` pointing to nonexistent column -- expect `SplitColumnNotFoundError`.
10. Test with KML file containing 3D coordinates -- verify force-2D applied.

---

### HANDLER: `vector_create_and_load_tables`

**PURPOSE**: For each geometry group, create a PostGIS table with batch tracking, insert data in idempotent chunks (DELETE+INSERT by batch_id), build deferred indexes, run ANALYZE, and verify row counts.

**PARAMS**:

| Name | Type | Required | Default | Source |
|---|---|---|---|---|
| `table_name` | `str` | yes | -- | workflow param |
| `schema_name` | `str` | no | `"geo"` | workflow param |
| `job_id` | `str` | yes | -- | workflow param |
| `processing_options` | `dict` | no | `{}` | workflow param |
| `geometry_groups` | `list[dict]` | yes | -- | `receives:` from `validate_and_clean.geometry_groups` |
| `_run_id` | `str` | yes | -- | system-injected |
| `_node_name` | `str` | yes | -- | system-injected |

Keys consumed from `processing_options`:
- `overwrite` (bool, default `false`): Whether to drop existing table before creating
- `chunk_size` (int, default `100000`): Rows per INSERT chunk

The handler MUST NOT read any other keys from `processing_options`.

`geometry_groups` entry contract (MUST validate each entry):
```
{
    "geometry_type": str,    # REQUIRED. One of: "polygon", "line", "point"
    "row_count": int,        # REQUIRED. Positive integer.
    "parquet_path": str      # REQUIRED. Absolute path on mount. File must exist.
}
```

**RETURNS (success)**:
```
{
    "success": true,
    "result": {
        "tables_created": [
            {
                "table_name": str,              # e.g. "my_dataset_polygon" or "my_dataset"
                "schema_name": str,
                "geometry_type": str,           # "polygon", "line", or "point"
                "row_count": int,               # Verified via SELECT COUNT(*)
                "rows_inserted_by_chunks": int, # Sum of per-chunk inserts (pre-verification)
                "column_count": int,
                "has_spatial_index": bool,
                "srid": int,                    # Always 4326
                "bbox": [float, float, float, float],  # [minx, miny, maxx, maxy]
                "is_split": bool,               # True if len(geometry_groups) > 1
                "table_suffix": str | None      # e.g. "polygon", or None if not split
            }
        ],
        "total_rows_loaded": int,
        "total_tables": int,
        "overwrite_performed": bool,
        "chunk_size_used": int,
        "warnings": list[str]
    }
}
```

**RETURNS (failure)**:
```
{
    "success": false,
    "error": str,
    "error_type": str                   # One of: ValidationError, IntermediateNotFoundError,
                                        #         TableExistsError, ZeroRowsError,
                                        #         DatabaseError, HandlerError
}
```

**BEHAVIORS TO PORT**:

Execute in the order listed for EACH geometry group (iterate over `geometry_groups`).

| ID | Behavior | Monolith Reference | Implementation Notes |
|---|---|---|---|
| H3-B12 | Table naming: `table_name_{geometry_type}` when split, plain `table_name` when single group | handler L254 | `is_split = len(geometry_groups) > 1`. If split, suffix with geometry_type. If single, no suffix. |
| H3-B3 | Table existence check with overwrite semantics | postgis_handler L1592-1617 | If table exists and `overwrite=true`: call `cleanup_split_view_metadata(table_name, schema_name)` THEN `DROP TABLE CASCADE`. If table exists and `overwrite=false`: fail with `TableExistsError`. |
| H3-B2 | `create_table_with_batch_tracking()`: table with `etl_batch_id TEXT` column and its index | postgis_handler L1549-1679 | Create table with columns from GeoParquet (excluding reserved: `id`, `geom`, `geometry`, `etl_batch_id`). Add `id SERIAL PRIMARY KEY`, geometry column as `GEOMETRY({mapped_type}, 4326)`, and `etl_batch_id TEXT`. Create `idx_{table_name}_etl_batch_id` index immediately (NOT deferred). Geometry type mapping: `"polygon"` -> `MULTIPOLYGON`, `"line"` -> `MULTILINESTRING`, `"point"` -> `MULTIPOINT`. |
| H3-B4 | Chunk insertion with idempotent DELETE+INSERT per batch_id | postgis_handler L1680-1809 | For each chunk i: `batch_id = f"{job_id[:8]}-chunk-{i}"`. Within a single transaction: `DELETE FROM table WHERE etl_batch_id = batch_id`, then `INSERT` all rows with that batch_id. `conn.commit()` after each chunk. This per-chunk commit is LOAD-BEARING for retry safety. |
| H3-B6 | NaT-to-None conversion during INSERT | postgis_handler L1209-1230 | For each row value: `None if val is pd.NaT else val`. This is the SECONDARY defense (see CR-5). |
| H3-B5 | Per-chunk row count verification | postgis_handler L1792-1806 | After each chunk INSERT: `SELECT COUNT(*) WHERE etl_batch_id = %s`. Compare to expected chunk size. Log WARNING if mismatch. |
| H3-B15 | Progress logging at 25/50/75/100% milestones | handler L829-835 | Log: milestone %, rows so far, total expected, elapsed time, rows/sec. |
| H3-B7 | Deferred index creation AFTER all data loaded | postgis_handler L1833-1912, handler L1012-1019 | Create spatial GIST index, attribute BTREE indexes, temporal BTREE DESC indexes. The `etl_batch_id` index is NOT deferred (already created with table). |
| H3-B8 | ANALYZE after index creation | postgis_handler L1811-1831, handler L1020 | Run `ANALYZE {schema}.{table}` after all indexes built. |
| H3-B9 | Zero-row validation: fail if `total_rows == 0` | handler L1097-1101 | After all chunks for all tables, verify total > 0. Fail with `ZeroRowsError`. |
| H3-B10 | Row count cross-check: `SELECT COUNT(*)` vs chunk sum | handler L1104-1120 | Use DB count as authoritative. If mismatch, log WARNING and add to `warnings` list. If `SELECT COUNT(*)` itself fails, continue with chunk sum (non-fatal). |
| H3-B16 | Chunk size default: 100,000 rows | handler L105 | Docker default. Do not use Function App default (1,000-5,000). |

**NEW BEHAVIORS**:

| ID | Behavior | Source |
|---|---|---|
| SEC-1 | SQL injection check on `table_name` | P's design. Reject names containing `;`, `--`, `'`, `"`. |
| SEC-2 | `geometry_groups` contract validation at boundary | P's design. Verify each entry has `geometry_type`, `row_count`, `parquet_path`. |
| WARN-1 | Handler-level `warnings` list in result | P's design. Surface row count discrepancies and overwrite actions. |

**ERROR HANDLING**:

| Error Condition | Error Type | Recovery |
|---|---|---|
| `table_name` missing or invalid characters | `ValidationError` | Fail immediately |
| `job_id` missing | `ValidationError` | Fail immediately |
| `geometry_groups` empty or missing | `ValidationError` | Fail immediately |
| `geometry_groups` entry missing required field | `ValidationError` | Fail immediately |
| Parquet file not found at `parquet_path` | `IntermediateNotFoundError` | Fail immediately |
| Table exists and `overwrite=false` | `TableExistsError` | Fail. Message includes table name. |
| Zero rows inserted across all tables | `ZeroRowsError` | Fail after all chunks attempted |
| Database connection failure | `DatabaseError` | Fail. Retryable by DAG (transient). |
| `SELECT COUNT(*)` cross-check fails | (not an error) | Log warning, continue with chunk sum |
| `cleanup_split_view_metadata` fails during overwrite | (not an error) | Log warning, proceed with DROP CASCADE. Stale catalog entries may remain. |
| Any unexpected exception | `HandlerError` | Fail |

**SIDE EFFECTS**:
- Reads GeoParquet files from mount (at `geometry_groups[*].parquet_path`)
- Creates PostGIS tables (1-3)
- Creates indexes on those tables
- Runs ANALYZE on those tables
- Optionally drops existing tables (when `overwrite=true`)
- Optionally cleans split view metadata from `geo.table_catalog` (when `overwrite=true`)
- Opens and closes ONE database connection for entire handler execution

**SHARED STATE RESOLUTION**:
- `is_split`: Derived from `len(geometry_groups) > 1` inside the handler. Not received from upstream.
- `batch_id`: Generated internally from `job_id[:8]` and chunk index. Never returned in result or crosses any boundary.
- `load_info`: Not consumed. Table metadata registration is node 5's job. This handler returns `row_count`, `column_count`, `bbox`, `srid` per table -- node 5 combines these with handler 1's `crs_raw`, `source_file`, etc.
- Single DB connection: Opened at handler start, held through DDL/INSERT/index/ANALYZE/verification, closed at handler end. Each chunk is committed independently within this connection.

**SUBTLE BEHAVIORS TO PRESERVE**:
- **S-1 (NaT-to-None)**: The INSERT value loop MUST check `val is pd.NaT` and convert to `None`. This is the secondary defense. Do not rely solely on handler 2 having sanitized datetimes.
- **S-4 (Per-chunk commit)**: Each chunk's DELETE+INSERT MUST be committed independently (`conn.commit()` after each chunk). Do NOT wrap all chunks in a single transaction. A failure on chunk 6 of 10 must leave chunks 0-5 committed. On retry, only chunk 6 is re-done (DELETE old partial, INSERT fresh).
- **S-6 (`is_split` flag)**: `is_split = len(geometry_groups) > 1` drives: table naming (suffix vs plain), result shape (`table_suffix` field), and `is_split` field in each table entry. Compute from the input list, not from any upstream flag.
- **C-1 (`etl_batch_id` coupling)**: The `etl_batch_id TEXT` column MUST be created with the table (H3-B2). Its index MUST be created immediately, not deferred. Without this column and index, the DELETE phase of idempotent insert is either impossible or unacceptably slow.
- **C-2 (Deferred index timing)**: Spatial GIST, attribute BTREE, and temporal BTREE indexes MUST be created AFTER all chunks are inserted. Creating them with the table (before INSERT) causes 5-10x performance degradation.
- **H3-B3 (Overwrite cleanup)**: The `cleanup_split_view_metadata` call MUST happen BEFORE `DROP CASCADE` during overwrite. The DROP removes views, but catalog entries for those views persist without explicit cleanup.
- **Reserved column skip in DDL**: When building the CREATE TABLE column list from GeoParquet columns, skip `id`, `geom`, `geometry`, `etl_batch_id`. These are created by the schema. The reserved list MUST match handler 2's list (CR-6).

**IDEMPOTENCY**:
Handler is idempotent via two mechanisms:
1. **Table level**: If `overwrite=true`, DROP+CREATE is idempotent. If `overwrite=false` and table exists, handler fails with `TableExistsError` (safe -- no partial state).
2. **Chunk level**: Each chunk uses deterministic `batch_id = f"{job_id[:8]}-chunk-{i}"`. The DELETE+INSERT pattern ensures that retrying a chunk replaces (not duplicates) data.

On retry after partial failure: committed chunks remain (their `etl_batch_id` values are in the table). The failed chunk is re-done via DELETE old + INSERT new. Subsequent chunks proceed normally. This is the core retry-safety mechanism.

**TESTING**:
Via `POST /api/dag/test/handler/vector_create_and_load_tables`:
1. Place cleaned GeoParquet files on mount. Provide `geometry_groups` referencing them.
2. Verify response `success: true`.
3. Verify each table exists in PostGIS: `SELECT * FROM information_schema.tables WHERE table_name = ...`.
4. Verify `row_count` matches `SELECT COUNT(*) FROM {schema}.{table}`.
5. Verify spatial index exists: check `pg_indexes` for GIST index.
6. Verify `etl_batch_id` column and its index exist.
7. Verify SRID is 4326: `SELECT Find_SRID(schema, table, 'geom')`.
8. Test with `overwrite=false` and existing table -- expect `TableExistsError`.
9. Test with `overwrite=true` and existing table -- verify old table dropped and new one created.
10. Test idempotency: submit same handler twice with same `job_id`. Verify row count is correct (not doubled).
11. Caller MUST DROP test tables after verification.

---

## 4. DEPENDENCY MAP

### Execution Order

```
[1] vector_load_source
         |
         | intermediate_path, columns, crs_raw, source_file, row_count
         v
[2] vector_validate_and_clean
         |
         | geometry_groups (list of {geometry_type, row_count, parquet_path})
         v
[3] vector_create_and_load_tables
         |
         | tables_created (list of {table_name, schema_name, geometry_type,
         |                          row_count, bbox, srid, is_split, table_suffix})
         v
[4] vector_create_split_views (existing, conditional on split_column)
         |
         v
[5] vector_register_catalog (existing)
         |
         v
[6] vector_refresh_tipg (existing)
```

### Data Flow Between Handlers 1-3

**Node 1 -> Node 2**:
| Field | Type | Consumed By |
|---|---|---|
| `intermediate_path` | `str` | Node 2 reads GeoParquet from this path |

(All other node 1 result fields flow to node 5 via the DAG's `receives:` mechanism, not through node 2.)

**Node 2 -> Node 3**:
| Field | Type | Consumed By |
|---|---|---|
| `geometry_groups` | `list[dict]` | Node 3 iterates to create one table per group |

Each dict contains:
- `geometry_type`: `str` -- determines PostGIS column type and table suffix
- `row_count`: `int` -- used for progress logging denominators
- `parquet_path`: `str` -- absolute mount path to read data from

**Node 3 -> Nodes 4/5** (for existing handlers):
| Field | Type | Consumed By |
|---|---|---|
| `tables_created` | `list[dict]` | Node 4 needs table names for view creation; Node 5 needs full table metadata |

Each dict contains: `table_name`, `schema_name`, `geometry_type`, `row_count`, `column_count`, `has_spatial_index`, `srid`, `bbox`, `is_split`, `table_suffix`.

**Workflow params flowing to multiple nodes** (via YAML `receives:` from workflow-level params, NOT through handler chain):
| Param | Consumed By |
|---|---|
| `table_name` | Node 3 (base name), Node 4 (for view naming), Node 5 (catalog) |
| `schema_name` | Node 3, Node 4, Node 5 |
| `job_id` | Node 1 (lineage), Node 3 (batch_id generation) |
| `processing_options.split_column` | Node 2 (pre-validation), Node 4 (view creation) |
| `processing_options.overwrite` | Node 3 (table existence handling) |
| `release_id` | Node 5 (release_tables junction, conditional) |
| `style` | Node 5 or future node (OGC style creation, see ESC-1) |

---

## 5. RISK REGISTER

### RR-1: NaT-to-None Conversion Omitted in Handler 3

**Description**: Builder implements handler 3 INSERT loop without NaT-to-None conversion, relying entirely on handler 2's datetime validation. A future code path bypasses handler 2, or handler 2's datetime validation has a bug for a specific column type, allowing NaT values to reach PostGIS.

**Likelihood**: Medium (handler 2 is the primary defense; handler 3 omission would only matter if handler 2 has a gap)

**Impact**: CRITICAL. Table is permanently unreadable. All psycopg3 clients crash with OverflowError on any SELECT.

**Mitigation**: CR-5 mandates NaT-to-None in BOTH handlers. Build spec H3-B6 explicitly requires it. Test by inserting a GeoParquet with a pd.NaT value directly into handler 3 (bypassing handler 2) and verifying the value becomes NULL in PostGIS.

---

### RR-2: Per-Chunk Commit Replaced with Single Transaction

**Description**: Builder wraps all chunks in a single database transaction for "atomicity." A failure on chunk N rolls back all previous chunks. On retry, all work is repeated.

**Likelihood**: Low (build spec S-4 explicitly prohibits this)

**Impact**: HIGH. A 10M-row upload failing at chunk 40/100 rolls back 4M committed rows. Retry re-does all 100 chunks. If the same transient error recurs, the job enters an infinite retry loop.

**Mitigation**: Build spec S-4 explicitly states: "Do NOT wrap all chunks in a single transaction." Test by interrupting a multi-chunk upload mid-execution, then retrying. Verify committed chunks are not re-inserted (check `etl_batch_id` values in table).

---

### RR-3: GPKG `spatial_layers` Scope Bug Reproduced

**Description**: Builder separates GPKG validation (H1-B7, H1-B8) and QGIS metadata detection (H1-B9) into separate functions but forgets to pass `spatial_layers` as a parameter. The QGIS detection block crashes with NameError, or silently fails to detect metadata layers.

**Likelihood**: High (F rated this as R-4 HIGH likelihood)

**Impact**: HIGH. QGIS metadata layers (style definitions, rendering expressions) silently upload as geospatial data tables.

**Mitigation**: Build spec S-2 explicitly requires passing `spatial_layers` as a parameter. Test with a QGIS-generated GPKG containing metadata layers. Verify the handler warns about metadata layers and guides user to data layers.

---

### RR-4: Force-2D Without GeoDataFrame Reconstruction

**Description**: Builder applies `shapely.force_2d()` in-place on geometries without reconstructing the GeoDataFrame (skipping the L257-261 pattern). Geometry column metadata still reports 3D. PostGIS rejects INSERT with dimension mismatch.

**Likelihood**: Medium (common mistake when working with GeoDataFrames)

**Impact**: HIGH. All KML/KMZ files and any file with 3D coordinates fails to load.

**Mitigation**: Build spec H2-B3 explicitly states MUST reconstruct. Test with a KML file containing 3D coordinates. Verify the GeoParquet output has 2D geometries and the PostGIS table accepts the data.

---

### RR-5: Mount Cleanup Does Not Run on Failure

**Description**: The finalize handler (not in scope for this spec, but referenced) is not configured with `always_run: true` in the YAML workflow. Failed jobs leave 500MB-2GB of intermediate files on mount.

**Likelihood**: Medium (depends on YAML workflow configuration)

**Impact**: HIGH. After 20 failed jobs, mount fills up. All subsequent ETL jobs fail with disk-full errors.

**Mitigation**: The YAML workflow definition MUST set the cleanup/finalize node with `always_run: true`. This is outside the scope of handlers 1-3 but is a CRITICAL workflow-level requirement. Document in the workflow YAML spec.

---

### RR-6: Overwrite Without Split View Metadata Cleanup

**Description**: Builder implements `DROP TABLE CASCADE` for overwrite but skips `cleanup_split_view_metadata()`. Views are removed by CASCADE but their catalog entries in `geo.table_catalog` persist.

**Likelihood**: Low (build spec H3-B3 explicitly includes cleanup)

**Impact**: MEDIUM. Catalog queries return references to deleted views. Map UI shows 404 errors for phantom views.

**Mitigation**: Build spec H3-B3 specifies cleanup before DROP. Test by creating a table with split views, then overwriting. Verify no stale view entries remain in `geo.table_catalog`.

---

### RR-7: Antimeridian Fix Omitted

**Description**: Builder omits antimeridian fix (H2-B4) as "edge case." Pacific-region datasets render as lines spanning the entire globe.

**Likelihood**: Medium (easy to dismiss as rare)

**Impact**: MEDIUM. Affects New Zealand, Fiji, Russia, Alaska datasets. Visually broken but geometrically correct. Every Pacific-region user reports a rendering bug.

**Mitigation**: Build spec H2-B4 explicitly includes antimeridian fix. The existing monolith implementation (postgis_handler L270-381) can be ported directly. Test with a dataset containing geometries crossing 180deg longitude.

---

### RR-8: `crs_raw` vs `original_crs` Field Name Mismatch

**Description**: Handler 1 returns `crs_raw` (per P's spec). Node 5 (`vector_register_catalog`) expects `original_crs` or `source_crs` (per monolith convention). The field is silently lost, and `table_catalog.source_crs` is recorded as NULL for all uploads.

**Likelihood**: High (naming convention mismatch across handler boundaries)

**Impact**: MEDIUM. Data lineage broken -- users cannot determine original CRS.

**Mitigation**: The YAML workflow's `receives:` mapping must explicitly map handler 1's `crs_raw` to node 5's expected field name. Alternatively, standardize on one name. Test by uploading a file with non-4326 CRS and verifying `table_catalog.source_crs` is populated.

---

### RR-9: Geometry Groups Contract Drift

**Description**: `vector_validate_and_clean` adds a field to `geometry_groups` entries (e.g., `compression`, `encoding`). `vector_create_and_load_tables` does not expect it. Benign now (extra fields ignored), but if handler 2 later removes or renames `parquet_path`, handler 3 breaks.

**Likelihood**: Low (contract is documented)

**Impact**: HIGH if it occurs (handler 3 cannot read input data)

**Mitigation**: Build spec defines the contract explicitly: `geometry_type` (str), `row_count` (int), `parquet_path` (str) are REQUIRED. Handler 3 validates at boundary. Extra fields ignored. Missing fields cause immediate `ValidationError`. Any contract change requires updating both handlers.

---

## 6. BEHAVIOR ACCOUNTING

Every behavior from F's BEHAVIOR PRESERVATION REQUIREMENTS mapped to exactly one handler's BEHAVIORS TO PORT.

### Handler 1 (`vector_load_source`)

| F ID | Behavior | Build Spec Reference |
|---|---|---|
| H1-B1 | Mount directory creation | H1-B1 |
| H1-B2 | Mount writability probe | H1-B2 |
| H1-B3 | Blob streaming with 32MB chunks | H1-B3 |
| H1-B4 | File size logging | H1-B4 |
| H1-B5 | CSV converter parameter merging | H1-B5 |
| H1-B6 | GPKG layer name routing | H1-B6 |
| H1-B7 | GPKG layer existence validation | H1-B7 |
| H1-B8 | GPKG non-spatial layer rejection | H1-B8 |
| H1-B9 | GPKG QGIS metadata layer detection | H1-B9 |
| H1-B10 | ZIP extract_dir for mount converters | H1-B10 |
| H1-B11 | Zero-feature check after conversion | H1-B11 |
| H1-B12 | `load_info` equivalent construction | H1-B12 |
| H1-B13 | Validation event emission | DEFERRED (ESC-3). Not in handler 1. |
| H1-B14 | Memory checkpoint logging | DROPPED. Operational profiling, no functional impact. Can be added later as debug-level logging. |

### Handler 2 (`vector_validate_and_clean`)

| F ID | Behavior | Build Spec Reference |
|---|---|---|
| H2-B1 | Null geometry removal with diagnostic sampling | H2-B1 |
| H2-B2 | make_valid with post-repair verification | H2-B2 |
| H2-B3 | Force 2D with GeoDataFrame reconstruction | H2-B3 |
| H2-B4 | Antimeridian fix | H2-B4 |
| H2-B5 | Multi-type normalization | H2-B5 |
| H2-B6 | Winding order enforcement | H2-B6 |
| H2-B7 | GeometryCollection rejection | H2-B7 |
| H2-B8 | Datetime validation (NaT, out-of-range years) | H2-B8 |
| H2-B9 | All-null column pruning | H2-B9 |
| H2-B10 | CRS handling (reproject/assign/verify) | H2-B10 |
| H2-B11 | Column name sanitization | H2-B11 |
| H2-B12 | User-specified column mapping | H2-B12 |
| H2-B13 | Geometry type split | H2-B13 |
| H2-B14 | Warnings accumulation | H2-B14 |
| H2-B15 | Optional simplification and quantization | H2-B15 |
| H2-B16 | Reserved column filtering | H2-B16 |

### Handler 3 (`vector_create_and_load_tables`)

| F ID | Behavior | Build Spec Reference |
|---|---|---|
| H3-B1 | Single connection for table lifecycle | CR-4 (handler-owned connection, held for full lifecycle) |
| H3-B2 | `create_table_with_batch_tracking` | H3-B2 |
| H3-B3 | Table existence check with overwrite | H3-B3 |
| H3-B4 | Idempotent DELETE+INSERT per batch_id | H3-B4 |
| H3-B5 | Per-chunk row count verification | H3-B5 |
| H3-B6 | NaT-to-None conversion during INSERT | H3-B6 |
| H3-B7 | Deferred index creation | H3-B7 |
| H3-B8 | ANALYZE after index creation | H3-B8 |
| H3-B9 | Zero-row validation | H3-B9 |
| H3-B10 | Row count cross-check | H3-B10 |
| H3-B11 | Feature count metadata update | ESCALATED (ESC-2). Depends on node 5's current contract. |
| H3-B12 | Geometry-split table naming | H3-B12 |
| H3-B13 | Table group catalog update | Assigned to node 5 (`vector_register_catalog`). Handler 3 passes `is_split` and `table_suffix` in its result for node 5 to use. |
| H3-B14 | Release tables junction | Assigned to node 5 (`vector_register_catalog`). `release_id` routed via workflow params. |
| H3-B15 | Progress logging at milestones | H3-B15 |
| H3-B16 | Chunk size default 100,000 | H3-B16 |
| H3-B17 | `register_table_metadata` (dual table write) | Assigned to node 5 (`vector_register_catalog`). Handler 3 passes all needed metadata in `tables_created`. |
| H3-B18 | Vector tile URL generation | Assigned to node 5 (`vector_register_catalog`). |

### Orphaned Behaviors Final Disposition

| D ID | Behavior | Disposition |
|---|---|---|
| O-1 | Release status PROCESSING | DEFERRED to DAG `on_start` workflow hook |
| O-2 | Checkpoint recording | DEFERRED to DAG infrastructure (`workflow_tasks.result_data` provides equivalent) |
| O-3 | Validation events | ESCALATED (ESC-3) |
| O-4 | Vector tile URL generation | Node 5 (existing) |
| O-5 | Table group update | Node 5 (existing) |
| O-6 | Release tables junction | Node 5 (existing) |
| O-7 | Per-chunk checkpoints | Subsumed by O-2 |
| O-8 | Progress logging | Handler 3 (H3-B15) |
| O-9 | Zero-row validation | Handler 3 (H3-B9) |
| O-10 | Row count cross-check | Handler 3 (H3-B10) |
| O-11 | Feature count in table_catalog | ESCALATED (ESC-2) |
| O-12 | OGC styles | ESCALATED (ESC-1) |
| O-13 | Split views | Node 4 (existing) |
| O-14 | TiPG refresh | Node 6 (existing) |
| O-15 | Table metadata registration | Node 5 (existing) |
| O-16 | Error enrichment | DEFERRED to handler wrapper infrastructure |
| O-17 | Mount cleanup | Finalize handler in YAML workflow (`always_run: true`) |
| O-18 | Connection diagnostic | DROPPED (pure diagnostic, no functional impact) |
| O-19 | Result aggregation | Handler 3 internally (for its tables); DAG infrastructure (cross-node) |
| O-20 | In-memory fallback | INTENTIONALLY REMOVED (operator confirmed) |

---

**END OF AGENT M REPORT**
