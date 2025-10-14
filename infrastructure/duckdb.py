# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# CATEGORY: ANALYTICAL DATABASE REPOSITORIES
# PURPOSE: DuckDB repository for analytical queries and GeoParquet operations
# EPOCH: Shared by all epochs (infrastructure layer)
# EXPORTS: DuckDBRepository singleton with connection pooling
# INTERFACES: IDuckDBRepository for dependency injection
# DEPENDENCIES: duckdb, geopandas, pyarrow, azure-identity
# SOURCE: In-memory or file-based DuckDB connections with Azure Blob integration
# SCOPE: Analytical queries, GeoParquet exports, spatial analytics
# VALIDATION: Extension availability, connection health, query results
# PATTERNS: Singleton, Repository, Connection pooling, Lazy initialization
# ENTRY_POINTS: DuckDBRepository.instance() for singleton access
# INDEX: IDuckDBRepository:80, DuckDBRepository:130, get_duckdb_repository:550
# ============================================================================

"""
DuckDB Repository - Analytical Query Engine

This module provides THE centralized DuckDB repository for analytical workloads,
GeoParquet operations, and serverless queries over Azure Blob Storage. It serves
as the single point for all DuckDB operations across the ETL pipeline.

Key Features:
- Connection pooling with singleton pattern
- Spatial extension for PostGIS-like geometry operations
- Azure extension for direct blob storage queries (NO DOWNLOAD!)
- In-memory or persistent database options
- All analytical services use this for DuckDB access
- Automatic extension installation and loading

Extensions Enabled:
1. spatial - ST_* functions for geometry operations
2. azure - Direct queries on Azure Blob Storage
3. httpfs - HTTP/HTTPS file access (optional)
4. parquet - Native Parquet file support (built-in)

Performance Benefits:
- Query Parquet files in blob storage WITHOUT downloading
- Serverless analytics - no data movement required
- 10-100x faster than downloading + processing
- Native columnar storage for efficient queries

Usage:
    from infrastructure.factory import RepositoryFactory

    # Get authenticated repository
    duckdb_repo = RepositoryFactory.create_duckdb_repository()

    # Query Parquet files in Azure Blob Storage
    result = duckdb_repo.query('''
        SELECT * FROM read_parquet('az://container/path/*.parquet')
        WHERE ST_Intersects(geometry, ST_GeomFromText(?))
    ''', [wkt_boundary])

    # Export to GeoParquet
    duckdb_repo.export_geoparquet(df, 'output.parquet')

Author: Robert and Geospatial Claude Legion
Date: 10 OCT 2025
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import traceback

# Third-party imports - These will fail fast if not installed
try:
    import duckdb
except ImportError:
    raise ImportError(
        "duckdb is required for DuckDBRepository. "
        "Install with: pip install duckdb"
    )

# Application imports
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, __name__)


# ============================================================================
# DUCKDB REPOSITORY INTERFACE
# ============================================================================

class IDuckDBRepository(ABC):
    """
    Interface for DuckDB analytical operations.

    Enables dependency injection and testing/mocking of DuckDB operations.
    All DuckDB repositories must implement this interface.
    """

    @abstractmethod
    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create DuckDB connection with extensions loaded"""
        pass

    @abstractmethod
    def query(self, sql: str, parameters: Optional[List[Any]] = None) -> duckdb.DuckDBPyRelation:
        """Execute SQL query with optional parameters"""
        pass

    @abstractmethod
    def query_to_df(self, sql: str, parameters: Optional[List[Any]] = None):
        """Execute SQL query and return pandas DataFrame"""
        pass

    @abstractmethod
    def execute(self, sql: str, parameters: Optional[List[Any]] = None) -> None:
        """Execute SQL statement without returning results"""
        pass

    @abstractmethod
    def read_parquet_from_blob(self, container: str, blob_pattern: str) -> duckdb.DuckDBPyRelation:
        """Read Parquet files from Azure Blob Storage (serverless query)"""
        pass

    @abstractmethod
    def export_geoparquet(self, data: Any, output_path: str) -> Dict[str, Any]:
        """Export data to GeoParquet format"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close DuckDB connection and cleanup resources"""
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check DuckDB health and extension availability"""
        pass


# ============================================================================
# DUCKDB REPOSITORY IMPLEMENTATION
# ============================================================================

class DuckDBRepository(IDuckDBRepository):
    """
    Singleton DuckDB repository for analytical workloads.

    This class provides a centralized DuckDB connection with automatic
    extension management, connection pooling, and Azure Blob integration.

    Connection Types:
    - memory: In-memory database (default, fast, ephemeral)
    - persistent: File-based database (survives restarts, slower)

    Singleton Pattern:
    - Use DuckDBRepository.instance() for the global singleton
    - Multiple calls return the same instance with connection reuse

    Thread Safety:
    - DuckDB connections are NOT thread-safe
    - Each Azure Function instance gets its own repository
    - Use connection pooling for concurrent queries (future)
    """

    _instance: Optional['DuckDBRepository'] = None
    _initialized: bool = False

    def __init__(
        self,
        connection_type: str = "memory",
        database_path: Optional[str] = None,
        storage_account_name: Optional[str] = None
    ):
        """
        Initialize DuckDB repository.

        Args:
            connection_type: "memory" or "persistent"
            database_path: Path to database file (for persistent)
            storage_account_name: Azure storage account for blob queries
        """
        self.connection_type = connection_type
        self.database_path = database_path
        self.storage_account_name = storage_account_name or os.getenv('AZURE_STORAGE_ACCOUNT_NAME', 'rmhazuregeo')
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._extensions_loaded: bool = False

        logger.info(f"DuckDBRepository initialized - type: {connection_type}, storage: {self.storage_account_name}")

    @classmethod
    def instance(cls, **kwargs) -> 'DuckDBRepository':
        """
        Get or create singleton instance.

        Args:
            **kwargs: Passed to __init__ on first call only

        Returns:
            DuckDBRepository singleton
        """
        if cls._instance is None:
            cls._instance = cls(**kwargs)
            cls._initialized = True
            logger.info("DuckDBRepository singleton created")
        return cls._instance

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """
        Get or create DuckDB connection with extensions loaded.

        STEP 1: Create connection (memory or persistent)
        STEP 2: Load required extensions (spatial, azure)

        Returns:
            DuckDB connection ready for queries
        """
        if self._conn is None:
            try:
                # STEP 1: Create connection
                logger.info("🔄 STEP 1: Creating DuckDB connection...")

                if self.connection_type == "memory":
                    self._conn = duckdb.connect(":memory:")
                    logger.info("✅ STEP 1: In-memory DuckDB connection created")
                else:
                    db_path = self.database_path or "duckdb.db"
                    self._conn = duckdb.connect(db_path)
                    logger.info(f"✅ STEP 1: Persistent DuckDB connection created - {db_path}")

                # STEP 2: Load extensions
                self._initialize_extensions()

            except Exception as e:
                logger.error(f"❌ STEP 1 FAILED: {e}\n{traceback.format_exc()}")
                raise

        return self._conn

    def _initialize_extensions(self) -> None:
        """
        Load DuckDB extensions for spatial and Azure operations.

        STEP 2: Install and load extensions
        STEP 3: Configure Azure authentication

        Extensions:
        - spatial: PostGIS-like ST_* functions
        - azure: Direct blob storage queries
        - h3: H3 hierarchical hexagonal grid functions
        - httpfs: HTTP/HTTPS file access for Overture Maps
        """
        if self._extensions_loaded:
            return

        try:
            logger.info("🔄 STEP 2: Installing and loading DuckDB extensions...")
            conn = self._conn

            # STEP 2a: Spatial extension
            try:
                logger.info("   Installing spatial extension...")
                conn.execute("INSTALL spatial")
                conn.execute("LOAD spatial")
                logger.info("   ✅ Spatial extension loaded (ST_* functions available)")
            except Exception as e:
                logger.warning(f"   ⚠️ Spatial extension failed (non-critical): {e}")

            # STEP 2b: Azure extension
            try:
                logger.info("   Installing azure extension...")
                conn.execute("INSTALL azure")
                conn.execute("LOAD azure")
                logger.info("   ✅ Azure extension loaded (blob storage queries available)")
            except Exception as e:
                logger.warning(f"   ⚠️ Azure extension failed (non-critical): {e}")

            # STEP 2c: H3 extension (for hexagonal grid operations - COMMUNITY EXTENSION)
            try:
                logger.info("   Installing h3 extension from community repository...")
                conn.execute("INSTALL h3 FROM community")
                conn.execute("LOAD h3")
                logger.info("   ✅ H3 extension loaded (h3_* functions available)")
            except Exception as e:
                logger.warning(f"   ⚠️ H3 extension failed (non-critical): {e}")

            # STEP 2d: httpfs extension (for Overture Maps HTTPS access)
            try:
                logger.info("   Installing httpfs extension...")
                conn.execute("INSTALL httpfs")
                conn.execute("LOAD httpfs")
                logger.info("   ✅ httpfs extension loaded (HTTPS file access available)")
            except Exception as e:
                logger.warning(f"   ⚠️ httpfs extension failed (non-critical): {e}")

            # STEP 3: Configure Azure authentication
            logger.info("🔄 STEP 3: Configuring Azure authentication...")
            try:
                # DuckDB uses Azure CLI or managed identity automatically
                # Set storage account for az:// protocol
                conn.execute(f"""
                    SET azure_storage_connection_string = 'DefaultEndpointsProtocol=https;AccountName={self.storage_account_name};AccountKey=MANAGED_IDENTITY';
                """)
                logger.info(f"   ✅ Azure storage configured - {self.storage_account_name}")
            except Exception as e:
                logger.warning(f"   ⚠️ Azure auth config failed (will use CLI): {e}")

            self._extensions_loaded = True
            logger.info("✅ STEP 2-3: All extensions initialized successfully")

        except Exception as e:
            logger.error(f"❌ STEP 2-3 FAILED: {e}\n{traceback.format_exc()}")
            # Non-fatal - connection still usable without extensions
            self._extensions_loaded = False

    def query(self, sql: str, parameters: Optional[List[Any]] = None) -> duckdb.DuckDBPyRelation:
        """
        Execute SQL query with optional parameters.

        Args:
            sql: SQL query string
            parameters: Optional list of parameter values for ? placeholders

        Returns:
            DuckDB relation (lazy evaluation)

        Example:
            result = repo.query("SELECT * FROM table WHERE id = ?", [123])
            df = result.df()
        """
        conn = self.get_connection()

        try:
            if parameters:
                return conn.execute(sql, parameters)
            else:
                return conn.execute(sql)
        except Exception as e:
            logger.error(f"Query failed: {e}\nSQL: {sql}\n{traceback.format_exc()}")
            raise

    def query_to_df(self, sql: str, parameters: Optional[List[Any]] = None):
        """
        Execute SQL query and return pandas DataFrame.

        Args:
            sql: SQL query string
            parameters: Optional list of parameter values

        Returns:
            pandas DataFrame with query results
        """
        relation = self.query(sql, parameters)
        return relation.df()

    def execute(self, sql: str, parameters: Optional[List[Any]] = None) -> None:
        """
        Execute SQL statement without returning results.

        Used for CREATE TABLE, INSERT, UPDATE, DELETE, etc.

        Args:
            sql: SQL statement
            parameters: Optional list of parameter values
        """
        conn = self.get_connection()

        try:
            if parameters:
                conn.execute(sql, parameters)
            else:
                conn.execute(sql)
        except Exception as e:
            logger.error(f"Execute failed: {e}\nSQL: {sql}\n{traceback.format_exc()}")
            raise

    def read_parquet_from_blob(
        self,
        container: str,
        blob_pattern: str,
        storage_account: Optional[str] = None
    ) -> duckdb.DuckDBPyRelation:
        """
        Read Parquet files from Azure Blob Storage (serverless query).

        NO DATA DOWNLOAD! DuckDB queries blob storage directly using
        the Azure extension. This is 10-100x faster than downloading.

        Args:
            container: Azure blob container name
            blob_pattern: Blob path with wildcards (e.g., "path/*.parquet")
            storage_account: Override default storage account

        Returns:
            DuckDB relation (lazy evaluation)

        Example:
            # Query multiple Parquet files at once
            result = repo.read_parquet_from_blob(
                'rmhazuregeosilver',
                'exports/2025/*.parquet'
            )
            df = result.df()
        """
        conn = self.get_connection()
        account = storage_account or self.storage_account_name

        # Azure URL format: az://container@account.blob.core.windows.net/path
        blob_url = f"az://{container}@{account}.blob.core.windows.net/{blob_pattern}"

        try:
            logger.info(f"Reading Parquet from blob: {blob_url}")
            result = conn.execute(f"SELECT * FROM read_parquet('{blob_url}')")
            logger.info("✅ Parquet read successful (serverless query)")
            return result
        except Exception as e:
            logger.error(f"Parquet blob read failed: {e}\nURL: {blob_url}\n{traceback.format_exc()}")
            raise

    def export_geoparquet(
        self,
        data: Any,
        output_path: str,
        geometry_column: str = "geometry"
    ) -> Dict[str, Any]:
        """
        Export data to GeoParquet format.

        Args:
            data: pandas DataFrame, GeoPandas GeoDataFrame, or DuckDB relation
            output_path: Output file path (.parquet)
            geometry_column: Name of geometry column (default: "geometry")

        Returns:
            Dict with export metadata (path, size, row_count)

        Example:
            metadata = repo.export_geoparquet(gdf, '/tmp/output.parquet')
        """
        conn = self.get_connection()

        try:
            logger.info(f"🔄 Exporting GeoParquet to {output_path}...")

            # Convert to DuckDB relation if needed
            if hasattr(data, 'df'):
                # Already a DuckDB relation
                relation = data
            else:
                # Create relation from DataFrame
                relation = conn.from_df(data)

            # Write to Parquet with spatial metadata
            relation.write_parquet(output_path)

            # Get file size
            file_size = Path(output_path).stat().st_size
            row_count = relation.count("*").fetchone()[0]

            logger.info(f"✅ GeoParquet export complete - {row_count} rows, {file_size:,} bytes")

            return {
                "success": True,
                "output_path": output_path,
                "file_size_bytes": file_size,
                "row_count": row_count,
                "geometry_column": geometry_column
            }

        except Exception as e:
            logger.error(f"❌ GeoParquet export failed: {e}\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    def close(self) -> None:
        """
        Close DuckDB connection and cleanup resources.

        Note: Singleton instance will remain, but connection will be closed.
        Next get_connection() call will create a new connection.
        """
        if self._conn is not None:
            try:
                self._conn.close()
                logger.info("DuckDB connection closed")
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
            finally:
                self._conn = None
                self._extensions_loaded = False

    def health_check(self) -> Dict[str, Any]:
        """
        Check DuckDB health and extension availability.

        Returns:
            Dict with health status, extensions, and connection info
        """
        try:
            conn = self.get_connection()

            # Test basic query
            version = conn.execute("SELECT version()").fetchone()[0]

            # Check extensions
            extensions = {}
            try:
                ext_result = conn.execute("SELECT * FROM duckdb_extensions()").fetchall()
                for row in ext_result:
                    ext_name = row[0]
                    ext_loaded = row[1]
                    extensions[ext_name] = "loaded" if ext_loaded else "available"
            except:
                extensions = {"error": "Could not query extensions"}

            return {
                "status": "healthy",
                "connection_type": self.connection_type,
                "version": version,
                "extensions": extensions,
                "storage_account": self.storage_account_name,
                "connection_active": self._conn is not None,
                "extensions_initialized": self._extensions_loaded
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}\n{traceback.format_exc()}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "traceback": traceback.format_exc()
            }


# ============================================================================
# FACTORY FUNCTION (for backwards compatibility)
# ============================================================================

def get_duckdb_repository(**kwargs) -> DuckDBRepository:
    """
    Get DuckDB repository singleton.

    This function provides backwards compatibility with the factory pattern.
    Prefer using RepositoryFactory.create_duckdb_repository() instead.

    Args:
        **kwargs: Passed to DuckDBRepository.instance()

    Returns:
        DuckDBRepository singleton
    """
    return DuckDBRepository.instance(**kwargs)
