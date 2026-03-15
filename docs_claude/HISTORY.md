# Project History

**Last Updated**: 14 MAR 2026 (v0.10.2.1)
**Active Log**: FEB - MAR 2026
**Rolling Archive**: When this file exceeds ~600 lines, older content is archived with a UUID filename.

**Archives** (chronological):
- [HISTORY_26e76e95.md](./HISTORY_26e76e95.md) - Sep-Nov 2025 (4,500+ lines)
- [HISTORY_ARCHIVE_DEC2025.md](./HISTORY_ARCHIVE_DEC2025.md) - TODO.md cleanup archive
- [HISTORY_e1fc3ce2.md](./HISTORY_e1fc3ce2.md) - DEC 2025 - JAN 2026

This document tracks completed architectural changes and improvements to the Azure Geospatial ETL Pipeline.

---

## 14 MAR 2026: PostgreSQL Repository Decomposition (v0.10.2.0) ✅

**Status**: ✅ **COMPLETE** — Deployed, COMPETE reviewed, SIEGE regression-free

### What Changed

Decomposed the `PostgreSQLRepository` god class (1,530 lines, 6 concerns, 22 subclasses) into composable components via internal composition. Zero breaking changes to the 41+ factory consumers.

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `infrastructure/db_auth.py` | 326 | `ManagedIdentityAuth` — token acquisition, connection string building, auth priority chain |
| `infrastructure/db_connections.py` | 260 | `ConnectionManager` — pooled/single-use routing, circuit breaker, transient retry |
| `infrastructure/db_utils.py` | 117 | Shared utilities — psycopg3 type adapters, JSONB parsing, connection string redaction |

### Modified Files

| File | Change |
|------|--------|
| `infrastructure/postgresql.py` | Reduced from ~1,530 to ~820 lines. Delegates auth to `ManagedIdentityAuth`, connections to `ConnectionManager`. `conn_string` is now a `@property`. |
| `infrastructure/connection_pool.py` | Imports from `db_utils`, thread-safety fixes for orphan drain, pool config from config layer |
| `infrastructure/pgstac_bootstrap.py` | Connection string redaction via `redact_connection_string()` |
| `config/database_config.py` | Added `pool_min_size`, `pool_max_size` fields |
| `config/external_config.py` | Added `db_password` field (routed through config, not `os.environ`) |

### Validation

- **COMPETE Run 42**: 15 findings fixed (2 CRITICAL: plaintext token logging, false-positive auth error markers), 5 accepted risks, 4 deferred
- **SIEGE Run 17** (Run 43): 101/109 = 92.7% pass rate. Zero regressions. ManagedIdentityAuth, ConnectionManager (pool + single-use), circuit breaker (856 successes, 0 failures), type adapters all working.
- **Schema rebuilt**: 22 enums, 27 tables, 121 indexes, 5 functions, pgSTAC 0.9.8

### Design Documents

- `V10_POSTGRES.md` — Knowledge repository
- `V10_DECISIONS.md` — Accepted risks and deferred items
- `docs/superpowers/specs/2026-03-14-postgresql-repository-decomposition-design.md` — Design spec
- `docs/agent_review/agent_docs/COMPETE_POSTGRESQL_DECOMPOSITION.md` — COMPETE review
- `docs/agent_review/agent_docs/SIEGE_RUN_17.md` — SIEGE regression report

---

## 13 MAR 2026: Connection Pool Hardening (v0.10.1.0-v0.10.1.1) ✅

**Status**: ✅ **COMPLETE** — Defensive DB hardening for Docker worker

### Changes

- **Circuit breaker**: 3 failures in 10s → OPEN (block 30s) → HALF_OPEN → CLOSED. Prevents cascading DB failures.
- **Orphan-and-sweep pool pattern**: Token refresh orphans old pool (in-flight connections preserved), janitor sweeps at next refresh cycle. 3-layer defense: max_lifetime → server idle timeout → pool drain.
- **Pool health check**: `check=ConnectionPool.check_connection` pings before checkout, discards dead connections.
- **Transient retry**: `_TRANSIENT_MARKERS` frozenset for connection-level retry on SSL/network errors.
- **Thread-safety**: `_drain_orphaned_pools()` moved inside `_pool_lock` in `recreate_pool()` and `shutdown()`.

---

## 10 MAR 2026: Split Views — Single File to Multiple TiPG Endpoints (v0.10.0.2) ✅

**Status**: ✅ **COMPLETE** — Verified end-to-end in production
**Priority**: P2 — Most critical multi-table workflow (one table, N category-based views)

### What It Does

A single vector file is uploaded to one PostGIS table, then a categorical column (e.g., `quadrant`, `admin_level`, `land_type`) generates N PostgreSQL VIEWs. Each view is automatically discovered by TiPG as an independent OGC Features collection with its own endpoint.

### How To Use

Submit a standard `vector_docker_etl` job with `split_column` parameter:

```json
{
  "blob_name": "admin_boundaries.geojson",
  "file_extension": "geojson",
  "table_name": "admin_boundaries",
  "split_column": "admin_level"
}
```

This creates:
- `geo.admin_boundaries` — base table (all features)
- `geo.admin_boundaries_admin_level_0` — VIEW for admin_level=0
- `geo.admin_boundaries_admin_level_1` — VIEW for admin_level=1
- etc.

### Constraints

- **MAX_SPLIT_CARDINALITY = 20** — hard cap on distinct values
- **Allowed types**: text, varchar, integer, smallint, bigint, boolean (NOT float/geometry/json)
- **View naming**: `{table}_{column}_{value}`, truncated to PostgreSQL's 63-char identifier limit
- **Idempotent**: `CREATE OR REPLACE VIEW` + catalog cleanup on overwrite
- **CASCADE cleanup**: `DROP TABLE ... CASCADE` removes dependent views

### Implementation (7 files, 586 insertions)

