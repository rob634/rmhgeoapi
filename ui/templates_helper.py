"""
Jinja2 Template Utilities for DAG Brain Admin UI.

Provides Jinja2Templates instance and render helpers.
Adapted from archive/docker_ui/ui/templates.py for the DAG Brain.
"""
from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from config import __version__
from ui.terminology import get_terms
from ui.features import get_enabled_features
from ui.navigation import get_nav_items, get_nav_sections

# Templates directory is at project root level
_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)


def get_template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """Build standard template context with common variables."""
    context = {
        "request": request,
        "version": __version__,
        "terms": get_terms(),
        "features": get_enabled_features(),
        "nav_items": get_nav_items(),
        "nav_sections": get_nav_sections(),
        "nav_active": kwargs.pop("nav_active", None),
    }
    context.update(kwargs)
    return context


def render_template(request: Request, template_name: str, **kwargs: Any) -> Response:
    """Render a Jinja2 template with standard context."""
    context = get_template_context(request, **kwargs)
    return templates.TemplateResponse(request, template_name, context=context)


def render_fragment(request: Request, template_name: str, **kwargs: Any) -> Response:
    """Render an HTMX fragment (no base layout)."""
    context = {"request": request, "version": __version__}
    context.update(kwargs)
    return templates.TemplateResponse(request, template_name, context=context)
