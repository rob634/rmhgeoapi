# Agent Pipeline Run Log

All pipeline executions in chronological order.

**Runs 1-43 (v0.9.x era)**: Condensed to `agent_docs/RUNS_HISTORY_v09.md`. Full detail docs archived to `docs/archive/agent_review/`.

**Active runs (v0.10.x)**: Below.

---

## Run 44: DB-Polling Task Dispatch (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 15 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DB-polling task dispatch subsystem — SKIP LOCKED migration from Service Bus |
| **Version** | v0.10.3.0 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 9 |
| **Findings** | 18 total: 3 CRITICAL, 4 HIGH, 6 MEDIUM, 5 LOW |
| **Fixes Applied** | 11 (all CRITICAL + HIGH + 4 MEDIUM) |
| **Accepted Risks** | 2 resolved (janitor implemented in `dag_janitor.py`, double PROCESSING write moot — SB deprecated). 1 still open: health check auth — diagnostics exception (by design for K8s probes) |
| **Verdict** | Sound architecture, critical shutdown/retry bugs fixed, deployable |

**Scope Split C — Alpha (Data Integrity) / Beta (Control Flow)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Data validation, enum alignment, schema evolution, datetime consistency | enums.py, task.py, transitions.py, queue.py, sql_generator.py, jobs_tasks.py |
| Beta | SKIP LOCKED atomicity, graceful shutdown, retry path, race conditions | jobs_tasks.py, machine.py, docker_service.py, transitions.py |
| Gamma | Blind spots: health check auth, status API gaps, index coverage | shared.py, defaults.py, sql_generator.py, get_job_status.py |

**Top Fixes**:

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | Connection pool destroyed while task in-flight (SIGTERM) | CRITICAL | `finalize_shutdown()` after thread join |
| 2 | `check_job_completion` ignores SKIPPED/CANCELLED | HIGH | `terminal_tasks` count |
| 3 | Non-atomic retry (two writes, conflicting backoff) | CRITICAL | Single atomic SQL function |
| 4 | PENDING_RETRY→PROCESSING bypass | CRITICAL | Transition table updated |
| 5 | `fail_tasks_for_job` overwrites settled states | HIGH | Excluded skipped/cancelled |

---

## Run 45: DB-Polling Regression (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 15 MAR 2026 |
| **Pipeline** | SIEGE (Sequential Smoke Test) |
| **Scope** | Post-deployment regression — DB-polling migration validation |
| **Version** | v0.10.3.0 |
| **Profile** | Quick |
| **Pass Rate** | **18/18 (100%)** |
| **Duration** | 1m 52s |
| **Findings** | 1 LOW (dbadmin task_counts missing 3 new statuses) |
| **Verdict** | Zero regressions. DB-polling fully functional. |

**Sequences**:

| Seq | Name | Verdict | Notes |
|-----|------|---------|-------|
| S0 | Endpoint Probes (7) | PASS | All healthy |
| S1 | Raster Lifecycle | PASS | Submit → complete → approve → catalog → TiTiler |
| S2 | Vector Lifecycle | PASS | Submit → complete → approve → catalog → OGC Features |
| S3 | Status API Validation | PASS | All 8 TaskStatus values in responses |
| S4 | Negative Tests | PASS | Ghost file → 400, fake release → 404 |

**Finding**:

| ID | Severity | Description |
|----|----------|-------------|
| SG18-F1 | LOW | `dbadmin/jobs` task_counts missing `pending_retry`, `skipped`, `cancelled` — only 4 of 8 statuses |

---

## Recurring Review Patterns

Two subsystems are designated for **regular re-review** using the COMPETE pipeline with full constitution enforcement. These are the highest-churn, highest-risk areas of the codebase — each has been the source of multiple SIEGE/TOURNAMENT findings across runs.

### Pattern A: Approval Workflow Review

**Original**: Run 4 (27 FEB 2026) — pre-constitution, 21 findings, 5 fixes
**Why recurring**: The approval lifecycle is the most-patched subsystem. Runs 4, 5, 6, 12, 14, 16, 25, 26, 27 all found or fixed approval-related issues. Every fix is a potential constitution violation introduction point.

