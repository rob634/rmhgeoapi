# ============================================================================
# CLAUDE CONTEXT - DAG INITIALIZER TESTS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Tests - Pure function tests for DAG initialization logic
# PURPOSE: Unit tests for _generate_run_id, _parse_dep, _resolve_handler,
#          _resolve_max_retries, and _build_tasks_and_deps
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: TestGenerateRunId, TestParseDep, TestResolveHandler,
#          TestResolveMaxRetries, TestBuildTasksAndDeps
# DEPENDENCIES: pytest, core.dag_initializer, core.models.workflow_definition
# ============================================================================

import pytest

from core.dag_initializer import (
    _generate_run_id,
    _generate_task_instance_id,
    _parse_dep,
    _resolve_handler,
    _resolve_max_retries,
    _build_tasks_and_deps,
)
from core.models.workflow_definition import (
    WorkflowDefinition,
    TaskNode,
    ConditionalNode,
    FanOutNode,
    FanInNode,
    FanOutTaskDef,
    BranchDef,
    ParameterDef,
    RetryPolicy,
)
from core.models.workflow_enums import WorkflowTaskStatus
from exceptions import ContractViolationError


# ============================================================================
# HELPERS
# ============================================================================


def _make_defn(nodes: dict, workflow: str = "test_wf") -> WorkflowDefinition:
    """Build a minimal WorkflowDefinition with the given nodes dict."""
    return WorkflowDefinition(
        workflow=workflow,
        description="test",
        version=1,
        parameters={"msg": ParameterDef(type="str", required=True)},
        nodes=nodes,
    )


# ============================================================================
# TestGenerateRunId
# ============================================================================


class TestGenerateRunId:
    """Tests for _generate_run_id determinism and sensitivity."""

    def test_deterministic_same_inputs(self):
        """Same (workflow_name, parameters) produces the same run_id."""
        params = {"message": "hello", "count": 5}
        id1 = _generate_run_id("my_workflow", params)
        id2 = _generate_run_id("my_workflow", params)
        assert id1 == id2

    def test_sensitive_to_parameters(self):
        """Different parameters produce different run_ids."""
        id1 = _generate_run_id("wf", {"a": 1})
        id2 = _generate_run_id("wf", {"a": 2})
        assert id1 != id2

    def test_sensitive_to_workflow_name(self):
        """Different workflow_name produces different run_ids."""
        params = {"x": "y"}
        id1 = _generate_run_id("alpha", params)
        id2 = _generate_run_id("beta", params)
        assert id1 != id2

    def test_returns_hex_string(self):
        """Output is a 64-character hex string (SHA256)."""
        run_id = _generate_run_id("wf", {"key": "val"})
        assert len(run_id) == 64
        assert all(c in "0123456789abcdef" for c in run_id)

    def test_key_order_insensitive(self):
        """Parameter dict key order does not affect run_id (sort_keys=True)."""
        id1 = _generate_run_id("wf", {"b": 2, "a": 1})
        id2 = _generate_run_id("wf", {"a": 1, "b": 2})
        assert id1 == id2


# ============================================================================
# TestParseDep
# ============================================================================


class TestParseDep:
    """Tests for _parse_dep optional suffix parsing."""

    def test_normal_dep(self):
        assert _parse_dep("validate") == ("validate", False)

    def test_optional_dep(self):
        assert _parse_dep("rechunk?") == ("rechunk", True)

    def test_empty_name_with_optional_suffix(self):
        """Edge case: '?' alone produces empty name."""
        assert _parse_dep("?") == ("", True)

    def test_no_mutation_of_normal_name(self):
        """A dep without '?' returns the exact same string."""
        name, opt = _parse_dep("step_one")
        assert name == "step_one"
        assert opt is False


# ============================================================================
# TestResolveHandler
# ============================================================================


