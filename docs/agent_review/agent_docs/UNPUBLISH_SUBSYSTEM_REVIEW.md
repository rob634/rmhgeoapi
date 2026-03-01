# COMPETE Review: Unpublish Subsystem

**Date**: 28 FEB 2026
**Pipeline**: COMPETE (Omega → Alpha + Beta → Gamma → Delta)
**Scope Split**: C (Data vs Control Flow)
**Subsystem**: Unpublish — reverse-ETL pipeline for raster, vector, and (future) zarr
**Files Reviewed**: 5 primary + 8 supporting infrastructure files
**Token Usage**: 346,656 total across 4 agents

---

## Executive Summary

The Unpublish Subsystem is architecturally sound — the 3-stage Inventory/Delete/Cleanup pipeline, the declarative `JobBaseMixin` pattern, and the atomic STAC-delete-with-revocation transaction are all well-designed. However, it contains one critical defect that will cause permanent job hangs for STAC-only catalog items (zero blobs at Stage 2), and a second critical defect where trigger-layer release revocation before job submission leaves no compensating cleanup path if the job fails to submit. Five additional high/medium issues affect audit completeness, retry parity, and forward-ETL traceability. The subsystem is safe for raster items with blobs and for vector unpublish in the happy path, but the two critical paths need fixes before broader adoption.

---

## Top 5 Fixes

### Fix 1: Zero-Task Stage 2 Causes Permanent Job Hang (CRITICAL)

- **WHAT**: When `create_tasks_for_stage` returns an empty list for Stage 2 (no blobs to delete), the job hangs in PROCESSING forever because no tasks exist to trigger stage completion.
- **WHY**: For `stac_catalog_container` items (STAC-only catalogs), Stage 1 inventory returns zero blobs. Stage 2 returns `[]`. CoreMachine calls `_individual_queue_tasks([])`, which returns `{'tasks_queued': 0, 'tasks_failed': 0}`. The guard at line 634 checks `tasks_queued == 0 AND tasks_failed > 0` — since `tasks_failed` is also 0, the guard does not fire. No task ever completes, so stage completion never triggers, and the job sits in PROCESSING indefinitely.
- **WHERE**: `core/machine.py`, `process_job_message`, lines 630-641. Secondary: `jobs/unpublish_raster.py`, `create_tasks_for_stage`, lines 180-183.
- **HOW**: Add a zero-task guard after line 628. If `result['total_tasks'] == 0`, treat the stage as immediately complete and call `_handle_stage_completion(job_id, job_type, current_stage)` to advance to the next stage. Fix at engine level so ALL job types benefit.
- **EFFORT**: Medium (2-3 hours). Touches CoreMachine orchestration loop.
- **RISK OF FIX**: Medium. Must distinguish "zero tasks because none needed" from "zero tasks because generation failed."

### Fix 2: Release Revocation Before Job Submission Has No Compensating Transaction (CRITICAL)

- **WHAT**: The trigger layer revokes the release and deletes STAC (via `AssetApprovalService.revoke_release`) BEFORE submitting the unpublish job. If job submission fails, release is revoked but blobs remain orphaned.
- **WHY**: Lines 148-174 of `triggers/platform/unpublish.py` revoke first, then lines 178+ delegate to execution helpers. If `create_and_submit_job` raises, no job exists to clean up remaining artifacts.
- **WHERE**: `triggers/platform/unpublish.py`, lines 142-175 (revocation block) and lines 438/351 (job submission).
- **HOW**: Move release revocation into the job itself (Stage 3 already does this at `services/unpublish_handlers.py:765-780`). Remove trigger-layer revocation, or wrap revocation + job submission in try/except that re-approves on failure.
- **EFFORT**: Medium (2-4 hours).
- **RISK OF FIX**: Medium. Changes timing of user-visible state transition.

### Fix 3: `stac_item_snapshot` Not Passed to Stage 3 for Raster Audit Record (HIGH)

- **WHAT**: Raster Stage 3 task creation does not include `stac_item_snapshot`, so the audit record's `artifacts_deleted` is always empty for raster.
- **WHY**: `jobs/unpublish_raster.py` lines 219-234 extracts `original_job_id` from `_stac_item` but never passes the snapshot itself. Handler at `services/unpublish_handlers.py:696` reads `params.get('stac_item_snapshot', {})` and gets `{}`.
- **WHERE**: `jobs/unpublish_raster.py`, `create_tasks_for_stage`, lines 219-234.
- **HOW**: Add `"stac_item_snapshot": stac_item` to Stage 3 parameters. Variable already exists at line 208.
- **EFFORT**: Small (< 30 minutes).
- **RISK OF FIX**: Low. Purely additive.

### Fix 4: Vector Unpublish Missing Retry Support (HIGH)

- **WHAT**: `_execute_vector_unpublish` returns idempotent_response for existing requests without checking if the previous job failed. Failed vector unpublish can never be retried.
- **WHY**: Lines 336-342 check `if existing:` and return immediately. Raster (lines 413-429) additionally checks `JobStatus.FAILED` and allows retry.
- **WHERE**: `triggers/platform/unpublish.py`, `_execute_vector_unpublish`, lines 336-342.
- **HOW**: Copy retry pattern from `_execute_raster_unpublish` (lines 413-429): query job status, if FAILED set `is_retry = True`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Follows proven pattern in same file.

### Fix 5: Validator Extracts `_stac_original_job_id` Using Wrong Property Names (HIGH)

