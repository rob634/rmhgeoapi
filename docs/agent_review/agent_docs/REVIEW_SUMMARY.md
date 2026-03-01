# Adversarial Review Summary

**Date Range**: 26-28 FEB 2026
**Method**: Adversarial multi-agent pipeline (Omega -> Alpha + Beta parallel -> Gamma -> Delta)
**Result**: 35 of 35 actionable findings RESOLVED across 5 subsystems. Zero regressions.

---

## Reviews Conducted

| # | Subsystem | Scope | Files | Findings | Fixes | Commit | Tests |
|---|-----------|-------|-------|----------|-------|--------|-------|
| 1 | CoreMachine Orchestration | Job pipeline orchestrator -- CoreMachine, StateManager, triggers | ~25 | 18 | 5 (1C, 2H, 2M) | `fa05cc1` (V0.9.8.1) | 352 passing |
| 2 | Vector Workflow | Complete vector pipeline -- ingestion, PostGIS, STAC, approval, unpublish | ~20 | 12 | 10 (1C, 3H, 4M, 1L, 1 pre-resolved) | `8355f7c` | 330 passing |
| 3 | Tiled Raster Pipeline | Large file COG tiling -> pgSTAC -> TiTiler mosaic | ~10 | 9 | 5+1 (1C, 2H, 2M + dead code) | `51e8a28` | 352 passing |
| 4 | Approval Workflow | Approve/Reject/Revoke lifecycle across 3 trigger layers | 7 | 21 | 5 (1C, 2H, 1M, 1L) | `088aca9` | 362 passing |
| 5 | B2B Domain -- Review A | Entity design, state machines, repositories | 10 | 13 | 5 (2C, 3H) | `416124c` (V0.9.8.2) | Deployed + rebuilt |
| 6 | B2B Domain -- Review B | HTTP contracts, lifecycle integration, 3 approval layers | 12 | 37 | 5 (1C, 4H) | `416124c` (V0.9.8.2) | Deployed + rebuilt |

**Review A + B combined**: 22 files, ~15,000 lines, 50 unique findings after dedup, 10 fixes total.

### Additional: Approval Conflict Guard (Greenfield Pipeline)

A focused greenfield pipeline (S -> A+C+O -> M -> B -> V) produced the version-ID conflict guard and atomic rollback mechanism, deployed alongside B2B fixes in `416124c`.

### Review Methodology

| Agent | Role |
|-------|------|
| **Omega** | Orchestrator -- splits review into asymmetric lenses |
| **Alpha** | Architecture reviewer -- design patterns, contracts, coupling |
| **Beta** | Correctness reviewer -- race conditions, atomicity, data integrity |
| **Gamma** | Adversarial contradiction finder -- disagreements, blind spots, severity recalibration |
| **Delta** | Final arbiter -- prioritized, actionable fixes |

---

## All Completed Fixes

### CoreMachine Orchestration (5 fixes -- commit `fa05cc1`)

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | CRITICAL | Orphan PENDING tasks block stage completion forever -- SB send fails after DB insert | Mark orphan task FAILED on SB send failure via `fail_task()`. Zero-queued check fails job immediately. |
| 2 | HIGH | All 13 `_mark_job_failed` call sites omit `job_type` -- callback always gets `'unknown'` | Added `job_type=` kwarg to all 13 call sites. |
| 3 | HIGH | TOCTOU race in `complete_task_with_sql` -- duplicate message raises `RuntimeError` | Re-check task status on `task_updated=False`; return no-op if already COMPLETED/FAILED. |
| 4 | MEDIUM | `fail_all_job_tasks` bypasses repo pattern with raw SQL and hardcoded `"app"` schema | New `fail_tasks_for_job()` on TaskRepository using `self.schema_name`. |
| 5 | MEDIUM | `_confirm_task_queued` creates fresh DB connections per task message | Accept optional `task_repo` param; caller passes existing repo. |