**Scope** (7 files, ~7,000 lines):
- `triggers/trigger_approvals.py` — approve/reject/revoke endpoints
- `services/asset_approval_service.py` — approval business logic
- `infrastructure/release_repository.py` — release persistence + atomic state transitions
- `core/models/asset.py` — AssetRelease model + state machine
- `core/models/platform.py` — PlatformRequest validation
- `services/stac_materialization.py` — STAC writes at approval time
- `infrastructure/pgstac_repository.py` — pgSTAC operations

**Constitution focus**: Sections 1 (zero-tolerance), 2 (config access), 3 (error handling), 5 (platform boundaries), 6 (database patterns)

**Recommended split**: B (Internal vs External) — Internal logic/invariants vs boundary contracts/error surfaces

**Cadence**: After every deployment that touches approval files, or monthly.

### Pattern B: CoreMachine Orchestration Review

**Original**: Run 1 (26 FEB 2026) — pre-constitution, 18 findings, 5 fixes
**Why recurring**: CoreMachine is the heart of all job processing. The zero-task stage guard (added post-Run 9) and various error handling changes make this a constitution compliance hotspot. Exception swallowing patterns (accepted risk BLIND-2) should be re-evaluated against Section 3.3.

**Scope** (8 files, ~5,600 lines):
- `core/machine.py` — orchestration engine
- `core/state_manager.py` — job/task state persistence
- `core/logic/transitions.py` — state machine rules
- `jobs/base.py` — abstract job interface
- `jobs/mixins.py` — JobBaseMixin (77% boilerplate reduction)
- `services/__init__.py` — handler registry
- `triggers/service_bus/task_handler.py` — task message processing
- `triggers/service_bus/job_handler.py` — job message processing

**Constitution focus**: Sections 1 (zero-tolerance, especially 1.3 ContractViolationError, 1.4 repository pattern), 3 (error handling categories), 4 (import hierarchy), 9 (job/task patterns)

**Recommended split**: A (Design vs Runtime) — Architecture/contracts vs correctness/reliability

**Cadence**: After major CoreMachine changes, or bi-monthly.

---

## Run 46: DAG Data Layer D.1-D.4 (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 16 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | DAG workflow definition, models, loader/registry, initializer, parameter resolver |
| **Files** | 12 |
| **Scope Split** | C (Data vs Control Flow) |
| **Findings** | 19 total (Alpha: 9, Beta: 6+3 risks+4 edge cases, Gamma: 5 blind spots) |
| **Gamma Corrections** | Alpha-MEDIUM-2 = FALSE POSITIVE, Alpha-LOW-1 = INVALID |
| **Constitution Violations** | 2 (Section 3.1: exception hierarchy, Section 1.1: silent skip) |
| **Fixes Applied** | 5/5 — all applied during v0.10.5.x development (verified 23 MAR 2026) |
| **Output** | `agent_docs/compete_run46_dag_data_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | HIGH | Replace `default=str` with explicit canonical serializer in `_generate_run_id` | `core/dag_initializer.py:44-56` | **FIXED** — `_canonical_json_default()` raises on unknown types |
| 2 | HIGH | Wire `WorkflowNotFoundError`/`WorkflowValidationError` into `BusinessLogicError` hierarchy | `core/workflow_registry.py:22`, `core/workflow_loader.py:27` | **FIXED** — both inherit via ResourceNotFoundError/ValidationError |
| 3 | MEDIUM | Raise `ContractViolationError` for unknown IDs in `_build_adjacency_from_tasks` | `core/dag_fan_engine.py:212-216` | **FIXED** — two explicit guards in `build_adjacency()` |
| 4 | MEDIUM | Add cross-field validation to `RetryPolicy` (initial_delay <= max_delay) | `core/models/workflow_definition.py:24-29` | **FIXED** — `@model_validator` enforces bounds |
| 5 | MEDIUM | Return fresh task state from `claim_ready_workflow_task` (stale timestamps) | `infrastructure/workflow_run_repository.py:891-892` | **FIXED** — returns WorkflowTask with RUNNING state |

**Accepted Risks (revised 23 MAR 2026)**: 3 of 6 remain open. RESOLVED: non-atomic param+promote (merged to `set_params_and_promote`), no RUNNING timeout (janitor 120s sweep), void fail_task (guarded by orchestrator flow). STILL OPEN: deterministic run_id resubmit (idempotent reject, no user notification), echo_test.yaml when-clause edge case, uuid4 fan-out children (non-deterministic by design).

---

## Run 47: DAG Control Layer D.5-D.6 (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 16 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | DAG graph utilities, transition engine, fan engine, orchestrator, repository, worker dual-poll |
| **Files** | 6 |
| **Scope Split** | A (Design vs Runtime) |
| **Findings** | 19 total (Alpha: 10, Beta: 8+3 risks+3 edge cases, Gamma: 6 blind spots) |
| **Gamma New Finds** | 2 CRITICAL (fan-out template race, TaskSummary handler field) |
| **Constitution Violations** | 2 (Section 1.1: silent skip in _build_adjacency, Section 4.1: core->infrastructure import) |
| **Fixes Applied** | 5/5 — all applied during v0.10.5.x development (verified 23 MAR 2026) |
| **Output** | `agent_docs/compete_run47_dag_control_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File | Status |
|---|----------|-------------|------|--------|
| 1 | CRITICAL | Add `handler` field to TaskSummary + SELECT — `evaluate_conditionals` crashes with AttributeError | `core/dag_graph_utils.py:52-66`, `infrastructure/workflow_run_repository.py:246-271` | **FIXED** — handler field in TaskSummary + SELECT |
| 2 | CRITICAL | Exclude fan-out templates from worker claim — workers can claim templates before orchestrator expands, causing permanent DAG stall | `infrastructure/workflow_run_repository.py:855-862`, `core/dag_initializer.py:83` | **FIXED** — `__fan_out__`/`__conditional__`/`__fan_in__` sentinels excluded from claim SQL |
| 3 | HIGH | Fix `predecessor_outputs` dict collision — fan-out children share task_name, last child wins | `core/dag_orchestrator.py:369-376` | **FIXED** — filters out fan-out children with `fan_out_source is None` |
| 4 | MEDIUM | Add `_ensure_fresh_tokens()` to `_process_workflow_task` | `docker_service.py:581` | **FIXED** — called at start of `_process_workflow_task` |
| 5 | MEDIUM | Merge `set_task_parameters` + `promote_task` into single atomic UPDATE | `core/dag_transition_engine.py:387-394` | **FIXED** — `set_params_and_promote()` with CAS guard |

