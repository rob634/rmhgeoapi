# ============================================================================
# CLAUDE CONTEXT - PANEL_REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Registry - Decorator-based panel auto-discovery
# PURPOSE: Central registry for dashboard panels with self-describing registration
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: PanelRegistry
# DEPENDENCIES: None (stdlib only)
# ============================================================================
"""
Panel registry for the platform dashboard.

Provides decorator-based registration and dynamic loading of panel modules
by tab name. Mirrors the InterfaceRegistry pattern from web_interfaces/
but uses a self-describing decorator (no argument -- the class provides
its own tab_name via the abstract method).

Exports:
    PanelRegistry: Registry class with @register decorator
"""

from typing import Dict, Type, Optional, List
import logging

logger = logging.getLogger(__name__)


class PanelRegistry:
    """
    Registry for all dashboard panels.

    Uses a self-describing decorator pattern: the panel class provides
    its own tab_name() so the decorator needs no argument. This prevents
    name drift between the registry key and the class's identity.

    Example:
        @PanelRegistry.register
        class PlatformPanel(BasePanel):
            def tab_name(self) -> str:
                return 'platform'
            ...

        # Now PanelRegistry.get('platform') returns PlatformPanel
    """

    _panels: Dict[str, Type] = {}

    @classmethod
    def register(cls, panel_class: Type) -> Type:
        """
        Decorator to register a panel class.

        The panel must implement tab_name() which returns the URL key.
        No decorator argument needed -- the class self-describes.

        Args:
            panel_class: Panel class to register (must have tab_name method)

        Returns:
            The panel class (unchanged)

        Raises:
            AttributeError: If panel_class has no tab_name method
        """
        # Instantiate temporarily to get the tab name
        instance = panel_class()
        name = instance.tab_name()

        if name in cls._panels:
            existing = cls._panels[name]
            logger.warning(
                f"Panel '{name}' already registered "
                f"({existing.__name__}), overwriting with {panel_class.__name__}"
            )

        cls._panels[name] = panel_class
        logger.info(f"Registered dashboard panel: '{name}' -> {panel_class.__name__}")

        return panel_class

    @classmethod
    def get(cls, name: str) -> Optional[Type]:
        """
        Get panel class by tab name.

        Args:
            name: Tab name (e.g., 'platform', 'jobs')

        Returns:
            Panel class or None if not found
        """
        return cls._panels.get(name)

    @classmethod
    def list_panels(cls) -> List[str]:
        """
        List all registered panel tab names in registration order.

        Returns:
            List of tab name strings
        """
        return list(cls._panels.keys())

    @classmethod
    def get_all(cls) -> Dict[str, Type]:
        """
        Get all registered panels.

        Returns:
            Dictionary mapping tab names to panel classes
        """
        return cls._panels.copy()

    @classmethod
    def get_ordered(cls) -> list:
        """
        Get all panels as instances, ordered by their tab_order property.

        Returns:
            List of (tab_name, panel_instance) tuples sorted by tab_order
        """
        panels = []
        for name, panel_class in cls._panels.items():
            instance = panel_class()
            order = getattr(instance, 'tab_order', 99)
            panels.append((order, name, instance))
        panels.sort(key=lambda x: x[0])
        return [(name, inst) for _, name, inst in panels]
