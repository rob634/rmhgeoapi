# ============================================================================
# DDL UTILITIES - SHARED SQL GENERATION PATTERNS
# ============================================================================
# STATUS: Core - DRY utilities for SQL DDL generation
# PURPOSE: Index, trigger, comment, and constraint builders using psycopg.sql
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
DDL Utilities - Shared SQL Generation Patterns.

Consolidates common DDL patterns used across:
- core/schema/sql_generator.py (app schema)
- core/schema/geo_table_builder.py (geo schema)
- infrastructure/h3_schema.py (h3 schema)

All methods return psycopg.sql.Composed objects for safe execution.
No string concatenation - full SQL composition for injection safety.

Usage:
    from core.schema.ddl_utils import IndexBuilder, TriggerBuilder, TYPE_MAP

    # Create a B-tree index
    idx = IndexBuilder.btree('app', 'jobs', ['status'])
    cursor.execute(idx)

    # Create updated_at trigger
    stmts = TriggerBuilder.updated_at('geo', 'countries')
    for stmt in stmts:
        cursor.execute(stmt)
"""

from typing import List, Optional, Union, Sequence
from psycopg import sql


# ============================================================================
# UNIFIED TYPE MAPPING
# ============================================================================

# Python/Pandas types to PostgreSQL types
# Merged from sql_generator.py and geo_table_builder.py
TYPE_MAP = {
    # Python native types (from sql_generator.py)
    str: "VARCHAR",
    int: "INTEGER",
    float: "DOUBLE PRECISION",
    bool: "BOOLEAN",
    dict: "JSONB",
    list: "JSONB",

    # String representations (from geo_table_builder.py pandas dtypes)
    'str': 'VARCHAR',
    'string': 'TEXT',
    'object': 'TEXT',
    'int': 'INTEGER',
    'int16': 'SMALLINT',
    'int32': 'INTEGER',
    'int64': 'BIGINT',
    'float': 'DOUBLE PRECISION',
    'float32': 'REAL',
    'float64': 'DOUBLE PRECISION',
    'bool': 'BOOLEAN',
    'boolean': 'BOOLEAN',
    'datetime': 'TIMESTAMP WITH TIME ZONE',
    'datetime64': 'TIMESTAMP WITH TIME ZONE',
    'datetime64[ns]': 'TIMESTAMP WITH TIME ZONE',
    'date': 'DATE',
    'timedelta': 'INTERVAL',
    'timedelta64': 'INTERVAL',

    # Explicit PostgreSQL types (pass-through)
    'TEXT': 'TEXT',
    'VARCHAR': 'VARCHAR',
    'INTEGER': 'INTEGER',
    'BIGINT': 'BIGINT',
    'SMALLINT': 'SMALLINT',
    'REAL': 'REAL',
    'DOUBLE PRECISION': 'DOUBLE PRECISION',
    'BOOLEAN': 'BOOLEAN',
    'JSONB': 'JSONB',
    'JSON': 'JSON',
    'TIMESTAMP': 'TIMESTAMP',
    'TIMESTAMPTZ': 'TIMESTAMP WITH TIME ZONE',
    'DATE': 'DATE',
    'INTERVAL': 'INTERVAL',
    'NUMERIC': 'NUMERIC',
    'DECIMAL': 'DECIMAL',
    'SERIAL': 'SERIAL',
    'BIGSERIAL': 'BIGSERIAL',
}


def get_postgres_type(python_type) -> str:
    """
    Map Python/Pandas type to PostgreSQL type.

    Args:
        python_type: Python type, dtype object, or string representation

    Returns:
        PostgreSQL type string

    Example:
        get_postgres_type(int)  # 'INTEGER'
        get_postgres_type('float64')  # 'DOUBLE PRECISION'
        get_postgres_type('object')  # 'TEXT'
    """
    # Handle type objects directly
    if python_type in TYPE_MAP:
        return TYPE_MAP[python_type]

    # Handle string representations (case-insensitive for common types)
    type_str = str(python_type).lower()

    # Check for partial matches (e.g., 'int64' in 'Int64')
    for key, pg_type in TYPE_MAP.items():
        if isinstance(key, str) and key.lower() in type_str:
            return pg_type

    # Default to TEXT for unknown types
    return 'TEXT'


# ============================================================================
# INDEX BUILDER
# ============================================================================

class IndexBuilder:
    """
    Builder for PostgreSQL index DDL statements.

    All methods are static and return sql.Composed objects.
    Supports B-tree, GiST, GIN, and partial indexes.

    Example:
        # Simple B-tree index
        idx = IndexBuilder.btree('app', 'jobs', 'status')

        # Composite index
        idx = IndexBuilder.btree('app', 'tasks', ['parent_job_id', 'stage'])

        # Partial index
        idx = IndexBuilder.btree('app', 'tasks', 'last_pulse',
                                 partial_where='last_pulse IS NOT NULL')

        # Spatial index
        idx = IndexBuilder.gist('geo', 'countries', 'geom')

        # Unique index
        idx = IndexBuilder.unique('app', 'etl_source_files',
                                  ['etl_type', 'source_blob_path'])
    """

    @staticmethod
    def _normalize_columns(columns: Union[str, Sequence[str]]) -> List[str]:
        """Convert single column or sequence to list."""
        if isinstance(columns, str):
            return [columns]
        return list(columns)

    @staticmethod
    def _generate_index_name(
        table: str,
        columns: List[str],
        prefix: str = 'idx',
        suffix: str = ''
    ) -> str:
        """Generate conventional index name."""
        col_part = '_'.join(columns)
        name = f"{prefix}_{table}_{col_part}"
        if suffix:
            name = f"{name}_{suffix}"
        return name

    @staticmethod
    def btree(
        schema: str,
        table: str,
        columns: Union[str, Sequence[str]],
        name: Optional[str] = None,
        descending: bool = False,
        partial_where: Optional[str] = None
    ) -> sql.Composed:
        """
        Create B-tree index (default PostgreSQL index type).

        Args:
            schema: Schema name
            table: Table name
            columns: Column name(s) to index
            name: Optional custom index name (auto-generated if None)
            descending: If True, create DESC index
            partial_where: Optional WHERE clause for partial index

        Returns:
            sql.Composed CREATE INDEX statement
        """
        cols = IndexBuilder._normalize_columns(columns)
        idx_name = name or IndexBuilder._generate_index_name(
            table, cols, suffix='desc' if descending else ''
        )

        # Build column list with optional DESC
        if descending:
            col_parts = [
                sql.SQL("{} DESC").format(sql.Identifier(c))
                for c in cols
            ]
        else:
            col_parts = [sql.Identifier(c) for c in cols]

        col_sql = sql.SQL(", ").join(col_parts)

        # Base statement
        stmt = sql.SQL("CREATE INDEX IF NOT EXISTS {name} ON {schema}.{table} ({columns})").format(
            name=sql.Identifier(idx_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
            columns=col_sql
        )

        # Add partial index WHERE clause if provided
        if partial_where:
            stmt = sql.SQL("{} WHERE {}").format(stmt, sql.SQL(partial_where))

        return stmt

    @staticmethod
    def gist(
        schema: str,
        table: str,
        column: str,
        name: Optional[str] = None,
        partial_where: Optional[str] = None
    ) -> sql.Composed:
        """
        Create GiST index (for geometry, range types, full-text search).

        Args:
            schema: Schema name
            table: Table name
            column: Column to index (typically geometry)
            name: Optional custom index name
            partial_where: Optional WHERE clause for partial index

        Returns:
            sql.Composed CREATE INDEX statement
        """
        idx_name = name or IndexBuilder._generate_index_name(table, [column])

        stmt = sql.SQL(
            "CREATE INDEX IF NOT EXISTS {name} ON {schema}.{table} USING GIST ({column})"
        ).format(
            name=sql.Identifier(idx_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
            column=sql.Identifier(column)
        )

        if partial_where:
            stmt = sql.SQL("{} WHERE {}").format(stmt, sql.SQL(partial_where))

        return stmt

    @staticmethod
    def gin(
        schema: str,
        table: str,
        column: str,
        name: Optional[str] = None,
        partial_where: Optional[str] = None
    ) -> sql.Composed:
        """
        Create GIN index (for JSONB, arrays, full-text search).

        Args:
            schema: Schema name
            table: Table name
            column: Column to index (typically JSONB)
            name: Optional custom index name
            partial_where: Optional WHERE clause for partial index

        Returns:
            sql.Composed CREATE INDEX statement
        """
        idx_name = name or IndexBuilder._generate_index_name(table, [column])

        stmt = sql.SQL(
            "CREATE INDEX IF NOT EXISTS {name} ON {schema}.{table} USING GIN ({column})"
        ).format(
            name=sql.Identifier(idx_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
            column=sql.Identifier(column)
        )

        if partial_where:
            stmt = sql.SQL("{} WHERE {}").format(stmt, sql.SQL(partial_where))

        return stmt

    @staticmethod
    def unique(
        schema: str,
        table: str,
        columns: Union[str, Sequence[str]],
        name: Optional[str] = None,
        partial_where: Optional[str] = None
    ) -> sql.Composed:
        """
        Create unique index.

        Args:
            schema: Schema name
            table: Table name
            columns: Column name(s) for unique constraint
            name: Optional custom index name
            partial_where: Optional WHERE clause for partial unique index

        Returns:
            sql.Composed CREATE UNIQUE INDEX statement
        """
        cols = IndexBuilder._normalize_columns(columns)
        idx_name = name or IndexBuilder._generate_index_name(table, cols, prefix='idx_unique')

        col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in cols)

        stmt = sql.SQL(
            "CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {schema}.{table} ({columns})"
        ).format(
            name=sql.Identifier(idx_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
            columns=col_sql
        )

        if partial_where:
            stmt = sql.SQL("{} WHERE {}").format(stmt, sql.SQL(partial_where))

        return stmt


# ============================================================================
# TRIGGER BUILDER
# ============================================================================

class TriggerBuilder:
    """
    Builder for PostgreSQL trigger DDL statements.

    All methods are static and return sql.Composed objects or lists.

    Example:
        # Create updated_at trigger (returns list of 3 statements)
        stmts = TriggerBuilder.updated_at('geo', 'countries')
        for stmt in stmts:
            cursor.execute(stmt)
    """

    @staticmethod
    def updated_at_function(schema: str) -> sql.Composed:
        """
        Create the update_updated_at_column() trigger function.

        This function sets NEW.updated_at = NOW() on every UPDATE.
        Only needs to be created once per schema.

        Args:
            schema: Schema name

        Returns:
            sql.Composed CREATE FUNCTION statement
        """
        return sql.SQL("""
            CREATE OR REPLACE FUNCTION {schema}.update_updated_at_column()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$
        """).format(schema=sql.Identifier(schema))

    @staticmethod
    def updated_at_trigger(
        schema: str,
        table: str,
        trigger_name: Optional[str] = None
    ) -> List[sql.Composed]:
        """
        Create trigger that calls update_updated_at_column() on UPDATE.

        Returns DROP + CREATE for idempotency.

        Args:
            schema: Schema name
            table: Table name
            trigger_name: Optional custom trigger name

        Returns:
            List of [DROP TRIGGER, CREATE TRIGGER] statements
        """
        trig_name = trigger_name or f"trg_{table}_updated_at"

        drop_stmt = sql.SQL("DROP TRIGGER IF EXISTS {name} ON {schema}.{table}").format(
            name=sql.Identifier(trig_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table)
        )

        create_stmt = sql.SQL("""
            CREATE TRIGGER {name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {schema}.update_updated_at_column()
        """).format(
            name=sql.Identifier(trig_name),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table)
        )

        return [drop_stmt, create_stmt]

    @staticmethod
    def updated_at(schema: str, table: str) -> List[sql.Composed]:
        """
        Create complete updated_at trigger setup for a table.

        Combines function creation + trigger creation for convenience.
        Safe to call multiple times (uses IF NOT EXISTS / OR REPLACE).

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of [CREATE FUNCTION, DROP TRIGGER, CREATE TRIGGER] statements
        """
        stmts = [TriggerBuilder.updated_at_function(schema)]
        stmts.extend(TriggerBuilder.updated_at_trigger(schema, table))
        return stmts


# ============================================================================
# COMMENT BUILDER
# ============================================================================

class CommentBuilder:
    """
    Builder for PostgreSQL COMMENT statements.

    All methods are static and return sql.Composed objects.

    Example:
        stmt = CommentBuilder.table('geo', 'countries', 'Country boundaries from Natural Earth')
        cursor.execute(stmt)
    """

    @staticmethod
    def schema(schema: str, comment: str) -> sql.Composed:
        """
        Add comment to schema.

        Args:
            schema: Schema name
            comment: Comment text

        Returns:
            sql.Composed COMMENT ON SCHEMA statement
        """
        return sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
            sql.Identifier(schema),
            sql.Literal(comment)
        )

    @staticmethod
    def table(schema: str, table: str, comment: str) -> sql.Composed:
        """
        Add comment to table.

        Args:
            schema: Schema name
            table: Table name
            comment: Comment text

        Returns:
            sql.Composed COMMENT ON TABLE statement
        """
        return sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.Literal(comment)
        )

    @staticmethod
    def column(schema: str, table: str, column: str, comment: str) -> sql.Composed:
        """
        Add comment to column.

        Args:
            schema: Schema name
            table: Table name
            column: Column name
            comment: Comment text

        Returns:
            sql.Composed COMMENT ON COLUMN statement
        """
        return sql.SQL("COMMENT ON COLUMN {}.{}.{} IS {}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.Identifier(column),
            sql.Literal(comment)
        )

    @staticmethod
    def index(schema: str, index_name: str, comment: str) -> sql.Composed:
        """
        Add comment to index.

        Args:
            schema: Schema name
            index_name: Index name
            comment: Comment text

        Returns:
            sql.Composed COMMENT ON INDEX statement
        """
        return sql.SQL("COMMENT ON INDEX {}.{} IS {}").format(
            sql.Identifier(schema),
            sql.Identifier(index_name),
            sql.Literal(comment)
        )


# ============================================================================
# SCHEMA UTILITIES
# ============================================================================

class SchemaUtils:
    """
    Utility methods for schema-level DDL operations.

    Example:
        stmt = SchemaUtils.create_schema('geo', 'Geographic data schema')
        cursor.execute(stmt)
    """

    @staticmethod
    def create_schema(schema: str, comment: Optional[str] = None) -> List[sql.Composed]:
        """
        Create schema with optional comment.

        Args:
            schema: Schema name
            comment: Optional schema comment

        Returns:
            List of [CREATE SCHEMA] or [CREATE SCHEMA, COMMENT] statements
        """
        stmts = [
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema)
            )
        ]

        if comment:
            stmts.append(CommentBuilder.schema(schema, comment))

        return stmts

    @staticmethod
    def set_search_path(schema: str, include_public: bool = True) -> sql.Composed:
        """
        Set search_path to include schema.

        Args:
            schema: Schema name
            include_public: If True, append 'public' to search path

        Returns:
            sql.Composed SET search_path statement
        """
        if include_public:
            return sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(schema)
            )
        else:
            return sql.SQL("SET search_path TO {}").format(
                sql.Identifier(schema)
            )

    @staticmethod
    def grant_all(schema: str, role: str) -> List[sql.Composed]:
        """
        Grant all privileges on schema to role.

        Args:
            schema: Schema name
            role: Role/user name

        Returns:
            List of GRANT statements for schema, tables, sequences
        """
        schema_ident = sql.Identifier(schema)
        role_ident = sql.Identifier(role)

        return [
            sql.SQL("GRANT ALL PRIVILEGES ON SCHEMA {} TO {}").format(
                schema_ident, role_ident
            ),
            sql.SQL("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO {}").format(
                schema_ident, role_ident
            ),
            sql.SQL("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                schema_ident, role_ident
            ),
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT ALL PRIVILEGES ON TABLES TO {}").format(
                schema_ident, role_ident
            ),
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT ALL PRIVILEGES ON SEQUENCES TO {}").format(
                schema_ident, role_ident
            ),
        ]


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Type mapping
    'TYPE_MAP',
    'get_postgres_type',

    # Builders
    'IndexBuilder',
    'TriggerBuilder',
    'CommentBuilder',
    'SchemaUtils',
]
