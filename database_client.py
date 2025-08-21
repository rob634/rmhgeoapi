"""
PostgreSQL database client using psycopg3 for STAC and geospatial operations.
Clean, modern implementation based on ancient_code/olddb.py patterns.
"""

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from typing import Optional, Dict, Any, List, Generator, Union
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import json

from config import Config
from logger_setup import create_buffered_logger


class DatabaseClient:
    """
    PostgreSQL database client using psycopg3.
    Provides connection management, query execution, and table operations.
    """
    
    def __init__(
        self,
        host: str = None,
        database: str = None,
        user: str = None,
        password: str = None,
        port: int = None,
        schema: str = None
    ):
        """Initialize database client with connection parameters."""
        self.logger = create_buffered_logger(
            name=f"{__name__}.DatabaseClient",
            capacity=100,
            flush_level=logging.ERROR
        )
        
        # Use provided params or fall back to config
        self.host = host or Config.POSTGIS_HOST
        self.database = database or Config.POSTGIS_DATABASE
        self.user = user or Config.POSTGIS_USER
        self.password = password or Config.POSTGIS_PASSWORD
        self.port = port or Config.POSTGIS_PORT or 5432
        self.schema = schema or Config.POSTGIS_SCHEMA or 'geo'
        
        # Connection string for psycopg3
        self.conn_string = self._build_connection_string()
        
        self.logger.info(f"Database client initialized for {self.host}/{self.database}")
    
    def _build_connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return f"host={self.host} port={self.port} dbname={self.database} user={self.user} password={self.password}"
    
    @contextmanager
    def get_connection(self, autocommit: bool = False):
        """
        Context manager for database connections.
        
        Args:
            autocommit: Whether to autocommit transactions
            
        Yields:
            psycopg.Connection object
        """
        conn = None
        try:
            conn = psycopg.connect(self.conn_string)
            if autocommit:
                conn.autocommit = True
            yield conn
        except psycopg.Error as e:
            self.logger.error(f"Database connection error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                if not autocommit:
                    conn.commit()
                conn.close()
    
    def test_connection(self) -> bool:
        """Test database connection and PostGIS availability."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Test basic connection
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()[0]
                    self.logger.info(f"Connected to: {version}")
                    
                    # Test PostGIS
                    cursor.execute("SELECT PostGIS_version();")
                    postgis_version = cursor.fetchone()[0]
                    self.logger.info(f"PostGIS version: {postgis_version}")
                    
            return True
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
    
    def execute(
        self,
        query: Union[str, sql.Composed],
        params: Optional[Union[List, Dict]] = None,
        fetch: bool = True
    ) -> Optional[List]:
        """
        Execute a database query.
        
        Args:
            query: SQL query string or psycopg3 sql.Composed object
            params: Query parameters
            fetch: Whether to fetch results (for SELECT queries)
            
        Returns:
            Query results if fetch=True, None otherwise
        """
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row if fetch else None) as cursor:
                self.logger.debug(f"Executing query: {str(query)[:200]}...")
                cursor.execute(query, params)
                
                if fetch:
                    results = cursor.fetchall()
                    self.logger.debug(f"Fetched {len(results)} rows")
                    return results
                else:
                    self.logger.debug(f"Affected {cursor.rowcount} rows")
                    return None
    
    # Schema and Table Methods
    
    def schema_exists(self, schema_name: str = None) -> bool:
        """Check if schema exists."""
        schema_name = schema_name or self.schema
        query = sql.SQL("""
            SELECT EXISTS(
                SELECT 1 FROM pg_namespace WHERE nspname = %s
            );
        """)
        result = self.execute(query, [schema_name])
        return result[0]['exists'] if result else False
    
    def create_schema(self, schema_name: str = None) -> bool:
        """Create schema if it doesn't exist."""
        schema_name = schema_name or self.schema
        if not self.schema_exists(schema_name):
            query = sql.SQL("CREATE SCHEMA IF NOT EXISTS {};").format(
                sql.Identifier(schema_name)
            )
            self.execute(query, fetch=False)
            self.logger.info(f"Created schema: {schema_name}")
            return True
        self.logger.debug(f"Schema already exists: {schema_name}")
        return False
    
    def table_exists(self, table_name: str, schema_name: str = None) -> bool:
        """Check if table exists in schema."""
        schema_name = schema_name or self.schema
        query = """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            );
        """
        result = self.execute(query, [schema_name, table_name])
        return result[0]['exists'] if result else False
    
    def create_table(
        self,
        table_name: str,
        columns: Dict[str, str],
        schema_name: str = None,
        primary_key: Optional[str] = None
    ) -> bool:
        """
        Create a table with specified columns.
        
        Args:
            table_name: Name of the table
            columns: Dictionary of column_name: data_type
            schema_name: Schema name (defaults to self.schema)
            primary_key: Column name for primary key
            
        Returns:
            True if table was created
        """
        schema_name = schema_name or self.schema
        
        # Build column definitions
        column_defs = []
        for col_name, col_type in columns.items():
            col_def = f"{col_name} {col_type}"
            if col_name == primary_key:
                col_def += " PRIMARY KEY"
            column_defs.append(sql.SQL(col_def))
        
        query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {}.{} ({});
        """).format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(', ').join(column_defs)
        )
        
        self.execute(query, fetch=False)
        self.logger.info(f"Created table: {schema_name}.{table_name}")
        return True
    
    def get_table_columns(
        self,
        table_name: str,
        schema_name: str = None
    ) -> Dict[str, Dict]:
        """Get column information for a table."""
        schema_name = schema_name or self.schema
        query = """
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                numeric_precision,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """
        
        results = self.execute(query, [schema_name, table_name])
        return {row['column_name']: row for row in results} if results else {}
    
    # Data Operations
    
    def insert(
        self,
        table_name: str,
        data: Union[Dict, List[Dict]],
        schema_name: str = None,
        returning: Optional[str] = None
    ) -> Optional[List]:
        """
        Insert data into table.
        
        Args:
            table_name: Target table
            data: Dictionary or list of dictionaries to insert
            schema_name: Schema name
            returning: Column to return after insert
            
        Returns:
            Returned values if returning is specified
        """
        schema_name = schema_name or self.schema
        
        # Ensure data is a list
        if isinstance(data, dict):
            data = [data]
        
        if not data:
            return None
        
        # Get column names from first record
        columns = list(data[0].keys())
        
        # Build INSERT query
        query = sql.SQL("""
            INSERT INTO {}.{} ({})
            VALUES ({})
            {}
        """).format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(', ').join([sql.Identifier(col) for col in columns]),
            sql.SQL(', ').join([sql.Placeholder()] * len(columns)),
            sql.SQL(f"RETURNING {returning}") if returning else sql.SQL("")
        )
        
        # Execute for each row
        results = []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for row in data:
                    values = [row.get(col) for col in columns]
                    cursor.execute(query, values)
                    if returning:
                        results.append(cursor.fetchone()[0])
        
        self.logger.info(f"Inserted {len(data)} rows into {schema_name}.{table_name}")
        return results if returning else None
    
    def update(
        self,
        table_name: str,
        data: Dict,
        where: Dict,
        schema_name: str = None
    ) -> int:
        """
        Update rows in table.
        
        Args:
            table_name: Target table
            data: Dictionary of column: value to update
            where: Dictionary of column: value for WHERE clause
            schema_name: Schema name
            
        Returns:
            Number of rows updated
        """
        schema_name = schema_name or self.schema
        
        # Build SET clause
        set_clause = sql.SQL(', ').join([
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder())
            for k in data.keys()
        ])
        
        # Build WHERE clause
        where_clause = sql.SQL(' AND ').join([
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder())
            for k in where.keys()
        ])
        
        query = sql.SQL("""
            UPDATE {}.{}
            SET {}
            WHERE {}
        """).format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            set_clause,
            where_clause
        )
        
        # Combine values
        values = list(data.values()) + list(where.values())
        
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, values)
                return cursor.rowcount
    
    def select(
        self,
        table_name: str,
        columns: Optional[List[str]] = None,
        where: Optional[Dict] = None,
        schema_name: str = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Select rows from table.
        
        Args:
            table_name: Source table
            columns: List of columns to select (None for all)
            where: Dictionary of column: value for WHERE clause
            schema_name: Schema name
            limit: Maximum rows to return
            
        Returns:
            List of dictionaries
        """
        schema_name = schema_name or self.schema
        
        # Build SELECT clause
        if columns:
            select_clause = sql.SQL(', ').join([sql.Identifier(col) for col in columns])
        else:
            select_clause = sql.SQL('*')
        
        # Build WHERE clause
        if where:
            where_clause = sql.SQL(' WHERE ') + sql.SQL(' AND ').join([
                sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder())
                for k in where.keys()
            ])
            values = list(where.values())
        else:
            where_clause = sql.SQL('')
            values = []
        
        # Build LIMIT clause
        limit_clause = sql.SQL(f' LIMIT {limit}') if limit else sql.SQL('')
        
        query = sql.SQL("""
            SELECT {} FROM {}.{}{}{}
        """).format(
            select_clause,
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            where_clause,
            limit_clause
        )
        
        return self.execute(query, values)
    
    def delete(
        self,
        table_name: str,
        where: Dict,
        schema_name: str = None
    ) -> int:
        """
        Delete rows from table.
        
        Args:
            table_name: Target table
            where: Dictionary of column: value for WHERE clause
            schema_name: Schema name
            
        Returns:
            Number of rows deleted
        """
        schema_name = schema_name or self.schema
        
        # Build WHERE clause
        where_clause = sql.SQL(' AND ').join([
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder())
            for k in where.keys()
        ])
        
        query = sql.SQL("""
            DELETE FROM {}.{}
            WHERE {}
        """).format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            where_clause
        )
        
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, list(where.values()))
                return cursor.rowcount
    
    # Batch Operations
    
    def batch_insert(
        self,
        table_name: str,
        data: List[Dict],
        schema_name: str = None,
        batch_size: int = 1000
    ) -> int:
        """
        Insert data in batches for better performance.
        
        Args:
            table_name: Target table
            data: List of dictionaries to insert
            schema_name: Schema name
            batch_size: Number of rows per batch
            
        Returns:
            Total rows inserted
        """
        schema_name = schema_name or self.schema
        total_inserted = 0
        
        if not data:
            return 0
        
        columns = list(data[0].keys())
        
        # Prepare the INSERT query with multiple value placeholders
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for i in range(0, len(data), batch_size):
                    batch = data[i:i + batch_size]
                    
                    # Build query for this batch
                    values_template = sql.SQL("({})").format(
                        sql.SQL(", ").join([sql.Placeholder()] * len(columns))
                    )
                    
                    query = sql.SQL("""
                        INSERT INTO {}.{} ({})
                        VALUES {}
                    """).format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                        sql.SQL(', ').join([sql.Identifier(col) for col in columns]),
                        sql.SQL(', ').join([values_template] * len(batch))
                    )
                    
                    # Flatten values
                    values = []
                    for row in batch:
                        values.extend([row.get(col) for col in columns])
                    
                    cursor.execute(query, values)
                    total_inserted += cursor.rowcount
                    
                    self.logger.debug(f"Inserted batch of {len(batch)} rows")
        
        self.logger.info(f"Batch inserted {total_inserted} rows into {schema_name}.{table_name}")
        return total_inserted
    
    # Geometry Operations (PostGIS)
    
    def insert_geometry(
        self,
        table_name: str,
        data: Dict,
        geom_column: str = 'geometry',
        geom_format: str = 'wkt',
        srid: int = 4326,
        schema_name: str = None
    ) -> Optional[Any]:
        """
        Insert data with geometry column.
        
        Args:
            table_name: Target table
            data: Dictionary including geometry data
            geom_column: Name of geometry column
            geom_format: Format of geometry ('wkt', 'geojson', 'wkb')
            srid: Spatial reference ID
            schema_name: Schema name
            
        Returns:
            Inserted row ID if returning is set
        """
        schema_name = schema_name or self.schema
        
        # Separate geometry from other columns
        geom_data = data.pop(geom_column, None)
        if not geom_data:
            raise ValueError(f"No geometry data found in column {geom_column}")
        
        # Build column lists
        columns = list(data.keys()) + [geom_column]
        placeholders = [sql.Placeholder()] * len(data)
        
        # Add geometry placeholder based on format
        if geom_format == 'wkt':
            geom_placeholder = sql.SQL("ST_GeomFromText(%s, %s)")
            geom_values = [geom_data, srid]
        elif geom_format == 'geojson':
            geom_placeholder = sql.SQL("ST_GeomFromGeoJSON(%s)")
            geom_values = [json.dumps(geom_data) if isinstance(geom_data, dict) else geom_data]
        elif geom_format == 'wkb':
            geom_placeholder = sql.SQL("ST_GeomFromWKB(%s, %s)")
            geom_values = [geom_data, srid]
        else:
            raise ValueError(f"Unsupported geometry format: {geom_format}")
        
        # Build query
        query = sql.SQL("""
            INSERT INTO {}.{} ({})
            VALUES ({}, {})
        """).format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(', ').join([sql.Identifier(col) for col in columns]),
            sql.SQL(', ').join(placeholders),
            geom_placeholder
        )
        
        # Execute
        values = list(data.values()) + geom_values
        self.execute(query, values, fetch=False)
        self.logger.debug(f"Inserted geometry data into {schema_name}.{table_name}")
        return True
    
    def create_geometry_index(
        self,
        table_name: str,
        geom_column: str = 'geometry',
        schema_name: str = None
    ) -> bool:
        """Create spatial index on geometry column."""
        schema_name = schema_name or self.schema
        index_name = f"{table_name}_{geom_column}_idx"
        
        query = sql.SQL("""
            CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST ({});
        """).format(
            sql.Identifier(index_name),
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.Identifier(geom_column)
        )
        
        self.execute(query, fetch=False)
        self.logger.info(f"Created spatial index on {schema_name}.{table_name}.{geom_column}")
        return True


