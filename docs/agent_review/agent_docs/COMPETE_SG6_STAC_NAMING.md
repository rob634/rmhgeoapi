# COMPETE Run 12: SG-6 STAC Item ID Naming Convention

**Date**: 01 MAR 2026
**Pipeline**: COMPETE
**Scope**: STAC item ID naming lifecycle — `-ord{N}` vs `-v{version_id}` mismatch
**Files**: 8 primary + 6 supporting
**Scope Split**: B (Internal vs External)
**Trigger**: SIEGE Run 1 Finding SG-6

---

## Agent Timing

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Omega | Scope split (Internal vs External) | — | inline |
| Alpha | Internal Logic and Invariants | 69,784 | 5m 51s |
| Beta | External Interfaces and Boundaries | 91,176 | 4m 31s |
| Alpha+Beta | (parallel wall clock) | 160,960 | 6m 17s |
| Gamma | Contradictions + Blind Spots | 112,503 | 5m 08s |
| Delta | Final Report | 64,098 | 3m 13s |
| **Total** | | **337,561** | **~16m 40s** |

---

## Executive Summary

The STAC item ID naming convention (`-ord{N}` during processing, `-v{version_id}` after approval) is architecturally sound as a two-phase identity lifecycle. However, the transition between phases is incomplete: the approval flow updates the `stac_item_id` column on the release and patches a local copy for pgSTAC, but it never writes the patched JSON back to the `asset_releases.stac_item_json` column, leaving a stale `-ord{N}` identifier in the cached blob. This same stale blob is then exposed verbatim through `release.to_dict()` on the approvals list and detail endpoints, leaking internal `geoetl:*` properties to B2B callers. The pgSTAC materialization itself is correct (it patches on read before writing to pgSTAC), so the consumer-facing STAC catalog is clean — the damage is contained to the platform API surface and to downstream consistency checks that rely on the cached JSON.

---

## Top 5 Fixes

### Fix 1: Strip `geoetl:*` properties from `to_dict()` serialization of `stac_item_json`

- **WHAT**: Sanitize `stac_item_json` in the Release model's `to_dict()` method before returning it to API callers.
- **WHY**: Raw `stac_item_json` with internal `geoetl:*` properties (provenance, job tracking, internal URIs) is exposed via `GET /api/platform/approvals` (line 753) and `GET /api/platform/approvals/{release_id}` (line 835) in `trigger_approvals.py`. These properties are internal ETL artifacts and should never be visible to B2B consumers.
- **WHERE**: `core/models/asset.py`, method `to_dict()`, line 696.
- **HOW**: Add a sanitization step that strips `geoetl:*` keys from `stac_item_json['properties']` before including it in the returned dict. Use the same logic as `STACMaterializer.sanitize_item_properties()`. Operate on a shallow copy to avoid mutating the model instance.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 2: Persist versioned `stac_item_json` back to DB after approval

- **WHAT**: After the approval flow patches `stac_item_id` on the release, also update the cached `stac_item_json` blob so its `id` field matches the new versioned identity.
- **WHY**: `asset_approval_service.py` lines 220-237 update the `stac_item_id` column to the `-v{version_id}` form, but the `stac_item_json` blob in the DB retains the original `-ord{N}` value. Any subsequent read of `stac_item_json` (API responses, rebuild operations, auditing) shows a stale identifier.
- **WHERE**: `services/asset_approval_service.py`, method `approve_release()`, lines 229-237 (after `update_physical_outputs` and before `_materialize_stac`).
- **HOW**: After updating `stac_item_id`, patch the cached JSON and write it back using the existing `release_repo.update_stac_item_json()` method.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. `update_stac_item_json` already exists and is well-tested.

### Fix 3: Add `else` / `logger.warning` to submit ordinal finalization

- **WHAT**: Add a catch-all branch to the ordinal finalization `if/elif/elif` chain that logs a warning for unhandled data types.
- **WHY**: If a new data type is submitted without `version_id`, the ordinal finalization block silently does nothing — the release keeps a `*-draft` stac_item_id instead of being finalized to `*-ord{N}`.
- **WHERE**: `triggers/platform/submit.py`, lines 334-384, after the ZARR block.
- **HOW**: Add `else: logger.warning(...)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Purely additive logging.

### Fix 4: Guard against `version_ordinal=0` producing `ord0`

- **WHAT**: Add validation in `PlatformConfig.generate_stac_item_id()` that rejects `version_ordinal < 1`.
- **WHY**: The ordinal convention is 1-indexed. A `version_ordinal=0` produces `ord0`, which is semantically invalid.
- **WHERE**: `config/platform_config.py`, method `generate_stac_item_id()`, lines 379-380.
- **HOW**: Add `if version_ordinal < 1: raise ValueError(...)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Medium. Verify that no code path passes `version_ordinal=0`.

