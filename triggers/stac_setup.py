# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC/PgSTAC infrastructure management
# PURPOSE: STAC setup and status HTTP endpoints for PgSTAC installation management
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: stac_setup_trigger (StacSetupTrigger instance), StacSetupTrigger
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None (uses dict responses)
# DEPENDENCIES: http_base.BaseHttpTrigger, infrastructure.stac, util_logger
# SOURCE: HTTP GET/POST requests to /api/stac/setup
# SCOPE: STAC infrastructure management - PgSTAC installation, status, verification
# VALIDATION: Installation status checks, confirmation parameters (confirm=yes), destructive operation checks (drop=true)
# PATTERNS: Template Method (base class), Infrastructure delegation, Idempotent operations
# ENTRY_POINTS: GET /api/stac/setup (status), POST /api/stac/setup?confirm=yes (install)
# INDEX: StacSetupTrigger:48, process_request:78, _handle_status:128, _handle_install:188
# ============================================================================

"""
STAC Setup HTTP Trigger

Provides HTTP endpoints for PgSTAC installation and status checking.
This is the user-facing API for STAC infrastructure management.

PgSTAC (PostgreSQL STAC) provides a PostgreSQL-native implementation of the
SpatioTemporal Asset Catalog (STAC) specification for managing geospatial assets.

Endpoints:
- GET  /api/stac/setup              - Check STAC installation status
- GET  /api/stac/setup?verify       - Full verification of STAC installation
- POST /api/stac/setup?confirm=yes  - Install PgSTAC (safe if already installed)
- POST /api/stac/setup?confirm=yes&drop=true - Reinstall PgSTAC (⚠️ DROPS EXISTING DATA)

Safety Features:
- Installation requires explicit confirmation (confirm=yes)
- Drop operation requires additional parameter (drop=true)
- Read-only operations (GET) are always safe
- All operations are idempotent (safe to repeat)
- Transactional installation (rollback on error)

Installation Process:
1. Check if PgSTAC is already installed
2. Create pgstac extension in PostgreSQL
3. Create STAC tables and indexes (items, collections, etc.)
4. Verify installation with test queries
5. Return detailed status report

Status Checks:
- Extension installed (pgstac)
- Tables created (items, collections, searches)
- Indexes present
- Functions available
- Sample data accessible

Last Updated: 29 OCT 2025
"""

import azure.functions as func
from typing import Dict, Any, List

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType
from infrastructure.pgstac_bootstrap import PgStacBootstrap, check_stac_installation, install_stac

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "StacSetupTrigger")


