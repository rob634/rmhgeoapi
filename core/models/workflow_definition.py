# ============================================================================
# CLAUDE CONTEXT - WORKFLOW DEFINITION MODELS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Pydantic models for DAG-based YAML workflow definitions
# PURPOSE: Define the complete workflow schema: supporting models, node types (discriminated union), and WorkflowDefinition
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: RetryPolicy, BranchDef, FanOutTaskDef, FinalizeDef, ParameterDef, ValidatorDef, TaskNode, ConditionalNode, FanOutNode, FanInNode, GateNode, NodeDefinition, WorkflowDefinition
# DEPENDENCIES: pydantic, workflow_enums
# ============================================================================

from typing import Any, Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .workflow_enums import AggregationMode, BackoffStrategy


# ============================================================================
# SUPPORTING MODELS
# ============================================================================


class RetryPolicy(BaseModel):
    """Retry configuration for task execution."""
    model_config = ConfigDict(extra='forbid')

    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_seconds: int = Field(default=5, ge=1)
    max_delay_seconds: int = Field(default=300, ge=1)

    @model_validator(mode='after')
    def check_delay_bounds(self) -> 'RetryPolicy':
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError(
                f"initial_delay_seconds ({self.initial_delay_seconds}) must be "
                f"<= max_delay_seconds ({self.max_delay_seconds})"
            )
        return self


class BranchDef(BaseModel):
    """A single branch within a conditional node."""
    model_config = ConfigDict(extra='forbid')

    name: str
    condition: Optional[str] = None
    default: bool = False
    next: list[str]


class FanOutTaskDef(BaseModel):
    """Task template for fan-out parallel execution."""
    model_config = ConfigDict(extra='forbid')

    handler: str
    params: dict[str, Any] = {}
    timeout_seconds: int = 3600
    retry: Optional[RetryPolicy] = None


class FinalizeDef(BaseModel):
    """Post-workflow finalization handler."""
    model_config = ConfigDict(extra='forbid')

    handler: str


class ParameterDef(BaseModel):
    """Schema for a single workflow parameter."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["str", "int", "float", "bool", "dict", "list"]
    required: bool = False
    default: Any = None
    nested: Optional[dict[str, 'ParameterDef']] = None


class ValidatorDef(BaseModel):
    """Pre-execution validator with extensible fields."""
    type: str
    model_config = ConfigDict(extra='allow')


# ============================================================================
# NODE TYPES (DISCRIMINATED UNION)
# ============================================================================


class TaskNode(BaseModel):
    """A single task execution node."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["task"] = "task"
    handler: str
    depends_on: list[str] = []
    params: list[str] | dict[str, Any] = []
    receives: dict[str, str] = {}
    constants: dict[str, Any] = {}
    when: Optional[str] = None
    retry: Optional[RetryPolicy] = None
    timeout_seconds: Optional[int] = None
    best_effort: bool = False


class ConditionalNode(BaseModel):
    """A branching node that evaluates a condition to select a path."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["conditional"]
    depends_on: list[str] = []
    condition: str
    branches: list[BranchDef] = Field(min_length=2)


class FanOutNode(BaseModel):
    """A scatter node that creates parallel tasks from a source list."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["fan_out"]
    depends_on: list[str] = []
    source: str
    task: FanOutTaskDef
    max_fan_out: int = Field(default=500, ge=1, le=10000)


class FanInNode(BaseModel):
    """A gather node that aggregates results from upstream parallel tasks."""
    model_config = ConfigDict(extra='forbid')

    type: Literal["fan_in"]
    depends_on: list[str]
    aggregation: AggregationMode = AggregationMode.COLLECT


class GateNode(BaseModel):
    """
    A node that suspends workflow execution until an external signal.

    Gate nodes block downstream dependencies until completed by an external
    API call (e.g., human approval). The transition engine promotes gate nodes
    to WAITING (not READY), and the janitor/Brain skip workflows in
    AWAITING_APPROVAL status.

    Transitions:
      PENDING → WAITING (when predecessors complete)
      WAITING → COMPLETED (external API approves)
      WAITING → SKIPPED (external API rejects)
    """
    model_config = ConfigDict(extra='forbid')

    type: Literal["gate"] = "gate"
    depends_on: list[str] = []
    gate_type: str = "approval"


# Discriminated union over the 'type' field
NodeDefinition = Annotated[
    TaskNode | ConditionalNode | FanOutNode | FanInNode | GateNode,
    Field(discriminator='type')
]


# ============================================================================
# TOP-LEVEL WORKFLOW DEFINITION
# ============================================================================


class WorkflowDefinition(BaseModel):
    """Complete DAG-based workflow definition, parsed from YAML."""
    model_config = ConfigDict(extra='forbid')

    workflow: str
    description: str
    version: int
    reversed_by: Optional[str] = None
    reverses: list[str] = []
    parameters: dict[str, ParameterDef]
    validators: list[ValidatorDef] = []
    nodes: dict[str, NodeDefinition]
    finalize: Optional[FinalizeDef] = None

    def get_node(self, name: str) -> NodeDefinition:
        """Get a node by name. Raises KeyError if not found."""
        return self.nodes[name]

    def get_root_nodes(self) -> dict[str, NodeDefinition]:
        """Return nodes with no dependencies (entry points)."""
        return {
            name: node for name, node in self.nodes.items()
            if not node.depends_on
        }

    def get_gate_nodes(self) -> list[str]:
        """Return names of all gate nodes in this workflow."""
        return [
            name for name, node in self.nodes.items()
            if isinstance(node, GateNode)
        ]

    def get_leaf_nodes(self) -> dict[str, NodeDefinition]:
        """Return nodes that no other node depends on or targets via branches."""
        # Collect all referenced node names (strip ? suffix from optional deps)
        referenced: set[str] = set()
        for node in self.nodes.values():
            referenced.update(dep.rstrip("?") for dep in node.depends_on)
            # Conditional branches reference next targets
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    referenced.update(branch.next)

        return {
            name: node for name, node in self.nodes.items()
            if name not in referenced
        }
