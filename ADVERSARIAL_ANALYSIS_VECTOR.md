# Adversarial Review: Vector Data Workflow

**Date**: 26 FEB 2026
**Pipeline**: Adversarial Review (Omega → Alpha + Beta → Gamma → Delta)
**Scope**: Complete vector workflow — ingestion through PostGIS, STAC, approval, unpublish
**Files Reviewed**: ~20 key files across jobs, services, core, config, triggers, infrastructure

---

## EXECUTIVE SUMMARY

The vector data workflow is architecturally sound — the Asset/Release separation, JobBaseMixin pattern, STAC-as-materialized-view, and anti-corruption layer are genuine strengths worth preserving. However, one confirmed **showstopper bug** (C-1) crashes every first-ever dataset submission with a `NameError`, and a **security-grade issue** (H-1) lets approved data be unpublished without authorization when the database is unreachable. Three additional high-priority fixes address orphaned state, non-atomic STAC operations, and a dual-write race. All five fixes are surgical — none require architectural changes. Total effort: ~2 hours.

---

## TOP 5 FIXES

### FIX 1: `table_name` NameError crashes first-ever release creation (CRITICAL)

**What:** `get_or_overwrite_release()` passes `table_name=table_name` to `create_release()` on line 348, but `table_name` is not defined anywhere in scope. Furthermore, `create_release()` no longer accepts a `table_name` parameter (removed 26 FEB 2026).

**Why:** Every first-ever submission for a new asset (no prior releases) hits the "FIRST RELEASE" branch at line 341 and crashes with `NameError`. The "new_version" branch (line 329) does NOT have this bug, so re-submissions of existing assets work.

**Where:** `services/asset_service.py`, method `get_or_overwrite_release()`, line 348.

**How:** Remove the `table_name=table_name` kwarg from the `create_release()` call. The "new_version" branch already omits it correctly.

**Effort:** 1 line deletion. 5 minutes.
**Risk:** Zero.
**Confidence:** CONFIRMED by Alpha, Beta, and Gamma.

---

### FIX 2: Approval guard swallowed on DB failure allows unauthorized unpublish (HIGH)

**What:** The approval check in `unpublish_inventory_by_stac_id()` is wrapped in a bare `except Exception` that logs a warning and continues (lines 122-124). If the database is unreachable, the approval guard is silently bypassed.

**Why:** An approved, published dataset can be unpublished without the `force_approved` flag if the DB connection times out during the approval check but recovers for the subsequent delete operations. This is a data-governance defect.

**Where:** `services/unpublish_handlers.py`, method `unpublish_inventory_by_stac_id()`, lines 122-124.

**How:** Change the exception handler to fail-closed — if the approval check cannot be performed, abort the unpublish:

```python
# BEFORE (fail-open)
except Exception as e:
    logger.warning(f"Could not check approval status for {stac_item_id}: {e}")

# AFTER (fail-closed)
except Exception as e:
    logger.error(f"Cannot verify approval status for {stac_item_id}: {e}")
    return {
        "success": False,
        "error": f"Approval check failed (DB unreachable). Cannot proceed without verification.",
        "error_type": "ApprovalCheckFailed",
        "detail": str(e),
        "hint": "Retry when database is available, or use force_approved=true to bypass."
    }
```

**Effort:** 5 lines changed. 15 minutes.
**Risk:** Low. Unpublish operations will fail when DB is down instead of proceeding unsafely.
**Confidence:** CONFIRMED.

---

### FIX 3: Orphaned `release_tables` entry on ETL validation failure (HIGH)

**What:** `submit.py` writes a `release_tables` entry with `geometry_type='UNKNOWN'` at lines 354-361 BEFORE the ETL job runs. If the job fails during validation, the phantom table reference persists.

**Why:** Downstream queries that join `release_tables` will reference tables that don't exist in PostGIS, causing errors in features API, tile generation, and unpublish workflows.

**Where:** `triggers/platform/submit.py`, lines 354-361.

**How (Option A — preferred):** Remove the `release_tables` write from submit.py entirely. The ETL handler already writes accurate per-table entries during processing. The callback in `machine_factory.py` has a fallback that creates an entry if none exist. Delete lines 354-361.

**Effort:** Delete 8 lines. 15 minutes.
**Risk:** Low. The handler writes the correct data.
**Confidence:** CONFIRMED.

---

### FIX 4: Non-atomic STAC delete + release revocation uses separate connections (HIGH)

**What:** `delete_stac_and_audit()` opens one connection for STAC operations (line 741), then opens a SECOND independent connection for release revocation (line 761). If the process crashes between them, the STAC item is deleted but the release remains APPROVED.

**Why:** Inconsistent state that the approval service cannot reconcile. Re-running finds no STAC item ("already deleted") while the release stays incorrectly approved. Manual DB intervention required.

**Where:** `services/unpublish_handlers.py`, method `delete_stac_and_audit()`, lines 741-782.

**How:** Move the release revocation into the same connection/transaction as the STAC delete. Execute the revocation within the existing `with conn.cursor() as cur:` block so `conn.commit()` atomically commits both operations.

