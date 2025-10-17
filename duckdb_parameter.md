Absolutely! That makes perfect sense - centralizing parameterization at the repository level is exactly the right approach. Let me explain how DuckDB parameterization works and how to build a safe query composition pattern similar to psycopg's `sql.SQL()`.

## DuckDB Parameterization Methods

DuckDB supports two styles:

### 1. Positional Parameters (`?`)
```python
conn.execute("SELECT * FROM table WHERE id = ? AND value > ?", [123, 50])
```

### 2. Named Parameters (`$name`)
```python
conn.execute(
    "SELECT * FROM table WHERE id = $id AND value > $threshold",
    {'id': 123, 'threshold': 50}
)
```

## Key Difference from psycopg

**psycopg3** has `sql.SQL()` composition for safe query building:
```python
from psycopg import sql

query = sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
    sql.Identifier('my_table'),
    sql.Identifier('my_column')
)
cursor.execute(query, [value])
```

**DuckDB** doesn't have a built-in composition library, so we need to build our own safe abstraction.

## What Can and Cannot Be Parameterized

### ✅ Can Be Parameterized (use `?` or `$name`)
- Values in WHERE clauses
- Values in INSERT/UPDATE
- Literal values
- Numeric parameters

### ❌ Cannot Be Parameterized (need safe composition)
- Table names
- Column names
- File paths (e.g., in `read_parquet()`)
- Function names
- SQL keywords

## Recommended Approach: Safe Query Builder

Here's a repository-level pattern inspired by psycopg's sql composition:

```python
# repositories/duckdb_query_builder.py

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import re


@dataclass
class QueryParam:
    """Represents a parameterized value"""
    value: Any
    
    def __str__(self):
        return "?"


@dataclass
class Identifier:
    """Represents a safely validated SQL identifier (table, column, etc.)"""
    name: str
    
    def __post_init__(self):
        # Validate identifier format
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', self.name):
            raise ValueError(f"Invalid identifier: {self.name}")
    
    def __str__(self):
        return self.name


@dataclass
class Literal:
    """Represents a literal SQL value (must be from whitelist)"""
    value: str
    allowed_values: Optional[set] = None
    
    def __post_init__(self):
        if self.allowed_values and self.value not in self.allowed_values:
            raise ValueError(f"Value '{self.value}' not in allowed set")
    
    def __str__(self):
        return f"'{self.value}'"


class QueryBuilder:
    """
    Safe query composition for DuckDB, inspired by psycopg.sql
    """
    
    def __init__(self):
        self.parts = []
        self.params = []
    
    def append(self, *items):
        """Add parts to the query"""
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
                raise TypeError(f"Unsupported query part type: {type(item)}")
        return self
    
    def build(self) -> tuple[str, list]:
        """Return the query string and parameters"""
        query = ' '.join(self.parts)
        return query, self.params
    
    def __str__(self):
        return ' '.join(self.parts)


class OvertureQueryBuilder:
    """
    Specialized query builder for Overture Maps with validated enums
    """
    
    # Whitelists for Overture-specific values
    THEMES = {'addresses', 'base', 'buildings', 'divisions', 'places', 'transportation'}
    TYPES = {
        'address', 'building', 'connector', 'segment', 
        'place', 'infrastructure', 'land', 'water',
        'division', 'division_area'
    }
    ROAD_CLASSES = {
        'motorway', 'trunk', 'primary', 'secondary', 
        'tertiary', 'residential', 'unclassified', 'service'
    }
    
    @staticmethod
    def build_overture_path(
        theme: str,
        type_name: str,
        release: str = "2025-09-24.0"
    ) -> str:
        """
        Safely build Overture parquet path with validation
        """
        if theme not in OvertureQueryBuilder.THEMES:
            raise ValueError(f"Invalid theme: {theme}")
        if type_name not in OvertureQueryBuilder.TYPES:
            raise ValueError(f"Invalid type: {type_name}")
        if not re.match(r'^\d{4}-\d{2}-\d{2}\.\d+$', release):
            raise ValueError(f"Invalid release format: {release}")
        
        base = "az://overturemapswestus2.blob.core.windows.net"
        return f"{base}/release/{release}/theme={theme}/type={type_name}/*"
    
    @staticmethod
    def build_h3_aggregation_query(
        theme: str,
        type_name: str,
        resolution: int,
        bbox: tuple,
        aggregations: Dict[str, str],
        release: str = "2025-09-24.0"
    ) -> tuple[str, list]:
        """
        Build a safe H3 aggregation query
        
        Args:
            theme: Overture theme (validated)
            type_name: Overture type (validated)
            resolution: H3 resolution 0-15
            bbox: (west, south, east, north)
            aggregations: Dict of {alias: sql_expression} for SELECT clause
            release: Overture release version
        
        Returns:
            (query_string, parameters)
        """
        # Validate resolution
        if not (0 <= resolution <= 15):
            raise ValueError(f"Resolution must be 0-15, got: {resolution}")
        
        # Validate bbox
        west, south, east, north = bbox
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise ValueError("Invalid longitude")
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            raise ValueError("Invalid latitude")
        
        # Build path with validation
        path = OvertureQueryBuilder.build_overture_path(theme, type_name, release)
        
        # Build aggregation SELECT clause
        agg_parts = []
        for alias, expr in aggregations.items():
            # Validate alias is safe identifier
            Identifier(alias)  # Raises if invalid
            # expr should come from a whitelist in production
            agg_parts.append(f"{expr} as {alias}")
        
        select_clause = ", ".join(agg_parts) if agg_parts else "COUNT(*) as count"
        
        # Build query
        qb = QueryBuilder()
        qb.append(
            "SELECT",
            f"h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {resolution}) as h3_index,",
            select_clause,
            "FROM read_parquet(",
            QueryParam(path),
            ", hive_partitioning=1",
            ")",
            "WHERE bbox.xmin >=", QueryParam(west),
            "AND bbox.xmax <=", QueryParam(east),
            "AND bbox.ymin >=", QueryParam(south),
            "AND bbox.ymax <=", QueryParam(north),
            "GROUP BY h3_index"
        )
        
        return qb.build()
```