| File | Change |
|------|--------|
| `services/vector/view_splitter.py` | NEW — validate, discover, create views, register catalog (~370 lines) |
| `services/handler_vector_docker_complete.py` | Phase 3.7 split views block + return dict fix |
| `services/vector/postgis_handler.py` | `DROP TABLE ... CASCADE` + cleanup stale view metadata |
| `services/vector/__init__.py` | Export split view functions |
| `core/models/processing_options.py` | `split_column` + `split_values` fields |
| `services/platform_translation.py` | Pass `split_column` to job params |
| `jobs/vector_docker_etl.py` | `split_column` in schema + passthrough |

### Verification (10 MAR 2026)

Test: `11_categorized.geojson` (3,301 H3 hex polygons) with `split_column: "quadrant"` (4 values: NE, NW, SE, SW)

| Collection | Features | TiPG Status |
|------------|----------|-------------|
| `geo.split_test_quadrant` (base) | 3,301 | Live |
| `geo.split_test_quadrant_quadrant_ne` | 825 | Live |
| `geo.split_test_quadrant_quadrant_nw` | 826 | Live |
| `geo.split_test_quadrant_quadrant_se` | 825 | Live |
| `geo.split_test_quadrant_quadrant_sw` | 825 | Live |

Sum of views = 3,301 (matches base table exactly).

### Bug Fixed During Deployment

`NameError: name 'split_views_result' is not defined` — variable was scoped inside `_process_single_table()` but referenced in outer `vector_docker_complete()`. Fixed by including `split_views` in the inner function's return dict.

---

## 10 MAR 2026: Multi-Source Vector ETL — P1 + P3 (v0.10.0.1) ✅

**Status**: ✅ **IMPLEMENTED** — Code complete, merged to master, deployed. End-to-end testing pending.
**Design**: `docs/plans/2026-03-08-multi-source-vector-design.md`

### What It Does

- **P1 (Multi-file)**: N files submitted together → N PostGIS tables, each a TiPG endpoint
- **P3 (GPKG multi-layer)**: 1 GeoPackage with N named layers → N PostGIS tables

### Implementation (11 files, 1,712 insertions)

#### New Files (4)

| File | Purpose |
|------|---------|
| `jobs/vector_multi_source_docker.py` | Job definition (237 lines) |
| `services/handler_vector_multi_source.py` | Handler: loops over sources, delegates to existing helpers (573 lines) |
| `jobs/unpublish_vector_multi_source.py` | 3-stage symmetric unpublish (321 lines) |
| `services/unpublish_handlers.py` | +166 lines: `inventory_vector_multi_source()` handler |

#### Modified Files (7)

| File | Change |
|------|--------|
| `infrastructure/validators.py` | +213 lines: `multi_source_mode` + `source_count_limit` validators |
| `core/models/processing_options.py` | `layer_names: Optional[List[str]]` with mutual exclusivity validator |
| `core/models/platform.py` | `is_vector_collection` property |
| `config/defaults.py` | `MAX_VECTOR_SOURCES = 10`, docker task routing |
| `services/platform_translation.py` | Route multi-source requests to new job type |
| `jobs/__init__.py` | Register both new jobs |
| `services/__init__.py` | Register both new handlers |

### Testing Status

| Pattern | Status | Notes |
|---------|--------|-------|
| P1 (multi-file) | 🔲 Needs test data | Requires 2+ GeoJSON files in wargames container |
| P3 (GPKG multi-layer) | 🔲 Needs test data | Requires GPKG with confirmed multiple layers |

---

## 09 MAR 2026: Zarr v3 Consolidated Metadata Fix (v0.9.16.1) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: ZARR_NOTES.md investigation — ERA5 rechunk store invisible to TiTiler

### The Problem

`ds.to_zarr(..., consolidated=True)` for Zarr v3 writes an empty `consolidated_metadata.metadata: {}` block. xarray trusts this on read and concludes the store has zero variables — silently returning nothing. Worse than omitting consolidated metadata entirely (which would cause xarray to scan).

### The Fix

Explicit `zarr.consolidate_metadata(store)` call after every `ds.to_zarr()` for `zarr_format == 3`. Uses `FsspecStore.from_url()` with the same storage_options already in scope.

### Files Modified

| File | Change |
|------|--------|
| `services/handler_ingest_zarr.py` | `zarr.consolidate_metadata()` after rechunk write |
| `services/handler_netcdf_to_zarr.py` | `zarr.consolidate_metadata()` after convert write |

### Verification

Both CMIP6 tasmax and ERA5 small-sample rechunk jobs produce visible variables on TiTiler `/xarray/variables` endpoint and render tiles (HTTP 200).

---

## 08-09 MAR 2026: Zarr Pipeline Observability — Tier 1 & Tier 2 (v0.9.16.0) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: 27GB ERA5 rechunk job had 30+ min "black hole" — only memory watchdog pulse visible during `ds.to_zarr()`

### Achievement

Added progress logging (Tier 1) and structured CHECKPOINT events (Tier 2) to all zarr pipeline handlers. `JobEventType.CHECKPOINT` (already in schema) now emitted at operation boundaries.

### Tier 1 — Inline Progress Logging

| Handler | Logs Added |
|---------|-----------|
| `ingest_zarr_validate` | After `xr.open_zarr()` — vars, blob count, dims |
| `ingest_zarr_copy` | Every ~10% of blob loop — `copied/total (pct%) [elapsed]` |
| `ingest_zarr_rechunk` | At each phase: zarr_opened, rechunk_applied, pre_cleanup, write_started (with chunk count estimate), write_complete (with timing) |
| `netcdf_convert` | After dataset open (file count, vars, dims) + write_started/write_complete with timing |

### Tier 2 — Structured CHECKPOINT Events

`_emit_checkpoint(params, name, data)` helper wraps `JobEventRepository.record_task_event()` with fail-safe. Duplicated in both handler files (avoids circular import).

| Handler | Checkpoints |
|---------|------------|
| `ingest_zarr_copy` | `copy_started`, `copy_progress` (every ~10%), `copy_complete` |
| `ingest_zarr_rechunk` | `zarr_opened`, `rechunk_applied`, `pre_cleanup_done`, `zarr_write_started`, `zarr_write_complete` |
| `netcdf_convert` | `dataset_opened`, `zarr_write_started`, `zarr_write_complete` |

### Platform Status Integration