class STACDatabase(DatabaseClient):
    """
    Specialized database client for STAC operations.
    Extends DatabaseClient with STAC-specific methods.
    """
    
    def __init__(self, **kwargs):
        """Initialize STAC database client."""
        super().__init__(**kwargs)
        self.collections_table = 'collections'
        self.items_table = 'items'
    
    def setup_stac_tables(self) -> bool:
        """Create STAC collections and items tables with PostGIS support."""
        # Ensure schema exists
        self.create_schema(self.schema)
        
        # Create collections table
        collections_columns = {
            'id': 'VARCHAR(255) PRIMARY KEY',
            'title': 'VARCHAR(255)',
            'description': 'TEXT',
            'keywords': 'TEXT[]',
            'license': 'VARCHAR(255)',
            'providers': 'JSONB',
            'extent': 'JSONB',
            'summaries': 'JSONB',
            'links': 'JSONB',
            'assets': 'JSONB',
            'created_at': 'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP',
            'updated_at': 'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP'
        }
        self.create_table(self.collections_table, collections_columns, self.schema)
        
        # Create items table
        items_columns = {
            'id': 'VARCHAR(255) PRIMARY KEY',
            'collection_id': 'VARCHAR(255) REFERENCES ' + f'{self.schema}.{self.collections_table}(id)',
            'geometry': 'GEOMETRY(Geometry, 4326)',
            'bbox': 'GEOMETRY(Polygon, 4326)',
            'properties': 'JSONB',
            'assets': 'JSONB',
            'links': 'JSONB',
            'stac_version': 'VARCHAR(20)',
            'created_at': 'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP',
            'updated_at': 'TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP'
        }
        self.create_table(self.items_table, items_columns, self.schema)
        
        # Create spatial indexes
        self.create_geometry_index(self.items_table, 'geometry', self.schema)
        self.create_geometry_index(self.items_table, 'bbox', self.schema)
        
        # Create indexes on common query fields
        self.execute(sql.SQL("""
            CREATE INDEX IF NOT EXISTS items_collection_idx 
            ON {}.{} (collection_id);
        """).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.items_table)
        ), fetch=False)
        
        self.logger.info(f"STAC tables created in schema {self.schema}")
        return True
    
    def insert_stac_item(
        self,
        item_id: str,
        collection_id: str,
        geometry: Dict,
        bbox: List[float],
        properties: Dict,
        assets: Dict = None,
        links: List = None,
        stac_version: str = "1.0.0"
    ) -> bool:
        """
        Insert a STAC item into the database.
        
        Args:
            item_id: Unique item identifier
            collection_id: Collection this item belongs to
            geometry: GeoJSON geometry
            bbox: Bounding box [minx, miny, maxx, maxy]
            properties: Item properties
            assets: Asset definitions
            links: Item links
            stac_version: STAC version
            
        Returns:
            True if successful
        """
        # Create bbox polygon from array
        bbox_wkt = f"POLYGON(({bbox[0]} {bbox[1]}, {bbox[2]} {bbox[1]}, {bbox[2]} {bbox[3]}, {bbox[0]} {bbox[3]}, {bbox[0]} {bbox[1]}))"
        
        query = sql.SQL("""
            INSERT INTO {}.{} 
            (id, collection_id, geometry, bbox, properties, assets, links, stac_version)
            VALUES (%s, %s, ST_GeomFromGeoJSON(%s), ST_GeomFromText(%s, 4326), %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                geometry = EXCLUDED.geometry,
                bbox = EXCLUDED.bbox,
                properties = EXCLUDED.properties,
                assets = EXCLUDED.assets,
                links = EXCLUDED.links,
                updated_at = CURRENT_TIMESTAMP;
        """).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.items_table)
        )
        
        values = [
            item_id,
            collection_id,
            json.dumps(geometry),
            bbox_wkt,
            json.dumps(properties),
            json.dumps(assets) if assets else None,
            json.dumps(links) if links else None,
            stac_version
        ]
        
        self.execute(query, values, fetch=False)
        self.logger.info(f"Inserted STAC item: {item_id}")
        return True
    
    def search_items_by_bbox(
        self,
        bbox: List[float],
        collection_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Search STAC items by bounding box.
        
        Args:
            bbox: Bounding box [minx, miny, maxx, maxy]
            collection_id: Optional collection filter
            limit: Maximum results
            
        Returns:
            List of STAC items
        """
        bbox_wkt = f"POLYGON(({bbox[0]} {bbox[1]}, {bbox[2]} {bbox[1]}, {bbox[2]} {bbox[3]}, {bbox[0]} {bbox[3]}, {bbox[0]} {bbox[1]}))"
        
        query = sql.SQL("""
            SELECT 
                id,
                collection_id,
                ST_AsGeoJSON(geometry)::json as geometry,
                ST_AsGeoJSON(bbox)::json as bbox,
                properties,
                assets,
                links,
                stac_version
            FROM {}.{}
            WHERE ST_Intersects(geometry, ST_GeomFromText(%s, 4326))
            {}
            LIMIT %s;
        """).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.items_table),
            sql.SQL("AND collection_id = %s" if collection_id else "")
        )
        
        values = [bbox_wkt]
        if collection_id:
            values.append(collection_id)
        values.append(limit)
        
        return self.execute(query, values)


# Factory function
def create_database_client(stac: bool = False) -> Union[DatabaseClient, STACDatabase]:
    """
    Create appropriate database client.
    
    Args:
        stac: Whether to create STAC-specific client
        
    Returns:
        DatabaseClient or STACDatabase instance
    """
    if stac:
        return STACDatabase()
    return DatabaseClient()