**Effort:** ~30 lines refactored. 1 hour.
**Risk:** Medium. Test cross-schema transaction (`pgstac` + `app`) in dev first.
**Confidence:** CONFIRMED.

---

### FIX 5: Dual processing status update — handler vs callback race (MEDIUM)

**What:** The vector docker handler sets `ProcessingStatus.COMPLETED` at line 317 WITHOUT `completed_at`. The callback in `machine_factory.py` (line 232-237) sets the same status WITH `completed_at`. If the callback fails, `completed_at` remains NULL.

**Why:** Downstream queries filtering on `completed_at IS NOT NULL` will miss completed jobs. Dual-write is redundant.

**Where:**
- `services/handler_vector_docker_complete.py`, lines 311-319 (success) and 359-370 (failure)
- `core/machine_factory.py`, lines 232-237

**How:** Remove the handler's status updates entirely (~20 lines across two blocks). The callback is the canonical path and handles both success and failure with `completed_at`.

**Effort:** Delete ~20 lines. 20 minutes.
**Risk:** Low. Callback is the single source of truth.
**Confidence:** CONFIRMED.

---

## EFFORT SUMMARY

| Fix | Effort | Impact |
|-----|--------|--------|
| Fix 1 (CRITICAL) | 5 min | Unblocks all first-time dataset submissions |
| Fix 2 (HIGH) | 15 min | Closes authorization bypass on DB failure |
| Fix 3 (HIGH) | 15 min | Eliminates phantom table references |
| Fix 4 (HIGH) | 1 hour | Atomic STAC + release state management |
| Fix 5 (MEDIUM) | 20 min | Single source of truth for completion status |
| **Total** | **~2 hours** | **Zero architectural refactoring required** |

---

## ACCEPTED RISKS

| ID | Finding | Severity | Rationale |
|----|---------|----------|-----------|
| H-4 | Column name collision after sanitization | HIGH | Theoretical edge case, no reported incidents. Fix when H-5 (God class) is tackled. |
| H-5 | `prepare_gdf()` is 700+ lines, 15+ concerns | HIGH | Works correctly today. Multi-day refactoring with regression risk. Track as enabler story. |
| H-6 | No canonical HandlerResult contract | HIGH | Extraction works for all current handlers. Track as tech debt for when handler count grows. |
| H-7 | `rebuild_collection_from_db` non-atomic | HIGH | Admin-only "nuclear rebuild" operation. Window is small. Acceptable for dev/admin tool. |
| M-3 | Temp file leak for non-mount ZIP extraction | MEDIUM | Docker containers are ephemeral. Mount path (production) has proper cleanup. |
| M-4 | `VectorConfig.target_schema` is dead config | MEDIUM | No runtime errors. Track as cleanup. |
| M-6 | submit.py 6-step orchestration non-transactional | MEDIUM | Idempotent via `get_or_overwrite_release`. Fix 3 addresses the most impactful orphan. |
| M-8 | Raw SQL in unpublish_handlers | MEDIUM | Unpublish crosses schemas in ways repositories don't support. Fix 4 improves atomicity. |

---

## ARCHITECTURE WINS (Preserve These)

**Anti-Corruption Layer at Platform Boundary.** `PlatformRequest` cleanly translates external DDH vocabulary into internal concepts. External callers never touch Asset, Release, or CoreMachine directly. Textbook bounded context isolation.

**Declarative Job Definition via JobBaseMixin.** Jobs are defined as data (stages list, parameters_schema) rather than code. Adding a new job type requires ~30 lines of configuration, not plumbing.

**Converter Strategy Pattern.** Vector format handling dispatched through a clean strategy pattern. Adding a new format requires one converter function and one dictionary entry.

**STAC as Materialized View.** pgSTAC is treated as a downstream projection — never source of truth. `STACMaterializer` can fully rebuild from internal DB. Eliminates an entire class of consistency bugs.

**Explicit Handler/Job Registries.** `ALL_JOBS` and `ALL_HANDLERS` are explicit dictionaries, not magic auto-discovery. Debuggable and prevents import-order surprises.

**Two-Entity Asset/Release Separation.** Asset (stable identity) vs Release (versioned artifact with lifecycle) is a clean domain model. `version_ordinal` with deterministic naming avoids "draft" ambiguity.

---

## FULL FINDINGS INVENTORY

### Unified Severity Rankings

