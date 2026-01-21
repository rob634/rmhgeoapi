# ============================================================================
# DATABASE INITIALIZER - CONSOLIDATED INFRASTRUCTURE AS CODE
# ============================================================================
# STATUS: Infrastructure - Database initialization orchestrator
# PURPOSE: Standardized workflow for database initialization with permission
#          verification, schema creation, and default privilege grants
# CREATED: 21 JAN 2026
# ============================================================================
"""
DatabaseInitializer - Consolidated Database Infrastructure as Code.

Provides a standardized workflow for initializing databases with:
1. Permission verification (UMI Reader read access, UMI Admin creates tables)
2. Schema analysis and drift detection (21 JAN 2026)
3. Smart initialization - only creates missing objects
4. Schema creation (geo, pgstac, app, h3)
5. System table initialization
6. Default privilege grants for future tables

Designed for multi-database deployments where we need consistent
initialization across internal and external data databases.

Usage:
    from infrastructure.database_initializer import DatabaseInitializer
    from config import DatabaseConfig

    # Initialize with default (internal) database
    initializer = DatabaseInitializer()
    result = initializer.initialize_all()

    # Analyze schemas before initialization (see what's missing)
    analysis = initializer.analyze_schemas()
    print(analysis)  # Shows drift report

    # Smart initialization - only creates what's missing
    result = initializer.initialize_all(smart_mode=True)

    # Force mode - recreates everything (like before)
    result = initializer.initialize_all(smart_mode=False)

    # Initialize external database
    external_db_config = DatabaseConfig(
        host="external-db.postgres.azure.com",
        database="external_data",
        ...
    )
    initializer = DatabaseInitializer(database_config=external_db_config)
    result = initializer.initialize_all()

    # Initialize specific schemas only
    result = initializer.initialize_schemas(['geo', 'app'])

    # Generate migration report
    report = initializer.generate_migration_report()
    print(report)

Exports:
    DatabaseInitializer: Orchestrator class for database initialization
    InitializationResult: Dataclass for step results
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from psycopg import sql
import traceback

from util_logger import LoggerFactory, ComponentType
from config import get_config, DatabaseConfig

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "DatabaseInitializer")


# ============================================================================
# DATA CLASSES
# ============================================================================

class SchemaType(Enum):
    """Available schema types for initialization."""
    GEO = "geo"
    PGSTAC = "pgstac"
    APP = "app"
    H3 = "h3"


@dataclass
class StepResult:
    """Result of a single initialization step."""
    name: str
    status: str  # 'success', 'failed', 'skipped'
    message: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InitializationResult:
    """Complete result of database initialization."""
    database_host: str
    database_name: str
    timestamp: str
    success: bool
    steps: List[StepResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "database_host": self.database_host,
            "database_name": self.database_name,
            "timestamp": self.timestamp,
            "success": self.success,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "message": s.message,
                    "error": s.error,
                    "details": s.details
                }
                for s in self.steps
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": {
                "total_steps": len(self.steps),
                "successful": len([s for s in self.steps if s.status == "success"]),
                "failed": len([s for s in self.steps if s.status == "failed"]),
                "skipped": len([s for s in self.steps if s.status == "skipped"])
            }
        }


# ============================================================================
# DATABASE INITIALIZER
# ============================================================================

class DatabaseInitializer:
    """
    Consolidated database initialization orchestrator.

    Provides Infrastructure as Code workflow for database setup:
    1. Permission verification
    2. Schema creation
    3. System table initialization
    4. Default privilege grants

    All operations are idempotent (safe to run multiple times).
    Each step runs in its own transaction for durability.
    """

    # Schema creation order (dependencies matter)
    SCHEMA_ORDER = [SchemaType.GEO, SchemaType.APP, SchemaType.PGSTAC, SchemaType.H3]

    def __init__(
        self,
        database_config: Optional[DatabaseConfig] = None,
        admin_identity: Optional[str] = None,
        reader_identity: Optional[str] = None
    ):
        """
        Initialize the database initializer.

        Args:
            database_config: Database configuration. If None, uses default from get_config().
            admin_identity: UMI Admin identity name (creates tables, writes).
                           If None, uses config.database.managed_identity_admin_name
            reader_identity: UMI Reader identity name (read-only access).
                            If None, uses config.database.managed_identity_reader_name
        """
        from infrastructure.postgresql import PostgreSQLRepository

        self.config = get_config()

        # Use provided config or default
        self.database_config = database_config or self.config.database

        # Identity names for permission setup
        self.admin_identity = admin_identity or self.database_config.managed_identity_admin_name
        self.reader_identity = reader_identity or getattr(
            self.database_config, 'managed_identity_reader_name', None
        )

        # Create repository for database operations
        # If custom database_config provided, build connection string
        if database_config:
            self._repo = PostgreSQLRepository(
                connection_string=self._build_connection_string(database_config),
                schema_name='public'  # Start with public for permission checks
            )
        else:
            self._repo = PostgreSQLRepository(schema_name='public')

        # Lazy-loaded schema analyzer
        self._schema_analyzer = None

        logger.info(f"🔧 DatabaseInitializer created for {self.database_config.host}/{self.database_config.database}")
        logger.info(f"   Admin identity: {self.admin_identity or 'NOT CONFIGURED'}")
        logger.info(f"   Reader identity: {self.reader_identity or 'NOT CONFIGURED'}")

    @property
    def schema_analyzer(self):
        """Lazy-load schema analyzer."""
        if self._schema_analyzer is None:
            from infrastructure.schema_analyzer import SchemaAnalyzer
            self._schema_analyzer = SchemaAnalyzer()
        return self._schema_analyzer

    def _build_connection_string(self, config: DatabaseConfig) -> str:
        """Build connection string from DatabaseConfig."""
        from config import get_postgres_connection_string
        return get_postgres_connection_string(
            host=config.host,
            database=config.database,
            user=config.username,
            password=config.password,
            port=config.port,
            sslmode=config.sslmode
        )

    # ========================================================================
    # MAIN ORCHESTRATION
    # ========================================================================

    def initialize_all(
        self,
        verify_permissions: bool = True,
        schemas: Optional[List[str]] = None,
        smart_mode: bool = True
    ) -> InitializationResult:
        """
        Initialize database with all configured schemas.

        Args:
            verify_permissions: If True, verify permissions before creating schemas
            schemas: List of schema names to initialize. If None, initializes all.
                    Options: 'geo', 'app', 'pgstac', 'h3'
            smart_mode: If True (default), analyze existing schema and only create
                       missing objects. If False, attempt to create everything
                       (idempotent but more SQL execution).

        Returns:
            InitializationResult with detailed step results
        """
        result = InitializationResult(
            database_host=self.database_config.host,
            database_name=self.database_config.database,
            timestamp=datetime.utcnow().isoformat(),
            success=False
        )

        logger.info("=" * 70)
        logger.info("🚀 DATABASE INITIALIZATION STARTED")
        logger.info(f"   Target: {self.database_config.host}/{self.database_config.database}")
        logger.info(f"   Mode: {'SMART (analyze first)' if smart_mode else 'FORCE (create all)'}")
        logger.info("=" * 70)

        # Determine which schemas to initialize
        target_schemas = self._resolve_target_schemas(schemas)
        logger.info(f"   Schemas to initialize: {[s.value for s in target_schemas]}")

        try:
            # Step 1: Verify permissions
            if verify_permissions:
                step_result = self._verify_permissions()
                result.steps.append(step_result)
                if step_result.status == "failed":
                    result.errors.append(f"Permission verification failed: {step_result.error}")
                    # Continue anyway - permission issues might be acceptable
                    result.warnings.append("Continuing despite permission issues")

            # Step 2: Analyze existing schemas (smart mode)
            drift_data = {}
            if smart_mode:
                step_result = self._analyze_existing_schemas(target_schemas)
                result.steps.append(step_result)
                if step_result.status == "success":
                    drift_data = step_result.details.get("drift_by_schema", {})
                    # Log summary
                    for schema_name, drift in drift_data.items():
                        if drift.get("has_drift"):
                            logger.info(f"   📊 {schema_name}: drift detected - "
                                       f"{len(drift.get('missing_tables', []))} missing tables, "
                                       f"{sum(len(c) for c in drift.get('missing_columns', {}).values())} missing columns")
                        else:
                            logger.info(f"   ✅ {schema_name}: no drift detected")

            # Step 3: Initialize each schema (with drift info if available)
            for schema_type in target_schemas:
                schema_drift = drift_data.get(schema_type.value, {}) if smart_mode else {}
                step_result = self._initialize_schema(schema_type, drift_info=schema_drift)
                result.steps.append(step_result)
                if step_result.status == "failed":
                    result.errors.append(f"Schema {schema_type.value} failed: {step_result.error}")

            # Step 3: Grant default privileges for future tables
            step_result = self._grant_default_privileges(target_schemas)
            result.steps.append(step_result)
            if step_result.status == "failed":
                result.warnings.append(f"Default privileges failed: {step_result.error}")

            # Determine overall success
            critical_failures = [
                s for s in result.steps
                if s.status == "failed" and s.name != "grant_default_privileges"
            ]
            result.success = len(critical_failures) == 0

        except Exception as e:
            logger.error(f"❌ Initialization failed with exception: {e}")
            logger.error(traceback.format_exc())
            result.errors.append(str(e))
            result.success = False

        # Log summary
        summary = result.to_dict()["summary"]
        logger.info("=" * 70)
        logger.info(f"🏁 INITIALIZATION {'COMPLETE' if result.success else 'FAILED'}")
        logger.info(f"   Steps: {summary['successful']} succeeded, {summary['failed']} failed, {summary['skipped']} skipped")
        if result.errors:
            logger.warning(f"   Errors: {result.errors}")
        if result.warnings:
            logger.warning(f"   Warnings: {result.warnings}")
        logger.info("=" * 70)

        return result

    def _resolve_target_schemas(self, schemas: Optional[List[str]]) -> List[SchemaType]:
        """Resolve schema names to SchemaType enums in correct order."""
        if schemas is None:
            return self.SCHEMA_ORDER

        # Convert strings to SchemaType, maintaining order
        requested = {s.lower() for s in schemas}
        return [st for st in self.SCHEMA_ORDER if st.value in requested]

    # ========================================================================
    # SCHEMA ANALYSIS (21 JAN 2026)
    # ========================================================================

    def analyze_schemas(
        self,
        schemas: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Analyze existing database schemas and detect drift.

        Public method to see current schema state before initialization.
        Useful for migration planning and understanding what needs to be created.

        Args:
            schemas: List of schema names to analyze. If None, analyzes all.

        Returns:
            Dict with analysis results for each schema including:
            - exists: bool
            - has_drift: bool
            - missing_tables: List[str]
            - missing_columns: Dict[table_name, List[column_name]]
            - extra_tables: List[str]
            - table_details: Dict with row counts, sizes, etc.
        """
        target_schemas = self._resolve_target_schemas(schemas)
        results = {}

        logger.info("📊 Analyzing database schemas...")

        for schema_type in target_schemas:
            schema_name = self._get_schema_name(schema_type)
            try:
                drift_report = self.schema_analyzer.detect_drift(schema_name)
                schema_report = self.schema_analyzer.analyze_schema(schema_name)

                results[schema_type.value] = {
                    "schema_name": schema_name,
                    "exists": schema_report.exists,
                    "has_drift": drift_report.has_drift,
                    "missing_tables": drift_report.missing_tables,
                    "missing_columns": drift_report.missing_columns,
                    "missing_indexes": drift_report.missing_indexes,
                    "extra_tables": drift_report.extra_tables,
                    "type_mismatches": drift_report.type_mismatches,
                    "summary": {
                        "total_tables": schema_report.total_tables,
                        "total_columns": schema_report.total_columns,
                        "total_indexes": schema_report.total_indexes,
                        "total_rows": schema_report.total_rows,
                        "total_size_mb": round(schema_report.total_size_bytes / 1024 / 1024, 2),
                    },
                    "table_details": {
                        name: {
                            "columns": len(t.columns),
                            "indexes": len(t.indexes),
                            "rows": t.row_count,
                            "size_mb": round(t.table_size_bytes / 1024 / 1024, 2),
                            "last_analyze": t.last_analyze.isoformat() if t.last_analyze else None,
                        }
                        for name, t in schema_report.tables.items()
                    } if schema_report.exists else {}
                }
            except Exception as e:
                logger.error(f"❌ Failed to analyze {schema_name}: {e}")
                results[schema_type.value] = {
                    "schema_name": schema_name,
                    "error": str(e)
                }

        return results

    def _analyze_existing_schemas(self, target_schemas: List[SchemaType]) -> StepResult:
        """
        Internal method to analyze schemas during initialization.

        Args:
            target_schemas: List of schema types to analyze

        Returns:
            StepResult with drift information in details
        """
        step = StepResult(name="analyze_existing_schemas", status="pending")

        logger.info("📊 Step: Analyzing existing schemas for drift...")

        try:
            drift_by_schema = {}

            for schema_type in target_schemas:
                schema_name = self._get_schema_name(schema_type)
                drift_report = self.schema_analyzer.detect_drift(schema_name)

                drift_by_schema[schema_type.value] = {
                    "schema_name": schema_name,
                    "has_drift": drift_report.has_drift,
                    "missing_tables": drift_report.missing_tables,
                    "missing_columns": drift_report.missing_columns,
                    "missing_indexes": drift_report.missing_indexes,
                    "extra_tables": drift_report.extra_tables,
                }

            # Summarize drift
            schemas_with_drift = [s for s, d in drift_by_schema.items() if d.get("has_drift")]
            total_missing_tables = sum(
                len(d.get("missing_tables", []))
                for d in drift_by_schema.values()
            )
            total_missing_columns = sum(
                sum(len(c) for c in d.get("missing_columns", {}).values())
                for d in drift_by_schema.values()
            )

            step.status = "success"
            step.message = (
                f"Analyzed {len(target_schemas)} schemas: "
                f"{len(schemas_with_drift)} with drift, "
                f"{total_missing_tables} missing tables, "
                f"{total_missing_columns} missing columns"
            )
            step.details = {
                "drift_by_schema": drift_by_schema,
                "schemas_with_drift": schemas_with_drift,
                "total_missing_tables": total_missing_tables,
                "total_missing_columns": total_missing_columns,
            }

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Schema analysis failed: {e}"
            logger.error(f"❌ Schema analysis error: {e}")

        logger.info(f"   Result: {step.status} - {step.message}")
        return step

    def _get_schema_name(self, schema_type: SchemaType) -> str:
        """Get the actual schema name for a schema type."""
        if schema_type == SchemaType.GEO:
            return self.config.postgis_schema
        elif schema_type == SchemaType.APP:
            return self.config.app_schema
        elif schema_type == SchemaType.PGSTAC:
            return 'pgstac'
        elif schema_type == SchemaType.H3:
            return getattr(self.config, 'h3_schema', 'h3')
        return schema_type.value

    def generate_migration_report(
        self,
        schemas: Optional[List[str]] = None,
        output_format: str = "text"
    ) -> str:
        """
        Generate a comprehensive migration report.

        Shows what's different between expected and actual schema,
        and provides SQL statements to fix drift.

        Args:
            schemas: List of schema names to report on. If None, reports all.
            output_format: "text" or "markdown"

        Returns:
            Formatted report string
        """
        return self.schema_analyzer.generate_migration_report(output_format)

    # ========================================================================
    # PERMISSION VERIFICATION
    # ========================================================================

    def _verify_permissions(self) -> StepResult:
        """
        Verify required permissions are in place.

        Checks:
        1. Current user can create schemas
        2. Admin identity exists (if configured)
        3. Reader identity exists (if configured)
        4. pgSTAC roles exist with proper grants (if pgstac will be initialized)
        """
        step = StepResult(name="verify_permissions", status="pending")

        logger.info("🔍 Step: Verifying permissions...")

        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    checks = {}

                    # Check 1: Can current user create schemas?
                    cur.execute("""
                        SELECT has_database_privilege(current_database(), 'CREATE') as can_create
                    """)
                    can_create = cur.fetchone()['can_create']
                    checks['can_create_schema'] = can_create
                    if not can_create:
                        logger.warning("⚠️ Current user cannot create schemas")

                    # Check 2: Admin identity exists?
                    if self.admin_identity:
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                            [self.admin_identity]
                        )
                        admin_exists = cur.fetchone()['exists']
                        checks['admin_identity_exists'] = admin_exists
                        if not admin_exists:
                            logger.warning(f"⚠️ Admin identity '{self.admin_identity}' does not exist")
                    else:
                        checks['admin_identity_exists'] = None
                        logger.warning("⚠️ No admin identity configured")

                    # Check 3: Reader identity exists?
                    if self.reader_identity:
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                            [self.reader_identity]
                        )
                        reader_exists = cur.fetchone()['exists']
                        checks['reader_identity_exists'] = reader_exists
                        if not reader_exists:
                            logger.warning(f"⚠️ Reader identity '{self.reader_identity}' does not exist")
                    else:
                        checks['reader_identity_exists'] = None
                        logger.info("   No reader identity configured (optional)")

                    # Check 4: pgSTAC roles exist?
                    pgstac_roles = ['pgstac_admin', 'pgstac_ingest', 'pgstac_read']
                    pgstac_checks = {}
                    for role in pgstac_roles:
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                            [role]
                        )
                        pgstac_checks[role] = cur.fetchone()['exists']
                    checks['pgstac_roles'] = pgstac_checks

                    missing_pgstac = [r for r, exists in pgstac_checks.items() if not exists]
                    if missing_pgstac:
                        logger.warning(f"⚠️ Missing pgSTAC roles: {missing_pgstac}")
                        logger.warning("   DBA must create these before pgSTAC initialization")

                    # Determine overall status
                    critical_issues = []
                    if not can_create:
                        critical_issues.append("Cannot create schemas")
                    if self.admin_identity and not checks.get('admin_identity_exists'):
                        critical_issues.append(f"Admin identity '{self.admin_identity}' missing")

                    if critical_issues:
                        step.status = "failed"
                        step.error = "; ".join(critical_issues)
                        step.message = f"Permission check failed: {step.error}"
                    else:
                        step.status = "success"
                        step.message = "All required permissions verified"

                    step.details = checks

                    conn.commit()

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Permission verification failed: {e}"
            logger.error(f"❌ Permission verification error: {e}")

        logger.info(f"   Result: {step.status} - {step.message}")
        return step

    # ========================================================================
    # SCHEMA INITIALIZATION
    # ========================================================================

    def _initialize_schema(
        self,
        schema_type: SchemaType,
        drift_info: Optional[Dict[str, Any]] = None
    ) -> StepResult:
        """
        Initialize a specific schema.

        Args:
            schema_type: The schema to initialize
            drift_info: Optional drift information from schema analysis.
                       If provided and shows no drift, may skip initialization.

        Returns:
            StepResult with initialization details
        """
        step = StepResult(name=f"initialize_{schema_type.value}_schema", status="pending")

        # Check if we can skip based on drift analysis
        if drift_info and not drift_info.get("has_drift", True):
            step.status = "skipped"
            step.message = f"Schema {schema_type.value} already complete - no drift detected"
            logger.info(f"⏭️ Skipping {schema_type.value} schema (no changes needed)")
            return step

        logger.info(f"📦 Step: Initializing {schema_type.value} schema...")

        # Log what we're creating if drift info available
        if drift_info:
            missing_tables = drift_info.get("missing_tables", [])
            missing_cols = drift_info.get("missing_columns", {})
            if missing_tables:
                logger.info(f"   Creating {len(missing_tables)} missing tables: {missing_tables}")
            if missing_cols:
                col_count = sum(len(c) for c in missing_cols.values())
                logger.info(f"   Adding {col_count} missing columns")

        try:
            if schema_type == SchemaType.GEO:
                step = self._initialize_geo_schema(drift_info)
            elif schema_type == SchemaType.APP:
                step = self._initialize_app_schema(drift_info)
            elif schema_type == SchemaType.PGSTAC:
                step = self._initialize_pgstac_schema()
            elif schema_type == SchemaType.H3:
                step = self._initialize_h3_schema()
            else:
                step.status = "skipped"
                step.message = f"Unknown schema type: {schema_type}"

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to initialize {schema_type.value}: {e}"
            logger.error(f"❌ {step.message}")
            logger.error(traceback.format_exc())

        logger.info(f"   Result: {step.status} - {step.message}")
        return step

    def _initialize_geo_schema(
        self,
        drift_info: Optional[Dict[str, Any]] = None
    ) -> StepResult:
        """
        Initialize geo schema with PostGIS extension and system tables.

        Creates (via PydanticToSQL from GeoTableCatalog model):
        - geo schema
        - PostGIS extension
        - geo.table_catalog (service layer metadata)

        NOTE (21 JAN 2026): This replaces the old geo.table_metadata table.
        The new table_catalog contains only service layer fields.
        ETL tracking fields are now in app.vector_etl_tracking.

        Args:
            drift_info: Optional drift information from schema analysis.
        """
        step = StepResult(name="initialize_geo_schema", status="pending")

        schema_name = self.config.postgis_schema

        try:
            from core.schema.sql_generator import PydanticToSQL

            # Generate DDL from GeoTableCatalog Pydantic model
            generator = PydanticToSQL(schema_name=schema_name)
            statements = generator.generate_geo_schema_ddl()

            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    executed_count = 0

                    # Enable PostGIS extension first
                    cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS postgis"))
                    executed_count += 1

                    # Execute generated DDL (schema, table, indexes)
                    for stmt in statements:
                        cur.execute(stmt)
                        executed_count += 1

                    # Add schema comment
                    cur.execute(sql.SQL("""
                        COMMENT ON SCHEMA {} IS 'Geographic vector data - PostGIS tables and service layer metadata'
                    """).format(sql.Identifier(schema_name)))

                    conn.commit()

                    step.status = "success"
                    step.message = (
                        f"Geo schema '{schema_name}' initialized "
                        f"({executed_count} statements executed)"
                    )
                    step.details = {
                        "schema": schema_name,
                        "statements_executed": executed_count,
                        "tables_created": ["table_catalog"],
                        "source": "PydanticToSQL.generate_geo_schema_ddl()",
                    }

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to initialize geo schema: {e}"
            logger.error(f"❌ Geo schema init failed: {e}")
            logger.error(traceback.format_exc())

        return step

    def _initialize_app_schema(
        self,
        drift_info: Optional[Dict[str, Any]] = None
    ) -> StepResult:
        """
        Initialize app schema using PydanticToSQL generator.

        Creates all app tables from Pydantic models:
        - Core tables: jobs, tasks, api_requests, etc.
        - ETL tracking: vector_etl_tracking, raster_etl_tracking

        NOTE (21 JAN 2026): ETL tracking tables have FK dependency on geo.table_catalog.
        The geo schema MUST be initialized before app schema. This is enforced by
        SCHEMA_ORDER = [GEO, APP, PGSTAC, H3] and verified at runtime.

        Args:
            drift_info: Optional drift information. Used to report what was missing.
        """
        step = StepResult(name="initialize_app_schema", status="pending")

        schema_name = self.config.app_schema
        missing_tables = drift_info.get("missing_tables", []) if drift_info else []
        missing_columns = drift_info.get("missing_columns", {}) if drift_info else {}

        try:
            from core.schema.sql_generator import PydanticToSQL

            generator = PydanticToSQL(schema_name=schema_name)

            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    executed_count = 0
                    skipped_count = 0
                    etl_statements_count = 0

                    # Part 1: Core app tables (jobs, tasks, api_requests, etc.)
                    core_statements = generator.generate_composed_statements()
                    logger.info(f"   Executing {len(core_statements)} core app statements...")

                    for stmt in core_statements:
                        try:
                            cur.execute(stmt)
                            executed_count += 1
                        except Exception as e:
                            skipped_count += 1
                            logger.debug(f"Statement skipped (may already exist): {e}")

                    # Part 2: ETL tracking tables (vector_etl_tracking, raster_etl_tracking)
                    # These have FK to geo.table_catalog, so verify it exists first
                    if generator.check_table_exists(conn, "geo", "table_catalog"):
                        logger.info("   ✅ geo.table_catalog exists - creating ETL tracking tables...")
                        etl_statements = generator.generate_etl_tracking_ddl(
                            conn=conn,
                            verify_dependencies=True
                        )

                        for stmt in etl_statements:
                            try:
                                cur.execute(stmt)
                                executed_count += 1
                                etl_statements_count += 1
                            except Exception as e:
                                skipped_count += 1
                                logger.debug(f"ETL statement skipped: {e}")
                    else:
                        # geo.table_catalog doesn't exist - can't create ETL tables
                        logger.warning(
                            "   ⚠️ geo.table_catalog not found - skipping ETL tracking tables. "
                            "Run geo schema initialization first."
                        )
                        step.details["etl_skipped_reason"] = "geo.table_catalog does not exist"

                    conn.commit()

                    step.status = "success"
                    step.message = (
                        f"App schema '{schema_name}' initialized "
                        f"({executed_count} executed, {skipped_count} skipped)"
                    )
                    step.details = {
                        "schema": schema_name,
                        "statements_executed": executed_count,
                        "statements_skipped": skipped_count,
                        "core_statements": len(core_statements),
                        "etl_statements": etl_statements_count,
                        "missing_tables_reported": missing_tables,
                        "missing_columns_reported": missing_columns,
                    }

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to initialize app schema: {e}"
            logger.error(f"❌ App schema init failed: {e}")
            logger.error(traceback.format_exc())

        return step

    def _initialize_pgstac_schema(self) -> StepResult:
        """
        Initialize pgSTAC schema.

        Uses PgStacBootstrap to install and configure pgSTAC extension.
        Requires DBA prerequisites (pgstac_* roles) to be in place.
        """
        step = StepResult(name="initialize_pgstac_schema", status="pending")

        try:
            from infrastructure.pgstac_bootstrap import PgStacBootstrap

            # Check DBA prerequisites first
            bootstrap = PgStacBootstrap()
            prereqs = bootstrap.check_dba_prerequisites()

            if not prereqs.get('ready', False):
                missing = prereqs.get('missing_roles', []) + prereqs.get('missing_grants', [])
                step.status = "failed"
                step.error = f"DBA prerequisites not met: {missing}"
                step.message = "pgSTAC requires DBA to create roles first"
                step.details = {
                    "prereqs": prereqs,
                    "dba_sql": prereqs.get('dba_sql', '')
                }
                return step

            # Check current installation
            install_status = bootstrap.check_installation()

            if install_status.get('installed', False):
                step.status = "success"
                step.message = f"pgSTAC already installed (v{install_status.get('version')})"
                step.details = install_status
            else:
                # Need to run pypgstac migrate
                # This is typically done via subprocess - delegate to bootstrap
                step.status = "skipped"
                step.message = "pgSTAC not installed - run pypgstac migrate manually"
                step.details = {
                    "install_status": install_status,
                    "migration_required": True,
                    "command": "pypgstac migrate"
                }

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to initialize pgSTAC: {e}"

        return step

    def _initialize_h3_schema(self) -> StepResult:
        """
        Initialize H3 schema using H3SchemaDeployer.

        Creates H3 cells, admin mappings, and stats tables.
        """
        step = StepResult(name="initialize_h3_schema", status="pending")

        try:
            from infrastructure.h3_schema import H3SchemaDeployer

            deployer = H3SchemaDeployer()
            result = deployer.deploy_all()

            if result.get('success', False):
                step.status = "success"
                step.message = "H3 schema initialized"
                step.details = result
            else:
                errors = result.get('errors', [])
                step.status = "failed"
                step.error = "; ".join(errors) if errors else "Unknown error"
                step.message = f"H3 schema initialization had errors"
                step.details = result

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to initialize H3 schema: {e}"

        return step

    # ========================================================================
    # DEFAULT PRIVILEGES
    # ========================================================================

    def _grant_default_privileges(self, schemas: List[SchemaType]) -> StepResult:
        """
        Grant default privileges for future tables created by admin.

        Ensures:
        1. Admin identity has ALL on current and future tables
        2. Reader identity has SELECT on current and future tables
        """
        step = StepResult(name="grant_default_privileges", status="pending")

        logger.info("🔐 Step: Granting default privileges...")

        if not self.admin_identity:
            step.status = "skipped"
            step.message = "No admin identity configured - skipping privilege grants"
            return step

        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    grants_applied = []

                    # Map schema types to actual schema names
                    schema_map = {
                        SchemaType.GEO: self.config.postgis_schema,
                        SchemaType.APP: self.config.app_schema,
                        SchemaType.PGSTAC: 'pgstac',  # Fixed name
                        SchemaType.H3: self.config.h3_schema if hasattr(self.config, 'h3_schema') else 'h3'
                    }

                    for schema_type in schemas:
                        schema_name = schema_map.get(schema_type)
                        if not schema_name:
                            continue

                        # Check if schema exists
                        cur.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM pg_namespace WHERE nspname = %s
                            ) as exists
                        """, [schema_name])
                        if not cur.fetchone()['exists']:
                            logger.debug(f"   Schema {schema_name} doesn't exist, skipping")
                            continue

                        # Grant ALL to admin on schema
                        cur.execute(sql.SQL(
                            "GRANT ALL PRIVILEGES ON SCHEMA {} TO {}"
                        ).format(
                            sql.Identifier(schema_name),
                            sql.Identifier(self.admin_identity)
                        ))
                        grants_applied.append(f"schema:{schema_name}->admin")

                        # Grant ALL on existing tables
                        cur.execute(sql.SQL(
                            "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO {}"
                        ).format(
                            sql.Identifier(schema_name),
                            sql.Identifier(self.admin_identity)
                        ))
                        grants_applied.append(f"tables:{schema_name}->admin")

                        # Grant ALL on sequences
                        cur.execute(sql.SQL(
                            "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO {}"
                        ).format(
                            sql.Identifier(schema_name),
                            sql.Identifier(self.admin_identity)
                        ))
                        grants_applied.append(f"sequences:{schema_name}->admin")

                        # Set default privileges for FUTURE tables
                        cur.execute(sql.SQL(
                            "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT ALL PRIVILEGES ON TABLES TO {}"
                        ).format(
                            sql.Identifier(schema_name),
                            sql.Identifier(self.admin_identity)
                        ))
                        grants_applied.append(f"default_tables:{schema_name}->admin")

                        cur.execute(sql.SQL(
                            "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT ALL PRIVILEGES ON SEQUENCES TO {}"
                        ).format(
                            sql.Identifier(schema_name),
                            sql.Identifier(self.admin_identity)
                        ))
                        grants_applied.append(f"default_sequences:{schema_name}->admin")

                        # Grant to reader identity if configured
                        if self.reader_identity:
                            # USAGE on schema
                            cur.execute(sql.SQL(
                                "GRANT USAGE ON SCHEMA {} TO {}"
                            ).format(
                                sql.Identifier(schema_name),
                                sql.Identifier(self.reader_identity)
                            ))
                            grants_applied.append(f"usage:{schema_name}->reader")

                            # SELECT on existing tables
                            cur.execute(sql.SQL(
                                "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}"
                            ).format(
                                sql.Identifier(schema_name),
                                sql.Identifier(self.reader_identity)
                            ))
                            grants_applied.append(f"select:{schema_name}->reader")

                            # DEFAULT SELECT for future tables
                            cur.execute(sql.SQL(
                                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                            ).format(
                                sql.Identifier(schema_name),
                                sql.Identifier(self.reader_identity)
                            ))
                            grants_applied.append(f"default_select:{schema_name}->reader")

                    conn.commit()

                    step.status = "success"
                    step.message = f"Granted {len(grants_applied)} privilege sets"
                    step.details = {
                        "grants_applied": grants_applied,
                        "admin_identity": self.admin_identity,
                        "reader_identity": self.reader_identity
                    }

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.message = f"Failed to grant default privileges: {e}"
            logger.error(f"❌ Privilege grant error: {e}")

        logger.info(f"   Result: {step.status} - {step.message}")
        return step

    # ========================================================================
    # CONVENIENCE METHODS
    # ========================================================================

    def verify_installation(self) -> Dict[str, Any]:
        """
        Quick verification of database installation state.

        Returns:
            Dict with schema existence and basic health info
        """
        result = {
            "database": f"{self.database_config.host}/{self.database_config.database}",
            "timestamp": datetime.utcnow().isoformat(),
            "schemas": {}
        }

        schema_names = {
            "geo": self.config.postgis_schema,
            "app": self.config.app_schema,
            "pgstac": "pgstac",
            "h3": getattr(self.config, 'h3_schema', 'h3')
        }

        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    for key, schema_name in schema_names.items():
                        cur.execute("""
                            SELECT
                                EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s) as exists,
                                (SELECT COUNT(*) FROM information_schema.tables
                                 WHERE table_schema = %s) as table_count
                        """, [schema_name, schema_name])
                        row = cur.fetchone()
                        result["schemas"][key] = {
                            "name": schema_name,
                            "exists": row['exists'],
                            "table_count": row['table_count'] if row['exists'] else 0
                        }
        except Exception as e:
            result["error"] = str(e)

        return result


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def initialize_database(
    database_config: Optional[DatabaseConfig] = None,
    schemas: Optional[List[str]] = None
) -> InitializationResult:
    """
    Initialize database with all schemas.

    Convenience function for deployment scripts.

    Args:
        database_config: Optional custom database config
        schemas: Optional list of schemas to initialize (default: all)

    Returns:
        InitializationResult with detailed results
    """
    initializer = DatabaseInitializer(database_config=database_config)
    return initializer.initialize_all(schemas=schemas)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'DatabaseInitializer',
    'InitializationResult',
    'StepResult',
    'SchemaType',
    'initialize_database',
]
