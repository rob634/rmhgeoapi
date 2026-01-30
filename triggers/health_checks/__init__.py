# ============================================================================
# HEALTH CHECK PLUGINS REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Plugin registry and exports
# PURPOSE: Central registry for health check plugins
# CREATED: 29 JAN 2026
# EXPORTS: get_all_plugins, HEALTH_CHECK_PLUGINS, plugin classes
# DEPENDENCIES: Plugin modules
# ============================================================================
"""
Health Check Plugins Registry.

Provides centralized registration and discovery of health check plugins.
Plugins are ordered by priority (lower = runs earlier).

Usage:
    from triggers.health_checks import get_all_plugins

    plugins = get_all_plugins(logger=my_logger)
    for plugin in plugins:
        for name, check_method in plugin.get_checks():
            result = check_method()

Adding a new plugin:
    1. Create a new file (e.g., my_checks.py) with class extending HealthCheckPlugin
    2. Import it here
    3. Add to HEALTH_CHECK_PLUGINS list
"""

from typing import List, Type

from .base import HealthCheckPlugin
from .startup import StartupHealthChecks
from .application import ApplicationHealthChecks
from .infrastructure import InfrastructureHealthChecks
from .database import DatabaseHealthChecks
from .external_services import ExternalServicesHealthChecks


# ============================================================================
# PLUGIN REGISTRY
# ============================================================================
# Ordered list of plugins by priority (lower priority number = runs earlier)
# During migration, plugins return empty check lists until methods are moved

HEALTH_CHECK_PLUGINS: List[Type[HealthCheckPlugin]] = [
    StartupHealthChecks,           # Priority 10 - Run first
    ApplicationHealthChecks,       # Priority 20
    InfrastructureHealthChecks,    # Priority 30
    DatabaseHealthChecks,          # Priority 40
    ExternalServicesHealthChecks,  # Priority 50 - Run last (parallel HTTP)
]


def get_all_plugins(logger=None) -> List[HealthCheckPlugin]:
    """
    Instantiate all registered plugins.

    Args:
        logger: Optional logger instance for error reporting

    Returns:
        List of instantiated HealthCheckPlugin objects, sorted by priority
    """
    plugins = [plugin_class(logger=logger) for plugin_class in HEALTH_CHECK_PLUGINS]
    # Sort by priority (lower = earlier)
    return sorted(plugins, key=lambda p: p.priority)


def get_enabled_plugins(config, logger=None) -> List[HealthCheckPlugin]:
    """
    Get only plugins that are enabled for the given config.

    Args:
        config: AppConfig instance
        logger: Optional logger instance

    Returns:
        List of enabled HealthCheckPlugin objects, sorted by priority
    """
    all_plugins = get_all_plugins(logger=logger)
    return [p for p in all_plugins if p.is_enabled(config)]


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Base class
    'HealthCheckPlugin',

    # Registry
    'HEALTH_CHECK_PLUGINS',
    'get_all_plugins',
    'get_enabled_plugins',

    # Plugin classes (for direct import if needed)
    'StartupHealthChecks',
    'ApplicationHealthChecks',
    'InfrastructureHealthChecks',
    'DatabaseHealthChecks',
    'ExternalServicesHealthChecks',
]
