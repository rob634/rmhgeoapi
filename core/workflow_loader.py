# ============================================================================
# CLAUDE CONTEXT - WORKFLOW LOADER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - YAML workflow parser with structural validations
# PURPOSE: Load YAML workflow files, validate with Pydantic, run 9 structural validations
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowLoader, WorkflowValidationError
# DEPENDENCIES: pyyaml, pydantic, core.models.workflow_definition
# ============================================================================

from collections import deque
from pathlib import Path
from typing import Optional

import yaml

from core.models.workflow_definition import (
    ConditionalNode,
    FanInNode,
    FanOutNode,
    TaskNode,
    WorkflowDefinition,
)


class WorkflowValidationError(Exception):
    """Raised when a workflow fails structural validation."""

    def __init__(self, workflow_name: str, errors: list[str]):
        self.workflow_name = workflow_name
        self.errors = errors
        super().__init__(f"Workflow '{workflow_name}' invalid: {'; '.join(errors)}")


class WorkflowLoader:
    """Load and validate YAML workflow definitions."""

    @staticmethod
    def load(path: Path, handler_names: Optional[set[str]] = None) -> WorkflowDefinition:
        """Load and validate a YAML workflow file.

        Args:
            path: Path to the YAML workflow file.
            handler_names: Optional set of known handler names for validation.

        Returns:
            Validated WorkflowDefinition.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            WorkflowValidationError: If structural validations fail.
        """
        with open(path, 'r') as f:
            raw_dict = yaml.safe_load(f)

        defn = WorkflowDefinition.model_validate(raw_dict)

        errors = WorkflowLoader._validate_structure(defn, handler_names)
        if errors:
            raise WorkflowValidationError(defn.workflow, errors)

        return defn

    @staticmethod
    def _validate_structure(
        defn: WorkflowDefinition,
        handler_names: Optional[set[str]] = None,
    ) -> list[str]:
        """Run all structural validations, collecting errors."""
        errors: list[str] = []
        errors.extend(WorkflowLoader._check_dependency_refs(defn))
        errors.extend(WorkflowLoader._check_branch_refs(defn))
        errors.extend(WorkflowLoader._check_conditional_defaults(defn))
        errors.extend(WorkflowLoader._check_fan_in_refs(defn))
        errors.extend(WorkflowLoader._check_receives_refs(defn))
        errors.extend(WorkflowLoader._check_param_refs(defn))
        errors.extend(WorkflowLoader._check_cycles(defn))
        errors.extend(WorkflowLoader._check_reachability(defn))
        if handler_names is not None:
            errors.extend(WorkflowLoader._check_handlers(defn, handler_names))
        return errors

    @staticmethod
    def _parse_dep(dep: str) -> tuple[str, bool]:
        """Strip '?' suffix from a dependency name.

        Returns:
            (node_name, is_optional)
        """
        if dep.endswith('?'):
            return dep[:-1], True
        return dep, False

    # ------------------------------------------------------------------
    # Validation 1: Cycle detection (Kahn's algorithm)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_cycles(defn: WorkflowDefinition) -> list[str]:
        """Detect cycles using Kahn's topological sort algorithm."""
        node_names = set(defn.nodes.keys())
        # Build adjacency: predecessor → set of successors
        adjacency: dict[str, set[str]] = {name: set() for name in node_names}
        in_degree: dict[str, int] = {name: 0 for name in node_names}

        for name, node in defn.nodes.items():
            # depends_on: predecessors → this node
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name in node_names:
                    adjacency[dep_name].add(name)
                    in_degree[name] += 1

            # Conditional branch next: this node → targets
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target in node_names:
                            adjacency[name].add(target)
                            in_degree[target] += 1

        # Kahn's algorithm
        queue = deque(n for n in node_names if in_degree[n] == 0)
        visited_count = 0

        while queue:
            current = queue.popleft()
            visited_count += 1
            for successor in adjacency[current]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if visited_count < len(node_names):
            remaining = [n for n in node_names if in_degree[n] > 0]
            return [f"Cycle detected involving nodes: {', '.join(sorted(remaining))}"]

        return []

    # ------------------------------------------------------------------
    # Validation 2: Dependency references exist
    # ------------------------------------------------------------------
    @staticmethod
    def _check_dependency_refs(defn: WorkflowDefinition) -> list[str]:
        """Every depends_on name must exist as a node key."""
        errors: list[str] = []
        node_names = set(defn.nodes.keys())
        for name, node in defn.nodes.items():
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name not in node_names:
                    errors.append(
                        f"Node '{name}' depends on '{dep_name}' which does not exist"
                    )
        return errors

    # ------------------------------------------------------------------
    # Validation 3: Branch target references exist
    # ------------------------------------------------------------------
    @staticmethod
    def _check_branch_refs(defn: WorkflowDefinition) -> list[str]:
        """Every conditional branch next: target must exist as a node key."""
        errors: list[str] = []
        node_names = set(defn.nodes.keys())
        for name, node in defn.nodes.items():
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target not in node_names:
                            errors.append(
                                f"Node '{name}' branch '{branch.name}' targets "
                                f"'{target}' which does not exist"
                            )
        return errors

    # ------------------------------------------------------------------
    # Validation 4: Conditional nodes have a default branch
    # ------------------------------------------------------------------
    @staticmethod
    def _check_conditional_defaults(defn: WorkflowDefinition) -> list[str]:
        """Every ConditionalNode must have at least one branch with default=True."""
        errors: list[str] = []
        for name, node in defn.nodes.items():
            if isinstance(node, ConditionalNode):
                has_default = any(b.default for b in node.branches)
                if not has_default:
                    errors.append(
                        f"Conditional node '{name}' has no default branch"
                    )
        return errors

    # ------------------------------------------------------------------
    # Validation 5: FanInNode depends on exactly one FanOutNode
    # ------------------------------------------------------------------
    @staticmethod
    def _check_fan_in_refs(defn: WorkflowDefinition) -> list[str]:
        """Every FanInNode must depend on exactly one FanOutNode."""
        errors: list[str] = []
        for name, node in defn.nodes.items():
            if isinstance(node, FanInNode):
                fan_out_count = 0
                for dep in node.depends_on:
                    dep_name, _ = WorkflowLoader._parse_dep(dep)
                    dep_node = defn.nodes.get(dep_name)
                    if isinstance(dep_node, FanOutNode):
                        fan_out_count += 1
                if fan_out_count != 1:
                    errors.append(
                        f"FanInNode '{name}' depends on {fan_out_count} "
                        f"FanOutNode(s), expected exactly 1"
                    )
        return errors

    # ------------------------------------------------------------------
    # Validation 6: Handler names exist in registry
    # ------------------------------------------------------------------
    @staticmethod
    def _check_handlers(
        defn: WorkflowDefinition, handler_names: set[str]
    ) -> list[str]:
        """All handler names must exist in the provided handler registry."""
        errors: list[str] = []

        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode):
                if node.handler not in handler_names:
                    errors.append(
                        f"Node '{name}' references unknown handler '{node.handler}'"
                    )
            elif isinstance(node, FanOutNode):
                if node.task.handler not in handler_names:
                    errors.append(
                        f"Node '{name}' fan_out task references unknown handler "
                        f"'{node.task.handler}'"
                    )

        if defn.finalize and defn.finalize.handler not in handler_names:
            errors.append(
                f"Finalize references unknown handler '{defn.finalize.handler}'"
            )

        return errors

    # ------------------------------------------------------------------
    # Validation 7: Receives node references exist
    # ------------------------------------------------------------------
    @staticmethod
    def _check_receives_refs(defn: WorkflowDefinition) -> list[str]:
        """For receives paths like 'validate.result.metadata', the first segment must be a node."""
        errors: list[str] = []
        node_names = set(defn.nodes.keys())
        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode) and node.receives:
                for key, path in node.receives.items():
                    ref_node = path.split('.')[0]
                    if ref_node not in node_names:
                        errors.append(
                            f"Node '{name}' receives '{key}' references "
                            f"unknown node '{ref_node}'"
                        )
        return errors

    # ------------------------------------------------------------------
    # Validation 8: Param list items exist in workflow parameters
    # ------------------------------------------------------------------
    @staticmethod
    def _check_param_refs(defn: WorkflowDefinition) -> list[str]:
        """When params is a list, each item must exist in defn.parameters."""
        errors: list[str] = []
        param_names = set(defn.parameters.keys())
        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode) and isinstance(node.params, list):
                for param in node.params:
                    if param not in param_names:
                        errors.append(
                            f"Node '{name}' references undeclared parameter '{param}'"
                        )
        return errors

    # ------------------------------------------------------------------
    # Validation 9: All nodes reachable from roots (BFS)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_reachability(defn: WorkflowDefinition) -> list[str]:
        """BFS from root nodes. All nodes must be reachable."""
        node_names = set(defn.nodes.keys())

        # Build successor adjacency (forward edges)
        successors: dict[str, set[str]] = {name: set() for name in node_names}
        for name, node in defn.nodes.items():
            # depends_on: predecessor → this node
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name in node_names:
                    successors[dep_name].add(name)

            # Conditional branch targets
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target in node_names:
                            successors[name].add(target)

        # Find root nodes (no dependencies)
        roots = {name for name, node in defn.nodes.items() if not node.depends_on}

        # BFS
        visited: set[str] = set()
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for successor in successors[current]:
                if successor not in visited:
                    queue.append(successor)

        orphans = node_names - visited
        if orphans:
            return [
                f"Unreachable node(s): {', '.join(sorted(orphans))}"
            ]

        return []
