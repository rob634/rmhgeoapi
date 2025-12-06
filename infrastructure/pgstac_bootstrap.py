"""
STAC Infrastructure Management.

Handles PgSTAC installation, schema detection, and configuration.
PgSTAC controls its own schema naming and structure - this module
provides safe, idempotent installation and verification.

Key Design Principles:
    - PgSTAC owns the 'pgstac' schema (cannot be changed)
    - Installation is idempotent (safe to run multiple times)
    - Separate from app schema (app.jobs, app.tasks)
    - Production-safe: preserves data, only updates functions

Exports:
    PgStacBootstrap: Infrastructure class for schema setup and management
"""

from typing import Dict, Any, Optional, List
import subprocess
import sys
import os
import json
import psycopg
from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from config import get_config
from config.defaults import STACDefaults

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PgStacBootstrap")


class PgStacBootstrap:
    """
    PgSTAC Infrastructure Management (PostgreSQL STAC Extension).

    Handles PgSTAC (PostgreSQL STAC extension) installation, configuration, and operations.
    Provides idempotent installation and verification of PgSTAC schema.
    All schema naming is controlled by PgSTAC library - we just trigger
    installation and verify results.

    Schema Structure (Fixed by PgSTAC):
    - Schema: pgstac (hardcoded, cannot change)
    - Roles: pgstac_admin, pgstac_ingest, pgstac_read
    - Tables: collections, items, partitions, etc.

    Note: This class specifically manages PgSTAC (PostgreSQL extension), not generic STAC.
          For general STAC metadata generation, see services/service_stac_metadata.py

    
    Date: 5 OCT 2025 (Renamed to PgStacBootstrap: 18 NOV 2025)
    """

    # PgSTAC schema constants (controlled by library)
    PGSTAC_SCHEMA = "pgstac"
    PGSTAC_ROLES = ["pgstac_admin", "pgstac_ingest", "pgstac_read"]

    # =========================================================================
    # PRODUCTION COLLECTION STRATEGY
    # =========================================================================
    # CRITICAL: Bronze container is DEV/TEST ONLY - NOT in production STAC
    #
    # Production STAC Collections (3 types):
    # 1. "cogs"       - Cloud-optimized GeoTIFFs in EPSG:4326
    # 2. "vectors"    - PostGIS tables (queryable features)
    # 3. "geoparquet" - GeoParquet analytical datasets (future)
    #
    # Development: Use "dev" collection for testing with Bronze container
    # =========================================================================

    # Collection metadata imported from config.defaults.STACDefaults
    # Single source of truth for collection definitions
    PRODUCTION_COLLECTIONS = STACDefaults.COLLECTION_METADATA

    # Legacy tier constants (deprecated - kept for backward compatibility during migration)
    VALID_TIERS = ['bronze', 'silver', 'gold']

    # Tier descriptions imported from config.defaults.STACDefaults
    TIER_DESCRIPTIONS = STACDefaults.TIER_DESCRIPTIONS

    # =========================================================================
    # CORPORATE/QA ENVIRONMENT ROLE PREREQUISITES (5 DEC 2025)
    # =========================================================================
    # In restricted environments, the DBA must pre-create roles and grant them
    # WITH ADMIN OPTION to the managed identity. This is because:
    #
    # 1. pypgstac migrate unconditionally runs: GRANT pgstac_admin TO current_user
    # 2. Even if already granted, executing GRANT requires ADMIN OPTION on the role
    # 3. Without ADMIN OPTION, pypgstac fails with "permission denied to grant role"
    #
    # DBA Prerequisites SQL (run once by DBA before first deployment):
    # ```sql
    # -- Create pgSTAC roles (if not exists - idempotent)
    # DO $$ BEGIN CREATE ROLE pgstac_admin; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    # DO $$ BEGIN CREATE ROLE pgstac_ingest; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    # DO $$ BEGIN CREATE ROLE pgstac_read; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    #
    # -- Grant roles WITH ADMIN OPTION (required for pypgstac migrate)
    # GRANT pgstac_admin TO <managed_identity_name> WITH ADMIN OPTION;
    # GRANT pgstac_ingest TO <managed_identity_name> WITH ADMIN OPTION;
    # GRANT pgstac_read TO <managed_identity_name> WITH ADMIN OPTION;
    # ```
    #
    # Use check_dba_prerequisites() to verify before running pypgstac migrate.
    # =========================================================================

    # =========================================================================
    # GRACEFUL DEGRADATION SUPPORT (6 DEC 2025)
    # =========================================================================
    # Cached availability status for performance (checked once per process)
    _availability_cache: Optional[bool] = None
    _availability_cache_time: Optional[float] = None
    _AVAILABILITY_CACHE_TTL_SECONDS = 60  # Re-check every 60 seconds

    @classmethod
    def is_available(cls) -> bool:
        """
        Quick check if pgstac schema is usable (for graceful degradation).

        Used by STAC handlers to detect if pgstac is available before attempting
        operations. Returns cached result for performance (TTL: 60 seconds).

        Returns:
            True if pgstac schema exists and is functional, False otherwise.

        Usage:
            if not PgStacBootstrap.is_available():
                return {"success": True, "degraded": True, "warning": "pgSTAC unavailable"}
        """
        import time

        # Check cache validity
        now = time.time()
        if (cls._availability_cache is not None and
            cls._availability_cache_time is not None and
            (now - cls._availability_cache_time) < cls._AVAILABILITY_CACHE_TTL_SECONDS):
            return cls._availability_cache

        # Perform actual check
        try:
            bootstrap = cls()
            result = bootstrap.check_installation()
            is_avail = result.get('installed', False) and result.get('schema_exists', False)

            # Cache result
            cls._availability_cache = is_avail
            cls._availability_cache_time = now

            if not is_avail:
                logger.warning("⚠️ pgSTAC not available - graceful degradation mode active")

            return is_avail

        except Exception as e:
            logger.warning(f"⚠️ pgSTAC availability check failed: {e} - degraded mode active")
            cls._availability_cache = False
            cls._availability_cache_time = now
            return False

    @classmethod
    def clear_availability_cache(cls) -> None:
        """Clear the availability cache (useful after schema rebuild)."""
        cls._availability_cache = None
        cls._availability_cache_time = None
        logger.info("🔄 pgSTAC availability cache cleared")

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize STAC infrastructure manager.

        ARCHITECTURE PRINCIPLE (16 NOV 2025):
        All database access must go through PostgreSQLRepository to ensure
        managed identity authentication works correctly.

        Args:
            connection_string: PostgreSQL connection string (uses config if not provided)
                              DEPRECATED: Use PostgreSQLRepository instead
        """
        from infrastructure.postgresql import PostgreSQLRepository

        self.config = get_config()

        # Use PostgreSQLRepository for all database connections (managed identity support)
        # If explicit connection string provided, use it (for backward compatibility)
        # Otherwise, let PostgreSQLRepository handle managed identity
        if connection_string:
            self._pg_repo = PostgreSQLRepository(
                connection_string=connection_string,
                schema_name='pgstac'
            )
        else:
            self._pg_repo = PostgreSQLRepository(schema_name='pgstac')

    # =========================================================================
    # SCHEMA DETECTION - Fast idempotent checks
    # =========================================================================

    def check_installation(self) -> Dict[str, Any]:
        """
        Check if PgSTAC is installed (fast, idempotent).

        This is a lightweight check suitable for startup validation.
        Does NOT install anything - just checks existence.

        Returns:
            Dict with installation status:
            {
                'installed': bool,
                'schema_exists': bool,
                'version': str or None,
                'tables_count': int,
                'roles': List[str],
                'needs_migration': bool
            }
        """
        logger.info("🔍 Checking PgSTAC installation status...")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check schema existence
                    cur.execute(
                        sql.SQL("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s) as exists"),
                        [self.PGSTAC_SCHEMA]
                    )
                    schema_exists = cur.fetchone()['exists']

                    if not schema_exists:
                        logger.info("❌ PgSTAC schema not found")
                        return {
                            'installed': False,
                            'schema_exists': False,
                            'version': None,
                            'tables_count': 0,
                            'roles': [],
                            'needs_migration': True
                        }

                    # Get version
                    version = None
                    try:
                        cur.execute("SELECT pgstac.get_version() as version")
                        version = cur.fetchone()['version']
                    except psycopg.Error:
                        logger.warning("⚠️ pgstac.get_version() failed - may need migration")

                    # Count tables in pgstac schema
                    cur.execute(
                        sql.SQL(
                            "SELECT COUNT(*) as count FROM information_schema.tables "
                            "WHERE table_schema = %s"
                        ),
                        [self.PGSTAC_SCHEMA]
                    )
                    tables_count = cur.fetchone()['count']

                    # Check roles
                    cur.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                    )
                    roles = [row['rolname'] for row in cur.fetchall()]

                    installed = (
                        schema_exists and
                        version is not None and
                        tables_count > 0 and
                        len(roles) >= 3
                    )

                    result = {
                        'installed': installed,
                        'schema_exists': schema_exists,
                        'version': version,
                        'tables_count': tables_count,
                        'roles': roles,
                        'needs_migration': not installed
                    }

                    if installed:
                        logger.info(f"✅ PgSTAC {version} installed ({tables_count} tables)")
                    else:
                        logger.warning(f"⚠️ PgSTAC schema exists but incomplete")

                    return result

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to check PgSTAC installation: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            return {
                'installed': False,
                'schema_exists': False,
                'version': None,
                'tables_count': 0,
                'roles': [],
                'needs_migration': True,
                'error': str(e)
            }

    def check_dba_prerequisites(self, identity_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if DBA prerequisites for pypgstac are in place (5 DEC 2025).

        In restricted corporate/QA environments, a DBA must:
        1. Create pgstac roles (pgstac_admin, pgstac_ingest, pgstac_read)
        2. Grant those roles to the managed identity

        This method verifies these prerequisites BEFORE running pypgstac migrate,
        which would fail with permission errors otherwise.

        Args:
            identity_name: Managed identity name to check grants for.
                          If not provided, uses config.database.managed_identity_name

        Returns:
            Dict with prerequisite check results:
            {
                'ready': bool,           # True if all prerequisites met
                'roles_exist': {         # Role existence check
                    'pgstac_admin': bool,
                    'pgstac_ingest': bool,
                    'pgstac_read': bool
                },
                'roles_granted': {       # Role grant check (to identity)
                    'pgstac_admin': bool,
                    'pgstac_ingest': bool,
                    'pgstac_read': bool
                },
                'identity_name': str,    # Identity checked
                'missing_roles': [...],  # Roles that don't exist
                'missing_grants': [...], # Grants that are missing
                'dba_sql': str           # SQL for DBA to run if not ready
            }

        Usage:
            >>> bootstrap = PgStacBootstrap()
            >>> prereqs = bootstrap.check_dba_prerequisites()
            >>> if not prereqs['ready']:
            ...     print("DBA must run:", prereqs['dba_sql'])
        """
        # Get identity name from config if not provided
        if identity_name is None:
            identity_name = (
                self.config.database.managed_identity_name or
                os.getenv("MANAGED_IDENTITY_NAME") or
                os.getenv("PGUSER") or
                "rmhpgflexadmin"  # Default fallback
            )

        logger.info(f"🔍 Checking DBA prerequisites for identity: {identity_name}")

        result = {
            'ready': False,
            'roles_exist': {},
            'roles_granted': {},
            'admin_option': {},  # NEW: Check if ADMIN OPTION is granted (required for pypgstac)
            'identity_name': identity_name,
            'missing_roles': [],
            'missing_grants': [],
            'missing_admin_option': [],  # NEW: Grants missing ADMIN OPTION
            'dba_sql': ''
        }

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check 1: Do the pgstac roles exist?
                    for role in self.PGSTAC_ROLES:
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                            [role]
                        )
                        exists = cur.fetchone()['exists']
                        result['roles_exist'][role] = exists
                        if not exists:
                            result['missing_roles'].append(role)
                            logger.warning(f"⚠️ Role '{role}' does not exist")

                    # Check 2: Are the roles granted to the identity WITH ADMIN OPTION?
                    # IMPORTANT (5 DEC 2025): pypgstac migrate runs GRANT pgstac_admin TO current_user
                    # even if already granted. This requires ADMIN OPTION on the role.
                    # Simple membership is NOT enough - must have ADMIN OPTION.
                    for role in self.PGSTAC_ROLES:
                        cur.execute("""
                            SELECT
                                EXISTS(
                                    SELECT 1
                                    FROM pg_auth_members m
                                    JOIN pg_roles r ON m.roleid = r.oid
                                    JOIN pg_roles member ON m.member = member.oid
                                    WHERE r.rolname = %s
                                    AND member.rolname = %s
                                ) as granted,
                                COALESCE((
                                    SELECT m.admin_option
                                    FROM pg_auth_members m
                                    JOIN pg_roles r ON m.roleid = r.oid
                                    JOIN pg_roles member ON m.member = member.oid
                                    WHERE r.rolname = %s
                                    AND member.rolname = %s
                                    LIMIT 1
                                ), false) as has_admin_option
                        """, [role, identity_name, role, identity_name])
                        row = cur.fetchone()
                        granted = row['granted']
                        has_admin = row['has_admin_option']

                        result['roles_granted'][role] = granted
                        result['admin_option'][role] = has_admin

                        if not granted:
                            result['missing_grants'].append(role)
                            logger.warning(f"⚠️ Role '{role}' not granted to '{identity_name}'")
                        elif not has_admin:
                            result['missing_admin_option'].append(role)
                            logger.warning(f"⚠️ Role '{role}' granted but WITHOUT ADMIN OPTION (required for pypgstac)")

                    # Generate DBA SQL if not ready
                    # IMPORTANT: Need ADMIN OPTION for pypgstac to work
                    if result['missing_roles'] or result['missing_grants'] or result['missing_admin_option']:
                        dba_sql_lines = [
                            "-- ========================================",
                            "-- DBA Prerequisites for pypgstac migrate",
                            "-- Run as superuser/DBA BEFORE application deployment",
                            "-- ========================================",
                            ""
                        ]

                        # Step 1: Check existing roles
                        dba_sql_lines.append("-- Step 1: Check if roles already exist")
                        dba_sql_lines.append("SELECT rolname FROM pg_roles WHERE rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read');")
                        dba_sql_lines.append("")

                        # Step 2: Role creation
                        if result['missing_roles']:
                            dba_sql_lines.append("-- Step 2: Create roles (SKIP any roles returned by Step 1)")
                            for role in result['missing_roles']:
                                dba_sql_lines.append(f"CREATE ROLE {role};")
                            dba_sql_lines.append("")

                        # Step 3: Role grants WITH ADMIN OPTION
                        roles_needing_grant = set(result['missing_grants']) | set(result['missing_admin_option'])
                        if roles_needing_grant:
                            step_num = "3" if result['missing_roles'] else "2"
                            dba_sql_lines.append(f"-- Step {step_num}: Grant roles WITH ADMIN OPTION to managed identity")
                            dba_sql_lines.append("-- CRITICAL: WITH ADMIN OPTION is required (pypgstac runs GRANT ... TO current_user)")
                            for role in sorted(roles_needing_grant):
                                dba_sql_lines.append(f"GRANT {role} TO {identity_name} WITH ADMIN OPTION;")
                            dba_sql_lines.append("")

                        # Step 4: Verification query
                        final_step = "4" if result['missing_roles'] else "3"
                        dba_sql_lines.append(f"-- Step {final_step}: Verify configuration (screenshot this for service ticket)")
                        dba_sql_lines.append(f"""SELECT r.rolname AS role_name,
       m.rolname AS granted_to,
       am.admin_option AS has_admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read')
AND m.rolname = '{identity_name}'
ORDER BY r.rolname;""")
                        dba_sql_lines.append("-- Expected: 3 rows, all with has_admin_option = true")

                        result['dba_sql'] = '\n'.join(dba_sql_lines)
                        result['ready'] = False
                        logger.warning(
                            f"❌ DBA prerequisites NOT met. "
                            f"Missing roles: {result['missing_roles']}, "
                            f"Missing grants: {result['missing_grants']}, "
                            f"Missing ADMIN OPTION: {result['missing_admin_option']}"
                        )
                    else:
                        result['ready'] = True
                        result['dba_sql'] = '-- All prerequisites met, no DBA action required'
                        logger.info(f"✅ DBA prerequisites met for identity: {identity_name}")

                    return result

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to check DBA prerequisites: {e}")
            result['error'] = str(e)
            result['ready'] = False
            return result

    # =========================================================================
    # INSTALLATION - One-time setup (idempotent)
    # =========================================================================

    def install_pgstac(self,
                       drop_existing: bool = False,
                       run_migrations: bool = True) -> Dict[str, Any]:
        """
        Install PgSTAC schema using pypgstac migrate.

        This uses the pypgstac CLI to run migrations. The pypgstac library
        controls all schema naming and structure - we just provide the
        database connection and trigger the process.

        Args:
            drop_existing: If True, drop pgstac schema before install (DESTRUCTIVE!)
            run_migrations: If True, run pypgstac migrate (default: True)

        Returns:
            Dict with installation results
        """
        logger.info("🚀 Starting PgSTAC installation...")

        # Safety check
        if drop_existing:
            logger.warning("⚠️ drop_existing=True - THIS WILL DELETE ALL STAC DATA!")
            if not self._confirm_drop():
                return {
                    'success': False,
                    'error': 'Installation cancelled - drop_existing requires confirmation'
                }

        try:
            # Drop existing schema if requested
            if drop_existing:
                self._drop_pgstac_schema()

            # Run pypgstac migrate
            if run_migrations:
                migration_result = self._run_pypgstac_migrate()
                if not migration_result['success']:
                    return migration_result

            # Verify installation
            verification = self.verify_installation()

            result = {
                'success': verification['valid'],
                'version': verification.get('version'),
                'schema': self.PGSTAC_SCHEMA,
                'tables_created': verification.get('tables_count', 0),
                'roles_created': verification.get('roles', []),
                'migration_output': migration_result.get('output') if run_migrations else None,
                'verification': verification
            }

            # FIX (25 NOV 2025): Propagate verification errors so callers know what failed
            if not verification['valid'] and verification.get('errors'):
                result['error'] = '; '.join(verification['errors'])

            return result

        except Exception as e:
            logger.error(f"❌ PgSTAC installation failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _drop_pgstac_schema(self):
        """Drop pgstac schema (DESTRUCTIVE - development only!)."""
        logger.warning("💣 Dropping pgstac schema...")

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(self.PGSTAC_SCHEMA)
                ))
                conn.commit()
                logger.info("✅ pgstac schema dropped")

    def _run_pypgstac_migrate(self, skip_prereq_check: bool = False) -> Dict[str, Any]:
        """
        Run pypgstac migrate using subprocess.

        IMPORTANT (5 DEC 2025): In corporate/QA environments with restricted permissions,
        pypgstac migrate may fail with "permission denied" on GRANT statements.

        The migration attempts: GRANT pgstac_admin TO current_user
        This fails if:
        1. The role doesn't exist yet (DBA didn't pre-create)
        2. The current user doesn't have CREATEROLE privilege
        3. The role wasn't pre-granted to the current user by DBA

        Solution: DBA must run prerequisites BEFORE deployment. Use check_dba_prerequisites()
        to verify readiness.

        Args:
            skip_prereq_check: If True, skip DBA prerequisite check (default: False)
                              Use with caution - only if you know prerequisites are met.

        Returns:
            Dict with migration results including:
            - success: bool
            - output: stdout from pypgstac
            - error: error message if failed
            - dba_action_required: True if failure is due to missing DBA prerequisites
            - dba_sql: SQL for DBA to run (only if dba_action_required)
        """
        logger.info("📦 Running pypgstac migrate...")

        try:
            # Set environment variables for pypgstac
            # ARCHITECTURE PRINCIPLE (24 NOV 2025): Support managed identity for pypgstac CLI
            env = os.environ.copy()

            # Determine authentication method
            client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID") or self.config.database.managed_identity_client_id
            website_name = os.getenv("WEBSITE_SITE_NAME")

            if client_id or website_name:
                # Managed identity: acquire token for PostgreSQL
                logger.info("🔐 Using managed identity for pypgstac migrate...")
                from azure.identity import ManagedIdentityCredential, DefaultAzureCredential

                # Get the identity name from config - single source of truth for default
                identity_name = self.config.database.managed_identity_name or os.getenv("MANAGED_IDENTITY_NAME")

                # Acquire token
                if client_id:
                    credential = ManagedIdentityCredential(client_id=client_id)
                else:
                    credential = DefaultAzureCredential()

                token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
                pg_password = token.token
                pg_user = identity_name
                logger.info(f"✅ Acquired managed identity token for user: {pg_user}")
            else:
                # Password auth: use config values
                pg_user = self.config.postgis_user
                pg_password = self.config.postgis_password
                if not pg_user or not pg_password:
                    return {
                        'success': False,
                        'error': 'No credentials available - need POSTGIS_USER/PASSWORD or managed identity'
                    }

            env.update({
                'PGHOST': self.config.postgis_host,
                'PGPORT': str(self.config.postgis_port),
                'PGDATABASE': self.config.postgis_database,
                'PGUSER': pg_user,
                'PGPASSWORD': pg_password
            })

            # Run pypgstac migrate
            # Use python -m with pypgstac.pypgstac for Azure Functions compatibility
            result = subprocess.run(
                [sys.executable, '-m', 'pypgstac.pypgstac', 'migrate'],
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                logger.info("✅ pypgstac migrate completed successfully")
                return {
                    'success': True,
                    'output': result.stdout,
                    'returncode': result.returncode
                }
            else:
                logger.error(f"❌ pypgstac migrate failed: {result.stderr}")

                # Check if this is a GRANT permission error (DBA prerequisites not met)
                error_text = result.stderr.lower()
                is_grant_error = (
                    'permission denied' in error_text or
                    'must have admin option' in error_text or
                    'grant' in error_text and 'pgstac' in error_text
                )

                response = {
                    'success': False,
                    'error': result.stderr,
                    'output': result.stdout,
                    'returncode': result.returncode
                }

                if is_grant_error:
                    # This is likely a DBA prerequisite failure
                    logger.warning("⚠️ GRANT permission error detected - DBA prerequisites may not be met")
                    response['dba_action_required'] = True
                    response['hint'] = (
                        "pypgstac migrate failed due to permission errors. "
                        "In corporate/QA environments, a DBA must pre-create pgstac roles "
                        "and grant them to the managed identity. "
                        "Call check_dba_prerequisites() to get the required SQL."
                    )

                    # Try to get DBA SQL for convenience
                    try:
                        prereqs = self.check_dba_prerequisites()
                        if not prereqs['ready']:
                            response['dba_sql'] = prereqs['dba_sql']
                            response['missing_roles'] = prereqs['missing_roles']
                            response['missing_grants'] = prereqs['missing_grants']
                    except Exception as e:
                        logger.warning(f"Could not check DBA prerequisites: {e}")

                return response

        except subprocess.TimeoutExpired:
            logger.error("❌ pypgstac migrate timed out after 5 minutes")
            return {
                'success': False,
                'error': 'Migration timed out after 5 minutes'
            }
        except FileNotFoundError as e:
            logger.error(f"❌ pypgstac command not found: {e}")
            logger.error(f"   sys.executable: {sys.executable}")
            logger.error(f"   PATH: {os.environ.get('PATH', 'not set')}")
            return {
                'success': False,
                'error': f'pypgstac not found - {e}'
            }
        except Exception as e:
            logger.error(f"❌ pypgstac migrate error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }

    def _confirm_drop(self) -> bool:
        """
        Confirm destructive drop operation.

        In production, this should always return False.
        For development, you can override this or use environment variable.

        Returns:
            True if drop confirmed, False otherwise
        """
        # Check for explicit confirmation environment variable
        confirm = os.getenv('PGSTAC_CONFIRM_DROP', 'false').lower()
        return confirm in ('true', '1', 'yes')

    # =========================================================================
    # VERIFICATION - Post-installation checks
    # =========================================================================

    def verify_installation(self) -> Dict[str, Any]:
        """
        Verify PgSTAC installation is complete and functional.

        Runs comprehensive checks:
        - Schema exists
        - Version query works
        - Tables exist
        - Roles configured
        - Search function available
        - Search hash functions available (search_tohash, search_hash)

        Returns:
            Dict with verification results
        """
        logger.info("🔍 Verifying PgSTAC installation...")

        checks = {
            'schema_exists': False,
            'version_query': False,
            'tables_exist': False,
            'roles_configured': False,
            'search_available': False,
            'search_hash_functions': False,
            'version': None,
            'tables_count': 0,
            'roles': [],
            'errors': []
        }

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Schema exists
                    cur.execute(
                        sql.SQL("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s) as exists"),
                        [self.PGSTAC_SCHEMA]
                    )
                    row = cur.fetchone()
                    checks['schema_exists'] = row['exists']

                    if not checks['schema_exists']:
                        checks['errors'].append("pgstac schema does not exist")
                        checks['valid'] = False
                        return checks

                    # 2. Version query
                    try:
                        cur.execute("SELECT pgstac.get_version() as version")
                        row = cur.fetchone()
                        checks['version'] = row['version']
                        checks['version_query'] = True
                    except psycopg.Error as e:
                        checks['errors'].append(f"Version query failed: {e}")
                        conn.rollback()  # Allow subsequent checks to run

                    # 3. Tables exist
                    cur.execute(
                        sql.SQL(
                            "SELECT COUNT(*) as count FROM information_schema.tables "
                            "WHERE table_schema = %s"
                        ),
                        [self.PGSTAC_SCHEMA]
                    )
                    row = cur.fetchone()
                    checks['tables_count'] = row['count']
                    checks['tables_exist'] = checks['tables_count'] > 0

                    if not checks['tables_exist']:
                        checks['errors'].append(f"No tables found in {self.PGSTAC_SCHEMA} schema")

                    # 4. Roles configured
                    cur.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                    )
                    checks['roles'] = [row['rolname'] for row in cur.fetchall()]
                    checks['roles_configured'] = len(checks['roles']) >= 3

                    if not checks['roles_configured']:
                        checks['errors'].append(f"Expected 3+ roles, found {len(checks['roles'])}")

                    # 5. Search function available
                    # NOTE: Instead of calling search('{}') which can fail due to transaction
                    # visibility issues immediately after pypgstac migrate, we verify the
                    # search function exists in the catalog. The health endpoint performs
                    # full functional testing.
                    try:
                        cur.execute("""
                            SELECT COUNT(*) as count FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                            WHERE n.nspname = 'pgstac' AND p.proname = 'search'
                        """)
                        row = cur.fetchone()
                        checks['search_available'] = (row['count'] >= 1)
                        if not checks['search_available']:
                            checks['errors'].append("pgstac.search function not found in catalog")
                    except psycopg.Error as e:
                        checks['errors'].append(f"Search function check failed: {e}")
                        # CRITICAL: Rollback aborted transaction to allow subsequent checks
                        # PostgreSQL marks transaction as aborted after first error,
                        # all subsequent queries fail with "current transaction is aborted"
                        conn.rollback()

                    # 6. Search hash functions available (18 NOV 2025)
                    # Required for pgstac.searches table GENERATED hash column
                    try:
                        # Check both functions exist
                        cur.execute("""
                            SELECT COUNT(*) as count FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                            WHERE n.nspname = 'pgstac'
                            AND p.proname IN ('search_tohash', 'search_hash')
                        """)
                        row = cur.fetchone()
                        func_count = row['count']
                        checks['search_hash_functions'] = (func_count == 2)

                        if not checks['search_hash_functions']:
                            checks['errors'].append(
                                f"Missing search hash functions (found {func_count}/2). "
                                "Run /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes to reinstall pgSTAC."
                            )
                    except psycopg.Error as e:
                        checks['errors'].append(f"Search hash function check failed: {e}")
                        # Rollback in case this check also fails
                        conn.rollback()

                    # Overall validation
                    checks['valid'] = (
                        checks['schema_exists'] and
                        checks['version_query'] and
                        checks['tables_exist'] and
                        checks['roles_configured'] and
                        checks['search_available'] and
                        checks['search_hash_functions']
                    )

                    if checks['valid']:
                        logger.info(f"✅ PgSTAC {checks['version']} verification passed")
                    else:
                        logger.warning(f"⚠️ PgSTAC verification failed: {checks['errors']}")

                    return checks

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Verification error: {e}")
            logger.error(f"   Connection string: {self.connection_string}")
            logger.error(f"   Error type: {type(e).__name__}")
            checks['errors'].append(str(e))
            checks['valid'] = False
            return checks

    # =========================================================================
    # COLLECTION MANAGEMENT - Initial setup
    # =========================================================================

    def create_collection(self,
                         container: str,
                         tier: str,
                         collection_id: Optional[str] = None,
                         title: Optional[str] = None,
                         description: Optional[str] = None,
                         summaries: Optional[Dict[str, Any]] = None,
                         **kwargs) -> Dict[str, Any]:
        """
        Create STAC collection for any tier (Bronze/Silver/Gold).

        Args:
            container: Azure Storage container name (from config.storage.{zone}.get_container())
            tier: Collection tier ('bronze', 'silver', or 'gold')
            collection_id: Unique collection identifier (defaults to '{tier}-{container}')
            title: Human-readable title (defaults to generated title)
            description: Collection description (defaults to tier-appropriate description)
            summaries: Optional custom summaries to merge with defaults
            **kwargs: Additional STAC collection properties

        Returns:
            Dict with collection creation results

        Raises:
            ValueError: If tier is not in VALID_TIERS
        """
        # Validate tier
        tier = tier.lower()
        if tier not in self.VALID_TIERS:
            error_msg = f"Invalid tier '{tier}'. Must be one of: {', '.join(self.VALID_TIERS)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'valid_tiers': self.VALID_TIERS
            }

        # Validate container
        if not container or not isinstance(container, str) or not container.strip():
            logger.error(f"❌ Invalid container name: {container}")
            return {
                'success': False,
                'error': 'Container must be a non-empty string',
                'provided': container
            }

        # Auto-generate IDs and titles if not provided
        collection_id = collection_id or f"{tier}-{container}"
        title = title or f"{tier.title()}: {container}"
        description = description or f"{self.TIER_DESCRIPTIONS[tier]} '{container}'"

        logger.info(f"📦 Creating {tier.upper()} collection: {collection_id} (container: {container})")

        # Build default summaries
        default_summaries = {
            "azure:container": [container],
            "azure:tier": [tier]
        }

        # Merge with custom summaries if provided
        final_summaries = {**default_summaries, **(summaries or {})}

        # Collection in STAC format
        collection = {
            "id": collection_id,
            "type": "Collection",
            "stac_version": "1.0.0",
            "title": title,
            "description": description,
            "license": STACDefaults.DEFAULT_LICENSE,
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]}
            },
            "summaries": final_summaries,
            **kwargs  # Allow additional STAC properties
        }

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Insert collection using pgstac function
                    cur.execute(
                        "SELECT * FROM pgstac.create_collection(%s)",
                        [json.dumps(collection)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ {tier.upper()} collection created: {collection_id}")
                    return {
                        'success': True,
                        'collection_id': collection_id,
                        'tier': tier,
                        'container': container,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to create {tier} collection: {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }

    def create_production_collection(self, collection_type: str) -> Dict[str, Any]:
        """
        Create one of the production STAC collections (idempotent).

        This method checks if the collection exists before attempting creation,
        making it safe to call multiple times (infrastructure-as-code pattern).

        Production collections:
        - "system-vectors": PostGIS vector tables created by ETL (System STAC Layer 1)
        - "system-rasters": COG raster files created by ETL (System STAC Layer 1)
        - "cogs": Cloud-optimized GeoTIFFs in EPSG:4326 (legacy)
        - "vectors": PostGIS tables (legacy)
        - "geoparquet": GeoParquet analytical datasets (legacy)
        - "dev": Development/testing (generic)

        Args:
            collection_type: One of PRODUCTION_COLLECTIONS keys

        Returns:
            Dict with collection creation results:
            {
                'success': bool,
                'existed': bool,  # True if collection already existed
                'collection_id': str,
                'collection_type': str,
                'config': dict,
                'result': Any  # PgSTAC function result (only if newly created)
            }

        Examples:
            >>> result = stac.create_production_collection('system-vectors')
            >>> result['success']  # True
            >>> result['existed']  # False (first run) or True (subsequent runs)
        """
        if collection_type not in self.PRODUCTION_COLLECTIONS:
            error_msg = f"Invalid collection type '{collection_type}'. Must be one of: {', '.join(self.PRODUCTION_COLLECTIONS.keys())}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'valid_types': list(self.PRODUCTION_COLLECTIONS.keys())
            }

        coll_config = self.PRODUCTION_COLLECTIONS[collection_type]

        logger.info(f"📦 Creating production collection: {collection_type}")

        # Build STAC Collection
        collection = {
            "id": collection_type,
            "type": "Collection",
            "stac_version": "1.0.0",
            "title": coll_config['title'],
            "description": coll_config['description'],
            "license": STACDefaults.DEFAULT_LICENSE,
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]}
            },
            "summaries": {
                "asset_type": [coll_config['asset_type']],
                "media_type": [coll_config['media_type']]
            }
        }

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Database-level idempotency check (18 OCT 2025)
                    # Check if collection already exists before attempting creation
                    logger.debug(f"🔍 Checking if collection '{collection_type}' exists...")
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s) as exists",
                        [collection_type]
                    )
                    exists = cur.fetchone()['exists']

                    if exists:
                        logger.info(f"✅ Collection '{collection_type}' already exists (idempotent - skipping creation)")
                        return {
                            'success': True,
                            'existed': True,
                            'collection_id': collection_type,
                            'collection_type': collection_type,
                            'config': coll_config,
                            'message': 'Collection already exists (idempotent)'
                        }

                    # Create collection (only if doesn't exist)
                    logger.debug(f"📝 Creating new collection '{collection_type}'...")
                    cur.execute(
                        "SELECT * FROM pgstac.create_collection(%s)",
                        [json.dumps(collection)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ Production collection created: {collection_type}")
                    return {
                        'success': True,
                        'existed': False,
                        'collection_id': collection_type,
                        'collection_type': collection_type,
                        'config': coll_config,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to create collection '{collection_type}': {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }

    @staticmethod
    def determine_collection(asset_type: str, **kwargs) -> str:
        """
        Determine which production collection an asset belongs to.

        Args:
            asset_type: Type of asset ('raster', 'postgis_table', 'geoparquet', 'dev')
            **kwargs: Additional context (unused for now, reserved for future logic)

        Returns:
            Collection ID for this asset

        Examples:
            determine_collection('raster') → 'cogs'
            determine_collection('postgis_table') → 'vectors'
            determine_collection('geoparquet') → 'geoparquet'
            determine_collection('dev') → 'dev'
        """
        mapping = {
            'raster': 'cogs',
            'cog': 'cogs',
            'postgis_table': 'vectors',
            'vector': 'vectors',
            'geoparquet': 'geoparquet',
            'dev': 'dev',
            'test': 'dev'
        }

        return mapping.get(asset_type.lower(), 'dev')

    # =========================================================================
    # COLLECTION MANAGEMENT - Check and verify PgSTAC collections
    # =========================================================================

    def collection_exists(self, collection_id: str) -> bool:
        """
        Check if STAC Collection exists in PgSTAC.

        Args:
            collection_id: Collection ID to check

        Returns:
            True if collection exists, False otherwise

        Note:
            This is critical before inserting items - pgSTAC uses table partitioning
            where each collection gets its own partition. Inserting into non-existent
            collection fails with "no partition of relation items found for row" error.
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Query pgstac.collections table
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s)",
                        (collection_id,)
                    )
                    result = cur.fetchone()
                    return result[0] if result else False

        except Exception as e:
            self.logger.error(f"Error checking collection existence: {e}")
            return False  # Conservative: assume doesn't exist on error

    # =========================================================================
    # ITEM MANAGEMENT - Insert STAC Items into PgSTAC
    # =========================================================================

    def item_exists(self, item_id: str, collection_id: str) -> bool:
        """
        Check if STAC Item already exists in PgSTAC collection.

        Args:
            item_id: STAC Item ID to check
            collection_id: Collection to check in

        Returns:
            True if item exists, False otherwise
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Query pgstac.items table for existing item
                    cur.execute(
                        "SELECT id FROM pgstac.items WHERE id = %s AND collection = %s",
                        (item_id, collection_id)
                    )
                    result = cur.fetchone()
                    exists = result is not None

                    if exists:
                        logger.debug(f"Item '{item_id}' already exists in collection '{collection_id}'")

                    return exists

        except (psycopg.Error, OSError) as e:
            logger.warning(f"Error checking if item exists: {e}")
            # On error, assume item doesn't exist (will fail on insert if it does)
            return False

    def get_existing_item_ids(
        self,
        collection_id: str,
        bbox: Optional[List[float]] = None,
        item_id_prefix: Optional[str] = None
    ) -> set:
        """
        Get set of existing STAC item IDs in a collection, optionally filtered by bbox.

        This enables STAC-driven idempotency: query which items already exist
        before processing, so we can skip already-completed work.

        Args:
            collection_id: STAC collection ID to query
            bbox: Optional bounding box [west, south, east, north] in EPSG:4326
            item_id_prefix: Optional prefix to filter item IDs (e.g., "n04w006_")

        Returns:
            Set of existing item IDs in the collection matching the filters

        Example:
            # Get all items in collection
            existing = stac.get_existing_item_ids("fathom-flood-stacked-ci")

            # Get items within a bbox
            existing = stac.get_existing_item_ids(
                "fathom-flood-stacked-ci",
                bbox=[-8, 4, -2, 10]
            )

            # Get items with ID prefix
            existing = stac.get_existing_item_ids(
                "fathom-flood-stacked-ci",
                item_id_prefix="n04w006_"
            )
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Build query with optional filters
                    if bbox:
                        # Spatial query using ST_Intersects with bbox
                        # pgstac stores geometry in 'geometry' column
                        query = """
                            SELECT id FROM pgstac.items
                            WHERE collection = %s
                            AND ST_Intersects(
                                geometry,
                                ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                            )
                        """
                        params = [collection_id, bbox[0], bbox[1], bbox[2], bbox[3]]

                        if item_id_prefix:
                            query += " AND id LIKE %s"
                            params.append(f"{item_id_prefix}%")

                        cur.execute(query, params)
                    elif item_id_prefix:
                        cur.execute(
                            "SELECT id FROM pgstac.items WHERE collection = %s AND id LIKE %s",
                            (collection_id, f"{item_id_prefix}%")
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM pgstac.items WHERE collection = %s",
                            (collection_id,)
                        )

                    rows = cur.fetchall()
                    item_ids = {row[0] for row in rows}

                    logger.debug(
                        f"Found {len(item_ids)} existing items in '{collection_id}'"
                        f"{f' within bbox {bbox}' if bbox else ''}"
                        f"{f' with prefix {item_id_prefix}' if item_id_prefix else ''}"
                    )

                    return item_ids

        except (psycopg.Error, OSError) as e:
            logger.warning(f"Error querying existing items: {e}")
            # On error, return empty set (will reprocess - safe fallback)
            return set()

    def get_items_by_bbox(
        self,
        collection_id: str,
        bbox: List[float],
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get STAC items within a bounding box.

        Args:
            collection_id: STAC collection ID
            bbox: Bounding box [west, south, east, north] in EPSG:4326
            limit: Maximum number of items to return

        Returns:
            List of STAC item dicts
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT content FROM pgstac.items
                        WHERE collection = %s
                        AND ST_Intersects(
                            geometry,
                            ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                        )
                        LIMIT %s
                        """,
                        (collection_id, bbox[0], bbox[1], bbox[2], bbox[3], limit)
                    )
                    rows = cur.fetchall()
                    items = [row[0] for row in rows]

                    logger.info(f"Retrieved {len(items)} items from '{collection_id}' within bbox {bbox}")
                    return items

        except (psycopg.Error, OSError) as e:
            logger.warning(f"Error querying items by bbox: {e}")
            return []

    def insert_item(self, item, collection_id: str) -> Dict[str, Any]:
        """
        Insert STAC Item into PgSTAC.

        Args:
            item: stac-pydantic Item (already validated) or dict
            collection_id: Collection to insert item into

        Returns:
            Insertion result from PgSTAC

        Example:
            from stac_pydantic import Item
            item = Item(**item_dict)
            result = stac.insert_item(item, 'dev')
        """
        # Convert stac-pydantic Item to dict if needed
        if hasattr(item, 'model_dump'):
            item_dict = item.model_dump(mode='json', by_alias=True)
        else:
            item_dict = item

        item_id = item_dict.get('id', 'unknown')
        logger.info(f"Inserting STAC Item '{item_id}' into collection '{collection_id}'")

        # =========================================================================
        # DEBUG LOGGING (13 NOV 2025): Investigate missing STAC fields in queries
        # =========================================================================
        logger.debug(f"🔍 DEBUG: STAC Item BEFORE pgSTAC insertion:")
        logger.debug(f"   Item ID: {item_dict.get('id', '❌ MISSING')}")
        logger.debug(f"   Type: {item_dict.get('type', '❌ MISSING')}")
        logger.debug(f"   Collection: {item_dict.get('collection', '❌ MISSING')}")
        logger.debug(f"   Geometry: {'✅ ' + item_dict['geometry']['type'] if item_dict.get('geometry') else '❌ MISSING'}")
        logger.debug(f"   STAC Version: {item_dict.get('stac_version', '❌ MISSING')}")
        logger.debug(f"   Bbox: {'✅ Present' if item_dict.get('bbox') else '❌ MISSING'}")
        logger.debug(f"   Total keys in item_dict: {len(item_dict)}")
        logger.debug(f"   Keys: {list(item_dict.keys())}")

        # Log first 500 chars of JSON being sent to pgSTAC
        item_json = json.dumps(item_dict)
        logger.debug(f"   JSON length: {len(item_json)} chars")
        logger.debug(f"   JSON preview (first 500 chars): {item_json[:500]}")
        # =========================================================================

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM pgstac.create_item(%s)",
                        [item_json]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    # DEBUG: Log what pgSTAC returned
                    logger.debug(f"🔍 DEBUG: pgSTAC create_item() returned: {result}")

                    logger.info(f"✅ STAC Item inserted: {item_id} → {collection_id}")
                    return {
                        'success': True,
                        'item_id': item_id,
                        'collection': collection_id,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to insert STAC Item '{item_id}': {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'item_id': item_id,
                'collection': collection_id
            }

    def collection_exists(self, collection_id: str) -> bool:
        """
        Check if a STAC collection exists in PgSTAC.

        CRITICAL (12 NOV 2025): PgSTAC requires collections to exist BEFORE inserting items
        because collections create partitions that items use. Without the collection,
        item insertion fails with: "no partition of relation 'items' found for row"

        Args:
            collection_id: Collection ID to check

        Returns:
            True if collection exists in pgstac.collections, False otherwise

        Example:
            if not stac.collection_exists('my_collection'):
                raise RuntimeError("Collection must exist before inserting items")
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s) as exists",
                        (collection_id,)
                    )
                    exists = cur.fetchone()['exists']
                    logger.debug(f"Collection '{collection_id}' exists: {exists}")
                    return exists
        except Exception as e:
            logger.error(f"❌ Error checking collection existence for '{collection_id}': {e}")
            return False

    def bulk_insert_items(self, items: list, collection_id: str) -> Dict[str, Any]:
        """
        Bulk insert STAC Items into PgSTAC.

        Args:
            items: List of stac-pydantic Items or dicts
            collection_id: Collection to insert items into

        Returns:
            Bulk insertion results with counts

        Example:
            items = [item1, item2, item3]
            result = stac.bulk_insert_items(items, 'cogs')
        """
        logger.info(f"Bulk inserting {len(items)} STAC Items into '{collection_id}'")

        inserted = []
        failed = []

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for item in items:
                    # Convert to dict if needed
                    if hasattr(item, 'model_dump'):
                        item_dict = item.model_dump(mode='json', by_alias=True)
                    else:
                        item_dict = item

                    item_id = item_dict.get('id', 'unknown')

                    try:
                        cur.execute(
                            "SELECT * FROM pgstac.create_item(%s)",
                            [json.dumps(item_dict)]
                        )
                        result = cur.fetchone()
                        inserted.append(item_id)
                        logger.debug(f"✅ Inserted: {item_id}")

                    except Exception as e:
                        failed.append({'item_id': item_id, 'error': str(e)})
                        logger.error(f"❌ Failed: {item_id} - {e}")

                conn.commit()

        logger.info(f"Bulk insert complete: {len(inserted)} succeeded, {len(failed)} failed")

        return {
            'success': len(failed) == 0,
            'inserted_count': len(inserted),
            'failed_count': len(failed),
            'inserted_items': inserted,
            'failed_items': failed,
            'collection': collection_id
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def check_stac_installation() -> Dict[str, Any]:
    """
    Quick check if STAC is installed (for startup validation).

    Returns:
        Installation status dict
    """
    return PgStacBootstrap().check_installation()


def install_stac(drop_existing: bool = False) -> Dict[str, Any]:
    """
    Install PgSTAC (for setup endpoints).

    Args:
        drop_existing: Drop schema before install (DESTRUCTIVE!)

    Returns:
        Installation results dict
    """
    return PgStacBootstrap().install_pgstac(drop_existing=drop_existing)


# ============================================================================
# STAC API QUERY METHODS (18 OCT 2025)
# ============================================================================
# STAC API standard endpoints for reading from pgstac schema
# These follow STAC API specification for interoperability
# ============================================================================

def get_collection(collection_id: str, repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get single STAC collection by ID (STAC API standard endpoint).

    Implements: GET /collections/{collection_id}

    Args:
        collection_id: Collection identifier
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        STAC Collection object or error dict
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # CRITICAL FIX (13 NOV 2025): pgSTAC 0.9.8 doesn't have get_collection() function
                # Use direct table query instead - returns collection JSONB from content column
                # Pattern matches pgSTAC 0.9.8 standard approach
                cur.execute(
                    "SELECT content FROM pgstac.collections WHERE id = %s",
                    [collection_id]
                )
                result = cur.fetchone()

                if result and result['content']:
                    return result['content']  # Return collection JSONB content
                else:
                    return {
                        'error': f"Collection '{collection_id}' not found",
                        'error_type': 'NotFound'
                    }

    except Exception as e:
        logger.error(f"Failed to get collection '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collection_items(
    collection_id: str,
    limit: int = 100,
    bbox: Optional[List[float]] = None,
    datetime_str: Optional[str] = None,
    repo: Optional['PostgreSQLRepository'] = None
) -> Dict[str, Any]:
    """
    Get items in a collection (STAC API standard endpoint).

    Implements: GET /collections/{collection_id}/items

    Args:
        collection_id: Collection identifier
        limit: Maximum number of items to return (default 100)
        bbox: Bounding box filter [minx, miny, maxx, maxy]
        datetime_str: Datetime filter (RFC 3339 or interval)
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        # Build search parameters (STAC search syntax)
        search_params = {
            'collections': [collection_id],
            'limit': limit
        }

        if bbox:
            search_params['bbox'] = bbox

        if datetime_str:
            search_params['datetime'] = datetime_str

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Query items directly from pgstac.items table
                # CRITICAL (13 NOV 2025): pgSTAC stores id, collection, geometry in separate columns
                # We must reconstruct the full STAC item by merging columns with content JSONB
                query = """
                    SELECT jsonb_build_object(
                        'type', 'FeatureCollection',
                        'features', COALESCE(jsonb_agg(
                            -- Merge separate columns into content JSONB for complete STAC item
                            content ||
                            jsonb_build_object(
                                'id', id,
                                'collection', collection,
                                'geometry', ST_AsGeoJSON(geometry)::jsonb,
                                'type', 'Feature',
                                'stac_version', COALESCE(content->>'stac_version', '1.0.0')
                            )
                        ), '[]'::jsonb),
                        'links', '[]'::jsonb
                    )
                    FROM (
                        SELECT id, collection, geometry, content
                        FROM pgstac.items
                        WHERE collection = %s
                        ORDER BY datetime DESC
                        LIMIT %s
                    ) items
                """
                cur.execute(query, [collection_id, limit])
                result = cur.fetchone()

                # CRITICAL (19 NOV 2025): fetchone() with RealDictCursor returns dict, not tuple
                # The jsonb_build_object() result is in the 'jsonb_build_object' column
                if result and 'jsonb_build_object' in result:
                    return result['jsonb_build_object']  # Returns GeoJSON FeatureCollection
                else:
                    # Empty FeatureCollection
                    return {
                        'type': 'FeatureCollection',
                        'features': [],
                        'links': []
                    }

    except Exception as e:
        logger.error(f"Failed to get items for collection '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def search_items(
    collections: Optional[List[str]] = None,
    bbox: Optional[List[float]] = None,
    datetime_str: Optional[str] = None,
    limit: int = 100,
    query: Optional[Dict[str, Any]] = None,
    repo: Optional['PostgreSQLRepository'] = None
) -> Dict[str, Any]:
    """
    Search items across collections (STAC API standard endpoint).

    Implements: GET /search (also supports POST)

    Args:
        collections: List of collection IDs to search
        bbox: Bounding box [minx, miny, maxx, maxy]
        datetime_str: Datetime filter (RFC 3339 or interval)
        limit: Maximum items to return (default 100)
        query: Additional query parameters (STAC query extension)
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        # Build search parameters
        search_params = {'limit': limit}

        if collections:
            search_params['collections'] = collections

        if bbox:
            search_params['bbox'] = bbox

        if datetime_str:
            search_params['datetime'] = datetime_str

        if query:
            search_params['query'] = query

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Query items directly from pgstac.items table (simpler than search())
                # NOTE: pgstac.search() requires 'searches' table which may not be set up
                logger.debug(f"STAC search - collections: {collections}, limit: {limit}")

                # Build WHERE clause
                where_clauses = []
                params = []

                if collections:
                    where_clauses.append("collection = ANY(%s)")
                    params.append(collections)

                where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

                query = f"""
                    SELECT jsonb_build_object(
                        'type', 'FeatureCollection',
                        'features', COALESCE(jsonb_agg(content), '[]'::jsonb),
                        'links', '[]'::jsonb
                    )
                    FROM (
                        SELECT content
                        FROM pgstac.items
                        WHERE {where_sql}
                        ORDER BY datetime DESC
                        LIMIT %s
                    ) items
                """
                params.append(limit)

                cur.execute(query, params)
                result = cur.fetchone()

                # CRITICAL (19 NOV 2025): fetchone() with RealDictCursor returns dict, not tuple
                # The jsonb_build_object() result is in the 'jsonb_build_object' column
                if result and 'jsonb_build_object' in result:
                    return result['jsonb_build_object']  # Returns GeoJSON FeatureCollection
                else:
                    # Empty FeatureCollection
                    return {
                        'type': 'FeatureCollection',
                        'features': [],
                        'links': []
                    }

    except Exception as e:
        logger.error(f"Failed to search items: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


# =============================================================================
# STAC DATA CLEARING (DEV/TEST ONLY) - Added 29 OCT 2025
# =============================================================================

def clear_stac_data(mode: str = 'all') -> Dict[str, Any]:
    """
    Clear STAC data from pgstac tables (DEV/TEST ONLY).

    ⚠️ DESTRUCTIVE OPERATION - Deletes data but preserves schema structure.

    Args:
        mode: Clearing mode
              'items' - Delete only items (preserve collections)
              'collections' - Delete collections (CASCADE deletes items)
              'all' - Delete both collections and items (default)

    Returns:
        Dict with deletion results:
        {
            'success': True,
            'mode': 'all',
            'deleted': {
                'items': 1234,
                'collections': 5
            },
            'execution_time_ms': 456.78
        }

    Note:
        - Preserves pgstac schema structure
        - Preserves functions, indexes, partitions
        - Much faster than full schema drop/recreate
        - CASCADE automatically handles foreign key relationships

    
    Date: 29 OCT 2025
    """
    import time

    config = get_config()
    start_time = time.time()

    try:
        # Get counts before deletion
        # ARCHITECTURE PRINCIPLE (24 NOV 2025): Use PostgreSQLRepository for managed identity support
        # PostgreSQLRepository handles both managed identity tokens and password-based auth
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Get pre-deletion counts
                # NOTE: PostgreSQLRepository uses dict_row factory, so results are dicts
                cur.execute("SELECT COUNT(*) as cnt FROM pgstac.items")
                items_before = cur.fetchone()['cnt']

                cur.execute("SELECT COUNT(*) as cnt FROM pgstac.collections")
                collections_before = cur.fetchone()['cnt']

                logger.info(f"🚨 STAC NUKE - Mode: {mode}")
                logger.info(f"   Items before: {items_before}")
                logger.info(f"   Collections before: {collections_before}")

                deleted = {'items': 0, 'collections': 0}

                if mode == 'items':
                    # Delete items only (preserve collections)
                    logger.warning("💣 Deleting all STAC items...")
                    cur.execute("DELETE FROM pgstac.items")
                    deleted['items'] = items_before
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['items']} items")

                elif mode == 'collections':
                    # Delete collections (CASCADE deletes items automatically)
                    logger.warning("💣 Deleting all STAC collections (CASCADE to items)...")
                    cur.execute("DELETE FROM pgstac.collections")
                    deleted['collections'] = collections_before
                    deleted['items'] = items_before  # CASCADE deleted
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['collections']} collections")
                    logger.info(f"✅ CASCADE deleted {deleted['items']} items")

                elif mode == 'all':
                    # Delete everything (collections CASCADE to items)
                    logger.warning("💣 Deleting all STAC collections and items...")
                    cur.execute("DELETE FROM pgstac.collections")
                    deleted['collections'] = collections_before
                    deleted['items'] = items_before  # CASCADE deleted
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['collections']} collections")
                    logger.info(f"✅ CASCADE deleted {deleted['items']} items")

                else:
                    return {
                        'success': False,
                        'error': f"Invalid mode: {mode}. Must be 'items', 'collections', or 'all'"
                    }

                execution_time_ms = (time.time() - start_time) * 1000

                return {
                    'success': True,
                    'mode': mode,
                    'deleted': deleted,
                    'counts_before': {
                        'items': items_before,
                        'collections': collections_before
                    },
                    'execution_time_ms': round(execution_time_ms, 2),
                    'warning': '⚠️ DEV/TEST ONLY - STAC data cleared (schema preserved)'
                }

    except Exception as e:
        logger.error(f"Failed to clear STAC data: {e}")
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


# ============================================================================
# PGSTAC SCHEMA INSPECTION (2 NOV 2025)
# ============================================================================
# Deep inspection endpoints for pgstac schema health and statistics
# ============================================================================

def get_schema_info(repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get detailed information about pgstac schema structure.

    Queries PostgreSQL system catalogs to inspect:
    - Tables and their sizes
    - Indexes
    - Functions
    - Partitions
    - Roles

    Args:
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        Dict with comprehensive schema information
    """
    logger.info("🔍 Inspecting pgstac schema structure...")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Get PgSTAC version
                version = None
                try:
                    cur.execute("SELECT pgstac.get_version() as version")
                    version = cur.fetchone()['version']
                except psycopg.Error:
                    version = "unknown"

                # Get table information with sizes
                cur.execute("""
                    SELECT
                        t.tablename,
                        pg_total_relation_size(quote_ident(t.schemaname) || '.' || quote_ident(t.tablename)) / 1024.0 / 1024.0 as size_mb,
                        (SELECT COUNT(*) FROM information_schema.columns
                         WHERE table_schema = t.schemaname AND table_name = t.tablename) as column_count
                    FROM pg_tables t
                    WHERE t.schemaname = 'pgstac'
                    ORDER BY pg_total_relation_size(quote_ident(t.schemaname) || '.' || quote_ident(t.tablename)) DESC
                """)
                tables_raw = cur.fetchall()

                tables = {}
                for row in tables_raw:
                    table_name = row['tablename']
                    size_mb = row['size_mb']
                    col_count = row['column_count']
                    # Get row count for each table
                    try:
                        cur.execute(
                            sql.SQL("SELECT COUNT(*) as count FROM {}").format(
                                sql.Identifier('pgstac', table_name)
                            )
                        )
                        row_count = cur.fetchone()['count']
                    except psycopg.Error:
                        row_count = None

                    # Get indexes for this table
                    cur.execute("""
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'pgstac' AND tablename = %s
                    """, [table_name])
                    indexes = [r['indexname'] for r in cur.fetchall()]

                    tables[table_name] = {
                        'row_count': row_count,
                        'size_mb': round(size_mb, 2),
                        'column_count': col_count,
                        'indexes': indexes
                    }

                # Get functions
                cur.execute("""
                    SELECT routine_name
                    FROM information_schema.routines
                    WHERE routine_schema = 'pgstac'
                    ORDER BY routine_name
                """)
                functions = [row['routine_name'] for row in cur.fetchall()]

                # Get roles
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                )
                roles = [row['rolname'] for row in cur.fetchall()]

                # Get total schema size
                cur.execute("""
                    SELECT
                        pg_size_pretty(SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)))) as total_size,
                        SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename))) / 1024.0 / 1024.0 as total_size_mb
                    FROM pg_tables
                    WHERE schemaname = 'pgstac'
                """)
                size_data = cur.fetchone()

                logger.info(f"✅ Schema inspection complete: {len(tables)} tables, {len(functions)} functions")

                return {
                    'schema': 'pgstac',
                    'version': version,
                    'total_size': size_data['total_size'] if size_data else 'unknown',
                    'total_size_mb': round(size_data['total_size_mb'], 2) if size_data else 0,
                    'tables': tables,
                    'table_count': len(tables),
                    'function_count': len(functions),
                    'functions': functions[:20],  # First 20 functions
                    'roles': roles
                }

    except Exception as e:
        logger.error(f"❌ Schema inspection failed: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collection_stats(collection_id: str, repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get detailed statistics for a specific STAC collection.

    Args:
        collection_id: Collection ID to analyze
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        Dict with collection statistics including:
        - Item count
        - Total size
        - Spatial extent (actual bbox from items)
        - Temporal extent
        - Asset types and counts
        - Recent items
    """
    logger.info(f"📊 Getting statistics for collection '{collection_id}'...")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if collection exists
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s) as exists",
                    [collection_id]
                )
                if not cur.fetchone()['exists']:
                    return {
                        'error': f"Collection '{collection_id}' not found",
                        'collection_id': collection_id
                    }

                # Get collection metadata
                cur.execute(
                    "SELECT content FROM pgstac.collections WHERE id = %s",
                    [collection_id]
                )
                collection_data = cur.fetchone()
                collection_json = collection_data['content'] if collection_data else {}

                # Get item count
                cur.execute(
                    "SELECT COUNT(*) as count FROM pgstac.items WHERE collection = %s",
                    [collection_id]
                )
                item_count = cur.fetchone()['count']

                # Get spatial extent (actual bbox from items)
                cur.execute("""
                    SELECT
                        ST_XMin(ST_Extent(geometry)) as xmin,
                        ST_YMin(ST_Extent(geometry)) as ymin,
                        ST_XMax(ST_Extent(geometry)) as xmax,
                        ST_YMax(ST_Extent(geometry)) as ymax
                    FROM pgstac.items
                    WHERE collection = %s AND geometry IS NOT NULL
                """, [collection_id])
                bbox_data = cur.fetchone()
                actual_bbox = None
                if bbox_data and bbox_data[0] is not None:
                    actual_bbox = [float(x) for x in bbox_data]

                # Get temporal extent
                cur.execute("""
                    SELECT
                        MIN(datetime) as earliest,
                        MAX(datetime) as latest
                    FROM pgstac.items
                    WHERE collection = %s AND datetime IS NOT NULL
                """, [collection_id])
                temporal_data = cur.fetchone()

                # Get asset types
                cur.execute("""
                    SELECT
                        jsonb_object_keys(content->'assets') as asset_key,
                        COUNT(*) as count
                    FROM pgstac.items
                    WHERE collection = %s
                    GROUP BY asset_key
                """, [collection_id])
                assets = {row['asset_key']: row['count'] for row in cur.fetchall()}

                # Get recent items (last 5)
                cur.execute("""
                    SELECT id, content->>'datetime' as datetime
                    FROM pgstac.items
                    WHERE collection = %s
                    ORDER BY datetime DESC NULLS LAST
                    LIMIT 5
                """, [collection_id])
                recent_items = [
                    {'id': row['id'], 'datetime': row['datetime']}
                    for row in cur.fetchall()
                ]

                logger.info(f"✅ Collection '{collection_id}' stats: {item_count} items")

                return {
                    'collection_id': collection_id,
                    'title': collection_json.get('title'),
                    'description': collection_json.get('description'),
                    'item_count': item_count,
                    'spatial_extent': {
                        'bbox': actual_bbox,
                        'configured_bbox': collection_json.get('extent', {}).get('spatial', {}).get('bbox', [[]])
                    },
                    'temporal_extent': {
                        'start': temporal_data[0].isoformat() if temporal_data and temporal_data[0] else None,
                        'end': temporal_data[1].isoformat() if temporal_data and temporal_data[1] else None,
                        'span_days': (temporal_data[1] - temporal_data[0]).days if temporal_data and temporal_data[0] and temporal_data[1] else None
                    },
                    'assets': assets,
                    'recent_items': recent_items,
                    'has_items': item_count > 0
                }

    except Exception as e:
        logger.error(f"❌ Failed to get collection stats for '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__,
            'collection_id': collection_id
        }


def get_item_by_id(item_id: str, collection_id: Optional[str] = None, repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get a single STAC item by ID.

    Args:
        item_id: STAC item ID
        collection_id: Optional collection ID to narrow search
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        STAC Item JSON or error dict
    """
    logger.info(f"🔍 Looking up item '{item_id}'" + (f" in collection '{collection_id}'" if collection_id else ""))

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # CRITICAL (13 NOV 2025): Reconstruct full STAC item from separate columns + content
                # pgSTAC stores id, collection, geometry separately from content JSONB
                if collection_id:
                    # Search in specific collection
                    cur.execute(
                        """SELECT content ||
                           jsonb_build_object(
                               'id', id,
                               'collection', collection,
                               'geometry', ST_AsGeoJSON(geometry)::jsonb,
                               'type', 'Feature',
                               'stac_version', COALESCE(content->>'stac_version', '1.0.0')
                           )
                           FROM pgstac.items WHERE id = %s AND collection = %s""",
                        [item_id, collection_id]
                    )
                else:
                    # Search across all collections
                    cur.execute(
                        """SELECT content ||
                           jsonb_build_object(
                               'id', id,
                               'collection', collection,
                               'geometry', ST_AsGeoJSON(geometry)::jsonb,
                               'type', 'Feature',
                               'stac_version', COALESCE(content->>'stac_version', '1.0.0')
                           )
                           FROM pgstac.items WHERE id = %s""",
                        [item_id]
                    )

                result = cur.fetchone()

                if result:
                    logger.info(f"✅ Found item '{item_id}'")
                    return result[0]  # Return STAC Item JSON (now with all required fields)
                else:
                    logger.warning(f"⚠️ Item '{item_id}' not found")
                    return {
                        'error': f"Item '{item_id}' not found" + (f" in collection '{collection_id}'" if collection_id else ""),
                        'item_id': item_id,
                        'collection_id': collection_id
                    }

    except Exception as e:
        logger.error(f"❌ Failed to get item '{item_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__,
            'item_id': item_id
        }


def get_health_metrics(repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get overall pgstac health metrics.

    Args:
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        Dict with health status, counts, and performance indicators
    """
    logger.info("🏥 Checking pgstac health...")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check schema exists
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'pgstac') as exists"
                )
                schema_exists = cur.fetchone()['exists']

                if not schema_exists:
                    return {
                        'status': 'unhealthy',
                        'schema_exists': False,
                        'message': 'pgstac schema does not exist'
                    }

                # Get version
                try:
                    cur.execute("SELECT pgstac.get_version() as version")
                    version = cur.fetchone()['version']
                except psycopg.Error:
                    version = "unknown"

                # Get counts
                cur.execute("SELECT COUNT(*) as count FROM pgstac.collections")
                collections_count = cur.fetchone()['count']

                cur.execute("SELECT COUNT(*) as count FROM pgstac.items")
                items_count = cur.fetchone()['count']

                # Get database size
                cur.execute("""
                    SELECT
                        SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename))) / 1024.0 / 1024.0 as size_mb
                    FROM pg_tables
                    WHERE schemaname = 'pgstac'
                """)
                db_size_mb = round(cur.fetchone()['size_mb'], 2)

                # Check for issues
                issues = []
                if items_count == 0 and collections_count > 0:
                    issues.append("Collections exist but no items found")

                status = 'healthy' if schema_exists and not issues else 'warning'

                logger.info(f"✅ Health check complete: {status}")

                return {
                    'status': status,
                    'schema_exists': schema_exists,
                    'version': version,
                    'collections_count': collections_count,
                    'items_count': items_count,
                    'database_size_mb': db_size_mb,
                    'issues': issues,
                    'message': f"PgSTAC {version} - {collections_count} collections, {items_count} items"
                }

    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collections_summary(repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get quick summary of all collections with key statistics.

    Args:
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        Dict with summary statistics for all collections
    """
    logger.info("📋 Getting collections summary...")

    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Get all collections with item counts
                cur.execute("""
                    SELECT
                        c.id,
                        c.content->>'title' as title,
                        c.content->>'description' as description,
                        COUNT(i.id) as item_count,
                        MAX(i.datetime) as last_updated
                    FROM pgstac.collections c
                    LEFT JOIN pgstac.items i ON i.collection = c.id
                    GROUP BY c.id, c.content
                    ORDER BY c.id
                """)

                collections = []
                total_items = 0

                for row in cur.fetchall():
                    coll_id = row['id']
                    title = row['title']
                    description = row['description']
                    item_count = row['item_count']
                    last_updated = row['last_updated']
                    total_items += item_count

                    collections.append({
                        'id': coll_id,
                        'title': title,
                        'description': description[:100] + '...' if description and len(description) > 100 else description,
                        'item_count': item_count,
                        'last_updated': last_updated.isoformat() if last_updated else None
                    })

                logger.info(f"✅ Collections summary: {len(collections)} collections, {total_items} total items")

                return {
                    'total_collections': len(collections),
                    'total_items': total_items,
                    'collections': collections
                }

    except Exception as e:
        logger.error(f"❌ Failed to get collections summary: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_all_collections(repo: Optional['PostgreSQLRepository'] = None) -> Dict[str, Any]:
    """
    Get all collections in STAC API v1.0.0 compliant format.

    Returns collections with full STAC-spec metadata including spatial/temporal extents
    and navigation links. Used by GET /collections endpoint.

    Args:
        repo: Optional PostgreSQLRepository instance (creates new if not provided)

    Returns:
        Dict with 'collections' array and 'links' array

    Example response:
        {
            "collections": [
                {
                    "id": "system-rasters",
                    "type": "Collection",
                    "title": "System Rasters",
                    "description": "...",
                    "stac_version": "1.0.0",
                    "license": STACDefaults.DEFAULT_LICENSE,
                    "extent": {
                        "spatial": {"bbox": [...]},
                        "temporal": {"interval": [...]}
                    },
                    "links": [...]
                }
            ],
            "links": [
                {"rel": "self", "href": "..."},
                {"rel": "root", "href": "..."}
            ]
        }
    """
    try:
        # Use repository pattern (16 NOV 2025 - managed identity support)
        if repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            repo = PostgreSQLRepository()

        # Base URL for STAC API
        base_url = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"

        # Query all collections with full content AND item counts
        query = """
            SELECT
                c.id,
                c.content,
                COUNT(i.id) as item_count
            FROM pgstac.collections c
            LEFT JOIN pgstac.items i ON i.collection = c.id
            GROUP BY c.id, c.content
            ORDER BY c.id;
        """

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()

        collections = []
        for row in rows:
            collection_id = row['id']
            content = row['content']
            item_count = row['item_count']

            # Inject item count into summaries field
            if 'summaries' not in content:
                content['summaries'] = {}
            content['summaries']['total_items'] = item_count

            # Add self and root links to each collection
            if 'links' not in content:
                content['links'] = []

            # Ensure required links exist
            has_self = any(link.get('rel') == 'self' for link in content['links'])
            has_root = any(link.get('rel') == 'root' for link in content['links'])
            has_parent = any(link.get('rel') == 'parent' for link in content['links'])
            has_items = any(link.get('rel') == 'items' for link in content['links'])

            if not has_self:
                content['links'].insert(0, {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"{base_url}/collections/{collection_id}"
                })

            if not has_root:
                content['links'].insert(1, {
                    "rel": "root",
                    "type": "application/json",
                    "href": base_url
                })

            if not has_parent:
                content['links'].append({
                    "rel": "parent",
                    "type": "application/json",
                    "href": base_url
                })

            if not has_items:
                content['links'].append({
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": f"{base_url}/collections/{collection_id}/items"
                })

            collections.append(content)

        # Return STAC-compliant collections response
        return {
            "collections": collections,
            "links": [
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"{base_url}/collections"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": base_url
                }
            ]
        }

    except Exception as e:
        logger.error(f"Error in get_all_collections: {e}", exc_info=True)
        base_url = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"
        return {
            'collections': [],
            'links': [
                {"rel": "self", "type": "application/json", "href": f"{base_url}/collections"},
                {"rel": "root", "type": "application/json", "href": base_url}
            ],
            'error': str(e),
            'error_type': type(e).__name__
        }


# =============================================================================
# MODULE-LEVEL HELPER FUNCTIONS
# =============================================================================

def get_system_stac_collections() -> List[Dict[str, Any]]:
    """
    Get STAC collection definitions for system collections (system-vectors, system-rasters).

    This function returns the collection definitions needed to create the system
    STAC collections after a full schema rebuild. These collections track operational
    data created by ETL processes.

    Returns:
        List of STAC collection dictionaries ready for insertion via pgstac.create_collection

    Used by:
        - triggers/admin/db_maintenance.py full_rebuild endpoint (Step 6)

    Date: 25 NOV 2025
    """
    system_collections = []

    # Only create system collections (system-vectors, system-rasters)
    # Other collections (cogs, vectors, geoparquet, dev) are created on-demand
    # Use only the first 2 system collections (vectors and rasters)
    # system-h3-grids is created on-demand by H3 jobs
    system_collection_types = STACDefaults.SYSTEM_COLLECTIONS[:2]

    for collection_type in system_collection_types:
        if collection_type in PgStacBootstrap.PRODUCTION_COLLECTIONS:
            config = PgStacBootstrap.PRODUCTION_COLLECTIONS[collection_type]

            collection = {
                "id": collection_type,
                "type": "Collection",
                "stac_version": "1.0.0",
                "title": config['title'],
                "description": config['description'],
                "license": STACDefaults.DEFAULT_LICENSE,
                "extent": {
                    "spatial": {"bbox": [[-180, -90, 180, 90]]},
                    "temporal": {"interval": [[None, None]]}
                },
                "summaries": {
                    "asset_type": [config['asset_type']],
                    "media_type": [config['media_type']]
                }
            }
            system_collections.append(collection)

    return system_collections
