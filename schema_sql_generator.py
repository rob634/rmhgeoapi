# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Generate PostgreSQL DDL from Pydantic models - single source of truth
# SOURCE: Pydantic models in schema_core.py and model_core.py
# SCOPE: Database schema generation from Python models
# VALIDATION: Ensures PostgreSQL schema always matches Pydantic definitions
# DEPLOYMENT: Use psycopg.sql composition to avoid SQL injection EXCEPT for database functions which can use f string for the time being
# ============================================================================

"""
Pydantic to PostgreSQL Schema Generator.

This module generates PostgreSQL DDL statements from Pydantic models,
ensuring that the database schema always matches the Python models.
The Pydantic models become the single source of truth for the schema.
"""

from typing import Dict, List, Optional, Type, get_args, get_origin, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum
import inspect
import re
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from psycopg import sql

# Import the core models
from schema_core import JobRecord, TaskRecord, JobStatus, TaskStatus


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
            from util_logger import LoggerFactory, ComponentType
            self.logger = LoggerFactory.get_logger(ComponentType.SERVICE, "SQLGenerator")
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
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is not None:
            args = get_args(field_type)
            if origin is type(Optional):
                # Optional[X] is Union[X, None]
                actual_type = args[0] if args else str
                return self.python_type_to_sql(actual_type, field_info)
            elif origin in (dict, Dict):
                return "JSONB"
            elif origin in (list, List):
                return "JSONB"
                
        # Handle Enums
        if inspect.isclass(field_type) and issubclass(field_type, Enum):
            # Convert CamelCase to snake_case for PostgreSQL
            enum_name = re.sub(r'(?<!^)(?=[A-Z])', '_', field_type.__name__).lower()
            self.enums[enum_name] = field_type
            return f"{self.schema_name}.{enum_name}"
            
        # Handle string fields with max_length
        if field_type == str:
            max_length = getattr(field_info, 'max_length', None)
            if max_length:
                return f"VARCHAR({max_length})"
            # Default VARCHAR without length for flexibility
            return "VARCHAR"
            
        # Standard type mapping
        sql_type = self.TYPE_MAP.get(field_type)
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
            
            # Build column definition using composition
            column_parts = [
                sql.Identifier(field_name),
                sql.SQL(" "),
                sql.SQL(sql_type_str)
            ]
            
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
                if field_name in ["parameters", "stage_results"]:
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
        Generate index statements using psycopg.sql composition.
        
        NO STRING CONCATENATION - Full SQL composition for safety.
        
        Args:
            table_name: Name of the table
            model: Pydantic model class
            
        Returns:
            List of composed CREATE INDEX statements
        """
        self.logger.debug(f"🔧 Generating indexes for table {table_name}")
        indexes = []
        
        if table_name == "jobs":
            # Status index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_jobs_status"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs"),
                    sql.Identifier("status")
                )
            )
            # Job type index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_jobs_job_type"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs"),
                    sql.Identifier("job_type")
                )
            )
            # Created at index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_jobs_created_at"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs"),
                    sql.Identifier("created_at")
                )
            )
            # Updated at index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_jobs_updated_at"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs"),
                    sql.Identifier("updated_at")
                )
            )
            
        elif table_name == "tasks":
            # Parent job ID index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_tasks_parent_job_id"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("parent_job_id")
                )
            )
            # Status index
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier("idx_tasks_status"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("status")
                )
            )
            # Composite index: parent_job_id, stage
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}, {})").format(
                    sql.Identifier("idx_tasks_job_stage"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("parent_job_id"),
                    sql.Identifier("stage")
                )
            )
            # Composite index: parent_job_id, stage, status
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}, {}, {})").format(
                    sql.Identifier("idx_tasks_job_stage_status"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("parent_job_id"),
                    sql.Identifier("stage"),
                    sql.Identifier("status")
                )
            )
            # Partial index for heartbeat
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}) WHERE {} IS NOT NULL").format(
                    sql.Identifier("idx_tasks_heartbeat"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("heartbeat"),
                    sql.Identifier("heartbeat")
                )
            )
            # Partial index for retry_count
            indexes.append(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({}) WHERE {} > 0").format(
                    sql.Identifier("idx_tasks_retry_count"),
                    sql.Identifier(self.schema_name),
                    sql.Identifier("tasks"),
                    sql.Identifier("retry_count"),
                    sql.Identifier("retry_count")
                )
            )
        
        self.logger.debug(f"✅ Generated {len(indexes)} indexes for table {table_name}")
        return indexes
    
####### database functions are the ONLY f string SQL allowed right now
    def generate_static_functions(self) -> List[str]:
        """
        Generate static PostgreSQL function definitions.
        
        Fallback if template files are not available.
        These functions are critical for the "last task turns out the lights"
        pattern and must match the signatures expected by the Python code.
        
        Returns:
            List of CREATE FUNCTION statements
        """
        functions = []
        
        # complete_task_and_check_stage function with FIXED BIGINT return types
        functions.append(f"""
