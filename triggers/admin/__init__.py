# ============================================================================
# ADMIN API TRIGGERS PACKAGE
# ============================================================================
# STATUS: Trigger layer - Package init for admin API endpoints
# PURPOSE: Export centralized admin API endpoints under /api/admin/*
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AdminDb*Trigger, ServiceBusAdminTrigger, SnapshotAdminTrigger
# ============================================================================
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

# Phase 4: System Snapshot Blueprint (04 JAN 2026)
from triggers.admin.snapshot import bp as snapshot_bp, SnapshotAdminTrigger, snapshot_admin_trigger

# Phase 5: Consolidated Admin Blueprints (12 JAN 2026)
from triggers.admin.admin_janitor import bp as admin_janitor_bp
# NOTE: admin_stac_bp moved to triggers/stac/stac_bp.py (24 JAN 2026 - V0.8 Phase 17.3)
# NOTE: admin_h3_bp archived (13 FEB 2026) → docs/archive/v08_archive_feb2026/triggers/
from triggers.admin.admin_system import bp as admin_system_bp

# Phase 6: External Database Admin Blueprint (21 JAN 2026)
from triggers.admin.admin_external_db import bp as admin_external_db_bp

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
    # Phase 4: System Snapshot (04 JAN 2026)
    'snapshot_bp',
    'SnapshotAdminTrigger',
    'snapshot_admin_trigger',
    # Phase 5: Consolidated Admin Blueprints (12 JAN 2026)
    'admin_janitor_bp',
    # NOTE: admin_stac_bp moved to triggers/stac/stac_bp.py (24 JAN 2026)
    # NOTE: admin_h3_bp archived (13 FEB 2026)
    'admin_system_bp',
    # Phase 6: External Database Admin Blueprint (21 JAN 2026)
    'admin_external_db_bp',
]
