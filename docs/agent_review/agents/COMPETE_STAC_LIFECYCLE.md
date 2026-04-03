# COMPETE: Unified STAC Lifecycle

**Purpose**: Adversarial review of the two-phase STAC materialization (structural state 2 + B2C state 3), approval gate integration across all four workflow types, optional vector STAC, and reject/revoke STAC cleanup. Verify the state machine is correct, the B2C boundary is enforced, and no internal data leaks to consumers.

**Best for**: Run after implementing the unified STAC lifecycle (v0.10.10). Targets the full materialization chain from item build through pgSTAC write, approval/reject/revoke flows, and unpublish cleanup.

**Motivation**: STAC materialization was restructured from a single method into two phases (structural pre-approval, B2C post-approval). Four workflows were rewired with new node ordering. A `constants` field was added to the DAG engine's TaskNode model. Vector gained optional STAC. This review verifies no state 2 (internal) data leaks to state 3 (consumer-facing), the approval gate correctly separates the phases, and the new `constants` mechanism works correctly.

---

## Scope Split: Split F — State Boundary vs Artifact Integrity (custom)

**Why this split**: The two-phase lifecycle creates a trust boundary between state 2 (internal, raw, `geoetl:*` preserved) and state 3 (consumer-facing, sanitized, TiTiler URLs injected). Alpha inspects whether the **boundary is enforced correctly** — can internal data ever reach consumers? Beta inspects whether the **artifacts are correct** — does each phase produce the right pgSTAC content, do the workflows wire params correctly, does the `constants` mechanism work?

### Alpha — State Boundary Enforcement (B2C Safety)