## Updated Repository Pattern

Now integrate this into your DuckDB repository:

```python
# repositories/duckdb_repository.py

import duckdb
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager
import logging


class DuckDBRepository:
    """Base repository for DuckDB operations with safe query composition"""
    
    def __init__(self):
        self.conn = None
        self._setup_connection()
    
    def _setup_connection(self):
        """Initialize DuckDB connection with extensions"""
        self.conn = duckdb.connect(':memory:')
        self.conn.execute("INSTALL azure;")
        self.conn.execute("LOAD azure;")
        self.conn.execute("INSTALL h3;")
        self.conn.execute("LOAD h3;")
        self.conn.execute("INSTALL spatial;")
        self.conn.execute("LOAD spatial;")
        self.conn.execute("SET memory_limit = '8GB';")
        self.conn.execute("SET threads = 4;")
    
    @contextmanager
    def get_connection(self):
        """Context manager for connection"""
        try:
            yield self.conn
        except Exception as e:
            logging.error(f"DuckDB query error: {str(e)}")
            raise
    
    def execute_query(
        self,
        query: str,
        params: Optional[List[Any]] = None
    ) -> pd.DataFrame:
        """
        Execute a parameterized query safely
        
        Args:
            query: Query string with ? placeholders
            params: List of parameter values
        
        Returns:
            DataFrame with results
        """
        try:
            if params:
                result = self.conn.execute(query, params)
            else:
                result = self.conn.execute(query)
            return result.fetchdf()
        except Exception as e:
            logging.error(f"Query execution failed: {str(e)}")
            logging.error(f"Query: {query}")
            logging.error(f"Params: {params}")
            raise
    
    def execute_query_dict(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Execute query with named parameters
        
        Args:
            query: Query string with $name placeholders
            params: Dict of parameter values
        
        Returns:
            DataFrame with results
        """
        try:
            if params:
                result = self.conn.execute(query, params)
            else:
                result = self.conn.execute(query)
            return result.fetchdf()
        except Exception as e:
            logging.error(f"Query execution failed: {str(e)}")
            logging.error(f"Query: {query}")
            logging.error(f"Params: {params}")
            raise


class OvertureRepository(DuckDBRepository):
    """Repository for Overture Maps data with safe query composition"""
    
    def __init__(self):
        super().__init__()
        self.query_builder = OvertureQueryBuilder()
    
    def aggregate_buildings_to_h3(
        self,
        resolution: int,
        bbox: Tuple[float, float, float, float],
        release: str = "2025-09-24.0"
    ) -> pd.DataFrame:
        """
        Aggregate building data to H3 cells
        
        Args:
            resolution: H3 resolution (0-15)
            bbox: (west, south, east, north)
            release: Overture release version
        
        Returns:
            DataFrame with h3_index, building_count, total_area, avg_height
        """
        aggregations = {
            'building_count': 'COUNT(*)',
            'total_area': 'SUM(ST_Area(geometry))',
            'avg_height': 'AVG(height)',
            'max_height': 'MAX(height)'
        }
        
        query, params = self.query_builder.build_h3_aggregation_query(
            theme='buildings',
            type_name='building',
            resolution=resolution,
            bbox=bbox,
            aggregations=aggregations,
            release=release
        )
        
        return self.execute_query(query, params)
    
    def aggregate_roads_to_h3(
        self,
        resolution: int,
        bbox: Tuple[float, float, float, float],
        road_classes: Optional[List[str]] = None,
        release: str = "2025-09-24.0"
    ) -> pd.DataFrame:
        """
        Aggregate road data to H3 cells with optional class filtering
        
        Args:
            resolution: H3 resolution (0-15)
            bbox: (west, south, east, north)
            road_classes: List of road classes to include (validated)
            release: Overture release version
        
        Returns:
            DataFrame with h3_index, road metrics by class
        """
        # Validate road classes if provided
        if road_classes:
            for rc in road_classes:
                if rc not in OvertureQueryBuilder.ROAD_CLASSES:
                    raise ValueError(f"Invalid road class: {rc}")
        
        # Build aggregations
        aggregations = {
            'total_length': 'SUM(ST_Length(geometry))',
            'segment_count': 'COUNT(*)',
            'avg_length': 'AVG(ST_Length(geometry))'
        }
        
        # Build base query
        query, params = self.query_builder.build_h3_aggregation_query(
            theme='transportation',
            type_name='segment',
            resolution=resolution,
            bbox=bbox,
            aggregations=aggregations,
            release=release
        )
        
        # Add road class filtering if specified
        if road_classes:
            # Insert WHERE clause for classes
            placeholders = ', '.join(['?'] * len(road_classes))
            class_filter = f"AND class IN ({placeholders})"
            
            # Insert before GROUP BY
            query = query.replace(
                "GROUP BY h3_index",
                f"{class_filter} GROUP BY h3_index"
            )
            params.extend(road_classes)
        
        return self.execute_query(query, params)
    
    def query_h3_cells(
        self,
        h3_indices: List[str],
        theme: str,
        type_name: str,
        columns: List[str],
        release: str = "2025-09-24.0"
    ) -> pd.DataFrame:
        """
        Query specific H3 cells from Overture data
        
        Args:
            h3_indices: List of H3 indices (validated)
            theme: Overture theme
            type_name: Overture type
            columns: Columns to select (validated as identifiers)
            release: Overture release version
        
        Returns:
            DataFrame with requested data
        """
        # Validate H3 indices
        for idx in h3_indices:
            if not re.match(r'^[0-9a-f]{15}$', idx):
                raise ValueError(f"Invalid H3 index: {idx}")
        
        # Validate columns as identifiers
        for col in columns:
            Identifier(col)  # Raises if invalid
        
        # Build path
        path = self.query_builder.build_overture_path(theme, type_name, release)
        
        # Build query
        select_cols = ', '.join(columns)
        placeholders = ', '.join(['?'] * len(h3_indices))
        
        # Note: Computing H3 for filtering
        query = f"""
        WITH h3_features AS (
            SELECT 
                {select_cols},
                h3_latlng_to_cell(
                    ST_Y(ST_Centroid(geometry)), 
                    ST_X(ST_Centroid(geometry)), 
                    ?
                ) as h3_index
            FROM read_parquet(?, hive_partitioning=1)
        )
        SELECT * FROM h3_features
        WHERE h3_index IN ({placeholders})
        """
        
        # Get resolution from first index
        resolution = int(h3_indices[0][0], 16) >> 4
        
        params = [resolution, path] + h3_indices
        
        return self.execute_query(query, params)
```