| Sev | ID | Finding | Confidence | Source |
|-----|----|---------|------------|--------|
| CRITICAL | C-1 | `table_name` NameError in asset_service.py:348 | CONFIRMED | Alpha + Beta + Gamma |
| HIGH | H-1 | Approval check swallowed in unpublish | CONFIRMED | Beta |
| HIGH | H-2 | Non-atomic STAC delete + release revocation | CONFIRMED | Beta + Gamma |
| HIGH | H-3 | Orphaned release_tables on ETL failure | CONFIRMED | Gamma (blind spot) |
| HIGH | H-4 | Column name collision after sanitization | PROBABLE | Beta + Gamma |
| HIGH | H-5 | prepare_gdf() God method (700+ lines) | CONFIRMED | Alpha |
| HIGH | H-6 | No canonical HandlerResult contract | CONFIRMED | Alpha |
| HIGH | H-7 | rebuild_collection_from_db non-atomic | CONFIRMED | Beta |
| MEDIUM | M-1 | Dual processing status update race | CONFIRMED | Alpha + Beta |
| MEDIUM | M-2 | wkt_df_to_gdf no per-row error handling | PROBABLE | Beta |
| MEDIUM | M-3 | Temp file leak for non-mount ZIP extraction | CONFIRMED | Beta |
| MEDIUM | M-4 | VectorConfig.target_schema dead config | CONFIRMED | Gamma (blind spot) |
| MEDIUM | M-5 | platform_job_submit swallows exception context | CONFIRMED | Gamma (blind spot) |
| MEDIUM | M-6 | submit.py non-transactional orchestration | CONFIRMED | Alpha |
| MEDIUM | M-7 | Inconsistent error return conventions | CONFIRMED | Alpha |
| MEDIUM | M-8 | Raw SQL in unpublish_handlers | CONFIRMED | Alpha |
| MEDIUM | M-9 | create_tasks_for_stage .get() proliferation | CONFIRMED | Alpha |
| LOW | L-1 | EventCallback type alias in two places | CONFIRMED | Alpha |
| LOW | L-2 | slugify divergence (underscore vs hyphen) | CONFIRMED | Alpha + Gamma |
| LOW | L-3 | delete_blob TOCTOU race | CONFIRMED | Beta |
| LOW | L-4 | No timeout on GPKG layer validation | PROBABLE | Beta |
| LOW | L-5 | Antimeridian recursion (bounded to depth 2) | CONFIRMED | Beta + Gamma |
| LOW | L-6 | has_m check properly guarded | CONFIRMED | Beta |
| LOW | L-7 | Vector STAC materialization skips (by design) | CONFIRMED | Beta |
| LOW | L-8 | DDH identifier logging (potential PII) | PROBABLE | Gamma |
| LOW | L-9 | Handler-repository layering (intentional) | CONFIRMED | Alpha + Gamma |

### Verified Safe Patterns

| ID | Pattern | Confidence |
|----|---------|------------|
| VS-1 | Idempotent chunk upload (DELETE+INSERT) | CONFIRMED |
| VS-2 | "Last task turns out the lights" via advisory locks | CONFIRMED |
| VS-3 | Geometry validation pipeline ordering correct | CONFIRMED |
| VS-4 | State transition fail-fast | CONFIRMED |
| VS-5 | Approval state machine with atomic transitions | CONFIRMED |
| VS-6 | Revocation ordering (DB first, STAC second) | CONFIRMED |
| VS-7 | Empty GeoDataFrame guards | CONFIRMED |
| VS-8 | Column sanitization regex for SQL injection | CONFIRMED |
| VS-9 | BytesIO seek(0) correctly handled | CONFIRMED |
| VS-10 | PlatformConfig validator ensures pattern placeholders | CONFIRMED |
| VS-11 | Deterministic request IDs with pipe separator | CONFIRMED |

---

## PIPELINE STRUCTURE

| Agent | Role | Scope |
|-------|------|-------|
| **Omega** | Orchestrator | Split review into asymmetric architecture vs correctness lenses |
| **Alpha** | Architecture Reviewer | Design patterns, contracts, coupling, composition, extensibility |
| **Beta** | Correctness Reviewer | Race conditions, error recovery, atomicity, data integrity |
| **Gamma** | Adversarial Contradiction Finder | Found contradictions, blind spots, recalibrated severity |
| **Delta** | Final Arbiter | Synthesized into prioritized, actionable fixes |

### Key Contradictions Resolved by Gamma

**table_name bug severity**: Alpha rated LOW, Beta rated CRITICAL. Gamma confirmed CRITICAL — first release creation path is broken.

**Layering violation**: Alpha rated HIGH. Gamma downgraded to LOW — handlers ARE the service layer in this architecture.

**Dual status update**: Beta rated HIGH. Gamma downgraded to MEDIUM — data quality issue (NULL timestamp), not data loss.

**Antimeridian recursion**: Beta flagged as unbounded. Gamma confirmed bounded to depth 2.

### Blind Spots Found by Gamma (Neither Reviewer Caught)

- **H-3**: Orphaned release_tables on ETL failure (submit.py writes before job runs)
- **M-4**: VectorConfig.target_schema is dead config (ETL hardcodes 'geo')
- **M-5**: platform_job_submit swallows exception context, non-atomic job+queue creation

---

## METHODOLOGY

This review used the Adversarial Review pipeline from `docs_claude/AGENT_PLAYBOOKS.md`. All agents ran as Claude Code subagents within a single conversation. Alpha and Beta were dispatched in parallel; Gamma and Delta ran sequentially. No external API key required.
