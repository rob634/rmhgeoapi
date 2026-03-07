# COMPETE Run 39: Zarr/NetCDF Pipeline End-to-End Review

**Date**: 07 MAR 2026
**Pipeline**: COMPETE (Omega → Alpha + Beta → Gamma → Delta)
**Scope**: All Zarr and NetCDF pipelines — ingest_zarr, netcdf_to_zarr, virtualzarr, unpublish_zarr
**Scope Split**: Split C — Data Integrity (Alpha) vs Orchestration/Control Flow (Beta)
**Files Reviewed**: 28

---

## AGENTS

| Agent | Role | Focus | Files |
|-------|------|-------|-------|
| **Omega** | Scope Splitter | Chose Split C (Data vs Control) for ETL pipeline review | — |
| **Alpha** | Data Integrity | Handler logic, format encoding, metadata flow, register contracts | 8 files |
| **Beta** | Orchestration | Job definitions, stage wiring, mixin validation, parameter threading | 7 files |
| **Gamma** | Contradiction Finder | Cross-referenced Alpha/Beta, found blind spots, recalibrated | All |
| **Delta** | Final Arbiter | Verified top findings against code, produced final report | 5 files |

---

## EXECUTIVE SUMMARY

The Zarr/NetCDF pipeline subsystem is structurally sound and follows the project's established mixin/stage/handler contract consistently. However, five confirmed bugs require attention, two of which (pre-cleanup I/O on orchestrator, urlparse on abfs:// URLs) are operationally consequential. The `zarr_format` parameter is wired at the Pydantic model level and at the handler level but is severed at both the translation layer and the job `parameters_schema`, meaning users cannot actually select Zarr v2 via the platform API — the default v3 always wins silently. The register handlers report `success: True` even when STAC or output updates fail, which violates the handler return contract and risks the job completing with an incomplete release record.

---

## TOP 5 FIXES

### FIX 1: Move Pre-Cleanup from Orchestrator to Handler (CRITICAL)

**What**: Remove the blocking `delete_blobs_by_prefix()` call from `create_tasks_for_stage` (orchestrator code path). Cleanup should happen only in the handler (worker code path).

**Why**: `create_tasks_for_stage` runs on the orchestrator (Azure Function App). Network I/O here blocks the Service Bus message pump. If deletion succeeds but task creation fails afterward, silver-zarr data is destroyed with no recovery. In rechunk path, cleanup runs twice (orchestrator at line 225 AND handler at line 797).

**Where**: `jobs/ingest_zarr.py:221-225` — delete the `BlobRepository` import, instantiation, and `delete_blobs_by_prefix` call.

**How**: For the copy path (non-rechunk), add pre-cleanup to the first copy task only (add `"cleanup_before_copy": True` flag to chunk 0). For rechunk, the handler already has cleanup — just remove the orchestrator duplicate.

**Effort**: Medium (2-3 hours)

---

### FIX 2: Fix urlparse on abfs:// URLs in Zarr Unpublish (HIGH)

**What**: Replace `urlparse()` with simple string splitting for `abfs://` URLs.

**Why**: `urlparse("abfs://silver-zarr/dataset/resource")` puts `silver-zarr` into `netloc`, not `path`. Handler extracts container from `path`, getting `dataset` instead of `silver-zarr`. Unpublish finds zero blobs — orphan data remains. **Confirmed by running urlparse against actual STAC hrefs.**

**Where**: `services/unpublish_handlers.py:600-606`

**How**: Strip `abfs://` prefix, split on `/` — same pattern already used correctly in `handler_ingest_zarr.py:99-102`.

**Effort**: Small (30 minutes)

---

### FIX 3: Wire zarr_format Through Translation + Job Schema (HIGH)

**What**: Add `zarr_format` to both `platform_translation.py` output dicts AND both job `parameters_schema` definitions.

**Why**: Two stacked bugs: (1) translation omits `zarr_format` from return dict, AND (2) even if added, mixin strips it because it's missing from `parameters_schema`. The `job_params.get("zarr_format", 3)` fallback always fires — users literally cannot request Zarr v2. Silent fallback violates "no backward compatibility" principle.

**Where**:
- `services/platform_translation.py:457-475` and `495-516`
- `jobs/ingest_zarr.py` and `jobs/netcdf_to_zarr.py` — add to `parameters_schema`

**Effort**: Small (45 minutes)

---

### FIX 4: Fail Register Handlers on Partial DB Failure (HIGH)

**What**: Return `success: False` when any DB update (STAC JSON, outputs, status) fails.

**Why**: Currently `update_stac_item_json` returning `False` logs a warning but handler returns `success: True`. Job completes with broken release record — approval will fail or produce empty STAC entry.

**Where**:
- `services/handler_ingest_zarr.py:628-672` (ingest_zarr_register)
- `services/handler_virtualzarr.py:986-1030` (virtualzarr_register)
- `services/handler_netcdf_to_zarr.py:1067-1071` (netcdf_register)

**Effort**: Small (1 hour)

---

