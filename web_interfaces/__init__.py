"""
Web interfaces registry module.

Central registry for all web interface modules with decorator-based registration
and dynamic interface loading by name.

Exports:
    InterfaceRegistry: Registry class with decorator pattern for interface registration
    BaseInterface: Base class for all web interfaces
    unified_interface_handler: HTTP handler for /api/interface/{name} route
"""

from typing import Dict, Type, Optional, List
import azure.functions as func
import logging

from .base import BaseInterface

logger = logging.getLogger(__name__)


class InterfaceRegistry:
    """
    Registry for all web interfaces.

    Provides decorator-based registration and dynamic loading of interface
    modules by name.

    Example:
        @InterfaceRegistry.register('myinterface')
        class MyInterface(BaseInterface):
            def render(self, request):
                return self.wrap_html("Title", "<h1>Hello</h1>")

        # Now /api/interface/myinterface works automatically.
    """

    # Class-level storage for registered interfaces
    _interfaces: Dict[str, Type[BaseInterface]] = {}

    @classmethod
    def register(cls, name: str):
        """
        Decorator to register an interface.

        Args:
            name: Interface name (used in URL: /api/interface/{name})

        Returns:
            Decorator function

        Raises:
            ValueError: If interface name already registered

        Example:
            @InterfaceRegistry.register('stac')
            class StacInterface(BaseInterface):
                def render(self, request):
                    return self.wrap_html("STAC", "<h1>STAC Dashboard</h1>")
        """
        def decorator(interface_class: Type[BaseInterface]):
            # Check for duplicate registration
            if name in cls._interfaces:
                existing = cls._interfaces[name]
                logger.warning(
                    f"Interface '{name}' already registered "
                    f"({existing.__name__}), overwriting with {interface_class.__name__}"
                )

            # Register interface
            cls._interfaces[name] = interface_class
            logger.info(f"✅ Registered interface: '{name}' -> {interface_class.__name__}")

            return interface_class

        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseInterface]]:
        """
        Get interface class by name.

        Args:
            name: Interface name

        Returns:
            Interface class or None if not found

        Example:
            interface_class = InterfaceRegistry.get('stac')
            if interface_class:
                interface = interface_class()
                html = interface.render(request)
        """
        return cls._interfaces.get(name)

    @classmethod
    def list_all(cls) -> List[str]:
        """
        List all registered interface names.

        Returns:
            List of interface names

        Example:
            names = InterfaceRegistry.list_all()
            # ['stac', 'vector', 'jobs', 'docs']
        """
        return list(cls._interfaces.keys())

    @classmethod
    def get_all(cls) -> Dict[str, Type[BaseInterface]]:
        """
        Get all registered interfaces.

        Returns:
            Dictionary mapping interface names to interface classes
        """
        return cls._interfaces.copy()


def unified_interface_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified HTTP handler for all web interfaces.

    Route: /api/interface/{name}

    Args:
        req: Azure Functions HttpRequest object

    Returns:
        HttpResponse with HTML content or error message

    Examples:
        GET /api/interface/stac
        GET /api/interface/vector?collection=test_geojson_fresh
        GET /api/interface/jobs
        GET /api/interface/docs

    Error Responses:
        400: Missing interface name
        404: Interface not found
        500: Error rendering interface
    """
    # Get interface name from route parameter
    interface_name = req.route_params.get('name')

    if not interface_name:
        available = ", ".join(InterfaceRegistry.list_all())
        return func.HttpResponse(
            f"❌ Missing interface name.\n\n"
            f"Available interfaces: {available}\n\n"
            f"Usage: /api/interface/{{name}}\n"
            f"Example: /api/interface/stac",
            status_code=400,
            mimetype="text/plain"
        )

    # Get interface class from registry
    interface_class = InterfaceRegistry.get(interface_name)

    if not interface_class:
        available = ", ".join(InterfaceRegistry.list_all())
        return func.HttpResponse(
            f"❌ Interface '{interface_name}' not found.\n\n"
            f"Available interfaces: {available}\n\n"
            f"Did you mean one of these?\n" +
            "\n".join(f"  • /api/interface/{name}" for name in InterfaceRegistry.list_all()),
            status_code=404,
            mimetype="text/plain"
        )

    try:
        logger.info(f"🌐 Rendering interface: {interface_name}")

        # Instantiate interface and render HTML
        interface = interface_class()
        html = interface.render(req)

        logger.info(f"✅ Successfully rendered interface: {interface_name}")

        return func.HttpResponse(
            html,
            mimetype="text/html",
            status_code=200
        )

    except Exception as e:
        logger.error(
            f"❌ Error rendering interface '{interface_name}': {e}",
            exc_info=True
        )

        # Return user-friendly error page
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - {interface_name}</title>
            <style>
                body {{
                    font-family: sans-serif;
                    background: #fee;
                    padding: 40px;
                    text-align: center;
                }}
                .error-box {{
                    background: white;
                    border: 2px solid #c33;
                    border-radius: 8px;
                    padding: 30px;
                    max-width: 600px;
                    margin: 0 auto;
                }}
                h1 {{ color: #c33; }}
                pre {{
                    background: #f5f5f5;
                    padding: 15px;
                    border-radius: 4px;
                    text-align: left;
                    overflow-x: auto;
                }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <h1>❌ Error Rendering Interface</h1>
                <p><strong>Interface:</strong> {interface_name}</p>
                <p><strong>Error:</strong></p>
                <pre>{str(e)}</pre>
                <p><a href="/api/interface/stac">← Back to interfaces</a></p>
            </div>
        </body>
        </html>
        """

        return func.HttpResponse(
            error_html,
            mimetype="text/html",
            status_code=500
        )


# Auto-import all interface modules to trigger registration
# These imports cause the @InterfaceRegistry.register() decorators to execute
try:
    from .home import interface as _home
    logger.info("✅ Imported Home interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Home interface: {e}")

try:
    from .stac import interface as _stac
    logger.info("✅ Imported STAC interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import STAC interface: {e}")

try:
    from .vector import interface as _vector
    logger.info("✅ Imported Vector interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Vector interface: {e}")

try:
    from .jobs import interface as _jobs
    logger.info("✅ Imported Jobs interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Jobs interface: {e}")

try:
    from .docs import interface as _docs
    logger.info("✅ Imported Docs interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Docs interface: {e}")

try:
    from .tasks import interface as _tasks
    logger.info("✅ Imported Tasks interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Tasks interface: {e}")

try:
    from .pipeline import interface as _pipeline
    logger.info("✅ Imported Pipeline interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Pipeline interface: {e}")


# Public API
__all__ = [
    'BaseInterface',
    'InterfaceRegistry',
    'unified_interface_handler'
]
