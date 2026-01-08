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

    Supports both full page renders and HTMX partial updates.
    HTMX requests (with HX-Request header) are routed to htmx_partial()
    with the 'fragment' query parameter specifying which partial to render.

    Args:
        req: Azure Functions HttpRequest object

    Returns:
        HttpResponse with HTML content or error message

    Examples:
        GET /api/interface/stac                          # Full page
        GET /api/interface/storage                       # Full page
        GET /api/interface/storage?fragment=containers&zone=bronze  # HTMX partial
        GET /api/interface/storage?fragment=files&container=foo     # HTMX partial

    Error Responses:
        400: Missing interface name or invalid fragment
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
        # Instantiate interface
        interface = interface_class()

        # Check for HTMX partial request
        is_htmx = req.headers.get('HX-Request') == 'true'
        fragment = req.params.get('fragment')

        if is_htmx and fragment:
            # HTMX partial update - return HTML fragment
            logger.info(f"🔄 HTMX partial: {interface_name}/{fragment}")
            html = interface.htmx_partial(req, fragment)

            return func.HttpResponse(
                html,
                mimetype="text/html",
                status_code=200
            )

        # Full page render
        logger.info(f"🌐 Rendering interface: {interface_name}")
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
    from .storage import interface as _storage
    logger.info("✅ Imported Storage interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Storage interface: {e}")

try:
    from .pipeline import interface as _pipeline
    logger.info("✅ Imported Pipeline interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Pipeline interface: {e}")

try:
    from .health import interface as _health
    logger.info("✅ Imported Health interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Health interface: {e}")

try:
    from .map import interface as _map
    logger.info("✅ Imported Map interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Map interface: {e}")

try:
    from .h3 import interface as _h3
    logger.info("✅ Imported H3 interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import H3 interface: {e}")

try:
    from .queues import interface as _queues
    logger.info("✅ Imported Queues interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Queues interface: {e}")

try:
    from .zarr import interface as _zarr
    logger.info("✅ Imported Zarr interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Zarr interface: {e}")

try:
    from .gallery import interface as _gallery
    logger.info("✅ Imported Gallery interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Gallery interface: {e}")

try:
    from .swagger import interface as _swagger
    logger.info("✅ Imported Swagger interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Swagger interface: {e}")

try:
    from .stac_map import interface as _stac_map
    logger.info("✅ Imported STAC Map interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import STAC Map interface: {e}")

try:
    from .submit_vector import interface as _submit_vector
    logger.info("✅ Imported Submit Vector interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Submit Vector interface: {e}")

try:
    from .promote_vector import interface as _promote_vector
    logger.info("✅ Imported Promote Vector interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Promote Vector interface: {e}")

try:
    from .submit_raster import interface as _submit_raster
    logger.info("✅ Imported Submit Raster interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Submit Raster interface: {e}")

try:
    from .raster_viewer import interface as _raster_viewer
    logger.info("✅ Imported Raster Viewer interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Raster Viewer interface: {e}")

try:
    from .metrics import interface as _metrics
    logger.info("✅ Imported Metrics interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Metrics interface: {e}")

try:
    from .execution import interface as _execution
    logger.info("✅ Imported Execution interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Execution interface: {e}")

try:
    from .promoted_viewer import interface as _promoted_viewer
    logger.info("✅ Imported Promoted Viewer interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Promoted Viewer interface: {e}")

try:
    from .submit_raster_collection import interface as _submit_raster_collection
    logger.info("✅ Imported Submit Raster Collection interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Submit Raster Collection interface: {e}")

try:
    from .database import interface as _database
    logger.info("✅ Imported Database interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import Database interface: {e}")

try:
    from .stac_collection import interface as _stac_collection
    logger.info("✅ Imported STAC Collection interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import STAC Collection interface: {e}")

try:
    from .fathom_viewer import interface as _fathom_viewer
    logger.info("✅ Imported FATHOM Viewer interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import FATHOM Viewer interface: {e}")

try:
    from .h3_map import interface as _h3_map
    logger.info("✅ Imported H3 Map interface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import H3 Map interface: {e}")


# Public API
__all__ = [
    'BaseInterface',
    'InterfaceRegistry',
    'unified_interface_handler'
]