**Accepted Risks (revised 23 MAR 2026)**: 4 of 8 remain open. RESOLVED: _build_adjacency silent skip (raises ContractViolationError), no heartbeat (last_pulse + janitor), no retry mechanism (janitor exponential backoff), time.sleep (only in test handler). STILL OPEN: expand_fan_out no CAS (UniqueViolation fallback), aggregate_fan_in no CAS, stale snapshot (inherent to optimistic locking), per-call repo instantiation (connection pool pressure under load).

---

## Cumulative Token Usage

---

## Run 48: Vector Handler Decomposition (DECOMPOSE — First Production Run)

| Field | Value |
|-------|-------|
| **Date** | 19 MAR 2026 |
| **Pipeline** | DECOMPOSE (Faithful Monolith Extraction) — FIRST RUN |
| **Mode** | Guided (boundaries from V10_MIGRATION.md) |
| **Monolith** | `services/handler_vector_docker_complete.py` (1,448 lines) |
| **Target** | 3 handlers: `vector_load_source`, `vector_validate_and_clean`, `vector_create_and_load_tables` |
| **Version** | v0.10.4.1 |
| **Output** | 3 handler files (2,948 lines total) + build spec |
| **Total Tokens** | 567,878 |
| **Wall Clock** | ~25 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| R | Opus | 34,893 | 2m 39s | Reverse-engineered monolith blind (11 phases, 5 [BUG] tags) |
| X | Opus | 46,584 | 4m 01s | Designed 3 handlers from specs blind |
| D | Opus | 48,358 | 5m 47s | Diff audit: 8 matched, 20 orphaned, 9 new, 5 boundary mismatches |
| P | Opus | 53,177 | 4m 38s | Atomic purist design |
| F | Opus | 130,128 | 6m 01s | Fidelity defense + 3 R corrections (CRS, column mapping, NaT gap) |
| M | Opus | 82,893 | 9m 00s | Resolved 12 conflicts, escalated 3 |
| B1 | Sonnet | 42,316 | 1m 58s | Built vector_load_source |
| B2 | Sonnet | 56,255 | 3m 23s | Built vector_validate_and_clean |
| B3 | Sonnet | 73,274 | 4m 31s | Built vector_create_and_load_tables |

