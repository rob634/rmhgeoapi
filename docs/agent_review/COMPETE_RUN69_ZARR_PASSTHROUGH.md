# COMPETE Run 69: Zarr Cloud Passthrough Review

**Date**: 30 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Scope**: Unified Zarr ingest pipeline — cloud-native Zarr passthrough + full NC/Zarr workflow
**Version**: v0.10.9.6
**Split**: C (Data vs Control Flow)
**Files**: 8
**Lines**: ~3,860

---

## Findings Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| CRITICAL | 2 | Cross-zone credential failure in generate_pyramid; rechunk ignores dry_run |
| HIGH | 4 | 7 handlers invisible to App Insights; generate_pyramid missing credential; passthrough bypasses dry_run; NetCDF pyramid drops encoding |
| MEDIUM | 6 | No pre-cleanup on pyramid writes; first-var-only rechunk check; encoding clear scope; 3 spatial extent impls; cross-product coord matching; az:// vs abfs:// |
| LOW | 8 | Passthrough field inconsistency, level sizes, total_size_bytes semantics, etc. |

**Total**: 20 findings (2 CRITICAL, 4 HIGH, 6 MEDIUM, 8 LOW)

---

## Agents

- **Omega**: Chose Split C (Data vs Control Flow) — ETL pipeline where data correctness and flow correctness create the most productive tension
- **Alpha**: Data Integrity and Lifecycle (7 strengths, 3 HIGH, 5 MEDIUM, 3 LOW, 5 assumptions, 6 recommendations)
- **Beta**: Orchestration, Flow Control, Failure Handling (12 verified safe, 1 CRITICAL, 2 HIGH, 2 MEDIUM, 2 risks, 3 edge cases)
- **Gamma**: 2 contradictions resolved, 2 agreement reinforcements, 9 blind spots, full severity recalibration
- **Delta**: Top 5 fixes, 5 accepted risks, 5 architecture wins

---

## Top 5 Fixes

### FIX 1 (CRITICAL): generate_pyramid source-read uses wrong-zone credentials

**WHAT**: `zarr_generate_pyramid` opens source Zarr with Silver-only `account_name` (no credential) when source may be Bronze.
**WHY**: When rechunk is skipped (chunks already optimal), `rechunk.result.zarr_store_url` is the original Bronze `abfs://` URL. `generate_pyramid` tries Silver credentials → HTTP 403.
**WHERE**: `services/zarr/handler_generate_pyramid.py`, `zarr_generate_pyramid`, lines 109-115
**HOW**: Detect source zone from URL container, use `get_xarray_storage_options()` from correct zone.
**EFFORT**: Small
**RISK OF FIX**: Low

### FIX 2 (CRITICAL): ingest_zarr_rechunk ignores dry_run

**WHAT**: Handler never extracts or checks `dry_run` parameter; performs real writes unconditionally.
**WHY**: Violates universal `dry_run=true` default. Combined with Fix 5, entire Zarr path writes during dry_run.
**WHERE**: `services/handler_ingest_zarr.py`, `ingest_zarr_rechunk`, lines 744-953
**HOW**: Add `dry_run = params.get("dry_run", True)` and guard before write logic.
**EFFORT**: Small
**RISK OF FIX**: Low

### FIX 3 (HIGH): 7 handlers use logging.getLogger instead of LoggerFactory

**WHAT**: All Epoch 5 zarr handlers + finalize handlers invisible to Application Insights.
**WHY**: Commit 7b2ae590 migrated DAG core files but missed handler layer. Violates P11.
**WHERE**: 7 files (see report body)
**HOW**: Replace `logging.getLogger(__name__)` with `LoggerFactory.create_logger(ComponentType.SERVICE, ...)`.
**EFFORT**: Small
**RISK OF FIX**: Low

### FIX 4 (HIGH): netcdf_convert_and_pyramid drops encoding on pyramid write

**WHAT**: Encoding built at line 1046 but not passed to `pyramid.to_zarr()` at line 1125.
**WHY**: NetCDF pyramids get default compression instead of explicit Blosc+LZ4. Violates P2.
**WHERE**: `services/handler_netcdf_to_zarr.py`, `netcdf_convert_and_pyramid`, line 1125
**HOW**: Add `encoding=encoding` parameter. Test with small pyramid to confirm DataTree accepts it.
**EFFORT**: Small
**RISK OF FIX**: Medium — pyramid DataTree encoding behavior needs validation

