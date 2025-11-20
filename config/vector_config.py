# ============================================================================
# CLAUDE CONTEXT - VECTOR CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: Vector processing pipeline configuration
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: VectorConfig
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: VectorConfig
# DEPENDENCIES: pydantic, os
# SOURCE: Environment variables (VECTOR_*)
# SCOPE: Vector-specific configuration
# VALIDATION: Pydantic v2 validation
# PATTERNS: Value objects, factory methods
# ENTRY_POINTS: from config import VectorConfig
# INDEX: VectorConfig:35
# ============================================================================

"""
Vector Processing Pipeline Configuration

Provides configuration for:
- Pickle file storage for chunked vector processing
- Chunk size settings
- PostGIS upload settings
- Spatial index creation

This module was extracted from config.py (lines 548-558) as part of the
god object refactoring (20 NOV 2025).
"""

import os
from pydantic import BaseModel, Field


# ============================================================================
# VECTOR CONFIGURATION
# ============================================================================

class VectorConfig(BaseModel):
    """
    Vector processing pipeline configuration.

    Controls chunked vector processing, PostGIS uploads, and spatial indexing.
    """

    # Pickle storage for chunked processing
    pickle_container: str = Field(
        default="rmhazuregeotemp",
        description="Container for vector ETL intermediate pickle files",
        examples=["rmhazuregeotemp", "silver"]
    )

    pickle_prefix: str = Field(
        default="temp/vector_etl",
        description="Blob path prefix for vector ETL pickle files",
        examples=["temp/vector_etl", "intermediate/vector"]
    )

    # Chunk size settings
    default_chunk_size: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="Default number of features per chunk for vector processing"
    )

    auto_chunk_sizing: bool = Field(
        default=True,
        description="Enable automatic chunk size calculation based on feature complexity"
    )

    # PostGIS settings
    target_schema: str = Field(
        default="geo",
        description="Target PostgreSQL schema for vector data"
    )

    create_spatial_indexes: bool = Field(
        default=True,
        description="Automatically create spatial indexes on geometry columns"
    )

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(
            pickle_container=os.environ.get("VECTOR_PICKLE_CONTAINER", "rmhazuregeotemp"),
            pickle_prefix=os.environ.get("VECTOR_PICKLE_PREFIX", "temp/vector_etl"),
            default_chunk_size=int(os.environ.get("VECTOR_DEFAULT_CHUNK_SIZE", "1000")),
            auto_chunk_sizing=os.environ.get("VECTOR_AUTO_CHUNK_SIZING", "true").lower() == "true",
            target_schema=os.environ.get("VECTOR_TARGET_SCHEMA", "geo"),
            create_spatial_indexes=os.environ.get("VECTOR_CREATE_SPATIAL_INDEXES", "true").lower() == "true"
        )
