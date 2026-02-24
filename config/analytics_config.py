"""
Analytics configuration - DuckDB and columnar data processing.

This module configures DuckDB for analytical workloads including:
- Spatial analytics (DuckDB Spatial extension)
- Azure blob storage access (Azure extension)
- HTTP/S data sources (HTTPFS extension)
- GeoParquet generation and querying

ROADMAP (Under Development):
---------------------------
This configuration module will eventually encompass all analytics-related settings:
1. DuckDB connection and performance tuning
2. GeoParquet generation settings (compression, row group size, geometry encoding)
3. Columnar ETL workflows (Parquet ↔ PostGIS, Parquet ↔ COGs)
4. Data lake integration (Delta Lake, Iceberg support)
5. Analytical query optimization (memory limits, parallelism)
6. Export formats (Parquet, Arrow, ORC)

Current Status: Phase 1 - DuckDB basics
Next Phase: GeoParquet tier configuration (Gold tier exports)
"""

import os
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import AnalyticsDefaults, parse_bool


class DuckDBConnectionType(str, Enum):
    """DuckDB connection types."""
    MEMORY = "memory"
    FILE = "file"
    PERSISTENT = "persistent"


class AnalyticsConfig(BaseModel):
    """
    Analytics configuration for DuckDB and columnar data processing.

    DuckDB is used for:
    - Fast spatial analytics on large datasets
    - GeoParquet generation from PostGIS tables
    - Columnar format conversions (COGs → Parquet, PostGIS → Parquet)
    - Data lake queries (Azure blob storage, HTTP sources)

    Configuration Fields:
    ---------------------
    connection_type: Memory, file-based, or persistent connection
    database_path: File path for persistent DuckDB databases
    enable_spatial: Load DuckDB Spatial extension (ST_* functions)
    enable_azure: Load Azure extension (az:// protocol for blob storage)
    enable_httpfs: Load HTTPFS extension (https:// data sources)
    memory_limit: Max memory for DuckDB operations (e.g., "4GB", "8GB")
    threads: Number of threads for parallel query execution

    Example Usage:
    -------------
    ```python
    from config import get_config

    config = get_config()

    # Access DuckDB settings
    if config.analytics.enable_spatial:
        print(f"DuckDB Spatial enabled with {config.analytics.threads} threads")

    # Create DuckDB connection
    import duckdb
    if config.analytics.connection_type == "memory":
        conn = duckdb.connect(":memory:")
    else:
        conn = duckdb.connect(config.analytics.database_path)

    # Configure extensions
    if config.analytics.enable_azure:
        conn.execute("INSTALL azure; LOAD azure;")
    if config.analytics.enable_spatial:
        conn.execute("INSTALL spatial; LOAD spatial;")
    ```

    Future Enhancements (GeoParquet):
    --------------------------------
    - geoparquet_compression: Compression codec (snappy, gzip, zstd)
    - geoparquet_row_group_size: Rows per row group (optimizes query performance)
    - geoparquet_geometry_encoding: WKB vs native encoding
    - export_batch_size: Rows per batch for PostGIS → Parquet exports
    - gold_tier_enabled: Enable Gold tier (GeoParquet) exports
    - gold_tier_container: Azure storage container for Gold tier
    """

    # DuckDB connection settings
    connection_type: DuckDBConnectionType = Field(
        default=DuckDBConnectionType.MEMORY,
        description="DuckDB connection type: memory (fast, ephemeral) or file (persistent)"
    )

    database_path: Optional[str] = Field(
        default=None,
        description="File path for persistent DuckDB database (only used if connection_type='file')"
    )

    # DuckDB extensions
    enable_spatial: bool = Field(
        default=True,
        description="Enable DuckDB Spatial extension (ST_* functions, GeoParquet support)"
    )

    enable_azure: bool = Field(
        default=True,
        description="Enable Azure extension (az:// protocol for blob storage access)"
    )

    enable_httpfs: bool = Field(
        default=True,
        description="Enable HTTPFS extension (https:// data sources, S3 support)"
    )

    # Performance tuning
    memory_limit: str = Field(
        default="4GB",
        description="Max memory for DuckDB operations (e.g., '4GB', '8GB', '16GB')"
    )

    threads: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Number of threads for parallel query execution (1-16)"
    )

    # Validation
    def model_post_init(self, __context):
        """Validate configuration after initialization."""
        if self.connection_type in [DuckDBConnectionType.FILE, DuckDBConnectionType.PERSISTENT]:
            if not self.database_path:
                raise ValueError(
                    f"database_path required when connection_type='{self.connection_type.value}'"
                )

    @classmethod
    def from_environment(cls) -> "AnalyticsConfig":
        """
        Load analytics configuration from environment variables.

        Environment Variables:
        ---------------------
        DUCKDB_CONNECTION_TYPE: "memory", "file", or "persistent" (default: "memory")
        DUCKDB_DATABASE_PATH: Path to DuckDB file (default: None)
        DUCKDB_ENABLE_SPATIAL: "true" or "false" (default: "true")
        DUCKDB_ENABLE_AZURE: "true" or "false" (default: "true")
        DUCKDB_ENABLE_HTTPFS: "true" or "false" (default: "true")
        DUCKDB_MEMORY_LIMIT: Memory limit string (default: "4GB")
        DUCKDB_THREADS: Number of threads (default: 4)

        Returns:
            AnalyticsConfig: Configured analytics settings
        """
        return cls(
            connection_type=DuckDBConnectionType(
                os.environ.get("DUCKDB_CONNECTION_TYPE", AnalyticsDefaults.CONNECTION_TYPE)
            ),
            database_path=os.environ.get("DUCKDB_DATABASE_PATH"),
            enable_spatial=parse_bool(
                os.environ.get("DUCKDB_ENABLE_SPATIAL", str(AnalyticsDefaults.ENABLE_SPATIAL).lower())
            ),
            enable_azure=parse_bool(
                os.environ.get("DUCKDB_ENABLE_AZURE", str(AnalyticsDefaults.ENABLE_AZURE).lower())
            ),
            enable_httpfs=parse_bool(
                os.environ.get("DUCKDB_ENABLE_HTTPFS", str(AnalyticsDefaults.ENABLE_HTTPFS).lower())
            ),
            memory_limit=os.environ.get("DUCKDB_MEMORY_LIMIT", AnalyticsDefaults.MEMORY_LIMIT),
            threads=int(os.environ.get("DUCKDB_THREADS", str(AnalyticsDefaults.THREADS)))
        )

    def debug_dict(self) -> dict:
        """
        Return debug-friendly configuration dictionary.

        Returns:
            dict: Configuration with sensitive fields masked
        """
        return {
            "connection_type": self.connection_type.value,
            "database_path": self.database_path if self.database_path else "<memory>",
            "enable_spatial": self.enable_spatial,
            "enable_azure": self.enable_azure,
            "enable_httpfs": self.enable_httpfs,
            "memory_limit": self.memory_limit,
            "threads": self.threads
        }


# Export
__all__ = ["AnalyticsConfig", "DuckDBConnectionType"]
