# ============================================================================
# PYDANTIC TO POSTGRESQL SCHEMA GENERATOR
# ============================================================================
# STATUS: Core - DDL generation from Pydantic models
# PURPOSE: Generate PostgreSQL CREATE statements using psycopg.sql composition
# LAST_REVIEWED: 16 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Pydantic to PostgreSQL Schema Generator.

Generates PostgreSQL DDL statements from Pydantic models,
ensuring database schema always matches Python models.
Pydantic models are the single source of truth for schema.

SCHEMA EVOLUTION PATTERN (16 JAN 2026):
    This generator uses IF NOT EXISTS patterns for safe, additive schema updates:
    - CREATE TABLE IF NOT EXISTS: New tables added without affecting existing
    - CREATE INDEX IF NOT EXISTS: New indexes added safely
    - CREATE TYPE ... (enums): Recreated on rebuild, careful with ensure

    Usage:
        action=ensure  -> Additive: Creates missing objects, skips existing (SAFE)
        action=rebuild -> Destructive: Drops and recreates everything

    Adding New Tables:
        1. Create Pydantic model in core/models/
        2. Export from core/models/__init__.py
        3. Import model here and add to generate_composed_statements()
        4. Deploy and run: POST /api/dbadmin/maintenance?action=ensure&confirm=yes

    See: docs_claude/SCHEMA_EVOLUTION.md for full patterns

Exports:
    PydanticToSQL: Generator class for SQL DDL from Pydantic models

Dependencies:
    pydantic: Model introspection
    psycopg: SQL composition
    core.models: JobRecord, TaskRecord, and status enums