| Change | Location |
|--------|----------|
| `progress` field on default status (when `job_status == "processing"`) | `trigger_platform_status.py` |
| `checkpoints` array in `?detail=full` response | `trigger_platform_status.py` |
| `_get_latest_checkpoint()` + `_get_latest_checkpoints()` helpers | `trigger_platform_status.py` |

### Files Modified (3 files)

| File | Changes |
|------|---------|
| `services/handler_ingest_zarr.py` | `_emit_checkpoint()` helper + logging + events in validate, copy, rechunk |
| `services/handler_netcdf_to_zarr.py` | `_emit_checkpoint()` helper + logging + events in netcdf_convert |
| `triggers/trigger_platform_status.py` | Checkpoint helpers + `progress` field + `detail.checkpoints` |

---

## 08 MAR 2026: SIEGE Run 13-14 Fixes (v0.9.14.4 → v0.9.16.1) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: SIEGE Runs 13-14 (Runs 38, 40)

### SIEGE Run 13 Fixes (v0.9.14.4, 07 MAR 2026)

| Bug | Fix | File |
|-----|-----|------|
| **SG13-1** | `_build_zarr_encoding()` format-aware — v2: `numcodecs.Blosc`+`"compressor"`, v3: `BloscCodec`+`"compressors"` | `handler_netcdf_to_zarr.py` |
| **SG13-4** | Three-tier container inference in `_build_outputs_block()` — cog result → zarr URL → blob_path prefix | `trigger_platform_status.py` |
| **SG13-6** | Same root cause as SG13-1 — `zarr_format` param controls v2/v3 output | Multiple |

### SIEGE Run 14 Fixes (v0.9.16.0-16.1, 08 MAR 2026)

| Bug | Fix | File |
|-----|-----|------|
| **SG14-1** | STAC URLs gated behind `approval_state == 'approved'` — null pre-approval | `trigger_platform_status.py` |
| **SG14-2** | `_resolve_release()` path 3 operation-aware for revoke — falls back to `get_latest()` | `trigger_approvals.py` |
| **SG14-3** | Catalog URLs use `/vsiaz/` (raster) and `abfs://` (zarr) — consistent with status | `platform_catalog_service.py` |
| **SG14-5** | Unpublish accepts `reviewer` as standard field — `deleted_by` deprecated | `unpublish.py` |

### Also Fixed

- **AUD-R1-1**: `row_factory=dict_row` on 3 cursors in `trigger_approvals.py` — bulk status lookup was returning `lookup_error: true`

### Remaining Known Bugs

| Bug | Severity | Description |
|-----|----------|-------------|
| ID-1 | MEDIUM | No authorization model on approvals (design limitation) |
| SG13-2 | MEDIUM | Catalog lookup requires version_id — no "get latest" path |
| SG13-3 | MEDIUM | TiTiler tilejson URLs missing WebMercatorQuad path segment in catalog |
| SG13-5 | LOW | Unpublish with force_approved fails on STAC collection naming mismatch |
| SG11-1 | LOW | version_id not validated against version_ordinal (cosmetic) |
| PRV-8 | LOW | XSS in stored free-text fields (safe at API, dangerous in UI) |
| PRV-9 | LOW | 404 instead of 405 for unsupported HTTP methods (Azure Functions limitation) |
| SG-9 | LOW | dbadmin/stats returns 404 |
| DIAG-1 | LOW | dbadmin/diagnostics/all returns 404 |

---

## 06 MAR 2026: Remaining MEDIUM Bug Fixes — PRV-3, PRV-7, SG2-1 (v0.9.14.3) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: ADVOCATE/TOURNAMENT/SIEGE agent findings — last 3 open MEDIUM bugs

### Fixes

| Bug | Fix | File |
|-----|-----|------|
| **PRV-3** | Max-length validation on free-text fields: `reviewer` ≤ 200 chars, `reason`/`notes` ≤ 2000 chars. Applied to all 3 handlers (approve, reject, revoke). | `triggers/trigger_approvals.py` |
| **PRV-7** | DDH identifier fallback in unpublish Option 4. When `data_type` is explicit but no direct identifiers provided, generates `table_name` or `stac_item_id` from `dataset_id`/`resource_id`/`version_id`. | `triggers/platform/unpublish.py` |
| **SG2-1** | Unpublish now accepts `release_id` (Option 2b) and `version_ordinal` + DDH identifiers (Option 3b). Added to `_UNPUBLISH_FIELDS` allowlist. Release-based lookup resolves data_type from parent Asset. | `triggers/platform/unpublish.py` |

### Also Closed (Already Fixed/Mitigated)

| Bug | Status | Rationale |
|-----|--------|-----------|
| **PRV-10** | Already fixed | ERH-12/13 aligned error shapes between `/submit` and `/approve` |
| **SG-6** | Already fixed | All 5 COMPETE fixes implemented — `stac_item_json` patched at approval time |
| **SG6-L3** | Mitigated | Orphan auto-cleanup on resubmit + compensating delete on job-create failure |

### Also Verified Fixed (CRITICALs — reproduced 06 MAR 2026)

| Bug | Status | Evidence |
|-----|--------|----------|
| **PRV-1** | ✅ Fixed | Malformed JSON to /approve, /reject, /revoke all return 400 `ValidationError`. `(ValueError, json.JSONDecodeError)` catch in all 3 handlers. |
| **LA-1/SG5-1** | ✅ Fixed | Approving a `processing_status=failed` release returns 400 `"Cannot approve: processing_status is 'failed'"`. 4 guards: soft check (service layer), hard SQL WHERE, stale ordinal guard, newer active ordinal query. |

### Remaining Known Bugs