**Key Pipeline Wins**:
- F caught R's CRS error: monolith silently assigns 4326, not rejects. Would have been a regression.
- F found NaT conversion gap: `insert_chunk_idempotent` has no NaT guard. Defense-in-depth mandated.
- F clarified column mapping != sanitization: two distinct operations, both preserved.
- D found 20 orphaned behaviors: 7 assigned to existing handlers (4/5/6), 4 added to handler 3.

**GATE1 Decisions**: 20 orphans triaged. 3 CRITICAL assigned. 7 covered by existing handlers. 6 deferred to infrastructure. 3 intentionally removed. 1 dropped.

**GATE2 Decisions**: 3 escalations resolved. OGC styles → node 5. Feature count → node 5 (already handles). Validation events → skip (DAG task timestamps suffice).

**Calibration Data** (vs pipeline estimates):

| Agent | Estimated | Actual | Delta |
|-------|-----------|--------|-------|
| R | 80-120K | 35K | 71% under |
| X | 40-60K | 47K | On target |
| D | 60-100K | 48K | 35% under |
| P | 40-60K | 53K | On target |
| F | 50-80K | 130K | 63% over (reads monolith + 2 support files) |
| M | 80-120K | 83K | On target |
| B (each) | 30-50K | 42-73K | On target to 46% over |

**Scope guidance update**: F is the most expensive agent — reading monolith + support files drives token count. For future runs, F's estimate should be 100-150K for 1,500-line monoliths.

---

## Run 49: Vector Atomic Handlers Review (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 20 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | 3 DECOMPOSE-extracted vector handlers (handler_load_source, handler_validate_and_clean, handler_create_and_load_tables) |
| **Version** | v0.10.4.1 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 3 handler files + 2 support modules |
| **Findings** | 22 total: 0 CRITICAL, 3 HIGH, 12 MEDIUM, 7 LOW |
| **Fixes Applied** | 5 (Top 5 from Delta) |
| **Accepted Risks** | 3 resolved (NaT round-trip, mount cleanup via janitor Phase 3, datetime→TIMESTAMPTZ). 2 still open: multi-group partial failure, private API chaining |
| **Total Tokens** | 325,779 |
| **Wall Clock** | ~15 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| Alpha | Opus | 93,527 | 3m 23s | Data integrity review (2 HIGH, 4 MEDIUM, 1 LOW) |
| Beta | Opus | 93,148 | 4m 27s | Orchestration review (2 HIGH, 2 MEDIUM, 3 RISK, 4 EDGE) |
| Gamma | Opus | 81,953 | 4m 09s | Contradictions + 5 blind spots (SQL regex, mount cleanup, NaT→TEXT) |
| Delta | Opus | 57,151 | 2m 49s | Final report: Top 5 fixes, 5 accepted risks, 5 architecture wins |

**Top 5 Fixes Applied**:
1. Handler 2 outer try/except (contract violation)
2. `conn.rollback()` after cleanup failure (connection poisoning)
3. SQL injection regex false positive on hyphens
4. `chunk_size <= 0` validation
5. Antimeridian exception logging (silent swallows)

**DAG Infrastructure Bugs Found During Testing** (post-COMPETE, during deployment):
1. Root node parameters never resolved by initializer → fixed in `dag_initializer.py`
2. Docker worker missing `_run_id`/`_node_name` injection → fixed in `docker_service.py`
3. Hardcoded `/mnt/etl` instead of `config.docker.etl_mount_path` → fixed in handlers 1+2

**E2E Test Results** (via `POST /api/dag/test/node/{handler_name}`):

| Handler | Status | Result |
|---------|--------|--------|
| `vector_load_source` | COMPLETED | 483 rows from roads.geojson, GeoParquet on mount |
| `vector_validate_and_clean` | COMPLETED | 1 group (line), 483 rows, CRS=4326 |
| `vector_create_and_load_tables` | COMPLETED | `geo.test_roads_dag`, 483 rows, spatial index |

---

## Cumulative Statistics

---

## Run 50: Raster Handler Decomposition (DECOMPOSE — Run 2)