"""

from typing import Dict, List, Optional, Type, get_args, get_origin, Any, Union
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID
import inspect
import re
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from psycopg import sql
from annotated_types import MaxLen  # Import at top for health check validation

from core.schema.ddl_utils import IndexBuilder, TriggerBuilder, SchemaUtils

# Import the core models
# NOTE: OrchestrationJob REMOVED (22 NOV 2025) - no job chaining in Platform
from ..models import (
    JobRecord,
    TaskRecord,
    JobStatus,
    TaskStatus,
    ApiRequest,
    PlatformRequestStatus,
    DataType,
    JanitorRun,
    JanitorRunType,
    JanitorRunStatus,
    EtlSourceFile,  # ETL tracking (21 DEC 2025 - generalized)
    UnpublishJobRecord,  # Unpublish audit (12 DEC 2025)
    UnpublishType,
    UnpublishStatus,
    CuratedDataset,  # Curated datasets (15 DEC 2025)
    CuratedUpdateLog,
    CuratedSourceType,
    CuratedUpdateStrategy,
    CuratedUpdateType,
    CuratedUpdateStatus
)
from ..models.promoted import PromotedDataset, SystemRole  # Promoted datasets (23 DEC 2025)
from ..models.stac import AccessLevel  # Data classification (25 JAN 2026 - S4.DM unified)
from ..models.system_snapshot import SystemSnapshotRecord, SnapshotTriggerType  # System snapshots (04 JAN 2026)
from ..models.external_refs import DatasetRefRecord  # External references (09 JAN 2026 - F7.8)
from ..models.raster_metadata import CogMetadataRecord  # Raster metadata (09 JAN 2026 - F7.9)
from ..models.asset import GeospatialAsset, AssetRevision, ApprovalState, ClearanceState, ProcessingStatus  # Geospatial assets (29 JAN 2026 - V0.8)
from ..models.platform_registry import Platform, DDH_PLATFORM  # Platform registry (29 JAN 2026 - V0.8)
from ..models.artifact import Artifact, ArtifactStatus  # Artifact registry (20 JAN 2026)
from ..models.external_service import ExternalService, ServiceType, ServiceStatus  # External service registry (22 JAN 2026)
from ..models.job_event import JobEvent, JobEventType, JobEventStatus  # Job event tracking (23 JAN 2026)

# Geo and ETL schema models (21 JAN 2026 - F7.IaC)
from ..models.geo import GeoTableCatalog, FeatureCollectionStyles  # OGC Styles (22 JAN 2026)
from ..models.etl_tracking import VectorEtlTracking, RasterEtlTracking, EtlStatus
from ..models.raster_render_config import RasterRenderConfig  # Render configs (22 JAN 2026 - F2.11)
from ..models.map_state import MapState, MapStateSnapshot, MapType  # Map states (23 JAN 2026)


class PydanticToSQL:
    """
    Convert Pydantic models to PostgreSQL DDL statements.
    
    This class analyzes Pydantic models and generates the corresponding
    PostgreSQL CREATE TABLE statements, including proper data types,
    constraints, and indexes.
    """
    
    # Type mapping from Python/Pydantic to PostgreSQL
    TYPE_MAP = {
        str: "VARCHAR",
        int: "INTEGER",
        float: "DOUBLE PRECISION",
        bool: "BOOLEAN",
        datetime: "TIMESTAMP",
        Decimal: "DECIMAL",
        dict: "JSONB",
        Dict: "JSONB",
        list: "JSONB",
        List: "JSONB",
        UUID: "UUID",  # Artifact registry (21 JAN 2026)
    }
    
    def __init__(self, schema_name: str = "app"):
        """
        Initialize the generator.
        
        Args:
            schema_name: PostgreSQL schema name to use
        """
        self.schema_name = schema_name
        self.enums: Dict[str, Type[Enum]] = {}
        self.tables: List[str] = []
        self.functions: List[str] = []
        
        # Setup logger for debugging
        try:
            from util_logger import LoggerFactory
            from util_logger import ComponentType, LogLevel, LogContext
            self.logger = LoggerFactory.create_logger(ComponentType.SERVICE, "SQLGenerator")
        except ImportError:
            # Fallback to simple logging for standalone testing
            import logging
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        self.statements: List[str] = []  # Track individual statements for deployment

    # =========================================================================
    # MODEL-DRIVEN DDL GENERATION (21 JAN 2026 - F7.IaC)
    # =========================================================================

    @staticmethod
    def get_model_sql_metadata(model: Type[BaseModel]) -> Dict[str, Any]:
        """
        Extract SQL DDL metadata from a Pydantic model's class attributes.

        Looks for __sql_* ClassVar attributes that define:
        - __sql_table_name: Target table name
        - __sql_schema: Target schema name
        - __sql_primary_key: List of primary key column(s)
        - __sql_foreign_keys: Dict of {column: "schema.table(column)"}
        - __sql_indexes: List of index definitions

        Args:
            model: Pydantic model class with __sql_* attributes

        Returns:
            Dict with table_name, schema, primary_key, foreign_keys, indexes

        Raises:
            ValueError: If model lacks required __sql_table_name attribute
        """
        # Access class attributes via name mangling
        class_name = model.__name__
        metadata = {}

        # Required: table name
        table_attr = f"_{class_name}__sql_table_name"
        if not hasattr(model, table_attr):
            raise ValueError(f"Model {class_name} missing required __sql_table_name attribute")
        metadata["table_name"] = getattr(model, table_attr)

        # Required: schema
        schema_attr = f"_{class_name}__sql_schema"
        if not hasattr(model, schema_attr):
            raise ValueError(f"Model {class_name} missing required __sql_schema attribute")
        metadata["schema"] = getattr(model, schema_attr)

        # Required: primary key
        pk_attr = f"_{class_name}__sql_primary_key"
        if not hasattr(model, pk_attr):
            raise ValueError(f"Model {class_name} missing required __sql_primary_key attribute")
        metadata["primary_key"] = getattr(model, pk_attr)

        # Optional: foreign keys
        fk_attr = f"_{class_name}__sql_foreign_keys"
        metadata["foreign_keys"] = getattr(model, fk_attr, {})

        # Optional: indexes
        idx_attr = f"_{class_name}__sql_indexes"
        metadata["indexes"] = getattr(model, idx_attr, [])

        # Optional: unique constraints (22 JAN 2026 - OGC Styles)
        unique_attr = f"_{class_name}__sql_unique_constraints"
        metadata["unique_constraints"] = getattr(model, unique_attr, [])

        return metadata

    def generate_table_from_model(self, model: Type[BaseModel]) -> sql.Composed:
        """
        Generate CREATE TABLE DDL from a Pydantic model with __sql_* metadata.

        This is the model-driven alternative to generate_table_composed().
        It reads table name, schema, PK, and FK from model class attributes.

        Args:
            model: Pydantic model with __sql_* class attributes

        Returns:
            Composed CREATE TABLE statement
        """
        # Get metadata from model
        meta = self.get_model_sql_metadata(model)
        table_name = meta["table_name"]
        schema_name = meta["schema"]
        primary_key = meta["primary_key"]
        foreign_keys = meta["foreign_keys"]
        unique_constraints = meta.get("unique_constraints", [])

        self.logger.debug(f"🔧 Generating table {schema_name}.{table_name} from model {model.__name__}")

        columns = []
        constraints = []

        # Process model fields
        for field_name, field_info in model.model_fields.items():
            field_type = field_info.annotation

            # Determine SQL type
            sql_type_str = self.python_type_to_sql(field_type, field_info)

            # Check if field is Optional
            is_optional = False
            origin = get_origin(field_type)
            if origin in [Union, type(Optional)]:
                args = get_args(field_type)
                if type(None) in args:
                    is_optional = True

            # Handle SERIAL type for auto-increment fields (22 JAN 2026, updated 27 JAN 2026)
            # Priority 1: Check for explicit __sql_serial_columns metadata (e.g., event_id)
            # Priority 2: Auto-detect field named 'id' that is Optional[int] and primary key
            # Note: Python name-mangles __attr to _ClassName__attr, so check both patterns
            mangled_name = f'_{model.__name__}__sql_serial_columns'
            serial_columns = getattr(model, mangled_name, getattr(model, '__sql_serial_columns', []))
            if field_name in serial_columns:
                sql_type_str = "SERIAL"
            elif field_name == "id" and primary_key == ["id"] and is_optional:
                sql_type_str = "SERIAL"

            # Build column definition
            column_parts = [
                sql.Identifier(field_name),
                sql.SQL(" ")
            ]

            # Handle enum types with schema qualification
            if sql_type_str in self.enums:
                column_parts.extend([
                    sql.Identifier(schema_name),
                    sql.SQL("."),
                    sql.Identifier(sql_type_str)
                ])
            else:
                column_parts.append(sql.SQL(sql_type_str))

            # Add NOT NULL if required (and not a PK column which gets it implicitly)
            # Skip for SERIAL as it's auto-generated
            if not is_optional and field_name not in primary_key and sql_type_str != "SERIAL":
                column_parts.extend([sql.SQL(" "), sql.SQL("NOT NULL")])

            # Handle defaults
            if field_info.default is not None and field_info.default != ...:
                if isinstance(field_info.default, Enum):
                    column_parts.extend([
                        sql.SQL(" DEFAULT "),
                        sql.Literal(field_info.default.value),
                        sql.SQL("::"),
                        sql.Identifier(schema_name),
                        sql.SQL("."),
                        sql.Identifier(sql_type_str)
                    ])
                elif isinstance(field_info.default, str):
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.Literal(field_info.default)])
                elif isinstance(field_info.default, (int, float)):
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.Literal(field_info.default)])
                elif isinstance(field_info.default, bool):
                    # Handle boolean defaults (22 JAN 2026 - OGC Styles)
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.SQL("true" if field_info.default else "false")])
            elif hasattr(field_info, 'default_factory') and field_info.default_factory is not None:
                # Handle default_factory for mutable defaults
                if field_name in ["created_at", "updated_at"]:
                    column_parts.extend([sql.SQL(" DEFAULT NOW()")])

            # Special timestamp defaults
            if field_name == "created_at" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT NOW()")])
            if field_name == "updated_at" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT NOW()")])

            columns.append(sql.SQL("").join(column_parts))

        # Add PRIMARY KEY constraint
        if len(primary_key) == 1:
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier(primary_key[0]))
            )
        else:
            # Composite primary key
            pk_columns = sql.SQL(", ").join(sql.Identifier(col) for col in primary_key)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(pk_columns)
            )

        # Add FOREIGN KEY constraints
        for fk_column, fk_reference in foreign_keys.items():
            # Parse reference: "schema.table(column)"
            import re
            match = re.match(r"(\w+)\.(\w+)\((\w+)\)", fk_reference)
            if match:
                ref_schema, ref_table, ref_column = match.groups()
                constraints.append(
                    sql.SQL("FOREIGN KEY ({}) REFERENCES {}.{} ({}) ON DELETE CASCADE").format(
                        sql.Identifier(fk_column),
                        sql.Identifier(ref_schema),
                        sql.Identifier(ref_table),
                        sql.Identifier(ref_column)
                    )
                )

        # Add UNIQUE constraints (22 JAN 2026 - OGC Styles)
        for unique_def in unique_constraints:
            uc_columns = unique_def.get("columns", [])
            uc_name = unique_def.get("name")
            if uc_columns:
                uc_cols_sql = sql.SQL(", ").join(sql.Identifier(col) for col in uc_columns)
                if uc_name:
                    constraints.append(
                        sql.SQL("CONSTRAINT {} UNIQUE ({})").format(
                            sql.Identifier(uc_name),
                            uc_cols_sql
                        )
                    )
                else:
                    constraints.append(
                        sql.SQL("UNIQUE ({})").format(uc_cols_sql)
                    )

        # Combine columns and constraints
        all_parts = columns + constraints

        # Build CREATE TABLE statement
        composed = sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(", ").join(all_parts)
        )

        self.logger.debug(f"✅ Table {schema_name}.{table_name} composed with {len(columns)} columns and {len(constraints)} constraints")
        return composed

    def generate_indexes_from_model(self, model: Type[BaseModel]) -> List[sql.Composed]:
        """
        Generate CREATE INDEX statements from a Pydantic model's __sql_indexes.

        Args:
            model: Pydantic model with __sql_indexes class attribute

        Returns:
            List of composed CREATE INDEX statements
        """
        meta = self.get_model_sql_metadata(model)
        table_name = meta["table_name"]
        schema_name = meta["schema"]
        indexes = meta.get("indexes", [])

        self.logger.debug(f"🔧 Generating indexes for {schema_name}.{table_name}")
        result = []

        for idx_def in indexes:
            columns = idx_def.get("columns", [])
            name = idx_def.get("name")
            partial_where = idx_def.get("partial_where")
            descending = idx_def.get("descending", False)
            index_type = idx_def.get("type", "btree")
            is_unique = idx_def.get("unique", False)  # Support unique indexes (22 JAN 2026)

            if not columns or not name:
                continue

            if index_type == "gin":
                result.append(IndexBuilder.gin(schema_name, table_name, columns[0], name=name))
            elif is_unique:
                # Use IndexBuilder.unique() for unique indexes
                result.append(IndexBuilder.unique(
                    schema_name, table_name, columns,
                    name=name,
                    partial_where=partial_where
                ))
            else:
                result.append(IndexBuilder.btree(
                    schema_name, table_name, columns,
                    name=name,
                    partial_where=partial_where,
                    descending=descending
                ))

        self.logger.debug(f"✅ Generated {len(result)} indexes for {schema_name}.{table_name}")
        return result

    def generate_enum_from_model(self, enum_class: Type[Enum], schema_name: str) -> List[sql.Composed]:
        """
        Generate ENUM type DDL for a given schema.

        Args:
            enum_class: Python Enum class
            schema_name: Target schema name

        Returns:
            List of composed SQL statements (DROP + CREATE)
        """
        # Convert CamelCase to snake_case
        enum_name = re.sub(r'(?<!^)(?=[A-Z])', '_', enum_class.__name__).lower()
        values_list = [member.value for member in enum_class]

        statements = []

        # DROP IF EXISTS
        statements.append(sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(schema_name),
            sql.Identifier(enum_name)
        ))

        # CREATE TYPE
        statements.append(sql.SQL("CREATE TYPE {}.{} AS ENUM ({})").format(
            sql.Identifier(schema_name),
            sql.Identifier(enum_name),
            sql.SQL(', ').join(sql.Literal(v) for v in values_list)
        ))

        return statements

    def generate_geo_schema_ddl(self) -> List[sql.Composed]:
        """
        Generate complete DDL for geo schema tables.

        Returns CREATE statements for:
        - geo.table_catalog (service layer metadata)
        - geo.feature_collection_styles (OGC API Styles - 22 JAN 2026)

        Returns:
            List of composed SQL statements
        """
        self.logger.info("🚀 Generating geo schema DDL")
        statements = []

        # Schema creation
        statements.append(sql.SQL("CREATE SCHEMA IF NOT EXISTS geo"))

        # GeoTableCatalog: service layer metadata
        statements.append(self.generate_table_from_model(GeoTableCatalog))
        statements.extend(self.generate_indexes_from_model(GeoTableCatalog))

        # FeatureCollectionStyles: OGC API Styles (22 JAN 2026)
        statements.append(self.generate_table_from_model(FeatureCollectionStyles))
        statements.extend(self.generate_indexes_from_model(FeatureCollectionStyles))

        self.logger.info(f"✅ Geo schema DDL complete: {len(statements)} statements")
        return statements

    @staticmethod
    def check_table_exists(conn, schema_name: str, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            conn: psycopg connection
            schema_name: Schema name
            table_name: Table name

        Returns:
            True if table exists, False otherwise
        """
        query = sql.SQL("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = {} AND table_name = {}
            )
        """).format(sql.Literal(schema_name), sql.Literal(table_name))

        with conn.cursor() as cur:
            cur.execute(query)
            result = cur.fetchone()
            return result[0] if result else False

    def verify_fk_dependencies(self, conn, model: Type[BaseModel]) -> Dict[str, bool]:
        """
        Verify that all FK dependencies exist for a model.

        Args:
            conn: psycopg connection
            model: Pydantic model with __sql_foreign_keys

        Returns:
            Dict mapping FK reference to existence status

        Raises:
            ValueError: If any FK dependency is missing
        """
        meta = self.get_model_sql_metadata(model)
        foreign_keys = meta.get("foreign_keys", {})
        results = {}

        for fk_column, fk_reference in foreign_keys.items():
            # Parse reference: "schema.table(column)"
            match = re.match(r"(\w+)\.(\w+)\((\w+)\)", fk_reference)
            if match:
                ref_schema, ref_table, ref_column = match.groups()
                exists = self.check_table_exists(conn, ref_schema, ref_table)
                results[fk_reference] = exists

                if not exists:
                    raise ValueError(
                        f"FK dependency missing: {model.__name__}.{fk_column} references "
                        f"{ref_schema}.{ref_table} which does not exist. "
                        f"Create {ref_schema}.{ref_table} first."
                    )

        return results

    def generate_etl_tracking_ddl(
        self,
        conn=None,
        verify_dependencies: bool = True
    ) -> List[sql.Composed]:
        """
        Generate DDL for ETL tracking tables in app schema.

        Returns CREATE statements for:
        - app.vector_etl_tracking
        - app.raster_etl_tracking (placeholder)
        - Required ENUM types

        Args:
            conn: Optional psycopg connection for dependency verification
            verify_dependencies: If True and conn provided, verify FK targets exist

        Returns:
            List of composed SQL statements

        Raises:
            ValueError: If verify_dependencies=True and geo.table_catalog doesn't exist
        """
        self.logger.info("🚀 Generating ETL tracking DDL")

        # Verify FK dependencies if connection provided
        if conn and verify_dependencies:
            self.logger.info("🔍 Verifying FK dependencies...")
            try:
                self.verify_fk_dependencies(conn, VectorEtlTracking)
                self.logger.info("✅ FK dependency verified: geo.table_catalog exists")
            except ValueError as e:
                self.logger.error(f"❌ FK dependency check failed: {e}")
                raise

        statements = []

        # Generate EtlStatus enum
        statements.extend(self.generate_enum_from_model(EtlStatus, "app"))

        # Generate vector_etl_tracking table
        statements.append(self.generate_table_from_model(VectorEtlTracking))
        statements.extend(self.generate_indexes_from_model(VectorEtlTracking))

        # Generate raster_etl_tracking table (placeholder - no FK dependencies)
        statements.append(self.generate_table_from_model(RasterEtlTracking))
        statements.extend(self.generate_indexes_from_model(RasterEtlTracking))

        # Generate raster_render_configs table (FK → cog_metadata) (22 JAN 2026 - F2.11)
        statements.append(self.generate_table_from_model(RasterRenderConfig))
        statements.extend(self.generate_indexes_from_model(RasterRenderConfig))

        self.logger.info(f"✅ ETL tracking DDL complete: {len(statements)} statements")
        return statements

    def generate_all_schemas_ddl(
        self,
        conn=None,
        verify_dependencies: bool = True
    ) -> Dict[str, List[sql.Composed]]:
        """
        Generate DDL for all schemas (app, geo, etl).

        This is the master method for full database initialization.
        Respects dependency order: geo schema must be created before
        ETL tracking tables that have FK references to geo.table_catalog.

        Args:
            conn: Optional psycopg connection for dependency verification
            verify_dependencies: If True and conn provided, verify FK targets exist

        Returns:
            Dict with schema names as keys and statement lists as values.
            Keys are ordered: ["geo", "app", "etl"] to respect FK dependencies.
        """
        self.logger.info("🚀 Generating complete schema DDL")
        self.logger.info("📋 Execution order: geo → app_core → app_etl (FK dependency order)")

        # IMPORTANT: Order matters due to FK dependencies
        # geo.table_catalog must exist before app.vector_etl_tracking
        #
        # Schema mapping:
        #   "geo"      → geo schema (geo.table_catalog)
        #   "app_core" → app schema core tables (jobs, tasks, etc.)
        #   "app_etl"  → app schema ETL tracking tables (app.vector_etl_tracking)
        #
        # NOTE: "app_etl" is NOT a separate schema - tables go in app schema
        result = {
            "geo": self.generate_geo_schema_ddl(),
            "app_core": self.generate_composed_statements(),  # app.jobs, app.tasks, etc.
            "app_etl": self.generate_etl_tracking_ddl(conn=conn, verify_dependencies=verify_dependencies),
        }

        total = sum(len(stmts) for stmts in result.values())
        self.logger.info(f"✅ Complete DDL generation: {total} statements across {len(result)} schemas")

        return result

    def execute_with_dependency_order(
        self,
        conn,
        schemas: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """
        Execute DDL in correct dependency order with FK verification.

        Execution order:
        1. geo schema (geo.table_catalog)
        2. app schema (jobs, tasks, etc.)
        3. etl tracking (app.vector_etl_tracking - has FK to geo.table_catalog)

        Args:
            conn: psycopg connection (must be in autocommit or transaction)
            schemas: Optional list of schemas to execute. Default: ["geo", "app", "etl"]
            dry_run: If True, log statements but don't execute

        Returns:
            Dict mapping schema name to number of statements executed

        Raises:
            ValueError: If FK dependencies are not met
        """
        if schemas is None:
            schemas = ["geo", "app_core", "app_etl"]

        # Enforce correct order (geo must come before app_etl due to FK)
        ordered_schemas = []
        for s in ["geo", "app_core", "app_etl"]:
            if s in schemas:
                ordered_schemas.append(s)

        self.logger.info(f"🚀 Executing DDL in order: {' → '.join(ordered_schemas)}")
        results = {}

        for schema in ordered_schemas:
            if schema == "geo":
                stmts = self.generate_geo_schema_ddl()
            elif schema == "app_core":
                stmts = self.generate_composed_statements()
            elif schema == "app_etl":
                # Verify geo.table_catalog exists before creating ETL tables in app schema
                if not self.check_table_exists(conn, "geo", "table_catalog"):
                    raise ValueError(
                        "Cannot create app.vector_etl_tracking: geo.table_catalog does not exist. "
                        "Run geo schema DDL first."
                    )
                stmts = self.generate_etl_tracking_ddl(conn=conn, verify_dependencies=True)
            else:
                self.logger.warning(f"Unknown schema group: {schema}, skipping")
                continue

            self.logger.info(f"📦 Executing {len(stmts)} statements for {schema} schema...")

            if dry_run:
                for stmt in stmts:
                    self.logger.info(f"  [DRY RUN] {str(stmt)[:100]}...")
                results[schema] = len(stmts)
            else:
                with conn.cursor() as cur:
                    for stmt in stmts:
                        cur.execute(stmt)
                results[schema] = len(stmts)
                self.logger.info(f"✅ {schema} schema complete: {len(stmts)} statements")

        total = sum(results.values())
        self.logger.info(f"🎉 DDL execution complete: {total} statements across {len(results)} schemas")
        return results

    def python_type_to_sql(self, field_type: Type, field_info: FieldInfo) -> str:
        """
        Convert Python type to PostgreSQL type.
        
        Args:
            field_type: Python type from Pydantic model
            field_info: Pydantic field information
            
        Returns:
            PostgreSQL type string
        """
        # First check if this is a string type (including Optional[str])
        # and has max_length constraint in metadata
        # This must be done BEFORE unwrapping Optional to preserve metadata
        actual_type = field_type
        is_optional = False
        
        # Check if it's Optional and unwrap to get actual type
        origin = get_origin(field_type)
        if origin is not None:
            args = get_args(field_type)
            # Optional[X] is actually Union[X, None] in runtime
            if origin is Union:
                # Check if this is an Optional (Union with None)
                if type(None) in args:
                    # Get the non-None type
                    actual_type = args[0] if args[0] is not type(None) else args[1]
                    is_optional = True
                else:
                    # Regular Union, not Optional
                    actual_type = args[0] if args else str
            elif origin in (dict, Dict):
                return "JSONB"
            elif origin in (list, List):
                return "JSONB"

        # Handle Literal types (e.g., Literal["vector", "raster"]) - 30 JAN 2026
        # Literal types should map to VARCHAR, not JSONB
        from typing import Literal as TypingLiteral
        try:
            from typing_extensions import Literal as ExtLiteral
            literal_types = (TypingLiteral, ExtLiteral)
        except ImportError:
            literal_types = (TypingLiteral,)

        if origin is not None and hasattr(origin, '__name__') and origin.__name__ == 'Literal':
            # Literal types are string enums without a Python Enum class
            # Map to VARCHAR with length based on longest value
            args = get_args(field_type)
            if args and all(isinstance(a, str) for a in args):
                max_len = max(len(a) for a in args)
                # Add some buffer for future values
                return f"VARCHAR({max(max_len + 10, 20)})"
            return "VARCHAR(50)"

        # Handle string fields with max_length - check metadata FIRST
        if actual_type == str:
            # In Pydantic v2, constraints are stored in metadata
            max_length = None
            if hasattr(field_info, 'metadata') and field_info.metadata:
                # Look for MaxLen constraint in metadata
                for constraint in field_info.metadata:
                    if isinstance(constraint, MaxLen):
                        max_length = constraint.max_length
                        break
            
            if max_length:
                return f"VARCHAR({max_length})"
            # Default VARCHAR without length for flexibility
            return "VARCHAR"
                
        # Handle Enums
        if inspect.isclass(actual_type) and issubclass(actual_type, Enum):
            # Convert CamelCase to snake_case for PostgreSQL
            enum_name = re.sub(r'(?<!^)(?=[A-Z])', '_', actual_type.__name__).lower()
            self.enums[enum_name] = actual_type
            # Return just the enum name - schema will be handled by composition
            return enum_name
            
        # Standard type mapping
        sql_type = self.TYPE_MAP.get(actual_type)
        if sql_type:
            return sql_type
            
        # Default to JSONB for complex types
        return "JSONB"
        
    def generate_enum(self, enum_name: str, enum_class: Type[Enum]) -> list:
        """
        Generate PostgreSQL ENUM using psycopg.sql composition.
        
        For PostgreSQL 14.x compatibility:
        - First DROP TYPE IF EXISTS
        - Then CREATE TYPE
        This ensures clean deployment without DO blocks.
        
        Args:
            enum_name: Name for the ENUM type
            enum_class: Python Enum class
            
        Returns:
            List of composed SQL objects for direct execution
        """
        values_list = [member.value for member in enum_class]
        
        self.logger.debug(f"🔧 Generating ENUM {enum_name} with values: {values_list}")
        
        # PostgreSQL 14 doesn't support IF NOT EXISTS for CREATE TYPE
        # Solution: DROP IF EXISTS + CREATE (atomic within transaction)
        statements = []
        
        # First drop if exists
        drop_stmt = sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(self.schema_name),
            sql.Identifier(enum_name)
        )
        statements.append(drop_stmt)
        
        # Then create
        create_stmt = sql.SQL("CREATE TYPE {}.{} AS ENUM ({})").format(
            sql.Identifier(self.schema_name),
            sql.Identifier(enum_name),
            sql.SQL(', ').join(sql.Literal(v) for v in values_list)
        )
        statements.append(create_stmt)
        
        self.logger.debug(f"✅ ENUM {enum_name} composed successfully (2 statements)")
        return statements
        
    def generate_table_composed(self, model: Type[BaseModel], table_name: str) -> sql.Composed:
        """
        Generate PostgreSQL CREATE TABLE using psycopg.sql composition.
        
        NO STRING CONCATENATION - Full SQL composition for safety.
        
        Args:
            model: Pydantic model class
            table_name: Name for the table
            
        Returns:
            Composed SQL object for direct execution
        """
        self.logger.debug(f"🔧 Generating table {table_name} from model {model.__name__}")
        
        columns = []
        constraints = []
        
        for field_name, field_info in model.model_fields.items():
            field_type = field_info.annotation
            
            # Determine SQL type (still using helper but returns string)
            sql_type_str = self.python_type_to_sql(field_type, field_info)
            
            # Check if field is Optional
            from typing import Union
            is_optional = False
            if get_origin(field_type) in [Union, type(Optional)]:
                args = get_args(field_type)
                if type(None) in args:
                    is_optional = True
            
            # Special handling for timestamp fields
            if field_name in ["created_at", "updated_at"]:
                sql_type_str = "TIMESTAMP"
                is_optional = False

            # Special handling for auto-increment id fields (SERIAL)
            # etl_source_files uses id as SERIAL primary key
            if field_name == "id" and table_name == "etl_source_files":
                sql_type_str = "SERIAL"
                is_optional = True  # SERIAL is auto-generated, doesn't need NOT NULL

            # Special handling for byte size fields - use BIGINT to support files > 2GB
            # INTEGER max is ~2.1GB, BIGINT supports up to 9.2 exabytes
            if field_name in ["size_bytes", "file_size_bytes", "source_size_bytes", "cog_size_bytes"]:
                sql_type_str = "BIGINT"

            # Build column definition using composition
            column_parts = [
                sql.Identifier(field_name),
                sql.SQL(" ")
            ]
            
            # Handle enum types with proper schema qualification
            if sql_type_str in self.enums:
                column_parts.extend([
                    sql.Identifier(self.schema_name),
                    sql.SQL("."),
                    sql.Identifier(sql_type_str)
                ])
            else:
                column_parts.append(sql.SQL(sql_type_str))
            
            # Add NOT NULL if required
            if not is_optional:
                column_parts.extend([sql.SQL(" "), sql.SQL("NOT NULL")])
            
            # Handle defaults
            if field_info.default is not None and field_info.default != ...:
                if isinstance(field_info.default, Enum):
                    column_parts.extend([
                        sql.SQL(" DEFAULT "),
                        sql.Literal(field_info.default.value),
                        sql.SQL("::"),
                        sql.SQL(sql_type_str)
                    ])
                elif isinstance(field_info.default, str):
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.Literal(field_info.default)])
                elif isinstance(field_info.default, (int, float)):
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.Literal(field_info.default)])
            elif hasattr(field_info, 'default_factory') and field_info.default_factory is not None:
                if field_name in ["parameters", "stage_results", "metadata", "jobs"]:
                    column_parts.extend([sql.SQL(" DEFAULT "), sql.SQL("'{}'")])  # JSONB empty object
                elif field_name in ["created_at", "updated_at"]:
                    column_parts.extend([sql.SQL(" DEFAULT NOW()")])

            # Special defaults for specific fields
            if field_name == "created_at" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT NOW()")])
            elif field_name == "updated_at" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT NOW()")])
            elif field_name == "parameters" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT '{}'")])  # JSONB empty object
            elif field_name == "stage_results" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT '{}'")])  # JSONB empty object
            elif field_name == "metadata" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT '{}'")])  # JSONB empty object
            elif field_name == "jobs" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT '{}'")])  # JSONB empty object
            elif field_name == "source_metadata" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT '{}'")])  # JSONB empty object for ETL metadata
            elif field_name == "retry_count" and " DEFAULT" not in str(sql.SQL("").join(column_parts)):
                column_parts.extend([sql.SQL(" DEFAULT 0")])  # Platform retry count (01 JAN 2026)

            columns.append(sql.SQL("").join(column_parts))
        
        # Add primary key constraint
        if table_name == "jobs":
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("job_id"))
            )
        elif table_name == "tasks":
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("task_id"))
            )
            constraints.append(
                sql.SQL("FOREIGN KEY ({}) REFERENCES {}.{} ({}) ON DELETE CASCADE").format(
                    sql.Identifier("parent_job_id"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs"),
                    sql.Identifier("job_id")
                )
            )
        elif table_name == "api_requests":
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("request_id"))
            )
        elif table_name == "orchestration_jobs":
            constraints.append(
                sql.SQL("PRIMARY KEY ({}, {})").format(
                    sql.Identifier("request_id"),
                    sql.Identifier("job_id")
                )
            )
            constraints.append(
                sql.SQL("FOREIGN KEY ({}) REFERENCES {}.{} ({}) ON DELETE CASCADE").format(
                    sql.Identifier("request_id"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("api_requests"),
                    sql.Identifier("request_id")
                )
            )
        elif table_name == "janitor_runs":
            # Janitor audit table (21 NOV 2025)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("run_id"))
            )
        elif table_name == "unpublish_jobs":
            # Unpublish audit table (12 DEC 2025)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("unpublish_id"))
            )
        elif table_name == "etl_source_files":
            # ETL tracking table (21 DEC 2025) - PRIMARY KEY on id, UNIQUE on (etl_type, source_blob_path)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("id"))
            )
            constraints.append(
                sql.SQL("UNIQUE ({}, {})").format(
                    sql.Identifier("etl_type"),
                    sql.Identifier("source_blob_path")
                )
            )
        elif table_name == "curated_datasets":
            # Curated datasets registry (15 DEC 2025)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("dataset_id"))
            )
        elif table_name == "curated_update_log":
            # Curated update audit log (15 DEC 2025)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("log_id"))
            )
        elif table_name == "promoted_datasets":
            # Promoted datasets registry (23 DEC 2025)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("promoted_id"))
            )
        elif table_name == "dataset_refs":
            # External references table (09 JAN 2026 - F7.8)
            # Composite primary key on (dataset_id, data_type)
            constraints.append(
                sql.SQL("PRIMARY KEY ({}, {})").format(
                    sql.Identifier("dataset_id"),
                    sql.Identifier("data_type")
                )
            )
        elif table_name == "cog_metadata":
            # Raster metadata table (09 JAN 2026 - F7.9)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("cog_id"))
            )
        elif table_name == "artifacts":
            # Artifact registry table (20 JAN 2026)
            constraints.append(
                sql.SQL("PRIMARY KEY ({})").format(sql.Identifier("artifact_id"))
            )

        # Combine columns and constraints
        all_parts = columns + constraints
        
        # Build CREATE TABLE statement
        composed = sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
            sql.Identifier(self.schema_name),
            sql.Identifier(table_name),
            sql.SQL(", ").join(all_parts)
        )
        
        self.logger.debug(f"✅ Table {table_name} composed with {len(columns)} columns and {len(constraints)} constraints")
        return composed
    
    # REMOVED: generate_table_ddl() - replaced by generate_table_composed()
    # Following "No Backward Compatibility" philosophy
    # This method used string concatenation which is unsafe
    # All table generation now uses psycopg.sql composition
        
    def generate_indexes_composed(self, table_name: str, model: Type[BaseModel]) -> List[sql.Composed]:
        """
        Generate index statements using IndexBuilder from ddl_utils.

        Uses centralized IndexBuilder for DRY index generation.

        Args:
            table_name: Name of the table
            model: Pydantic model class

        Returns:
            List of composed CREATE INDEX statements
        """
        self.logger.debug(f"🔧 Generating indexes for table {table_name}")
        indexes = []
        s = self.schema_name  # Shorthand

        if table_name == "jobs":
            indexes.append(IndexBuilder.btree(s, "jobs", "status", name="idx_jobs_status"))
            indexes.append(IndexBuilder.btree(s, "jobs", "job_type", name="idx_jobs_job_type"))
            indexes.append(IndexBuilder.btree(s, "jobs", "created_at", name="idx_jobs_created_at"))
            indexes.append(IndexBuilder.btree(s, "jobs", "updated_at", name="idx_jobs_updated_at"))
            # V0.8 Release Control: Asset & Platform linkage (30 JAN 2026)
            indexes.append(IndexBuilder.btree(
                s, "jobs", "asset_id", name="idx_jobs_asset",
                partial_where="asset_id IS NOT NULL"
            ))
            indexes.append(IndexBuilder.btree(
                s, "jobs", "platform_id", name="idx_jobs_platform",
                partial_where="platform_id IS NOT NULL"
            ))

        elif table_name == "tasks":
            indexes.append(IndexBuilder.btree(s, "tasks", "parent_job_id", name="idx_tasks_parent_job_id"))
            indexes.append(IndexBuilder.btree(s, "tasks", "status", name="idx_tasks_status"))
            indexes.append(IndexBuilder.btree(s, "tasks", ["parent_job_id", "stage"], name="idx_tasks_job_stage"))
            indexes.append(IndexBuilder.btree(s, "tasks", ["parent_job_id", "stage", "status"], name="idx_tasks_job_stage_status"))
            indexes.append(IndexBuilder.btree(s, "tasks", "last_pulse", name="idx_tasks_last_pulse",
                                              partial_where="last_pulse IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "tasks", "retry_count", name="idx_tasks_retry_count",
                                              partial_where="retry_count > 0"))
            indexes.append(IndexBuilder.btree(s, "tasks", "target_queue", name="idx_tasks_target_queue"))
            indexes.append(IndexBuilder.btree(s, "tasks", "executed_by_app", name="idx_tasks_executed_by_app"))
            # Checkpoint index (11 JAN 2026 - Docker worker resume support)
            indexes.append(IndexBuilder.btree(s, "tasks", "checkpoint_phase", name="idx_tasks_checkpoint_phase",
                                              partial_where="checkpoint_phase IS NOT NULL"))

        elif table_name == "api_requests":
            # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
            indexes.append(IndexBuilder.btree(s, "api_requests", "dataset_id", name="idx_api_requests_dataset_id"))
            indexes.append(IndexBuilder.btree(s, "api_requests", "created_at", name="idx_api_requests_created_at"))
            # V0.8 Release Control: Asset & Platform linkage (30 JAN 2026)
            indexes.append(IndexBuilder.btree(
                s, "api_requests", "asset_id", name="idx_api_requests_asset",
                partial_where="asset_id IS NOT NULL"
            ))
            indexes.append(IndexBuilder.btree(
                s, "api_requests", "platform_id", name="idx_api_requests_platform",
                partial_where="platform_id IS NOT NULL"
            ))

        elif table_name == "orchestration_jobs":
            indexes.append(IndexBuilder.btree(s, "orchestration_jobs", "request_id", name="idx_orchestration_jobs_request_id"))
            indexes.append(IndexBuilder.btree(s, "orchestration_jobs", "job_id", name="idx_orchestration_jobs_job_id"))

        elif table_name == "janitor_runs":
            indexes.append(IndexBuilder.btree(s, "janitor_runs", "started_at", name="idx_janitor_runs_started_at", descending=True))
            indexes.append(IndexBuilder.btree(s, "janitor_runs", "run_type", name="idx_janitor_runs_type"))

        elif table_name == "etl_source_files":
            # Generalized ETL tracking table (21 DEC 2025)
            # Note: UNIQUE constraint on (etl_type, source_blob_path) is in table definition
            indexes.append(IndexBuilder.btree(s, "etl_source_files", "etl_type", name="idx_etl_source_files_type"))
            indexes.append(IndexBuilder.btree(s, "etl_source_files", ["etl_type", "phase1_group_key"], name="idx_etl_source_files_p1_group"))
            indexes.append(IndexBuilder.btree(s, "etl_source_files", ["etl_type", "phase2_group_key"], name="idx_etl_source_files_p2_group"))
            # Partial indexes for finding unprocessed records by ETL type
            indexes.append(IndexBuilder.btree(s, "etl_source_files", ["etl_type", "phase1_group_key"], name="idx_etl_source_files_p1_pending",
                                              partial_where="phase1_completed_at IS NULL"))
            indexes.append(IndexBuilder.btree(s, "etl_source_files", ["etl_type", "phase2_group_key"], name="idx_etl_source_files_p2_pending",
                                              partial_where="phase1_completed_at IS NOT NULL AND phase2_completed_at IS NULL"))

        elif table_name == "unpublish_jobs":
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "stac_item_id", name="idx_unpublish_jobs_stac_item"))
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "collection_id", name="idx_unpublish_jobs_collection"))
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "original_job_id", name="idx_unpublish_jobs_original_job"))
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "status", name="idx_unpublish_jobs_status"))
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "created_at", name="idx_unpublish_jobs_created_at", descending=True))
            indexes.append(IndexBuilder.btree(s, "unpublish_jobs", "unpublish_job_id", name="idx_unpublish_jobs_unpublish_job_id"))

        elif table_name == "curated_datasets":
            # Curated datasets registry (15 DEC 2025)
            indexes.append(IndexBuilder.btree(s, "curated_datasets", "enabled", name="idx_curated_datasets_enabled"))
            indexes.append(IndexBuilder.btree(s, "curated_datasets", "target_table_name", name="idx_curated_datasets_target_table"))
            # Partial index for finding scheduled datasets
            indexes.append(IndexBuilder.btree(s, "curated_datasets", "update_schedule", name="idx_curated_datasets_scheduled",
                                              partial_where="enabled = true AND update_schedule IS NOT NULL"))

        elif table_name == "curated_update_log":
            # Curated update audit log (15 DEC 2025)
            indexes.append(IndexBuilder.btree(s, "curated_update_log", "dataset_id", name="idx_curated_update_log_dataset"))
            indexes.append(IndexBuilder.btree(s, "curated_update_log", "job_id", name="idx_curated_update_log_job"))
            indexes.append(IndexBuilder.btree(s, "curated_update_log", "status", name="idx_curated_update_log_status"))
            indexes.append(IndexBuilder.btree(s, "curated_update_log", "started_at", name="idx_curated_update_log_started", descending=True))

        elif table_name == "promoted_datasets":
            # Promoted datasets registry (23 DEC 2025)
            indexes.append(IndexBuilder.btree(s, "promoted_datasets", "stac_collection_id", name="idx_promoted_datasets_collection",
                                              partial_where="stac_collection_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "promoted_datasets", "stac_item_id", name="idx_promoted_datasets_item",
                                              partial_where="stac_item_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "promoted_datasets", "in_gallery", name="idx_promoted_datasets_gallery",
                                              partial_where="in_gallery = true"))
            indexes.append(IndexBuilder.btree(s, "promoted_datasets", "gallery_order", name="idx_promoted_datasets_gallery_order",
                                              partial_where="in_gallery = true AND gallery_order IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "promoted_datasets", "system_role", name="idx_promoted_datasets_system_role",
                                              partial_where="system_role IS NOT NULL"))

        elif table_name == "system_snapshots":
            # System snapshots for configuration drift detection (04 JAN 2026)
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "captured_at", name="idx_system_snapshots_captured_at", descending=True))
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "trigger_type", name="idx_system_snapshots_trigger_type"))
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "config_hash", name="idx_system_snapshots_config_hash"))
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "instance_id", name="idx_system_snapshots_instance_id",
                                              partial_where="instance_id IS NOT NULL"))
            # Drift detection queries
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "has_drift", name="idx_system_snapshots_has_drift",
                                              partial_where="has_drift = true"))
            # Config quality monitoring
            indexes.append(IndexBuilder.btree(s, "system_snapshots", "config_defaults_count", name="idx_system_snapshots_defaults_count",
                                              partial_where="config_defaults_count > 0"))

        elif table_name == "dataset_refs":
            # External references table (09 JAN 2026 - F7.8)
            # Indexes for DDH lookup queries
            indexes.append(IndexBuilder.btree(s, "dataset_refs", "ddh_dataset_id", name="idx_dataset_refs_ddh_dataset",
                                              partial_where="ddh_dataset_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "dataset_refs", "ddh_resource_id", name="idx_dataset_refs_ddh_resource",
                                              partial_where="ddh_resource_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "dataset_refs", "data_type", name="idx_dataset_refs_data_type"))

        elif table_name == "cog_metadata":
            # Raster metadata table (09 JAN 2026 - F7.9)
            # Indexes for STAC and ETL queries
            indexes.append(IndexBuilder.btree(s, "cog_metadata", "stac_collection_id", name="idx_cog_metadata_stac_collection",
                                              partial_where="stac_collection_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "cog_metadata", "stac_item_id", name="idx_cog_metadata_stac_item",
                                              partial_where="stac_item_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "cog_metadata", "etl_job_id", name="idx_cog_metadata_etl_job",
                                              partial_where="etl_job_id IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "cog_metadata", "container", name="idx_cog_metadata_container"))
            indexes.append(IndexBuilder.btree(s, "cog_metadata", "created_at", name="idx_cog_metadata_created_at", descending=True))

        elif table_name == "artifacts":
            # Artifact registry table (20 JAN 2026)
            # Primary lookup: Find artifact by client references (GIN index for JSONB)
            indexes.append(IndexBuilder.gin(s, "artifacts", "client_refs", name="idx_artifacts_client_refs"))
            # Client type filtering
            indexes.append(IndexBuilder.btree(s, "artifacts", "client_type", name="idx_artifacts_client_type"))
            # STAC reverse lookup
            indexes.append(IndexBuilder.btree(s, "artifacts", ["stac_collection_id", "stac_item_id"], name="idx_artifacts_stac",
                                              partial_where="stac_item_id IS NOT NULL"))
            # Job lookup
            indexes.append(IndexBuilder.btree(s, "artifacts", "source_job_id", name="idx_artifacts_job",
                                              partial_where="source_job_id IS NOT NULL"))
            # Lineage queries
            indexes.append(IndexBuilder.btree(s, "artifacts", "supersedes", name="idx_artifacts_supersedes",
                                              partial_where="supersedes IS NOT NULL"))
            # Active artifacts only
            indexes.append(IndexBuilder.btree(s, "artifacts", "status", name="idx_artifacts_active",
                                              partial_where="status = 'active'"))
            # Content deduplication
            indexes.append(IndexBuilder.btree(s, "artifacts", "content_hash", name="idx_artifacts_content_hash",
                                              partial_where="content_hash IS NOT NULL"))
            # Time-based queries
            indexes.append(IndexBuilder.btree(s, "artifacts", "created_at", name="idx_artifacts_created_at", descending=True))

        self.logger.debug(f"✅ Generated {len(indexes)} indexes for table {table_name}")
        return indexes
    
    def generate_static_functions(self) -> List[sql.Composed]:
        """
        Generate static PostgreSQL function definitions using proper SQL composition.
        
        Uses psycopg.sql composition for all identifiers and schema references
        to avoid SQL injection and properly handle special characters.
        
        Returns:
            List of sql.Composed CREATE FUNCTION statements
        """
        functions = []
        
        # 1. complete_task_and_check_stage function
        body_complete_task = """