### FIX 5 (HIGH): Zarr passthrough bypasses dry_run in download_to_mount

**WHAT**: Passthrough returns at line 124 before dry_run check at line 159.
**WHY**: Combined with Fix 2, entire Zarr path ignores dry_run.
**WHERE**: `services/zarr/handler_download_to_mount.py`, `zarr_download_to_mount`, lines 116-130
**HOW**: Move dry_run awareness into passthrough response.
**EFFORT**: Small
**RISK OF FIX**: Low

---

## Accepted Risks

1. **`needs_rechunk` only checks first data variable's chunks** — heterogeneous chunking is rare in real geospatial data. Revisit when ingesting from new providers.
2. **Three spatial extent extraction implementations** — DRY violation but zero functional risk. Revisit if a fourth appears.
3. **`az://` vs `abfs://` URL scheme divergence** — adlfs treats both identically. Revisit during cleanup pass.
4. **No pre-cleanup in convert_and_pyramid and generate_pyramid** — `mode="w"` overwrites metadata, orphan chunks waste storage but don't corrupt reads. Revisit if storage costs matter.
5. **Encoding clear applies to ALL variables including coordinates** — harmless for small coord arrays. Revisit if a coordinate needs preserved encoding.

---

## Architecture Wins

1. **Cloud-native Zarr passthrough** — `.zarr` suffix detection returns `abfs://` URL, avoids downloading hundreds of chunk files. `is_cloud_source()` centralised in `etl_mount.py`.
2. **YAML workflow with conditional routing** — `detect_type` cleanly separates NC vs Zarr paths. Optional dependency syntax (`"convert_and_pyramid?"`) handles path convergence at register.
3. **`_build_zarr_encoding` shared builder** — single source of truth for chunks, codecs, format-aware encoding. Used by both rechunk and NC convert.
4. **Rechunk-skip optimisation** — checks `current_chunks` against `ACCEPTABLE_SPATIAL_CHUNKS` before heavy work. Zero additional I/O.
5. **`BlobRepository.get_xarray_storage_options()`** — declared canonical credential source. Handlers that use it correctly demonstrate the pattern.

---

## Alpha/Beta/Gamma/Delta Full Reports

### Alpha (Data Integrity)
- 7 strengths, 3 HIGH (H1: cross-zone creds, H2: missing credential, H3: cross-product spatial matching), 5 MEDIUM, 3 LOW
- 5 assumptions (same storage account, .zarr suffix convention, no concurrent writes, CRS preservation, consolidated metadata correctness)
- 6 recommendations (zone-aware creds, get_xarray_storage_options, paired spatial matching, zarr_passthrough field, data_vars encoding scope, pass source_zone through YAML)

### Beta (Flow Control)
- 12 verified safe patterns (return contracts, conditional routing, optional deps, dataset close, finalize passthrough, idempotent cleanup, strict param resolution, centralised cloud detection, traceable passthrough)
- 1 CRITICAL (cross-zone credential failure), 2 HIGH (rechunk ignores dry_run, passthrough bypasses dry_run), 2 MEDIUM (missing credential, no pre-cleanup)
- 2 risks (credential expiry during long rechunk, consolidated retry swallows errors)
- 3 edge cases (Zarr without .zarr suffix, rechunk skip + pyramid failure, empty Zarr store)

### Gamma (Contradiction Finder)
- 2 contradictions: both resolved (Alpha/Beta imprecise on same bug; Alpha M1 dataset leak is speculative)
- 2 agreement reinforcements: cross-zone credentials (HIGHEST CONFIDENCE), missing credential key
- 9 blind spots: LoggerFactory migration missed (BLIND-1), 3 spatial extent implementations (BLIND-2), no pre-cleanup in convert_and_pyramid (BLIND-3), encoding dropped on pyramid write (BLIND-4), rechunk ignores dry_run (BLIND-5), passthrough bypasses dry_run (BLIND-6), register release_id logging (BLIND-7), STAC xarray:open_kwargs credential design (BLIND-8 — NOT A BUG), dim name normalization inconsistency (BLIND-9)
- Constitution violations: P1 (dry_run), S1.5 (auth), P11 (traceable state), P2 (deterministic views), P6 (composable units), S3.3 (exception swallowing)

### Delta (Final Arbiter)
- Top 5 fixes (all Small effort, 4 Low risk, 1 Medium risk)
- 5 accepted risks with revisit triggers
- 5 architecture wins to preserve
