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

from pathlib import Path
from typing import Optional

from util_logger import LoggerFactory, ComponentType

from core.models.workflow_definition import WorkflowDefinition
from core.workflow_loader import WorkflowLoader, WorkflowValidationError

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, __name__)


from exceptions import ResourceNotFoundError


class WorkflowNotFoundError(ResourceNotFoundError):
    """Raised when a workflow name is not in the registry."""

    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        super().__init__(f"Workflow not found: '{workflow_name}'")


class WorkflowRegistry:
    """In-memory cache of validated workflow definitions loaded from YAML files."""

    # Epoch 4 job_type → Epoch 5 YAML workflow name.
    # Platform submit uses legacy job_type names; the registry resolves to YAML.
    # When a job_type is not in this map, it is used as-is (direct match).
    JOB_TYPE_ALIASES: dict[str, str] = {
        "process_raster_docker": "process_raster",
        "vector_docker_complete": "vector_docker_etl",
    }

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

        Resilient: loads each file independently. Invalid files are skipped
        and recorded in ``self.load_errors`` for health check reporting.
        Valid workflows are cached; broken ones do not block the registry.

        Returns:
            Number of workflows successfully loaded.
        """
        self.load_errors: list[dict] = []

        if not self._dir.exists():
            logger.warning("Workflows directory does not exist: %s", self._dir)
            return 0

        # Collect and sort for deterministic load order
        files = sorted(
            f for f in self._dir.iterdir()
            if f.is_file() and f.suffix in ('.yaml', '.yml')
        )

        for filepath in files:
            try:
                defn = WorkflowLoader.load(filepath, self._handler_names)
            except (WorkflowValidationError, Exception) as exc:
                error_info = {
                    "file": filepath.name,
                    "error": str(exc),
                }
                self.load_errors.append(error_info)
                logger.error(
                    "Workflow load FAILED (skipping): %s — %s",
                    filepath.name, exc,
                )
                continue

            name = defn.workflow

            # Check for duplicate workflow name from a different file
            if name in self._workflows:
                existing_file = self._file_paths[name]
                error_info = {
                    "file": filepath.name,
                    "error": (
                        f"Duplicate workflow name '{name}' — "
                        f"already loaded from '{existing_file.name}'"
                    ),
                }
                self.load_errors.append(error_info)
                logger.error(
                    "Workflow load FAILED (skipping): %s — duplicate name '%s'",
                    filepath.name, name,
                )
                continue

            self._workflows[name] = defn
            self._file_paths[name] = filepath

        if self.load_errors:
            logger.warning(
                "Loaded %d workflow(s), %d failed from %s",
                len(self._workflows), len(self.load_errors), self._dir,
            )
        else:
            logger.info(
                "Loaded %d workflow(s) from %s", len(self._workflows), self._dir
            )
        return len(self._workflows)

    def _resolve_name(self, name: str) -> str:
        """Resolve a name through the alias table. Returns the canonical name."""
        return self.JOB_TYPE_ALIASES.get(name, name)

    def get(self, name: str) -> Optional[WorkflowDefinition]:
        """Return workflow definition by name (or alias), or None if not found."""
        return self._workflows.get(self._resolve_name(name))

    def get_or_raise(self, name: str) -> WorkflowDefinition:
        """Return workflow definition by name (or alias), or raise WorkflowNotFoundError."""
        defn = self._workflows.get(self._resolve_name(name))
        if defn is None:
            raise WorkflowNotFoundError(name)
        return defn

    def has(self, name: str) -> bool:
        """Check if a workflow name (or alias) is loaded."""
        return self._resolve_name(name) in self._workflows

    def list_workflows(self) -> list[str]:
        """Return sorted list of loaded workflow names."""
        return sorted(self._workflows.keys())

    def get_reverse_workflow(self, name: str) -> Optional[str]:
        """Return the reversed_by field for a workflow, or None."""
        defn = self._workflows.get(name)
        if defn is None:
            return None
        return defn.reversed_by


# =============================================================================
# MODULE-LEVEL CACHED SINGLETON
# =============================================================================

_cached_registry: Optional['WorkflowRegistry'] = None


def get_workflow_registry() -> 'WorkflowRegistry':
    """
    Return a cached WorkflowRegistry singleton.

    Loads all YAML workflows on first call. Subsequent calls return the
    same instance. All callers (DAG scheduler, API endpoints, health
    checks) share one registry instead of re-loading from disk each time.
    """
    global _cached_registry
    if _cached_registry is None:
        workflows_dir = Path(__file__).resolve().parent.parent / "workflows"
        _cached_registry = WorkflowRegistry(workflows_dir)
        _cached_registry.load_all()
        logger.info("Workflow registry cached: %d workflows", len(_cached_registry.list_workflows()))
    return _cached_registry