- **WHAT**: The `stac_item_exists` validator looks for `processing:job_id`/`etl_job_id` but forward ETL writes `geoetl:job_id`. Validator's `_stac_original_job_id` is always None.
- **WHY**: `infrastructure/validators.py:1184` uses wrong property names. Forward ETL uses `APP_PREFIX = "geoetl"`. Partially mitigated by Stage 3's direct read at `unpublish_raster.py:212`.
- **WHERE**: `infrastructure/validators.py`, `_validate_stac_item_exists`, line 1184.
- **HOW**: Change to `properties.get('geoetl:job_id') or properties.get('processing:job_id') or properties.get('etl_job_id')`.
- **EFFORT**: Small (< 15 minutes).
- **RISK OF FIX**: Low. Purely additive lookup.

---

## Accepted Risks

| ID | Issue | Why Acceptable | Revisit When |
|----|-------|---------------|-------------|
| AR-1 | Partial blob deletion leaves inconsistent state | Idempotent retries fix it; blobs are not source-of-truth | Production deployment |
| AR-2 | `_stac_item` in job_params unbounded size | Current items are small (<10KB); task messages don't carry it | 50+ assets per item |
| AR-3 | Dual revocation race | Defense-in-depth; pre-check makes second a no-op | Concurrent unpublish |
| AR-4 | `table_catalog` query lacks schema_name filter | Single schema in use; collision extremely unlikely | Multi-tenant schemas |
| AR-5 | `UnpublishType` enum missing ZARR | Zarr unpublish is future work; dead code otherwise | Zarr unpublish implementation |
| AR-6 | `reverses` list missing `ingest_collection` | Declarative metadata only, not enforced at runtime | Automated reverse-ETL lookups |
| AR-7 | Option 4 cleanup mode skips trigger-layer revocation | Stage 3 handles it; admin path only | Option 4 becomes primary UX |

---

## Architecture Wins

1. **Atomic STAC Delete + Release Revocation** (`services/unpublish_handlers.py:751-845`): Single transaction wrapping STAC delete, release revocation, collection cleanup, and audit insert. Correct pattern.

2. **Declarative `JobBaseMixin` + `reverses` Metadata** (`jobs/unpublish_raster.py:41-110`): Self-documenting, minimal boilerplate, enables future tooling.

3. **Pre-flight Validation via `resource_validators`** (`jobs/unpublish_raster.py:113-120`): Fail fast, hydrate `_stac_item` into params for all stages.

4. **Idempotent Blob Deletion** (`services/unpublish_handlers.py:398-477`): `blob_exists` check before delete, `success: True` for already-gone blobs.

5. **Fan-Out Stage 2** (`jobs/unpublish_raster.py:166-199`): Dynamic one-task-per-blob enabling parallel deletion.

6. **Dry-Run Safety Default** (`jobs/unpublish_raster.py:103-104`): `dry_run=True` at every layer. Explicit opt-in to destruction.

---

## Full Finding Registry

| Rank | ID | Severity | Confidence | Description |
|------|-----|----------|------------|-------------|
| 1 | BS-1 / Beta EDGE-1 | CRITICAL | CONFIRMED | Zero-task Stage 2 permanent job hang |
| 2 | Beta F-1 | CRITICAL | CONFIRMED | Release revocation before job submission |
| 3 | Alpha H-2 / Gamma AG-1 | HIGH | CONFIRMED | `stac_item_snapshot` not passed to Stage 3 audit |
| 4 | Alpha H-3 / Gamma AG-3 | HIGH | CONFIRMED | Validator property name mismatch (`geoetl:job_id`) |
| 5 | Beta F-2 | HIGH | CONFIRMED | Vector unpublish missing retry support |
| 6 | Beta F-3 | HIGH | PROBABLE | Partial blob deletion inconsistent state |
| 7 | Gamma BS-2 | HIGH | PROBABLE | Dual revocation `is_latest` flip race |
| 8 | Gamma BS-3 / Beta E-4 | HIGH | PROBABLE | `_stac_item` unbounded size in job_params |
| 9 | Alpha M-4 | MEDIUM | CONFIRMED | Release revocation skipped in Option 4 |
| 10 | Alpha M-5 | MEDIUM | CONFIRMED | `delete_blob` zone fails for `silverext` |
| 11 | Gamma BS-4 | MEDIUM | CONFIRMED | `table_catalog` query lacks `schema_name` |
| 12 | Beta F-4 | MEDIUM | PROBABLE | TOCTOU race in `delete_blob` decorator |
| 13 | Alpha M-1 | MEDIUM | CONFIRMED | `UnpublishType` enum missing ZARR |
| 14 | Alpha M-3 | MEDIUM | CONFIRMED | `reverses` list missing `ingest_collection` |
| 15 | Beta F-5 | MEDIUM | CONFIRMED | Collection-level unpublish not transactional |
| 16 | Beta F-6 | LOW | SPECULATIVE | Duplicate HTTP requests produce duplicate queue messages |
| 17 | Alpha M-2 | LOW | PROBABLE | Bronze source files never cleaned up |
| 18 | Alpha L-2 | LOW | CONFIRMED | `'none'` sentinel strings instead of SQL NULL |
| 19 | Gamma BS-5 | LOW | CONFIRMED | Full blob paths logged to App Insights |
| 20 | Gamma BS-6 | LOW | CONFIRMED | `force_curated` has no auth gate |
| 21 | Alpha L-1 | LOW | PROBABLE | `original_job_type` always None for raster |
| 22 | Alpha L-3 | LOW | CONFIRMED | `_inventory_data` missing on error path |

---

## Pipeline Metrics

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Omega | Scope split (inline) | ~0 | — |
| Alpha | Data Integrity | 81,312 | 4m 36s |
| Beta | Flow Control | 114,589 | 4m 19s |
| Gamma | Contradictions | 82,310 | 3m 57s |
| Delta | Final Report | 68,445 | 3m 25s |
| **Total** | — | **346,656** | **~16m 17s** |