DECLARE
    v_job_id VARCHAR(64);
    v_stage INTEGER;
    v_remaining INTEGER;
    v_task_status {schema}.task_status;
BEGIN
    -- Get task info and update atomically
    -- Now validates that p_job_id and p_stage match the task's actual values
    UPDATE {schema}.tasks 
    SET 
        status = CASE 
            WHEN p_error_details IS NOT NULL THEN 'failed'::{schema}.task_status
            ELSE 'completed'::{schema}.task_status
        END,
        result_data = p_result_data,
        error_details = p_error_details,
        updated_at = NOW()
    WHERE 
        task_id = p_task_id 
        AND parent_job_id = p_job_id  -- Validate job_id matches
        AND stage = p_stage            -- Validate stage matches
        AND status = 'processing'
    RETURNING parent_job_id, stage, status
    INTO v_job_id, v_stage, v_task_status;
    
    IF v_job_id IS NULL THEN
        RETURN QUERY SELECT FALSE, FALSE, NULL::VARCHAR(64), NULL::INTEGER, 0::INTEGER;
        RETURN;
    END IF;
    
    -- Use advisory lock to prevent race conditions without row-level locks
    -- This avoids deadlocks when many tasks complete simultaneously
    -- Lock key is hash of job_id and stage to serialize per stage
    PERFORM pg_advisory_xact_lock(
        hashtext(v_job_id || ':stage:' || v_stage::text)
    );
    
    -- Count remaining non-completed tasks in the same stage
    -- Now that we have the lock, this count will be accurate
    SELECT COUNT(*)::INTEGER INTO v_remaining
    FROM {schema}.tasks 
    WHERE parent_job_id = v_job_id 
      AND stage = v_stage 
      AND status NOT IN ('completed', 'failed');
    
    RETURN QUERY SELECT 
        TRUE,
        v_remaining = 0,
        v_job_id,
        v_stage,
        v_remaining;