| Bug | Severity | Description |
|-----|----------|-------------|
| RCH-1 | HIGH | Zarr rechunk fails — `dask` not in Docker worker requirements |
| PRV-2 | HIGH | SSRF info leak — URL in container_name exposes Azure Storage errors |
| LA-2 | MEDIUM | Unpublish dry_run accepts non-approved releases |
| ID-1 | MEDIUM | No authorization model on approvals (design limitation) |
| SEQ5-1 | MEDIUM | NetCDF handler can't find .nc files in Docker mount path (infra) |
| SG11-1 | LOW | version_id not validated against version_ordinal (cosmetic) |
| PRV-8 | LOW | XSS in stored free-text fields (safe at API, dangerous in UI) |
| PRV-9 | LOW | 404 instead of 405 for unsupported HTTP methods (Azure Functions limitation) |
| SG-9 | LOW | dbadmin/stats returns 404 |
| DIAG-1 | LOW | dbadmin/diagnostics/all returns 404 (new regression) |

---

## 05 MAR 2026: Zarr Chunking Optimization for Tile Serving (v0.9.13.4) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: ZARR_MAGIC.md spec — spatial 256×256, time 1, Blosc+LZ4 for tile serving

### Achievement

Wired optimized chunking into both Zarr pipelines (`netcdf_to_zarr` and `ingest_zarr`) so output Zarr stores are chunk-aligned for performant tile serving via TiTiler-xarray.

### Design

- **`netcdf_to_zarr`**: Always applies optimized chunking (conversion — we control output)
- **`ingest_zarr`**: Optional `rechunk` flag. When true, Stage 2 reads source Zarr via xarray and rechunks instead of fan-out blob copy. Stub comment for future dynamic analysis (skip if already optimal).
- **Scope**: Chunking + compression only. Pyramids deferred.

### Changes (8 files)

| File | Change |
|------|--------|
| `core/models/processing_options.py` | Added 5 fields to `ZarrProcessingOptions`: `spatial_chunk_size` (64-1024, default 256), `time_chunk_size` (1-100, default 1), `compressor` (lz4/zstd/none), `compression_level` (1-9), `rechunk` (bool) |
| `services/platform_translation.py` | Passes chunking params to `netcdf_to_zarr` (4 keys) and `ingest_zarr` (5 keys incl. `rechunk`) |
| `jobs/netcdf_to_zarr.py` | Added 4 entries to `parameters_schema` + passes all 4 to Stage 4 task params |
| `jobs/ingest_zarr.py` | Added 5 entries to `parameters_schema` + conditional Stage 2: `rechunk=True` → single `ingest_zarr_rechunk` task, `False` → original fan-out blob copy |
| `services/handler_netcdf_to_zarr.py` | Added `_build_zarr_encoding()` helper (detects spatial/time dims, builds `numcodecs.Blosc`, per-variable encoding). Wired into `netcdf_convert` with `ds.chunk()` + `encoding=` |
| `services/handler_ingest_zarr.py` | Added `ingest_zarr_rechunk` handler — opens source Zarr, calls `_build_zarr_encoding()`, rechunks, writes to silver |
| `services/__init__.py` | Registered `ingest_zarr_rechunk` in handler registry |
| `config/defaults.py` | Added `ingest_zarr_rechunk` to `DOCKER_TASKS` routing |

### `_build_zarr_encoding()` Helper

Module-level function in `handler_netcdf_to_zarr.py`, imported by `handler_ingest_zarr.py`:
1. Detects spatial dims (`lat/latitude/y`, `lon/longitude/x`) and time dim (`time/t`)
2. Builds `target_chunks` dict — clamps each to `min(chunk_size, dim_size)`
3. Builds `numcodecs.Blosc` compressor (or None for "none")
4. Returns `(target_chunks, encoding)` for `ds.chunk()` and `ds.to_zarr(encoding=...)`
5. Only encodes data vars, not coordinate vars

---

## 04 MAR 2026: Remove `is_latest` Denormalized Flag (v0.9.13.0) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: F-01 MEDIUM — approve+revoke race condition on `is_latest`

### Design Decision

Replaced the mutable `is_latest` boolean with a computed approach: "latest" = `MAX(version_ordinal)` via `ORDER BY version_ordinal DESC LIMIT 1`. Applied to both `app.asset_releases` and `geo.b2c_routes`/`geo.b2b_routes`.

**Rationale**: `is_latest` was a denormalized flag requiring two-phase flip logic (`clear_latest` → `set_latest`) across multiple methods. Concurrent approve+revoke could leave it inconsistent (F-01). In an ETL architecture where consistency trumps query speed, the computed approach is correct by construction — no flip, no race.

### Changes (15 files)

| Area | Changes |
|------|---------|
| **Model** (`core/models/asset.py`) | Removed `is_latest` field, replaced `idx_releases_latest` partial unique index with `idx_releases_latest_approved` composite |
| **Model** (`core/models/geo.py`) | Removed `is_latest` field from route models, replaced `idx_b2c/b2b_routes_latest` partial unique indexes with descending `slug_ordinal` indexes |
| **Release Repository** | Deleted `flip_is_latest()` (~60 lines), rewrote `get_latest()`, simplified `approve_release_atomic()` (removed Step 1 is_latest clear), simplified `rollback_approval_atomic()` (removed Step 2 sibling promotion), removed from `update_revocation()`, `update_version_assignment()`, `_INSERT_COLUMNS`, `_build_insert_values`, `_row_to_model` |
| **Route Repository** | Full rewrite (401→213 lines). Deleted `upsert_as_latest()`, `clear_latest()`, `promote_next_latest()`. `get_by_slug(version='latest')` now uses `ORDER BY version_ordinal DESC LIMIT 1` |
| **Approval Service** | Deleted `if release.is_latest:` promotion block (~30 lines) from `revoke_release()`. Route creation uses `upsert_route()` instead of `upsert_as_latest()` |
| **Catalog/Triggers/UI** | Removed `is_latest` from 5 response dicts, LATERAL subqueries replace `LEFT JOIN ON is_latest=true` in catalog listing and platform request listing, removed from web interface display |

### Net Effect

- ~250 lines deleted (more removed than added)
- F-01 resolved by construction
- Simpler approve/revoke flows (no flip logic)
- Route repository cut in half

**Requires**: Schema rebuild (`action=rebuild&target=app`) + geo schema rebuild for route index changes.

---

## 04 MAR 2026: ADVOCATE MEDIUM Fixes (v0.9.12.2) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: ADVOCATE Run 31 findings — 5 remaining MEDIUM items (ADV-11, 12, 15, 17, 18)