class TestResolveHandler:
    """Tests for _resolve_handler mapping node types to handler strings."""

    def test_task_node_returns_handler(self):
        node = TaskNode(handler="process_data")
        assert _resolve_handler("n", node) == "process_data"

    def test_fan_out_node_returns_sentinel(self):
        """Fan-out templates use __fan_out__ sentinel to prevent worker claims."""
        node = FanOutNode(
            type="fan_out",
            source="items",
            task=FanOutTaskDef(handler="process_chunk"),
        )
        assert _resolve_handler("n", node) == "__fan_out__"

    def test_conditional_node_returns_sentinel(self):
        node = ConditionalNode(
            type="conditional",
            condition="params.mode",
            branches=[
                BranchDef(name="a", next=["x"]),
                BranchDef(name="b", default=True, next=["y"]),
            ],
        )
        assert _resolve_handler("n", node) == "__conditional__"

    def test_fan_in_node_returns_sentinel(self):
        node = FanInNode(type="fan_in", depends_on=["scatter"])
        assert _resolve_handler("n", node) == "__fan_in__"

    def test_unknown_type_raises_contract_violation(self):
        """A non-node object raises ContractViolationError."""
        with pytest.raises(ContractViolationError, match="Unknown node type"):
            _resolve_handler("bad", "not_a_node")


# ============================================================================
# TestResolveMaxRetries
# ============================================================================


class TestResolveMaxRetries:
    """Tests for _resolve_max_retries per node type."""

    def test_task_node_with_retry_policy(self):
        node = TaskNode(handler="h", retry=RetryPolicy(max_attempts=7))
        assert _resolve_max_retries(node) == 7

    def test_task_node_without_retry_defaults_to_3(self):
        node = TaskNode(handler="h")
        assert _resolve_max_retries(node) == 3

    def test_fan_out_node_with_retry(self):
        node = FanOutNode(
            type="fan_out",
            source="items",
            task=FanOutTaskDef(handler="h", retry=RetryPolicy(max_attempts=5)),
        )
        assert _resolve_max_retries(node) == 5

    def test_fan_out_node_without_retry_defaults_to_3(self):
        node = FanOutNode(
            type="fan_out",
            source="items",
            task=FanOutTaskDef(handler="h"),
        )
        assert _resolve_max_retries(node) == 3

    def test_conditional_node_returns_zero(self):
        node = ConditionalNode(
            type="conditional",
            condition="params.mode",
            branches=[
                BranchDef(name="a", next=["x"]),
                BranchDef(name="b", default=True, next=["y"]),
            ],
        )
        assert _resolve_max_retries(node) == 0

    def test_fan_in_node_returns_zero(self):
        node = FanInNode(type="fan_in", depends_on=["scatter"])
        assert _resolve_max_retries(node) == 0


# ============================================================================
# TestBuildTasksAndDeps
# ============================================================================