END;
""".format(schema=self.schema_name)  # Safe - schema_name is controlled
        
        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}(
    p_task_id VARCHAR(100),
    p_job_id VARCHAR(64),         -- Added to match Python interface
    p_stage INTEGER,              -- Added to match Python interface
    p_result_data JSONB DEFAULT NULL,
    p_error_details TEXT DEFAULT NULL
)
RETURNS TABLE (
    task_updated BOOLEAN,
    is_last_task_in_stage BOOLEAN,
    job_id VARCHAR(64),
    stage_number INTEGER,
    remaining_tasks INTEGER
)
LANGUAGE plpgsql
AS $$
{}
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("complete_task_and_check_stage"),
            sql.SQL(body_complete_task)
        ))
        
        # 2. advance_job_stage function  
        body_advance_stage = """
DECLARE
    v_total_stages INTEGER;
    v_new_stage INTEGER;
BEGIN
    -- Update job stage and stage results atomically
    UPDATE {schema}.jobs
    SET 
        stage = stage + 1,
        stage_results = CASE 
            WHEN p_stage_results IS NOT NULL THEN
                stage_results || jsonb_build_object(p_current_stage::text, p_stage_results)
            ELSE stage_results
        END,
        status = CASE 
            WHEN stage + 1 > total_stages THEN 'completed'::{schema}.job_status
            ELSE 'processing'::{schema}.job_status
        END,
        updated_at = NOW()
    WHERE 
        job_id = p_job_id 
        AND stage = p_current_stage
    RETURNING stage, total_stages
    INTO v_new_stage, v_total_stages;
    
    IF v_new_stage IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, NULL::BOOLEAN;
        RETURN;
    END IF;
    
    RETURN QUERY SELECT 
        TRUE,
        v_new_stage,
        v_new_stage > v_total_stages;
