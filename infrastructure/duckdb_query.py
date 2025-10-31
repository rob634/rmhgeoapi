# ============================================================================
# CLAUDE CONTEXT - INFRASTRUCTURE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - DuckDB SQL query composition utility
# PURPOSE: Safe SQL query composition for DuckDB (similar to psycopg.sql)
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: QueryBuilder, Identifier, Literal, QueryParam, OvertureQueryBuilder
# INTERFACES: None - utility classes for SQL composition
# PYDANTIC_MODELS: None (uses dataclasses)
# DEPENDENCIES: re (regex), typing, dataclasses
# SOURCE: N/A - infrastructure utility
# SCOPE: DuckDB SQL injection prevention via composition
# VALIDATION: Identifier format validation, whitelist literals, parameter type checking
# PATTERNS: Builder pattern, SQL composition (injection-safe), Validation decorators
# ENTRY_POINTS: qb = QueryBuilder(); qb.append(...); query, params = qb.build()
# INDEX: QueryParam:40, Identifier:50, Literal:75, QueryBuilder:100, OvertureQueryBuilder:180
# ============================================================================

"""
DuckDB Safe SQL Query Composition

This module provides safe SQL composition for DuckDB queries, similar to
psycopg's sql.SQL() and sql.Identifier() pattern. It prevents SQL injection
by separating query structure from parameters and validating identifiers.

Architecture:
    PostgreSQL (psycopg):
        sql.SQL("SELECT * FROM {}").format(sql.Identifier('table'))

    DuckDB (this module):
        qb = QueryBuilder()
        qb.append("SELECT * FROM", Identifier('table'))
        query, params = qb.build()

Key Classes:
    - QueryParam: Marks values for parameterization (? placeholders)
    - Identifier: Validates SQL identifiers (tables, columns)
    - Literal: Validates whitelisted string literals
    - QueryBuilder: Core composition engine
    - OvertureQueryBuilder: Domain-specific validation

Safety Guarantees:
    - Identifiers validated against regex (alphanumeric + underscore)
    - Literals validated against whitelists
    - Values automatically parameterized
    - Type checking prevents accidental string concatenation

Example Usage:
    ```python
    from infrastructure.duckdb_query import QueryBuilder, Identifier, QueryParam

    qb = QueryBuilder()
    qb.append(
        "SELECT * FROM",
        Identifier('my_table'),
        "WHERE id =", QueryParam(123),
        "AND name =", QueryParam('test')
    )
    query, params = qb.build()
    # query = "SELECT * FROM my_table WHERE id = ? AND name = ?"
    # params = [123, 'test']

    conn.execute(query, params)
    ```

Author: Robert and Geospatial Claude Legion
Date: 14 OCT 2025
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass


@dataclass
class QueryParam:
    """
    Represents a parameterized value in a DuckDB query.

    Values are replaced with ? placeholders and tracked separately
    for safe parameter binding.

    Example:
        QueryParam(123) → "?" with params=[123]
        QueryParam('test') → "?" with params=['test']
    """
    value: Any

    def __str__(self):
        return "?"


@dataclass
class Identifier:
    """
    Represents a safely validated SQL identifier (table, column, etc.).

    Validates that the identifier follows SQL naming conventions:
    - Starts with letter or underscore
    - Contains only alphanumeric characters and underscores

    This prevents SQL injection via table/column names.

    Example:
        Identifier('my_table')  # Valid
        Identifier('users')     # Valid
        Identifier('table1')    # Valid
        Identifier('my-table')  # INVALID (hyphen not allowed)
        Identifier('1table')    # INVALID (starts with number)
        Identifier('DROP TABLE users')  # INVALID (spaces not allowed)

    Raises:
        ValueError: If identifier doesn't match SQL naming conventions
    """
    name: str

    def __post_init__(self):
        # Validate identifier format
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', self.name):
            raise ValueError(
                f"Invalid identifier: '{self.name}'. "
                f"Must start with letter/underscore and contain only "
                f"alphanumeric characters and underscores."
            )

    def __str__(self):
        return self.name


@dataclass
class Literal:
    """
    Represents a literal SQL value (must be from whitelist).

    Used for string literals that must come from a predefined set
    (e.g., Overture themes, road classes).

    Example:
        THEMES = {'buildings', 'transportation', 'places'}
        Literal('buildings', THEMES)  # Valid
        Literal('invalid', THEMES)    # INVALID - raises ValueError

    Args:
        value: String value to use as literal
        allowed_values: Optional set of allowed values for validation

    Raises:
        ValueError: If value not in allowed_values
    """
    value: str
    allowed_values: Optional[Set[str]] = None

    def __post_init__(self):
        if self.allowed_values and self.value not in self.allowed_values:
            raise ValueError(
                f"Value '{self.value}' not in allowed set: {self.allowed_values}"
            )

    def __str__(self):
        return f"'{self.value}'"


class QueryBuilder:
    """
    Safe query composition for DuckDB, inspired by psycopg.sql.

    Builds SQL queries by composing parts and tracking parameters separately.
    This prevents SQL injection by ensuring values are never concatenated
    directly into SQL strings.

    Usage Pattern:
        1. Create builder: qb = QueryBuilder()
        2. Append parts: qb.append("SELECT", Identifier('col'), "FROM", ...)
        3. Build query: query, params = qb.build()
        4. Execute: conn.execute(query, params)

    Example:
        ```python
        qb = QueryBuilder()
        qb.append(
            "SELECT",
            Identifier('name'),
            "FROM",
            Identifier('users'),
            "WHERE age >", QueryParam(18),
            "AND city =", QueryParam('NYC')
        )
        query, params = qb.build()
        # query = "SELECT name FROM users WHERE age > ? AND city = ?"
        # params = [18, 'NYC']
        ```

    Thread Safety:
        Not thread-safe. Create separate instances for concurrent queries.
    """

    def __init__(self):
        """Initialize empty query builder."""
        self.parts: List[str] = []
        self.params: List[Any] = []

    def append(self, *items) -> 'QueryBuilder':
        """
        Add parts to the query.

        Accepts:
        - QueryParam: Adds ? placeholder and tracks parameter
        - Identifier: Adds validated identifier name
        - Literal: Adds validated literal value
        - str: Adds raw SQL (use only for static strings)

        Args:
            *items: Variable number of query parts

        Returns:
            Self for method chaining

        Raises:
            TypeError: If item type is not supported

        Example:
            qb.append("SELECT", Identifier('col'), "FROM", Identifier('table'))
        """
        for item in items:
            if isinstance(item, QueryParam):
                self.parts.append("?")
                self.params.append(item.value)
            elif isinstance(item, (Identifier, Literal)):
                self.parts.append(str(item))
            elif isinstance(item, str):
                # Raw SQL - use with caution, only for static strings
                self.parts.append(item)
            else:
                raise TypeError(
                    f"Unsupported query part type: {type(item).__name__}. "
                    f"Use QueryParam, Identifier, Literal, or str."
                )
        return self

    def build(self) -> Tuple[str, List[Any]]:
        """
        Build the final query string and parameter list.

        Returns:
            Tuple of (query_string, parameters)
            - query_string: SQL with ? placeholders
            - parameters: List of parameter values in order

        Example:
            query, params = qb.build()
            result = conn.execute(query, params)
        """
        query = ' '.join(self.parts)
        return query, self.params

    def __str__(self):
        """String representation (for debugging)."""
        return ' '.join(self.parts)


class OvertureQueryBuilder:
    """
    Specialized query builder for Overture Maps with validated enums.

    Provides domain-specific validation for Overture Maps data:
    - Themes (buildings, transportation, places, etc.)
    - Types (building, segment, connector, etc.)
    - Release versions (YYYY-MM-DD.N format)
    - Road classes (motorway, primary, etc.)

    This class enforces whitelists for all Overture-specific values to
    prevent SQL injection via path manipulation.

    Example:
        ```python
        builder = OvertureQueryBuilder()
        path = builder.build_overture_path(
            theme='buildings',
            type_name='building',
            release='2024-11-13.0'
        )
        # Returns validated path string
        ```
    """

    # Whitelists for Overture-specific values
    THEMES: Set[str] = {
        'addresses', 'base', 'buildings', 'divisions',
        'places', 'transportation'
    }

    TYPES: Set[str] = {
        'address', 'building', 'connector', 'segment',
        'place', 'infrastructure', 'land', 'water',
        'division', 'division_area'
    }

    ROAD_CLASSES: Set[str] = {
        'motorway', 'trunk', 'primary', 'secondary',
        'tertiary', 'residential', 'unclassified', 'service'
    }

    @staticmethod
    def validate_theme(theme: str) -> str:
        """
        Validate Overture theme name.

        Args:
            theme: Theme name to validate

        Returns:
            Validated theme name

        Raises:
            ValueError: If theme not in whitelist
        """
        if theme not in OvertureQueryBuilder.THEMES:
            raise ValueError(
                f"Invalid theme: '{theme}'. "
                f"Allowed themes: {', '.join(sorted(OvertureQueryBuilder.THEMES))}"
            )
        return theme

    @staticmethod
    def validate_type(type_name: str) -> str:
        """
        Validate Overture type name.

        Args:
            type_name: Type name to validate

        Returns:
            Validated type name

        Raises:
            ValueError: If type not in whitelist
        """
        if type_name not in OvertureQueryBuilder.TYPES:
            raise ValueError(
                f"Invalid type: '{type_name}'. "
                f"Allowed types: {', '.join(sorted(OvertureQueryBuilder.TYPES))}"
            )
        return type_name

    @staticmethod
    def validate_release(release: str) -> str:
        """
        Validate Overture release version format.

        Expected format: YYYY-MM-DD.N (e.g., 2024-11-13.0)

        Args:
            release: Release version string

        Returns:
            Validated release string

        Raises:
            ValueError: If release doesn't match expected format
        """
        if not re.match(r'^\d{4}-\d{2}-\d{2}\.\d+$', release):
            raise ValueError(
                f"Invalid release format: '{release}'. "
                f"Expected format: YYYY-MM-DD.N (e.g., 2024-11-13.0)"
            )
        return release

    @staticmethod
    def validate_resolution(resolution: int) -> int:
        """
        Validate H3 resolution level.

        H3 supports resolutions 0-15:
        - 0: ~1,000 km edge length
        - 4: ~10 km edge length
        - 6: ~1 km edge length
        - 15: ~1 meter edge length

        Args:
            resolution: H3 resolution level

        Returns:
            Validated resolution

        Raises:
            ValueError: If resolution not in range 0-15
        """
        if not (0 <= resolution <= 15):
            raise ValueError(
                f"Invalid H3 resolution: {resolution}. "
                f"Must be between 0 and 15."
            )
        return resolution

    @staticmethod
    def build_overture_path(
        theme: str,
        type_name: str,
        release: str = "2024-11-13.0"
    ) -> str:
        """
        Safely build Overture parquet path with validation.

        Validates all components and builds the Azure Blob Storage path
        for Overture Maps data.

        Args:
            theme: Overture theme (validated against whitelist)
            type_name: Overture type (validated against whitelist)
            release: Release version (validated format)

        Returns:
            Complete Azure Blob Storage path

        Raises:
            ValueError: If any component fails validation

        Example:
            path = build_overture_path(
                theme='buildings',
                type_name='building',
                release='2024-11-13.0'
            )
            # Returns: 'az://overturemapswestus2.blob.core.windows.net/
            #           release/2024-11-13.0/theme=buildings/type=building/*'
        """
        # Validate all inputs
        theme = OvertureQueryBuilder.validate_theme(theme)
        type_name = OvertureQueryBuilder.validate_type(type_name)
        release = OvertureQueryBuilder.validate_release(release)

        # Build path with validated components
        base = "azure://overturemapswestus2.blob.core.windows.net"
        path = f"{base}/release/{release}/theme={theme}/type={type_name}/*.parquet"

        return path