### Vector Workflow (10 fixes -- commit `8355f7c`)

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| C-1 | CRITICAL | `table_name` NameError in `asset_service.py:348` -- crashes first-ever release creation | Removed stale `table_name=table_name` kwarg. |
| H-1 | HIGH | Approval guard swallowed on DB failure allows unauthorized unpublish | Changed from fail-open to fail-closed. |
| H-2 | HIGH | Non-atomic STAC delete + release revocation uses separate connections | Moved revocation into same cursor/connection for atomic commit. |
| H-3 | HIGH | Orphaned `release_tables` entry on ETL validation failure | Removed premature placeholder write with `geometry_type='UNKNOWN'`. |
| M-1 | MEDIUM | Dual processing status update -- handler vs callback race | Removed redundant status updates -- callback is canonical. |
| M-2 | MEDIUM | Per-row WKT parsing crashes on bad geometry | `_safe_wkt_load()` -- drops bad rows instead of crashing. 5 new tests. |
| M-5 | MEDIUM | Service Bus send failure leaves orphan jobs | SB send failure marks job FAILED. Outer handler re-raises with context. |
| M-7 | MEDIUM | Missing `error_type` in failure returns | Audit found all 14 returns already include it. Already resolved. |
| M-9 | MEDIUM | 30+ manual `.get()` calls for param passthrough | Declarative `_PASSTHROUGH_PARAMS` list. |
| L-1 | LOW | `EventCallback` type alias duplicated across 3 files | Centralized to `services/vector/__init__.py`. |

### Tiled Raster Pipeline (5+1 fixes -- commit `51e8a28`)

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| C-1 | CRITICAL | `config_obj.raster.use_etl_mount` AttributeError -- crashes all single-COG Docker processing | Changed 4 references to `config_obj.docker.*`. |
| C-2 | HIGH | `raster_type` unbound on VSI checkpoint resume -- NameError in Phase 4 | Added `raster_type` recovery from `extraction_result.raster_metadata`. |
| H-1 | HIGH | Zero tile overlap in mount workflow causes visible seams | Added `overlap=512` matching VSI workflow. |
| 4 | MEDIUM | `_calculate_spatial_extent_from_tiles` opens every COG via HTTP (~200 GETs) | Extract `spatial_extent` from `tiling_result` bounds. HTTP fallback retained for collection handler. |
| 5 | MEDIUM | `AZURE_STORAGE_KEY` unguarded env access -- undefined GDAL behavior with MI | Removed all storage key references. Fallback uses `AZURE_AD` auth. |
| M-5 | MEDIUM | `TiTilerSearchService` is dead code (266 lines) | Deleted `services/titiler_search_service.py`. |

### Approval Workflow (5 fixes -- commit `088aca9`)

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | CRITICAL | `_delete_stac()` deletes ALL items in pgSTAC collection on tiled revocation | Tag items with `ddh:release_id` at materialization. Filter deletion to matching items. Legacy fail-safe skip. |
| 2 | HIGH | Exception handlers leak `str(e)` to unauthenticated callers across all 3 trigger layers | New `safe_error_response()` in `http_base.py`. 18 catch blocks sanitized. |
| 3 | HIGH | Post-atomic STAC materialization failure undetected | try/except wrapper, CRITICAL log, `last_error` field via `update_last_error()`. |
| 4 | MEDIUM | `approve_release_atomic()` doesn't clear `rejection_reason` | Added `rejection_reason = NULL` to both SQL branches. |
| 5 | LOW | `reject_release()` calls `can_approve()` instead of `can_reject()` | Changed to `can_reject()`. |

### B2B Domain -- Reviews A + B (10 fixes -- commit `416124c`)

| # | Sev | Finding | Resolution |
|---|-----|---------|------------|
| 1 | CRITICAL | `update_approval_state()` has no WHERE guard -- concurrent calls can approve already-rejected releases | Added `AND approval_state = 'pending_review'` to WHERE. Returns `False` on rowcount 0. |
| 2 | CRITICAL | `(asset_id, version_ordinal)` has no uniqueness constraint + ordinal query checks wrong column | Fixed query to `version_ordinal IS NOT NULL`. Added `uq_release_asset_ordinal` partial unique constraint. |
| 3 | CRITICAL | Approval contracts inconsistent across 3 layers -- different field names, error shapes | Standardized to `reviewer` field (accepting `revoker` alias). All JSON parse failures return 400. Auto-generate `version_id` from ordinal. |
| 4 | HIGH | Release not re-read after atomic approval -- STAC materialization uses stale state | Added `release = self.release_repo.get_by_id(release_id)` after atomic approval. |
| 5 | HIGH | 44-column INSERT duplicated -- drift risk | Extracted `_INSERT_COLUMNS` tuple, `_build_insert_values()`, `_build_insert_sql()` shared methods. |
| 6 | HIGH | Raster unpublish reconstructs `stac_item_id` from DDH identifiers instead of reading Release | Reads from Release record via `get_by_job_id()`. Falls back to DDH reconstruction for pre-V0.9. |
| 7 | HIGH | Collection-level unpublish skips release revocation | Added revocation loop before job submission. New `get_by_stac_item_id()` repository method. |
| 8 | HIGH | Catalog returns 200 for not-found, leaks exception details in 500s | Added `_catalog_error_response()` helper. 404 for not-found. All 5 exception handlers sanitized. |
| 9 | HIGH | DDH `version_id` resolution fails -- `suggested_version_id` vs internal mismatch | Two-pass lookup: `get_by_suggested_version()` first, fall back to `get_by_version()`. Fixed `and version_id` to `and version_id is not None`. |
| 10 | HIGH | `nominal_refs`, `version_ref`, `uses_versioning` not persisted | Added all 3 columns to 4 SELECT lists, INSERT, and `_row_to_platform()` mapper. |

