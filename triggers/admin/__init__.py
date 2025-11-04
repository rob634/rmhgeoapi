# ============================================================================
# CLAUDE CONTEXT - ADMIN TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - HTTP triggers for administrative operations
# PURPOSE: Centralized admin API endpoints under /api/admin/* for APIM access control
# LAST_REVIEWED: 03 NOV 2025
# EXPORTS: AdminDbSchemasTrigger, AdminDbTablesTrigger, AdminDbQueriesTrigger, AdminDbHealthTrigger, AdminDbMaintenanceTrigger
# INTERFACES: Azure Functions HTTP triggers
# PYDANTIC_MODELS: None - uses dict responses for admin operations
# DEPENDENCIES: azure.functions, infrastructure.*, util_logger
# SOURCE: PostgreSQL database, Service Bus, Blob Storage for admin inspection
# SCOPE: Admin-level visibility and operations for monitoring and debugging
# VALIDATION: Authorization required for all endpoints (future APIM integration)
# PATTERNS: Single path consolidation (/api/admin/*), RESTful admin operations
# ENTRY_POINTS: from triggers.admin import AdminDbSchemasTrigger
# INDEX: Exports below
# ============================================================================

"""
Admin API Triggers Package

Consolidates all administrative endpoints under /api/admin/* for simplified
APIM access control. Designed for monitoring applications and AI agents that
maintain and troubleshoot the system.

Architecture:
- Single APIM policy path: /api/admin/*
- Phase 1: Database Admin API (PostgreSQL schemas)
- Phase 2: STAC Admin API (pgstac schema)
- Phase 3: Service Bus Admin API (queue inspection)
- Phase 4: Storage Admin API (blob containers)
- Phase 5: Registry & Discovery API (jobs/handlers)
- Phase 6: Traces & Execution Analysis
- Phase 7: System-Wide Operations

Author: Robert and Geospatial Claude Legion
Date: 03 NOV 2025
"""

# Phase 1: Database Admin API
from triggers.admin.db_schemas import AdminDbSchemasTrigger
from triggers.admin.db_tables import AdminDbTablesTrigger
from triggers.admin.db_queries import AdminDbQueriesTrigger
from triggers.admin.db_health import AdminDbHealthTrigger
from triggers.admin.db_maintenance import AdminDbMaintenanceTrigger

# Export all admin triggers
__all__ = [
    # Phase 1: Database Admin
    'AdminDbSchemasTrigger',
    'AdminDbTablesTrigger',
    'AdminDbQueriesTrigger',
    'AdminDbHealthTrigger',
    'AdminDbMaintenanceTrigger',
]