| Field | Value |
|-------|-------|
| **Date** | 21 MAR 2026 |
| **Pipeline** | DECOMPOSE (Faithful Monolith Extraction) — Run 2 |
| **Mode** | Guided (boundaries from V10_MIGRATION.md, single COG path only) |
| **Monolith** | `services/handler_process_raster_complete.py` (2,369 lines, single COG path) |
| **Target** | 5 handlers: download_source, validate, create_cog, upload_cog, persist_app_tables |
| **Version** | v0.10.5.0 |
| **Output** | 5 handler files (3,086 lines total) + build spec (957 lines) |
| **Total Tokens** | 672,869 |
| **Wall Clock** | ~28 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| R | Opus | 43,522 | 3m 26s | Reverse-engineered single COG path (8 phases, 7 anomalies) |
| X | Opus | 64,275 | 4m 53s | Designed 5 handlers from V10 spec |
| D | Opus | 46,991 | 5m 30s | Diff audit: 5 matched, 14 orphaned, 10 new, 4 boundary mismatches, 10 data flow gaps |
| P | Opus | 61,040 | 3m 29s | Atomic purist design |
| F | Opus | 102,531 | 5m 39s | Fidelity defense + 6 R corrections (render_config NOT dead write, column mapping, NaT gap, etc.) |
| M | Opus | 84,366 | 9m 47s | Resolved 9 conflicts, escalated 3 |
| B1 | Sonnet | 39,059 | 1m 42s | Built raster_download_source |
| B2 | Sonnet | 49,215 | 2m 27s | Built raster_validate |
| B3 | Sonnet | 75,912 | 3m 16s | Built raster_create_cog |
| B4 | Sonnet | 43,017 | 2m 18s | Built raster_upload_cog |
| B5 | Sonnet | 62,941 | 3m 04s | Built raster_persist_app_tables |

**Key Design Decision**: `raster_create_cog` extracts raster_bands/rescale_range/transform/resolution from the COG file directly (windowed reads), eliminating blob re-read in persist handler.

**GATE1**: 14 orphans triaged — 1 absorbed (ProvenanceProperties), 4 eliminated by DAG design, 9 deferred.
**GATE2**: 3 escalations resolved — skip_cleanup/skip_upload for raster_cog.py, output_blob_name required, tier suffix preserved.

---

## Run 51: Raster Atomic Handlers Review (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 21 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | 5 DECOMPOSE-extracted raster handlers |
| **Version** | v0.10.5.0 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 5 handler files + raster_cog.py (context) |
| **Findings** | 16 total: 1 CRITICAL, 4 HIGH, 6 MEDIUM, 5 LOW |
| **Fixes Applied** | 5 (Top 5 from Delta) |
| **Accepted Risks** | 5 resolved (file_checksum removed, rescale unified via `build_renders()`, degenerate guard added, node_name validated, basename prefixed with run_id[:8]). 1 still open: context param unused (future-proofing) |
| **Total Tokens** | 354,745 |
| **Wall Clock** | ~10 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration |
|-------|-------|--------|----------|
| Alpha | Opus | 111,252 | 2m 48s |
| Beta | Opus | 111,189 | 3m 39s |
| Gamma | Opus | 84,134 | 4m 00s |
| Delta | Opus | 48,170 | 2m 21s |

**Top 5 Fixes Applied**:
1. raster_cog.py: skip_cleanup + skip_upload params (CRITICAL — entire chain was non-functional)
2. handler_create_cog: output_blob_name + target_crs required params
3. handler_persist_app_tables: outer try/except for contract compliance
4. handler_create_cog: windowed block reads replace full-band ds.read() (OOM prevention)
5. handler_create_cog: bounds_4326 CRS guard via transform_bounds

---

## Run 52: Zarr + STAC Producer vs Consumer (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 23 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Zarr handlers + STAC composable handlers (producer vs consumer split) |
| **Version** | v0.10.5.7 |
| **Split** | Custom: Producers (metadata writers) vs Consumers (pgSTAC writers) |
| **Files** | 8 (zarr handlers, STAC handlers, repositories, BlobRepository) |
| **Findings** | 14 total: 2 CRITICAL, 4 HIGH, 4 MEDIUM, 4 LOW |
| **Total Tokens** | 190,680 |
| **Wall Clock** | ~5 minutes |
| **Report** | `agent_docs/compete_run52_zarr_stac_producers_consumers.md` |

**Token Usage**:

| Agent | Model | Tokens | Duration |
|-------|-------|--------|----------|
| Alpha (Producers) | Opus | 74,577 | 2m 02s |
| Beta (Consumers) | Opus | 67,869 | 2m 17s |
| Gamma+Delta (combined) | Opus | 48,234 | 2m 38s |

