# ============================================================================
# SCHEMA ANALYZER - DATABASE INTROSPECTION AND DRIFT DETECTION
# ============================================================================
# STATUS: Infrastructure - Schema introspection and comparison
# PURPOSE: Analyze existing database schema, detect drift, and identify
#          missing tables/columns/indexes for smart migrations
# CREATED: 21 JAN 2026
# ============================================================================
"""
SchemaAnalyzer - Database Introspection and Drift Detection.

Provides comprehensive analysis of existing database schemas compared to
expected schema definitions. Enables smart migrations by:

1. Introspecting current database state (tables, columns, indexes, constraints)
2. Comparing against expected schema (from Pydantic models, DDL definitions)
3. Detecting drift (missing tables, columns, indexes, type mismatches)
4. Generating migration reports for future migrations

Usage:
    from infrastructure.schema_analyzer import SchemaAnalyzer

    analyzer = SchemaAnalyzer()

    # Get full analysis of a schema
    report = analyzer.analyze_schema('app')

    # Compare against expected (from Pydantic models)
    drift = analyzer.detect_drift('app')

    # Get migration SQL for missing objects
    migration_sql = analyzer.generate_migration_sql('app')

Exports:
    SchemaAnalyzer: Main analyzer class
    SchemaReport: Dataclass for analysis results
    DriftReport: Dataclass for drift detection results
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from psycopg import sql
import traceback

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "SchemaAnalyzer")


# ============================================================================
# DATA CLASSES
# ============================================================================

class DriftType(Enum):
    """Types of schema drift that can be detected."""
    MISSING_TABLE = "missing_table"
    MISSING_COLUMN = "missing_column"
    TYPE_MISMATCH = "type_mismatch"
    MISSING_INDEX = "missing_index"
    MISSING_CONSTRAINT = "missing_constraint"
    EXTRA_TABLE = "extra_table"  # Table exists in DB but not in expected schema
    EXTRA_COLUMN = "extra_column"


@dataclass
class ColumnInfo:
    """Information about a database column."""
    name: str
    data_type: str
    is_nullable: bool
    column_default: Optional[str]
    ordinal_position: int
    character_maximum_length: Optional[int] = None
    numeric_precision: Optional[int] = None


@dataclass
class IndexInfo:
    """Information about a database index."""
    name: str
    table_name: str
    columns: List[str]
    is_unique: bool
    is_primary: bool
    index_type: str  # btree, gist, gin, etc.
    definition: str


@dataclass
class TableInfo:
    """Information about a database table."""
    schema_name: str
    table_name: str
    columns: Dict[str, ColumnInfo]
    indexes: Dict[str, IndexInfo]
    row_count: int
    table_size_bytes: int
    created_at: Optional[datetime] = None
    last_vacuum: Optional[datetime] = None
    last_analyze: Optional[datetime] = None


@dataclass
class DriftItem:
    """A single instance of schema drift."""
    drift_type: DriftType
    schema_name: str
    table_name: str
    object_name: Optional[str]  # Column name, index name, etc.
    expected: Optional[str]  # Expected definition
    actual: Optional[str]  # Actual definition (None if missing)
    migration_sql: Optional[str]  # SQL to fix the drift
    severity: str = "warning"  # info, warning, error


@dataclass
class SchemaReport:
    """Complete analysis of a database schema."""
    schema_name: str
    timestamp: str
    exists: bool
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    total_tables: int = 0
    total_columns: int = 0
    total_indexes: int = 0
    total_rows: int = 0
    total_size_bytes: int = 0
    oldest_table: Optional[str] = None
    newest_table: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_name": self.schema_name,
            "timestamp": self.timestamp,
            "exists": self.exists,
            "summary": {
                "total_tables": self.total_tables,
                "total_columns": self.total_columns,
                "total_indexes": self.total_indexes,
                "total_rows": self.total_rows,
                "total_size_mb": round(self.total_size_bytes / 1024 / 1024, 2),
                "oldest_table": self.oldest_table,
                "newest_table": self.newest_table,
            },
            "tables": {
                name: {
                    "columns": len(t.columns),
                    "indexes": len(t.indexes),
                    "row_count": t.row_count,
                    "size_mb": round(t.table_size_bytes / 1024 / 1024, 2),
                    "last_vacuum": t.last_vacuum.isoformat() if t.last_vacuum else None,
                    "last_analyze": t.last_analyze.isoformat() if t.last_analyze else None,
                }
                for name, t in self.tables.items()
            },
            "error": self.error
        }


@dataclass
class DriftReport:
    """Report of schema drift between expected and actual."""
    schema_name: str
    timestamp: str
    has_drift: bool
    drift_items: List[DriftItem] = field(default_factory=list)
    missing_tables: List[str] = field(default_factory=list)
    missing_columns: Dict[str, List[str]] = field(default_factory=dict)
    missing_indexes: List[str] = field(default_factory=list)
    type_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    extra_tables: List[str] = field(default_factory=list)
    migration_statements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_name": self.schema_name,
            "timestamp": self.timestamp,
            "has_drift": self.has_drift,
            "summary": {
                "missing_tables": len(self.missing_tables),
                "missing_columns": sum(len(cols) for cols in self.missing_columns.values()),
                "missing_indexes": len(self.missing_indexes),
                "type_mismatches": len(self.type_mismatches),
                "extra_tables": len(self.extra_tables),
                "total_drift_items": len(self.drift_items),
            },
            "drift_items": [
                {
                    "type": d.drift_type.value,
                    "table": d.table_name,
                    "object": d.object_name,
                    "expected": d.expected,
                    "actual": d.actual,
                    "severity": d.severity,
                }
                for d in self.drift_items
            ],
            "missing_tables": self.missing_tables,
            "missing_columns": self.missing_columns,
            "missing_indexes": self.missing_indexes,
            "type_mismatches": self.type_mismatches,
            "extra_tables": self.extra_tables,
            "migration_statement_count": len(self.migration_statements),
        }


# ============================================================================
# EXPECTED SCHEMA DEFINITIONS
# ============================================================================

class ExpectedSchemaRegistry:
    """
    Registry of expected schema definitions.

    Provides expected table/column/index definitions for drift detection.
    Sources:
    - App schema: Derived from Pydantic models via PydanticToSQL
    - Geo schema: Standard metadata columns from GeoTableBuilder
    - H3 schema: From H3SchemaDeployer table definitions
    """

    @staticmethod
    def get_expected_app_tables() -> Dict[str, Dict[str, str]]:
        """
        Get expected table definitions for app schema.

        Returns dict of {table_name: {column_name: expected_type}}
        """
        # Core app tables with their required columns
        return {
            "jobs": {
                "job_id": "VARCHAR",
                "job_type": "VARCHAR",
                "status": "job_status",  # enum
                "parameters": "JSONB",
                "stage": "INTEGER",
                "total_stages": "INTEGER",
                "stage_results": "JSONB",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
                "error_details": "TEXT",
            },
            "tasks": {
                "task_id": "VARCHAR",
                "parent_job_id": "VARCHAR",
                "task_type": "VARCHAR",
                "status": "task_status",  # enum
                "stage": "INTEGER",
                "task_index": "INTEGER",
                "parameters": "JSONB",
                "result_data": "JSONB",
                "error_details": "TEXT",
                "retry_count": "INTEGER",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
                "target_queue": "VARCHAR",
                "executed_by_app": "VARCHAR",
                "last_pulse": "TIMESTAMP",
                "checkpoint_phase": "INTEGER",
                "checkpoint_data": "JSONB",
            },
            "api_requests": {
                "request_id": "VARCHAR",
                "dataset_id": "VARCHAR",
                "data_type": "data_type",  # enum
                "data_format": "VARCHAR",
                "source_path": "VARCHAR",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
                "retry_count": "INTEGER",
            },
            "janitor_runs": {
                "run_id": "VARCHAR",
                "run_type": "janitor_run_type",  # enum
                "status": "janitor_run_status",  # enum
                "started_at": "TIMESTAMP",
                "completed_at": "TIMESTAMP",
                "records_processed": "INTEGER",
                "records_deleted": "INTEGER",
                "error_details": "TEXT",
            },
            "etl_source_files": {
                "id": "SERIAL",
                "etl_type": "VARCHAR",
                "source_blob_path": "VARCHAR",
                "phase1_group_key": "VARCHAR",
                "phase2_group_key": "VARCHAR",
                "phase1_completed_at": "TIMESTAMP",
                "phase2_completed_at": "TIMESTAMP",
                "source_metadata": "JSONB",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
            },
            "unpublish_jobs": {
                "unpublish_id": "VARCHAR",
                "unpublish_type": "unpublish_type",  # enum
                "stac_item_id": "VARCHAR",
                "collection_id": "VARCHAR",
                "status": "unpublish_status",  # enum
                "created_at": "TIMESTAMP",
                "completed_at": "TIMESTAMP",
            },
            "curated_datasets": {
                "dataset_id": "VARCHAR",
                "display_name": "VARCHAR",
                "target_table_name": "VARCHAR",
                "source_type": "curated_source_type",  # enum
                "enabled": "BOOLEAN",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
            },
            "curated_update_log": {
                "log_id": "VARCHAR",
                "dataset_id": "VARCHAR",
                "update_type": "curated_update_type",  # enum
                "status": "curated_update_status",  # enum
                "job_id": "VARCHAR",
                "started_at": "TIMESTAMP",
                "completed_at": "TIMESTAMP",
            },
            "promoted_datasets": {
                "promoted_id": "VARCHAR",
                "stac_collection_id": "VARCHAR",
                "stac_item_id": "VARCHAR",
                "display_name": "VARCHAR",
                "description": "TEXT",
                "classification": "classification",  # enum
                "system_role": "system_role",  # enum
                "in_gallery": "BOOLEAN",
                "gallery_order": "INTEGER",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
            },
            "system_snapshots": {
                "snapshot_id": "VARCHAR",
                "trigger_type": "snapshot_trigger_type",  # enum
                "captured_at": "TIMESTAMP",
                "config_hash": "VARCHAR",
                "instance_id": "VARCHAR",
                "has_drift": "BOOLEAN",
            },
            "dataset_refs": {
                "dataset_id": "VARCHAR",
                "data_type": "data_type",  # enum
                "ddh_dataset_id": "VARCHAR",
                "ddh_resource_id": "INTEGER",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
            },
            "cog_metadata": {
                "cog_id": "VARCHAR",
                "container": "VARCHAR",
                "blob_path": "VARCHAR",
                "stac_collection_id": "VARCHAR",
                "stac_item_id": "VARCHAR",
                "created_at": "TIMESTAMP",
            },
            "artifacts": {
                "artifact_id": "UUID",
                "client_type": "VARCHAR",
                "client_refs": "JSONB",
                "stac_collection_id": "VARCHAR",
                "stac_item_id": "VARCHAR",
                "status": "artifact_status",  # enum
                "created_at": "TIMESTAMP",
            },
        }

    @staticmethod
    def get_expected_geo_tables() -> Dict[str, Dict[str, str]]:
        """
        Get expected table definitions for geo schema.

        Returns dict of {table_name: {column_name: expected_type}}
        """
        return {
            "table_metadata": {
                "id": "SERIAL",
                "table_name": "VARCHAR",
                "created_at": "TIMESTAMP",
                "updated_at": "TIMESTAMP",
                "source_file": "VARCHAR",
                "source_format": "VARCHAR",
                "original_crs": "VARCHAR",
                "feature_count": "INTEGER",
                "geometry_type": "VARCHAR",
                "bbox": "JSONB",
                "stac_item_id": "VARCHAR",
                "stac_collection_id": "VARCHAR",
                "etl_job_id": "VARCHAR",
                "properties": "JSONB",
            }
        }

    @staticmethod
    def get_expected_h3_tables() -> Dict[str, Dict[str, str]]:
        """
        Get expected table definitions for h3 schema.

        Returns dict of {table_name: {column_name: expected_type}}
        """
        return {
            "cells": {
                "h3_index": "BIGINT",
                "resolution": "SMALLINT",
                "geom": "GEOMETRY",
                "parent_h3_index": "BIGINT",
                "is_land": "BOOLEAN",
                "created_at": "TIMESTAMP",
                "source_job_id": "VARCHAR",
            },
            "cell_admin0": {
                "h3_index": "BIGINT",
                "iso3": "VARCHAR",
                "coverage_pct": "NUMERIC",
                "created_at": "TIMESTAMP",
            },
            "cell_admin1": {
                "h3_index": "BIGINT",
                "admin1_id": "VARCHAR",
                "iso3": "VARCHAR",
                "admin1_name": "VARCHAR",
                "coverage_pct": "NUMERIC",
                "created_at": "TIMESTAMP",
            },
            "dataset_registry": {
                "id": "VARCHAR",
                "display_name": "VARCHAR",
                "theme": "VARCHAR",
                "source_type": "VARCHAR",
                "source_config": "JSONB",
                "created_at": "TIMESTAMP",
            },
            "source_catalog": {
                "id": "VARCHAR",
                "display_name": "VARCHAR",
                "source_type": "VARCHAR",
                "theme": "VARCHAR",
                "created_at": "TIMESTAMP",
            },
            "zonal_stats": {
                "theme": "VARCHAR",
                "h3_index": "BIGINT",
                "dataset_id": "VARCHAR",
                "band": "VARCHAR",
                "stat_type": "VARCHAR",
                "value": "DOUBLE PRECISION",
                "computed_at": "TIMESTAMP",
            },
            "point_stats": {
                "h3_index": "BIGINT",
                "source_id": "VARCHAR",
                "category": "VARCHAR",
                "count": "INTEGER",
                "computed_at": "TIMESTAMP",
            },
            "batch_progress": {
                "id": "SERIAL",
                "job_id": "VARCHAR",
                "batch_id": "VARCHAR",
                "status": "VARCHAR",
                "items_processed": "INTEGER",
                "created_at": "TIMESTAMP",
            },
        }

    @staticmethod
    def get_expected_app_indexes() -> Dict[str, List[str]]:
        """
        Get expected indexes for app schema.

        Returns dict of {table_name: [index_names]}
        """
        return {
            "jobs": [
                "idx_jobs_status",
                "idx_jobs_job_type",
                "idx_jobs_created_at",
                "idx_jobs_updated_at",
            ],
            "tasks": [
                "idx_tasks_parent_job_id",
                "idx_tasks_status",
                "idx_tasks_job_stage",
                "idx_tasks_job_stage_status",
                "idx_tasks_target_queue",
            ],
            "api_requests": [
                "idx_api_requests_dataset_id",
                "idx_api_requests_created_at",
            ],
        }


# ============================================================================
# SCHEMA ANALYZER
# ============================================================================

class SchemaAnalyzer:
    """
    Analyze database schemas for drift detection and migration planning.

    Provides comprehensive introspection of existing database state
    and comparison against expected schema definitions.
    """

    def __init__(self, database_config=None):
        """
        Initialize schema analyzer.

        Args:
            database_config: Optional DatabaseConfig. If None, uses default.
        """
        from infrastructure.postgresql import PostgreSQLRepository

        self.config = get_config()
        self._repo = PostgreSQLRepository(schema_name='public')

        logger.info("🔍 SchemaAnalyzer initialized")

    # ========================================================================
    # SCHEMA INTROSPECTION
    # ========================================================================

    def analyze_schema(self, schema_name: str) -> SchemaReport:
        """
        Perform comprehensive analysis of a database schema.

        Args:
            schema_name: Name of schema to analyze

        Returns:
            SchemaReport with detailed information about all objects
        """
        report = SchemaReport(
            schema_name=schema_name,
            timestamp=datetime.utcnow().isoformat(),
            exists=False
        )

        logger.info(f"📊 Analyzing schema: {schema_name}")

        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check schema exists
                    cur.execute("""
                        SELECT EXISTS(
                            SELECT 1 FROM pg_namespace WHERE nspname = %s
                        ) as exists
                    """, [schema_name])
                    report.exists = cur.fetchone()['exists']

                    if not report.exists:
                        logger.warning(f"⚠️ Schema '{schema_name}' does not exist")
                        return report

                    # Get all tables in schema
                    tables = self._get_tables(cur, schema_name)
                    report.tables = tables
                    report.total_tables = len(tables)

                    # Calculate totals
                    for table_info in tables.values():
                        report.total_columns += len(table_info.columns)
                        report.total_indexes += len(table_info.indexes)
                        report.total_rows += table_info.row_count
                        report.total_size_bytes += table_info.table_size_bytes

                    logger.info(f"✅ Schema analysis complete: {report.total_tables} tables, "
                               f"{report.total_columns} columns, {report.total_indexes} indexes")

        except Exception as e:
            report.error = str(e)
            logger.error(f"❌ Schema analysis failed: {e}")
            logger.error(traceback.format_exc())

        return report

    def _get_tables(self, cur, schema_name: str) -> Dict[str, TableInfo]:
        """Get all tables in a schema with their details."""
        tables = {}

        # Get table list with stats
        cur.execute("""
            SELECT
                t.table_name,
                pg_catalog.pg_total_relation_size(
                    quote_ident(t.table_schema) || '.' || quote_ident(t.table_name)
                ) as total_size,
                (SELECT reltuples::bigint
                 FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = t.table_schema AND c.relname = t.table_name
                ) as row_estimate,
                s.last_vacuum,
                s.last_analyze
            FROM information_schema.tables t
            LEFT JOIN pg_stat_user_tables s
                ON s.schemaname = t.table_schema AND s.relname = t.table_name
            WHERE t.table_schema = %s
                AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """, [schema_name])

        table_rows = cur.fetchall()

        for row in table_rows:
            table_name = row['table_name']

            # Get columns for this table
            columns = self._get_columns(cur, schema_name, table_name)

            # Get indexes for this table
            indexes = self._get_indexes(cur, schema_name, table_name)

            tables[table_name] = TableInfo(
                schema_name=schema_name,
                table_name=table_name,
                columns=columns,
                indexes=indexes,
                row_count=int(row['row_estimate'] or 0),
                table_size_bytes=int(row['total_size'] or 0),
                last_vacuum=row['last_vacuum'],
                last_analyze=row['last_analyze'],
            )

        return tables

    def _get_columns(self, cur, schema_name: str, table_name: str) -> Dict[str, ColumnInfo]:
        """Get all columns for a table."""
        columns = {}

        cur.execute("""
            SELECT
                column_name,
                data_type,
                udt_name,
                is_nullable,
                column_default,
                ordinal_position,
                character_maximum_length,
                numeric_precision
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, [schema_name, table_name])

        for row in cur.fetchall():
            # Normalize data type (use udt_name for custom types like enums)
            data_type = row['data_type']
            if data_type == 'USER-DEFINED':
                data_type = row['udt_name']
            elif data_type == 'ARRAY':
                data_type = row['udt_name']

            columns[row['column_name']] = ColumnInfo(
                name=row['column_name'],
                data_type=data_type.upper(),
                is_nullable=row['is_nullable'] == 'YES',
                column_default=row['column_default'],
                ordinal_position=row['ordinal_position'],
                character_maximum_length=row['character_maximum_length'],
                numeric_precision=row['numeric_precision'],
            )

        return columns

    def _get_indexes(self, cur, schema_name: str, table_name: str) -> Dict[str, IndexInfo]:
        """Get all indexes for a table."""
        indexes = {}

        cur.execute("""
            SELECT
                i.relname as index_name,
                am.amname as index_type,
                ix.indisunique as is_unique,
                ix.indisprimary as is_primary,
                pg_get_indexdef(ix.indexrelid) as definition,
                array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) as columns
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_am am ON am.oid = i.relam
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE n.nspname = %s AND t.relname = %s
            GROUP BY i.relname, am.amname, ix.indisunique, ix.indisprimary, ix.indexrelid
            ORDER BY i.relname
        """, [schema_name, table_name])

        for row in cur.fetchall():
            indexes[row['index_name']] = IndexInfo(
                name=row['index_name'],
                table_name=table_name,
                columns=row['columns'],
                is_unique=row['is_unique'],
                is_primary=row['is_primary'],
                index_type=row['index_type'],
                definition=row['definition'],
            )

        return indexes

    # ========================================================================
    # DRIFT DETECTION
    # ========================================================================

    def detect_drift(self, schema_name: str) -> DriftReport:
        """
        Detect drift between expected and actual schema.

        Args:
            schema_name: Name of schema to check

        Returns:
            DriftReport with all detected differences
        """
        report = DriftReport(
            schema_name=schema_name,
            timestamp=datetime.utcnow().isoformat(),
            has_drift=False
        )

        logger.info(f"🔍 Detecting drift for schema: {schema_name}")

        # Get current state
        current = self.analyze_schema(schema_name)

        if not current.exists:
            report.has_drift = True
            report.drift_items.append(DriftItem(
                drift_type=DriftType.MISSING_TABLE,
                schema_name=schema_name,
                table_name="<schema>",
                object_name=None,
                expected="Schema should exist",
                actual=None,
                migration_sql=f"CREATE SCHEMA IF NOT EXISTS {schema_name}",
                severity="error"
            ))
            return report

        # Get expected schema based on schema name
        if schema_name == self.config.app_schema:
            expected_tables = ExpectedSchemaRegistry.get_expected_app_tables()
            expected_indexes = ExpectedSchemaRegistry.get_expected_app_indexes()
        elif schema_name == self.config.postgis_schema:
            expected_tables = ExpectedSchemaRegistry.get_expected_geo_tables()
            expected_indexes = {}
        elif schema_name == 'h3' or schema_name == getattr(self.config, 'h3_schema', 'h3'):
            expected_tables = ExpectedSchemaRegistry.get_expected_h3_tables()
            expected_indexes = {}
        else:
            logger.warning(f"⚠️ No expected schema defined for '{schema_name}'")
            return report

        # Check for missing tables
        for table_name, expected_columns in expected_tables.items():
            if table_name not in current.tables:
                report.has_drift = True
                report.missing_tables.append(table_name)
                report.drift_items.append(DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    schema_name=schema_name,
                    table_name=table_name,
                    object_name=None,
                    expected=f"Table with {len(expected_columns)} columns",
                    actual=None,
                    migration_sql=None,  # Complex - need full DDL
                    severity="error"
                ))
            else:
                # Check for missing columns
                actual_table = current.tables[table_name]
                actual_columns = {c.lower() for c in actual_table.columns.keys()}
                expected_col_names = {c.lower() for c in expected_columns.keys()}

                missing_cols = expected_col_names - actual_columns
                if missing_cols:
                    report.has_drift = True
                    report.missing_columns[table_name] = list(missing_cols)
                    for col_name in missing_cols:
                        expected_type = expected_columns.get(col_name, 'UNKNOWN')
                        report.drift_items.append(DriftItem(
                            drift_type=DriftType.MISSING_COLUMN,
                            schema_name=schema_name,
                            table_name=table_name,
                            object_name=col_name,
                            expected=expected_type,
                            actual=None,
                            migration_sql=f"ALTER TABLE {schema_name}.{table_name} ADD COLUMN {col_name} {expected_type}",
                            severity="warning"
                        ))

        # Check for extra tables (in DB but not in expected)
        expected_table_names = set(expected_tables.keys())
        actual_table_names = set(current.tables.keys())
        extra_tables = actual_table_names - expected_table_names

        # Don't flag geo tables as "extra" since they're dynamic
        if schema_name != self.config.postgis_schema:
            for table_name in extra_tables:
                # Skip known system tables
                if not table_name.startswith('pg_') and table_name not in ['spatial_ref_sys']:
                    report.extra_tables.append(table_name)
                    report.drift_items.append(DriftItem(
                        drift_type=DriftType.EXTRA_TABLE,
                        schema_name=schema_name,
                        table_name=table_name,
                        object_name=None,
                        expected=None,
                        actual=f"Table exists with {len(current.tables[table_name].columns)} columns",
                        migration_sql=None,
                        severity="info"
                    ))

        # Check for missing indexes
        for table_name, expected_idx_names in expected_indexes.items():
            if table_name in current.tables:
                actual_idx_names = set(current.tables[table_name].indexes.keys())
                missing_idxs = set(expected_idx_names) - actual_idx_names
                if missing_idxs:
                    report.has_drift = True
                    report.missing_indexes.extend(list(missing_idxs))
                    for idx_name in missing_idxs:
                        report.drift_items.append(DriftItem(
                            drift_type=DriftType.MISSING_INDEX,
                            schema_name=schema_name,
                            table_name=table_name,
                            object_name=idx_name,
                            expected=idx_name,
                            actual=None,
                            migration_sql=None,  # Would need to reconstruct
                            severity="warning"
                        ))

        # Generate migration statements
        for item in report.drift_items:
            if item.migration_sql:
                report.migration_statements.append(item.migration_sql)

        logger.info(f"{'⚠️' if report.has_drift else '✅'} Drift detection complete: "
                   f"{len(report.missing_tables)} missing tables, "
                   f"{sum(len(c) for c in report.missing_columns.values())} missing columns, "
                   f"{len(report.missing_indexes)} missing indexes")

        return report

    def detect_all_drift(self) -> Dict[str, DriftReport]:
        """
        Detect drift for all configured schemas.

        Returns:
            Dict mapping schema name to DriftReport
        """
        schemas = [
            self.config.app_schema,
            self.config.postgis_schema,
            getattr(self.config, 'h3_schema', 'h3'),
        ]

        results = {}
        for schema in schemas:
            results[schema] = self.detect_drift(schema)

        return results

    # ========================================================================
    # MIGRATION HELPERS
    # ========================================================================

    def get_missing_objects(self, schema_name: str) -> Dict[str, Any]:
        """
        Get list of missing objects that need to be created.

        Useful for smart initialization - only create what's missing.

        Args:
            schema_name: Schema to check

        Returns:
            Dict with missing tables, columns, indexes
        """
        drift = self.detect_drift(schema_name)

        return {
            "schema_exists": not any(
                d.drift_type == DriftType.MISSING_TABLE and d.table_name == "<schema>"
                for d in drift.drift_items
            ),
            "missing_tables": drift.missing_tables,
            "missing_columns": drift.missing_columns,
            "missing_indexes": drift.missing_indexes,
            "has_drift": drift.has_drift,
        }

    def generate_migration_report(self, output_format: str = "text") -> str:
        """
        Generate a comprehensive migration report for all schemas.

        Args:
            output_format: "text" or "markdown"

        Returns:
            Formatted report string
        """
        all_drift = self.detect_all_drift()

        lines = []
        lines.append("=" * 70)
        lines.append("DATABASE SCHEMA MIGRATION REPORT")
        lines.append(f"Generated: {datetime.utcnow().isoformat()}")
        lines.append("=" * 70)

        for schema_name, drift in all_drift.items():
            lines.append(f"\n## Schema: {schema_name}")
            lines.append("-" * 40)

            if not drift.has_drift:
                lines.append("✅ No drift detected - schema matches expected")
                continue

            if drift.missing_tables:
                lines.append(f"\n### Missing Tables ({len(drift.missing_tables)})")
                for t in drift.missing_tables:
                    lines.append(f"  - {t}")

            if drift.missing_columns:
                lines.append(f"\n### Missing Columns")
                for table, cols in drift.missing_columns.items():
                    lines.append(f"  Table: {table}")
                    for col in cols:
                        lines.append(f"    - {col}")

            if drift.missing_indexes:
                lines.append(f"\n### Missing Indexes ({len(drift.missing_indexes)})")
                for idx in drift.missing_indexes:
                    lines.append(f"  - {idx}")

            if drift.extra_tables:
                lines.append(f"\n### Extra Tables (not in expected schema)")
                for t in drift.extra_tables:
                    lines.append(f"  - {t}")

            if drift.migration_statements:
                lines.append(f"\n### Migration SQL Statements ({len(drift.migration_statements)})")
                for stmt in drift.migration_statements:
                    lines.append(f"  {stmt};")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'SchemaAnalyzer',
    'SchemaReport',
    'DriftReport',
    'DriftItem',
    'DriftType',
    'TableInfo',
    'ColumnInfo',
    'IndexInfo',
    'ExpectedSchemaRegistry',
]
