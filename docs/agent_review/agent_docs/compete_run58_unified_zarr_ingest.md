# COMPETE Run 58: Unified Zarr Ingest (v0.10.9)

| Field | Value |
|-------|-------|
| **Date** | 27 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Unified Zarr ingest workflow — NC/Zarr → rechunk → pyramid → STAC |
| **Version** | v0.10.6.5 (pre-deploy) |
| **Split** | C — Data vs Control Flow |
| **Files** | 12 files reviewed |
| **Findings** | Total: 12 (1 CRITICAL, 4 HIGH, 4 MEDIUM, 2 LOW, 1 NON-ISSUE) |
| **Top 5 Fixes** | All Small effort, 4 Low risk, 1 Medium risk |
| **Accepted Risks** | 7 (flat return contract, CRS hardcode, first-var chunks, pyramid defaults, empty current_chunks, size fallback, credential bypass) |
| **Verdict** | Sound topology, 3 blocking bugs in NC path + 1 YAML default issue. Fix before E2E. |

---

## Scope Split C — Alpha (Data) / Beta (Control Flow)

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Data validation, transformation, encoding, format | handler_validate_source, handler_generate_pyramid, _build_zarr_encoding, rechunk bypass |
| Beta | DAG lifecycle, routing, failure, contracts, dry_run | ingest_zarr.yaml, param_resolver, handler returns, skip propagation |
| Gamma | Blind spots + contradictions | param_resolver.py, blob.py, config/defaults.py, credential patterns |

---

## EXECUTIVE SUMMARY

The unified Zarr ingest subsystem has a sound workflow topology — conditional routing between NetCDF and Zarr paths, correct fan-in at register, and proper composable STAC materialization. However, the NetCDF conversion handler (`netcdf_convert_and_pyramid`) has two blocking bugs: it writes to the wrong storage account (bronze instead of silver) and the register node constructs a URL that does not match where data is written. Combined with `dry_run: true` as the YAML default and no dry_run awareness in register/materialize, every default submission will fail. The Zarr-path handlers are materially better — they use `BlobRepository.for_zone()` correctly and have consolidated metadata fallback. Fixing 3 issues in the NC handler and 1 in the YAML unblocks the entire workflow.

---

## TOP 5 FIXES

### Fix 1: Register node URL mismatch on NetCDF path

- **WHAT**: `zarr_register_metadata` constructs `abfs://silver-zarr/{target_prefix}` but `netcdf_convert_and_pyramid` writes to `{target_prefix}_pyramid.zarr`.
- **WHY**: Register will fail with "store not found" on every NetCDF-path execution.
- **WHERE**: `services/zarr/handler_register.py:54`, `services/handler_netcdf_to_zarr.py:1159`
- **HOW**: Add `zarr_store_url` to `convert_and_pyramid` result dict. Wire via `receives:` in YAML. Register already checks `zarr_store_url` before `target_prefix` fallback.
- **EFFORT**: Small
- **RISK OF FIX**: Low

### Fix 2: source_account used for silver write in netcdf_convert_and_pyramid

- **WHAT**: Handler uses bronze `source_account` for writing pyramid to silver container.
- **WHY**: Writes data to wrong storage account in multi-account deployments. Violates Principle 3.
- **WHERE**: `services/handler_netcdf_to_zarr.py:1127`
- **HOW**: Replace with `BlobRepository.for_zone("silver").account_name`. Same pattern as `handler_generate_pyramid.py:108`.
- **EFFORT**: Small
- **RISK OF FIX**: Low

### Fix 3: dry_run default causes confusing failure at register

- **WHAT**: YAML defaults `dry_run: true`, but register/materialize nodes don't check it.
- **WHY**: Default submissions fail at register with "store not found" instead of a clear dry-run message.
- **WHERE**: `workflows/ingest_zarr.yaml:20`, `services/zarr/handler_register.py`, `services/stac/handler_materialize_item.py`
- **HOW**: Pass `dry_run` to register/materialize nodes, add early-exit guards. Consider changing YAML default to `false` (explicit opt-in for dry-run preview).
- **EFFORT**: Small
- **RISK OF FIX**: Low

### Fix 4: encoding not passed to pyramid.to_zarr()

- **WHAT**: Blosc/LZ4 encoding computed but discarded — pyramid uses ndpyramid defaults.
- **WHY**: Pyramid store may have inconsistent compression and larger-than-necessary size.
- **WHERE**: `services/handler_netcdf_to_zarr.py:1131`
- **HOW**: Add `encoding=encoding` to `pyramid.to_zarr()`. Test that encoding keys match pyramid variable names.
- **EFFORT**: Small
- **RISK OF FIX**: Medium (encoding keys may not match pyramid structure)

### Fix 5: zarr_validate_source hardcodes consolidated=True without fallback

- **WHAT**: Gateway node has no fallback for stores without consolidated metadata.
- **WHY**: Workflow fails at first node for any non-consolidated Zarr store.
- **WHERE**: `services/zarr/handler_validate_source.py:103-107`
- **HOW**: Wrap in try/except, fallback to `consolidated=False`. Pattern exists in `handler_register.py:104-107`.
- **EFFORT**: Small
- **RISK OF FIX**: Low

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| Flat vs nested return contract in validate handler | Works today via resolve_dotted_path | Building handler test harness or result-schema validation |
| CRS hardcoded to EPSG:4326 | All current datasets are WGS84 | Ingesting projected/UTM datasets |
| First-variable-only chunk inspection | Real-world stores use uniform chunking | Chunk validation failures in production |
| pyramid_resample default pixels_per_tile | PROBABLE, not confirmed | Tile rendering artifacts in TiTiler |
| fsspec credential bypass in validate handler | Read-only on bronze, ambient MI works | Tightening bronze access policies |
| NetCDF needs_rechunk=False with empty chunks | No downstream consumer uses it | Never |
| total_size_bytes fallback to 0 | Informational field only | Never |

---

## ARCHITECTURE WINS

1. **Conditional routing topology** — `detect_type` with optional-dep fan-in at register is a textbook DAG pattern
2. **Register handler's consolidated fallback** — defensive without being silent, should propagate to all open_zarr sites
3. **BlobRepository.for_zone() in handler_generate_pyramid** — correct multi-account pattern, just needs consistent application
4. **Composable STAC tail** — register → materialize_item → materialize_collection reused across raster and zarr
5. **_auto_detect_levels algorithm** — simple, correct, sensible defaults with zero-level guard

---

*COMPETE Run 58 — 27 MAR 2026*
*Split C: Data vs Control Flow*
*Author: Claude + Robert Harrison*