**Top 5 Fixes**:
1. NameError crash — `cog_metadata` undefined on zarr materialization path (CRITICAL)
2. SQL injection — f-string SQL in zarr_metadata_repository.upsert() (CRITICAL)
3. Silent exception swallowing — `except Exception: pass` in 4 locations (HIGH, systemic)
4. Global bbox fallback `[-180,-90,180,90]` masks missing spatial data (HIGH)
5. No STAC item contract validation before pgSTAC write (HIGH)

**Split effectiveness**: Producer vs Consumer split was highly productive. The contract boundary between metadata tables and pgSTAC was the primary friction point.

---

## Cumulative Statistics

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19, 28-30, 33, 39, 42, 44, 46, 47, 49, 51, 52 | ~4.5M+ |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944K |
| SIEGE | Runs 11, 13, 18, 20-23, 25-26, 34-35, 37-38, 40-41, 43, 45 | ~2.5M+ |
| REFLEXION | Runs 14-17, 32 | ~975K |
| TOURNAMENT | Run 27 | ~278K |
| ADVOCATE | Runs 31, 36 | ~335K |
| DECOMPOSE | Runs 48, 50 | ~1.24M |
| **Total** | 52 runs | **~10.8M+** |

---

## Open Issues Summary (verified 23 MAR 2026)

### Pending Fixes: ALL RESOLVED

All 10 pending fixes from Runs 46 + 47 were applied during v0.10.5.x development:

| Run | Fix | Severity | Status |
|-----|-----|----------|--------|
| 46 | Canonical JSON serializer | HIGH | Fixed in `_canonical_json_default()` |
| 46 | Error class hierarchy | HIGH | Fixed — both inherit from BusinessLogicError |
| 46 | ContractViolationError for unknown IDs | MEDIUM | Fixed in `build_adjacency()` |
| 46 | RetryPolicy cross-field validation | MEDIUM | Fixed — `@model_validator` |
| 46 | Fresh task state from claim | MEDIUM | Fixed — returns WorkflowTask |
| 47 | TaskSummary handler field | CRITICAL | Fixed — handler in SELECT + TaskSummary |
| 47 | Exclude fan-out templates from claim | CRITICAL | Fixed — sentinel handler exclusion |
| 47 | predecessor_outputs collision | HIGH | Fixed — `fan_out_source is None` filter |
| 47 | `_ensure_fresh_tokens()` | MEDIUM | Fixed — called at start of workflow task processing |
| 47 | Atomic set_params_and_promote | MEDIUM | Fixed — single CAS-guarded UPDATE |

### Accepted Risks Still Open (11 of 30)

**Architectural / By Design (6)** — these are conscious trade-offs, not bugs:

| Run | Risk | Rationale |
|-----|------|-----------|
| 44 | Health check auth exception | K8s probes + monitoring need unauthenticated access |
| 46 | Deterministic run_id resubmit | Idempotent reject on PK collision; no user notification on duplicate |
| 46 | uuid4 fan-out children | Non-deterministic IDs required — deterministic would need canonical expansion order |
| 47 | Stale snapshot | Inherent to optimistic locking; pessimistic locking too expensive |
| 47 | Per-call repo instantiation | Avoids shared state; connection pool pressure acceptable at current scale |
| 51 | Context param unused | Future-proofing for worker-provided context injection |

**Deferred / Low Priority (5)** — real gaps, low blast radius:

| Run | Risk | Impact |
|-----|------|--------|
| 46 | echo_test.yaml when-clause edge case | Test workflow only, not production |
| 47 | expand_fan_out no CAS | Second concurrent expand gets UniqueViolation (non-fatal) |
| 47 | aggregate_fan_in no CAS | Concurrent aggregation could double-complete (unlikely, non-fatal) |
| 49 | Multi-group partial failure | Partial result returned without explicit failure status |
| 49 | Private API chaining | Tightly coupled handlers call internal methods |

**Technical Debt (0)** — all resolved 23 MAR 2026:

~~Mount cleanup deferred~~ → Janitor Phase 3 added to `dag_janitor.py` (30-day threshold, `JANITOR_MOUNT_MAX_AGE_DAYS` env override)
~~datetime→TEXT mapping~~ → `postgis_handler._get_postgres_type()` now returns `TIMESTAMP WITH TIME ZONE` (requires schema rebuild for existing tables)