### Approval Conflict Guard (Greenfield Pipeline)

| Component | Resolution |
|-----------|------------|
| Version-ID conflict guard | `idx_releases_version_conflict` partial unique index. NOT EXISTS subquery in `approve_release_atomic()`. UniqueViolation caught with explicit rollback. |
| Atomic rollback | New `rollback_approval_atomic()` for STAC materialization failures. Preserves audit trail. |
| Typed error responses | `VersionConflict` -> 409, `StacMaterializationError` -> 500, `StacRollbackFailed` -> 500. `ERROR_STATUS_MAP` dict. |

---

## Deployment & Verification Log (28 FEB 2026)

| Step | Result |
|------|--------|
| Deploy orchestrator (`./deploy.sh orchestrator`) | v0.9.8.2 deployed, health check passed |
| Schema rebuild (`action=rebuild`) | 24 tables, 112 indexes, 21 enums, 5 functions, 2 triggers -- all verified |
| Test job (`hello_world`) | Completed in ~12s -- 2 stages, 6/6 tasks, 0 failures |
| New constraint `uq_release_asset_ordinal` | Created via rebuild |
| Platform columns (`nominal_refs`, `version_ref`, `uses_versioning`) | Created via rebuild |
| Version-conflict-guard index `idx_releases_version_conflict` | Created via rebuild |

---

## Accepted Risks (All Subsystems)

### CoreMachine Orchestration

| ID | Sev | Finding | Rationale |
|----|-----|---------|-----------|
| BLIND-2 | HIGH | Exception swallowing prevents dead-lettering; double-failure = stuck job | Intentional -- re-raising causes infinite retries. Janitor detects by timeout. |
| BLIND-3 | HIGH | Stage advancement rollback race | Double-failure requires simultaneous SB + PostgreSQL outage. Janitor covers. |
| C4 | MEDIUM | Transition rules duplicated between `transitions.py` and model | Defense-in-depth. DB enforces authoritative transitions. |
| BUG-5 | MEDIUM | Retry creates duplicate messages without deduplication IDs | SB configuration concern, not code bug. Idempotency handles. |
| RISK-1 | MEDIUM | SB lock expiration during long tasks causes duplicate execution | Mitigated by idempotent task completion (Fix 3). |
| C7 | MEDIUM | `process_task_message()` is 812 lines | Battle-tested. Refactor when logic stabilizes. |
| C1 | MEDIUM | Duplicate repository bundles in CoreMachine and StateManager | Functional. Address during DI cleanup. |
| Others | LOW | 10 LOW findings (BUG-4, BLIND-1/4/5, C5/6/8/9, RISK-2/3/4, EDGE-1/2/5) | Theoretical, cosmetic, or non-critical paths. |

### Vector Workflow

| ID | Sev | Finding | Rationale |
|----|-----|---------|-----------|
| H-4 | HIGH | Column name collision after sanitization | Theoretical edge case, no incidents. |
| H-5 | HIGH | `prepare_gdf()` is 700+ lines, 15+ concerns | Works correctly. Multi-day refactor with regression risk. |
| H-6 | HIGH | No canonical `HandlerResult` contract | Works for all current handlers. Track for growth. |
| H-7 | HIGH | `rebuild_collection_from_db` non-atomic | Admin-only operation. Small window. |
| Others | MED-LOW | 8 findings (M-3/4/6/8, L-2/3/4/8) | Docker ephemeral, dead config, theoretical races, cosmetic. |

### Tiled Raster Pipeline

| ID | Sev | Finding | Rationale |
|----|-----|---------|-----------|
| H-1 | HIGH | VSI workflow has no per-tile Phase 3 checkpoint | Mount workflow (production) has resume. VSI is fallback. |
| **H-2** | **HIGH** | **Two duplicate ~500-line tiled workflows** | **Biggest tech debt.** Both stable. Multi-day consolidation. |
| H-4 | HIGH | `_process_raster_tiled_mount` is ~645 lines | Readability. Fix during H-2 consolidation. |
| Others | MED-LOW | 6 findings (M-1/4/6/7/8, L-1) | Theoretical, stable, or cosmetic. |

