# ============================================================================
# CLAUDE CONTEXT - JINJA2 TEMPLATE UTILITIES
# ============================================================================
# STATUS: Core - UI Migration Phase 1
# PURPOSE: Centralized Jinja2 configuration and template helpers
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# ============================================================================
"""
Jinja2 Template Utilities.

Provides centralized Jinja2Templates instance and helper functions
for rendering templates across all UI routers in the Docker app.

Usage:
    from templates_utils import render_template, templates

    @router.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request):
        return render_template(request, "pages/admin/health.html", data=health_data)

Exports:
    templates: Jinja2Templates instance
    get_template_context: Build standard context with common variables
    render_template: Convenience wrapper for rendering templates
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from starlette.templating import Jinja2Templates

from config import __version__, get_config

# Initialize templates directory (relative to this file)
_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)


def get_template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """
    Build a standard template context with common variables.

    Every template receives these variables automatically:
        - request: FastAPI request object (required for url_for)
        - version: Application version from config
        - nav_active: Current navigation item (for highlighting)

    Args:
        request: The FastAPI request object
        **kwargs: Additional context variables

    Returns:
        Dictionary with standard context variables plus any extras

    Example:
        context = get_template_context(request, jobs=jobs_list, nav_active="/jobs/")
    """
    config = get_config()

    context = {
        # Required by Jinja2
        "request": request,

        # Application info
        "version": __version__,
        "environment": config.environment,

        # Database info (for health displays)
        "database_host": config.database.host,

        # Feature flags (for conditional UI)
        "debug_mode": config.debug_mode,
    }
    context.update(kwargs)
    return context


def render_template(
    request: Request,
    template_name: str,
    **kwargs: Any
):
    """
    Render a Jinja2 template with standard context.

    This is the primary method for rendering UI pages. It automatically
    includes common context variables and returns a TemplateResponse.

    Args:
        request: The FastAPI request object
        template_name: Path to template file (e.g., "pages/admin/health.html")
        **kwargs: Additional context variables for the template

    Returns:
        Starlette TemplateResponse

    Example:
        @router.get("/health")
        async def health_page(request: Request):
            health_data = get_health_status()
            return render_template(
                request,
                "pages/admin/health.html",
                health=health_data,
                nav_active="/admin/health"
            )
    """
    context = get_template_context(request, **kwargs)
    return templates.TemplateResponse(template_name, context)


def render_fragment(
    request: Request,
    template_name: str,
    **kwargs: Any
):
    """
    Render an HTMX fragment template.

    Fragments are partial HTML responses for HTMX requests.
    They don't include the base layout, just the content.

    Args:
        request: The FastAPI request object
        template_name: Path to fragment template (e.g., "pages/admin/_health_status.html")
        **kwargs: Context variables for the template

    Returns:
        Starlette TemplateResponse

    Example:
        @router.get("/health/_status")
        async def health_status_fragment(request: Request):
            status = get_health_status()
            return render_fragment(request, "pages/admin/_health_status.html", status=status)
    """
    # Fragments get minimal context (no nav highlighting needed)
    context = {
        "request": request,
        "version": __version__,
    }
    context.update(kwargs)
    return templates.TemplateResponse(template_name, context)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'templates',
    'get_template_context',
    'render_template',
    'render_fragment',
]
