# COMPETE Run 53: Workflow YAML Definitions + Loader/Registry/Initializer

**Date**: 26 MAR 2026
**Version**: v0.10.6.3
**Pipeline**: COMPETE (Adversarial Code Review)
**Split**: C (Data vs Control Flow)
**Files**: 15 (11 YAML workflows + 4 Python control flow modules)

---

## Omega: Split Rationale

**Split C (Data vs Control Flow)** chosen because this scope spans pure data contracts (11 YAML workflow definitions) and their control flow consumers (loader validation, registry lookup, DAG initialization, parameter resolution). The productive tension: Alpha focuses on whether the YAMLs define correct, consistent data contracts; Beta focuses on whether the Python modules correctly process those contracts at runtime. Where they disagree (e.g., Alpha says a path is wrong, Beta says the resolver handles it) generates the highest-value findings.

**Alpha (Data Integrity)** assigned:
- All 11 workflow YAML files
- `core/models/workflow_definition.py`
- Constitution: Standards 4, 5, 8, 9 (import hierarchy, platform decoupling, naming, job patterns)

**Beta (Orchestration / Control Flow)** assigned:
- `core/workflow_loader.py`
- `core/workflow_registry.py`
- `core/dag_initializer.py`
- `core/param_resolver.py`
- `core/models/workflow_definition.py` (shared, examined from control flow lens)
- Constitution: Standards 1, 2, 3, 6, 7 (zero-tolerance, config, error handling, DB patterns, schema evolution)

---

## Alpha Review: Data Integrity and Lifecycle

### STRENGTHS

1. **Discriminated union via Pydantic** (`core/models/workflow_definition.py:125-129`): The `NodeDefinition` union discriminated on `type` field guarantees type safety at parse time. Each node type uses `extra='forbid'` preventing silent schema drift.

2. **Consistent handler registration**: All 40+ handlers referenced across 11 YAML files are registered in `services/__init__.py` ALL_HANDLERS dict. No orphan handler references found.

3. **Conditional + fan-out + fan-in proven patterns**: `process_raster.yaml` demonstrates all four node types working together in a single workflow (conditional routing, parallel tile processing, fan-in aggregation, STAC materialization). This is a strong architectural template.

4. **Parameter schema declarations**: Every workflow declares parameters with types, required flags, and defaults. `ParameterDef` model (`workflow_definition.py:62-67`) uses a constrained type literal preventing arbitrary types.

5. **Paired lifecycle for vector**: `vector_docker_etl.yaml:4` declares `reversed_by: unpublish_vector` and `unpublish_vector.yaml:4` declares `reverses: [vector_docker_etl]`. Bidirectional linkage.

### CONCERNS

**HIGH-1: `process_raster.yaml` line 138 -- fan-in result path mismatch**

The `persist_tiled` node receives:
```yaml
tile_results: "aggregate_tiles.results"
```
But `AggregationMode.COLLECT` produces `{"items": [...]}` (confirmed in `dag_fan_engine.py:752`). The correct path should be `"aggregate_tiles.items"`, not `"aggregate_tiles.results"`. This will raise `ParameterResolutionError` at runtime when the tiled raster path is taken.

- **File**: `workflows/process_raster.yaml:138`
- **Impact**: Tiled raster processing (>2GB files) will fail at the persist_tiled step. Single COG path is unaffected.

**HIGH-2: `process_raster.yaml` missing `reversed_by` field**

`unpublish_raster.yaml:4` declares `reverses: [process_raster]` but `process_raster.yaml` has no `reversed_by: unpublish_raster` field. The pairing is one-directional. `WorkflowRegistry.get_reverse_workflow("process_raster")` returns `None`.

- **File**: `workflows/process_raster.yaml` (missing line after `version: 2`)
- **Impact**: Constitution Principle 5 (Paired Lifecycles) violation. Programmatic reverse lookup fails.

**MEDIUM-1: Inconsistent handler result structure across workflows**

Some handlers return results at root level (e.g., `handle_generate_list` returns `{"success": True, "items": [...]}`) while others nest under `result` key (e.g., `raster_download_source` returns `{"success": True, "result": {"source_path": "..."}}`). YAML receives paths reflect this: `"generate.items"` vs `"download_source.result.source_path"`.