END;
""".format(schema=self.schema_name)
        
        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}(
    p_job_id VARCHAR(64),
    p_current_stage INTEGER,
    p_stage_results JSONB DEFAULT NULL
)
RETURNS TABLE (
    job_updated BOOLEAN,
    new_stage INTEGER,
    is_final_stage BOOLEAN
)
LANGUAGE plpgsql  
AS $$
{}
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("advance_job_stage"),
            sql.SQL(body_advance_stage)
        ))
        
        # 3. check_job_completion function
        body_check_completion = """
DECLARE
    v_job_record RECORD;
    v_task_counts RECORD;
BEGIN
    -- Get job info with row-level lock
    SELECT job_id, job_type, status, stage, total_stages, stage_results
    INTO v_job_record
    FROM {schema}.jobs 
    WHERE job_id = p_job_id
    FOR UPDATE;
    
    IF v_job_record.job_id IS NULL THEN
        RETURN QUERY SELECT 
            FALSE,
            0::INTEGER,
            0::BIGINT,
            0::BIGINT,
            '[]'::jsonb;
        RETURN;
    END IF;
    
    -- Count tasks for this job
    SELECT 
        COUNT(*)::BIGINT as total_tasks,
        COUNT(CASE WHEN status = 'completed' THEN 1 END)::BIGINT as completed_tasks,
        COUNT(CASE WHEN status = 'failed' THEN 1 END)::BIGINT as failed_tasks,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'task_id', task_id,
                    'task_type', task_type,
                    'stage', stage,
                    'task_index', task_index,
                    'status', status::text,
                    'result_data', result_data,
                    'error_details', error_details
                )
            ) FILTER (WHERE result_data IS NOT NULL OR error_details IS NOT NULL), 
            '[]'::jsonb
        ) as task_results
    INTO v_task_counts
    FROM {schema}.tasks 
    WHERE parent_job_id = p_job_id;
    
    RETURN QUERY SELECT 
        (
            v_task_counts.total_tasks > 0 AND 
            (v_task_counts.completed_tasks + v_task_counts.failed_tasks) = v_task_counts.total_tasks AND
            v_job_record.stage >= v_job_record.total_stages
        ) as job_complete,
        v_job_record.stage as final_stage,
        v_task_counts.total_tasks,
        v_task_counts.completed_tasks,
        v_task_counts.task_results;