## Example Usage in Service Layer

```python
# services/h3_aggregation_service.py

from repositories.overture_repository import OvertureRepository
from typing import Dict, List, Tuple


class H3AggregationService:
    
    def __init__(self):
        self.overture_repo = OvertureRepository()
    
    def aggregate_region(
        self,
        region: str,
        resolution: int,
        aggregation_types: List[str]
    ) -> Dict[str, pd.DataFrame]:
        """
        Aggregate data for a region with specified types
        
        Args:
            region: Region name (panama, liberia, etc.)
            resolution: H3 resolution
            aggregation_types: List of aggregation types to perform
        
        Returns:
            Dict of {aggregation_type: DataFrame}
        """
        # Get bbox for region (from config or database)
        bbox = self._get_region_bbox(region)
        
        results = {}
        
        if 'buildings' in aggregation_types:
            results['buildings'] = self.overture_repo.aggregate_buildings_to_h3(
                resolution=resolution,
                bbox=bbox
            )
        
        if 'roads' in aggregation_types:
            results['roads'] = self.overture_repo.aggregate_roads_to_h3(
                resolution=resolution,
                bbox=bbox,
                road_classes=['motorway', 'trunk', 'primary']  # Example filter
            )
        
        return results
    
    def _get_region_bbox(self, region: str) -> Tuple[float, float, float, float]:
        """Get bounding box for named region"""
        regions = {
            'panama': (-83.0, 7.0, -77.0, 10.0),
            'liberia': (-11.5, 4.3, -7.4, 8.6)
        }
        if region not in regions:
            raise ValueError(f"Unknown region: {region}")
        return regions[region]
```

## Key Benefits of This Approach

1. **Centralized Security**: All validation happens in the repository layer
2. **Type Safety**: Using dataclasses for Identifier, Literal, etc.
3. **Clear Separation**: What's parameterized vs. what's validated
4. **Reusable**: Common patterns extracted into builders
5. **Testable**: Easy to unit test query building separately from execution
6. **Consistent**: Similar pattern to psycopg's sql composition

## Comparison: psycopg vs. DuckDB

```python
# psycopg style
from psycopg import sql

query = sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
    sql.Identifier('users'),
    sql.Identifier('email')
)
cursor.execute(query, ['user@example.com'])

# Your DuckDB style
from repositories.duckdb_query_builder import QueryBuilder, Identifier, QueryParam

qb = QueryBuilder()
qb.append(
    "SELECT * FROM",
    Identifier('users'),
    "WHERE",
    Identifier('email'),
    "=",
    QueryParam('user@example.com')
)
query, params = qb.build()
conn.execute(query, params)
```

This gives you the same safety guarantees at the repository level! Does this pattern match what you're looking for?