### Changes

| ADV | Fix | Files |
|-----|-----|-------|
| ADV-11 | Idempotent submit response now includes `job_type` — matches fresh 202 shape | `services/platform_response.py`, `triggers/platform/submit.py` |
| ADV-12 | Catalog 500 fixed — `list_dataset_unified()` cursor missing `row_factory=dict_row` | `services/platform_catalog_service.py`, `triggers/trigger_platform_catalog.py` |
| ADV-15 | OpenAPI spec bumped to 0.9.12, +4 missing endpoints, stale `raster_api/openapi/` copy deleted | `openapi/platform-api-v1.json` |
| ADV-17 | STAC materialization cleans up empty shell collections on item failure | `services/stac_materialization.py` |
| ADV-18 | Status list enriched with `processing_status`, `approval_state`, `clearance_state` via LEFT JOIN | `infrastructure/platform.py` |

### ADVOCATE Run 31 Resolution Summary

Of 25 original findings: **18 fixed** (2 CRITICAL, 7 HIGH, 9 MEDIUM), 7 remain as known bugs (5 MEDIUM, 1 LOW, 1 INFO). DX score estimated improvement from 37% to ~65%.

---

## 04 MAR 2026: Platform API Cleanup (v0.9.12.1) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: ADVOCATE Run 31 findings (ADV-1, ADV-3)

### Achievement

Cleaned platform API surface: removed dead endpoints, normalized error responses, fixed broken URLs.

### Changes

| Change | Details | Commits |
|--------|---------|---------|
| Remove 5 dead endpoints | `/lineage`, `/validate`, 3x deprecated 410s — ~568 lines deleted | `88d7793` |
| Normalize error responses (ADV-3) | All `/platform/*` endpoints guarantee `{success, error, error_type}` on errors | `bfebb32` |
| Remove from OpenAPI specs | Removed validate and lineage from spec docs | `2dea466` |
| Fix ADV-1: dead `job_status_url` | Removed dead field, made `monitor_url` absolute | `9d96e09` |

---

## 04 MAR 2026: Release Audit Trail (v0.9.12.1) ✅

**Status**: ✅ **COMPLETE**
**Reviewed by**: COMPETE Run 33

### Achievement

Append-only audit log for release lifecycle events. Every approval, revocation, and overwrite is permanently recorded with full context snapshot.

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `ReleaseAuditEvent` model | `core/models/release_audit.py` | Pydantic model + `ReleaseAuditAction` enum |
| `ReleaseAuditRepository` | `infrastructure/release_audit_repository.py` | Append-only persistence |
| Audit emission | `services/asset_approval_service.py` | APPROVED, REVOKED events inline with mutations |
| Overwrite audit | `infrastructure/release_repository.py` | OVERWRITTEN event via `_record_audit_inline()` |

### Key Design Decisions

- **Single-transaction audit** (BS-4 fix): Audit write happens in same transaction as the mutation it records — no phantom events
- **Inline recording** via `_record_audit_inline()` — SQL INSERT embedded in mutation methods, not separate repo calls
- **Registered in DDL generator** — table created automatically via `action=ensure`

### COMPETE Run 33 Fixes Applied

| ID | Severity | Fix |
|----|----------|-----|
| BS-1 | CRITICAL | `get_overwrite_candidate()` — broader lookup including REVOKED releases |
| F-2 | HIGH | Remove `dict(zip(columns, dict_row))` garbage in 4 audit read methods |
| BS-4 | HIGH | Single-transaction audit via `_record_audit_inline()` |
| AR-3 | HIGH | WHERE state guard on `update_overwrite()` |
| F-4 | HIGH | Fix `INTERVAL '%s hours'` → `make_interval(hours => %s)` for psycopg3 |
| AR-1 | HIGH | Register `ReleaseAuditRepository` in `infrastructure/__init__.py` |

---

## 03-04 MAR 2026: Stale Ordinal Guard & In-Place Revision (v0.9.12.1) ✅

**Status**: ✅ **COMPLETE**
**Verified by**: REFLEXION Run 32

### Achievement

Fixed inoperative stale-ordinal guard and enabled in-place ordinal revision (overwriting REVOKED releases).

### Changes

| Change | Commit | Details |
|--------|--------|---------|
| Fix positional row indexing | REFLEXION Run 32 P1 | `row[0]`→`row['release_id']` in `has_newer_active_ordinal()` — was silently crashing on `dict_row` cursors |
| Stale ordinal exemption | `56d8704` | Exempt in-place revision (revision > 1) from stale ordinal check |
| Accept REVOKED for overwrite | `ebaa61d` | `can_overwrite()` now accepts REVOKED state for in-place ordinal revision |
| ADV-2 approval guard verified | REFLEXION Run 32 | Both Python guard + SQL WHERE clause confirmed working — CANNOT be bypassed |

---

## 02-03 MAR 2026: Observability & Reliability (v0.9.12.0) ✅

**Status**: ✅ **COMPLETE**

### Changes

| Change | Commit | Details |
|--------|--------|---------|
| DB token refresh fix | `302f1a1` | Docker worker: refresh on startup + per-message freshness check |
| Orphaned release cleanup | `d6e3210` | Compensating cleanup if job creation fails after release creation |
| OBSERVATORY diagnostic gaps | `81c52cc` | 3 P0 bugs fixed + 5 observability enhancements |

---

## 02 MAR 2026: Zarr Service Layer (v0.9.11.8-11.10) ✅

**Status**: ✅ **COMPLETE**

### Achievement

Native Zarr ingest pipeline alongside existing VirtualiZarr, plus xarray TiTiler URL injection for Zarr visualization.

### Components

| Component | Version | Details |
|-----------|---------|---------|
| IngestZarr job | v0.9.11.8 | 3-stage pipeline: validate → copy → register (`jobs/ingest_zarr.py`) |
| IngestZarr handlers | v0.9.11.8 | `services/handler_ingest_zarr.py` — validate, copy, register handlers |
| Pipeline routing | v0.9.11.8 | `submit.py` routes to `ingest_zarr` or `virtualzarr` based on `pipeline` field |
| xarray TiTiler URLs | v0.9.11.10 | `generate_xarray_tile_urls()` injected into STAC items at materialization |
| B2C/B2B route models | v0.9.11.10 | `core/models/` — URL resolution for service layer routing |
| .zarr auto-detection | v0.9.11.8 | Files ending `.zarr` automatically detected as zarr data type |

