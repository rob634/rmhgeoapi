# ============================================================================
# VECTOR PROCESSING CONFIGURATION
# ============================================================================
# STATUS: Configuration - PostGIS vector ETL settings
# PURPOSE: Configure chunked vector processing, uploads, and spatial indexing
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no Azure resources)
# ============================================================================
"""
Vector Processing Pipeline Configuration.

Provides configuration for the vector ETL pipeline:
    - Pickle file storage for chunked vector processing
    - Chunk size settings for memory management
    - PostGIS upload settings
    - Spatial index creation

================================================================================
ENVIRONMENT VARIABLES (All Optional - Sensible Defaults Provided)
================================================================================

No Azure resources required. All settings have defaults suitable for most deployments.

Storage:
    VECTOR_PICKLE_CONTAINER    Default: "pickles"
                               Container for intermediate pickle files (silver zone)

    VECTOR_PICKLE_PREFIX       Default: "temp/vector_etl"
                               Blob path prefix for pickle files

Chunking:
    VECTOR_DEFAULT_CHUNK_SIZE  Default: 1000 (range: 100-100000)
                               Features per chunk for vector processing

    VECTOR_AUTO_CHUNK_SIZING   Default: "true"
                               Enable automatic chunk sizing based on feature complexity

PostGIS:
    VECTOR_TARGET_SCHEMA       Default: "geo"
                               Target PostgreSQL schema for vector tables

    VECTOR_CREATE_SPATIAL_INDEXES  Default: "true"
                                   Create spatial indexes on geometry columns

================================================================================
EXPORTS
================================================================================

    VectorConfig: Pydantic vector configuration model
"""

import os
from pydantic import BaseModel, Field

from .defaults import VectorDefaults


# ============================================================================
# VECTOR CONFIGURATION
# ============================================================================

class VectorConfig(BaseModel):
    """
    Vector processing pipeline configuration.

    Controls chunked vector processing, PostGIS uploads, and spatial indexing.

    Attributes:
        pickle_container: Container for intermediate pickle files
        pickle_prefix: Blob path prefix for pickle files
        default_chunk_size: Features per chunk (100-100000)
        auto_chunk_sizing: Enable automatic chunk sizing
        target_schema: Target PostgreSQL schema
        create_spatial_indexes: Create spatial indexes on geometry columns
    """

    # Pickle storage for chunked processing
    pickle_container: str = Field(
        default=VectorDefaults.PICKLE_CONTAINER,
        description="Container for vector ETL intermediate pickle files (silver zone)",
        examples=["pickles", "silver-temp"]
    )

    pickle_prefix: str = Field(
        default=VectorDefaults.PICKLE_PREFIX,
        description="Blob path prefix for vector ETL pickle files",
        examples=["temp/vector_etl", "intermediate/vector"]
    )

    # Chunk size settings
    default_chunk_size: int = Field(
        default=VectorDefaults.DEFAULT_CHUNK_SIZE,
        ge=100,
        le=100000,
        description="Default number of features per chunk for vector processing"
    )

    auto_chunk_sizing: bool = Field(
        default=VectorDefaults.AUTO_CHUNK_SIZING,
        description="Enable automatic chunk size calculation based on feature complexity"
    )

    # PostGIS settings
    target_schema: str = Field(
        default=VectorDefaults.TARGET_SCHEMA,
        description="Target PostgreSQL schema for vector data"
    )

    create_spatial_indexes: bool = Field(
        default=VectorDefaults.CREATE_SPATIAL_INDEXES,
        description="Automatically create spatial indexes on geometry columns"
    )

    @classmethod
    def from_environment(cls) -> "VectorConfig":
        """
        Load configuration from environment variables.

        All environment variables are optional with sensible defaults
        from VectorDefaults.

        Returns:
            VectorConfig: Configured instance
        """
        return cls(
            pickle_container=os.environ.get(
                "VECTOR_PICKLE_CONTAINER",
                VectorDefaults.PICKLE_CONTAINER
            ),
            pickle_prefix=os.environ.get(
                "VECTOR_PICKLE_PREFIX",
                VectorDefaults.PICKLE_PREFIX
            ),
            default_chunk_size=int(os.environ.get(
                "VECTOR_DEFAULT_CHUNK_SIZE",
                str(VectorDefaults.DEFAULT_CHUNK_SIZE)
            )),
            auto_chunk_sizing=os.environ.get(
                "VECTOR_AUTO_CHUNK_SIZING",
                str(VectorDefaults.AUTO_CHUNK_SIZING).lower()
            ).lower() == "true",
            target_schema=os.environ.get(
                "VECTOR_TARGET_SCHEMA",
                VectorDefaults.TARGET_SCHEMA
            ),
            create_spatial_indexes=os.environ.get(
                "VECTOR_CREATE_SPATIAL_INDEXES",
                str(VectorDefaults.CREATE_SPATIAL_INDEXES).lower()
            ).lower() == "true"
        )
