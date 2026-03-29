"""
Preflight check registry — mode-aware filtering.

Each check declares which APP_MODEs require it. The registry
returns only checks relevant to the current deployment.
"""

from typing import List

from config.app_mode_config import AppMode
from .base import PreflightCheck
from .environment import EnvironmentCheck
from .database import (
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
)
from .dag import DAGLeaseCheck, WorkflowRegistryCheck, DAGTablesCheck
from .storage import StorageTokenCheck, BlobCRUDCheck
from .runtime import HandlerImportsCheck, GDALVersionCheck, MountWriteCheck

# Execution order = registration order.
ALL_PREFLIGHT_CHECKS: List[type] = [
    # Tier 1: Environment (fast, no I/O)
    EnvironmentCheck,
    # Tier 2: Database (needs DB connection)
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
    # Tier 3: DAG infrastructure
    DAGLeaseCheck,
    WorkflowRegistryCheck,
    DAGTablesCheck,
    # Tier 4: Storage (needs blob credentials)
    StorageTokenCheck,
    BlobCRUDCheck,
    # Tier 5: Runtime (needs libraries + mount)
    HandlerImportsCheck,
    GDALVersionCheck,
    MountWriteCheck,
]


def get_checks_for_mode(
    mode: AppMode,
    docker_worker_enabled: bool = False,
) -> List[PreflightCheck]:
    """Instantiate and filter checks for the given APP_MODE."""
    checks = []
    for cls in ALL_PREFLIGHT_CHECKS:
        instance = cls()
        if instance.is_required(mode, docker_worker_enabled):
            checks.append(instance)
    return checks
