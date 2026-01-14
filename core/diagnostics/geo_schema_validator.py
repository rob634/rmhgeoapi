# ============================================================================
# GEO SCHEMA VALIDATOR - Table Integrity Diagnostics
# ============================================================================
# STATUS: Core - Diagnostic utility for geo schema validation
# PURPOSE: Detect improperly configured geo tables (untyped geometry, missing SRID)
# CREATED: 14 JAN 2026
# DESIGN: First principle - we don't fix tables, we flag them for deletion
# ============================================================================
"""
Geo Schema Validator - Integrity diagnostics for PostGIS tables.

Detects tables that won't work with TiPG/OGC Features due to:
    - Untyped geometry columns (GEOMETRY without subtype)
    - Missing SRID (0 or NULL)
    - Missing spatial index
    - Not registered in geometry_columns view

Usage:
    from core.diagnostics.geo_schema_validator import GeoSchemaValidator

    validator = GeoSchemaValidator(connection)
    report = validator.validate_all()

    if report['invalid_tables']:
        for table in report['invalid_tables']:
            print(f"DELETE: {table['table_name']} - {table['issues']}")

Exports:
    GeoSchemaValidator: Validator class for geo schema integrity checks
    GeoTableIssue: Enum of possible table issues
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class GeoTableIssue(Enum):
    """Possible issues with geo schema tables."""
    UNTYPED_GEOMETRY = "untyped_geometry"      # GEOMETRY without subtype (Point, Polygon, etc.)
    MISSING_SRID = "missing_srid"              # SRID is 0 or NULL
    NO_SPATIAL_INDEX = "no_spatial_index"      # No GIST index on geometry column
    NOT_REGISTERED = "not_registered"          # Table exists but not in geometry_columns
    EMPTY_TABLE = "empty_table"                # Table has 0 rows (optional check)
    MIXED_GEOMETRY = "mixed_geometry"          # Multiple geometry types in same column


@dataclass
class TableValidationResult:
    """Result of validating a single table."""
    schema: str
    table_name: str
    geometry_column: str
    geometry_type: Optional[str]
    srid: Optional[int]
    has_spatial_index: bool
    row_count: Optional[int]
    issues: List[GeoTableIssue]

    @property
    def is_valid(self) -> bool:
        """Table is valid if no issues found."""
        return len(self.issues) == 0

    @property
    def is_tipg_compatible(self) -> bool:
        """Table can be served by TiPG if geometry is typed and has SRID."""
        critical_issues = {
            GeoTableIssue.UNTYPED_GEOMETRY,
            GeoTableIssue.MISSING_SRID,
            GeoTableIssue.NOT_REGISTERED
        }
        return not any(issue in critical_issues for issue in self.issues)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'schema': self.schema,
            'table_name': self.table_name,
            'full_name': f"{self.schema}.{self.table_name}",
            'geometry_column': self.geometry_column,
            'geometry_type': self.geometry_type,
            'srid': self.srid,
            'has_spatial_index': self.has_spatial_index,
            'row_count': self.row_count,
            'issues': [issue.value for issue in self.issues],
            'is_valid': self.is_valid,
            'is_tipg_compatible': self.is_tipg_compatible
        }


class GeoSchemaValidator:
    """
    Validator for geo schema table integrity.

    Checks PostGIS tables for proper configuration required by TiPG
    and OGC Features API.
    """

    # System tables in geo schema to exclude from TiPG comparison
    # These are internal metadata tables, not user data
    SYSTEM_TABLES = {
        'table_metadata',      # Vector metadata tracking
        'spatial_ref_sys',     # PostGIS system table
        'geometry_columns',    # PostGIS system view
        'geography_columns',   # PostGIS system view
        'raster_columns',      # PostGIS system view
        'raster_overviews',    # PostGIS system view
    }

    # Geometry types that are properly typed (not generic)
    VALID_GEOMETRY_TYPES = {
        'POINT', 'MULTIPOINT',
        'LINESTRING', 'MULTILINESTRING',
        'POLYGON', 'MULTIPOLYGON',
        'GEOMETRYCOLLECTION',
        'CIRCULARSTRING', 'COMPOUNDCURVE', 'CURVEPOLYGON',
        'MULTICURVE', 'MULTISURFACE',
        'POLYHEDRALSURFACE', 'TIN', 'TRIANGLE'
    }

    def __init__(self, connection, schema: str = 'geo'):
        """
        Initialize validator.

        Args:
            connection: psycopg connection object
            schema: Schema to validate (default 'geo')
        """
        self.conn = connection
        self.schema = schema

    def validate_all(
        self,
        include_row_counts: bool = False,
        include_tipg_sync: bool = True,
        titiler_base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate all tables in the geo schema.

        Args:
            include_row_counts: If True, count rows in each table (slower)
            include_tipg_sync: If True, compare with TiPG collection list
            titiler_base_url: TiTiler URL for TiPG sync (defaults to config)

        Returns:
            Dictionary with validation report:
            {
                'schema': 'geo',
                'total_tables': 15,
                'valid_tables': 12,
                'invalid_tables': [...],
                'tipg_sync': {...},  # TiPG comparison results
                'summary': {...}
            }
        """
        logger.info(f"🔍 Validating geo schema: {self.schema}")

        # Get all tables with geometry columns
        tables = self._get_geometry_tables()

        results: List[TableValidationResult] = []
        for table_info in tables:
            result = self._validate_table(
                table_info,
                include_row_counts=include_row_counts
            )
            results.append(result)

        # Categorize results
        valid = [r for r in results if r.is_valid]
        invalid = [r for r in results if not r.is_valid]
        tipg_compatible = [r for r in results if r.is_tipg_compatible]
        tipg_incompatible = [r for r in results if not r.is_tipg_compatible]

        # Build report
        report = {
            'schema': self.schema,
            'total_tables': len(results),
            'valid_tables': len(valid),
            'invalid_tables': len(invalid),
            'tipg_compatible': len(tipg_compatible),
            'tipg_incompatible': len(tipg_incompatible),
            'tables': [r.to_dict() for r in results],
            'issues_found': [r.to_dict() for r in invalid],
            'summary': self._build_summary(results)
        }

        # TiPG sync check - compare geo schema tables with TiPG collections
        if include_tipg_sync:
            tipg_sync = self.validate_tipg_sync(titiler_base_url)
            report['tipg_sync'] = tipg_sync

            # Add missing tables to issues if any
            if tipg_sync.get('missing_from_tipg'):
                logger.warning(
                    f"⚠️ {len(tipg_sync['missing_from_tipg'])} tables in geo schema "
                    f"but NOT in TiPG: {tipg_sync['missing_from_tipg'][:5]}"
                )

        # Log summary
        if invalid:
            logger.warning(f"⚠️ Found {len(invalid)} tables with issues:")
            for r in invalid:
                logger.warning(f"   - {r.schema}.{r.table_name}: {[i.value for i in r.issues]}")
        else:
            logger.info(f"✅ All {len(results)} tables are valid")

        return report

    def _get_geometry_tables(self) -> List[Dict[str, Any]]:
        """
        Get all tables with geometry columns from geometry_columns view.

        Returns:
            List of table info dictionaries
        """
        query = """
            SELECT
                f_table_schema as schema,
                f_table_name as table_name,
                f_geometry_column as geometry_column,
                type as geometry_type,
                srid,
                coord_dimension
            FROM geometry_columns
            WHERE f_table_schema = %s
            ORDER BY f_table_name
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (self.schema,))
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

        return [dict(zip(columns, row)) for row in rows]

    def _validate_table(
        self,
        table_info: Dict[str, Any],
        include_row_counts: bool = False
    ) -> TableValidationResult:
        """
        Validate a single table.

        Args:
            table_info: Dictionary with table metadata from geometry_columns
            include_row_counts: If True, count rows

        Returns:
            TableValidationResult with issues found
        """
        issues: List[GeoTableIssue] = []

        schema = table_info['schema']
        table_name = table_info['table_name']
        geom_col = table_info['geometry_column']
        geom_type = table_info.get('geometry_type', '').upper()
        srid = table_info.get('srid')

        # Check 1: Untyped geometry
        if not geom_type or geom_type == 'GEOMETRY':
            issues.append(GeoTableIssue.UNTYPED_GEOMETRY)
            logger.debug(f"   {table_name}: untyped geometry (type={geom_type})")
        elif geom_type not in self.VALID_GEOMETRY_TYPES:
            # Check if it's a valid type we don't recognize
            logger.debug(f"   {table_name}: unusual geometry type: {geom_type}")

        # Check 2: Missing SRID
        if srid is None or srid == 0:
            issues.append(GeoTableIssue.MISSING_SRID)
            logger.debug(f"   {table_name}: missing SRID (srid={srid})")

        # Check 3: Spatial index
        has_index = self._check_spatial_index(schema, table_name, geom_col)
        if not has_index:
            issues.append(GeoTableIssue.NO_SPATIAL_INDEX)
            logger.debug(f"   {table_name}: no spatial index")

        # Check 4: Row count (optional)
        row_count = None
        if include_row_counts:
            row_count = self._get_row_count(schema, table_name)
            if row_count == 0:
                issues.append(GeoTableIssue.EMPTY_TABLE)

        return TableValidationResult(
            schema=schema,
            table_name=table_name,
            geometry_column=geom_col,
            geometry_type=geom_type if geom_type else None,
            srid=srid,
            has_spatial_index=has_index,
            row_count=row_count,
            issues=issues
        )

    def _check_spatial_index(
        self,
        schema: str,
        table_name: str,
        geom_col: str
    ) -> bool:
        """
        Check if table has a GIST spatial index on geometry column.

        Args:
            schema: Schema name
            table_name: Table name
            geom_col: Geometry column name

        Returns:
            True if spatial index exists
        """
        query = """
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = %s
                  AND tablename = %s
                  AND indexdef ILIKE %s
            )
        """

        # Match GIST indexes on the geometry column
        pattern = f'%gist%{geom_col}%'

        with self.conn.cursor() as cur:
            cur.execute(query, (schema, table_name, pattern))
            result = cur.fetchone()
            if not result:
                return False
            # Handle both tuple (psycopg2) and dict (psycopg3 with row_factory)
            if isinstance(result, dict):
                return result.get('exists', False)
            return result[0]

    def _get_row_count(self, schema: str, table_name: str) -> int:
        """
        Get row count for a table.

        Args:
            schema: Schema name
            table_name: Table name

        Returns:
            Number of rows
        """
        # Use identifier quoting for safety
        from psycopg import sql
        query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            sql.Identifier(schema),
            sql.Identifier(table_name)
        )

        with self.conn.cursor() as cur:
            cur.execute(query)
            result = cur.fetchone()
            if not result:
                return 0
            # Handle both tuple (psycopg2) and dict (psycopg3 with row_factory)
            if isinstance(result, dict):
                return result.get('count', 0)
            return result[0]

    def _build_summary(self, results: List[TableValidationResult]) -> Dict[str, Any]:
        """
        Build summary statistics from validation results.

        Args:
            results: List of validation results

        Returns:
            Summary dictionary
        """
        # Count issues by type
        issue_counts: Dict[str, int] = {}
        for result in results:
            for issue in result.issues:
                issue_counts[issue.value] = issue_counts.get(issue.value, 0) + 1

        # Count geometry types
        geom_types: Dict[str, int] = {}
        for result in results:
            gt = result.geometry_type or 'UNKNOWN'
            geom_types[gt] = geom_types.get(gt, 0) + 1

        # Count SRIDs
        srids: Dict[str, int] = {}
        for result in results:
            srid_key = str(result.srid) if result.srid else 'NULL'
            srids[srid_key] = srids.get(srid_key, 0) + 1

        return {
            'issue_counts': issue_counts,
            'geometry_types': geom_types,
            'srids': srids,
            'tables_without_index': sum(1 for r in results if not r.has_spatial_index)
        }


    def validate_tipg_sync(self, titiler_base_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Compare geo schema tables with TiPG's collection list.

        Tables in geo schema but NOT in TiPG indicate a problem - TiPG
        cannot serve them (likely invalid geometry format).

        Args:
            titiler_base_url: TiTiler base URL (defaults to config)

        Returns:
            Dictionary with sync report:
            {
                'in_sync': True/False,
                'geo_tables': ['table1', 'table2', ...],
                'tipg_collections': ['geo.table1', ...],
                'missing_from_tipg': ['table3'],  # PROBLEM - TiPG can't serve
                'extra_in_tipg': [],  # Unlikely but possible
            }
        """
        import httpx

        logger.info("🔄 Checking TiPG collection sync")

        # Get TiTiler URL from config if not provided
        if not titiler_base_url:
            try:
                from config import get_config
                config = get_config()
                titiler_base_url = config.titiler_base_url
            except Exception as e:
                logger.warning(f"Could not get titiler_base_url from config: {e}")
                return {
                    'in_sync': None,
                    'error': f"Could not determine TiTiler URL: {e}",
                    'skipped': True
                }

        # Get tables from geo schema (excluding system tables)
        geo_tables = self._get_geo_table_names()
        geo_tables_set = set(geo_tables) - self.SYSTEM_TABLES

        logger.info(f"   Found {len(geo_tables_set)} user tables in geo schema")

        # Fetch TiPG collections
        try:
            tipg_url = f"{titiler_base_url.rstrip('/')}/vector/collections"
            logger.info(f"   Fetching TiPG collections from: {tipg_url}")

            with httpx.Client(timeout=30.0) as client:
                response = client.get(tipg_url)
                response.raise_for_status()
                data = response.json()

            # Extract collection IDs (format: "geo.tablename")
            tipg_collections = []
            for collection in data.get('collections', []):
                coll_id = collection.get('id', '')
                tipg_collections.append(coll_id)

            logger.info(f"   Found {len(tipg_collections)} collections in TiPG")

            # Extract just table names from TiPG (remove "geo." prefix)
            tipg_table_names = set()
            for coll_id in tipg_collections:
                if coll_id.startswith(f"{self.schema}."):
                    table_name = coll_id[len(f"{self.schema}."):]
                    tipg_table_names.add(table_name)
                elif '.' not in coll_id:
                    # No schema prefix
                    tipg_table_names.add(coll_id)

            # Compare
            missing_from_tipg = geo_tables_set - tipg_table_names
            extra_in_tipg = tipg_table_names - geo_tables_set

            # Filter out system tables from missing (double-check)
            missing_from_tipg = missing_from_tipg - self.SYSTEM_TABLES

            in_sync = len(missing_from_tipg) == 0

            if missing_from_tipg:
                logger.warning(f"   ⚠️ {len(missing_from_tipg)} tables NOT in TiPG: {list(missing_from_tipg)[:5]}")
            else:
                logger.info("   ✅ All geo tables are available in TiPG")

            return {
                'in_sync': in_sync,
                'geo_tables_count': len(geo_tables_set),
                'tipg_collections_count': len(tipg_collections),
                'geo_tables': sorted(list(geo_tables_set)),
                'tipg_collections': sorted(tipg_collections),
                'missing_from_tipg': sorted(list(missing_from_tipg)),
                'extra_in_tipg': sorted(list(extra_in_tipg)),
                'tipg_url': tipg_url
            }

        except httpx.HTTPError as e:
            logger.error(f"   ❌ Failed to fetch TiPG collections: {e}")
            return {
                'in_sync': None,
                'error': f"HTTP error fetching TiPG: {e}",
                'tipg_url': tipg_url,
                'skipped': True
            }
        except Exception as e:
            logger.error(f"   ❌ Error checking TiPG sync: {e}")
            return {
                'in_sync': None,
                'error': str(e),
                'skipped': True
            }

    def _get_geo_table_names(self) -> List[str]:
        """
        Get all table names in the geo schema.

        Returns:
            List of table names (without schema prefix)
        """
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (self.schema,))
            rows = cur.fetchall()

        return [row[0] for row in rows]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_geo_schema(connection, schema: str = 'geo') -> Dict[str, Any]:
    """
    Convenience function to validate geo schema.

    Args:
        connection: psycopg connection
        schema: Schema to validate

    Returns:
        Validation report dictionary
    """
    validator = GeoSchemaValidator(connection, schema)
    return validator.validate_all()


def get_invalid_tables(connection, schema: str = 'geo') -> List[str]:
    """
    Get list of invalid table names for deletion.

    Args:
        connection: psycopg connection
        schema: Schema to check

    Returns:
        List of fully qualified table names (schema.table)
    """
    validator = GeoSchemaValidator(connection, schema)
    report = validator.validate_all()

    return [
        f"{t['schema']}.{t['table_name']}"
        for t in report['issues_found']
        if not t['is_tipg_compatible']
    ]


def get_tipg_incompatible_tables(connection, schema: str = 'geo') -> List[Dict[str, Any]]:
    """
    Get tables that TiPG cannot serve.

    Args:
        connection: psycopg connection
        schema: Schema to check

    Returns:
        List of table info dictionaries with issues
    """
    validator = GeoSchemaValidator(connection, schema)
    report = validator.validate_all()

    return [
        t for t in report['tables']
        if not t['is_tipg_compatible']
    ]
