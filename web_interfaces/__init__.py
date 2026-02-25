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
import html
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

    # Redirect to home if no interface specified
    if not interface_name:
        return func.HttpResponse(
            body="",
            status_code=302,
            headers={"Location": "/api/interface/home"}
        )

    # Backward-compatible aliases (24 FEB 2026)
    _ALIASES = {'tasks': 'status'}
    if interface_name in _ALIASES:
        alias_target = _ALIASES[interface_name]
        # Preserve query params in redirect
        qs = req.url.split('?', 1)[1] if '?' in req.url else ''
        redirect_url = f"/api/interface/{alias_target}" + (f"?{qs}" if qs else "")
        return func.HttpResponse(
            body="",
            status_code=302,
            headers={"Location": redirect_url}
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

        # Check for embed mode (for iframe integration) - 02 FEB 2026
        embed_mode = req.params.get('embed', '').lower() == 'true'
        if embed_mode:
            interface.embed_mode = True
            logger.info(f"📦 Embed mode enabled for: {interface_name}")

        # Check for HTMX partial request
        is_htmx = req.headers.get('HX-Request') == 'true'
        fragment = req.params.get('fragment')

        if fragment:
            # HTMX partial update - return HTML fragment
            source = "HTMX" if is_htmx else "fragment param"
            logger.info(f"🔄 {source} partial: {interface_name}/{fragment}")
            html = interface.htmx_partial(req, fragment)

            return func.HttpResponse(
                html,
                mimetype="text/html",
                status_code=200,
                headers={"Content-Security-Policy": "frame-ancestors *"}
            )

        # Full page render
        logger.info(f"🌐 Rendering interface: {interface_name}")
        html = interface.render(req)

        logger.info(f"✅ Successfully rendered interface: {interface_name}")

        # Response headers - allow iframe embedding (02 FEB 2026)
        # frame-ancestors * allows any domain to embed this interface
        # To restrict: "frame-ancestors 'self' https://trusted-domain.com"
        response_headers = {
            "Content-Security-Policy": "frame-ancestors *"
        }

        return func.HttpResponse(
            html,
            mimetype="text/html",
            status_code=200,
            headers=response_headers
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
            <title>Error - {html.escape(str(interface_name))}</title>
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
                <p><strong>Interface:</strong> {html.escape(str(interface_name))}</p>
                <p><strong>Error:</strong></p>
                <pre>{html.escape(str(e))}</pre>
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


# Auto-import all interface modules to trigger @InterfaceRegistry.register() decorators.
# Uses pkgutil auto-discovery instead of manual try/except per module.
import importlib
import pkgutil

_SKIP_MODULES = {'__pycache__'}

for _importer, _module_name, _is_pkg in pkgutil.iter_modules(__path__):
    if _module_name in _SKIP_MODULES:
        continue
    try:
        importlib.import_module(f'.{_module_name}.interface', package=__name__)
        logger.info(f"Imported {_module_name} interface module")
    except (ImportError, ModuleNotFoundError):
        # Module doesn't follow the .interface convention — skip silently
        pass
    except Exception as e:
        logger.warning(f"Could not import {_module_name} interface: {e}")


# Public API
__all__ = [
    'BaseInterface',
    'InterfaceRegistry',
    'unified_interface_handler'
]
