# Adversarial Review — Remaining Issues & Architecture Wins

**Date**: 26 FEB 2026
**Status**: All actionable fixes complete. This document tracks accepted risks and architecture guidance.

---

## Accepted Risks by Subsystem

### CoreMachine Orchestration

| ID | Sev | Finding | Rationale |
|----|------|---------|-----------|
| BLIND-2 | HIGH | Exception swallowing prevents dead-lettering; double-failure = permanently stuck job | Intentional — re-raising causes infinite retry loops for non-transient errors. Janitor detects stuck jobs by timeout. |
| BLIND-3 | HIGH | Stage advancement PROCESSING→QUEUED→PROCESSING rollback race | Double-failure requires simultaneous SB + PostgreSQL outage. Primary case handled by C1.6 fix. Janitor covers this. |
| C4 | MEDIUM | Transition rules duplicated between `transitions.py` and model methods | Defense-in-depth. DB enforces authoritative transitions. Low divergence risk. |
| BUG-5 | MEDIUM | Retry creates duplicate messages without deduplication IDs | SB configuration concern (`RequiresDuplicateDetection`), not a code bug. Idempotency handling covers this. |
| RISK-1 | MEDIUM | SB lock expiration during long tasks causes duplicate handler execution | Mitigated by idempotent task completion (Fix 3). |
| C7 | MEDIUM | `process_task_message()` is 812 lines with deep nesting | Battle-tested. Refactor when orchestration logic stabilizes. |
| C1 | MEDIUM | Duplicate repository bundles in CoreMachine and StateManager | Functional. Address during broader DI cleanup. |
| BUG-4 | LOW | Failed tasks don't trigger stage completion check | Blocks COMPLETED_WITH_ERRORS status. Low priority. |
| BLIND-1 | LOW | SQL function body uses `.format()` for schema | Latent injection vector. Schema name is config-controlled, not user input. |
| C5 | LOW | `StateManager.handle_stage_completion()` signature mismatch with interface | No runtime impact. |
| C6 | LOW | `JobBase` @staticmethod vs `JobBaseMixin` @classmethod tension | Design tension, not a bug. |
| RISK-2 | LOW | Managed identity token caching expires after ~1 hour in Docker workers | Azure SDK handles refresh. Monitor. |
| RISK-3/4 | LOW | `store_stage_results()` and monitoring methods swallow exceptions | Non-critical paths. |
| C8 | LOW | Event recording has 10+ identical try/except blocks | DRY concern, not a bug. |
| BLIND-4 | LOW | `total_stages` always None in completion logs | Cosmetic. |
| BLIND-5 | LOW | Truncated lock token in logs | Minimal security exposure. |
| C9 | LOW | `fan_in.py` creates its own repository, bypassing factory | Fix during DI cleanup. |
| EDGE-1,2,5 | LOW | Edge cases: QUEUED status race, negative stage, second handler continues | Theoretical. |

### Vector Workflow

| ID | Sev | Finding | Rationale |
|----|------|---------|-----------|
| H-4 | HIGH | Column name collision after sanitization | Theoretical edge case, no incidents. Fix during H-5 refactor. |
| H-5 | HIGH | `prepare_gdf()` is 700+ lines, 15+ concerns | Works correctly. Multi-day refactor with regression risk. Track as enabler story. |
| H-6 | HIGH | No canonical `HandlerResult` contract | Works for all current handlers. Track for when handler count grows. |
| H-7 | HIGH | `rebuild_collection_from_db` non-atomic | Admin-only "nuclear rebuild" operation. Small window. |
| M-3 | MEDIUM | Temp file leak for non-mount ZIP extraction | Docker containers are ephemeral. Mount path (production) has proper cleanup. |
| M-4 | MEDIUM | `VectorConfig.target_schema` is dead config | No runtime errors. Track as cleanup. |
| M-6 | MEDIUM | `submit.py` 6-step orchestration non-transactional | Idempotent via `get_or_overwrite_release`. |
| M-8 | MEDIUM | Raw SQL in unpublish_handlers | Crosses schemas in ways repositories don't support. |
| L-2 | LOW | `slugify` divergence (underscore vs hyphen) | Accepted. |
| L-3 | LOW | `delete_blob` TOCTOU race | Theoretical. |
| L-4 | LOW | No timeout on GPKG layer validation | Theoretical. |
| L-8 | LOW | DDH identifier logging (potential PII) | Low exposure. |

