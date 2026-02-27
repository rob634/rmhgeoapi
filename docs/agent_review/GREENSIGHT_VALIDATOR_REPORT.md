# Greensight Validator Report: VirtualiZarr Pipeline

**Date**: 27 FEB 2026
**Pipeline**: Greensight (S → A + C + O → M → B → V → Spec Diff)
**Agent V Rating**: NEEDS MINOR WORK

---

## Agent V Summary

Agent V received all 12 code files with zero context and correctly inferred:
- The pipeline generates lightweight kerchunk references from NetCDF files
- Four-stage workflow: scan, validate, combine, register
- Integrated into existing platform submit/approve lifecycle
- No physical data conversion (metadata-only references)

V identified **16 concerns** (C1-C16). Full analysis below.

---

## SPEC DIFF (S's Spec vs V's Inferences)

### MATCHES — Well-Implemented Areas

| # | Spec Requirement | V's Inference | Assessment |
|---|-----------------|---------------|------------|
| 1 | PURPOSE: lightweight kerchunk references, avoid physical Zarr conversion | V inferred exactly this | Perfect match |
| 2 | BOUNDARIES: read-only against source, no TiTiler deployment, no approval mods | V confirmed all boundaries | Perfect match |
| 3 | Contract 2 (Scan): list .nc files, sorted alphabetically, Azure credentials | V inferred scan behavior correctly | Match |
| 4 | Contract 3 (Validate): header-only HDF5 read, chunking warnings, fail_on_warnings | V inferred validate behavior correctly | Match |
| 5 | Contract 5 (Combine): concatenate along concat_dim, extract spatial/temporal extent | V inferred combine behavior correctly | Match |
| 6 | Contract 6 (Register): cache STAC on release, update blob_path, status → COMPLETED | V inferred register behavior correctly | Match |
| 7 | Invariant 1: no data duplication | V confirmed metadata-only | Match |
| 8 | Invariant 4: STAC cached, not materialized | V confirmed — materialization at approval only | Match |
| 9 | Invariant 5: original files untouched | V confirmed read-only | Match |
| 10 | Invariant 6: stage ordering | V confirmed 4-stage sequential | Match (see GAP 1 re: stage count) |
| 11 | NFR Security: Azure Managed Identity | V confirmed (and flagged inconsistency — see C4) | Partial match |
| 12 | NFR Observability: INFO logging with params, count, duration | V confirmed comprehensive logging | Match |

### GAPS — In Spec But Missing or Deviated in Code

| # | Spec Requirement | What Code Does | Severity | Action |
|---|-----------------|----------------|----------|--------|
| G1 | **5-stage pipeline** (Scan → Validate → Generate Refs → Combine → Register) | **4-stage pipeline** — no separate Generate Refs stage. Combine handler opens virtual datasets directly from source files without per-file intermediate references. | LOW | Mediator likely resolved this. Verify with GREENSIGHT_MEDIATOR_RESOLUTION.md. If intentional, update spec. |
| G2 | Contract 2: **`recursive: True`** parameter in scan input | Scan uses `fs.ls()` (single-level listing). No recursive glob. V flagged as C3. | MEDIUM | If source dirs have nested subdirs, files will be missed. Add recursive option or document limitation. |
| G3 | Contract 2: **"Returns empty list (not error) if no files match"** | Scan returns `success: False` with error message when zero files found. | LOW | Spec-code mismatch. Current behavior (error on empty) is arguably better — prevents silent empty pipelines. Update spec to match code. |
| G4 | Contract 3 output: **`recommendation` field** | Not present in validate handler output. | LOW | Minor spec field omission. Add if consumers need it, otherwise update spec. |
| G5 | Contract 5 output: **`ref_size_bytes`** and **`dataset_id`** fields | Not present in combine handler output. | LOW | Missing metadata fields. Easy to add if needed. |
| G6 | Contract 2 input: **`source_url` must be an `abfs://` path** (spec requirement) | `source_url` field has `max_length=500` but no `abfs://` format validation. V flagged as C13. | MEDIUM | Add field validator to enforce `abfs://` prefix on PlatformRequest.source_url. |
| G7 | NFR Security: **Azure Managed Identity for ALL blob access** | Scan handler uses `DefaultAzureCredential`, but validate and combine use bare `fsspec.filesystem("abfs")` without explicit credential. V flagged as C4. | HIGH | Auth inconsistency. Fix validate/combine to use `DefaultAzureCredential` consistently. |
| G8 | Invariant 2: **Reference validity** — every reference file must resolve to same data | Combine handler has validation read (lines 550-566) but it's non-fatal and may not work against blob storage. V flagged as C6. | MEDIUM | Fix validation read to use proper storage_options, or make failure fatal with clear error. |

### EXTRAS — In Code But Not in Spec

| # | What V Found | Assessment |
|---|-------------|------------|
| E1 | **`max_files` cap in scan** — fails if file count exceeds limit | Useful guard. Spec didn't mention but Mediator Resolution defined 500-file cap. Keep. |
| E2 | **Manifest blob** as inter-stage communication (scan writes manifest.json, combine reads it) | Design decision not in S's spec. Avoids passing large file lists in Service Bus messages (256KB limit). This addresses Operator concern. Keep. |
| E3 | **Variable mismatch validation** in combine handler | Validates all files have identical variables and compatible non-concat dimensions. Not in spec but excellent defensive check. Keep. |
| E4 | **Validation read** after combine | Attempts to open the combined reference to verify it works. Good practice, but currently broken per C6. Fix, don't remove. |
| E5 | **`output_mode="zarr_reference"`** on release | Distinct output mode for zarr releases. Not in spec but enables downstream differentiation. Keep. |
| E6 | **`xarray:open_kwargs`** in STAC properties | Embeds the exact xarray open configuration in the STAC item. Spec mentioned "xarray-specific properties" but didn't specify this pattern. Excellent for consumers. Keep. |
| E7 | **`zarr:variables` and `zarr:dimensions`** in STAC properties | Additional metadata for consumers. Not in spec. Keep. |

