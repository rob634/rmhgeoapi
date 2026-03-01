# GREENFIELD Report: Zarr Unpublish Pipeline

**Date**: 28 FEB 2026
**Pipeline**: GREENFIELD (S -> A+C+O -> M -> B -> V -> Spec Diff)
**Subsystem**: unpublish_zarr — Reverse VirtualiZarr pipeline
**Files Created/Modified**: 8
**Token Usage**: 631,196 total across 6 agents

---

## Executive Summary

The zarr unpublish pipeline was designed through the full GREENFIELD adversarial pipeline. Agent A designed a 7-component system reusing existing delete_blob and delete_stac_and_audit handlers. Agent C found 6 ambiguities, 8 edge cases, and 4 contradictions. Agent O confirmed strong infrastructure fit and calculated that 500 blobs across 4 workers completes in ~4.2 minutes (within 5-minute NFR). Agent M resolved 10 conflicts, producing a final spec with 7 components. Agent B wrote the code. Agent V rated it NEEDS MINOR WORK due to two integration gaps (now fixed).

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Pipeline shape | 3-stage (matches raster) | Battle-tested pattern, same CoreMachine behavior |
| STAC item discovery | pgstac + Release fallback | Zarr items may not be materialized (unapproved) |
| Pre-flight validator | None (inline in handler) | stac_item_exists would block unapproved items |
| Blob discovery | Manifest read + list_blobs fallback | STAC has only one asset (combined_ref.json) |
| delete_data_files=false | Still delete manifest + combined_ref | They are references, not data |
| Dry-run pattern | HTTP 200, no job (matches raster) | Spec said 202 — overridden by Design Constraint |
| Data type guard | Check geoetl:data_type | Prevents cross-type unpublish (C's E-4) |

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `core/models/unpublish.py` | Add `ZARR = "zarr"` to UnpublishType enum | 1 line |
| `jobs/unpublish_zarr.py` | **NEW** — UnpublishZarrJob (3-stage, JobBaseMixin) | 288 lines |
| `services/unpublish_handlers.py` | Add `inventory_zarr_item` handler | ~310 lines |
| `triggers/platform/unpublish.py` | Add zarr routing + `_execute_zarr_unpublish` | ~120 lines |
| `jobs/__init__.py` | Register UnpublishZarrJob | 2 lines |
| `services/__init__.py` | Register inventory_zarr_item | 2 lines |
| `config/defaults.py` | Add to DOCKER_TASKS | 1 line |
| `services/platform_translation.py` | Add zarr to normalize_data_type + get_unpublish_params_from_request | ~15 lines |

## Deployment Requirements

1. **Database migration FIRST** (standalone, cannot run in transaction):
   ```sql
   ALTER TYPE app.unpublish_type ADD VALUE 'zarr';
   ```
2. Code deployment SECOND (ACR build + container restart)
3. `action=ensure` THIRD (if any new columns needed)

## V's Verdict

**NEEDS MINOR WORK** (2 integration gaps fixed post-review):
- Fixed: `normalize_data_type` now maps `"unpublish_zarr"` → `"zarr"`
- Fixed: `get_unpublish_params_from_request` now handles zarr data type
- Accepted: `original_job_id=None` at Stage 3 (design tradeoff — M accepted)

## Deferred Items

| Item | Why Deferred | Trigger |
|------|-------------|---------|
| Failed forward pipeline cleanup | Requires different entry point (by job_id or prefix) | Storage costs material |
| Collection-level zarr unpublish | Single items only for now | Multi-item zarr collections |
| Concurrent unpublish + forward guard | Ordinal naming prevents most collisions | Race condition observed |
| Deep dry-run with full inventory | Matches raster pattern | User request |
| TiTiler-xarray cache invalidation | Not deployed yet | TiTiler-xarray deployment |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Manifest schema drift | LOW | HIGH | list_blobs fallback catches it |
| ref_output_prefix derivation | LOW | HIGH | Forward pipeline uses same naming |
| PostgreSQL enum migration ordering | MEDIUM | MEDIUM | Deploy checklist, idempotent migration |
| BlobRepository zone routing | LOW | HIGH | "silver" substring match confirmed |

## Pipeline Metrics

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| S | Spec Writer (inline) | — | inline |
| A | Advocate (design) | 95,473 | 3m 6s |
| C | Critic (gaps) | 113,438 | 3m 24s |
| O | Operator (ops) | 112,153 | 3m 37s |
| M | Mediator (resolve) | 121,278 | 4m 31s |
| B | Builder (code) | 115,645 | 7m 47s |
| V | Validator (review) | 73,209 | 2m 30s |
| **Total** | — | **631,196** | **~24m 55s** |

## Grand Total (COMPETE + GREENFIELD)

| Pipeline | Tokens | Duration |
|----------|--------|----------|
| COMPETE (unpublish subsystem review) | 346,656 | ~16m 17s |
| GREENFIELD (zarr unpublish build) | 631,196 | ~24m 55s |
| **Grand Total** | **977,852** | **~41m 12s** |