- **Files**: `workflows/test_fan_out.yaml:19` vs `workflows/process_raster.yaml:37`
- **Impact**: No runtime bug (each workflow matches its handler), but violates Principle 10 (Explicit Data Contracts) -- there is no documented convention for whether handler results use a `result` wrapper.

**MEDIUM-2: Semantic naming mismatch in zarr STAC materialization**

Both `netcdf_to_zarr.yaml:58` and `ingest_zarr.yaml:85` pass `cog_id: "register.result.zarr_id"` to `stac_materialize_item`. The parameter name `cog_id` is semantically incorrect for zarr workflows. The STAC materialization handler accepts `cog_id` as a generic item identifier, but the name implies COG-specific semantics.

- **Files**: `workflows/netcdf_to_zarr.yaml:58`, `workflows/ingest_zarr.yaml:85`
- **Impact**: Developer confusion. The handler should accept an `item_id` parameter, or document that `cog_id` is a legacy name.

**MEDIUM-3: `process_raster_single_cog.yaml` has no reverse workflow or STAC materialization**

This workflow produces a COG, uploads it, and persists app tables but never materializes a STAC item or collection. Compare with `process_raster.yaml` which includes `materialize_single_item` and `materialize_collection`. Also has no `reversed_by` field.

- **File**: `workflows/process_raster_single_cog.yaml`
- **Impact**: Items created by this workflow are invisible to pgSTAC/TiTiler and cannot be programmatically unpublished.

**MEDIUM-4: `get_leaf_nodes()` does not strip `?` suffix from optional deps**

`WorkflowDefinition.get_leaf_nodes()` at line 165 adds raw dependency strings including `"materialize_single_item?"` to the `referenced` set. The `?` suffix means the actual node name `materialize_single_item` won't match, so optional-dep targets are incorrectly classified as leaf nodes.

- **File**: `core/models/workflow_definition.py:160-174`
- **Impact**: Currently not used in runtime code (only in docs/specs), so blast radius is zero. Will cause incorrect results if used for workflow analysis or visualization.

**LOW-1: Five workflows lack `finalize` handler**

`unpublish_raster.yaml`, `unpublish_vector.yaml`, `acled_sync.yaml`, `test_fan_out.yaml`, `echo_test.yaml`, and `hello_world.yaml` have no `finalize` block. This is optional per the Pydantic model (`FinalizeDef` is `Optional`), but inconsistent with the pattern in production workflows.

- **Impact**: No runtime issue. Cleanup/audit hooks won't fire for these workflows.

**LOW-2: All finalize handlers use `vector_finalize`**

Every workflow with a finalize block uses `handler: vector_finalize` regardless of whether it's a raster, zarr, or vector workflow. This either means the handler is generic (good) or misnamed (confusing).

- **Files**: All 5 workflows with finalize blocks
- **Impact**: Naming inconsistency only.

### ASSUMPTIONS

1. **Handler result_data structure**: The absence of a formal `result` wrapper convention means each new handler must be manually verified against its YAML workflow's `receives` paths.

2. **Fan-in aggregation mode**: All fan-in nodes use `collect` mode. The other modes (`concat`, `sum`, `first`, `last`) are untested in any workflow.

3. **Max retries**: No workflow specifies custom retry policies; all rely on the default (3 attempts). This may be insufficient for long-running raster operations.

### RECOMMENDATIONS

1. Add `reversed_by: unpublish_raster` to `process_raster.yaml` and add reverse workflows for zarr pipelines.
2. Fix `aggregate_tiles.results` to `aggregate_tiles.items` in `process_raster.yaml:138`.
3. Establish a documented convention for handler result structure (always use `result` wrapper or never).
4. Rename `cog_id` to `item_id` in `stac_materialize_item` handler or document the generic usage.
5. Fix `get_leaf_nodes()` to strip `?` suffix before adding to referenced set.

---

## Beta Review: Orchestration, Flow Control, and Failure Handling

### VERIFIED SAFE

1. **Cycle detection via Kahn's algorithm** (`workflow_loader.py:101-141`): Correct implementation. All edges are included (depends_on and conditional branch targets). The visited count vs node count comparison catches all cycles.