### Tiled Raster Pipeline

| ID | Sev | Finding | Rationale |
|----|------|---------|-----------|
| H-1 | HIGH | VSI workflow has no per-tile Phase 3 checkpoint (~50 min lost on failure) | Mount workflow (production path) has per-tile resume. VSI is fallback only. |
| **H-2** | **HIGH** | **Two duplicate ~500-line tiled workflows** | **Biggest tech debt item.** Real maintenance hazard, but consolidation is multi-day Feature-level refactor. Both are stable. |
| H-4 | HIGH | `_process_raster_tiled_mount` is ~645 lines | Readability concern. Refactor during H-2 consolidation. |
| M-1 | MEDIUM | Python hash vs pgSTAC GENERATED column hash divergence | Theoretical. Consistent serialization. Monitor. |
| M-4 | MEDIUM | Partial `cog_metadata` state on extraction failure | Recoverable via upsert on retry. |
| M-6 | MEDIUM | Fan-in mode in `stac_collection.py` is legacy | Functions correctly. Remove during H-2 consolidation. |
| M-7 | MEDIUM | Untyped inter-phase dict contracts | Real debt. Fix during H-2 refactor. |
| M-8 | MEDIUM | Direct infrastructure imports in `stac_collection.py` | Stable. Fix during service layer refactoring. |
| L-1 | LOW | Inconsistent `total_phases` in progress reporting | Cosmetic only. |

---

## Cross-Cutting Tech Debt Themes

| Theme | Affected Subsystems | Effort | Priority |
|-------|-------------------|--------|----------|
| **Tiled workflow consolidation (H-2)** | Tiled Raster | L (multi-day) | Medium — addresses H-1, H-4, M-6, M-7 simultaneously |
| **`prepare_gdf()` God method (H-5)** | Vector | L (multi-day) | Medium — addresses H-4 (column collision) as side effect |
| **Canonical HandlerResult contract (H-6)** | Vector | M | Low — only matters when handler count grows |
| **DI/Repository cleanup** | CoreMachine | M | Low — C1, C9 are stable bypass paths |
| **812-line process_task_message() (C7)** | CoreMachine | L | Low — battle-tested, well-labeled |

---

## Architecture Wins (Preserve These)

These patterns were identified as strengths across all 3 reviews. Do not regress.

### CoreMachine
- **Advisory-lock stage completion** — `pg_advisory_xact_lock` keyed on `job_id:stage` for "last task turns out the lights"
- **Composition + explicit registry injection** — CoreMachine receives all deps via constructor; `ALL_JOBS`/`ALL_HANDLERS` validated at import time
- **RETRYABLE vs PERMANENT exception categorization** — Module-level tuples with corresponding handler branches
- **Checkpoint-based observability** — Structured `extra` dicts for every state transition
- **JobBase + JobBaseMixin split** — Template Method pattern; 77% boilerplate reduction per job

### Vector Workflow
- **Anti-Corruption Layer at platform boundary** — `PlatformRequest` translates external DDH vocabulary
- **Declarative job definition via JobBaseMixin** — Jobs defined as data (stages list, parameters_schema)
- **Converter strategy pattern** — Adding a format requires one converter function + one dict entry
- **STAC as materialized view** — pgSTAC is downstream projection, never source of truth
- **Explicit handler/job registries** — No magic auto-discovery
- **Two-entity Asset/Release separation** — Clean domain model with `version_ordinal`

### Tiled Raster Pipeline
- **CheckpointManager design** — Clean phase tracking with artifact validation and shutdown awareness
- **ETL-owned pgSTAC write pattern** — TiTiler stays read-only; ETL owns all writes
- **Non-fatal STAC with degraded mode** — STAC failure returns `"degraded": True` instead of failing the job
- **Handler registry with import-time validation** — Catches misconfig at import, not at job submission
- **Disaster recovery via `metadata.json` sidecar** — Allows manual STAC reconstruction without DB
- **Typed Pydantic result models** — `COGCreationResult`, `RasterValidationResult`, `STACCreationResult`

### Verified Safe Patterns (Vector)
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