### Accepted Risks Resolved Since Original Runs (19 of 30)

| Run | Risk | How Resolved |
|-----|------|-------------|
| 44 | No janitor | `dag_janitor.py` — background sweep with exponential backoff |
| 44 | Double PROCESSING write | Moot — Service Bus deprecated, DB-polling only |
| 46 | Non-atomic param+promote | Merged to `set_params_and_promote` with CAS |
| 46 | No RUNNING timeout | Janitor enforces 120s stale threshold |
| 46 | Void fail_task | Guarded by orchestrator flow; only called on RUNNING tasks |
| 47 | _build_adjacency silent skip | Raises `ContractViolationError` for unknown IDs |
| 47 | time.sleep not interruptible | Only used in test handler (`hello_world.py`) |
| 47 | No heartbeat | `last_pulse` field + janitor sweep |
| 47 | No retry mechanism | Janitor exponential backoff with max_retries |
| 49 | NaT round-trip | Fixed via `.astype(object)` before `to_parquet()` |
| 51 | file_checksum not computed | Removed — no consumer for SHA-256 |
| 51 | Rescale divergence | Unified via canonical `build_renders()` from `stac_renders.py` |
| 51 | Degenerate rescale | Guard for `[0.0, 0.0]` returns None |
| 51 | node_name inconsistency | Both `_run_id` + `_node_name` validated as required |
| 51 | Basename collision | `run_id[:8]` prefix on downloaded filenames |
| 52 | NameError on zarr path | `cog_metadata = None` before try block |
| 52 | SQL injection in zarr repo | Parameterized SQL with column whitelist |
| 49 | Mount cleanup deferred | Janitor Phase 3: `_sweep_mount_dirs()` removes dirs older than 30 days |
| 49 | datetime→TEXT mapping | `postgis_handler._get_postgres_type()` → `TIMESTAMP WITH TIME ZONE` |

---

## Run 53: DAG Brain Primary Loop + Orchestration (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 24 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DAG Brain primary loop (new), orchestrator dispatch engines, worker claim path, repository |
| **Version** | v0.10.5.8 |
| **Context** | Removed all per-submission orchestrator thread spawning. Built DAGBrainPrimaryLoop as single source of orchestration. Function App only writes to DB. |
| **Split** | 3-way: Primary Loop / Dispatch Engines / Worker+Repo |
| **Files** | 7 (docker_service.py, dag_orchestrator.py, dag_transition_engine.py, dag_fan_engine.py, dag_graph_utils.py, dag_janitor.py, workflow_run_repository.py) |
| **Findings** | 22 total: 3 CRITICAL, 5 HIGH, 6 MEDIUM, 3 LOW, 5 confirmed OK |
| **Fixes Applied** | 3 (C1, C2, C3 — in progress) |

### CRITICAL

| ID | Finding | File | Impact |
|----|---------|------|--------|
| C1 | No heartbeat for DAG workflow tasks during execution — `last_pulse` set once at claim, never updated. Janitor reclaims anything running >120s | `docker_service.py:_process_workflow_task` | Tasks killed mid-execution, duplicate processing |
| C2 | SKIPPED mandatory dep blocks downstream forever — conditional branch not taken → target SKIPPED → join node with mandatory dep deadlocks | `dag_graph_utils.py:all_predecessors_terminal` | Deadlocked runs on any reconvergent conditional |
| C3 | One run's error skips remaining runs in same scan — try/except wraps entire for-loop not each iteration | `docker_service.py:DAGBrainPrimaryLoop._loop` | One bad run starves all others for 5s |

### HIGH

| ID | Finding | File | Impact |
|----|---------|------|--------|
| H1 | Lock connection churn — each scan opens+closes dedicated TCP connection per active run for advisory lock | `dag_orchestrator.py:_open_lock_connection` | Connection exhaustion under load |
| H2 | Legacy tasks starve DAG tasks — dual-poll always tries legacy first | `docker_service.py:_run_loop` | DAG workflows blocked during transition |
| H3 | `contains`/`not_contains` crash on non-iterable — `in` on int/bool/None raises TypeError | `dag_fan_engine.py:192-195` | Unhandled crash fails entire run |
| H4 | max_cycles=1 adds 5s latency per sequential node — 10-node workflow = 50s pure wait | `docker_service.py:DAGBrainPrimaryLoop` | Slow workflows |
| H5 | Fan-out children corrupt `task_by_name` graph structures — children share template name | `dag_graph_utils.py:build_adjacency` | Latent corruption if non-fan-in depends on fan-out |

