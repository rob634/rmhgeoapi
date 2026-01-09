# ============================================================================
# PYDANTIC TO POSTGRESQL SCHEMA GENERATOR
# ============================================================================
# STATUS: Core - DDL generation from Pydantic models
# PURPOSE: Generate PostgreSQL CREATE statements using psycopg.sql composition
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Pydantic to PostgreSQL Schema Generator.

Generates PostgreSQL DDL statements from Pydantic models,
ensuring database schema always matches Python models.
Pydantic models are the single source of truth for schema.

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
from ..models.promoted import PromotedDataset, SystemRole, Classification  # Promoted datasets (23 DEC 2025)
from ..models.system_snapshot import SystemSnapshotRecord, SnapshotTriggerType  # System snapshots (04 JAN 2026)
from ..models.external_refs import DatasetRefRecord  # External references (09 JAN 2026 - F7.8)


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

        elif table_name == "tasks":
            indexes.append(IndexBuilder.btree(s, "tasks", "parent_job_id", name="idx_tasks_parent_job_id"))
            indexes.append(IndexBuilder.btree(s, "tasks", "status", name="idx_tasks_status"))
            indexes.append(IndexBuilder.btree(s, "tasks", ["parent_job_id", "stage"], name="idx_tasks_job_stage"))
            indexes.append(IndexBuilder.btree(s, "tasks", ["parent_job_id", "stage", "status"], name="idx_tasks_job_stage_status"))
            indexes.append(IndexBuilder.btree(s, "tasks", "heartbeat", name="idx_tasks_heartbeat",
                                              partial_where="heartbeat IS NOT NULL"))
            indexes.append(IndexBuilder.btree(s, "tasks", "retry_count", name="idx_tasks_retry_count",
                                              partial_where="retry_count > 0"))
            indexes.append(IndexBuilder.btree(s, "tasks", "target_queue", name="idx_tasks_target_queue"))
            indexes.append(IndexBuilder.btree(s, "tasks", "executed_by_app", name="idx_tasks_executed_by_app"))

        elif table_name == "api_requests":
            # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
            indexes.append(IndexBuilder.btree(s, "api_requests", "dataset_id", name="idx_api_requests_dataset_id"))
            indexes.append(IndexBuilder.btree(s, "api_requests", "created_at", name="idx_api_requests_created_at"))

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
        composed.extend(self.generate_enum("classification", Classification))
        composed.extend(self.generate_enum("snapshot_trigger_type", SnapshotTriggerType))  # System snapshots (04 JAN 2026)

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

        # Functions - already sql.Composed objects
        composed.extend(self.generate_static_functions())
            
        # Triggers - now using composed SQL
        composed.extend(self.generate_triggers_composed())
        
        self.logger.info(f"✅ SQL composition complete: {len(composed)} statements ready")
        self.logger.info(f"   - Schema & search_path: 2")
        self.logger.info(f"   - ENUMs: 2")  
        self.logger.info(f"   - Tables: 2")
        self.logger.info(f"   - Indexes: {len(self.generate_indexes_composed('jobs', JobRecord)) + len(self.generate_indexes_composed('tasks', TaskRecord))}")
        self.logger.info(f"   - Functions: {len(self.generate_static_functions())}")
        self.logger.info(f"   - Triggers: {len(self.generate_triggers_composed())}")
        
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