### Fix 5: Update `cog_metadata.stac_item_id` after approval

- **WHAT**: After the approval flow updates the release's `stac_item_id`, also update the corresponding `cog_metadata` row.
- **WHY**: `cog_metadata.stac_item_id` is written at processing time with the ordinal-based name. The metadata consistency checker cross-references it against pgSTAC — a stale ordinal reference gets flagged as an orphan.
- **WHERE**: `services/asset_approval_service.py`, after the `stac_item_id` update block (around line 237).
- **HOW**: Add an update call to `RasterMetadataRepository` to sync the stac_item_id. Requires a new `update_stac_item_id(old_id, new_id)` method.
- **EFFORT**: Medium (1-4 hours).
- **RISK OF FIX**: Medium. Need to verify cog_id vs stac_item_id column relationship.

---

## Accepted Risks

### AR-1: `stac_item_id` identity change breaks pre-approval bulk lookup

The `/api/platform/approvals/status?stac_item_ids=...` bulk lookup will fail for pre-approval IDs after approval. Acceptable because primary status endpoint uses `release_id`/`asset_id`, not `stac_item_id`. No known B2B integrations depend on ordinal-form lookups post-approval.

**Revisit if**: A DDH integration caches `stac_item_id` at submission time.

### AR-2: Five mutation points for `stac_item_id`

Each mutation point serves a distinct lifecycle phase; flow is sequential, not concurrent. Consolidating would require fundamentally different architecture.

**Revisit if**: A sixth mutation point is proposed or debugging becomes recurring.

### AR-3: Orphaned pgSTAC items after failed revocation + re-approve

`_delete_stac` failure is logged, and `rebuild_all_from_db()` can recover. `metadata_consistency.py` detects orphans.

**Revisit if**: Revocation frequency increases.

### AR-4: Race condition between stac_item_id update and pgSTAC materialization

Single-threaded per release (atomic guard). Materialization patches defensively.

**Revisit if**: Approval is ever parallelized.

---

## Architecture Wins

1. **pgSTAC as deterministic materialized view**: The materializer always reads from the authoritative `stac_item_id` column (not cached JSON) for identity. Consumer-facing STAC catalog is never contaminated.

2. **Approval rollback on STAC failure**: `approve_release()` implements robust rollback — if materialization fails after atomic DB approval, it reverts to `pending_review`. Double-failure path explicitly handled with `MANUAL_INTERVENTION_REQUIRED`.

3. **Collection-first materialization guard**: `materialize_release()` ensures pgSTAC collection exists before first item insert (SG-1 fix from this session).

4. **Ordinal reservation at draft creation**: `get_next_version_ordinal()` reserves slots at creation time using `MAX(version_ordinal) + 1`, preventing collisions.

5. **Defensive ID patching in materialization**: Even with stale cached JSON, pgSTAC writes are always correct — the materializer overrides `id` from the column.

---

## Gamma's Recalibrated Findings (Full Table)

| Rank | Finding | Source | Severity | Confidence |
|------|---------|--------|----------|------------|
| 1 | Raw `stac_item_json` with `geoetl:*` exposed via `to_dict()` | Gamma (BS-1) | HIGH | CONFIRMED |
| 2 | Stale `stac_item_json['id']` in DB after approval | Alpha+Beta (AR-1) | HIGH | CONFIRMED |
| 3 | `stac_item_id` identity change breaks approvals/status lookup | Beta (downgraded) | MEDIUM | CONFIRMED |
| 4 | Five mutation points for `stac_item_id` | Alpha | MEDIUM | CONFIRMED |
| 5 | `cog_metadata.stac_item_id` stale after approval | Alpha (downgraded) | MEDIUM | PROBABLE |
| 6 | `version_ordinal=0` accepted silently | Alpha | LOW | CONFIRMED |
| 7 | No catch-all in submit ordinal finalization | Alpha+Gamma | LOW | CONFIRMED |
| 8 | Orphaned pgSTAC items after failed revocation | Beta | MEDIUM | PROBABLE |
| 9 | Race condition in approval flow | Beta | LOW (mitigated) | PROBABLE |
| 10 | Auto `version_id` naming collision | Alpha | LOW (handled) | PROBABLE |

---

## Key Outcome

**The naming convention itself is sound.** The `-ord{N}` → `-v{version_id}` transition is a deliberate two-phase lifecycle. The real issue is incomplete lifecycle hygiene: the approval flow updates the identity column but leaves stale artifacts in the cached JSON blob and cog_metadata. Fixes 1-2 address the data integrity gap with minimal risk. The STAC catalog (pgSTAC) has always been correct due to the defensive patching in the materializer.