### B2B Domain (Reviews A + B)

| ID | Sev | Finding | Rationale |
|----|-----|---------|-----------|
| B-16 | HIGH | All endpoints `AuthLevel.ANONYMOUS` | Dev environment; Gateway handles auth. Pre-production requirement. |
| A-4 | MEDIUM | Race in `get_or_overwrite_release()` ordinal | Low traffic; unique constraint is DB safety net. |
| A-1 | MEDIUM | God Object (AssetRelease, 45 fields) | Flat table projection, not behavior-rich. |
| Others | LOW | 15 findings (A-7, B-1/2/5/6/8/9/11/13/14/15, A-2, B-13) | Cosmetic, known patterns, or feature-gated. |

---

## Architecture Wins (Preserve These)

### CoreMachine
- **Advisory-lock stage completion** -- `pg_advisory_xact_lock` for "last task turns out the lights"
- **Composition + explicit registry injection** -- All deps via constructor; validated at import time
- **RETRYABLE vs PERMANENT exception categorization** -- Module-level tuples with handler branches
- **Checkpoint-based observability** -- Structured `extra` dicts for every state transition
- **JobBase + JobBaseMixin split** -- Template Method; 77% boilerplate reduction

### Vector Workflow
- **Anti-Corruption Layer** at platform boundary -- `PlatformRequest` translates DDH vocabulary
- **Declarative job definition** via JobBaseMixin -- Jobs defined as data
- **Converter strategy pattern** -- New format = one function + one dict entry
- **STAC as materialized view** -- pgSTAC is downstream projection, never source of truth
- **Explicit handler/job registries** -- No magic auto-discovery
- **Two-entity Asset/Release separation** -- Clean domain model with `version_ordinal`

### Tiled Raster Pipeline
- **CheckpointManager** -- Phase tracking with artifact validation and shutdown awareness
- **ETL-owned pgSTAC write pattern** -- TiTiler stays read-only
- **Non-fatal STAC with degraded mode** -- `"degraded": True` instead of failing the job
- **Handler registry with import-time validation** -- Catches misconfig at import
- **Disaster recovery via `metadata.json` sidecar** -- Manual STAC reconstruction without DB
- **Typed Pydantic result models** -- `COGCreationResult`, `RasterValidationResult`, `STACCreationResult`

### B2B Domain
- **Asset/Release entity split** -- Stable identity vs versioned content
- **`approve_release_atomic()` single transaction** -- Atomic state change with `is_latest` flip
- **Version-conflict guard** (NOT EXISTS + partial unique index) -- Prevents duplicate approvals
- **Deterministic ID generation** (SHA256) -- Idempotent job deduplication
- **Anti-corruption layer** DDH -> CoreMachine -- `platform_translation.py` isolates external vocabulary
- **B2C sanitization** stripping `geoetl:*` -- Internal properties never leak to public STAC
- **Advisory locks for find_or_create** -- Prevents duplicate Asset creation
- **Typed error responses** via ERROR_STATUS_MAP -- Declarative HTTP status mapping

---

## Cross-Cutting Tech Debt

| Theme | Affected Subsystems | Effort | Priority |
|-------|-------------------|--------|----------|
| **Tiled workflow consolidation (H-2)** | Tiled Raster | L (multi-day) | Medium -- addresses H-1, H-4, M-6, M-7 simultaneously |
| **`prepare_gdf()` God method (H-5)** | Vector | L (multi-day) | Medium -- addresses H-4 (column collision) as side effect |
| **Canonical HandlerResult contract (H-6)** | Vector | M | Low -- only matters when handler count grows |
| **DI/Repository cleanup** | CoreMachine | M | Low -- C1, C9 are stable bypass paths |
| **812-line process_task_message() (C7)** | CoreMachine | L | Low -- battle-tested, well-labeled |

---

## Verified Safe Patterns (Vector)

| Pattern | Confidence |
|---------|------------|
| Idempotent chunk upload (DELETE+INSERT) | CONFIRMED |
| "Last task turns out the lights" via advisory locks | CONFIRMED |
| Geometry validation pipeline ordering | CONFIRMED |
| State transition fail-fast | CONFIRMED |
| Approval state machine with atomic transitions | CONFIRMED |
| Revocation ordering (DB first, STAC second) | CONFIRMED |
| Empty GeoDataFrame guards | CONFIRMED |
| Column sanitization regex for SQL injection | CONFIRMED |
| BytesIO seek(0) correctly handled | CONFIRMED |
| PlatformConfig validator ensures pattern placeholders | CONFIRMED |
| Deterministic request IDs with pipe separator | CONFIRMED |
