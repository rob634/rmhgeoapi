# ============================================================================
# CLAUDE CONTEXT - EXTERNAL DATABASE INITIALIZER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - External database initialization using PgStacBootstrap patterns
# PURPOSE: Initialize external databases with pgstac and geo schemas using
#          user-specified admin UMI (not app's production identity)
# LAST_REVIEWED: 10 MAR 2026
# EXPORTS: ExternalDatabaseInitializer, InitStepStatus, InitStep, ExternalInitResult
# DEPENDENCIES: azure-identity, psycopg, pypgstac, core.schema.sql_generator
# ============================================================================
"""
External Database Initializer Service.

Rebuilt 10 MAR 2026 to follow PgStacBootstrap patterns:
- psycopg.sql composition (no f-string SQL)
- 6-check verify_installation()
- No extension creation (DBA prerequisite only)
- GRANT error detection + DBA SQL generation
- drop_existing parameter for rebuilds

Key Design Principles:
    - Uses USER-SPECIFIED admin UMI (not app config)
    - Target database params passed as arguments (not from app config)
    - Idempotent operations (safe to run multiple times)
    - Dry-run mode for validation before execution
    - Full audit logging

Prerequisites (DBA must complete before running):
    1. External PostgreSQL server exists
    2. PostGIS extension enabled (DBA runs: CREATE EXTENSION IF NOT EXISTS postgis)
    3. Admin UMI user created in target database
    4. Admin UMI has CREATE privilege on database
    5. pgstac_admin, pgstac_ingest, pgstac_read roles created
    6. Admin UMI granted pgstac_* roles WITH ADMIN OPTION
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
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
    verification: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target_host": self.target_host,
            "target_database": self.target_database,
            "admin_umi_client_id": self.admin_umi_client_id[:8] + "...",
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
            "verification": self.verification,
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

    Rebuilt 10 MAR 2026 using PgStacBootstrap patterns:
    - psycopg.sql composition throughout (no f-string SQL)
    - verify_installation() with 6 checks
    - No extension creation (DBA prerequisite only)
    - GRANT error detection + DBA SQL generation
    - drop_existing parameter for rebuilds
    """

    DEFAULT_PORT = 5432
    DEFAULT_SSLMODE = "require"
    PGSTAC_SCHEMA = "pgstac"

    # Input validation patterns — prevent connection string injection
    _HOST_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
    _DBNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
    _UMI_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
    _UUID_PATTERN = re.compile(
        r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    )

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
        # Validate inputs before storing
        if not self._HOST_PATTERN.match(target_host):
            raise ValueError(f"Invalid target_host: must match [a-zA-Z0-9._-]+")
        if not self._DBNAME_PATTERN.match(target_database):
            raise ValueError(f"Invalid target_database: must match [a-zA-Z0-9_-]+")
        if not self._UUID_PATTERN.match(admin_umi_client_id):
            raise ValueError(f"Invalid admin_umi_client_id: must be UUID format")
        if not self._UMI_NAME_PATTERN.match(admin_umi_name):
            raise ValueError(f"Invalid admin_umi_name: must match [a-zA-Z0-9_-]+")

        self.target_host = target_host
        self.target_database = target_database
        self.admin_umi_client_id = admin_umi_client_id
        self.target_port = target_port
        self.target_sslmode = target_sslmode
        self.geo_schema_name = geo_schema_name
        self._admin_token: Optional[str] = None
        self._admin_username: str = admin_umi_name

        logger.info(f"ExternalDatabaseInitializer created")
        logger.info(f"   Target: {target_host}/{target_database}")
        logger.info(f"   Admin UMI: {admin_umi_client_id[:8]}... ({admin_umi_name})")

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    def _acquire_admin_token(self) -> bool:
        """Acquire AAD token using the admin UMI."""
        try:
            from azure.identity import ManagedIdentityCredential

            logger.info(f"Acquiring AAD token with admin UMI: {self.admin_umi_client_id[:8]}...")
            credential = ManagedIdentityCredential(client_id=self.admin_umi_client_id)
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            self._admin_token = token.token
            logger.info(f"AAD token acquired (user: {self._admin_username})")
            return True
        except Exception as e:
            logger.error(f"Failed to acquire AAD token: {e}")
            return False

    def _get_connection(self):
        """Get a psycopg connection to the target database using admin token."""
        import psycopg
        from psycopg.rows import dict_row

        if not self._admin_token:
            raise RuntimeError("Admin token not acquired. Call _acquire_admin_token() first.")

        return psycopg.connect(
            host=self.target_host,
            port=self.target_port,
            dbname=self.target_database,
            user=self._admin_username,
            password=self._admin_token,
            sslmode=self.target_sslmode,
            row_factory=dict_row
        )

    # =========================================================================
    # PREREQUISITES CHECK
    # =========================================================================

    def check_prerequisites(self) -> Dict[str, Any]:
        """
        Check DBA prerequisites for external database initialization.

        Does NOT attempt to create extensions — that is a DBA-only operation.
        """
        prereqs = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
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

                    # Check 2: PostGIS extension (DBA must create — we only verify)
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_extension WHERE extname = 'postgis'
                        ) as exists
                    """)
                    has_postgis = cur.fetchone()['exists']
                    prereqs["checks"]["postgis_extension"] = has_postgis
                    if not has_postgis:
                        prereqs["missing"].append(
                            "PostGIS extension not installed — DBA must run: "
                            "CREATE EXTENSION IF NOT EXISTS postgis;"
                        )
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
                        SELECT has_database_privilege(
                            current_user, current_database(), 'CREATE'
                        ) as can_create
                    """)
                    can_create = cur.fetchone()['can_create']
                    prereqs["checks"]["create_privilege"] = can_create
                    if not can_create:
                        prereqs["missing"].append("Admin UMI lacks CREATE privilege on database")
                        prereqs["dba_sql"].append(
                            f'GRANT CREATE ON DATABASE "{self.target_database}" '
                            f'TO "{self._admin_username}";'
                        )

            prereqs["ready"] = len(prereqs["missing"]) == 0

        except Exception as e:
            prereqs["checks"]["connection"] = False
            prereqs["missing"].append(f"Connection failed: {e}")

        return prereqs

    # =========================================================================
    # GEO SCHEMA INITIALIZATION
    # =========================================================================

    def _initialize_geo_schema(self, dry_run: bool = False, drop_existing: bool = False) -> InitStep:
        """
        Initialize geo schema using PydanticToSQL.generate_geo_schema_ddl().

        Does NOT create PostGIS extension — that is a DBA prerequisite.
        Creates 4 tables + indexes: table_catalog, feature_collection_styles,
        b2c_routes, b2b_routes.
        """
        step = InitStep(name="initialize_geo_schema", status=InitStepStatus.PENDING)

        try:
            from core.schema.sql_generator import PydanticToSQL
            from psycopg import sql

            generator = PydanticToSQL(schema_name=self.geo_schema_name)
            statements = generator.generate_geo_schema_ddl()

            if dry_run:
                with self._get_connection() as conn:
                    for stmt in statements:
                        step.sql_executed.append(stmt.as_string(conn))

                step.status = InitStepStatus.DRY_RUN
                step.message = f"Would execute {len(step.sql_executed)} statements"
                step.details = {"statement_count": len(step.sql_executed)}
                return step

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Drop existing schema if requested
                    if drop_existing:
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(self.geo_schema_name)
                        ))
                        step.sql_executed.append(
                            f"DROP SCHEMA IF EXISTS {self.geo_schema_name} CASCADE"
                        )
                        logger.info(f"Dropped existing geo schema '{self.geo_schema_name}'")

                    # Execute generated DDL
                    for stmt in statements:
                        cur.execute(stmt)
                        step.sql_executed.append(stmt.as_string(conn)[:100] + "...")

                    conn.commit()

            step.status = InitStepStatus.SUCCESS
            step.message = (
                f"Geo schema '{self.geo_schema_name}' initialized "
                f"({len(step.sql_executed)} statements)"
            )
            step.details = {
                "schema": self.geo_schema_name,
                "statements_executed": len(step.sql_executed),
                "tables_created": [
                    "table_catalog", "feature_collection_styles",
                    "b2c_routes", "b2b_routes"
                ],
                "drop_existing": drop_existing,
                "source": "PydanticToSQL.generate_geo_schema_ddl()"
            }

        except Exception as e:
            step.status = InitStepStatus.FAILED
            step.error = str(e)
            step.message = f"Failed to initialize geo schema: {e}"
            logger.error(f"Geo schema init failed: {e}")

        return step

    # =========================================================================
    # PGSTAC SCHEMA INITIALIZATION
    # =========================================================================

    def _initialize_pgstac_schema(
        self, dry_run: bool = False, drop_existing: bool = False
    ) -> InitStep:
        """
        Initialize pgSTAC schema using pypgstac migrate.

        Follows PgStacBootstrap._run_pypgstac_migrate() pattern:
        - subprocess with PGHOST/PGPORT/etc env vars
        - GRANT error detection + DBA SQL generation
        - Post-migration function fixes via psycopg.sql composition
        """
        step = InitStep(name="initialize_pgstac_schema", status=InitStepStatus.PENDING)

        try:
            if dry_run:
                step.status = InitStepStatus.DRY_RUN
                step.message = "Would run: pypgstac migrate"
                step.sql_executed.append(
                    "-- pypgstac migrate (creates pgstac schema, tables, functions)"
                )
                step.details = {
                    "command": [sys.executable, "-m", "pypgstac.pypgstac", "migrate"],
                    "target_host": self.target_host,
                    "target_database": self.target_database,
                    "drop_existing": drop_existing
                }
                return step

            # Drop existing pgstac schema if requested
            if drop_existing:
                from psycopg import sql
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(self.PGSTAC_SCHEMA)
                        ))
                        conn.commit()
                step.sql_executed.append(
                    f"DROP SCHEMA IF EXISTS {self.PGSTAC_SCHEMA} CASCADE"
                )
                logger.info(f"Dropped existing pgstac schema")

            # Build environment for pypgstac
            env = os.environ.copy()
            env.update({
                'PGHOST': self.target_host,
                'PGPORT': str(self.target_port),
                'PGDATABASE': self.target_database,
                'PGUSER': self._admin_username,
                'PGPASSWORD': self._admin_token
            })

            logger.info(
                f"Running pypgstac migrate on "
                f"{self.target_host}/{self.target_database}..."
            )

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
                    "returncode": result.returncode,
                    "drop_existing": drop_existing
                }
                logger.info("pypgstac migrate completed successfully")

                # Apply post-migration fixes (psycopg.sql composition)
                fixes_applied = self._apply_pgstac_function_fixes()
                step.details["post_migration_fixes"] = fixes_applied

                step.status = InitStepStatus.SUCCESS
                step.message = "pypgstac migrate completed successfully"
            else:
                # Check for GRANT permission errors
                error_text = result.stderr.lower() if result.stderr else ""
                is_grant_error = (
                    'permission denied' in error_text or
                    'must have admin option' in error_text or
                    ('grant' in error_text and 'pgstac' in error_text)
                )

                step.status = InitStepStatus.FAILED
                step.error = result.stderr
                step.message = (
                    f"pypgstac migrate failed (exit code {result.returncode})"
                )
                step.details = {
                    "stderr": result.stderr[:1000] if result.stderr else None,
                    "stdout": result.stdout[:500] if result.stdout else None,
                    "returncode": result.returncode,
                    "dba_action_required": is_grant_error,
                }

                if is_grant_error:
                    step.details["dba_hint"] = (
                        "GRANT permission error — DBA must pre-create pgstac roles "
                        "and grant them to the admin UMI WITH ADMIN OPTION."
                    )
                    step.details["dba_sql"] = [
                        "DO $$ BEGIN CREATE ROLE pgstac_admin; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
                        "DO $$ BEGIN CREATE ROLE pgstac_ingest; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
                        "DO $$ BEGIN CREATE ROLE pgstac_read; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
                        f'GRANT pgstac_admin TO "{self._admin_username}" '
                        f'WITH ADMIN OPTION;',
                    ]

                logger.error(f"pypgstac migrate failed: {result.stderr}")

        except subprocess.TimeoutExpired:
            step.status = InitStepStatus.FAILED
            step.error = "pypgstac migrate timed out after 5 minutes"
            step.message = "Migration timed out"
        except Exception as e:
            step.status = InitStepStatus.FAILED
            step.error = str(e)
            step.message = f"Failed to run pypgstac migrate: {e}"
            logger.error(f"pypgstac migrate exception: {e}")

        return step

    def _apply_pgstac_function_fixes(self) -> List[str]:
        """
        Apply post-migration fixes using psycopg.sql composition.

        Follows PgStacBootstrap._apply_pgstac_function_fixes() pattern.
        Fixes search_path for trigger functions that reference pgstac tables
        without schema prefix.
        """
        from psycopg import sql

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
                            cur.execute(sql.SQL(
                                "ALTER FUNCTION {}.{} "
                                "SET search_path = pgstac, public"
                            ).format(
                                sql.Identifier(self.PGSTAC_SCHEMA),
                                sql.SQL(func_sig)
                            ))
                            fixes_applied.append(f"pgstac.{func_sig}")
                            logger.info(f"  Fixed search_path for pgstac.{func_sig}")
                        except Exception as e:
                            # Function may not exist in future pypgstac versions
                            logger.warning(
                                f"  Could not fix pgstac.{func_sig}: {e}"
                            )
                    conn.commit()
        except Exception as e:
            logger.warning(f"Post-migration fixes failed (non-fatal): {e}")

        return fixes_applied

    # =========================================================================
    # VERIFICATION (mirrors PgStacBootstrap.verify_installation)
    # =========================================================================

    def _verify_pgstac(self) -> Dict[str, Any]:
        """
        Verify pgSTAC installation — 6 checks matching PgStacBootstrap.

        Checks: schema_exists, version_query, tables_exist,
                roles_configured, search_available, search_hash_functions.
        """
        import psycopg
        from psycopg import sql

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
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Schema exists
                    cur.execute(
                        "SELECT EXISTS("
                        "SELECT 1 FROM pg_namespace WHERE nspname = %s"
                        ") as exists",
                        [self.PGSTAC_SCHEMA]
                    )
                    checks['schema_exists'] = cur.fetchone()['exists']

                    if not checks['schema_exists']:
                        checks['errors'].append("pgstac schema does not exist")
                        checks['valid'] = False
                        return checks

                    # 2. Version query
                    try:
                        cur.execute("SELECT pgstac.get_version() as version")
                        checks['version'] = cur.fetchone()['version']
                        checks['version_query'] = True
                    except psycopg.Error as e:
                        checks['errors'].append(f"Version query failed: {e}")
                        conn.rollback()

                    # 3. Tables exist
                    cur.execute(
                        "SELECT COUNT(*) as count FROM information_schema.tables "
                        "WHERE table_schema = %s",
                        [self.PGSTAC_SCHEMA]
                    )
                    checks['tables_count'] = cur.fetchone()['count']
                    checks['tables_exist'] = checks['tables_count'] > 0

                    if not checks['tables_exist']:
                        checks['errors'].append(
                            f"No tables found in {self.PGSTAC_SCHEMA} schema"
                        )

                    # 4. Roles configured
                    cur.execute(
                        "SELECT rolname FROM pg_roles "
                        "WHERE rolname LIKE 'pgstac_%'"
                    )
                    checks['roles'] = [row['rolname'] for row in cur.fetchall()]
                    checks['roles_configured'] = len(checks['roles']) >= 3

                    if not checks['roles_configured']:
                        checks['errors'].append(
                            f"Expected 3+ pgstac roles, found {len(checks['roles'])}"
                        )

                    # 5. Search function available
                    try:
                        cur.execute("""
                            SELECT COUNT(*) as count FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                            WHERE n.nspname = 'pgstac' AND p.proname = 'search'
                        """)
                        checks['search_available'] = cur.fetchone()['count'] >= 1
                        if not checks['search_available']:
                            checks['errors'].append(
                                "pgstac.search function not found"
                            )
                    except psycopg.Error as e:
                        checks['errors'].append(f"Search function check failed: {e}")
                        conn.rollback()

                    # 6. Search hash functions
                    try:
                        cur.execute("""
                            SELECT COUNT(*) as count FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                            WHERE n.nspname = 'pgstac'
                            AND p.proname IN ('search_tohash', 'search_hash')
                        """)
                        checks['search_hash_functions'] = (
                            cur.fetchone()['count'] == 2
                        )
                        if not checks['search_hash_functions']:
                            checks['errors'].append(
                                "Missing search hash functions (search_tohash, search_hash)"
                            )
                    except psycopg.Error as e:
                        checks['errors'].append(
                            f"Search hash function check failed: {e}"
                        )
                        conn.rollback()

                    checks['valid'] = all([
                        checks['schema_exists'],
                        checks['version_query'],
                        checks['tables_exist'],
                        checks['roles_configured'],
                        checks['search_available'],
                        checks['search_hash_functions'],
                    ])

        except Exception as e:
            checks['errors'].append(str(e))
            checks['valid'] = False

        return checks

    def _verify_geo(self) -> Dict[str, Any]:
        """Verify geo schema — check schema exists, tables, index count."""
        checks = {
            'schema_exists': False,
            'tables': [],
            'table_count': 0,
            'index_count': 0,
            'errors': []
        }

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Schema exists
                    cur.execute(
                        "SELECT EXISTS("
                        "SELECT 1 FROM pg_namespace WHERE nspname = %s"
                        ") as exists",
                        [self.geo_schema_name]
                    )
                    checks['schema_exists'] = cur.fetchone()['exists']

                    if not checks['schema_exists']:
                        checks['errors'].append(
                            f"Schema '{self.geo_schema_name}' does not exist"
                        )
                        checks['valid'] = False
                        return checks

                    # Tables
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                        "ORDER BY table_name",
                        [self.geo_schema_name]
                    )
                    checks['tables'] = [row['table_name'] for row in cur.fetchall()]
                    checks['table_count'] = len(checks['tables'])

                    # Index count
                    cur.execute(
                        "SELECT COUNT(*) as count FROM pg_indexes "
                        "WHERE schemaname = %s",
                        [self.geo_schema_name]
                    )
                    checks['index_count'] = cur.fetchone()['count']

                    checks['valid'] = checks['table_count'] >= 4

                    if not checks['valid']:
                        checks['errors'].append(
                            f"Expected 4+ tables, found {checks['table_count']}"
                        )

        except Exception as e:
            checks['errors'].append(str(e))
            checks['valid'] = False

        return checks

    # =========================================================================
    # TOP-LEVEL ORCHESTRATOR
    # =========================================================================

    def initialize(
        self,
        dry_run: bool = False,
        schemas: Optional[List[str]] = None,
        drop_existing: bool = False
    ) -> ExternalInitResult:
        """
        Initialize the external database with pgstac and geo schemas.

        Orchestrates: prereqs -> geo -> pgstac -> verify.

        Args:
            dry_run: If True, show what would be done without executing
            schemas: List of schemas to initialize. Default: ['geo', 'pgstac']
            drop_existing: If True, drop and recreate schemas (data loss!)
        """
        if schemas is None:
            schemas = ['geo', 'pgstac']

        result = ExternalInitResult(
            target_host=self.target_host,
            target_database=self.target_database,
            admin_umi_client_id=self.admin_umi_client_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            dry_run=dry_run,
            success=False
        )

        logger.info("=" * 70)
        logger.info("EXTERNAL DATABASE INITIALIZATION STARTED")
        logger.info(f"   Target: {self.target_host}/{self.target_database}")
        logger.info(f"   Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
        logger.info(f"   Schemas: {schemas}")
        logger.info(f"   Drop existing: {drop_existing}")
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
                step = self._initialize_geo_schema(
                    dry_run=dry_run, drop_existing=drop_existing
                )
                result.steps.append(step)
                if step.status == InitStepStatus.FAILED:
                    result.errors.append(f"Geo schema failed: {step.error}")

            # Step 4: Initialize pgstac schema
            if 'pgstac' in schemas:
                step = self._initialize_pgstac_schema(
                    dry_run=dry_run, drop_existing=drop_existing
                )
                result.steps.append(step)
                if step.status == InitStepStatus.FAILED:
                    result.errors.append(f"pgSTAC schema failed: {step.error}")

            # Step 5: Verify (only if not dry_run and no failures)
            failed_steps = [
                s for s in result.steps if s.status == InitStepStatus.FAILED
            ]
            if not dry_run and len(failed_steps) == 0:
                verification = {}
                if 'geo' in schemas:
                    verification['geo'] = self._verify_geo()
                if 'pgstac' in schemas:
                    verification['pgstac'] = self._verify_pgstac()
                result.verification = verification

                # Add verification step
                all_valid = all(
                    v.get('valid', False) for v in verification.values()
                )
                result.steps.append(InitStep(
                    name="verify_installation",
                    status=(
                        InitStepStatus.SUCCESS if all_valid
                        else InitStepStatus.FAILED
                    ),
                    message=(
                        "All verification checks passed" if all_valid
                        else "Verification failed"
                    ),
                    details=verification
                ))
                if not all_valid:
                    result.errors.append("Post-initialization verification failed")

            # Determine overall success
            failed_steps = [
                s for s in result.steps if s.status == InitStepStatus.FAILED
            ]
            result.success = len(failed_steps) == 0

        except Exception as e:
            logger.error(f"Initialization failed with exception: {e}")
            result.errors.append(str(e))
            result.success = False

        logger.info("=" * 70)
        logger.info(
            f"INITIALIZATION {'COMPLETE' if result.success else 'FAILED'}"
        )
        summary = result.to_dict()["summary"]
        logger.info(
            f"   Steps: {summary['successful']} succeeded, "
            f"{summary['failed']} failed"
        )
        if result.errors:
            logger.warning(f"   Errors: {result.errors}")
        logger.info("=" * 70)

        return result