### MEDIUM

| ID | Finding | File | Impact |
|----|---------|------|--------|
| M1 | Stale snapshot across engine dispatch — each engine sees pre-mutation state | `dag_orchestrator.py:495-509` | +5s latency per state transition |
| M2 | Fan-in can aggregate from PENDING (skipping READY state) | `dag_fan_engine.py:650-654` | State machine violation |
| M3 | No thread join on shutdown — pool torn down while loop mid-query | `docker_service.py` lifespan | Crash on shutdown |
| M4 | New WorkflowRunRepository per poll cycle instead of cached | `docker_service.py:_claim_next_workflow_task` | Wasted allocations |
| M5 | Shared repo instance across threads — auth token thread safety unverified | `docker_service.py` lifespan | Theoretical race on token refresh |
| M6 | No size limit on result_data JSONB — fan-in of 1000 tiles could be huge | `workflow_run_repository.py` | Memory/network pressure |

### LOW

| ID | Finding | File |
|----|---------|------|
| L1 | Counter fields read/written across threads (safe under CPython GIL) | `docker_service.py:DAGBrainPrimaryLoop` |
| L2 | `in`/`not_in` operators crash on non-iterable operand (same pattern as H3) | `dag_fan_engine.py:188-191` |
| L3 | Worker ID not unique across container restarts (hostname:PID reuse) | `docker_service.py:655` |

### Confirmed OK

| ID | Checked | Verdict |
|----|---------|---------|
| OK1 | `is_run_terminal` + fan-out children | Correct — re-fetches tasks before terminal check |
| OK2 | Idempotency of engine dispatch | Correct — CAS guards in repository prevent double-promotion |
| OK3 | Claim atomicity (SELECT...FOR UPDATE SKIP LOCKED) | Correct — single transaction, no window for partial claims |
| OK4 | `update_run_status` transition guards | Correct — SQL WHERE prevents invalid transitions |
| OK5 | `list_active_runs` index support | Correct — partial index on status IN ('pending','running') |

### Fixes Applied (24 MAR 2026)

All CRITICAL and HIGH findings fixed. M2, M3, M4 also fixed. M1/M5/M6 accepted, L1-L3 accepted (L2 covered by H3 fix).

| ID | Severity | Fix | Commit |
|----|----------|-----|--------|
| C1 | CRITICAL | Heartbeat pulse thread in `_process_workflow_task` + `update_workflow_task_pulse` repo method | (session) |
| C2 | CRITICAL | SKIPPED treated as terminal in `all_predecessors_terminal` for all deps | (session) |
| C3 | CRITICAL | Per-run try/except in `DAGBrainPrimaryLoop._loop` | (session) |
| H3 | HIGH | TypeError guard on in/not_in/contains/not_contains operators | `2df00a21` |
| H5 | HIGH | Filter fan-out children from task_by_name + adjacency maps | `daff9cfa` |
| H2 | HIGH | Alternating legacy/DAG poll priority | `8e908022` |
| H4 | HIGH | Fast rescan when orchestrator makes progress (skip sleep) | `e1b1fe78` |
| H1 | HIGH | Transaction-level advisory locks via pooled connection | `960a2d8a` |
| M2 | MEDIUM | Fan-in only aggregates from READY + CAS guard on repo method | (session) |
| M3 | MEDIUM | Thread join on shutdown for primary loop, janitor, scheduler | (session) |
| M4 | MEDIUM | Cached WorkflowRunRepository in worker | (session) |

### Accepted Risks

| ID | Severity | Why Accepted |
|----|----------|-------------|
| M1 | MEDIUM | Stale snapshot: correctness OK, H4 fast rescan mitigates latency |
| M5 | MEDIUM | Token access is atomic reference swap under CPython GIL |
| M6 | MEDIUM | No size limit on result_data: not urgent, add warning log later |
| L1 | LOW | Counter fields: safe under GIL |
| L2 | LOW | Already fixed by H3 (same try/except block) |
| L3 | LOW | Worker ID collision: narrow edge case, correct behavior anyway |
