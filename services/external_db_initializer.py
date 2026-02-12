# ============================================================================
# EXTERNAL DATABASE INITIALIZER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - External database initialization for B2B/partner databases
# PURPOSE: Initialize target databases with pgstac and geo schemas using
#          user-specified admin UMI (not app's production identity)
# CREATED: 21 JAN 2026
# EXPORTS: ExternalDatabaseInitializer, get_external_db_initializer
# DEPENDENCIES: azure-identity, psycopg, pypgstac
# ============================================================================
"""
External Database Initializer Service.

Provides a workflow to initialize EXTERNAL databases with pgstac and geo schemas.
This is a SETUP operation run by DevOps using a temporary admin identity - the
production app will NOT have write access to external databases.

Key Design Principles:
    - Uses USER-SPECIFIED admin UMI (not app config)
    - Target database params passed as arguments (not from app config)
    - Idempotent operations (safe to run multiple times)
    - Dry-run mode for validation before execution
    - Full audit logging

Architecture:
    ┌─────────────────────────────────────────────────────────────────────┐
    │  POST /api/admin/external/initialize                                │
    │  {                                                                  │
    │    "target_host": "external-db.postgres.database.azure.com",        │
    │    "target_database": "geodb",                                      │
    │    "admin_umi_client_id": "xxxxxxxx-xxxx-...",  // Temp admin UMI   │
    │    "dry_run": false                                                 │
    │  }                                                                  │
    └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  ExternalDatabaseInitializer                                        │
    │  1. Acquire AAD token using admin_umi_client_id                     │
    │  2. Connect to target database with token                           │
    │  3. Create geo schema (PydanticToSQL.generate_geo_schema_ddl())     │
    │  4. Run pypgstac migrate (subprocess with target DB env vars)       │
    │  5. Return detailed results                                         │
    └─────────────────────────────────────────────────────────────────────┘

Prerequisites (DBA must complete before running):
    1. External PostgreSQL server exists
    2. Admin UMI user created in target database
    3. Admin UMI has CREATE privilege on database
    4. PostGIS extension enabled (service request required)
    5. pgstac_admin, pgstac_ingest, pgstac_read roles created
    6. Admin UMI granted pgstac_* roles WITH ADMIN OPTION

Usage:
    from services.external_db_initializer import ExternalDatabaseInitializer

    initializer = ExternalDatabaseInitializer(
        target_host="external-db.postgres.database.azure.com",
        target_database="geodb",
        admin_umi_client_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    )

    # Dry run first
    result = initializer.initialize(dry_run=True)

    # Actual execution
    result = initializer.initialize(dry_run=False)
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import subprocess
import sys
import os

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ExternalDbInitializer")


# ============================================================================
# DATA CLASSES
# ============================================================================

class InitStepStatus(str, Enum):
    """Status of an initialization step."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


@dataclass
class InitStep:
    """Result of a single initialization step."""
    name: str
    status: InitStepStatus
    message: str = ""
    error: Optional[str] = None
    sql_executed: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExternalInitResult:
    """Complete result of external database initialization."""
    target_host: str
    target_database: str
    admin_umi_client_id: str
    timestamp: str
    dry_run: bool
    success: bool
    steps: List[InitStep] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    dba_prerequisites: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target_host": self.target_host,
            "target_database": self.target_database,
            "admin_umi_client_id": self.admin_umi_client_id[:8] + "...",  # Mask for security
            "timestamp": self.timestamp,
            "dry_run": self.dry_run,
            "success": self.success,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status.value,
                    "message": s.message,
                    "error": s.error,
                    "sql_count": len(s.sql_executed),
                    "details": s.details
                }
                for s in self.steps
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "dba_prerequisites": self.dba_prerequisites,
            "summary": {
                "total_steps": len(self.steps),
                "successful": len([s for s in self.steps if s.status == InitStepStatus.SUCCESS]),
                "failed": len([s for s in self.steps if s.status == InitStepStatus.FAILED]),
                "skipped": len([s for s in self.steps if s.status == InitStepStatus.SKIPPED]),
                "dry_run": len([s for s in self.steps if s.status == InitStepStatus.DRY_RUN])
            }
        }


# ============================================================================
# EXTERNAL DATABASE INITIALIZER
# ============================================================================