END;
""".format(schema=self.schema_name)
        
        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}(
    p_job_id VARCHAR(64)
)
RETURNS TABLE (
    job_complete BOOLEAN,
    final_stage INTEGER,
    total_tasks BIGINT,
    completed_tasks BIGINT,
    task_results JSONB
)
LANGUAGE plpgsql
AS $$
{}
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("check_job_completion"),
            sql.SQL(body_check_completion)
        ))
        
        # 4. increment_task_retry_count function (for exponential backoff retry)
        body_increment_retry = """
DECLARE
    v_new_retry_count INTEGER;
BEGIN
    -- Atomically increment retry count and reset status to QUEUED
    -- This supports exponential backoff retry with Service Bus scheduled delivery
    UPDATE {schema}.tasks
    SET
        retry_count = retry_count + 1,
        status = 'queued'::{schema}.task_status,
        updated_at = NOW()
    WHERE task_id = p_task_id
    RETURNING retry_count INTO v_new_retry_count;

    -- Return the new retry count (NULL if task not found)
    RETURN QUERY SELECT v_new_retry_count;
END;
""".format(schema=self.schema_name)

        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}(
    p_task_id VARCHAR(100)
)
RETURNS TABLE (
    new_retry_count INTEGER
)
LANGUAGE plpgsql
AS $$
{}
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("increment_task_retry_count"),
            sql.SQL(body_increment_retry)
        ))

        # 5. update_updated_at_column trigger function
        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("update_updated_at_column")
        ))

        # 6. upsert_geospatial_asset function (V0.8 Entity Architecture - 30 JAN 2026)
        # Uses advisory locks to serialize concurrent requests for the same asset
        # V0.8: Uses platform_id + platform_refs instead of explicit DDH columns
        # V0.8 Release Control: Added lineage_id, version_ordinal, previous_asset_id, is_latest
        body_upsert_asset = """
DECLARE
    v_existing RECORD;
BEGIN
    -- Acquire advisory lock for this asset_id (serialize concurrent requests)
    PERFORM pg_advisory_xact_lock(hashtext(p_asset_id));

    -- Check for existing record (excluding soft-deleted)
    SELECT * INTO v_existing
    FROM {schema}.geospatial_assets
    WHERE asset_id = p_asset_id
      AND deleted_at IS NULL;

    IF v_existing IS NULL THEN
        -- Check if soft-deleted version exists
        SELECT * INTO v_existing
        FROM {schema}.geospatial_assets
        WHERE asset_id = p_asset_id
          AND deleted_at IS NOT NULL;

        IF v_existing IS NOT NULL THEN
            -- Reactivate soft-deleted asset
            UPDATE {schema}.geospatial_assets SET
                deleted_at = NULL,
                deleted_by = NULL,
                revision = v_existing.revision + 1,
                current_job_id = NULL,
                approval_state = 'pending_review'::{schema}.approval_state,
                clearance_state = 'uncleared'::{schema}.clearance_state,
                reviewer = NULL,
                reviewed_at = NULL,
                rejection_reason = NULL,
                adf_run_id = NULL,
                cleared_at = NULL,
                cleared_by = NULL,
                made_public_at = NULL,
                made_public_by = NULL,
                table_name = p_table_name,
                blob_path = p_blob_path,
                -- V0.8 Release Control: Update lineage fields on reactivation
                lineage_id = COALESCE(p_lineage_id, v_existing.lineage_id),
                version_ordinal = COALESCE(p_version_ordinal, v_existing.version_ordinal),
                previous_asset_id = COALESCE(p_previous_asset_id, v_existing.previous_asset_id),
                is_latest = COALESCE(p_is_latest, TRUE),
                is_served = TRUE,
                updated_at = NOW()
            WHERE asset_id = p_asset_id;

            RETURN QUERY SELECT 'reactivated'::VARCHAR(20), v_existing.revision + 1, NULL::TEXT;
        ELSE
            -- Create new asset (V0.8: platform_id + platform_refs + lineage fields)
            INSERT INTO {schema}.geospatial_assets (
                asset_id, platform_id, platform_refs,
                lineage_id, version_ordinal, previous_asset_id, is_latest, is_served,
                data_type, stac_item_id, stac_collection_id,
                table_name, blob_path,
                revision, approval_state, clearance_state
            ) VALUES (
                p_asset_id, p_platform_id, p_platform_refs,
                p_lineage_id, COALESCE(p_version_ordinal, 1), p_previous_asset_id, COALESCE(p_is_latest, TRUE), TRUE,
                p_data_type, p_stac_item_id, p_stac_collection_id,
                p_table_name, p_blob_path,
                1, 'pending_review'::{schema}.approval_state, 'uncleared'::{schema}.clearance_state
            );
            RETURN QUERY SELECT 'created'::VARCHAR(20), 1, NULL::TEXT;
        END IF;

    ELSIF p_overwrite THEN
        -- Log current revision to history (only if current_job_id exists)
        IF v_existing.current_job_id IS NOT NULL THEN
            INSERT INTO {schema}.asset_revisions (
                revision_id, asset_id, revision, job_id, content_hash,
                approval_state_at_supersession, clearance_state_at_supersession,
                reviewer_at_supersession, created_at, superseded_at
            ) VALUES (
                gen_random_uuid(),
                v_existing.asset_id,
                v_existing.revision,
                v_existing.current_job_id,
                v_existing.content_hash,
                v_existing.approval_state,
                v_existing.clearance_state,
                v_existing.reviewer,
                v_existing.created_at,
                NOW()
            );
        END IF;

        -- Update to new revision
        UPDATE {schema}.geospatial_assets SET
            revision = revision + 1,
            current_job_id = NULL,
            content_hash = NULL,
            approval_state = 'pending_review'::{schema}.approval_state,
            clearance_state = 'uncleared'::{schema}.clearance_state,
            reviewer = NULL,
            reviewed_at = NULL,
            rejection_reason = NULL,
            adf_run_id = NULL,
            cleared_at = NULL,
            cleared_by = NULL,
            made_public_at = NULL,
            made_public_by = NULL,
            table_name = COALESCE(p_table_name, table_name),
            blob_path = COALESCE(p_blob_path, blob_path),
            -- V0.8 Release Control: Update lineage fields on overwrite
            lineage_id = COALESCE(p_lineage_id, lineage_id),
            version_ordinal = COALESCE(p_version_ordinal, version_ordinal),
            previous_asset_id = COALESCE(p_previous_asset_id, previous_asset_id),
            is_latest = COALESCE(p_is_latest, is_latest),
            updated_at = NOW()
        WHERE asset_id = p_asset_id;

        RETURN QUERY SELECT 'updated'::VARCHAR(20), v_existing.revision + 1, NULL::TEXT;

    ELSE
        -- Exists and no overwrite requested
        RETURN QUERY SELECT 'exists'::VARCHAR(20), v_existing.revision,
            'Asset exists. Use overwrite=true to replace.'::TEXT;
    END IF;