2. **Deduplication of dependency edges** (`dag_initializer.py:280, 306`): `seen_edges` set prevents duplicate `WorkflowTaskDep` rows when a node has both a `depends_on` and a conditional branch edge to the same target.

3. **Root node parameter resolution** (`dag_initializer.py:249-257`): Root TaskNodes get parameters resolved at initialization time. Non-root tasks defer to the transition engine. This correctly handles the two-phase dispatch model.

4. **Jinja2 NativeEnvironment for fan-out** (`param_resolver.py:29`): Using `NativeEnvironment` preserves Python types (int, bool, list) instead of stringifying them. `StrictUndefined` catches missing variables immediately.

5. **Canonical JSON serializer** (`dag_initializer.py:44-69`): Explicit type handlers for datetime, Decimal, UUID, Enum with `ContractViolationError` on unknown types. This is the correct pattern per Constitution Standard 1.1 (no silent accommodation).

6. **Structural validation completeness** (`workflow_loader.py:69-85`): Nine validation checks cover dependency refs, branch refs, conditional defaults, fan-in-to-fan-out pairing, receives refs, param refs, cycles, reachability, and optional handler verification. Comprehensive coverage.

### FINDINGS

**HIGH-1: Loader `_check_param_refs` only validates list-type params, not dict params with Jinja templates**

`_check_param_refs` at `workflow_loader.py:270-281` only validates when `node.params` is a list. When params is a dict (as in fan-out task templates), no validation occurs. Fan-out nodes use `FanOutTaskDef.params` (always a dict), which is never checked for undeclared parameter references.

- **File**: `core/workflow_loader.py:270-281`
- **Scenario**: A fan-out template referencing `{{ inputs.nonexistent_param }}` passes loader validation but fails at runtime with `ParameterResolutionError`.
- **Impact**: MEDIUM in practice (Jinja2 StrictUndefined catches this at runtime), but the validation gap means errors are discovered late.

**HIGH-2: `_check_receives_refs` does not validate dotted path depth or intermediate keys**

`_check_receives_refs` at `workflow_loader.py:251-264` only checks that the first segment (node name) exists. It does not validate that the referenced result keys (`result.source_path`, `result.raster_type.detected_type`) exist. This means typos in receives paths pass validation.

- **File**: `core/workflow_loader.py:251-264`
- **Scenario**: A typo like `"validate.result.sourc_crs"` (missing 'e') passes all 9 validations but fails at runtime.
- **Impact**: MEDIUM. Runtime `resolve_dotted_path` catches this with a clear error, but late discovery increases debugging cost.

**MEDIUM-1: `resolve_task_params` raises on missing optional params**

`resolve_task_params` at `param_resolver.py:189-196` raises `ParameterResolutionError` if any param in the list is not in `job_params`. But many workflow parameters are declared `required: false` with no default (e.g., `dataset_id`, `resource_id` in `process_raster.yaml`). If the caller omits optional params, the param resolver raises instead of defaulting.

- **File**: `core/param_resolver.py:189-196`
- **Scenario**: A workflow submitted without optional `dataset_id` but with a node that lists `dataset_id` in its `params` list will fail at parameter resolution.
- **Impact**: MEDIUM. The DAG initializer applies defaults from `ParameterDef.default` before calling `resolve_task_params`, so this may be mitigated by the submission layer. Needs verification.

**MEDIUM-2: `WorkflowRegistry.load_all` fails fast on first invalid workflow**

`load_all` at `workflow_registry.py:76-77` calls `WorkflowLoader.load()` inside a loop without try/except. If one workflow file is invalid, the entire registry fails to load and no workflows are available.

- **File**: `core/workflow_registry.py:76-77`
- **Scenario**: A single malformed YAML file (e.g., during development) prevents all other valid workflows from loading.
- **Impact**: MEDIUM. This is arguably correct for production (Constitution Principle 1: fail explicitly), but harsh for development workflows. Constitution says fail explicitly, so this may be intentional.

**MEDIUM-3: No loader validation for conditional `condition` field references**

