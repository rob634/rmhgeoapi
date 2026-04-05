# Working Backlog

**Last Updated**: 04 APR 2026
**Version**: v0.10.10.1

**Source of Truth**:
- SAFe product docs: `docs/product/` (EPICS.md, STORIES_F1-F5)
- Deferred fixes: `V10_DEFERRED_FIXES.md`
- Architecture decisions: `V10_DECISIONS.md`
- Completed work: `docs_claude/HISTORY.md`

---

## Active Phase: v0.10.10 — DAG is Default

DAG is the default submission path for all workflows. CoreMachine (Epoch 4) remains available but is no longer the primary. This phase validates that every workflow type completes end-to-end through the DAG engine under real conditions: submit, process, approve, materialize STAC, serve tiles. Bugs are fixed as found.

Discovery automation (8 handlers + 2 workflows) merged in v0.10.10.1.

---

## Feature Status Summary

Non-Done stories only. All other stories across F1-F5 are Done.

| ID | Story | Feature | Status | Notes |
|----|-------|---------|--------|-------|
| S1.12 | Enhanced data validation | F1 | Partial | Datetime range done; pandera evaluation pending (spike) |
| S2.3 | Raster collection pipeline | F2 | Partial | `process_raster_collection.yaml` designed, not E2E tested |
| S2.12 | Raster classification | F2 | Planned | Band count + dtype + value range decision tree |
| S2.14 | FATHOM ETL Phase 2 | F2 | Partial | 46/47 spatial merge tiles complete, 1 failed task pending retry |
| S3.9 | CMIP6 data hosting | F3 | Planned | Curated East Africa climate projections (SSP2-4.5, SSP5-8.5) |
| S3.10 | TiTiler unified services | F3 | Planned | Consolidate COG + Zarr tile serving into single deployment |

---

## v0.10.10 Work Items

Active work for the current phase.

| Item | Status | Details |
|------|--------|---------|
| DAG switchover validation | In Progress | All 10 workflows running through DAG as default path |
| E2E raster collection (S2.3) | Pending | `process_raster_collection.yaml` needs live Azure test |
| FATHOM retry (S2.14) | Pending | 1 failed tile (`n10-n15_w005-w010`), retry with `force_reprocess=true` |
| DF-JANITOR-1: pgSTAC search bloat | Pending | Janitor sweep to delete orphan `pgstac.searches` rows not referenced by active releases |
| Bug fixes as discovered | Ongoing | Fix and deploy as issues surface during validation |

---

## v0.11.0 Horizon — Strangler Fig Complete

Remove all Epoch 4 legacy: CoreMachine, Service Bus queues, Python job classes, dual-poll worker logic. After v0.11.0, DAG is the only orchestration path.

Discovery automation already merged (v0.10.10.1). Service Bus enabler (EN7) deprecated.

**Key removals**:
- `core/machine.py` (CoreMachine state machine)
- `core/state_manager.py`
- Service Bus queue config (`geospatial-jobs`, `functionapp-tasks`, `container-tasks`)
- `jobs/*.py` (Epoch 4 job classes)
- Worker dual-poll logic in `docker_service.py`
- `WORKER_FUNCTIONAPP` app mode

---

## Deferred / Backlog

### Deferred Fixes (from V10_DEFERRED_FIXES.md)

**SHOULD FIX (before v0.11.0)**:

| ID | Item | Priority |
|----|------|----------|
| DF-JANITOR-1 | pgSTAC search table bloat — orphan rows from duplicate registration | HIGH |

**NICE TO HAVE**:

| ID | Item | File |
|----|------|------|
| DF-LOG-1 | `get_tasks_for_run` logs at INFO on every call (should be DEBUG) | `infrastructure/workflow_run_repository.py` |
| DF-LOG-2 | Multi-band non-multispectral render falls through silently | `services/stac_renders.py` |
| DF-CFG-1 | JanitorConfig reads `os.environ` directly (Constitution S2.2 violation) | `core/dag_janitor.py` |
| DF-CFG-2 | `fail_task` docstring contradicts SQL behavior | `infrastructure/workflow_run_repository.py` |
| DF-CFG-3 | `target_width_pixels` / `target_height_pixels` passed but unused | `services/raster/handler_generate_tiling_scheme.py` |
| DF-CFG-4 | Minute-level granularity in schedule `request_id` (collision risk) | `core/dag_scheduler.py` |
| DF-CFG-5 | Missing EPOCH in `orchestration_manager.py` file header | `core/orchestration_manager.py` |

