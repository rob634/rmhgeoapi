"""
Routes module - Azure Functions Blueprint definitions.

This module contains Blueprint definitions for organizing routes into logical groups.
Each Blueprint can be registered with the main FunctionApp.

Structure (15 DEC 2025):
    admin_db.py         - Database admin endpoints (dbadmin/*)
    admin_servicebus.py - Service Bus admin endpoints (servicebus/*)

Future:
    core.py             - Core endpoints (health, jobs)
    platform.py         - Platform layer endpoints
    stac.py             - STAC API endpoints
    ogc_features.py     - OGC Features API endpoints
    curated.py          - Curated datasets endpoints
"""

from .admin_db import bp as admin_db_bp
from .admin_servicebus import bp as admin_servicebus_bp

__all__ = [
    'admin_db_bp',
    'admin_servicebus_bp',
]