Review every path where STAC items move between states. The question is: **can internal data (geoetl:*, raw abfs:// URLs, ddh:status='processing') ever reach a consumer-facing endpoint?**

Checklist:
- Does `materialize_structural()` correctly stamp `ddh:status='processing'`?
- Does `materialize_structural()` correctly SKIP sanitization (geoetl:* must be preserved)?
- Does `materialize_structural()` correctly SKIP URL injection (no TiTiler URLs at state 2)?
- Does `materialize_approved()` correctly stamp `ddh:status='approved'`?
- Does `materialize_approved()` correctly APPLY sanitization (geoetl:* stripped)?
- Does `materialize_approved()` correctly INJECT TiTiler URLs?
- Can a state 2 item be served by TiTiler without approval? (Check if pgSTAC searches filter by ddh:status)
- Does the platform/status services block correctly gate on approval_state='approved'?
- Is the `materialize_to_pgstac` alias safe? Does any caller bypass the mode routing?
- On rejection: is the state 2 item actually deleted from pgSTAC?
- On revoke: is the state 3 item actually deleted from pgSTAC?
- For vector with `create_stac=false`: is there ANY pgSTAC presence? (Must be zero)
- For vector with `create_stac=true`: does the STAC item contain TiPG URLs only after approval?
- Does the `stac_item_builder` include any internal infrastructure in the item (storage account names, connection strings)?

**Alpha does NOT review**: YAML node ordering, fan-out mechanics, param resolution, handler registration, workflow structural validation.

### Beta — Artifact Integrity and Workflow Mechanics

Review whether each phase produces the correct pgSTAC artifacts and the workflow wiring is correct. The question is: **does the system produce the right output at each stage, and do the new YAML nodes connect correctly?**

Checklist:
- Does the `constants` field on TaskNode actually pass values to handlers? Trace through param_resolver.
- In each of the 4 workflows: do the structural nodes depend on the right predecessors?
- In each of the 4 workflows: does the approval gate depend on `materialize_collection_structural` (not on persist)?
- In each of the 4 workflows: do the approved nodes depend on the approval gate?
- For tiled rasters: does the structural fan-out correctly materialize ALL tiles (not just one)?
- For raster collections: same question — does the structural fan-out iterate cog_ids?
- For zarr: the approval gate is NEW — does the workflow still work end-to-end? Are all node dependencies correct?
- For vector: do the `when: "params.create_stac"` conditionals work? What happens to downstream deps when skipped?
- Does the `mode` parameter reach the handler correctly from both `constants` (task nodes) and `params` dict (fan-out nodes)?
- Does `materialize_collection` (extent + search registration) run correctly in both phases?
- Is there a race condition where state 3 upsert could clobber state 2 before approval completes?
- Does the bulk `cog_ids` path in `stac_materialize_item` correctly route to structural vs approved?
- Does `vector_build_stac_item` correctly read from `tables_info` and cache on Release?

**Beta does NOT review**: B2C sanitization content, property stripping rules, URL injection correctness, data leakage to consumers.

### Gamma — Gaps Between Boundary and Artifact

After reading Alpha and Beta reports, find:
- **Epoch 4 materialization path**: Does the old `materialize_item(release, reviewer, clearance_state)` method still work? Does it stamp `ddh:status`? Could Epoch 4 bypass the two-phase model?
- **Mixed-mode items**: What happens if `materialize_structural` runs but `materialize_approved` never runs (workflow fails at gate)? Is the state 2 item cleaned up by finalize?
- **Double-materialization**: Both structural and approved call `pgstac.insert_item()` (upsert). Does the second call correctly overwrite ALL properties, or do state 2 properties leak into state 3?
- **Collection extent**: `materialize_collection` runs in both phases. Does the second run correctly recompute extent from state 3 items?
- **pgSTAC search registration**: Does it happen at state 2 (structural collection) or state 3 (approved collection)? Should it be different?
- **Unpublish after structural-only**: If a dataset is at state 2 (never approved) and gets unpublished, does the inventory find the item?

---

## Target Files

### Primary (Alpha + Beta review all)

| # | File | Lines | Role |
|---|------|-------|------|
| 1 | `services/stac_materialization.py` | 1113 | Core: materialize_structural + materialize_approved + sanitization |
| 2 | `services/stac/handler_materialize_item.py` | 207 | Handler: mode routing, bulk cog_ids, zarr_prefix wiring |
| 3 | `services/stac/handler_materialize_collection.py` | 114 | Handler: extent + pgSTAC search registration |
| 4 | `services/vector/handler_build_stac_item.py` | 172 | NEW: vector STAC item from table_catalog |
| 5 | `core/param_resolver.py` | 343 | constants field resolution |
| 6 | `core/models/workflow_definition.py` | 216 | TaskNode constants field |
| 7 | `workflows/process_raster.yaml` | 231 | Raster: structural + gate + approved |
| 8 | `workflows/process_raster_collection.yaml` | 223 | Collection: structural fan-out + gate + approved fan-out |
| 9 | `workflows/ingest_zarr.yaml` | 136 | Zarr: NEW approval gate |
| 10 | `workflows/vector_docker_etl.yaml` | 159 | Vector: optional STAC nodes |

### Secondary (Gamma + Delta review)

| # | File | Lines | Role |
|---|------|-------|------|
| 11 | `services/stac/stac_item_builder.py` | 196 | Pure function: STAC item dict construction |
| 12 | `services/stac/stac_collection_builder.py` | 58 | Pure function: STAC collection dict construction |
| 13 | `services/asset_approval_service.py` | 1098 | Approve/reject/revoke flows + STAC cleanup |
| 14 | `services/pgstac_search_registration.py` | 301 | pgSTAC search writes for mosaic |
| 15 | `infrastructure/pgstac_repository.py` | 871 | pgSTAC CRUD |
| 16 | `services/unpublish_handlers.py` | 1463 | Inventory + cleanup (D6 fallbacks) |

**Total**: ~6,900 lines across 16 files.

---

## Severity Classification

| Severity | Definition for this target |
|----------|---------------------------|
| **CRITICAL** | Internal data (geoetl:*, abfs:// URLs, ddh:status='processing') reaches consumer-facing pgSTAC items. State 2 properties survive into state 3. Sanitization bypassed. |
| **HIGH** | Workflow node wired incorrectly (wrong dependency, missing mode param). Approval gate in wrong position. constants field not passed to handler. State 2 items not cleaned on reject. |
| **MEDIUM** | Double-materialization leaves stale properties. Collection extent computed from wrong state. pgSTAC search registered at wrong phase. Vector STAC conditional doesn't skip cleanly. |
| **LOW** | Logging inconsistency. ddh:status not stamped in edge case. Stale comments. |

---

## Output Format (Delta)

Delta produces a single report with:

1. **Executive Summary** — Is the B2C boundary enforced? Is the state machine correct?
2. **Top 5 Fixes** — Table: Severity, ID, WHY, WHERE, HOW, EFFORT, RISK
3. **Full Finding List** — All findings
4. **State Boundary Audit** — For each data type: what properties exist at state 2 vs state 3? Any leakage?
5. **Workflow Wiring Verification** — For each of 4 workflows: correct node ordering confirmed or gaps found
6. **Accepted Risks** — Known limitations