---

## 01-02 MAR 2026: Web Dashboard (v0.9.11.5) ✅

**Status**: ✅ **COMPLETE**
**Built by**: GREENFIELD Run 19 (initial), Run 24 (submit form)

### Achievement

HTMX-powered single-page dashboard replacing the legacy per-endpoint web interfaces for operational monitoring.

### Structure

| Tab | Sub-tabs | Key Features |
|-----|----------|------------|
| Platform | Requests, Approvals | Release table with approval actions, status badges |
| Jobs | Active, History | Job progress, task details, error display |
| Data | Storage, STAC, Queues | Zone-grouped container browser, blob listing, Service Bus peek/DLQ |
| System | Health, Config | Diagnostics overview |

### Key Details

- **Location**: `web_dashboard/` — 9 files, ~4,500 LOC
- **HTMX CDN**: Async load with `s.onload` callback for `htmx.process(document.body)`
- **Auto-refresh**: 15s on queue monitoring, 30s on active jobs
- **Submit form** (GREENFIELD Run 24): File browser with container/blob selection
- **P0/P1 fixes**: Applied from GREENFIELD Validator findings in v0.9.11.5

### Files

| File | Purpose |
|------|---------|
| `web_dashboard/__init__.py` | Blueprint registration |
| `web_dashboard/base_panel.py` | Shared `data_table()`, `status_badge()`, escaping utilities |
| `web_dashboard/platform_panel.py` | Platform requests + approval actions |
| `web_dashboard/jobs_panel.py` | Job monitoring + task details |
| `web_dashboard/data_panel.py` | Storage browser + STAC overview |
| `web_dashboard/system_panel.py` | Health + config diagnostics |
| `web_dashboard/queue_panel.py` | Service Bus monitoring |
| `web_dashboard/submit_panel.py` | File browser submit form |

---

## 01 MAR 2026: Web Interface Security Hardening (v0.9.11.0) ✅

**Status**: ✅ **COMPLETE**
**Scope**: 5 files in `web_interfaces/`

### Achievement

XSS hardening across all legacy web interfaces.

### Patterns Applied

| Pattern | Implementation |
|---------|---------------|
| Server-side HTML escaping | `html_mod.escape()` for all dynamic content in HTML context |
| Server-side JS escaping | `_js_escape()` static method on `BaseInterface` for JS single-quoted literals |
| Client-side escaping | `escapeHtml()` JS function wraps all API data before `innerHTML` assignment |
| URL validation | Protocol check (`/^https?:\/\//i.test(url)`) + `encodeURIComponent()` for path segments |
| Double-escape for JS-in-HTML | `onclick` handlers get JS-escaped then HTML-escaped |

### Also Identified

- ~11,500 lines (25%) dead/unreachable code in web_interfaces — metrics, integration, submit_raster, submit_vector, submit_raster_collection, plus orphan chain (platform, execution)
- `html` variable shadowing bug in `__init__.py` — renamed to `html_content`

---

## 01 MAR 2026: VirtualiZarr Pipeline Fixes (v0.9.11.6-11.8) ✅

**Status**: ✅ **COMPLETE**

### Fixes

| Fix | Commit | Details |
|-----|--------|---------|
| GAP-1, GAP-2, GAP-7 | `482c499` | NetCDF pipeline gaps for clean end-to-end run |
| SG6-L1 | `30e685d` | Replace scipy with netCDF4 engine for lazy metadata read |
| Validate handler | `f498230`, `8b0f79c` | Download NetCDF to temp file for netCDF4 engine |
| Combine stage | `885ab4c` | Pass full `abfs://` URL to `open_virtual_dataset` |
| scipy dependency | `fb6a078` | Added for kerchunk NetCDF3 chunking |

---

## 28 FEB 2026: VirtualiZarr Pipeline (v0.9.9.0) ✅

**Status**: ✅ **COMPLETE** (implemented earlier, fixes applied 28 FEB - 01 MAR)

### Achievement

5-stage NetCDF-to-Zarr pipeline using VirtualiZarr for lazy reference-based Zarr stores.

### Pipeline Stages

```
Stage 1: scan_netcdf_variables   → Extract variable metadata from NetCDF files
Stage 2: copy_netcdf_to_silver   → Copy raw NetCDF to silver storage
Stage 3: validate_netcdf         → Validate file integrity with netCDF4
Stage 4: combine_virtual_zarr    → Build virtual Zarr reference store
Stage 5: register_zarr_catalog   → Register in STAC catalog
```

### Key Files

- `jobs/virtualzarr.py` — Job definition (5 stages)
- `services/handler_virtualzarr.py` — All 5 stage handlers
- `jobs/unpublish_zarr.py` — Reverse pipeline (inventory → delete_blobs → cleanup)
- `services/unpublish_handlers.py` — Unpublish handlers including `inventory_zarr_item`

### CoreMachine Enhancement

- **Zero-task stage guard** in `core/machine.py` — when `create_tasks_for_stage` returns `[]`, stage auto-advances to next stage instead of hanging

---

## 26 FEB - 04 MAR 2026: Agent Review Campaign ✅

**Status**: ✅ **COMPLETE** (33 runs across 7 pipelines)
**Token usage**: ~6,564,653 instrumented tokens (Runs 9-33)
**Full log**: `docs/agent_review/AGENT_RUNS.md`

### Pipeline Summary

