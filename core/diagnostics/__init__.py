"""
Core diagnostics module.

Provides validation and integrity checking utilities.

Exports:
    GeoSchemaValidator: Validator for geo schema table integrity
    GeoTableIssue: Enum of possible table issues
    validate_geo_schema: Convenience function for validation
    get_invalid_tables: Get list of invalid tables for deletion
    get_tipg_incompatible_tables: Get tables TiPG cannot serve
"""

from .geo_schema_validator import (
    GeoSchemaValidator,
    GeoTableIssue,
    TableValidationResult,
    validate_geo_schema,
    get_invalid_tables,
    get_tipg_incompatible_tables
)

__all__ = [
    'GeoSchemaValidator',
    'GeoTableIssue',
    'TableValidationResult',
    'validate_geo_schema',
    'get_invalid_tables',
    'get_tipg_incompatible_tables'
]