---

## Agent V Concerns — Disposition

| V Concern | Severity | Disposition |
|-----------|----------|-------------|
| **C1**: Hardcoded container `rmhazuregeosilver` | MEDIUM | **FIX** — derive from config like other pipelines |
| **C2**: Duplicate `_get_storage_account()` | LOW | **FIX** — consolidate to single import |
| **C3**: No recursive scan | MEDIUM | **DECIDE** — maps to spec GAP G2. Add recursive flag or document limitation. |
| **C4**: Auth inconsistency (scan vs validate/combine) | HIGH | **FIX** — maps to spec GAP G7. Use `DefaultAzureCredential` everywhere. |
| **C5**: No credentials on `to_kerchunk()` write | HIGH | **FIX** — likely runtime failure in production. Pass storage_options to export. |
| **C6**: Validation read may not work against blob | MEDIUM | **FIX** — maps to spec GAP G8. Fix storage_options or remove validation read. |
| **C7**: Fragile manifest URL reconstruction in Stage 3 | MEDIUM | **FIX** — pass manifest_url through job context or previous_results chain. |
| **C8**: max_files limit mismatch (10000 vs 5000) | LOW | **FIX** — align job schema max to 5000 to match ZarrProcessingOptions. |
| **C9**: Missing release_id in parameters_schema | LOW | **ACCEPT** — release_id is injected by submit trigger, not user-provided. Document. |
| **C10**: No unpublish path for zarr | MEDIUM | **DEFER** — out of scope per spec boundaries. Track as V2 feature. |
| **C11**: ADF data_type detection uses geoetl: property | LOW | **ACCEPT** — detection runs before sanitization. Document ordering assumption. |
| **C12**: Stale docstring on normalize_data_type | LOW | **FIX** — trivial. |
| **C13**: source_url no abfs:// validation | MEDIUM | **FIX** — maps to spec GAP G6. Add Pydantic field validator. |
| **C14**: All virtual datasets held in memory | LOW | **ACCEPT** — virtual datasets are metadata-only. Monitor at scale. |
| **C15**: Missing STAC extensions declaration | LOW | **DEFER** — no standard Zarr STAC extension exists yet. Add when available. |
| **C16**: Inconsistent enum comparison in submit trigger | LOW | **FIX** — trivial. Normalize to enum comparison. |

---

## VERDICT

### Is the code ready to use?

**NEEDS MINOR WORK** — The pipeline architecture is sound and all integration points are wired correctly. No architectural issues.

### Must-Fix Before Ship (5 items)

| # | Source | Issue | Files |
|---|--------|-------|-------|
| 1 | C1 | Hardcoded `rmhazuregeosilver` container name | `jobs/virtualzarr.py`, `handler_virtualzarr.py` |
| 2 | C4+C5 | Auth inconsistency + no credentials on blob write | `handler_virtualzarr.py` (validate, combine handlers) |
| 3 | G7+C4 | `to_kerchunk()` export likely fails without storage_options | `handler_virtualzarr.py` (combine handler, line 503) |
| 4 | C7 | Fragile manifest URL reconstruction in Stage 3 | `jobs/virtualzarr.py` (create_tasks_for_stage, stage 3) |
| 5 | C8 | max_files limit mismatch (10000 vs 5000) | `jobs/virtualzarr.py` |

### Should-Fix (6 items)

| # | Source | Issue |
|---|--------|-------|
| 6 | G2+C3 | Add recursive scan option or document limitation |
| 7 | G6+C13 | Validate source_url starts with `abfs://` |
| 8 | C2 | Consolidate duplicate `_get_storage_account()` |
| 9 | C6+G8 | Fix or remove validation read in combine handler |
| 10 | C12 | Update stale docstring on normalize_data_type |
| 11 | C16 | Normalize enum comparison pattern in submit trigger |

### Accepted / Deferred (5 items)

| # | Source | Rationale |
|---|--------|-----------|
| 12 | C9 | release_id injected by submit trigger — working as designed |
| 13 | C10 | No unpublish path — out of scope per spec, V2 feature |
| 14 | C11 | ADF detection ordering is safe — document assumption |
| 15 | C14 | Memory for virtual datasets — monitor at scale |
| 16 | C15 | No standard Zarr STAC extension — defer |

---

## Pipeline Status

| Agent | Status | Output |
|-------|--------|--------|
| S (Spec) | DONE | `GREENSIGHT_VIRTUALZARR_SPEC.md` |
| A (Advocate) | DONE | Fed into M |
| C (Critic) | DONE | Fed into M |
| O (Operator) | DONE | `GREENSIGHT_OPERATOR_REVIEW.md` |
| M (Mediator) | DONE | `GREENSIGHT_MEDIATOR_RESOLUTION.md` |
| B (Builder) | DONE | Committed `ad3b8bd` |
| V (Validator) | DONE | This document |
| Spec Diff | DONE | This document |

### Next Steps

1. Fix the 5 must-fix items (estimated 1-2 hours)
2. Fix the 6 should-fix items (estimated 30 minutes)
3. Docker dependency verification (virtualizarr, kerchunk, h5py in Docker image)
4. Write tests for the 4 handlers
5. Optional: Chain to Adversarial Review (Pipeline 1) for implementation-level review