### FIX 5: Fix Hardcoded original_job_type in Unpublish Cleanup (MEDIUM)

**What**: Replace hardcoded `"original_job_type": "virtualzarr"` with actual originating pipeline type.

**Why**: `UnpublishZarrJob` reverses three pipelines (virtualzarr, ingest_zarr, netcdf_to_zarr) but always records `"virtualzarr"` in cleanup. Corrupts audit trail.

**Where**: `jobs/unpublish_zarr.py:218`

**Effort**: Small (1 hour)

---

## ALL FINDINGS (25 total, ranked by severity)

| # | Severity | ID | Finding | Location |
|---|----------|----|---------|----------|
| 1 | CRITICAL | ORCH-1 | Pre-cleanup I/O on orchestrator — Constitution §5.1 violation | `jobs/ingest_zarr.py:221-225` |
| 2 | HIGH | URL-1 | urlparse breaks abfs:// URLs in unpublish inventory | `unpublish_handlers.py:600-606` |
| 3 | HIGH | PARAM-1 | zarr_format severed at translation + mixin — always defaults to 3 | `platform_translation.py` + both jobs |
| 4 | HIGH | REG-1 | Register handlers return success:True on partial DB failures | 3 register handlers |
| 5 | HIGH | ORCH-2 | Double pre-cleanup in rechunk path (orchestrator + handler) | `ingest_zarr.py:225` + `handler_ingest_zarr.py:797` |
| 6 | HIGH | DS-1 | xarray dataset not closed on failure path (no try/finally) | `handler_ingest_zarr.py:163-219` |
| 7 | MEDIUM | UNPUB-1 | Hardcoded `original_job_type: "virtualzarr"` | `unpublish_zarr.py:218` |
| 8 | MEDIUM | EXT-1 | Spatial extent assumes lat/lon/y + lon/longitude/x names | 5 handler sites |
| 9 | MEDIUM | DRY-1 | dry_run default conflict: schema=True vs .get fallback=False | `unpublish_zarr.py` |
| 10 | MEDIUM | VAL-1 | No compressor validation at job level (schema is bare str) | Both job schemas |
| 11 | MEDIUM | META-1 | STAC items don't record zarr_format/chunking/compression | Register handlers |
| 12 | MEDIUM | COPY-1 | Copy handler doesn't validate source blob exists before copy | `handler_ingest_zarr.py` |
| 13 | MEDIUM | ERR-1 | Validate handler uses generic Exception catch | `handler_ingest_zarr.py:244` |
| 14 | MEDIUM | CLEAN-1 | netcdf cleanup stage hardcodes `netcdf_to_zarr` check | `handler_netcdf_to_zarr.py` |
| 15 | LOW | MSG-1 | Blob list may approach Service Bus 256KB message limit | `ingest_zarr.py:268-269` |
| 16 | LOW | DUP-1 | Spatial extent helper duplicated across 3 handlers | Multiple |
| 17 | LOW | DOC-1 | Missing docstrings on some internal helpers | Various |
| 18-25 | LOW | Various | Minor inconsistencies, dead code paths, log formatting | Various |

---

## ACCEPTED RISKS

| ID | Risk | Why Acceptable |
|----|------|----------------|
| AR-1 | No compressor validation at job level | Platform API enforces via Pydantic; direct submit is admin-only |
| AR-2 | Spatial extent uses hardcoded coord names | Fallback to global bbox is valid STAC; current data is CF-compliant |
| AR-3 | dry_run default conflict | Schema default (True) wins in practice; .get fallback is dead code |
| AR-4 | Blob list message size | 50 names × ~200 chars = ~10KB, well under 256KB limit |
| AR-5 | STAC doesn't record zarr_format/compression | Zarr stores are self-describing; nice-to-have for discoverability |
| AR-6 | xarray not closed on failure | GC handles it; transient containers; not a long-running process |

---

## ARCHITECTURE WINS

1. **Consistent Handler Contract** — All handlers follow `{success, result}` / `{success, error, error_type}` envelope. Lazy imports keep orchestrator startup fast.

2. **Stage Decomposition** — Validate-then-act staging provides natural checkpoints. Zero-task stage guard handles empty inventory. `previous_results` threading works correctly after NZ1-F1 fix.

3. **`_build_zarr_encoding()` Shared Helper** — Format-aware encoding builder correctly branches v2/v3 for codecs and encoding keys. `ingest_zarr_rechunk` imports it rather than duplicating.

4. **Declarative Job Configuration** — Mixin pattern with `stages`, `parameters_schema`, `reversed_by` linkages. Custom logic isolated to `create_tasks_for_stage`.

5. **Source Account Resolution at Submit Time** — `platform_translation.py` bakes `source_account` into job params, making jobs self-contained and independent of config state at execution time.

---

## RECOMMENDATION

**FIX 1-3 immediately** — they represent data loss risk (orphan data from broken unpublish), silent misconfiguration (zarr_format), and a Constitution violation (orchestrator I/O). FIX 4 should follow as it masks DB failures. FIX 5 is low-risk cleanup for audit trail correctness.