**Known Bugs**:

| Bug | Impact |
|-----|--------|
| `validate` reclaimed by janitor on large files (60s+ exceeds heartbeat) | Large file validation killed mid-flight |
| Epoch 4 Guardian enum mismatch after schema rebuild | Harmless — Epoch 4 only, removed at v0.11.0 |

### Technical Debt

**EN-TD.2: psycopg3 Type Adapter Cleanup** (Phase 1 done, Phases 2-4 remaining)

| Phase | Status | Scope |
|-------|--------|-------|
| Phase 1: Register adapters | Done | Adapters in `db_utils.py`, all repos inherit |
| Phase 2: Revert bandaid in `asset_repository.update()` | Ready | Remove `isinstance` dict/list check + enum pre-conversion |
| Phase 3: Remove redundant `json.dumps()` across repos | Ready | ~50 sites across 8+ repos. One repo per commit. |
| Phase 4: Cleanup models + documentation | Blocked by Phase 3 | Delete dead `to_dict()`, deprecated `json_encoders` |

**EN-TD.3: Multi-App Routing Cleanup** (low priority)

Remove dead queue configs, unused app URLs, `_force_functionapp` override, `WORKER_FUNCTIONAPP` mode, obsolete TaskRecord fields. Plan: `docs_claude/MULTI_APP_CLEANUP.md`. Largely superseded by v0.11.0 Epoch 4 removal.

**EN-TD.4: Core Orchestration Refactors** (deferred)

C1.5 (consolidate repo bundles), C1.8 (decompose `process_task_message` 811 lines), C2.8 (remove legacy AppConfig aliases), C8.4 (split `base.py` 3100-line monolith). High risk, low urgency. Revisit after v0.11.0.

### Styles and Legends Migration (US 5.5)

D360 gap: legend info (1.9) and raster legend (3.5). Cross-repo work (rmhgeoapi ETL writes + rmhtitiler service reads). Plan: `docs_claude/D360_STYLES_LEGENDS_MIGRATION.md`.

| Phase | Status | Scope |
|-------|--------|-------|
| Phase 1: Vector styles to rmhtitiler | Not started | Copy models + translator, rewrite repo (asyncpg), create FastAPI router |
| Phase 2: Database permissions | Not started | GRANT SELECT to geotiler user |
| Phase 3: Deprecate rmhgeoapi endpoints | Future | Add Deprecation header, eventually remove |

### DDH Platform Integration

| Item | Status | Details |
|------|--------|---------|
| API contract review with DDH team | In progress | US 7.1 |
| Environment provisioning (QA/UAT/PROD) | Not started | US 7.3 |
| B2B request context tracking | Not started | US 7.x — extend ApiRequest with client fields |
| Integration test suite | Not started | EN 7.4 — round-trip tests for vector, raster, OGC, jobs |

### Future (When Funded / Prioritized)

| Item | Status | Notes |
|------|--------|-------|
| S3.9: CMIP6 data hosting | Planned | East Africa climate projections |
| S3.10: TiTiler unified services | Planned | Single deployment for COG + Zarr |
| S2.12: Raster classification | Planned | Automated band/dtype/range decision tree |
| H3 analytics (Rwanda aggregation, flood exposure) | Deferred | Infrastructure ready, needs client funding |
| AzCopy integration | Planned | 5-10x blob transfer speedup |

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| Done | Complete |
| In Progress | Currently active |
| Partial | Partially implemented |
| Planned | Designed but not started |
| Pending | Ready to start |
| Not started | No work done |
| Deferred | Postponed intentionally |
