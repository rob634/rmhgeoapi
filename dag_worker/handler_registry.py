# ============================================================================
# DAG HANDLER REGISTRY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Handler name → function mapping
# PURPOSE: Look up handler functions by name
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Handler Registry

Maps handler names (strings from workflow YAML) to Python functions.

Usage:
    from dag_worker.handler_registry import get_handler, register_handler

    # Register a handler
    @register_handler("my_handler")
    def my_handler(params: dict) -> dict:
        return {"result": "success"}

    # Look up and call
    handler = get_handler("my_handler")
    result = await handler({"input": "value"})

Integration with Existing Handlers:
    This registry imports existing handler functions from the rmhgeoapi
    codebase and registers them by name. The actual handler implementations
    live in services/handler_*.py - we just create a lookup table.
"""

import logging
from typing import Any, Callable, Dict, Optional, Union
from functools import wraps

logger = logging.getLogger(__name__)

# Type for handler functions
# Handlers can be sync or async, take params dict, return dict
HandlerFunc = Callable[[Dict[str, Any]], Union[Dict[str, Any], Any]]

# Global registry
_REGISTRY: Dict[str, HandlerFunc] = {}


def register_handler(name: str):
    """
    Decorator to register a handler function.

    Args:
        name: Handler name (used in workflow YAML)

    Usage:
        @register_handler("raster_validate")
        async def raster_validate(params: dict) -> dict:
            ...
    """
    def decorator(func: HandlerFunc) -> HandlerFunc:
        if name in _REGISTRY:
            logger.warning(f"Handler '{name}' already registered, overwriting")
        _REGISTRY[name] = func
        logger.debug(f"Registered handler: {name}")
        return func
    return decorator


def get_handler(name: str) -> HandlerFunc:
    """
    Look up a handler by name.

    Args:
        name: Handler name

    Returns:
        Handler function

    Raises:
        KeyError if handler not found
    """
    if name not in _REGISTRY:
        available = list(_REGISTRY.keys())
        raise KeyError(
            f"Unknown handler: '{name}'. "
            f"Available handlers: {available}"
        )
    return _REGISTRY[name]


def has_handler(name: str) -> bool:
    """Check if a handler is registered."""
    return name in _REGISTRY


def list_handlers() -> list[str]:
    """List all registered handler names."""
    return list(_REGISTRY.keys())


def clear_registry() -> None:
    """Clear all registered handlers (for testing)."""
    _REGISTRY.clear()


# ============================================================================
# BUILT-IN HANDLERS
# ============================================================================
# These are simple handlers for testing. Real handlers are imported below.

@register_handler("echo")
async def echo_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Echo handler - returns input params as output.

    Useful for testing the orchestrator without real processing.
    """
    logger.info(f"Echo handler called with: {params}")
    return {
        "echoed": True,
        "input": params,
        "message": params.get("message", "no message"),
    }


@register_handler("sleep")
async def sleep_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sleep handler - waits for specified seconds.

    Useful for testing timeouts and long-running tasks.

    Params:
        seconds: How long to sleep (default: 5)
    """
    import asyncio

    seconds = params.get("seconds", 5)
    logger.info(f"Sleep handler: sleeping for {seconds} seconds")
    await asyncio.sleep(seconds)

    return {
        "slept_seconds": seconds,
    }


@register_handler("fail")
async def fail_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fail handler - always raises an exception.

    Useful for testing error handling.
    """
    message = params.get("message", "Intentional failure for testing")
    raise RuntimeError(message)


# ============================================================================
# IMPORT EXISTING HANDLERS
# ============================================================================
# Import and register existing handler functions from rmhgeoapi.
# These imports are wrapped in try/except to allow the module to load
# even if some handlers aren't available.

def _import_existing_handlers():
    """
    Import existing handlers from rmhgeoapi services.

    This function is called at module load time to populate the registry
    with existing handler implementations.
    """
    # TODO: Import actual handlers from services/handler_*.py
    # Example:
    #
    # try:
    #     from services.handler_raster_validate import raster_validate
    #     _REGISTRY["raster_validate"] = raster_validate
    # except ImportError as e:
    #     logger.warning(f"Could not import raster_validate: {e}")
    #
    # For now, we just log that this is where imports would go.

    logger.info(
        "DAG handler registry initialized. "
        f"Built-in handlers: {list_handlers()}"
    )


# Run imports at module load
_import_existing_handlers()