class StacSetupTrigger(BaseHttpTrigger):
    """
    HTTP trigger for STAC setup operations.

    Provides installation status, verification, and setup endpoints
    for PgSTAC infrastructure management.
    """

    def __init__(self):
        """Initialize the trigger."""
        super().__init__(trigger_name="stac_setup")
        self._stac = None  # Lazy-loaded to avoid config issues at import time

    @property
    def stac(self) -> PgStacBootstrap:
        """Lazy-load STAC infrastructure (avoids config loading at import time)."""
        if self._stac is None:
            self._stac = PgStacBootstrap()
        return self._stac

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods."""
        return ["GET", "POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle STAC setup requests.

        GET requests:
        - GET /api/stac/setup              - Quick status check
        - GET /api/stac/setup?verify=true  - Full verification

        POST requests:
        - POST /api/stac/setup?confirm=yes              - Install PgSTAC
        - POST /api/stac/setup?confirm=yes&drop=true    - Reinstall (DESTRUCTIVE!)

        Args:
            req: HTTP request

        Returns:
            Dictionary with operation results

        Raises:
            ValueError: If required parameters missing
        """
        method = req.method.upper()

        if method == "GET":
            return self._handle_status(req)
        elif method == "POST":
            return self._handle_install(req)
        else:
            raise ValueError(f"Method {method} not supported")

    # =========================================================================
    # GET - Status and Verification
    # =========================================================================

    def _handle_status(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET request for STAC status.

        Query Parameters:
            verify: If 'true', run full verification (default: quick check)

        Returns:
            Status dict with installation details
        """
        verify_param = req.params.get('verify', 'false').lower()
        full_verify = verify_param in ('true', '1', 'yes')

        if full_verify:
            logger.info("🔍 Running full STAC verification...")
            result = self.stac.verify_installation()

            return {
                'operation': 'verify',
                'valid': result.get('valid', False),
                'version': result.get('version'),
                'details': result,
                'message': (
                    f"✅ PgSTAC {result.get('version')} verified"
                    if result.get('valid')
                    else f"❌ Verification failed: {result.get('errors', [])}"
                )
            }
        else:
            logger.info("🔍 Checking STAC installation status...")
            result = check_stac_installation()

            return {
                'operation': 'status',
                'installed': result.get('installed', False),
                'schema_exists': result.get('schema_exists', False),
                'version': result.get('version'),
                'tables_count': result.get('tables_count', 0),
                'roles': result.get('roles', []),
                'needs_migration': result.get('needs_migration', True),
                'message': (
                    f"✅ PgSTAC {result.get('version')} installed"
                    if result.get('installed')
                    else "⚠️ PgSTAC not installed - use POST to install"
                ),
                'install_instructions': {
                    'method': 'POST',
                    'url': '/api/stac/setup?confirm=yes',
                    'warning': 'Installation will create pgstac schema and run migrations'
                }
            }

    # =========================================================================
    # POST - Installation
    # =========================================================================

    def _handle_install(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle POST request for STAC installation.

        Query Parameters:
            confirm: REQUIRED - Must be 'yes' to proceed
            drop: If 'true', drop existing schema (DESTRUCTIVE!)

        Returns:
            Installation results dict

        Raises:
            ValueError: If confirmation not provided
        """
        # Require explicit confirmation
        confirm = req.params.get('confirm', '').lower()
        if confirm not in ('yes', 'true', '1'):
            raise ValueError(
                "Installation requires explicit confirmation: "
                "POST /api/stac/setup?confirm=yes"
            )

        # Check drop parameter
        drop_param = req.params.get('drop', 'false').lower()
        drop_existing = drop_param in ('true', '1', 'yes')

        if drop_existing:
            logger.warning("⚠️ DROP REQUESTED - This will delete all STAC data!")

            # Additional safety check for drop
            if not self._confirm_destructive_operation():
                return {
                    'success': False,
                    'error': (
                        'DROP operation requires PGSTAC_CONFIRM_DROP=true environment variable. '
                        'This is a safety mechanism to prevent accidental data loss.'
                    ),
                    'message': '❌ DROP operation not confirmed'
                }

        logger.info(f"🚀 Installing PgSTAC (drop_existing={drop_existing})...")

        # Run installation
        result = install_stac(drop_existing=drop_existing)

        if result.get('success'):
            logger.info(f"✅ PgSTAC {result.get('version')} installed successfully")
        else:
            logger.error(f"❌ PgSTAC installation failed: {result.get('error')}")

        return {
            'operation': 'install',
            'success': result.get('success', False),
            'version': result.get('version'),
            'schema': result.get('schema'),
            'tables_created': result.get('tables_created', 0),
            'roles_created': result.get('roles_created', []),
            'verification': result.get('verification', {}),
            'migration_output': result.get('migration_output'),
            'error': result.get('error'),
            'message': (
                f"✅ PgSTAC {result.get('version')} installed successfully"
                if result.get('success')
                else f"❌ Installation failed: {result.get('error')}"
            ),
            'next_steps': (
                [
                    "Create STAC collections",
                    "Ingest STAC items",
                    "Use pgstac.search() for queries"
                ] if result.get('success') else []
            )
        }

    def _confirm_destructive_operation(self) -> bool:
        """
        Confirm destructive drop operation.

        Checks PGSTAC_CONFIRM_DROP environment variable.
        This is a safety mechanism to prevent accidental data loss.

        Returns:
            True if confirmed, False otherwise
        """
        import os
        confirm = os.getenv('PGSTAC_CONFIRM_DROP', 'false').lower()
        return confirm in ('true', '1', 'yes')


# ============================================================================
# TRIGGER INSTANCE - For registration in function_app.py
# ============================================================================

stac_setup_trigger = StacSetupTrigger()
