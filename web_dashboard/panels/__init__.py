# ============================================================================
# CLAUDE CONTEXT - PANELS_PACKAGE_INIT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Package init - Auto-imports all panel modules to trigger registration
# PURPOSE: Ensure all panels are registered with PanelRegistry on import
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: None (side effect: panel registration)
# DEPENDENCIES: pkgutil, importlib
# ============================================================================
"""
Dashboard panels package.

Auto-imports all panel modules in this directory to trigger their
@PanelRegistry.register decorators. This mirrors the pattern from
web_interfaces/__init__.py.
"""

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

_SKIP_MODULES = {"__pycache__"}

for _importer, _module_name, _is_pkg in pkgutil.iter_modules(__path__):
    if _module_name in _SKIP_MODULES:
        continue
    try:
        importlib.import_module(f".{_module_name}", package=__name__)
        logger.info(f"Imported dashboard panel module: {_module_name}")
    except Exception as e:
        logger.warning(f"Could not import dashboard panel '{_module_name}': {e}")
