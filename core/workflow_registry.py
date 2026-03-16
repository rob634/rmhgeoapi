# ============================================================================
# CLAUDE CONTEXT - WORKFLOW REGISTRY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - In-memory workflow definition cache
# PURPOSE: Load all YAML workflow files from a directory at startup, provide lookup by name
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRegistry, WorkflowNotFoundError
# DEPENDENCIES: core.workflow_loader, core.models.workflow_definition
# ============================================================================

import logging
from pathlib import Path
from typing import Optional

from core.models.workflow_definition import WorkflowDefinition
from core.workflow_loader import WorkflowLoader, WorkflowValidationError

logger = logging.getLogger(__name__)


class WorkflowNotFoundError(Exception):
    """Raised when a workflow name is not in the registry."""

    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        super().__init__(f"Workflow not found: '{workflow_name}'")


class WorkflowRegistry:
    """In-memory cache of validated workflow definitions loaded from YAML files."""

    def __init__(
        self,
        workflows_dir: Path,
        handler_names: Optional[set[str]] = None,
    ):
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._dir = workflows_dir
        self._handler_names = handler_names
        self._file_paths: dict[str, Path] = {}

    def load_all(self) -> int:
        """Load all *.yaml and *.yml files from the directory.

        Fails fast on any invalid workflow. Rejects duplicate workflow names
        across different files.

        Returns:
            Number of workflows loaded.

        Raises:
            WorkflowValidationError: If any file is invalid or duplicates exist.
        """
        if not self._dir.exists():
            logger.warning("Workflows directory does not exist: %s", self._dir)
            return 0

        # Collect and sort for deterministic load order
        files = sorted(
            f for f in self._dir.iterdir()
            if f.is_file() and f.suffix in ('.yaml', '.yml')
        )

        for filepath in files:
            defn = WorkflowLoader.load(filepath, self._handler_names)
            name = defn.workflow

            # Check for duplicate workflow name from a different file
            if name in self._workflows:
                existing_file = self._file_paths[name]
                raise WorkflowValidationError(
                    name,
                    [
                        f"Duplicate workflow name '{name}' in "
                        f"'{filepath.name}' and '{existing_file.name}'"
                    ],
                )

            self._workflows[name] = defn
            self._file_paths[name] = filepath

        logger.info(
            "Loaded %d workflow(s) from %s", len(self._workflows), self._dir
        )
        return len(self._workflows)

    def get(self, name: str) -> Optional[WorkflowDefinition]:
        """Return workflow definition by name, or None if not found."""
        return self._workflows.get(name)

    def get_or_raise(self, name: str) -> WorkflowDefinition:
        """Return workflow definition by name, or raise WorkflowNotFoundError."""
        defn = self._workflows.get(name)
        if defn is None:
            raise WorkflowNotFoundError(name)
        return defn

    def has(self, name: str) -> bool:
        """Check if a workflow name is loaded."""
        return name in self._workflows

    def list_workflows(self) -> list[str]:
        """Return sorted list of loaded workflow names."""
        return sorted(self._workflows.keys())

    def get_reverse_workflow(self, name: str) -> Optional[str]:
        """Return the reversed_by field for a workflow, or None."""
        defn = self._workflows.get(name)
        if defn is None:
            return None
        return defn.reversed_by