The conditional node `condition` field (e.g., `"download_source.result.file_size_bytes"` in `process_raster.yaml:43`) is a dotted path into predecessor outputs, but no loader validation checks whether the referenced node exists in the condition string. Only `depends_on` and `receives` are validated.

- **File**: `core/workflow_loader.py` (missing validation)
- **Scenario**: A conditional with `condition: "nonexistent_node.result.value"` passes loader validation.
- **Impact**: LOW (runtime evaluation catches this), but inconsistent with the thoroughness of other validations.

### RISKS

1. **Jinja2 template injection**: Fan-out params use Jinja2 rendering with `NativeEnvironment`. While templates come from trusted YAML files (not user input), `NativeEnvironment` can evaluate Python expressions. If workflow YAML ever becomes user-editable, this is a code execution vector.

2. **Deterministic run_id collision on parameter mutation**: `_generate_run_id` hashes workflow name + parameters. If a workflow is resubmitted with identical params but different intent (e.g., re-run after fixing source data), the idempotent path returns the old (possibly FAILED) run. The caller must vary parameters to force a new run.

3. **Large fan-out memory pressure**: `expand_fan_outs` in `dag_fan_engine.py` loads all predecessor outputs into memory and passes them to `resolve_fan_out_params` for each item. For a 500-item fan-out with large predecessor results, this could consume significant memory.

### EDGE CASES

1. **Empty fan-out source list**: If a fan-out source resolves to `[]`, the fan-out creates zero children. The fan-in may then aggregate an empty list. Behavior is correct but should be documented.

2. **Conditional with all branches skipped**: If the condition evaluates to a value that matches no branch and the default branch next targets a node that is also a target of another branch, the dependency resolution is complex. The code handles this via `all_predecessors_terminal` but edge cases may exist.