| Pipeline | Runs | Purpose |
|----------|------|---------|
| COMPETE | 13 (Runs 1-6, 9, 12, 19, 28-30, 33) | Adversarial code review — Alpha/Beta split + Gamma blind-spot finder + Delta judge |
| GREENFIELD | 4 (Runs 7-8, 10, 24) | Greenfield implementation — multi-agent build + validator |
| SIEGE | 9 (Runs 11, 13, 18, 20-23, 25-26) | Live API smoke testing — sequential HTTP scenario execution |
| REFLEXION | 5 (Runs 14-17, 32) | Targeted deep analysis — Reverse Engineer → Fault Injector → Patch Author → Judge |
| TOURNAMENT | 1 (Run 27) | Full-spectrum adversarial — golden-path + attacks + blind audit + boundary-value |
| ADVOCATE | 1 (Run 31) | B2B developer experience audit — friction log + REST dimension grading |

### Key Outcomes

- **SIEGE Runs**: Started at FAIL (11 findings), improved to 90.8% pass rate (52/54 steps)
- **TOURNAMENT Run 27**: 87.2% score, 0 state divergences, found PRV-1 CRITICAL (malformed JSON 500s)
- **ADVOCATE Run 31**: DX score 37% (pre-beta), 25 findings. Led to ADV-1/ADV-3 fixes in v0.9.12.1
- **REFLEXION Run 32**: Confirmed approval guard CANNOT be bypassed. Found stale-ordinal guard inoperative — fixed
- **COMPETE Run 33**: Release audit trail reviewed. BS-1 CRITICAL (REVOKED overwrite unreachable) fixed

### Bug Fix Tally

| Category | Fixed | By Design | Still Open |
|----------|-------|-----------|------------|
| CRITICAL | 6 | 0 | 0 |
| HIGH | 8 | 0 | 0 |
| MEDIUM | 7 | 3 | 10 |
| LOW | 3 | 1 | 3 |

---

## 23 FEB 2026: V0.9 Asset/Release Entity Split (v0.8.21 → v0.9.0.0) ✅

**Status**: ✅ **COMPLETE**
**Version jump**: v0.8.21.0 → v0.9.0.0

### Achievement

Split monolithic `GeospatialAsset` (identity + version + approval + processing in one row) into two entities:

```
Asset (stable identity container)
  └── AssetRelease (versioned artifact with lifecycle)
       ├── version_ordinal: 1, 2, 3...
       ├── approval_state: pending_review → approved/rejected → revoked
       ├── processing_status: pending → processing → completed/failed
       └── stac_item_json: cached STAC materialization
```

### Phases

| Phase | Description | Commit |
|-------|-------------|--------|
| 1a-c | Define Asset + AssetRelease models, register in DDL | `d7ee000`, `b2399d9`, `ea4d36a` |
| 2a-c | AssetRepositoryV2, ReleaseRepository, register in infra | `8480c27`, `9e3d274`, `6749ffe` |
| 3a-b | AssetServiceV2, AssetApprovalServiceV2 | `3b8f7e1`, `633c847` |
| 4a-d | Rewrite platform submit, approval, status, resubmit | `b2eec6f`, `e909f57`, `8ef055e`, `82ae46a` |
| 5a-e | Handlers, STAC caching, unpublish, catalog, validation | `a8c42eb`-`1a887f8` |
| 6a-c | Archive V0.8 entities, rename V2→canonical, update tests | `a850e88`-`4498c9c` |

### Key Design Decisions

- **STAC materialization deferred to approval** — cached dict on Release, written to pgSTAC only when approved
- **Version ordinal reservation** at submit time — guarantees ordinal even if processing fails
- **Ordinal naming** (`ord1`, `ord2`) replaces "draft" placeholder in blob paths
- **Forward foreign keys** — Release points to Asset (not reverse lookup)

---

## 23 FEB 2026: V0.9.1-9.2 UI Sweep + STAC Fixes ✅

**Status**: ✅ **COMPLETE**

### Changes

| Version | Change |
|---------|--------|
| v0.9.1.0 | Asset Versions interface, approval stats, navbar links, STAC V0.9 patterns |
| v0.9.2.0 | Fix STAC materialization bugs, raster ordinal naming, approval endpoints |
| v0.9.2.1 | Fix blob_path: store silver COG path on Release, not bronze input |
| v0.9.2.3 | Vector approve UI fix |

---

## 23 FEB 2026: Security Hardening (COMPETE Runs 1-6 Fixes) ✅

**Status**: ✅ **COMPLETE**

### Changes Applied

| ID | Category | Fix | Commit |
|----|----------|-----|--------|
| C3.1-C3.3 | SQL Injection | `sql.Identifier` for column names, schema, batch operations | `17f4370`-`a5ae176` |
| C5.1 | Access Control | Mode guard + query length limit on appinsights endpoint | `8030cdd` |
| C7.1-C7.2 | Error Leaks | Keyword args for DB connect, sanitize error messages, App Insights context | `bc2792b`, `fcc0ba4` |
| C8.1 | XSS | HTML-escape interface_name and exception in error page | `4266042` |
| C1.1-C1.3 | Correctness | StageResultContract, error_details field, transitions reconciliation | `73fe30f`-`5d32d35` |
| C4.1-C4.3 | Consistency | SHA256 hash includes job_type, JobBaseMixin enforcement, SQL composition | `8e3375f`-`713a83a` |
| C6.1 | Logic | `_resolve_release()` uses operation param for correct draft/approved resolution | `357c67f` |

---

## 22-23 FEB 2026: Vector Ordinal Naming (v0.8.22-23) ✅

**Status**: ✅ **COMPLETE**

### Achievement

Replaced "draft" placeholder with `ord{N}` in vector blob paths and identifiers. New version workflow with release ordinal reservation and defense-in-depth validation.

| Version | Change |
|---------|--------|
| v0.8.22.0 | New version workflow, release ordinal reservation, defense-in-depth |
| v0.8.23.0 | Vector ordinal naming: replace "draft" with `ord{N}` in paths |

---

## 19-20 FEB 2026: STAC as B2C Materialized View (v0.8.20) ✅

**Status**: ✅ **COMPLETE**

### Achievement

Deferred pgSTAC writes to approval time. STAC is now a materialized view for consumer discovery, not the source of truth.

- Block coexisting drafts, reset identity on overwrite
- Fix revoke-first workflow
- `api_requests` stale job_id fix: upsert on new version submission

---

## 18 FEB 2026: EN-TD.2 Phase 1 — psycopg3 Type Adapters (v0.8.19.2) ✅

