"""
Admin API Triggers Package.

Centralized admin API endpoints under /api/admin/* for APIM access control.

Exports:
    Database Admin Triggers (Phase 1)
    Service Bus Admin Triggers (Phase 2)
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

# Phase 3: Admin Blueprints (moved from routes/ - 02 JAN 2026)
from triggers.admin.admin_db import bp as admin_db_bp
from triggers.admin.admin_servicebus import bp as admin_servicebus_bp

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
    # Phase 3: Admin Blueprints
    'admin_db_bp',
    'admin_servicebus_bp',
]