class TestBuildTasksAndDeps:
    """Tests for _build_tasks_and_deps — the core pure function."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _task_by_name(tasks, name):
        """Find a task in the list by task_name."""
        matches = [t for t in tasks if t.task_name == name]
        assert len(matches) == 1, f"Expected 1 task named '{name}', found {len(matches)}"
        return matches[0]

    @staticmethod
    def _dep_edge_set(deps):
        """Return set of (task_name_from_id, depends_on_name_from_id) for readability."""
        # task_instance_id format: '{run_id[:12]}-{task_name}'
        def _name(instance_id: str) -> str:
            return instance_id.split("-", 1)[1]
        return {(_name(d.task_instance_id), _name(d.depends_on_instance_id)) for d in deps}

    # ------------------------------------------------------------------
    # Linear chain: A -> B -> C
    # ------------------------------------------------------------------

    def test_linear_chain_task_count(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
            "c": TaskNode(handler="hc", depends_on=["b"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        assert len(tasks) == 3

    def test_linear_chain_dep_count(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
            "c": TaskNode(handler="hc", depends_on=["b"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        assert len(deps) == 2

    def test_linear_chain_dep_edges(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
            "c": TaskNode(handler="hc", depends_on=["b"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        edges = self._dep_edge_set(deps)
        assert ("b", "a") in edges
        assert ("c", "b") in edges

    def test_linear_chain_root_is_ready(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
            "c": TaskNode(handler="hc", depends_on=["b"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        a = self._task_by_name(tasks, "a")
        b = self._task_by_name(tasks, "b")
        c = self._task_by_name(tasks, "c")
        assert a.status == WorkflowTaskStatus.READY
        assert b.status == WorkflowTaskStatus.PENDING
        assert c.status == WorkflowTaskStatus.PENDING

    def test_linear_chain_instance_id_format(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        a = self._task_by_name(tasks, "a")
        assert a.task_instance_id == f"{run_id[:12]}-a"

    # ------------------------------------------------------------------
    # Single node
    # ------------------------------------------------------------------

    def test_single_node(self):
        defn = _make_defn({"only": TaskNode(handler="h")})
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        assert len(tasks) == 1
        assert len(deps) == 0
        assert tasks[0].status == WorkflowTaskStatus.READY

    # ------------------------------------------------------------------
    # Conditional node with branch targets
    # ------------------------------------------------------------------

    def test_conditional_node_tasks_and_deps(self):
        defn = _make_defn({
            "validate": TaskNode(handler="h_validate"),
            "route": ConditionalNode(
                type="conditional",
                depends_on=["validate"],
                condition="result.file_size",
                branches=[
                    BranchDef(name="large", next=["large_handler"]),
                    BranchDef(name="small", default=True, next=["small_handler"]),
                ],
            ),
            "large_handler": TaskNode(handler="h_large"),
            "small_handler": TaskNode(handler="h_small"),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)

        assert len(tasks) == 4

        # Edges: route depends on validate, large depends on route, small depends on route
        assert len(deps) == 3
        edges = self._dep_edge_set(deps)
        assert ("route", "validate") in edges
        assert ("large_handler", "route") in edges
        assert ("small_handler", "route") in edges

    def test_conditional_node_handler_and_retries(self):
        defn = _make_defn({
            "validate": TaskNode(handler="h_validate"),
            "route": ConditionalNode(
                type="conditional",
                depends_on=["validate"],
                condition="result.file_size",
                branches=[
                    BranchDef(name="a", next=["done_a"]),
                    BranchDef(name="b", default=True, next=["done_b"]),
                ],
            ),
            "done_a": TaskNode(handler="h"),
            "done_b": TaskNode(handler="h"),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        route = self._task_by_name(tasks, "route")
        assert route.handler == "__conditional__"
        assert route.max_retries == 0

    def test_conditional_root_is_ready_others_pending(self):
        defn = _make_defn({
            "validate": TaskNode(handler="h"),
            "route": ConditionalNode(
                type="conditional",
                depends_on=["validate"],
                condition="x",
                branches=[
                    BranchDef(name="a", next=["done"]),
                    BranchDef(name="b", default=True, next=["done"]),
                ],
            ),
            "done": TaskNode(handler="h"),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        validate = self._task_by_name(tasks, "validate")
        route = self._task_by_name(tasks, "route")
        done = self._task_by_name(tasks, "done")
        assert validate.status == WorkflowTaskStatus.READY
        assert route.status == WorkflowTaskStatus.PENDING
        assert done.status == WorkflowTaskStatus.PENDING

    # ------------------------------------------------------------------
    # Branch next creates correct edge direction
    # ------------------------------------------------------------------

    def test_conditional_branch_next_direction(self):
        """The TARGET depends on the conditional, not the other way around."""
        defn = _make_defn({
            "route": ConditionalNode(
                type="conditional",
                condition="x",
                branches=[
                    BranchDef(name="a", next=["target_a"]),
                    BranchDef(name="b", default=True, next=["target_b"]),
                ],
            ),
            "target_a": TaskNode(handler="h"),
            "target_b": TaskNode(handler="h"),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        edges = self._dep_edge_set(deps)
        # target depends on route (not route depends on target)
        assert ("target_a", "route") in edges
        assert ("target_b", "route") in edges
        assert ("route", "target_a") not in edges
        assert ("route", "target_b") not in edges

    # ------------------------------------------------------------------
    # Optional dependency
    # ------------------------------------------------------------------

    def test_optional_dependency(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a?"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)
        assert len(tasks) == 2
        assert len(deps) == 1
        assert deps[0].optional is True

    # ------------------------------------------------------------------
    # Fan-out + fan-in
    # ------------------------------------------------------------------

    def test_fan_out_fan_in(self):
        defn = _make_defn({
            "validate": TaskNode(handler="h_validate"),
            "expand": FanOutNode(
                type="fan_out",
                depends_on=["validate"],
                source="items",
                task=FanOutTaskDef(handler="h_chunk"),
            ),
            "aggregate": FanInNode(
                type="fan_in",
                depends_on=["expand"],
            ),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)

        assert len(tasks) == 3
        assert len(deps) == 2

        expand = self._task_by_name(tasks, "expand")
        assert expand.handler == "__fan_out__"  # Template uses sentinel; children get real handler

        aggregate = self._task_by_name(tasks, "aggregate")
        assert aggregate.handler == "__fan_in__"
        assert aggregate.max_retries == 0

        edges = self._dep_edge_set(deps)
        assert ("expand", "validate") in edges
        assert ("aggregate", "expand") in edges

    # ------------------------------------------------------------------
    # Edge deduplication
    # ------------------------------------------------------------------

    def test_deduplication_of_edges(self):
        """When a conditional's next: target also has explicit depends_on on the
        conditional, only 1 edge is produced, not 2."""
        defn = _make_defn({
            "route": ConditionalNode(
                type="conditional",
                condition="x",
                branches=[
                    BranchDef(name="a", next=["step"]),
                    BranchDef(name="b", default=True, next=["step"]),
                ],
            ),
            # step explicitly depends_on route AND is a branch target
            "step": TaskNode(handler="h", depends_on=["route"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, deps = _build_tasks_and_deps(run_id, defn)

        # Only 1 unique edge: step depends on route
        edges = self._dep_edge_set(deps)
        assert len(edges) == 1
        assert ("step", "route") in edges

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_missing_dependency_reference_raises(self):
        defn = _make_defn({
            "a": TaskNode(handler="h", depends_on=["nonexistent"]),
        })
        run_id = _generate_run_id("test_wf", {})
        with pytest.raises(ContractViolationError, match="unknown node 'nonexistent'"):
            _build_tasks_and_deps(run_id, defn)

    def test_missing_branch_target_raises(self):
        defn = _make_defn({
            "route": ConditionalNode(
                type="conditional",
                condition="x",
                branches=[
                    BranchDef(name="a", next=["ghost"]),
                    BranchDef(name="b", default=True, next=["ghost"]),
                ],
            ),
        })
        run_id = _generate_run_id("test_wf", {})
        with pytest.raises(ContractViolationError, match="unknown node 'ghost'"):
            _build_tasks_and_deps(run_id, defn)

    def test_no_root_nodes_raises(self):
        """All nodes have deps — indicates a cycle."""
        defn = _make_defn({
            "a": TaskNode(handler="h", depends_on=["b"]),
            "b": TaskNode(handler="h", depends_on=["a"]),
        })
        run_id = _generate_run_id("test_wf", {})
        with pytest.raises(ContractViolationError, match="no root nodes"):
            _build_tasks_and_deps(run_id, defn)

    # ------------------------------------------------------------------
    # when clause preservation
    # ------------------------------------------------------------------

    def test_when_clause_preserved(self):
        defn = _make_defn({
            "root": TaskNode(handler="h"),
            "guarded": TaskNode(
                handler="h",
                depends_on=["root"],
                when="params.uppercase",
            ),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        guarded = self._task_by_name(tasks, "guarded")
        assert guarded.when_clause == "params.uppercase"

    def test_when_clause_none_for_non_task_nodes(self):
        defn = _make_defn({
            "validate": TaskNode(handler="h"),
            "route": ConditionalNode(
                type="conditional",
                depends_on=["validate"],
                condition="x",
                branches=[
                    BranchDef(name="a", next=["done_a"]),
                    BranchDef(name="b", default=True, next=["done_b"]),
                ],
            ),
            "done_a": TaskNode(handler="h"),
            "done_b": TaskNode(handler="h"),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        route = self._task_by_name(tasks, "route")
        assert route.when_clause is None

    # ------------------------------------------------------------------
    # All tasks share the same run_id
    # ------------------------------------------------------------------

    def test_all_tasks_share_run_id(self):
        defn = _make_defn({
            "a": TaskNode(handler="ha"),
            "b": TaskNode(handler="hb", depends_on=["a"]),
            "c": TaskNode(handler="hc", depends_on=["b"]),
        })
        run_id = _generate_run_id("test_wf", {})
        tasks, _ = _build_tasks_and_deps(run_id, defn)
        for t in tasks:
            assert t.run_id == run_id