3. **Receives from optional dependency that was skipped**: If `persist_tiled` receives from `validate.result.*` but validate was on the other conditional branch (single COG), the receives resolution could fail. In `process_raster.yaml`, this is safe because validate runs on BOTH paths (it's before the conditional). But the pattern could be fragile in future workflows.

4. **`_build_tasks_and_deps` root detection via `all_downstream_names`**: This set includes both `depends_on` targets AND conditional branch targets. A node that appears only as a conditional branch target but has no `depends_on` is correctly treated as non-root. But if a new edge type is added (e.g., fan-out implicit edges), the root detection would need updating.

---

## Gamma Review: Contradictions, Blind Spots, and Recalibration

### CONTRADICTIONS

**None found.** Alpha and Beta reached compatible conclusions. Alpha identified the `aggregate_tiles.results` path bug from the data contract side; Beta's validation gap findings explain why the loader doesn't catch it. The two analyses reinforce each other.

### AGREEMENT REINFORCEMENT

**AG-1: Late discovery of dotted path errors (Alpha HIGH-1 + Beta HIGH-2)**

Both reviewers independently identified that receives/source path validation is shallow. Alpha found the specific bug (`aggregate_tiles.results` should be `aggregate_tiles.items`). Beta found the structural gap (loader only validates first segment). Combined confidence: CONFIRMED.

- **Files**: `workflows/process_raster.yaml:138`, `core/workflow_loader.py:251-264`
- **Lines traced**: `dag_fan_engine.py:752` produces `{"items": [...]}`, `param_resolver.py:55-133` resolves dotted paths, `workflow_loader.py:258` only checks `path.split('.')[0]`.

**AG-2: Optional parameter handling gap (Alpha implicit + Beta MEDIUM-1)**

Alpha noted that many workflow parameters are `required: false` without defaults. Beta identified that `resolve_task_params` raises on missing keys regardless of required status. The parameter resolver has no awareness of the workflow-level parameter schema.

### BLIND SPOTS

**BLIND-1: `when` clause evaluation not validated by loader** [CONFIRMED]

`TaskNode.when` (e.g., `"params.processing_options.split_column"` in `vector_docker_etl.yaml:53`) references job parameters, but neither the loader nor the initializer validates that the referenced path exists in the declared parameters. If `processing_options` is optional and omitted, the when-clause evaluation at runtime must handle None gracefully.

- **File**: `core/workflow_loader.py` (missing validation), `workflows/vector_docker_etl.yaml:53`, `workflows/echo_test.yaml:19`
- **Traced**: The `when` clause is stored on `WorkflowTask.when_clause` (dag_initializer.py:243) and evaluated by the transition engine. The engine's handling of None intermediate values determines behavior.
- **Severity**: LOW (runtime handles it; when clause evaluates to falsy on missing path, correctly skipping the node)

**BLIND-2: `hello_world.yaml` receives path references non-standard result key** [CONFIRMED]

`hello_world.yaml:19` uses `original_greeting: "greet.greeting"`. This works because `handle_greeting` returns `{"success": True, "greeting": "..."}` at root level. But most production handlers return nested under `result`. This is a test workflow only, but if used as a template for new workflows, it would propagate the inconsistency.

- **File**: `workflows/hello_world.yaml:19`, `services/service_hello_world.py:59-65`
- **Severity**: LOW (test workflow, no production impact)

**BLIND-3: `acled_sync.yaml` receives from skipped predecessor output** [PROBABLE]

`append_to_silver` at `acled_sync.yaml:31-32` receives `new_events: "fetch_and_diff.result.new_events"` and `event_count: "fetch_and_diff.result.metadata.new_count"`. It depends on `save_to_bronze` but receives from `fetch_and_diff` (grandparent). This works because `predecessor_outputs` includes all completed tasks, not just direct predecessors. But if `fetch_and_diff` produces a large `raw_responses` blob, it stays in predecessor_outputs memory for the entire workflow duration.

- **File**: `workflows/acled_sync.yaml:31-32`
- **Severity**: LOW (data is small for ACLED sync)

**BLIND-4: No cross-workflow parameter naming convention enforcement** [CONFIRMED]

Different workflows use different names for the same concept: `blob_name` (raster) vs `source_url` (zarr), `collection_id` (raster/zarr) vs `table_name` (vector). There's no enforcement that semantically equivalent parameters use the same names across workflows.

- **Severity**: LOW (each workflow is self-contained, but hinders automation/generalization)

**BLIND-5: `ingest_zarr.yaml` conditional uses `"truthy"` condition string** [CONFIRMED]

`ingest_zarr.yaml:39` has `condition: "truthy"` as a branch condition for the `rechunk_mode` branch. The conditional evaluator must interpret this string. Looking at the fan engine's `_evaluate_branch_condition` function, this should match the actual truthiness of `params.rechunk`. If the evaluator doesn't recognize `"truthy"` as a special keyword, it may always match or never match.

- **File**: `workflows/ingest_zarr.yaml:39`, `core/dag_fan_engine.py` (conditional evaluator)
- **Severity**: MEDIUM (if the evaluator doesn't handle "truthy", the rechunk path is unreachable)

### SEVERITY RECALIBRATION

| ID | Source | Original | Recalibrated | Confidence | Rationale |
|----|--------|----------|--------------|------------|-----------|
| Alpha-HIGH-1 | Alpha | HIGH | **HIGH** | CONFIRMED | `aggregate_tiles.results` will KeyError at runtime. Traced through fan engine line 752. |
| Alpha-HIGH-2 | Alpha | HIGH | **MEDIUM** | CONFIRMED | Missing `reversed_by` field. Principle 5 violation but non-blocking -- reverse lookup not used in active code paths. |
| Alpha-MEDIUM-1 | Alpha | MEDIUM | **LOW** | CONFIRMED | Handler result structure inconsistency. Each workflow correctly matches its handler. Convention issue, not bug. |
| Alpha-MEDIUM-2 | Alpha | MEDIUM | **LOW** | CONFIRMED | `cog_id` naming. Cosmetic, handler works correctly with any identifier. |
| Alpha-MEDIUM-3 | Alpha | MEDIUM | **MEDIUM** | CONFIRMED | `process_raster_single_cog.yaml` lacks STAC and reverse. Functional gap, not bug. |
| Alpha-MEDIUM-4 | Alpha | MEDIUM | **LOW** | CONFIRMED | `get_leaf_nodes()` `?` suffix bug. Not used in runtime code. |
| Alpha-LOW-1 | Alpha | LOW | **LOW** | CONFIRMED | Missing finalize blocks in utility workflows. |
| Alpha-LOW-2 | Alpha | LOW | **LOW** | CONFIRMED | `vector_finalize` naming. |
| Beta-HIGH-1 | Beta | HIGH | **MEDIUM** | CONFIRMED | Dict params not validated. Runtime Jinja2 StrictUndefined catches errors. |
| Beta-HIGH-2 | Beta | HIGH | **MEDIUM** | CONFIRMED | Receives path depth not validated. Runtime resolver catches errors. |
| Beta-MEDIUM-1 | Beta | MEDIUM | **MEDIUM** | PROBABLE | Optional param handling. Need to verify if submission layer applies defaults. |
| Beta-MEDIUM-2 | Beta | MEDIUM | **LOW** | CONFIRMED | Fail-fast on invalid workflow file. Consistent with Constitution Principle 1. |
| Beta-MEDIUM-3 | Beta | MEDIUM | **LOW** | CONFIRMED | Conditional condition field not validated. Runtime catches. |
| BLIND-1 | Gamma | - | **LOW** | CONFIRMED | When clause path not validated. Runtime handles gracefully. |
| BLIND-5 | Gamma | - | **MEDIUM** | PROBABLE | `"truthy"` condition keyword. Needs evaluation path verification. |

---

## Delta Report: Final Prioritized Analysis

### EXECUTIVE SUMMARY

The workflow YAML definitions and their supporting Python control flow modules form a well-structured DAG system with strong structural validation (9 checks in the loader) and a robust parameter resolution pipeline (dotted paths + Jinja2 templates). The architecture is sound. However, a confirmed data contract bug in `process_raster.yaml` will crash the tiled raster path, and the validation layer has systematic gaps in dotted-path depth checking that allow typos to pass to runtime. The paired lifecycle compliance is incomplete for 3 of 5 production workflows. All findings are localized and independently fixable.

### TOP 5 FIXES

**Fix 1: Correct fan-in result path in process_raster.yaml**

- **WHAT**: Change `aggregate_tiles.results` to `aggregate_tiles.items` in the persist_tiled receives block.
- **WHY**: `AggregationMode.COLLECT` stores results under key `"items"` (dag_fan_engine.py:752). The current path `"results"` will raise `ParameterResolutionError` when any raster >2GB triggers the tiled path.
- **WHERE**: `workflows/process_raster.yaml`, `persist_tiled` node, line 138.
- **HOW**: Change `tile_results: "aggregate_tiles.results"` to `tile_results: "aggregate_tiles.items"`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Single line change, no downstream consumers of the old path.

**Fix 2: Add `reversed_by` field to `process_raster.yaml`**

- **WHAT**: Add `reversed_by: unpublish_raster` to make the forward-reverse workflow pairing bidirectional.
- **WHY**: Constitution Principle 5 (Paired Lifecycles). `unpublish_raster.yaml` already declares `reverses: [process_raster]` but the forward workflow doesn't reciprocate. `WorkflowRegistry.get_reverse_workflow("process_raster")` returns None.
- **WHERE**: `workflows/process_raster.yaml`, after `version: 2` (line 3).
- **HOW**: Add `reversed_by: unpublish_raster` on line 4.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Adding a metadata field.

**Fix 3: Fix `get_leaf_nodes()` to strip `?` suffix from optional deps**

- **WHAT**: Strip the `?` suffix from dependency strings before adding to the `referenced` set.
- **WHY**: Optional dependency strings like `"materialize_single_item?"` don't match the node name `"materialize_single_item"`, causing optional-dep targets to be incorrectly classified as leaf nodes.
- **WHERE**: `core/models/workflow_definition.py`, `get_leaf_nodes()`, line 165.
- **HOW**: Replace `referenced.update(node.depends_on)` with `referenced.update(dep.rstrip('?') for dep in node.depends_on)`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Method not used in runtime code currently.

**Fix 4: Add loader validation for fan-out template Jinja2 variable references**

- **WHAT**: Add a validation check that Jinja2 templates in fan-out params only reference `inputs.*` keys that exist in the workflow's declared parameters.
- **WHY**: Currently, typos in `{{ inputs.nonexistent }}` pass all 9 loader validations and only fail at runtime during fan-out expansion.
- **WHERE**: `core/workflow_loader.py`, new validation method, called from `_validate_structure()`.
- **HOW**: Parse Jinja2 AST for each fan-out template value, extract `inputs.*` references, validate against `defn.parameters`. Skip `item`, `index`, and `nodes.*` references (runtime-only).
- **EFFORT**: Medium (1-4 hours). Requires Jinja2 AST parsing.
- **RISK OF FIX**: Medium. Jinja2 AST parsing can be fragile. Test thoroughly against all 11 workflows.

**Fix 5: Add STAC materialization nodes to `process_raster_single_cog.yaml`**

- **WHAT**: Add `materialize_item` and `materialize_collection` nodes matching the pattern in `process_raster.yaml`.
- **WHY**: The single COG workflow produces app table entries but never materializes STAC items, making outputs invisible to pgSTAC/TiTiler. This is a functional gap -- workflows that create data should also publish it.
- **WHERE**: `workflows/process_raster_single_cog.yaml`, after `persist_app_tables` node.
- **HOW**: Add two task nodes: `materialize_item` (depends on `persist_app_tables`, handler `stac_materialize_item`, receives `cog_id` and `blob_path` from `upload_cog`) and `materialize_collection` (depends on `materialize_item`, handler `stac_materialize_collection`).
- **EFFORT**: Small (< 1 hour). Copy from process_raster.yaml and adjust node names.
- **RISK OF FIX**: Low. Additive change.

### ACCEPTED RISKS

1. **Inconsistent handler result structure (root vs `result` wrapper)**: Real inconsistency, but each workflow's receives paths correctly match its handlers. Establishing a convention is a documentation task, not a code fix. **Revisit when**: creating a workflow template generator or linter.

2. **Loader does not validate receives dotted path depth** (Beta-HIGH-2): The runtime `resolve_dotted_path` provides clear error messages with available keys. Adding compile-time validation would require handler return schema declarations, which don't exist yet. **Revisit when**: handler contracts are formalized in a schema registry.

3. **`resolve_task_params` raises on optional params** (Beta-MEDIUM-1): The submission layer should apply defaults from `ParameterDef.default` before passing to the initializer. If this is already happening, the risk is zero. **Revisit when**: a workflow submission fails on an optional parameter.

4. **`"truthy"` condition keyword in `ingest_zarr.yaml`** (BLIND-5): The conditional evaluator's handling of this needs verification. If it works, no fix needed. If not, the rechunk path is unreachable. **Revisit when**: the zarr ingest workflow is first tested E2E.

5. **Jinja2 NativeEnvironment template execution** (Beta RISK-1): Templates come from trusted YAML files in the repository. No user-editable workflow YAML exists. **Revisit when**: workflow YAML becomes user-submittable.

### ARCHITECTURE WINS

1. **9-validation loader pipeline** (`workflow_loader.py:69-85`): The layered validation catches structural issues at load time. Cycle detection, reachability, fan-in pairing, and handler verification provide defense in depth. This is a textbook validation pipeline.

2. **Deterministic run ID generation** (`dag_initializer.py:72-85`): SHA256(workflow_name + canonical JSON params) provides idempotent deduplication. The explicit `_canonical_json_default` serializer rejects unknown types per Constitution Standard 1.1.

3. **Three-pass task and dep builder** (`dag_initializer.py:152-316`): Clean separation of concerns: Pass 1 validates, Pass 2 builds tasks, Pass 3 builds edges with deduplication. Root nodes get pre-resolved params; non-roots defer to the transition engine.

4. **Pure function parameter resolution** (`param_resolver.py`): No DB, no I/O, no side effects. Three functions (`resolve_dotted_path`, `resolve_task_params`, `resolve_fan_out_params`) are independently testable. Jinja2 NativeEnvironment preserves Python types.

5. **Conditional branch + optional dep pattern** (`process_raster.yaml`): The `route_by_size` conditional with `create_single_cog`/`generate_tiling_scheme` targets, converging at `materialize_collection` via optional deps (`"materialize_single_item?"`, `"persist_tiled?"`), is a clean pattern for workflows with mutually exclusive paths.