END;
""".format(schema=self.schema_name)

        functions.append(sql.SQL("""
CREATE OR REPLACE FUNCTION {}.{}(
    p_asset_id VARCHAR(64),
    p_platform_id VARCHAR(50),
    p_platform_refs JSONB,
    p_data_type VARCHAR(20),
    p_stac_item_id VARCHAR(200),
    p_stac_collection_id VARCHAR(200),
    p_table_name VARCHAR(63) DEFAULT NULL,
    p_blob_path VARCHAR(500) DEFAULT NULL,
    p_overwrite BOOLEAN DEFAULT FALSE,
    -- V0.8 Release Control: Lineage parameters (30 JAN 2026)
    p_lineage_id VARCHAR(64) DEFAULT NULL,
    p_version_ordinal INTEGER DEFAULT NULL,
    p_previous_asset_id VARCHAR(64) DEFAULT NULL,
    p_is_latest BOOLEAN DEFAULT NULL
)
RETURNS TABLE (
    operation VARCHAR(20),
    new_revision INTEGER,
    error_message TEXT
)
LANGUAGE plpgsql
AS $$
{}
$$""").format(
            sql.Identifier(self.schema_name),
            sql.Identifier("upsert_geospatial_asset"),
            sql.SQL(body_upsert_asset)
        ))

        return functions
        
    def generate_triggers_composed(self) -> List[sql.Composed]:
        """
        Generate trigger statements using TriggerBuilder from ddl_utils.

        Uses centralized TriggerBuilder for DRY trigger generation.

        Returns:
            List of composed trigger statements
        """
        self.logger.debug(f"🔧 Generating triggers for updated_at columns")
        triggers = []

        # Updated_at triggers for jobs and tasks tables
        # TriggerBuilder.updated_at_trigger returns [DROP, CREATE] statements
        triggers.extend(TriggerBuilder.updated_at_trigger(self.schema_name, "jobs", "update_jobs_updated_at"))
        triggers.extend(TriggerBuilder.updated_at_trigger(self.schema_name, "tasks", "update_tasks_updated_at"))

        self.logger.debug(f"✅ Generated {len(triggers)} trigger statements")
        return triggers

    def generate_seed_data(self) -> List[sql.Composed]:
        """
        Generate seed data INSERT statements.

        V0.8 (29 JAN 2026): Seeds DDH platform for Platform Registry.
        Uses ON CONFLICT DO NOTHING for idempotent execution.

        Returns:
            List of composed INSERT statements
        """
        self.logger.debug("🌱 Generating seed data")
        seeds = []

        # Seed DDH platform (V0.8 - 29 JAN 2026, updated 30 JAN 2026 for versioning)
        # Uses ON CONFLICT DO NOTHING for safe re-execution
        seeds.append(sql.SQL("""