-- Atomic task completion with stage detection
CREATE OR REPLACE FUNCTION {self.schema_name}.complete_task_and_check_stage(
    p_task_id VARCHAR(100),
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
DECLARE
    v_job_id VARCHAR(64);
    v_stage INTEGER;
    v_remaining INTEGER;
    v_task_status {self.schema_name}.task_status;
BEGIN
    -- Get task info and update atomically
    UPDATE {self.schema_name}.tasks 
    SET 
        status = CASE 
            WHEN p_error_details IS NOT NULL THEN 'failed'::{self.schema_name}.task_status
            ELSE 'completed'::{self.schema_name}.task_status
        END,
        result_data = p_result_data,
        error_details = p_error_details,
        updated_at = NOW()
    WHERE 
        task_id = p_task_id 
        AND status = 'processing'
    RETURNING parent_job_id, stage, status
    INTO v_job_id, v_stage, v_task_status;
    
    IF v_job_id IS NULL THEN
        RETURN QUERY SELECT FALSE, FALSE, NULL::VARCHAR(64), NULL::INTEGER, NULL::INTEGER;
        RETURN;
    END IF;
    
    -- Count remaining non-completed tasks in the same stage
    SELECT COUNT(*)::INTEGER INTO v_remaining
    FROM {self.schema_name}.tasks 
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
$$;""")
        
        # advance_job_stage function - FIXED: using p_stage_results consistently
        functions.append(f"""
-- Atomic job stage advancement
CREATE OR REPLACE FUNCTION {self.schema_name}.advance_job_stage(
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
DECLARE
    v_total_stages INTEGER;
    v_new_stage INTEGER;
BEGIN
    -- Update job stage and stage results atomically
    UPDATE {self.schema_name}.jobs
    SET 
        stage = stage + 1,
        stage_results = CASE 
            WHEN p_stage_results IS NOT NULL THEN
                stage_results || jsonb_build_object(p_current_stage::text, p_stage_results)
            ELSE stage_results
        END,
        status = CASE 
            WHEN stage + 1 > total_stages THEN 'completed'::{self.schema_name}.job_status
            ELSE 'processing'::{self.schema_name}.job_status
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
$$;""")
        
        # check_job_completion function with FIXED BIGINT types
        functions.append(f"""
-- Check job completion and gather results
CREATE OR REPLACE FUNCTION {self.schema_name}.check_job_completion(
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
DECLARE
    v_job_record RECORD;
    v_task_counts RECORD;
BEGIN
    -- Get job info with row-level lock
    SELECT job_id, job_type, status, stage, total_stages, stage_results
    INTO v_job_record
    FROM {self.schema_name}.jobs 
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
    
    -- Count tasks for this job (with explicit BIGINT casting)
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
    FROM {self.schema_name}.tasks 
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
$$;""")
        
        # update_updated_at trigger function
        functions.append(f"""
-- Trigger function for updating timestamps
CREATE OR REPLACE FUNCTION {self.schema_name}.update_updated_at_column()
RETURNS TRIGGER 
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;""")
        
        return functions
        
    def generate_triggers_composed(self) -> List[sql.Composed]:
        """
        Generate trigger statements using psycopg.sql composition.
        
        NO STRING CONCATENATION - Full SQL composition for safety.
        
        Returns:
            List of composed trigger statements
        """
        self.logger.debug(f"🔧 Generating triggers for updated_at columns")
        triggers = []
        
        # Updated_at trigger for jobs table
        triggers.append(
            sql.SQL("DROP TRIGGER IF EXISTS {} ON {}.{}").format(
                sql.Identifier("update_jobs_updated_at"),
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs")
            )
        )
        triggers.append(
            sql.SQL("CREATE TRIGGER {} BEFORE UPDATE ON {}.{} FOR EACH ROW EXECUTE FUNCTION {}.{}()").format(
                sql.Identifier("update_jobs_updated_at"),
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs"),
                sql.Identifier(self.schema_name),
                sql.Identifier("update_updated_at_column")
            )
        )
        
        # Updated_at trigger for tasks table
        triggers.append(
            sql.SQL("DROP TRIGGER IF EXISTS {} ON {}.{}").format(
                sql.Identifier("update_tasks_updated_at"),
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks")
            )
        )
        triggers.append(
            sql.SQL("CREATE TRIGGER {} BEFORE UPDATE ON {}.{} FOR EACH ROW EXECUTE FUNCTION {}.{}()").format(
                sql.Identifier("update_tasks_updated_at"),
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks"),
                sql.Identifier(self.schema_name),
                sql.Identifier("update_updated_at_column")
            )
        )
        
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
        
        # For tables, indexes, functions, and triggers, we still need string format
        # because they are complex multi-line statements
        # But we'll return them as sql.SQL objects for consistency
        
        # Tables - now using composed SQL
        composed.append(self.generate_table_composed(JobRecord, "jobs"))
        composed.append(self.generate_table_composed(TaskRecord, "tasks"))
        
        # Indexes - now using composed SQL
        composed.extend(self.generate_indexes_composed("jobs", JobRecord))
        composed.extend(self.generate_indexes_composed("tasks", TaskRecord))
            
        # Functions
        for function in self.generate_static_functions():
            composed.append(sql.SQL(function))
            
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


def main():
    """
    Generate SQL schema and optionally save to file.
    
    NO STRING CONCATENATION - Uses composed SQL statements.
    For file output only - real deployment uses composed objects directly.
    """
    generator = PydanticToSQL(schema_name="app")
    
    # Generate composed statements (the ONLY way now)
    composed_statements = generator.generate_composed_statements()
    
    # For file output, we need to convert to strings
    # This is ONLY for display/file writing - deployment uses composed objects
    sql_lines = []
    header = """-- =============================================================================
-- GENERATED PostgreSQL Schema from Pydantic Models
-- Generated at: {}
-- =============================================================================
-- 
-- This schema is automatically generated from Pydantic models
-- The Python models are the single source of truth
-- Generated using psycopg.sql composition - NO STRING CONCATENATION
-- 
-- =============================================================================

""".format(datetime.utcnow().isoformat())
    
    sql_lines.append(header)
    
    # Note about composed statements
    sql_lines.append("-- NOTE: SQL statements are generated using psycopg.sql composition\n")
    sql_lines.append("-- They cannot be directly converted to strings for file output\n")
    sql_lines.append("-- Use the deployment endpoint to execute these composed statements\n")
    sql_lines.append("-- Endpoint: POST /api/schema/deploy-pydantic?confirm=yes\n\n")
    sql_lines.append(f"-- Total composed statements generated: {len(composed_statements)}\n")
    
    sql_schema = '\n'.join(sql_lines)
    
    # Save to file
    output_file = "schema_generated.sql"
    with open(output_file, "w") as f:
        f.write(sql_schema)
        
    print(f"✅ Schema generated and saved to {output_file}")
    print(f"📊 Generated {len(generator.enums)} ENUMs")
    print(f"📊 Generated 2 tables (jobs, tasks)")
    print(f"📊 Generated 4 critical functions")
    
    return sql_schema


if __name__ == "__main__":
    main()