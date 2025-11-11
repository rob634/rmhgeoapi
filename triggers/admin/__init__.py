# ============================================================================
# CLAUDE CONTEXT - ADMIN TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - HTTP triggers for administrative operations
# PURPOSE: Centralized admin API endpoints under /api/admin/* for APIM access control
# LAST_REVIEWED: 04 NOV 2025
# EXPORTS: AdminDbSchemasTrigger, AdminDbTablesTrigger, AdminDbQueriesTrigger, AdminDbHealthTrigger, AdminDbMaintenanceTrigger, ServiceBusAdminTrigger
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
- Phase 1: Database Admin API (PostgreSQL schemas) ✅ COMPLETE
- Phase 2: Service Bus Admin API (queue inspection) ✅ COMPLETE
- Phase 3: STAC Admin API (pgstac schema) - Future
- Phase 4: Storage Admin API (blob containers) - Future
- Phase 5: Registry & Discovery API (jobs/handlers) - Future
- Phase 6: Traces & Execution Analysis - Future
- Phase 7: System-Wide Operations - Future

Author: Robert and Geospatial Claude Legion
Date: 04 NOV 2025
"""

# Phase 1: Database Admin API ✅ COMPLETE (including legacy migration - 10 NOV 2025)
from triggers.admin.db_schemas import AdminDbSchemasTrigger, admin_db_schemas_trigger
from triggers.admin.db_tables import AdminDbTablesTrigger, admin_db_tables_trigger
from triggers.admin.db_queries import AdminDbQueriesTrigger, admin_db_queries_trigger
from triggers.admin.db_health import AdminDbHealthTrigger, admin_db_health_trigger
from triggers.admin.db_maintenance import AdminDbMaintenanceTrigger, admin_db_maintenance_trigger
from triggers.admin.db_data import AdminDbDataTrigger, admin_db_data_trigger
from triggers.admin.db_diagnostics import AdminDbDiagnosticsTrigger, admin_db_diagnostics_trigger

# Phase 2: Service Bus Admin API ✅ COMPLETE
from triggers.admin.servicebus import ServiceBusAdminTrigger, servicebus_admin_trigger

# Export all admin triggers
__all__ = [
    # Phase 1: Database Admin - Classes
    'AdminDbSchemasTrigger',
    'AdminDbTablesTrigger',
    'AdminDbQueriesTrigger',
    'AdminDbHealthTrigger',
    'AdminDbMaintenanceTrigger',
    'AdminDbDataTrigger',
    'AdminDbDiagnosticsTrigger',
    # Phase 1: Database Admin - Instances
    'admin_db_schemas_trigger',
    'admin_db_tables_trigger',
    'admin_db_queries_trigger',
    'admin_db_health_trigger',
    'admin_db_maintenance_trigger',
    'admin_db_data_trigger',
    'admin_db_diagnostics_trigger',
    # Phase 2: Service Bus Admin - Class & Instance
    'ServiceBusAdminTrigger',
    'servicebus_admin_trigger',
]