**Status**: ✅ **COMPLETE**
**Trigger**: Production bug — `assign_version()` passed raw dict to psycopg3 `%s` param

### Achievement

Registered `JsonbBinaryDumper` for dict/list and custom `_EnumDumper` for Enum at both connection creation points. All repositories automatically inherit dict→JSONB and Enum→.value conversion.

### Files Modified

| File | Change |
|------|--------|
| `infrastructure/postgresql.py:108-125` | `_EnumDumper` class + `_register_type_adapters()` function |
| `infrastructure/postgresql.py:729` | Call in `_get_single_use_connection()` |
| `infrastructure/connection_pool.py:240-241` | Call in `_configure_connection()` |

### Phase 2 Also Done

- v0.8.19.3: Reverted bandaid `json.dumps()` in `asset_repository.update()` (`479b944`)

### Remaining (Phases 3-4)

- Phase 3: Remove ~50+ redundant `json.dumps()` calls across repos (harmless but noisy)
- Phase 4: Cleanup dead `to_dict()`, deprecated `json_encoders`, check `_parse_jsonb_column()`

---

## 28 FEB 2026: SIEGE Bug Fixes (v0.9.10.0 - v0.9.10.1) ✅

**Status**: ✅ **COMPLETE**

### SIEGE Run 1 Fixes (v0.9.10.0)

| ID | Severity | Fix |
|----|----------|-----|
| SG-1 | CRITICAL | STAC materialization ordering |
| SG-2 | HIGH | SQL error leak on approvals/status |
| SG-3 | HIGH | catalog/dataset returns 500 |
| SG-7 | MEDIUM | is_latest not restored after rollback |
| SG-8 | LOW | Inconsistent lineage 404 shape |
| SG-6 | MEDIUM | STAC naming mismatch + 4 bonus COMPETE Run 12 findings |

### REFLEXION Fixes (v0.9.10.1)

| Run | ID | Fix |
|-----|-----|-----|
| Run 14 | SG-3 | catalog/dataset 500 (deeper fix) |
| Run 15 | SG-5 | Unpublish blob deletion no-op |
| Run 16 | SG2-2 | Revoked release retains is_served=true |
| Run 17 | SG2-3 | Catalog API strips STAC 1.0.0 fields |

---

## 02 MAR 2026: Ad Hoc Bug Fixes (v0.9.11.10-11.11) ✅

**Status**: ✅ **COMPLETE**

| Version | ID | Fix |
|---------|-----|-----|
| v0.9.11.10 | OW1-F1 | `is_served=true` on pending_review — now only set at approval |
| v0.9.11.10 | SVC-F3 | Double container path in zarr URLs |
| v0.9.11.10 | REJ1-F1 | Rejection reason not surfaced in /status |
| v0.9.11.11 | PRV-1 | /approve, /reject, /revoke crash 500 on malformed JSON |
| v0.9.11.11 | PRV-2 | SSRF info leak via URL in container_name |

---

## 11 FEB 2026: V0.8 Approval Consolidation Complete ✅

**Status**: ✅ **COMPLETE** (All 5 Phases + Post-Migration)
**Epic**: E4 Data Governance
**User Story**: US 4.2

### Achievement

Consolidated approval state into GeospatialAsset as the single source of truth, eliminating the legacy DatasetApproval system. GeospatialAsset now serves as the DDD Aggregate Root with four orthogonal state dimensions: Revision, Approval, Clearance, Processing.

### Phases Completed

| Phase | Description | Date |
|-------|-------------|------|
| Phase 1 | Enhanced GeospatialAsset (REVOKED state, approval_notes, revocation audit fields) | 08 FEB 2026 |
| Phase 2 | Created AssetApprovalService (approve/reject/revoke/list/stats) | 08 FEB 2026 |
| Phase 3 | New /api/assets/{id}/approve\|reject\|revoke endpoints + query routes | 08 FEB 2026 |
| Phase 4 | Updated all active code paths; removed DatasetApproval from machine_factory | 08 FEB 2026 |
| Phase 5 | Schema cleanup - removed legacy DDL, archived legacy files, cleaned imports | 11 FEB 2026 |
| Post-Migration | Verified OpenAPI spec + docs landing page up to date | 11 FEB 2026 |

### Legacy Code Archived

Moved to `docs/archive/v0.7_approval/`:
- `approval_model.py` (DatasetApproval, ApprovalStatus)
- `approval_repository.py` (ApprovalRepository)
- `approval_service.py` (ApprovalService)

### Design Document

Full plan: `docs_claude/V0.8_APPROVAL_CONSOLIDATION.md`

---

## 10 FEB 2026: US 4.2.1 Approval-Aware Overwrite & Version Validation ✅

**Status**: ✅ **COMPLETE**

### Achievement

- Block overwrite if asset is APPROVED (must revoke first)
- Reset approval to pending_review on successful overwrite (not at submit time)
- Require approved predecessor for semantic version advances
- Bug fixes: v0.8.16.7-16.8 resolved approval reset timing and constraint violations

---

## 09 FEB 2026: V0.8.16 Forward FK Architecture ✅

**Status**: ✅ **COMPLETE**

### Achievement

Refactored platform status and approval workflows from reverse lookups to forward foreign keys:
- Before: `asset_repo.get_by_job_id(current_job_id)` (reverse lookups via job completion)
- After: `platform_request.asset_id` or `job.asset_id` (direct FKs set at job creation)
- Query param deprecation: `/api/platform/status?job_id=xxx` now returns 400

---

## 09 FEB 2026: BUG_REFORM Error Handling (All 6 Phases) ✅

**Status**: ✅ **COMPLETE**

### Achievement

- `ErrorCategory` enum (7 categories for blame assignment)
- `ErrorScope` enum (NODE vs WORKFLOW for DAG-ready classification)
- 47 error codes (up from 25)
- `error_id` generation for support ticket correlation
- Remediation messages for all user-fixable errors
- Docs: ERROR_CODE_REFERENCE.md, B2B_ERROR_HANDLING_GUIDE.md, ERROR_TROUBLESHOOTING.md

---