class ExternalDatabaseInitializer:
    """
    Initialize external databases with pgstac and geo schemas.

    Uses user-specified admin UMI to create schemas in target database.
    This is a SETUP operation - production app won't have write access.
    """

    # Default port for Azure PostgreSQL
    DEFAULT_PORT = 5432
    DEFAULT_SSLMODE = "require"

    def __init__(
        self,
        target_host: str,
        target_database: str,
        admin_umi_client_id: str,
        admin_umi_name: str,
        target_port: int = DEFAULT_PORT,
        target_sslmode: str = DEFAULT_SSLMODE,
        geo_schema_name: str = "geo"
    ):
        """
        Initialize the external database initializer.

        Args:
            target_host: External database hostname
            target_database: External database name
            admin_umi_client_id: Client ID of admin UMI to use for authentication
            admin_umi_name: Display name of the admin UMI (used as PostgreSQL username)
            target_port: Database port (default: 5432)
            target_sslmode: SSL mode (default: require)
            geo_schema_name: Name for geo schema (default: geo)
        """
        self.target_host = target_host
        self.target_database = target_database
        self.admin_umi_client_id = admin_umi_client_id
        self.target_port = target_port
        self.target_sslmode = target_sslmode
        self.geo_schema_name = geo_schema_name

        # Will be populated by _acquire_admin_token()
        self._admin_token: Optional[str] = None
        self._admin_username: str = admin_umi_name

        logger.info(f"🔧 ExternalDatabaseInitializer created")
        logger.info(f"   Target: {target_host}/{target_database}")
        logger.info(f"   Admin UMI: {admin_umi_client_id[:8]}... ({admin_umi_name})")

    def _acquire_admin_token(self) -> bool:
        """
        Acquire AAD token using the admin UMI.

        Returns:
            True if token acquired successfully, False otherwise
        """
        try:
            from azure.identity import ManagedIdentityCredential

            logger.info(f"🔐 Acquiring AAD token with admin UMI: {self.admin_umi_client_id[:8]}...")

            credential = ManagedIdentityCredential(client_id=self.admin_umi_client_id)
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

            self._admin_token = token.token

            logger.info(f"✅ AAD token acquired successfully (user: {self._admin_username})")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to acquire AAD token: {e}")
            return False

    def _get_connection(self):
        """
        Get a psycopg connection to the target database using admin token.

        Returns:
            psycopg connection object
        """
        import psycopg
        from psycopg.rows import dict_row

        if not self._admin_token:
            raise RuntimeError("Admin token not acquired. Call _acquire_admin_token() first.")

        conn_string = (
            f"host={self.target_host} "
            f"port={self.target_port} "
            f"dbname={self.target_database} "
            f"user={self._admin_username} "
            f"password={self._admin_token} "
            f"sslmode={self.target_sslmode}"
        )

        return psycopg.connect(conn_string, row_factory=dict_row)

    def check_prerequisites(self) -> Dict[str, Any]:
        """
        Check DBA prerequisites for external database initialization.

        Returns:
            Dict with prerequisite status and any required DBA actions
        """
        prereqs = {
            "checked_at": datetime.utcnow().isoformat(),
            "target_host": self.target_host,
            "target_database": self.target_database,
            "ready": False,
            "checks": {},
            "missing": [],
            "dba_sql": []
        }

        try:
            if not self._acquire_admin_token():
                prereqs["checks"]["admin_token"] = False
                prereqs["missing"].append("Cannot acquire admin token - check UMI configuration")
                return prereqs

            prereqs["checks"]["admin_token"] = True

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check 1: Can connect
                    prereqs["checks"]["connection"] = True

                    # Check 2: PostGIS extension
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_extension WHERE extname = 'postgis'
                        ) as exists
                    """)
                    has_postgis = cur.fetchone()['exists']
                    prereqs["checks"]["postgis_extension"] = has_postgis
                    if not has_postgis:
                        prereqs["missing"].append("PostGIS extension not installed")
                        prereqs["dba_sql"].append("CREATE EXTENSION IF NOT EXISTS postgis;")

                    # Check 3: pgstac roles exist
                    pgstac_roles = ["pgstac_admin", "pgstac_ingest", "pgstac_read"]
                    for role in pgstac_roles:
                        cur.execute(
                            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                            (role,)
                        )
                        exists = cur.fetchone()['exists']
                        prereqs["checks"][f"role_{role}"] = exists
                        if not exists:
                            prereqs["missing"].append(f"Role '{role}' does not exist")
                            prereqs["dba_sql"].append(
                                f"DO $$ BEGIN CREATE ROLE {role}; "
                                f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                            )

                    # Check 4: Admin has CREATE privilege
                    cur.execute("""
                        SELECT has_database_privilege(current_user, current_database(), 'CREATE') as can_create
                    """)
                    can_create = cur.fetchone()['can_create']
                    prereqs["checks"]["create_privilege"] = can_create
                    if not can_create:
                        prereqs["missing"].append("Admin UMI lacks CREATE privilege on database")
                        prereqs["dba_sql"].append(
                            f"GRANT CREATE ON DATABASE {self.target_database} TO <admin_umi_name>;"
                        )

            # Determine overall readiness
            prereqs["ready"] = len(prereqs["missing"]) == 0

        except Exception as e:
            prereqs["checks"]["connection"] = False
            prereqs["missing"].append(f"Connection failed: {e}")

        return prereqs

    def initialize(
        self,
        dry_run: bool = False,
        schemas: Optional[List[str]] = None
    ) -> ExternalInitResult:
        """
        Initialize the external database with pgstac and geo schemas.

        Args:
            dry_run: If True, show what would be done without executing
            schemas: List of schemas to initialize. Default: ['geo', 'pgstac']
                    Options: 'geo', 'pgstac'

        Returns:
            ExternalInitResult with detailed step results
        """
        if schemas is None:
            schemas = ['geo', 'pgstac']

        result = ExternalInitResult(
            target_host=self.target_host,
            target_database=self.target_database,
            admin_umi_client_id=self.admin_umi_client_id,
            timestamp=datetime.utcnow().isoformat(),
            dry_run=dry_run,
            success=False
        )

        logger.info("=" * 70)
        logger.info("🚀 EXTERNAL DATABASE INITIALIZATION STARTED")
        logger.info(f"   Target: {self.target_host}/{self.target_database}")
        logger.info(f"   Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
        logger.info(f"   Schemas: {schemas}")
        logger.info("=" * 70)

        try:
            # Step 1: Check prerequisites
            prereqs = self.check_prerequisites()
            result.dba_prerequisites = prereqs

            if not prereqs["ready"]:
                result.errors.append("DBA prerequisites not met")
                result.warnings.append(f"Missing: {prereqs['missing']}")
                step = InitStep(
                    name="check_prerequisites",
                    status=InitStepStatus.FAILED,
                    message="DBA prerequisites not met",
                    error=str(prereqs["missing"]),
                    details=prereqs
                )
                result.steps.append(step)
                return result

            result.steps.append(InitStep(
                name="check_prerequisites",
                status=InitStepStatus.SUCCESS,
                message="All prerequisites met",
                details=prereqs["checks"]
            ))

            # Step 2: Acquire admin token (if not already done in prereqs)
            if not self._admin_token:
                if not self._acquire_admin_token():
                    result.errors.append("Failed to acquire admin token")
                    return result

            # Step 3: Initialize geo schema
            if 'geo' in schemas:
                step = self._initialize_geo_schema(dry_run=dry_run)
                result.steps.append(step)
                if step.status == InitStepStatus.FAILED:
                    result.errors.append(f"Geo schema failed: {step.error}")

            # Step 4: Initialize pgstac schema
            if 'pgstac' in schemas:
                step = self._initialize_pgstac_schema(dry_run=dry_run)
                result.steps.append(step)
                if step.status == InitStepStatus.FAILED:
                    result.errors.append(f"pgSTAC schema failed: {step.error}")

            # Determine overall success
            failed_steps = [s for s in result.steps if s.status == InitStepStatus.FAILED]
            result.success = len(failed_steps) == 0

        except Exception as e:
            logger.error(f"❌ Initialization failed with exception: {e}")
            result.errors.append(str(e))
            result.success = False

        # Log summary
        logger.info("=" * 70)
        logger.info(f"🏁 INITIALIZATION {'COMPLETE' if result.success else 'FAILED'}")
        summary = result.to_dict()["summary"]
        logger.info(f"   Steps: {summary['successful']} succeeded, {summary['failed']} failed")
        if result.errors:
            logger.warning(f"   Errors: {result.errors}")
        logger.info("=" * 70)

        return result

    def _initialize_geo_schema(self, dry_run: bool = False) -> InitStep:
        """
        Initialize geo schema with PostGIS extension and system tables.

        Uses PydanticToSQL.generate_geo_schema_ddl() for DDL generation.
        """
        step = InitStep(
            name="initialize_geo_schema",
            status=InitStepStatus.PENDING
        )

        try:
            from core.schema.sql_generator import PydanticToSQL
            from psycopg import sql

            # Generate DDL from GeoTableCatalog Pydantic model
            generator = PydanticToSQL(schema_name=self.geo_schema_name)
            statements = generator.generate_geo_schema_ddl()

            # Add PostGIS extension statement at the beginning
            postgis_stmt = sql.SQL("CREATE EXTENSION IF NOT EXISTS postgis")

            if dry_run:
                # Just collect SQL without executing
                step.sql_executed.append("CREATE EXTENSION IF NOT EXISTS postgis;")
                with self._get_connection() as conn:
                    for stmt in statements:
                        step.sql_executed.append(stmt.as_string(conn))

                step.status = InitStepStatus.DRY_RUN
                step.message = f"Would execute {len(step.sql_executed)} statements"
                step.details = {"statement_count": len(step.sql_executed)}
            else:
                # Execute DDL
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        # PostGIS extension
                        cur.execute(postgis_stmt)
                        step.sql_executed.append("CREATE EXTENSION IF NOT EXISTS postgis;")

                        # Generated DDL
                        for stmt in statements:
                            cur.execute(stmt)
                            step.sql_executed.append(stmt.as_string(conn)[:100] + "...")

                        conn.commit()

                step.status = InitStepStatus.SUCCESS
                step.message = f"Geo schema '{self.geo_schema_name}' initialized ({len(step.sql_executed)} statements)"
                step.details = {
                    "schema": self.geo_schema_name,
                    "statements_executed": len(step.sql_executed),
                    "tables_created": ["table_catalog"],
                    "source": "PydanticToSQL.generate_geo_schema_ddl()"
                }

        except Exception as e:
            step.status = InitStepStatus.FAILED
            step.error = str(e)
            step.message = f"Failed to initialize geo schema: {e}"
            logger.error(f"❌ Geo schema init failed: {e}")

        return step

    def _initialize_pgstac_schema(self, dry_run: bool = False) -> InitStep:
        """
        Initialize pgSTAC schema using pypgstac migrate.

        Runs pypgstac migrate via subprocess with target database env vars.
        """
        step = InitStep(
            name="initialize_pgstac_schema",
            status=InitStepStatus.PENDING
        )

        try:
            if dry_run:
                step.status = InitStepStatus.DRY_RUN
                step.message = "Would run: pypgstac migrate"
                step.sql_executed.append("-- pypgstac migrate (creates pgstac schema, tables, functions)")
                step.details = {
                    "command": [sys.executable, "-m", "pypgstac.pypgstac", "migrate"],
                    "target_host": self.target_host,
                    "target_database": self.target_database
                }
                return step

            # Build environment for pypgstac
            env = os.environ.copy()
            env.update({
                'PGHOST': self.target_host,
                'PGPORT': str(self.target_port),
                'PGDATABASE': self.target_database,
                'PGUSER': self._admin_username,
                'PGPASSWORD': self._admin_token
            })

            logger.info(f"📦 Running pypgstac migrate on {self.target_host}/{self.target_database}...")

            # Run pypgstac migrate
            result = subprocess.run(
                [sys.executable, '-m', 'pypgstac.pypgstac', 'migrate'],
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                step.sql_executed.append("-- pypgstac migrate completed")
                step.details = {
                    "stdout": result.stdout[:500] if result.stdout else None,
                    "returncode": result.returncode
                }
                logger.info("✅ pypgstac migrate completed successfully")

                # Apply post-migration fixes (search_path for trigger functions)
                # pypgstac 0.9.8 has a bug where partition_after_triggerfunc is
                # created without search_path, causing errors on item deletion
                fixes_applied = self._apply_pgstac_function_fixes()
                step.details["post_migration_fixes"] = fixes_applied

                step.status = InitStepStatus.SUCCESS
                step.message = "pypgstac migrate completed successfully"
            else:
                step.status = InitStepStatus.FAILED
                step.error = result.stderr
                step.message = f"pypgstac migrate failed (exit code {result.returncode})"
                step.details = {
                    "stderr": result.stderr[:1000] if result.stderr else None,
                    "stdout": result.stdout[:500] if result.stdout else None,
                    "returncode": result.returncode
                }
                logger.error(f"❌ pypgstac migrate failed: {result.stderr}")

        except subprocess.TimeoutExpired:
            step.status = InitStepStatus.FAILED
            step.error = "pypgstac migrate timed out after 5 minutes"
            step.message = "Migration timed out"
        except Exception as e:
            step.status = InitStepStatus.FAILED
            step.error = str(e)
            step.message = f"Failed to run pypgstac migrate: {e}"
            logger.error(f"❌ pypgstac migrate exception: {e}")

        return step

    def _apply_pgstac_function_fixes(self) -> List[str]:
        """
        Apply post-migration fixes for pypgstac bugs.

        pypgstac 0.9.8 creates partition_after_triggerfunc without search_path,
        causing "relation partition_sys_meta does not exist" errors.
        Safe to run multiple times (idempotent).

        Returns:
            List of fixes applied
        """
        fixes_applied = []
        functions_to_fix = [
            'partition_after_triggerfunc()',
            'collection_delete_trigger_func()',
        ]

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    for func_sig in functions_to_fix:
                        try:
                            cur.execute(
                                f"ALTER FUNCTION pgstac.{func_sig} "
                                f"SET search_path = pgstac, public"
                            )
                            fixes_applied.append(f"pgstac.{func_sig}")
                            logger.info(f"  ✅ Fixed search_path for pgstac.{func_sig}")
                        except Exception as e:
                            # Function may not exist in future pypgstac versions
                            logger.warning(f"  ⚠️ Could not fix pgstac.{func_sig}: {e}")
                    conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ Post-migration fixes failed (non-fatal): {e}")

        return fixes_applied