INSERT INTO {schema}.{table} (
    platform_id, display_name, description, required_refs, optional_refs,
    nominal_refs, version_ref, uses_versioning, is_active
) VALUES (
    {platform_id},
    {display_name},
    {description},
    {required_refs}::jsonb,
    {optional_refs}::jsonb,
    {nominal_refs}::jsonb,
    {version_ref},
    {uses_versioning},
    {is_active}
) ON CONFLICT (platform_id) DO NOTHING
""").format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms"),
            platform_id=sql.Literal(DDH_PLATFORM.platform_id),
            display_name=sql.Literal(DDH_PLATFORM.display_name),
            description=sql.Literal(DDH_PLATFORM.description),
            required_refs=sql.Literal(str(DDH_PLATFORM.required_refs).replace("'", '"')),
            optional_refs=sql.Literal(str(DDH_PLATFORM.optional_refs).replace("'", '"')),
            nominal_refs=sql.Literal(str(DDH_PLATFORM.nominal_refs).replace("'", '"')),
            version_ref=sql.Literal(DDH_PLATFORM.version_ref),
            uses_versioning=sql.Literal(DDH_PLATFORM.uses_versioning),
            is_active=sql.Literal(DDH_PLATFORM.is_active)
        ))

        self.logger.debug(f"✅ Generated {len(seeds)} seed data statements")
        return seeds

    # REMOVED: generate_triggers() - replaced by generate_triggers_composed()
    # Following "No Backward Compatibility" philosophy
    # This method used string concatenation which is unsafe
    # All trigger generation now uses psycopg.sql composition
        
    def generate_composed_statements(self) -> List[sql.Composed]:
        """
        Generate PostgreSQL schema as a list of composed SQL statements.
        
        This method generates psycopg.sql.Composed objects for safe execution,
        avoiding string concatenation and SQL injection issues.
        
        Returns:
            List of sql.Composed objects for direct execution
        """
        self.logger.info("🚀 Starting SQL composition with psycopg.sql")
        composed = []
        
        # Schema creation
        composed.append(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(self.schema_name)
            )
        )
        
        # Set search path
        composed.append(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(self.schema_name)
            )
        )
        
        # Generate ENUMs using composed SQL (returns list of statements)
        composed.extend(self.generate_enum("job_status", JobStatus))
        composed.extend(self.generate_enum("task_status", TaskStatus))
        composed.extend(self.generate_enum("platform_request_status", PlatformRequestStatus))
        composed.extend(self.generate_enum("data_type", DataType))
        composed.extend(self.generate_enum("janitor_run_type", JanitorRunType))
        composed.extend(self.generate_enum("janitor_run_status", JanitorRunStatus))
        composed.extend(self.generate_enum("unpublish_type", UnpublishType))  # Unpublish audit (12 DEC 2025)
        composed.extend(self.generate_enum("unpublish_status", UnpublishStatus))
        composed.extend(self.generate_enum("curated_source_type", CuratedSourceType))  # Curated datasets (15 DEC 2025)
        composed.extend(self.generate_enum("curated_update_strategy", CuratedUpdateStrategy))
        composed.extend(self.generate_enum("curated_update_type", CuratedUpdateType))
        composed.extend(self.generate_enum("curated_update_status", CuratedUpdateStatus))
        composed.extend(self.generate_enum("system_role", SystemRole))  # Promoted datasets (23 DEC 2025)
        # AccessLevel unified from Classification (25 JAN 2026 - S4.DM)
        # NOTE: RESTRICTED is defined but NOT YET SUPPORTED
        composed.extend(self.generate_enum("access_level", AccessLevel))
        composed.extend(self.generate_enum("snapshot_trigger_type", SnapshotTriggerType))  # System snapshots (04 JAN 2026)
        composed.extend(self.generate_enum("artifact_status", ArtifactStatus))  # Artifact registry (20 JAN 2026)
        composed.extend(self.generate_enum("service_type", ServiceType))  # External service registry (22 JAN 2026)
        composed.extend(self.generate_enum("service_status", ServiceStatus))  # External service registry (22 JAN 2026)
        composed.extend(self.generate_enum("map_type", MapType))  # Map states (23 JAN 2026)
        composed.extend(self.generate_enum("job_event_type", JobEventType))  # Job event tracking (23 JAN 2026)
        composed.extend(self.generate_enum("job_event_status", JobEventStatus))  # Job event tracking (23 JAN 2026)
        composed.extend(self.generate_enum("approval_state", ApprovalState))  # Geospatial assets (29 JAN 2026 - V0.8)
        composed.extend(self.generate_enum("clearance_state", ClearanceState))  # Geospatial assets (29 JAN 2026 - V0.8)
        composed.extend(self.generate_enum("processing_status", ProcessingStatus))  # DAG Orchestration (29 JAN 2026 - V0.8)

        # For tables, indexes, functions, and triggers, we still need string format
        # because they are complex multi-line statements
        # But we'll return them as sql.SQL objects for consistency

        # Tables - now using composed SQL
        # NOTE: OrchestrationJob REMOVED (22 NOV 2025) - no job chaining in Platform
        composed.append(self.generate_table_composed(JobRecord, "jobs"))
        composed.append(self.generate_table_composed(TaskRecord, "tasks"))
        composed.append(self.generate_table_composed(ApiRequest, "api_requests"))
        composed.append(self.generate_table_composed(JanitorRun, "janitor_runs"))
        composed.append(self.generate_table_composed(EtlSourceFile, "etl_source_files"))  # ETL tracking (21 DEC 2025 - generalized)
        composed.append(self.generate_table_composed(UnpublishJobRecord, "unpublish_jobs"))  # Unpublish audit (12 DEC 2025)
        composed.append(self.generate_table_composed(CuratedDataset, "curated_datasets"))  # Curated datasets (15 DEC 2025)
        composed.append(self.generate_table_composed(CuratedUpdateLog, "curated_update_log"))
        composed.append(self.generate_table_composed(PromotedDataset, "promoted_datasets"))  # Promoted datasets (23 DEC 2025)
        composed.append(self.generate_table_composed(SystemSnapshotRecord, "system_snapshots"))  # System snapshots (04 JAN 2026)
        composed.append(self.generate_table_composed(DatasetRefRecord, "dataset_refs"))  # External references (09 JAN 2026 - F7.8)
        composed.append(self.generate_table_composed(CogMetadataRecord, "cog_metadata"))  # Raster metadata (09 JAN 2026 - F7.9)
        composed.append(self.generate_table_composed(Artifact, "artifacts"))  # Artifact registry (20 JAN 2026)
        composed.append(self.generate_table_from_model(ExternalService))  # External service registry (22 JAN 2026)
        composed.append(self.generate_table_from_model(MapState))  # Map states (23 JAN 2026)
        composed.append(self.generate_table_from_model(MapStateSnapshot))  # Map state snapshots (23 JAN 2026)
        composed.append(self.generate_table_from_model(JobEvent))  # Job event tracking (23 JAN 2026)
        composed.append(self.generate_table_from_model(Platform))  # Platform registry (29 JAN 2026 - V0.8) - before assets (FK)
        composed.append(self.generate_table_from_model(GeospatialAsset))  # Geospatial assets (29 JAN 2026 - V0.8)
        composed.append(self.generate_table_from_model(AssetRevision))  # Asset revisions (29 JAN 2026 - V0.8)

        # Indexes - now using composed SQL
        composed.extend(self.generate_indexes_composed("jobs", JobRecord))
        composed.extend(self.generate_indexes_composed("tasks", TaskRecord))
        composed.extend(self.generate_indexes_composed("api_requests", ApiRequest))
        composed.extend(self.generate_indexes_composed("janitor_runs", JanitorRun))
        composed.extend(self.generate_indexes_composed("etl_source_files", EtlSourceFile))  # ETL tracking (21 DEC 2025 - generalized)
        composed.extend(self.generate_indexes_composed("unpublish_jobs", UnpublishJobRecord))  # Unpublish audit (12 DEC 2025)
        composed.extend(self.generate_indexes_composed("curated_datasets", CuratedDataset))  # Curated datasets (15 DEC 2025)
        composed.extend(self.generate_indexes_composed("curated_update_log", CuratedUpdateLog))
        composed.extend(self.generate_indexes_composed("promoted_datasets", PromotedDataset))  # Promoted datasets (23 DEC 2025)
        composed.extend(self.generate_indexes_composed("system_snapshots", SystemSnapshotRecord))  # System snapshots (04 JAN 2026)
        composed.extend(self.generate_indexes_composed("dataset_refs", DatasetRefRecord))  # External references (09 JAN 2026 - F7.8)
        composed.extend(self.generate_indexes_composed("cog_metadata", CogMetadataRecord))  # Raster metadata (09 JAN 2026 - F7.9)
        composed.extend(self.generate_indexes_composed("artifacts", Artifact))  # Artifact registry (20 JAN 2026)
        composed.extend(self.generate_indexes_from_model(ExternalService))  # External service registry (22 JAN 2026)
        composed.extend(self.generate_indexes_from_model(MapState))  # Map states (23 JAN 2026)
        composed.extend(self.generate_indexes_from_model(MapStateSnapshot))  # Map state snapshots (23 JAN 2026)
        composed.extend(self.generate_indexes_from_model(JobEvent))  # Job event tracking (23 JAN 2026)
        composed.extend(self.generate_indexes_from_model(Platform))  # Platform registry (29 JAN 2026 - V0.8)
        composed.extend(self.generate_indexes_from_model(GeospatialAsset))  # Geospatial assets (29 JAN 2026 - V0.8)
        composed.extend(self.generate_indexes_from_model(AssetRevision))  # Asset revisions (29 JAN 2026 - V0.8)

        # Functions - already sql.Composed objects
        composed.extend(self.generate_static_functions())
            
        # Triggers - now using composed SQL
        composed.extend(self.generate_triggers_composed())

        # Seed data - Platform Registry (V0.8 - 29 JAN 2026)
        composed.extend(self.generate_seed_data())

        self.logger.info(f"✅ SQL composition complete: {len(composed)} total statements")
        
        return composed
    
    # REMOVED: generate_statements_list() - replaced by generate_composed_statements()
    # Following "No Backward Compatibility" philosophy
    # This method generated string-based SQL statements
    # All SQL generation now uses psycopg.sql composition for safety
    
    # REMOVED: Old string-based methods following "No Backward Compatibility" philosophy
    # The following methods have been removed:
    # - generate_complete_schema() - replaced by generate_composed_statements()
    # - generate_statements_list() - no longer needed
    # - generate_table_ddl() - replaced by generate_table_composed()
    # - generate_indexes() - replaced by generate_indexes_composed()
    # - generate_triggers() - replaced by generate_triggers_composed()
    
    # REMOVED: generate_complete_schema_REMOVED() - replaced by generate_composed_statements()
    # Following "No Backward Compatibility" philosophy
    # This method used string concatenation and called non-existent methods
    # All SQL generation now uses psycopg.sql composition ONLY
    
    def inspect(self, connection=None, verbose=True) -> Dict[str, List[str]]:
        """
        Inspect and display SQL statements that would be generated.
        
        This method provides a formatted view of all SQL statements that would
        be executed, organized by category. Useful for debugging and verification
        without actually executing the SQL.
        
        Args:
            connection: Optional psycopg connection for rendering SQL
            verbose: If True, print formatted output to console
            
        Returns:
            Dictionary with categorized SQL statements
        """
        # Generate the composed statements
        composed_statements = self.generate_composed_statements()
        
        # Categorize statements for better organization
        categories = {
            "SCHEMA & SETUP": [],
            "ENUM TYPES": [],
            "TABLES": [],
            "INDEXES": [],
            "FUNCTIONS": [],
            "TRIGGERS": []
        }
        
        # Process each statement
        for stmt in composed_statements:
            # Render the statement
            if connection:
                try:
                    stmt_str = stmt.as_string(connection)
                except Exception as e:
                    stmt_str = f"[Unable to render: {e}]"
            else:
                # Basic string representation without connection
                stmt_str = str(stmt)
            
            # Categorize based on content
            stmt_lower = stmt_str.lower()
            if 'create schema' in stmt_lower or 'set search_path' in stmt_lower:
                categories["SCHEMA & SETUP"].append(stmt_str)
            elif 'create type' in stmt_lower:
                categories["ENUM TYPES"].append(stmt_str)
            elif 'create table' in stmt_lower:
                categories["TABLES"].append(stmt_str)
            elif 'create index' in stmt_lower:
                categories["INDEXES"].append(stmt_str)
            elif 'create' in stmt_lower and 'function' in stmt_lower:
                categories["FUNCTIONS"].append(stmt_str)
            elif 'trigger' in stmt_lower:
                categories["TRIGGERS"].append(stmt_str)
        
        if verbose:
            self.logger.info("=" * 80)
            self.logger.info("SQL SCHEMA INSPECTION")
            self.logger.info("=" * 80)
            self.logger.info(f"\nSchema: {self.schema_name}")
            self.logger.info(f"Total statements: {len(composed_statements)}")
            self.logger.info("=" * 80)

            for category, statements in categories.items():
                if statements:
                    self.logger.info(f"\n{category} ({len(statements)} statements):")
                    self.logger.info("-" * 80)
                    for stmt_str in statements:
                        # Truncate very long statements for display
                        if len(stmt_str) > 2000:
                            lines = stmt_str.split('\n')
                            if len(lines) > 30:
                                for line in lines[:20]:
                                    self.logger.debug(line)
                                self.logger.debug("\n... [truncated] ...\n")
                                for line in lines[-5:]:
                                    self.logger.debug(line)
                            else:
                                self.logger.debug(stmt_str)
                        else:
                            self.logger.debug(stmt_str)
                        self.logger.debug(";")

            self.logger.info("\n" + "=" * 80)
            self.logger.info("SUMMARY")
            self.logger.info("=" * 80)
            for category, statements in categories.items():
                if statements:
                    self.logger.info(f"  {category:20} {len(statements):3} statements")

            if not connection:
                self.logger.warning("\n⚠️  Note: SQL shown without PostgreSQL rendering")
                self.logger.warning("  For properly formatted SQL, provide a connection")
        
        return categories


def main():
    """
    Inspect SQL schema generation without executing.
    
    This is now a simple wrapper around the PydanticToSQL.inspect() method,
    following proper OOP hierarchy.
    """
    import sys
    import psycopg
    import os
    
    # Get schema name from config - REQUIRED, no fallback (23 DEC 2025)
    try:
        from config import get_config
        config = get_config()
        schema_name = config.app_schema
    except Exception as e:
        print(f"ERROR: Could not load configuration: {e}")
        print("\nRequired environment variables for schema names:")
        print("  - APP_SCHEMA (e.g., 'app')")
        print("  - POSTGIS_SCHEMA (e.g., 'geo')")
        print("  - PGSTAC_SCHEMA (e.g., 'pgstac')")
        print("  - H3_SCHEMA (e.g., 'h3')")
        sys.exit(1)
    
    # Create generator instance
    generator = PydanticToSQL(schema_name=schema_name)
    
    # Try to get a connection for proper SQL rendering (optional)
    connection = None
    if '--with-connection' in sys.argv:
        # Try to connect for proper SQL rendering
        connection_attempts = [
            os.environ.get("DATABASE_URL"),
            "host=localhost port=5432 dbname=postgres user=postgres",
        ]
        
        for conn_str in connection_attempts:
            if not conn_str:
                continue
            try:
                connection = psycopg.connect(conn_str, connect_timeout=2)
                # Connection successful - will be logged by inspect() method
                break
            except Exception as e:
                print(f"  Note: Could not connect with {conn_str[:30]}...: {type(e).__name__}")
                continue
    
    # Use the inspect method for formatted output
    categories = generator.inspect(connection=connection, verbose=True)
    
    # Clean up connection if we created one
    if connection:
        connection.close()
    
    return categories


if __name__ == "__main__":
    main()
